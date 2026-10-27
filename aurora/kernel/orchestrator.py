"""ExecutionOrchestrator（P0-B1，离线）。

铁律（对应用户验收门禁）：
1. 同一 Intent 重放不重复下单（intent_id 主键 + ledger-first）。
2. SUBMIT_UNKNOWN 禁止自动重提；恢复时必须先 query_order 查事实。
3. 部分成交按实际成交量建立保护。
4. 保护失败 → reduceOnly 定向紧急平仓 → 验证归零 → Kill Switch。
5. 平仓结果未知 → CLOSE_UNKNOWN → RECOVERY_REQUIRED + Kill Switch。
6. 持仓事实 UNKNOWN 禁止新开仓。
7. Kill Switch 持久化，重启后仍生效。
8. 启动先 recover()（对账 + 解决未决），才允许开仓。

G0-4B（执行事实真源）补充铁律：
9. 保护数量来自权威成交聚合/仓位事实；入场 ACK executedQty 只是早期观察值，
   绝不是保护数量真源；0 < protection_qty <= confirmed_position_qty。
10. 紧急平仓的尝试/拒绝/未知/确认四态分离；只有权威成交或仓位归零事实
    才产生 EMERGENCY_CLOSE_CONFIRMED；"调用过 close" ≠ "已执行"。
11. 强制腿 SL 保护价缺失/非法 → OPEN DENIED；不存在 99/101 哨兵保护价。
"""
import math
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from .coverage import compute_protection_status
from .ledger import CLOSE_PROVENANCE_UNKNOWN, Ledger, PositionFactState
from .port import (
    CancelUnknownError,
    Fill,
    OrderKind,
    OrderRejectedError,
    OrderRequest,
    SubmitUnknownError,
)
from .state_machine import IntentState, Transition, utc_now


def _valid_price(px: Any) -> bool:
    """合法保护触发价：有限正数。0/负数/NaN/None 都不是价格。"""
    return (
        isinstance(px, (int, float))
        and not isinstance(px, bool)
        and math.isfinite(px)
        and float(px) > 0
    )


EXECUTION_QTY_DRIFT = "EXECUTION_QTY_DRIFT"
EMERGENCY_CLOSE_ATTEMPTED = "EMERGENCY_CLOSE_ATTEMPTED"
EMERGENCY_CLOSE_REJECTED = "EMERGENCY_CLOSE_REJECTED"
EMERGENCY_CLOSE_UNKNOWN = "EMERGENCY_CLOSE_UNKNOWN"
EMERGENCY_CLOSE_CONFIRMED = "EMERGENCY_CLOSE_CONFIRMED"
# B2：close_outcome → kill 理由标签。NOT_ZERO（平仓单成交但仓位未归零）
# 属于"未确认平仓"，与 UNKNOWN 同级，不得写成 CONFIRMED。
_EMERGENCY_OUTCOME_LABELS = {
    "CONFIRMED": EMERGENCY_CLOSE_CONFIRMED,
    "REJECTED": EMERGENCY_CLOSE_REJECTED,
    "UNKNOWN": EMERGENCY_CLOSE_UNKNOWN,
    "NOT_ZERO": EMERGENCY_CLOSE_UNKNOWN,
}
_QTY_EPS = 1e-9


class Orchestrator:
    def __init__(self, ledger: Ledger, exchange, symbol: str = "BTCUSDT", instance_id: str = "orch"):
        self.ledger = ledger
        self.exchange = exchange
        self.symbol = symbol
        self.instance_id = instance_id
        self._protect_px: Dict[str, Any] = {}

    # ---------- 公共 API ----------

    def recover(self) -> Dict[str, Any]:
        """启动恢复：解决未决订单 + 以交易所为真源重建持仓事实。"""
        report = {"resolved": [], "unresolved": [], "kill_engaged": False}

        # BOOT-DRIFT：先快照账本证据，再对照仓位级独立查询结果。
        pre_fact = self.ledger.get_position_fact(self.symbol)
        pre_intents = {i["intent_id"]: i["state"] for i in self.ledger.list_intents()}

        for order in self.ledger.pending_orders():
            intent_id = order["intent_id"]
            cid = order["client_order_id"]
            fact = self._safe_query_order(cid)
            if fact is None:
                report["unresolved"].append({
                    "client_order_id": cid,
                    "order_kind": order["order_kind"],
                    "fact": "QUERY_FAILED",
                })
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.UNKNOWN,
                    source="recovery", note=f"query failed {cid}")
                continue
            entry = {
                "client_order_id": cid,
                "order_kind": order["order_kind"],
                "fact": fact.status,
            }

            if order["order_kind"] == "ENTRY":
                if fact.status == "NOT_FOUND":
                    self.ledger.update_order(cid, state="REJECTED")
                    self.ledger.transition_intent(
                        intent_id, IntentState.REJECTED,
                        f"recovery: order not found on exchange", correlation_id=intent_id)
                    report["resolved"].append(entry)
                elif fact.status in ("FILLED", "PARTIALLY_FILLED"):
                    # 订单行事实同步：状态与成交量都以交易所查询为准
                    self.ledger.update_order(
                        cid,
                        state="FILLED" if fact.status == "FILLED" else "PARTIALLY_FILLED",
                        filled_qty=fact.filled_qty, avg_price=fact.avg_price)
                    self._apply_fills(cid)
                    self.ledger.sync_order_projection_from_fills(cid)
                    agg = self.ledger.fills_aggregate(cid)["qty"]
                    intent = self.ledger.get_intent(intent_id)
                    if intent and IntentState(intent["state"]) in (
                        IntentState.SUBMITTING, IntentState.SUBMIT_UNKNOWN,
                        IntentState.ACKNOWLEDGED, IntentState.PARTIALLY_FILLED,
                    ):
                        self.ledger.transition_intent(
                            intent_id, IntentState.FILLED_UNPROTECTED,
                            f"recovery: entry {fact.status} "
                            f"(fill_aggregate={agg}; query.executedQty={fact.filled_qty} observation)",
                            correlation_id=intent_id)
                        self._ensure_protection(intent_id)
                    report["resolved"].append(entry)
                else:  # NEW / CANCELLED 之外的未知停留
                    report["unresolved"].append(entry)
                    self.ledger.set_position_fact(
                        self.symbol, PositionFactState.UNKNOWN,
                        source="recovery", note=f"entry pending {cid}")

            elif order["order_kind"] in ("STOP_LOSS", "TAKE_PROFIT"):
                intent = self.ledger.get_intent(intent_id)
                state = IntentState(intent["state"]) if intent else None
                if fact.status == "NOT_FOUND":
                    self.ledger.update_order(cid, state="REJECTED")
                    if state in (IntentState.PROTECTION_SUBMITTING, IntentState.FILLED_UNPROTECTED):
                        self.ledger.transition_intent(
                            intent_id, IntentState.PROTECTION_FAILED,
                            f"recovery: protection order {cid} not found",
                            correlation_id=intent_id)
                        self._emergency_close(intent_id, trigger="recovery protection missing")
                    elif state == IntentState.RECOVERY_REQUIRED and not self._exchange_flat():
                        self._emergency_close(intent_id, trigger="recovery protection missing")
                elif fact.status == "NEW":
                    self.ledger.update_order(cid, state="ACTIVE")
                    if state == IntentState.PROTECTION_SUBMITTING:
                        self.ledger.transition_intent(
                            intent_id, IntentState.PROTECTED,
                            f"recovery: protection confirmed {cid}", correlation_id=intent_id)
                    report["resolved"].append(entry)
                elif fact.status in ("FILLED", "PARTIALLY_FILLED"):
                    self.ledger.update_order(
                        cid, state="FILLED",
                        filled_qty=fact.filled_qty, avg_price=fact.avg_price)
                    self._apply_fills(cid)
                    if state == IntentState.PROTECTION_SUBMITTING:
                        self.ledger.transition_intent(
                            intent_id, IntentState.PROTECTED,
                            f"recovery: protection confirmed {cid}", correlation_id=intent_id)
                    report["resolved"].append(entry)
                elif fact.status in ("TRIGGERED", "FINISHED"):
                    self._apply_fills(cid)
                    fill_state = self._protection_fill_state(order)
                    if fill_state is not None:
                        self.ledger.update_order(cid, state=fill_state)
                    report["unresolved"].append({
                        **entry,
                        "reason": ("authoritative fill recorded; awaits position reconciliation"
                                   if fill_state else
                                   "algo terminal/triggered without authoritative fill"),
                    })
                else:
                    # TRIGGERED / FINISHED / EXPIRED / CANCELLED / UNKNOWN：
                    # 状态名不等于成交或平仓事实；保持未决，等待 fill/position 证据。
                    self.ledger.update_order(cid, state=fact.status)
                    report["unresolved"].append({
                        **entry,
                        "reason": "non-fill status; protection leg awaits fill/position evidence",
                    })

            elif order["order_kind"] == "CLOSE":
                if fact.status == "FILLED":
                    # 订单行事实同步 + 成交明细入账
                    self.ledger.update_order(
                        cid, state="FILLED",
                        filled_qty=fact.filled_qty, avg_price=fact.avg_price)
                    self._apply_fills(cid)
                    intent = self.ledger.get_intent(intent_id)
                    state = IntentState(intent["state"]) if intent else None
                    # 合法收敛路径按当前状态选择：RECOVERY_REQUIRED 只能直达
                    # RECONCILED；CLOSING/CLOSE_UNKNOWN 经 CLOSED 再 RECONCILED
                    if state == IntentState.RECOVERY_REQUIRED:
                        self.ledger.transition_intent(
                            intent_id, IntentState.RECONCILED,
                            f"recovery: close confirmed {cid} (flat verified)",
                            correlation_id=intent_id)
                    else:
                        self.ledger.transition_intent(
                            intent_id, IntentState.CLOSED,
                            f"recovery: close confirmed {cid}", correlation_id=intent_id)
                        self.ledger.transition_intent(
                            intent_id, IntentState.RECONCILED,
                            "recovery: ledger matches exchange (flat)", correlation_id=intent_id)
                    report["resolved"].append(entry)
                elif self._exchange_flat():
                    # 仓位已空 ≠ 本 CLOSE 单成交。禁止把订单标成 FILLED 或补造 SELL。
                    self._record_close_provenance_unknown(
                        report, reason=f"exchange flat; close {cid} has no fill")
                elif fact.status == "NOT_FOUND" and not self._exchange_flat():
                    intent = self.ledger.get_intent(intent_id)
                    # 幂等恢复：已在 RECOVERY_REQUIRED 则不重复自环转移
                    if intent and IntentState(intent["state"]) in (
                        IntentState.CLOSING, IntentState.CLOSE_UNKNOWN,
                    ):
                        self.ledger.transition_intent(
                            intent_id, IntentState.RECOVERY_REQUIRED,
                            f"recovery: close {cid} not found and position still open",
                            correlation_id=intent_id)
                    self.ledger.engage_kill(f"recovery: close unknown {cid}")
                    self.ledger.set_position_fact(
                        self.symbol, PositionFactState.UNKNOWN,
                        source="recovery", note=f"close unknown {cid}")
                    report["unresolved"].append(entry)
                else:
                    report["unresolved"].append(entry)

        self._refresh_position_fact()
        self._reconcile_protected_intents()
        # 仍处于 PROTECTED 的意图：按覆盖口径核对并补足/修复
        for intent in self.ledger.list_intents(states=[IntentState.PROTECTED.value]):
            synced = self.sync_protection(intent["intent_id"])
            if not synced.get("success"):
                report["unresolved"].append({
                    "intent_id": intent["intent_id"],
                    "fact": "QUERY_FAILED",
                    "reason": synced.get("reason"),
                })
        # 崩溃可能遗留在 DEGRADED 的意图：从当前事实幂等续修
        for intent in self.ledger.list_intents(
                states=[IntentState.PROTECTION_DEGRADED.value]):
            self._repair_protection(intent["intent_id"])
        # G0-4C C1：FILLED_UNPROTECTED 不是可忽略状态——交易所确认仍有仓位时
        # 必须进入保护生命周期恢复（识别已有保护/补齐差额/重建或安全熔断），
        # 重提交永远以权威"确认不存在"证据为前提（C2）。
        for intent in self.ledger.list_intents(states=[
            IntentState.FILLED_UNPROTECTED.value,
            IntentState.PROTECTION_SUBMITTING.value,
            IntentState.PARTIALLY_FILLED.value,
        ]):
            entry = self._recover_protection_lifecycle(intent["intent_id"])
            if entry is not None:
                report["unresolved"].append(entry)
        self._boot_position_audit(report, pre_fact, pre_intents)
        # G0-4C C6：仓位已空但 ACTIVE 保护腿残留 → ORPHAN_PROTECTION
        # fail-closed。残留条件单未来可能触发并新建反向风险；本刀只保证
        # 发现与熔断新增风险，不自动撤销（撤销属于真实协议执行阶段）。
        self._audit_orphan_protection(report)
        # 持久化 RECOVERY_REQUIRED 本身就是尚未收敛事实。即使本轮没有
        # pending order 可查询，也不得以空 unresolved 报告制造确定性。
        for intent in self.ledger.list_intents(
                states=[IntentState.RECOVERY_REQUIRED.value]):
            if not any(e.get("intent_id") == intent["intent_id"]
                       for e in report["unresolved"]):
                report["unresolved"].append({
                    "intent_id": intent["intent_id"],
                    "fact": "RECOVERY_REQUIRED",
                    "reason": "persisted recovery state has not converged",
                })
        kill = self.ledger.kill_state()
        report["kill_engaged"] = bool(kill["engaged"])
        fact = self.ledger.get_position_fact(self.symbol)
        report["position_fact"] = fact["state"] if fact else None
        return report

    def _boot_position_audit(
        self, report: Dict[str, Any], pre_fact: Optional[Dict[str, Any]],
        pre_intents: Dict[str, str],
    ) -> None:
        """BOOT-DRIFT：交易所事实必须由账本证据解释，否则不认领、不误平。

        - 账本完全无记录而交易所有仓 → UNKNOWN + 阻断新增风险；
        - 账本 KNOWN_OPEN 而交易所确认空仓且本轮无成交/平仓证据 → UNKNOWN；
        - 查询失败/不完整已由 _refresh_position_fact 标 UNKNOWN，这里不重复。
        """
        fact = self.ledger.get_position_fact(self.symbol)
        if fact is None or fact["state"] == PositionFactState.UNKNOWN.value:
            # 查询失败/不完整（含多腿模糊）已是 UNKNOWN；确保恢复报告
            # 对调用链显式未完成，不能只靠下游各自读 fact。
            if not report["unresolved"]:
                report["unresolved"].append({
                    "fact": "POSITION_FACT_UNKNOWN",
                    "reason": "exchange position query failed or incomplete",
                })
            return
        resolved_fills = any(
            e.get("fact") in ("FILLED", "PARTIALLY_FILLED")
            for e in report["resolved"]
        )
        # 本轮恢复中确实有 intent 被收敛到终态，也算"账本解释得通"的证据
        # （交易所侧 SL/TP 触发走的 _reconcile_protected_intents 不进 resolved 列表）。
        reconciled_this_run = any(
            i["state"] in (IntentState.RECONCILED.value, IntentState.CLOSED.value)
            and pre_intents.get(i["intent_id"]) not in (
                IntentState.RECONCILED.value, IntentState.CLOSED.value,
            )
            for i in self.ledger.list_intents()
        )
        close_evidence = resolved_fills or reconciled_this_run
        # UNKNOWN 的 fact 行只是"不知道"，不是持仓归属证据。
        had_ledger_evidence = (
            pre_fact is not None
            and pre_fact["state"] != PositionFactState.UNKNOWN.value
        ) or bool(pre_intents)
        if fact["state"] == PositionFactState.KNOWN_OPEN.value:
            if not had_ledger_evidence and not close_evidence:
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.UNKNOWN, source="boot-audit",
                    note="BOOT-DRIFT: exchange position has no ledger evidence; not adopted")
                report["unresolved"].append({
                    "fact": "BOOT_DRIFT",
                    "reason": "exchange open, ledger has no intent/order/position record",
                })
        elif fact["state"] == PositionFactState.KNOWN_FLAT.value:
            unexplained = (not close_evidence) and (
                (pre_fact is not None
                 and pre_fact["state"] == PositionFactState.KNOWN_OPEN.value)
                or (pre_fact is not None
                    and pre_fact.get("source") == CLOSE_PROVENANCE_UNKNOWN)
            )
            if unexplained:
                self._record_close_provenance_unknown(
                    report,
                    reason="exchange flat; no matching close order/fill")

    def open_position(
        self, side: str, quantity: float,
        intent_id: Optional[str] = None, reason: str = "manual",
        stop_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        kill = self.ledger.kill_state()
        if kill["engaged"]:
            return self._refuse(f"kill switch engaged: {kill['reason']}")

        # Fix 2：未解析 fill 标志 → 阻断新增风险（不阻减仓——
        # close_position 不查此标志）
        try:
            unresolved = self.ledger.unresolved_fill_ids()
        except Exception:
            unresolved = ["<READ_ERROR>"]  # fail-closed
        if unresolved == ["<READ_ERROR>"]:
            return self._refuse(
                "unresolved-fill flag read error; new opens blocked"
                " (fail-closed)")
        if unresolved:
            return self._refuse(
                f"unresolved fills present ({len(unresolved)}):"
                f" {unresolved[:3]}; new opens blocked until resolved")
        try:
            pnl_bad = self.ledger.pnl_unreliable(self.symbol)
        except Exception:
            pnl_bad = True  # fail-closed：读不到就当不可靠
        if pnl_bad:
            return self._refuse(
                "pnl unreliable for symbol; new opens blocked")

        # B3：强制腿保护价必须在开仓前存在。没有明确保护合同，不允许开仓；
        # 绝不自动制造"看起来有数字"的哨兵保护价（99/101 已废除）。
        if not _valid_price(stop_price):
            return self._refuse(
                "OPEN DENIED: mandatory SL protection price missing/invalid;"
                " no intent created, no order sent"
            )

        # 保护修复期间禁止一切新开仓（DEGRADED 存在即拒绝）
        degraded = self.ledger.list_intents(states=[IntentState.PROTECTION_DEGRADED.value])
        if degraded:
            return self._refuse(
                f"protection repair in progress ({degraded[0]['intent_id']}); "
                "new opens forbidden")

        # 幂等优先：重放/抢占判定必须在任何市场状态检查之前
        intent_id = intent_id or f"AURORA-{uuid.uuid4().hex[:12]}"
        if not self.ledger.create_intent(intent_id, self.symbol, side, quantity):
            existing = self.ledger.get_intent(intent_id)
            if (
                existing
                and existing["state"] == IntentState.INTENT_CREATED.value
                and existing["claimed_by"]
                and existing["claimed_by"] != self.instance_id
            ):
                return self._refuse(f"intent {intent_id} claimed by another executor")
            return {  # 重放：绝不二次下单
                "success": False, "replay": True, "intent_id": intent_id,
                "state": existing["state"] if existing else "UNKNOWN",
                "reason": "intent already exists; no duplicate order",
            }
        if not self.ledger.claim_intent(intent_id, self.instance_id):
            return self._refuse(f"intent {intent_id} claimed by another executor")

        # 未决提交未核验前，不得新增风险（BOOT-DRIFT 原则同样适用于订单层）。
        if self.ledger.pending_orders():
            self.ledger.transition_intent(
                intent_id, IntentState.REJECTED,
                "pending orders unresolved; run recover() before new opens",
                correlation_id=intent_id)
            return self._refuse(
                "pending orders unresolved; run recover() before new opens")

        fact = self.ledger.get_position_fact(self.symbol)
        if fact is None or fact["state"] == PositionFactState.UNKNOWN.value:
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="open_position", note="fact missing/unknown; run recover()")
            self.ledger.transition_intent(
                intent_id, IntentState.REJECTED,
                "position fact UNKNOWN; new opens forbidden until recover()",
                correlation_id=intent_id)
            return self._refuse("position fact UNKNOWN; new opens forbidden until recover()")
        if fact["state"] == PositionFactState.KNOWN_OPEN.value:
            self.ledger.transition_intent(
                intent_id, IntentState.REJECTED,
                "position already open", correlation_id=intent_id)
            return self._refuse("position already open")
        # CLOSE_PROVENANCE_UNKNOWN 是证据残留，不是永久开仓禁令。
        # 当前事故运行锁（kill / INCIDENT_LOCKED）另层拒绝新风险。
        # 未来 incident disposition 可以在残留仍 OPEN 时批准新的 qualification。

        # TP 是可选腿：价格缺失时跳过 TP（NOT_CONFIGURED），不制造哨兵价。
        # SL 已在开仓前校验；写入账本，重启 recover 不得靠 99/101 回填。
        tp_stored = (
            float(take_profit_price) if _valid_price(take_profit_price) else None
        )
        self.ledger.set_intent_protect_prices(
            intent_id, float(stop_price), tp_stored)
        self._protect_px[intent_id] = (float(stop_price), tp_stored)
        try:
            return self._submit_entry(intent_id, side, quantity, reason)
        except _LedgerWriteFailed as exc:
            # ledger-first 不变量：账本写不进去就没有订单被提交
            return self._refuse(f"ledger pre-submit write failed; no order sent: {exc}")

    def close_position(
        self, reason: str = "manual",
        intent_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        fact = self.ledger.get_position_fact(self.symbol)
        if fact is None or fact["state"] != PositionFactState.KNOWN_OPEN.value:
            return self._refuse("close requires KNOWN_OPEN position fact")
        kill = self.ledger.kill_state()
        intent_id = intent_id or f"AURORA-CLOSE-{uuid.uuid4().hex[:12]}"
        self.ledger.create_intent(intent_id, self.symbol, "CLOSE", fact["qty"])
        if not self.ledger.claim_intent(intent_id, self.instance_id):
            return self._refuse(f"close intent {intent_id} claimed by another executor")
        self.ledger.transition_intent(
            intent_id, IntentState.SUBMITTING, f"close begin ({reason}); kill={bool(kill['engaged'])}",
            correlation_id=intent_id)
        self.ledger.transition_intent(
            intent_id, IntentState.CLOSING, f"closing ({reason})", correlation_id=intent_id)
        return self._submit_close(
            intent_id, reason, emergency=False, client_order_id=client_order_id)

    # ---------- 内部：开仓与保护 ----------

    def _submit_entry(self, intent_id: str, side: str, quantity: float, reason: str) -> Dict[str, Any]:
        self.ledger.transition_intent(
            intent_id, IntentState.SUBMITTING, f"entry submit ({reason})",
            correlation_id=intent_id)
        cid = f"{intent_id}-ENTRY"
        try:
            self.ledger.record_order_submitting(
                client_order_id=cid, intent_id=intent_id, order_kind="ENTRY",
                side="BUY" if side == "LONG" else "SELL", position_side=side,
                quantity=quantity,
            )
        except Exception as exc:  # 账本失败 → 绝不提交订单
            raise _LedgerWriteFailed(str(exc)) from exc

        req = OrderRequest(
            client_order_id=cid, symbol=self.symbol, order_kind=OrderKind.ENTRY,
            side="BUY" if side == "LONG" else "SELL", position_side=side, quantity=quantity,
        )
        try:
            ack = self.exchange.submit_order(req)
        except OrderRejectedError as exc:
            self.ledger.update_order(cid, state="REJECTED")
            self.ledger.transition_intent(
                intent_id, IntentState.REJECTED, f"entry rejected: {exc}",
                correlation_id=intent_id)
            return {"success": False, "intent_id": intent_id, "state": "REJECTED",
                    "reason": str(exc)}
        except SubmitUnknownError as exc:
            self.ledger.update_order(cid, state="SUBMIT_UNKNOWN")
            self.ledger.transition_intent(
                intent_id, IntentState.SUBMIT_UNKNOWN,
                "entry result unknown; resubmission forbidden until queried",
                correlation_id=intent_id)
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="entry", note=f"submit unknown {cid}")
            return {"success": False, "intent_id": intent_id, "state": "SUBMIT_UNKNOWN",
                    "reason": str(exc)}

        self.ledger.update_order(
            cid, state="FILLED" if ack.status == "FILLED" else "PARTIALLY_FILLED",
            exchange_order_id=ack.exchange_order_id,
            filled_qty=ack.filled_qty, avg_price=ack.avg_price)
        self._apply_fills(cid)
        # ACK.executedQty 只是早期观察；保护数量必须在成交入账后再取真源。
        self.ledger.sync_order_projection_from_fills(cid)
        agg = self.ledger.fills_aggregate(cid)["qty"]

        if ack.status == "PARTIALLY_FILLED":
            self.ledger.transition_intent(
                intent_id, IntentState.PARTIALLY_FILLED,
                f"entry partial fill_aggregate={agg} ack={ack.filled_qty}",
                correlation_id=intent_id)
        self.ledger.transition_intent(
            intent_id, IntentState.FILLED_UNPROTECTED,
            f"entry fill_aggregate={agg}; ack.executedQty={ack.filled_qty} (observation only); "
            "protection required",
            correlation_id=intent_id)
        return self._ensure_protection(intent_id)

    def _protection_sizing(self, intent_id: str) -> Dict[str, Any]:
        """保护数量真源（G0-4B B1）。

        优先级：权威成交聚合 → 已确认仓位事实 / 交易所仓位 → 其他权威执行事实。
        入场 ACK.executedQty 只是早期观察，绝不作为 sizing 真源。
        fills 与仓位不一致 → EXECUTION_QTY_DRIFT，不得取 max/min 继续挂保护。
        """
        cid = f"{intent_id}-ENTRY"
        self._apply_fills(cid)
        self.ledger.sync_order_projection_from_fills(cid)
        fill_qty = self.ledger.fills_aggregate(cid)["qty"]
        pos = self._safe_position()
        fact = self.ledger.get_position_fact(self.symbol)
        position_qty = None
        position_side = None
        if pos is not None:
            position_qty = abs(pos.signed_qty)
            if position_qty > _QTY_EPS:
                position_side = "LONG" if pos.signed_qty > 0 else "SHORT"
        elif fact is not None and fact["state"] == PositionFactState.KNOWN_OPEN.value:
            position_qty = abs(float(fact["qty"] or 0.0))
            position_side = fact.get("side")
        else:
            return {"error": "POSITION_UNKNOWN", "fill_qty": fill_qty}

        if fill_qty > _QTY_EPS and position_qty is not None:
            if abs(fill_qty - position_qty) > _QTY_EPS:
                return {
                    "error": EXECUTION_QTY_DRIFT,
                    "fill_qty": fill_qty,
                    "position_qty": position_qty,
                }

        if fill_qty > _QTY_EPS:
            qty = fill_qty
        elif position_qty is not None and position_qty > _QTY_EPS:
            qty = position_qty
        else:
            return {"error": "PROTECTION_QTY_ZERO",
                    "fill_qty": fill_qty, "position_qty": position_qty}

        if position_qty is not None and qty > position_qty + _QTY_EPS:
            return {"error": EXECUTION_QTY_DRIFT,
                    "fill_qty": fill_qty, "position_qty": position_qty}

        intent = self.ledger.get_intent(intent_id)
        side = intent["side"] if intent else position_side
        if position_side and side and position_side != side:
            return {"error": EXECUTION_QTY_DRIFT,
                    "fill_qty": fill_qty, "position_qty": position_qty}
        return {
            "qty": qty, "side": side,
            "position_qty": position_qty, "fill_qty": fill_qty,
        }

    def _entry_price_for_protection(self, intent_id: str) -> Optional[float]:
        cid = f"{intent_id}-ENTRY"
        agg = self.ledger.fills_aggregate(cid)
        if agg["qty"] > _QTY_EPS and _valid_price(agg.get("avg_price")):
            return float(agg["avg_price"])
        order = self.ledger.get_order(cid)
        if order is not None and _valid_price(order.get("avg_price")):
            return float(order["avg_price"])
        pos = self._safe_position()
        if pos is not None and _valid_price(getattr(pos, "entry_price", None)):
            return float(pos.entry_price)
        return None

    def _ensure_protection(self, intent_id: str) -> Dict[str, Any]:
        intent = self.ledger.get_intent(intent_id)
        side = intent["side"]
        sizing = self._protection_sizing(intent_id)
        if sizing.get("error"):
            err = sizing["error"]
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED,
                f"protection sizing failed: {err}", correlation_id=intent_id)
            self.ledger.engage_kill(f"{err} {intent_id}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="protection-sizing", note=err)
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "halt": True,
                    "reason": err, "sizing": sizing}

        filled_qty = sizing["qty"]
        self.ledger.transition_intent(
            intent_id, IntentState.PROTECTION_SUBMITTING,
            f"protection submit for fill/position qty={filled_qty}",
            correlation_id=intent_id)

        sl_px, tp_px = self._protect_prices(intent_id)
        if not _valid_price(sl_px):
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED,
                "mandatory SL price unavailable; sentinels removed (G0-4B)",
                correlation_id=intent_id)
            self.ledger.engage_kill(f"mandatory SL price missing {intent_id}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="protection", note=f"SL price missing {intent_id}")
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "halt": True,
                    "reason": "mandatory SL price missing"}
        # 强制腿 SL：失败 = 裸奔仓位 → 紧急平仓
        try:
            self._place_protection_leg(
                intent_id, self._leg_cid(intent_id, "SL"),
                OrderKind.STOP_LOSS, side, filled_qty, stop_price=float(sl_px))
        except SubmitUnknownError as exc:
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED,
                f"mandatory SL submit unknown; query first: {exc}",
                correlation_id=intent_id)
            self.ledger.engage_kill(f"mandatory SL submit unknown {intent_id}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="protection", note=f"SL submit unknown {intent_id}")
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "halt": True,
                    "reason": f"mandatory SL submit unknown: {exc}"}
        except OrderRejectedError as exc:
            self.ledger.transition_intent(
                intent_id, IntentState.PROTECTION_FAILED,
                f"mandatory SL rejected: {exc}", correlation_id=intent_id)
            return self._emergency_close(intent_id, trigger="mandatory SL failed")

        # 可选腿 TP：价格缺失/无效 = 明确不挂 TP（NOT_CONFIGURED →
        # safe_but_incomplete），绝不制造哨兵保护价；仅 TP 失败不紧急平仓。
        tp_ok = False
        tp_not_configured = False
        if _valid_price(tp_px):
            try:
                self._place_protection_leg(
                    intent_id, self._leg_cid(intent_id, "TP"),
                    OrderKind.TAKE_PROFIT, side, filled_qty, stop_price=float(tp_px))
                tp_ok = True
            except (OrderRejectedError, SubmitUnknownError):
                tp_ok = False
        else:
            tp_not_configured = True

        self.ledger.transition_intent(
            intent_id, IntentState.PROTECTED,
            f"SL confirmed for qty={filled_qty}"
            + ("" if tp_ok else "; TP incomplete (safe_but_incomplete)")
            + ("; TP NOT_CONFIGURED" if tp_not_configured else ""),
            correlation_id=intent_id)
        self.ledger.set_position_fact(
            self.symbol, PositionFactState.KNOWN_OPEN, qty=filled_qty, side=side,
            source="protection", note="protected" if tp_ok else "sl-only")
        return {"success": True, "intent_id": intent_id, "state": "PROTECTED",
                "protected_qty": filled_qty,
                "tp_coverage": filled_qty if tp_ok else 0.0,
                "safe_but_incomplete": not tp_ok}

    def _emergency_close(self, intent_id: str, trigger: str) -> Dict[str, Any]:
        self.ledger.transition_intent(
            intent_id, IntentState.CLOSING,
            f"{EMERGENCY_CLOSE_ATTEMPTED} ({trigger})", correlation_id=intent_id)
        result = self._submit_close(intent_id, trigger, emergency=True)
        label = _EMERGENCY_OUTCOME_LABELS.get(
            str(result.get("close_outcome") or ""), EMERGENCY_CLOSE_ATTEMPTED)
        self.ledger.engage_kill(f"{label}: {trigger} ({intent_id})")
        return {
            **result, "success": False, "halt": True,
            "reason": f"{trigger}; {label}; kill switch engaged",
        }

    def _submit_close(
        self, intent_id: str, reason: str, emergency: bool,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pos = self._safe_position()
        if pos is None:
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED,
                f"close blocked: exchange position UNKNOWN ({reason})",
                correlation_id=intent_id)
            self.ledger.engage_kill(f"position UNKNOWN during close {intent_id}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN, source="close", note="unknown")
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "close_outcome": "UNKNOWN",
                    "reason": "position UNKNOWN"}

        qty = abs(pos.signed_qty)
        side = "LONG" if pos.signed_qty > 0 else "SHORT"
        if qty == 0:
            self.ledger.transition_intent(
                intent_id, IntentState.CLOSED, f"already flat ({reason})",
                correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.RECONCILED, "flat confirmed", correlation_id=intent_id)
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.KNOWN_FLAT, source="close", note=reason)
            return {"success": True, "intent_id": intent_id, "state": "RECONCILED",
                    "close_outcome": "CONFIRMED",
                    "reason": "already flat"}

        tag = "CLOSE-EMG" if emergency else "CLOSE"
        cid = client_order_id or f"{intent_id}-{tag}"
        try:
            self.ledger.record_order_submitting(
                client_order_id=cid, intent_id=intent_id, order_kind="CLOSE",
                side="SELL" if side == "LONG" else "BUY", position_side=side,
                quantity=qty, reduce_only=True,
            )
        except Exception as exc:
            raise _LedgerWriteFailed(str(exc)) from exc

        req = OrderRequest(
            client_order_id=cid, symbol=self.symbol, order_kind=OrderKind.CLOSE,
            side="SELL" if side == "LONG" else "BUY", position_side=side,
            quantity=qty, reduce_only=True,
        )
        try:
            ack = self.exchange.submit_order(req)
        except SubmitUnknownError as exc:
            self.ledger.update_order(cid, state="CLOSE_UNKNOWN")
            self.ledger.transition_intent(
                intent_id, IntentState.CLOSE_UNKNOWN,
                f"close result unknown ({reason})", correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED,
                "close unknown requires fact query", correlation_id=intent_id)
            self.ledger.engage_kill(f"close unknown {cid}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN, source="close", note=cid)
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "close_outcome": "UNKNOWN",
                    "reason": str(exc)}
        except OrderRejectedError as exc:
            self.ledger.update_order(cid, state="REJECTED")
            # 拒单是确定性事实：仓位未平。合法路径 CLOSING→CLOSE_UNKNOWN→
            # RECOVERY_REQUIRED（状态机禁止 CLOSING 直跳 RECOVERY_REQUIRED）
            if IntentState(self.ledger.get_intent(intent_id)["state"]) == IntentState.CLOSING:
                self.ledger.transition_intent(
                    intent_id, IntentState.CLOSE_UNKNOWN,
                    f"close rejected (terminal fact: not filled)",
                    correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED,
                f"close rejected: {exc}", correlation_id=intent_id)
            self.ledger.engage_kill(f"close rejected {cid}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN, source="close", note=cid)
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "close_outcome": "REJECTED",
                    "reason": str(exc)}

        self.ledger.update_order(
            cid, exchange_order_id=ack.exchange_order_id)
        self._apply_fills(cid)
        close_fills = self.ledger.fills_aggregate(cid)["qty"]
        flat = self._exchange_flat()
        if close_fills <= _QTY_EPS and not flat:
            self.ledger.update_order(cid, state="CLOSE_UNKNOWN")
            self.ledger.transition_intent(
                intent_id, IntentState.CLOSE_UNKNOWN,
                f"close ack without fill or flatten fact ({reason})",
                correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED,
                "close unconfirmed: no authoritative close fill and position still open",
                correlation_id=intent_id)
            if not emergency:
                self.ledger.engage_kill(f"close unknown {cid}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN, source="close", note=cid)
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "close_outcome": "UNKNOWN",
                    "reason": "close ack is not a flatten fact"}

        if flat:
            self.ledger.transition_intent(
                intent_id, IntentState.CLOSED, f"close confirmed flat ({reason})",
                correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.RECONCILED, "ledger matches exchange",
                correlation_id=intent_id)
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.KNOWN_FLAT, source="close", note=reason)
            return {"success": True, "intent_id": intent_id, "state": "RECONCILED",
                    "close_outcome": "CONFIRMED"}

        self.ledger.transition_intent(
            intent_id, IntentState.RECOVERY_REQUIRED,
            "close fill present but position not zero", correlation_id=intent_id)
        if not emergency:
            self.ledger.engage_kill(f"post-close non-zero position {intent_id}")
        self.ledger.set_position_fact(
            self.symbol, PositionFactState.UNKNOWN, source="close", note="non-zero after close")
        return {"success": False, "intent_id": intent_id,
                "state": "RECOVERY_REQUIRED", "close_outcome": "NOT_ZERO",
                "reason": "position not zero after close"}

    # ---------- 内部：事实同步 ----------

    def _reconcile_protected_intents(self) -> None:
        """交易所侧 SL/TP 已触发（仓位在交易所消失）时，把账本收敛到 RECONCILED。

        这是"幽灵仓位"反向的处理：账本认为 PROTECTED，交易所已平。
        保护单的实际成交按 client_order_id 拉取入账，绝不凭空推断。
        OCO 语义（吸收自 NautilusTrader bracket 警告）：任一保护腿成交后，
        兄弟腿不保证被交易所自动撤销，必须按精确 ID 主动撤单。
        """
        pos = self._safe_position()
        if pos is None:
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="reconcile", note="exchange position query failed")
            return
        if abs(pos.signed_qty) >= 1e-12:
            return  # 交易所仍有仓位：不收敛

        for intent in self.ledger.list_intents(states=[IntentState.PROTECTED.value]):
            iid = intent["intent_id"]
            fired = []
            cancel_unknown = False
            for order in self.ledger.orders_for_intent(iid):
                if order["order_kind"] not in ("STOP_LOSS", "TAKE_PROFIT"):
                    continue
                cid = order["client_order_id"]
                fact = self._safe_query_order(cid)
                if fact is None:
                    self.ledger.engage_kill(
                        f"protection query failed after exchange close {cid}")
                    cancel_unknown = True
                    continue
                if fact.status == "FILLED":
                    self._apply_fills(cid)
                    self.ledger.update_order(
                        cid, state="FILLED", filled_qty=fact.filled_qty,
                        avg_price=fact.avg_price)
                    fired.append(order["order_kind"])
                elif fact.status in ("TRIGGERED", "FINISHED"):
                    self._apply_fills(cid)
                    fill_state = self._protection_fill_state(order)
                    if fill_state is None:
                        self.ledger.update_order(cid, state=fact.status)
                        self.ledger.engage_kill(
                            f"protection execution unverified {cid}: {fact.status}")
                        cancel_unknown = True
                    else:
                        self.ledger.update_order(cid, state=fill_state)
                        fired.append(order["order_kind"])
                elif fact.status == "NEW":
                    # OCO 兄弟腿撤销：仓位已平，残留保护单成为孤儿挂单。
                    # 撤单结果未知时无法确认孤儿已清除 → 熔断（fail-safe）
                    try:
                        if self.exchange.cancel_order(cid):
                            self.ledger.update_order(cid, state="CANCELLED")
                    except CancelUnknownError:
                        self.ledger.engage_kill(
                            f"sibling cancel unknown after exchange close {cid}")
                        cancel_unknown = True
                elif fact.status not in ("CANCELLED", "NOT_FOUND"):
                    self.ledger.update_order(cid, state=fact.status)
                    self.ledger.engage_kill(
                        f"protection execution unverified {cid}: {fact.status}")
                    cancel_unknown = True
            if cancel_unknown:
                self.ledger.transition_intent(
                    iid, IntentState.RECOVERY_REQUIRED,
                    f"exchange-side close detected but sibling cancel/query unknown"
                    f" ({'+'.join(fired) if fired else CLOSE_PROVENANCE_UNKNOWN})",
                    correlation_id=iid)
                self._record_close_provenance_unknown(
                    None, reason=f"exchange flat; sibling cancel/query unknown {iid}")
                continue
            if not fired:
                # G3: 若存在已成交并 reconciled 的独立 close intent，则原始
                # PROTECTED intent 的生命周期已经由该平仓行为解释清楚。
                # active position/order recovery 必须收敛为 RECONCILED；
                # 不能仅因 "原始 SL/TP 未触发" 就把整个系统拖回 RECOVERY_REQUIRED。
                independent_close = self._any_closed_intent_filled_close()
                if independent_close:
                    self.ledger.transition_intent(
                        iid, IntentState.CLOSING,
                        f"exchange flat via independent close {independent_close}",
                        correlation_id=iid)
                    self.ledger.transition_intent(
                        iid, IntentState.CLOSED,
                        "position closed by independent close intent",
                        correlation_id=iid)
                    self.ledger.transition_intent(
                        iid, IntentState.RECONCILED,
                        "ledger matches exchange after independent close",
                        correlation_id=iid)
                    self.ledger.set_position_fact(
                        self.symbol, PositionFactState.KNOWN_FLAT,
                        source="INDEPENDENT_CLOSE",
                        note=f"closed by {independent_close}")
                    continue
                self.ledger.transition_intent(
                    iid, IntentState.RECOVERY_REQUIRED,
                    f"{CLOSE_PROVENANCE_UNKNOWN}: exchange flat without matching fill",
                    correlation_id=iid)
                self._record_close_provenance_unknown(
                    None, reason="exchange flat without matching protection/close fill")
                continue
            self.ledger.transition_intent(
                iid, IntentState.CLOSING,
                f"exchange-side close detected ({'+'.join(fired) if fired else 'external close'})",
                correlation_id=iid)
            self.ledger.transition_intent(
                iid, IntentState.CLOSED, "already flat on exchange",
                correlation_id=iid)
            self.ledger.transition_intent(
                iid, IntentState.RECONCILED,
                "ledger matches exchange after SL/TP fired", correlation_id=iid)

    def sync_protection(self, intent_id: str) -> Dict[str, Any]:
        """按正确覆盖口径核对并修复保护（P0-B2.1）。

        口径见 aurora/kernel/coverage.py：SL/TP 按角色分片求和、禁止相加、
        禁止取 max；SL 为强制腿（mandatory），TP 不足=安全但不完整。
        - 覆盖足额 → 无操作；
        - 入场增量导致缺口（无保护腿已触发）→ 按角色差额补挂；
        - 保护腿已部分/全部触发且仓位有剩余 → PROTECTION_DEGRADED 修复流程。
        """
        intent = self.ledger.get_intent(intent_id)
        if intent is None:
            return self._refuse(f"intent {intent_id} not found")
        if IntentState(intent["state"]) not in (
            IntentState.PROTECTED, IntentState.PROTECTION_SUBMITTING,
            IntentState.PARTIALLY_FILLED, IntentState.FILLED_UNPROTECTED,
        ):
            return {"success": True, "intent_id": intent_id, "state": intent["state"],
                    "reason": "no protection sync needed in this state"}

        entry = self.ledger.get_order(f"{intent_id}-ENTRY")
        if entry is None:
            return self._refuse("no entry order")
        fact = self._safe_query_order(entry["client_order_id"])
        if fact is None:
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="protection-sync", note="entry query failed")
            return {"success": False, "intent_id": intent_id,
                    "reason": "order query failed"}
        if fact.status in ("FILLED", "PARTIALLY_FILLED"):
            self._apply_fills(entry["client_order_id"])
            self.ledger.update_order(
                entry["client_order_id"],
                state="FILLED" if fact.status == "FILLED" else "PARTIALLY_FILLED",
                filled_qty=fact.filled_qty, avg_price=fact.avg_price)

        # 同步保护腿事实（触发情况以交易所查询为准）
        any_fired = False
        for order in self.ledger.orders_for_intent(intent_id):
            if order["order_kind"] not in ("STOP_LOSS", "TAKE_PROFIT"):
                continue
            pf = self._safe_query_order(order["client_order_id"])
            if pf is None:
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.UNKNOWN,
                    source="protection-sync", note=f"query failed {order['client_order_id']}")
                return {"success": False, "intent_id": intent_id,
                        "reason": "order query failed"}
            if pf.status in ("FILLED", "PARTIALLY_FILLED"):
                any_fired = True
                self._apply_fills(order["client_order_id"])
                self.ledger.update_order(
                    order["client_order_id"], state=pf.status,
                    filled_qty=pf.filled_qty, avg_price=pf.avg_price)
            elif pf.status in ("TRIGGERED", "FINISHED"):
                self._apply_fills(order["client_order_id"])
                fill_state = self._protection_fill_state(order)
                if fill_state is None:
                    cid = order["client_order_id"]
                    self.ledger.update_order(cid, state=pf.status)
                    self.ledger.set_position_fact(
                        self.symbol, PositionFactState.UNKNOWN,
                        source="protection-sync",
                        note=f"protection execution unverified {cid}: {pf.status}")
                    return {"success": False, "intent_id": intent_id,
                            "reason": f"protection execution unverified {cid}: {pf.status}"}
                any_fired = True
                self.ledger.update_order(
                    order["client_order_id"], state=fill_state)
            elif pf.status == "CANCELLED":
                self.ledger.update_order(order["client_order_id"], state="CANCELLED")
            elif pf.status == "NEW":
                self.ledger.update_order(order["client_order_id"], state="ACTIVE")
            else:
                cid = order["client_order_id"]
                self.ledger.update_order(cid, state=pf.status)
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.UNKNOWN,
                    source="protection-sync",
                    note=f"protection execution unverified {cid}: {pf.status}")
                return {"success": False, "intent_id": intent_id,
                        "reason": f"protection execution unverified {cid}: {pf.status}"}

        pos = self._safe_position()
        exchange_qty = abs(pos.signed_qty) if pos is not None else None
        if exchange_qty is not None and exchange_qty < 1e-12:
            return {"success": True, "intent_id": intent_id,
                    "reason": "exchange flat; reconcile path handles"}

        status = compute_protection_status(
            self.ledger.orders_for_intent(intent_id), exchange_qty)
        if not status.position_known:
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="protection-sync", note="exchange position unknown")
            return {"success": False, "intent_id": intent_id,
                    "reason": "exchange position UNKNOWN; protection unverifiable"}

        # G0-4C C3/C4：超覆盖是危险合同，不是"保护更充分"。仓位缩减后
        # 旧保护失配必须走降级重建（撤旧腿、按实际仓位重建），不得继续
        # 宣称 VERIFIED，也不得保留可能反向执行的过量条件单。
        if exchange_qty is not None and status.sl_coverage > exchange_qty + _QTY_EPS:
            return self._repair_protection(intent_id)
        if status.protected_full:
            return {"success": True, "intent_id": intent_id,
                    "sl_coverage": status.sl_coverage,
                    "tp_coverage": status.tp_coverage,
                    "safe_but_incomplete": False}

        # 有保护腿已触发 → 必须走降级修复（不能在 fired 腿上做增量假设）
        if any_fired:
            return self._repair_protection(intent_id)

        # 纯增量缺口 → 按角色差额补挂（SL/TP 各自补到覆盖仓位）
        side = intent["side"]
        deficits = {
            "SL": max(0.0, round(exchange_qty - status.sl_coverage, 10)),
            "TP": max(0.0, round(exchange_qty - status.tp_coverage, 10)),
        }
        if deficits["SL"] <= 1e-12 and deficits["TP"] <= 1e-12:
            return {"success": True, "intent_id": intent_id,
                    "sl_coverage": status.sl_coverage,
                    "tp_coverage": status.tp_coverage,
                    "safe_but_incomplete": status.safe_but_incomplete}

        sl_px, tp_px = self._protect_prices(intent_id)
        # G0-4B：TP 价格缺失 = 维持 safe_but_incomplete（明确不挂 TP），
        # 绝不是需要紧急平仓的失败；SL 价格缺失才不能补、必须走失败路径。
        if deficits["SL"] > 1e-12 and not _valid_price(sl_px):
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED",
                    "reason": "SL top-up price unavailable; sentinels removed (G0-4B)"}
        tp_price_missing = not _valid_price(tp_px)

        for tag, kind, deficit in (
            ("SL-TOPUP", OrderKind.STOP_LOSS, deficits["SL"]),
            ("TP-TOPUP", OrderKind.TAKE_PROFIT, deficits["TP"]),
        ):
            if deficit <= 1e-12:
                continue
            if tag.startswith("TP"):
                if tp_price_missing:
                    continue  # 无 TP 价 → 明确跳过，保持 sl-only 覆盖
                topup_px = float(tp_px)
            else:
                topup_px = float(sl_px)
            cid = self._leg_cid(intent_id, tag)
            try:
                self._place_protection_leg(
                    intent_id, cid, kind, side, deficit,
                    stop_price=topup_px)
            except SubmitUnknownError as exc:
                current = IntentState(self.ledger.get_intent(intent_id)["state"])
                if current in (
                    IntentState.PROTECTED, IntentState.PROTECTION_SUBMITTING,
                    IntentState.FILLED_UNPROTECTED, IntentState.PARTIALLY_FILLED,
                ):
                    self.ledger.transition_intent(
                        intent_id, IntentState.RECOVERY_REQUIRED,
                        f"protection top-up submit unknown (deficit={deficit}): {exc}",
                        correlation_id=intent_id)
                self.ledger.engage_kill(f"protection top-up submit unknown {intent_id}")
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.UNKNOWN,
                    source="protection-sync", note=f"top-up unknown {cid}")
                return {"success": False, "intent_id": intent_id,
                        "state": "RECOVERY_REQUIRED",
                        "reason": f"protection top-up submit unknown: {exc}"}
            except OrderRejectedError:
                current = IntentState(self.ledger.get_intent(intent_id)["state"])
                if current in (IntentState.FILLED_UNPROTECTED,
                               IntentState.PROTECTION_SUBMITTING):
                    self.ledger.transition_intent(
                        intent_id, IntentState.PROTECTION_FAILED,
                        f"protection top-up rejected (deficit={deficit})",
                        correlation_id=intent_id)
                elif current == IntentState.PARTIALLY_FILLED:
                    self.ledger.transition_intent(
                        intent_id, IntentState.FILLED_UNPROTECTED,
                        "top-up rejected; position unprotected", correlation_id=intent_id)
                    self.ledger.transition_intent(
                        intent_id, IntentState.PROTECTION_FAILED,
                        f"protection top-up rejected (deficit={deficit})",
                        correlation_id=intent_id)
                return self._emergency_close(
                    intent_id, trigger="protection top-up failed")

        fresh = compute_protection_status(
            self.ledger.orders_for_intent(intent_id), exchange_qty)
        return {"success": True, "intent_id": intent_id,
                "sl_coverage": fresh.sl_coverage,
                "tp_coverage": fresh.tp_coverage,
                "topped_up": max(deficits.values()),
                "safe_but_incomplete": fresh.safe_but_incomplete}

    def _repair_protection(self, intent_id: str) -> Dict[str, Any]:
        """PROTECTION_DEGRADED 修复（P0-B2.2 竞态安全顺序）。

        检测部分成交 → DEGRADED → 精确撤销全部旧腿 → 等待每条腿明确终态
        → 拉取最新 fills → 拉取交易所实际仓位 →
          已平仓：不重建，直接对账收敛；
          仍持仓：先提交并确认 SL（强制），再提交可选 TP；
                  仅 TP 失败 = safe_but_incomplete，不触发紧急平仓。
        撤单结果未知 / 撤单后腿仍无明确终态 → RECOVERY_REQUIRED + Kill。
        """
        current = IntentState(self.ledger.get_intent(intent_id)["state"])
        if current == IntentState.PROTECTED:
            self.ledger.transition_intent(
                intent_id, IntentState.PROTECTION_DEGRADED,
                "protection coverage insufficient / leg fired with remainder",
                correlation_id=intent_id)

        # G0-4C：修复可从多个入口进入（DEGRADED / RECOVERY_REQUIRED /
        # FILLED_UNPROTECTED 溢出恢复）。同态不自环；合法转移照常落账。
        def _transition_idem(to_state: IntentState, reason: str) -> None:
            cur = IntentState(self.ledger.get_intent(intent_id)["state"])
            if cur == to_state:
                return
            self.ledger.transition_intent(
                intent_id, to_state, reason, correlation_id=intent_id)

        def _recovery(reason: str) -> Dict[str, Any]:
            _transition_idem(
                IntentState.RECOVERY_REQUIRED, reason)
            self.ledger.engage_kill(f"protection repair: {reason}")
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="repair", note=reason)
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED", "reason": reason}

        # 1) 精确撤销全部旧腿，并等待每条腿明确终态
        for order in self.ledger.orders_for_intent(intent_id):
            if order["order_kind"] not in ("STOP_LOSS", "TAKE_PROFIT"):
                continue
            if order["state"] != "ACTIVE":
                continue
            cid = order["client_order_id"]
            try:
                self.exchange.cancel_order(cid)
            except CancelUnknownError:
                return _recovery(f"cancel result unknown: {cid}")
            fact = self._safe_query_order(cid)
            if fact is None:
                return _recovery(f"query failed after cancel: {cid}")
            if fact.status == "CANCELLED":
                self.ledger.update_order(cid, state="CANCELLED")
            elif fact.status in ("FILLED", "PARTIALLY_FILLED"):
                # 撤单竞态：腿在撤单窗口内成交 → 以事实为准
                self._apply_fills(cid)
                self.ledger.update_order(
                    cid, state=fact.status, filled_qty=fact.filled_qty,
                    avg_price=fact.avg_price)
            elif fact.status == "NEW":
                return _recovery(f"cancel unconfirmed, leg still NEW: {cid}")
            else:
                return _recovery(f"leg in unexpected state {fact.status}: {cid}")

        # 2) 拉取交易所实际仓位（唯一数量真源）
        pos = self._safe_position()
        if pos is None:
            return _recovery("exchange position UNKNOWN")

        if abs(pos.signed_qty) < 1e-12:
            # 修复窗口内仓位归零：只有权威保护/平仓成交才能干净收敛。
            # 无成交事实 → CLOSE_PROVENANCE_UNKNOWN，禁止合成 SELL / 假 RECONCILED。
            if self._intent_has_close_fill(intent_id):
                _transition_idem(
                    IntentState.CLOSING, "flat confirmed during repair")
                _transition_idem(
                    IntentState.CLOSED, "already flat on exchange")
                _transition_idem(
                    IntentState.RECONCILED,
                    "ledger matches exchange after repair-time close")
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.KNOWN_FLAT, source="repair")
                return {"success": True, "intent_id": intent_id,
                        "state": "RECONCILED", "reason": "flat during repair"}
            _transition_idem(
                IntentState.RECOVERY_REQUIRED,
                f"{CLOSE_PROVENANCE_UNKNOWN}: flat during repair without close fill")
            self._record_close_provenance_unknown(
                None, reason=f"flat during repair; no close fill {intent_id}")
            self.ledger.engage_kill(
                f"{CLOSE_PROVENANCE_UNKNOWN} during protection repair {intent_id}")
            return {"success": False, "intent_id": intent_id,
                    "state": "RECOVERY_REQUIRED",
                    "reason": CLOSE_PROVENANCE_UNKNOWN}

        remaining = abs(pos.signed_qty)
        side = "LONG" if pos.signed_qty > 0 else "SHORT"

        # 3) 先提交并确认强制腿 SL
        _transition_idem(
            IntentState.PROTECTION_SUBMITTING,
            f"rebuild mandatory SL for remaining {remaining}")
        try:
            sl_px, tp_px = self._protect_prices(intent_id)
            if not _valid_price(sl_px):
                return _recovery("mandatory SL price missing")
            self._place_protection_leg(
                intent_id, self._leg_cid(intent_id, "SL-R"),
                OrderKind.STOP_LOSS, side, remaining, stop_price=float(sl_px))
        except SubmitUnknownError as exc:
            return _recovery(f"mandatory SL rebuild result unknown: {exc}")
        except OrderRejectedError as exc:
            self.ledger.transition_intent(
                intent_id, IntentState.PROTECTION_FAILED,
                f"mandatory SL rebuild rejected: {exc}", correlation_id=intent_id)
            return self._emergency_close(
                intent_id, trigger="mandatory SL rebuild failed")

        tp_ok = False
        if _valid_price(tp_px):
            try:
                self._place_protection_leg(
                    intent_id, self._leg_cid(intent_id, "TP-R"),
                    OrderKind.TAKE_PROFIT, side, remaining, stop_price=float(tp_px))
                tp_ok = True
            except (OrderRejectedError, SubmitUnknownError):
                tp_ok = False

        self.ledger.transition_intent(
            intent_id, IntentState.PROTECTED,
            "SL rebuilt"
            + ("" if tp_ok else "; TP incomplete (safe_but_incomplete)"),
            correlation_id=intent_id)
        return {"success": True, "intent_id": intent_id, "state": "PROTECTED",
                "sl_coverage": remaining,
                "tp_coverage": remaining if tp_ok else 0.0,
                "safe_but_incomplete": not tp_ok}

    def _intent_has_close_fill(self, intent_id: str) -> bool:
        """是否存在可解释平仓的权威成交（保护腿或 CLOSE），禁止用空仓本身当 fill。"""
        for order in self.ledger.orders_for_intent(intent_id):
            if order["order_kind"] not in ("CLOSE", "STOP_LOSS", "TAKE_PROFIT"):
                continue
            if self.ledger.fills_aggregate(order["client_order_id"])["qty"] > _QTY_EPS:
                return True
        return False

    def _any_closed_intent_filled_close(self) -> Optional[str]:
        """是否存在另一个已 reconciled/closed 且含成交 close 单的 intent。

        用于 _reconcile_protected_intents G3 收敛：原始 PROTECTED intent 的
        SL/TP 虽未触发，但仓位已被独立 close intent 权威平掉。
        """
        for intent in self.ledger.list_intents():
            if intent["side"] != "CLOSE":
                continue
            if intent["state"] not in (
                IntentState.CLOSED.value, IntentState.RECONCILED.value,
            ):
                continue
            for order in self.ledger.orders_for_intent(intent["intent_id"]):
                if (
                    order["order_kind"] == "CLOSE"
                    and order["filled_qty"] > _QTY_EPS
                    and self.ledger.fills_aggregate(order["client_order_id"])["qty"] > _QTY_EPS
                ):
                    return intent["intent_id"]
        return None

    def _recover_protection_lifecycle(self, intent_id: str) -> Optional[Dict[str, Any]]:
        """G0-4C：保护中间态的生命周期恢复。

        覆盖 FILLED_UNPROTECTED / PROTECTION_SUBMITTING / PARTIALLY_FILLED。
        只在交易所确认仍有仓位时补保护：
        - 覆盖超限（C3/C4 失配）→ COVERAGE_OVERFLOW → 撤旧按实际仓位重建；
        - 覆盖不足 → sync_protection 按角色差额补齐（C2：不重提未知单）；
        - SL 已足额 → 恢复 PROTECTED，绝不重挂；
        - 仓位已空且无平仓成交 → CLOSE_PROVENANCE_UNKNOWN，不合成 SELL。
        """
        fact = self.ledger.get_position_fact(self.symbol)
        if fact is None or fact["state"] == PositionFactState.UNKNOWN.value:
            return {"intent_id": intent_id, "fact": "PROTECTION_RECOVERY",
                    "reason": "position UNKNOWN; protection recovery blocked"}
        pos = self._safe_position()
        if pos is None:
            return {"intent_id": intent_id, "fact": "PROTECTION_RECOVERY",
                    "reason": "exchange position query failed; recovery blocked"}
        exchange_qty = abs(pos.signed_qty)
        if (
            fact["state"] != PositionFactState.KNOWN_OPEN.value
            or exchange_qty <= _QTY_EPS
        ):
            if self._intent_has_close_fill(intent_id):
                return None
            current = self.ledger.get_intent(intent_id)
            if current and IntentState(current["state"]) in (
                IntentState.FILLED_UNPROTECTED, IntentState.PARTIALLY_FILLED,
                IntentState.PROTECTION_SUBMITTING,
            ):
                self.ledger.transition_intent(
                    intent_id, IntentState.RECOVERY_REQUIRED,
                    f"{CLOSE_PROVENANCE_UNKNOWN}: flat without close fill",
                    correlation_id=intent_id)
            self._record_close_provenance_unknown(
                None, reason=f"protection mid-state flat without close fill {intent_id}")
            return {"intent_id": intent_id, "fact": CLOSE_PROVENANCE_UNKNOWN,
                    "reason": "exchange flat; no matching close order/fill"}

        orders = self.ledger.orders_for_intent(intent_id)
        status = compute_protection_status(orders, exchange_qty)
        if status.sl_coverage > exchange_qty + _QTY_EPS:
            repaired = self._repair_protection(intent_id)
            if repaired.get("success"):
                return None
            return {"intent_id": intent_id,
                    "fact": repaired.get("reason") or "PROTECTION_RECOVERY",
                    "reason": repaired.get("reason")}

        synced = self.sync_protection(intent_id)
        if not synced.get("success"):
            return {"intent_id": intent_id, "fact": "PROTECTION_RECOVERY",
                    "reason": synced.get("reason") or "protection sync failed"}

        fresh = compute_protection_status(
            self.ledger.orders_for_intent(intent_id), exchange_qty)
        if fresh.sl_coverage + _QTY_EPS < exchange_qty:
            return {"intent_id": intent_id, "fact": "PROTECTION_RECOVERY",
                    "reason": f"SL coverage insufficient after sync"
                              f" ({fresh.sl_coverage}/{exchange_qty})"}
        current = self.ledger.get_intent(intent_id)
        if current is None:
            return None
        state = IntentState(current["state"])
        if state == IntentState.PARTIALLY_FILLED:
            self.ledger.transition_intent(
                intent_id, IntentState.FILLED_UNPROTECTED,
                "protection recovery: entry fills authoritative",
                correlation_id=intent_id)
            state = IntentState.FILLED_UNPROTECTED
        if state == IntentState.FILLED_UNPROTECTED:
            self.ledger.transition_intent(
                intent_id, IntentState.PROTECTION_SUBMITTING,
                f"protection recovery: SL covers position ({fresh.sl_coverage})",
                correlation_id=intent_id)
            state = IntentState.PROTECTION_SUBMITTING
        if state == IntentState.PROTECTION_SUBMITTING:
            self.ledger.transition_intent(
                intent_id, IntentState.PROTECTED,
                "recovered protection lifecycle"
                + ("" if fresh.tp_ok else "; sl-only"),
                correlation_id=intent_id)
        return None

    def _audit_orphan_protection(self, report: Dict[str, Any]) -> None:
        """G0-4C C6：仓位已空但仍有 ACTIVE 保护腿 → ORPHAN_PROTECTION。

        残留条件单未来可能触发并新建反向风险。本刀只负责发现与
        fail-closed（熔断新增风险 + 报告未决）；是否撤销属于真实协议
        执行阶段，绝不在此自动撤单。
        """
        fact = self.ledger.get_position_fact(self.symbol)
        if fact is None or fact["state"] != PositionFactState.KNOWN_FLAT.value:
            return
        orphans = self.ledger.orders_in_states(
            ["ACTIVE"], kinds=("STOP_LOSS", "TAKE_PROFIT"))
        if not orphans:
            return
        self.ledger.engage_kill(
            f"ORPHAN_PROTECTION: {len(orphans)} active protection leg(s)"
            " with flat position")
        if not any(e.get("fact") == "ORPHAN_PROTECTION" for e in report["unresolved"]):
            report["unresolved"].append({
                "fact": "ORPHAN_PROTECTION",
                "reason": "flat position with active protection leg(s): "
                          + ",".join(o["client_order_id"] for o in orphans),
            })

    def _protect_prices(self, intent_id: str) -> tuple:
        """返回 (sl_px, tp_px)；缺失/非法为 None（G0-4B 哨兵废除）。

        优先取账本保护腿已记录的触发价（重放/修复路径），否则取开仓时
        冻结的计划价。TP 为可选腿，None 表示明确不挂 TP，绝不是哨兵价。
        """
        sl = tp = None
        intent = self.ledger.get_intent(intent_id)
        if intent:
            if _valid_price(intent.get("stop_price")):
                sl = float(intent["stop_price"])
            if _valid_price(intent.get("take_profit_price")):
                tp = float(intent["take_profit_price"])
        cached = self._protect_px.get(intent_id)
        if cached:
            if _valid_price(cached[0]):
                sl = float(cached[0])
            if len(cached) > 1 and _valid_price(cached[1]):
                tp = float(cached[1])
            elif len(cached) > 1 and cached[1] is None:
                tp = None
        for order in self.ledger.orders_for_intent(intent_id):
            px = order.get("stop_price")
            if not _valid_price(px):
                continue
            if order["order_kind"] == "STOP_LOSS":
                sl = float(px)
            elif order["order_kind"] == "TAKE_PROFIT":
                tp = float(px)
        return sl, tp

    def _place_protection_leg(
        self, intent_id: str, cid: str, kind: OrderKind, side: str,
        qty: float, stop_price: float,
    ) -> None:
        """ledger-first 挂保护腿；提交结果同步到账本。

        硬合同（G0-4B）：qty 必须为正且不超过任何已确认仓位语义，触发价必须
        是合法正价。零数量/哨兵价保护在提交前拒绝，不允许"看起来挂上了"。
        """
        if qty <= _QTY_EPS or not _valid_price(stop_price):
            raise OrderRejectedError(
                f"protection leg rejected before submit: qty={qty},"
                f" stop_price={stop_price}; zero-qty or sentinel protection forbidden"
            )
        if side not in ("LONG", "SHORT"):
            raise OrderRejectedError(
                f"protection leg rejected before submit: invalid side {side}")
        pos = self._safe_position()
        if pos is None:
            raise OrderRejectedError(
                "protection leg rejected before submit: position UNKNOWN")
        pos_qty = abs(pos.signed_qty)
        if qty > pos_qty + _QTY_EPS:
            raise OrderRejectedError(
                f"protection qty {qty} exceeds confirmed position {pos_qty}")
        if pos_qty > _QTY_EPS:
            pos_side = "LONG" if pos.signed_qty > 0 else "SHORT"
            if pos_side != side:
                raise OrderRejectedError(
                    f"protection would not reduce {pos_side} with side={side}")
        entry_px = self._entry_price_for_protection(intent_id)
        if _valid_price(entry_px):
            px = float(stop_price)
            entry = float(entry_px)
            if kind == OrderKind.STOP_LOSS:
                if side == "LONG" and px >= entry:
                    raise OrderRejectedError(
                        f"nonsensical LONG SL {px} not below entry {entry}")
                if side == "SHORT" and px <= entry:
                    raise OrderRejectedError(
                        f"nonsensical SHORT SL {px} not above entry {entry}")
            elif kind == OrderKind.TAKE_PROFIT:
                if side == "LONG" and px <= entry:
                    raise OrderRejectedError(
                        f"nonsensical LONG TP {px} not above entry {entry}")
                if side == "SHORT" and px >= entry:
                    raise OrderRejectedError(
                        f"nonsensical SHORT TP {px} not below entry {entry}")
        try:
            self.ledger.record_order_submitting(
                client_order_id=cid, intent_id=intent_id, order_kind=kind.value,
                side="SELL" if side == "LONG" else "BUY", position_side=side,
                quantity=qty, stop_price=stop_price, reduce_only=True,
            )
        except Exception as exc:
            raise _LedgerWriteFailed(str(exc)) from exc
        req = OrderRequest(
            client_order_id=cid, symbol=self.symbol, order_kind=kind,
            side="SELL" if side == "LONG" else "BUY", position_side=side,
            quantity=qty, stop_price=stop_price, reduce_only=True,
        )
        try:
            ack = self.exchange.submit_order(req)
            if ack.status == "NEW":
                state = "ACTIVE"
            elif ack.status in ("FILLED", "PARTIALLY_FILLED"):
                state = ack.status
            else:
                raise SubmitUnknownError(
                    f"protection ack status not authoritative: {ack.status}")
            self.ledger.update_order(
                cid, state=state,
                exchange_order_id=ack.exchange_order_id,
                filled_qty=ack.filled_qty, avg_price=ack.avg_price)
        except SubmitUnknownError:
            self.ledger.update_order(cid, state="SUBMIT_UNKNOWN")
            raise
        except Exception:
            self.ledger.update_order(cid, state="REJECTED")
            raise

    def _leg_cid(self, intent_id: str, tag: str) -> str:
        """确定性腿 ID：首腿无后缀，重复挂腿从 2 起编号。"""
        existing = {
            o["client_order_id"] for o in self.ledger.orders_for_intent(intent_id)}
        base = f"{intent_id}-{tag}"
        if base not in existing:
            return base
        n = 2
        while f"{base}{n}" in existing:
            n += 1
        return f"{base}{n}"

    # ---------- 迟到成交（P0-B2.2 证据门控三分类） ----------

    def apply_fill_event(self, fill: Fill) -> Dict[str, Any]:
        """venue 迟到成交事件（W1 修正：固有 EVENT 严格路径）。

        分类：REJECTED（非法事实，先于写库）/ IDENTITY_CONFLICT /
        IDENTITY_UNRESOLVED（缺失事实：不造 raw、不确认重复、
        不收养；阻新增不阻减仓）/ DUPLICATE（完全确认的幂等重放）/
        COVERED_BY_FACT / SYNTHETIC_REPLACED / LATE_NEW_FILL。
        """
        from aurora.kernel import fill_identity as _fi

        # ① 非法事实先于一切（含缺 symbol 的提前返回）：
        #    提供了 raw 就必须是有限、严格正的合法数值。
        if fill.qty_raw is not None:
            d = _fi.parse_finite(fill.qty_raw)
            if d is None or d <= 0:
                return self._fill_rejected(
                    fill, f"qty_raw invalid: {fill.qty_raw!r}")
        if fill.price_raw is not None:
            d = _fi.parse_finite(fill.price_raw)
            if d is None or d <= 0:
                return self._fill_rejected(
                    fill, f"price_raw invalid: {fill.price_raw!r}")
        if fill.fee_raw not in (None, ""):
            d = _fi.parse_finite(fill.fee_raw)
            if d is None:
                return self._fill_rejected(
                    fill, f"fee_raw invalid: {fill.fee_raw!r}")
            if not fill.fee_asset:
                return self._fill_rejected(
                    fill, "fee KNOWN requires fee_asset")
        # raw 缺失但 REAL 数值本身非法 → 同样拒收（不因缺 raw 放过）
        import math as _math
        for name, v in (("qty", fill.qty), ("price", fill.price)):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                fv = float("nan")
            if _math.isnan(fv) or fv < 0 or (name == "price" and fv == 0):
                return self._fill_rejected(
                    fill, f"{name} REAL value invalid: {v!r}")
        if float(fill.qty) <= 0 and fill.qty_raw is None:
            return self._fill_rejected(
                fill, f"qty non-positive and no raw: {fill.qty!r}")
        # side 枚举（Fix 1）：非法 side 不入账
        if fill.side not in ("BUY", "SELL"):
            return self._fill_rejected(
                fill, f"side invalid: {fill.side!r}")
        # 费用从 raw 派生（Fix 1）：fee_raw 提供时 fee 必须一致派生
        if fill.fee_raw is not None and fill.fee_raw != "":
            from decimal import Decimal as _D
            try:
                fee_d = _D(fill.fee_raw)
            except Exception:
                return self._fill_rejected(
                    fill, f"fee_raw unparseable: {fill.fee_raw!r}")
            if not fee_d.is_finite():
                return self._fill_rejected(
                    fill, f"fee_raw non-finite: {fill.fee_raw!r}")
            if fill.fee_raw is not None and abs(
                    float(fill.fee or 0) - float(fee_d)) > 1e-12:
                # fee 展示值与 raw 不一致：以 raw 为准（派生），不拒
                pass  # 派生在下方 raw→REAL 块统一处理
        # raw 权威→REAL 派生（Fix 1 强化）：有限性 + 溢出/下溢检查
        # + fee 派生；任何派生失败 → 拒收（不写库）
        import math as _m
        try:
            _qty_f = float(fill.qty_raw) if fill.qty_raw else float(fill.qty)
            _price_f = (float(fill.price_raw) if fill.price_raw
                        else float(fill.price))
            _fee_f = (float(fill.fee_raw)
                      if fill.fee_raw not in (None, "") else float(fill.fee or 0))
        except (ValueError, OverflowError):
            return self._fill_rejected(fill, "raw→float conversion failed")
        for _n, _v in (("qty", _qty_f), ("price", _price_f),
                       ("fee", _fee_f)):
            if not _m.isfinite(_v):
                return self._fill_rejected(
                    fill, f"{_n} derived value non-finite: {_v}")
        if _qty_f <= 0 or _price_f <= 0:
            return self._fill_rejected(
                fill, f"derived qty/price non-positive: {_qty_f}/{_price_f}")
        fill = Fill(
            fill_id=fill.fill_id, client_order_id=fill.client_order_id,
            qty=_qty_f, price=_price_f, fee=_fee_f,
            side=fill.side, filled_at=fill.filled_at,
            symbol=fill.symbol, qty_raw=fill.qty_raw,
            price_raw=fill.price_raw, fee_raw=fill.fee_raw,
            fee_asset=fill.fee_asset)

        # ② 缺失事实（symbol / raw 不齐备）→ UNRESOLVED，不降级
        missing = [f for f in ("symbol", "qty_raw", "price_raw")
                   if getattr(fill, f, None) in (None, "")]
        if missing:
            # 审计告警（transitions 表）而非全局 kill——W2 语义：
            # 未解析必须持久可审计、不收养、不重复入账、不熔断。
            self.ledger._log_transition(Transition(
                "fill", fill.fill_id, "", "IDENTITY_UNRESOLVED",
                utc_now(), f"missing facts {missing}; not adopted,"
                " not confirmed duplicate", fill.fill_id))
            self.ledger.mark_fill_unresolved(
                fill.fill_id,
                f"missing facts {missing}")
            return {"class": "IDENTITY_UNRESOLVED",
                    "fill_id": fill.fill_id,
                    "missing": missing,
                    "action": "MANUAL_RECOVERY"}

        # ③ 归属校验：事件 symbol vs 订单 symbol
        attribution = _fi.check_attribution(
            self.ledger._conn, fill.symbol, fill.client_order_id)
        if attribution["verdict"] == "ORDER_NOT_FOUND":
            self.ledger.engage_kill(
                f"orphan fill event {fill.fill_id}")
            return {"class": "ORPHAN", "fill_id": fill.fill_id,
                    "action": "MANUAL_RECOVERY"}
        if attribution["verdict"] == "ATTRIBUTION_ANOMALY":
            self.ledger.engage_kill(
                f"fill attribution anomaly {fill.fill_id}:"
                f" {attribution}")
            return {"class": "ATTRIBUTION_ANOMALY",
                    "fill_id": fill.fill_id,
                    "detail": attribution,
                    "action": "MANUAL_RECOVERY"}

        # ④ 身份比较：venue=EVENT 严格；账本行为可信读取（模式在
        #    调用处声明，不从载荷读取）——Fix 1：复合身份 (symbol,
        #    fill_id) 定位既有行
        existing = self.ledger.get_fill(fill.fill_id, symbol=fill.symbol)
        if existing is None and fill.symbol is not None:
            # 复合身份未命中 → **显式**查询同 fill_id 的 NULL-symbol
            # 历史行（R1：裸 ID 探测受插入顺序影响命中任意一行；
            # NULL 行是迁移前同一笔交易的确定性审计定位）→ 跨等级
            # 比较，绝不收养为新身份（否则重放变新成交=二次记账）
            shadow = self.ledger.get_legacy_fill(fill.fill_id)
            if shadow is not None:
                existing = shadow
        if existing is not None:
            legacy = {
                "client_order_id": existing["client_order_id"],
                "symbol": None, "side": existing["side"],
                "qty": existing["qty"], "price": existing["price"],
                "fee_raw": None, "fee_asset": None,
            }
            event = {
                "client_order_id": fill.client_order_id,
                "symbol": fill.symbol, "side": fill.side,
                "qty": float(fill.qty), "price": float(fill.price),
                "qty_raw": fill.qty_raw, "price_raw": fill.price_raw,
                "fee_raw": fill.fee_raw, "fee_asset": fill.fee_asset,
            }
            # 依据存储行 origin 选择比较模式（两侧同 EVENT → 同等级
            # compare_as('EVENT')；legacy 行 → compare_mixed 跨等级）
            stored_origin = existing.get("origin")
            if stored_origin == "EVENT" and existing.get("qty_raw"):
                # 两侧 EVENT：用 raw 做同等级比较
                both_event = {
                    "client_order_id": fill.client_order_id,
                    "symbol": fill.symbol, "side": fill.side,
                    "qty": fill.qty, "price": fill.price,
                    "qty_raw": fill.qty_raw,
                    "price_raw": fill.price_raw,
                    "fee_raw": fill.fee_raw,
                    "fee_asset": fill.fee_asset,
                }
                stored_event = {
                    "client_order_id": existing["client_order_id"],
                    "symbol": existing.get("symbol") or fill.symbol,
                    "side": existing["side"],
                    "qty": existing["qty"],
                    "price": existing["price"],
                    "qty_raw": existing.get("qty_raw"),
                    "price_raw": existing.get("price_raw"),
                    "fee_raw": existing.get("fee_raw"),
                    "fee_asset": existing.get("fee_asset"),
                }
                report = _fi.compare_as("EVENT", stored_event, both_event)
            else:
                report = _fi.compare_mixed(legacy, event)
            if report["verdict"] == "MISMATCH":
                self.ledger.engage_kill(
                    f"fill identity conflict {fill.fill_id}: fields="
                    f"{report['conflict_fields']}")
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.UNKNOWN,
                    source="fill-event",
                    note=f"identity conflict {fill.fill_id}")
                return {"class": "IDENTITY_CONFLICT",
                        "fill_id": fill.fill_id,
                        "action": "MANUAL_RECOVERY",
                        "kill_engaged": True, "report": report}
            if report["verdict"] == "INCOMPLETE":
                # 审计告警而非全局 kill（同上）
                self.ledger._log_transition(Transition(
                    "fill", fill.fill_id, "", "IDENTITY_UNRESOLVED",
                    utc_now(),
                    f"unverifiable={report['unverifiable_fields']}"
                    "; not confirmed duplicate", fill.fill_id))
                self.ledger.mark_fill_unresolved(
                    fill.fill_id,
                    f"unverifiable={report['unverifiable_fields']}")
                return {"class": "IDENTITY_UNRESOLVED",
                        "fill_id": fill.fill_id,
                        "action": "MANUAL_RECOVERY",
                        "report": report}
            # Fix 3: DEVIATION 自动检测——按**冻结的**推导上下文重算
            # realized_pnl 与存储值比对：
            # - stored ctx 缺失 = 不可证实（绝不伪造空串为"同上下文"）；
            # - 基准变化（entry avg 变）= EXPLICIT_RECOMPUTE 路径，
            #   追加重算事件（append-only），不改历史行、不判偏离；
            # - 同 ctx 重算不一致 → DEVIATION → 损益 UNRELIABLE。
            _order = self.ledger.get_order(fill.client_order_id)
            if _order is not None:
                recomputed = self._realized_pnl(_order, fill)
                stored_pnl = float(existing.get("realized_pnl") or 0)
                stored_ctx = existing.get("derivation_ctx")
                recompute_ctx = self._pnl_derivation_ctx(_order, fill)
                if stored_ctx is None or str(stored_ctx).strip() == "":
                    # 缺推导上下文：不可证实——审计但不伪造比较
                    self.ledger._log_transition(Transition(
                        "fill", fill.fill_id, "", "PNL_UNVERIFIABLE",
                        utc_now(),
                        "no derivation_ctx stored on existing row;"
                        " pnl cannot be verified on replay (not"
                        " fabricated as same-context)", fill.fill_id))
                else:
                    d_check = _fi.derivation_check(
                        stored_ctx, recompute_ctx,
                        Decimal(str(recomputed)),
                        Decimal(str(stored_pnl)))
                    if d_check["path"] == "EXPLICIT_RECOMPUTE":
                        # 冻结基准已变化：显式重算（依据落审计链）
                        self.ledger.append_fill_recomputation(
                            fill.fill_id, stored_pnl, recomputed,
                            f"basis changed on venue replay:"
                            f" {d_check['reason']}",
                            old_ctx=str(stored_ctx),
                            new_ctx=str(recompute_ctx),
                            basis_ref=(
                                f"order:{_order['client_order_id']}"),
                            symbol=fill.symbol)
                        self.ledger._log_transition(Transition(
                            "fill", fill.fill_id, "", "EXPLICIT_RECOMPUTE",
                            utc_now(),
                            f"basis changed: {d_check['reason']};"
                            f" stored={stored_pnl}"
                            f" recomputed={recomputed}",
                            fill.fill_id))
                    elif d_check["deviation"]:
                        self.ledger.mark_pnl_unreliable(
                            self.symbol,
                            f"derivation deviation on fill {fill.fill_id}:"
                            f" recomputed={recomputed} stored={stored_pnl}")
                        self.ledger._log_transition(Transition(
                            "fill", fill.fill_id, "", "DERIVATION_DEVIATION",
                            utc_now(),
                            f"recomputed={recomputed} != stored={stored_pnl};"
                            " pnl marked UNRELIABLE", fill.fill_id))
            return {"class": "DUPLICATE", "fill_id": fill.fill_id,
                    "report": report}

        # 无既有行：走证据门控（fact/synthetic/late-new）
        return self._fill_new_evidence(fill)

    def _fill_rejected(self, fill: Fill, reason: str) -> Dict[str, Any]:
        """非法事实：拒收（不写库、不熔断——数据错误非运行故障）。"""
        return {"class": "REJECTED", "fill_id": fill.fill_id,
                "reason": reason, "wrote": False}

    def _fill_new_evidence(self, fill: Fill) -> Dict[str, Any]:
        """无既有行的新 venue 事件：证据门控（保留原三分支语义）。"""
        order = self.ledger.get_order(fill.client_order_id)

        # 证据一：reconciliation fact 明确覆盖该 venue trade ID
        # （R2：覆盖证据按订单归属核验——跨订单/跨 symbol 的同
        # trade ID 不得套用他方 fact，否则经济影响被静默豁免）
        fact_id = self.ledger.evidence_covers_fill(
            fill.fill_id, client_order_id=fill.client_order_id)
        if fact_id:
            realized = 0.0
            if order is not None and order.get("order_kind") != "ENTRY":
                realized = self._realized_pnl(order, fill) if order else 0.0
            self.ledger.insert_fill(
                fill.fill_id, fill.client_order_id,
                float(fill.qty), float(fill.price),
                float(fill.fee or 0), fill.side, fill.filled_at,
                realized_pnl=realized,
                covered_by_fact_id=fact_id, economic_effect_applied=False,
                venue_symbol=fill.symbol,
                venue_qty_raw=fill.qty_raw,
                venue_price_raw=fill.price_raw,
                venue_fee_raw=fill.fee_raw,
                venue_fee_asset=fill.fee_asset,
                venue_derivation_ctx=self._pnl_derivation_ctx(order))
            return {"class": "COVERED_BY_FACT", "fill_id": fill.fill_id,
                    "evidence_fact_id": fact_id,
                    "order": fill.client_order_id,
                    "realized_pnl": realized}

        # 证据二：确定性替换未匹配合成调整
        synthetic = next(
            (s for s in self.ledger.open_synthetic_fills(
                fill.client_order_id)
             if abs(float(s["qty"]) - float(fill.qty)) <= 1e-9), None)
        if synthetic is not None:
            realized = self._realized_pnl(order, fill) if (
                order is not None
                and order.get("order_kind") != "ENTRY") else 0.0
            inserted = self.ledger.insert_fill(
                fill.fill_id, fill.client_order_id,
                float(fill.qty), float(fill.price),
                float(fill.fee or 0), fill.side, fill.filled_at,
                realized_pnl=realized,
                replaces_synthetic_fill_id=synthetic["fill_id"],
                venue_symbol=fill.symbol,
                venue_qty_raw=fill.qty_raw,
                venue_price_raw=fill.price_raw,
                venue_fee_raw=fill.fee_raw,
                venue_fee_asset=fill.fee_asset,
                venue_derivation_ctx=self._pnl_derivation_ctx(order))
            if inserted:
                self.ledger.mark_synthetic_replaced(
                    synthetic["fill_id"], fill.fill_id)
                self.ledger.sync_order_projection_from_fills(
                    fill.client_order_id)
            return {"class": "SYNTHETIC_REPLACED",
                    "fill_id": fill.fill_id,
                    "replaces": synthetic["fill_id"],
                    "realized_pnl": realized,
                    "order_qty_unchanged": True}

        # 证据三（无证据）：LATE_NEW_FILL——修正累计 + 终态逃逸检查
        realized = self._realized_pnl(order, fill) if (
            order is not None and order.get("order_kind") != "ENTRY"
        ) else 0.0
        inserted = self.ledger.insert_fill(
            fill.fill_id, fill.client_order_id,
            float(fill.qty), float(fill.price),
            float(fill.fee or 0), fill.side, fill.filled_at,
            realized_pnl=realized,
            venue_symbol=fill.symbol,
            venue_qty_raw=fill.qty_raw,
            venue_price_raw=fill.price_raw,
            venue_fee_raw=fill.fee_raw,
            venue_fee_asset=fill.venue_fee_asset
            if hasattr(fill, 'venue_fee_asset') else fill.fee_asset,
            venue_derivation_ctx=self._pnl_derivation_ctx(order))
        if not inserted and self.ledger.fill_exists(
                fill.fill_id, symbol=fill.symbol):
            return {"class": "DUPLICATE", "fill_id": fill.fill_id}

        self.ledger.sync_order_projection_from_fills(fill.client_order_id)
        self._refresh_position_fact()
        pos = self._safe_position()
        intent = self.ledger.get_intent(order["intent_id"]) if order else None
        intent_state = IntentState(intent["state"]) if intent else None
        if intent_state in (
                IntentState.RECONCILED, IntentState.REJECTED,
                IntentState.CLOSED):
            self.ledger.transition_intent(
                order["intent_id"], IntentState.RECOVERY_REQUIRED,
                f"EXCHANGE_FACT_CORRECTION late venue fact invalidates "
                f"terminal state (fill {fill.fill_id})",
                correlation_id=order["intent_id"],
                exchange_fact=(f"late-fill:{fill.fill_id}", fill.fill_id))
            self.ledger.engage_kill(
                f"late fill after terminal state {fill.fill_id}")
        elif intent_state == IntentState.PROTECTED:
            self.sync_protection(order["intent_id"])
        return {"class": "LATE_NEW_FILL", "fill_id": fill.fill_id,
                "order": fill.client_order_id,
                "realized_pnl": realized,
                "position_after":
                    abs(pos.signed_qty) if pos else None}

    def record_synthetic_fill(
        self, fill: Fill, reason: str = "reconciliation gap",
    ) -> Dict[str, Any]:
        """对账缺口合成调整（数量层面补齐）。真实 Fill 到达后按
        SYNTHETIC_REPLACED 路径替换其经济影响。"""
        order = self.ledger.get_order(fill.client_order_id)
        if order is None:
            return self._refuse("no order for synthetic fill")
        inserted = self.ledger.insert_fill(
            fill.fill_id, fill.client_order_id, fill.qty, fill.price,
            fill.fee, fill.side, fill.filled_at, realized_pnl=0.0,
            synthetic=True)
        if inserted:
            economic = sum(
                f["qty"] for f in self.ledger.fills_for_order(fill.client_order_id))
            self.ledger.update_order(
                fill.client_order_id, filled_qty=round(economic, 10))
        return {"success": True, "synthetic_fill_id": fill.fill_id,
                "reason": reason}

    def _pnl_derivation_ctx(self, order: Optional[Dict],
                            fill: Optional[Fill] = None) -> Optional[str]:
        """Fix 3：realized_pnl 的推导上下文（冻结基准快照）。

        依据 = 入场基准（entry 腿订单 + 其 avg_price）+ 平仓方向。
        重算必须按该快照进行：基准变化走 EXPLICIT_RECOMPUTE（追加
        重算事件），不是把当前上下文伪装成"相同"。order 缺失 = 无
        上下文（不可证实），不伪造。
        """
        if not order:
            return None
        entry = self.ledger.get_order(f"{order['intent_id']}-ENTRY")
        entry_avg = float(entry["avg_price"]) if entry else 0.0
        return (f"v1|basis=order:{order['intent_id']}-ENTRY"
                f"|entry_avg={entry_avg!r}|side={order['side']}")

    def _realized_pnl(self, order: Dict, fill: Fill) -> float:
        """平仓方向成交的已实现盈亏（入场腿记 0）。"""
        if order["order_kind"] == "ENTRY":
            return 0.0
        entry = self.ledger.get_order(f"{order['intent_id']}-ENTRY")
        entry_avg = float(entry["avg_price"]) if entry else 0.0
        if entry_avg <= 0:
            return 0.0
        sign = 1.0 if order["side"] == "SELL" else -1.0
        return round((fill.price - entry_avg) * fill.qty * sign, 10)

    def _apply_fills(self, client_order_id: str) -> int:
        order = self.ledger.get_order(client_order_id)
        inserted_count = 0
        for fill in self.exchange.fills(client_order_id):
            realized = self._realized_pnl(order, fill) if order else 0.0
            inserted = self.ledger.insert_fill(
                fill.fill_id, fill.client_order_id, fill.qty, fill.price,
                fill.fee, fill.side, fill.filled_at, realized_pnl=realized)
            if not inserted:
                continue  # 重复 Fill 事件不重复记账
            inserted_count += 1
        # B1：成交入账后立即把订单投影收敛到权威聚合（filled_qty 是投影，
        # fills 是事实；投影只推进不倒退）。
        self.ledger.sync_order_projection_from_fills(client_order_id)
        agg = self.ledger.fills_aggregate(client_order_id)
        if agg["qty"] > _QTY_EPS and _valid_price(agg.get("avg_price")):
            self.ledger.update_order(client_order_id, avg_price=agg["avg_price"])
        return inserted_count

    def _protection_fill_state(self, order: Dict[str, Any]) -> Optional[str]:
        fills = self.ledger.fills_for_order(order["client_order_id"])
        filled_qty = sum(float(f["qty"]) for f in fills)
        if filled_qty <= 1e-12:
            return None
        return ("FILLED" if filled_qty + 1e-12 >= float(order["quantity"])
                else "PARTIALLY_FILLED")

    def _record_close_provenance_unknown(
        self, report: Optional[Dict[str, Any]], reason: str,
    ) -> None:
        """记录仓位已空但平仓来源未知。

        position truth ≠ financial provenance truth。
        该残留可永久 OPEN / APPEND-ONLY；不因此永久禁止账户未来交易。
        新风险是否放开只取决于事故运行锁 / 明确 incident disposition。
        """
        self.ledger.set_position_fact(
            self.symbol, PositionFactState.KNOWN_FLAT,
            source=CLOSE_PROVENANCE_UNKNOWN, note=reason)
        if report is not None and not any(
            e.get("fact") == CLOSE_PROVENANCE_UNKNOWN for e in report["unresolved"]
        ):
            report["unresolved"].append({
                "fact": CLOSE_PROVENANCE_UNKNOWN,
                "reason": reason,
            })

    def _safe_query_order(self, client_order_id: str):
        try:
            return self.exchange.query_order(client_order_id)
        except Exception:
            return None

    def _safe_position(self):
        try:
            return self.exchange.position(self.symbol)
        except Exception:
            return None

    def _exchange_flat(self) -> bool:
        pos = self._safe_position()
        return pos is not None and abs(pos.signed_qty) < 1e-12

    def _refresh_position_fact(self) -> None:
        pos = self._safe_position()
        if pos is None:
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.UNKNOWN,
                source="reconcile", note="exchange position query failed")
            return
        if abs(pos.signed_qty) < 1e-12:
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.KNOWN_FLAT, source="reconcile")
        else:
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.KNOWN_OPEN,
                qty=abs(pos.signed_qty), side="LONG" if pos.signed_qty > 0 else "SHORT",
                source="reconcile")

    @staticmethod
    def _refuse(reason: str) -> Dict[str, Any]:
        return {"success": False, "replay": False, "state": "REFUSED", "reason": reason}


class _LedgerWriteFailed(Exception):
    """账本预写失败：订单绝不能被提交。"""
