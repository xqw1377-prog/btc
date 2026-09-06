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
"""
import uuid
from typing import Any, Dict, Optional

from .coverage import compute_protection_status
from .ledger import Ledger, PositionFactState
from .port import (
    CancelUnknownError,
    Fill,
    OrderKind,
    OrderRejectedError,
    OrderRequest,
    SubmitUnknownError,
)
from .state_machine import IntentState


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
                    intent = self.ledger.get_intent(intent_id)
                    if intent and IntentState(intent["state"]) in (
                        IntentState.SUBMITTING, IntentState.SUBMIT_UNKNOWN,
                        IntentState.ACKNOWLEDGED, IntentState.PARTIALLY_FILLED,
                    ):
                        self.ledger.transition_intent(
                            intent_id, IntentState.FILLED_UNPROTECTED,
                            f"recovery: entry {fact.status} (filled={fact.filled_qty})",
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
                else:
                    self.ledger.update_order(
                        cid,
                        state="ACTIVE" if fact.status == "NEW" else "FILLED",
                        filled_qty=fact.filled_qty if fact.status != "NEW" else None,
                        avg_price=fact.avg_price if fact.status != "NEW" else None)
                    if fact.status in ("FILLED", "PARTIALLY_FILLED"):
                        self._apply_fills(cid)
                    if state == IntentState.PROTECTION_SUBMITTING:
                        self.ledger.transition_intent(
                            intent_id, IntentState.PROTECTED,
                            f"recovery: protection confirmed {cid}", correlation_id=intent_id)
                report["resolved"].append(entry)

            elif order["order_kind"] == "CLOSE":
                if fact.status == "FILLED" or self._exchange_flat():
                    # 订单行事实同步 + 成交明细入账
                    if fact.status == "FILLED":
                        self.ledger.update_order(
                            cid, state="FILLED",
                            filled_qty=fact.filled_qty, avg_price=fact.avg_price)
                        self._apply_fills(cid)
                    else:
                        self.ledger.update_order(cid, state="FILLED")
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
        kill = self.ledger.kill_state()
        report["kill_engaged"] = bool(kill["engaged"])
        return report

    def open_position(
        self, side: str, quantity: float,
        intent_id: Optional[str] = None, reason: str = "manual",
        stop_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        kill = self.ledger.kill_state()
        if kill["engaged"]:
            return self._refuse(f"kill switch engaged: {kill['reason']}")

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

        self._protect_px[intent_id] = (
            float(stop_price) if stop_price else 99.0,
            float(take_profit_price) if take_profit_price else 101.0,
        )
        try:
            return self._submit_entry(intent_id, side, quantity, reason)
        except _LedgerWriteFailed as exc:
            # ledger-first 不变量：账本写不进去就没有订单被提交
            return self._refuse(f"ledger pre-submit write failed; no order sent: {exc}")

    def close_position(self, reason: str = "manual") -> Dict[str, Any]:
        fact = self.ledger.get_position_fact(self.symbol)
        if fact is None or fact["state"] != PositionFactState.KNOWN_OPEN.value:
            return self._refuse("close requires KNOWN_OPEN position fact")
        kill = self.ledger.kill_state()
        intent_id = f"AURORA-CLOSE-{uuid.uuid4().hex[:12]}"
        self.ledger.create_intent(intent_id, self.symbol, "CLOSE", fact["qty"])
        if not self.ledger.claim_intent(intent_id, self.instance_id):
            return self._refuse(f"close intent {intent_id} claimed by another executor")
        self.ledger.transition_intent(
            intent_id, IntentState.SUBMITTING, f"close begin ({reason}); kill={bool(kill['engaged'])}",
            correlation_id=intent_id)
        self.ledger.transition_intent(
            intent_id, IntentState.CLOSING, f"closing ({reason})", correlation_id=intent_id)
        return self._submit_close(intent_id, reason, emergency=False)

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

        if ack.status == "PARTIALLY_FILLED":
            self.ledger.transition_intent(
                intent_id, IntentState.PARTIALLY_FILLED,
                f"entry partial filled_qty={ack.filled_qty}", correlation_id=intent_id)
        self.ledger.transition_intent(
            intent_id, IntentState.FILLED_UNPROTECTED,
            f"entry filled={ack.filled_qty}; protection required",
            correlation_id=intent_id)
        return self._ensure_protection(intent_id)

    def _ensure_protection(self, intent_id: str) -> Dict[str, Any]:
        intent = self.ledger.get_intent(intent_id)
        entry_order = self.ledger.get_order(f"{intent_id}-ENTRY")
        filled_qty = entry_order["filled_qty"] if entry_order else 0.0
        side = intent["side"]

        self.ledger.transition_intent(
            intent_id, IntentState.PROTECTION_SUBMITTING,
            f"protection submit for actual filled qty={filled_qty}",
            correlation_id=intent_id)

        sl_px, tp_px = self._protect_prices(intent_id)
        # 强制腿 SL：失败 = 裸奔仓位 → 紧急平仓
        try:
            self._place_protection_leg(
                intent_id, self._leg_cid(intent_id, "SL"),
                OrderKind.STOP_LOSS, side, filled_qty, stop_price=sl_px)
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

        # 可选腿 TP：仅 TP 失败 = safe_but_incomplete，不紧急平仓
        tp_ok = True
        try:
            self._place_protection_leg(
                intent_id, self._leg_cid(intent_id, "TP"),
                OrderKind.TAKE_PROFIT, side, filled_qty, stop_price=tp_px)
        except (OrderRejectedError, SubmitUnknownError):
            tp_ok = False

        self.ledger.transition_intent(
            intent_id, IntentState.PROTECTED,
            f"SL confirmed for qty={filled_qty}"
            + ("" if tp_ok else "; TP incomplete (safe_but_incomplete)"),
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
            f"emergency reduceOnly close ({trigger})", correlation_id=intent_id)
        result = self._submit_close(intent_id, trigger, emergency=True)
        self.ledger.engage_kill(f"{trigger}; emergency close executed for {intent_id}")
        if result.get("success"):
            # 紧急平仓成功 ≠ 开仓成功：整体操作失败并熔断，禁止一切新开仓
            result = {
                **result, "success": False, "halt": True,
                "reason": f"{trigger}; emergency flatten succeeded; kill switch engaged",
            }
        return result

    def _submit_close(self, intent_id: str, reason: str, emergency: bool) -> Dict[str, Any]:
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
                    "state": "RECOVERY_REQUIRED", "reason": "position UNKNOWN"}

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
                    "reason": "already flat"}

        tag = "CLOSE-EMG" if emergency else "CLOSE"
        cid = f"{intent_id}-{tag}"
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
                    "state": "RECOVERY_REQUIRED", "reason": str(exc)}
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
                    "state": "RECOVERY_REQUIRED", "reason": str(exc)}

        self.ledger.update_order(cid, state="FILLED",
                                 exchange_order_id=ack.exchange_order_id,
                                 filled_qty=ack.filled_qty, avg_price=ack.avg_price)
        self._apply_fills(cid)

        if self._exchange_flat():
            self.ledger.transition_intent(
                intent_id, IntentState.CLOSED, f"close confirmed flat ({reason})",
                correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.RECONCILED, "ledger matches exchange",
                correlation_id=intent_id)
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.KNOWN_FLAT, source="close", note=reason)
            return {"success": True, "intent_id": intent_id, "state": "RECONCILED"}

        self.ledger.transition_intent(
            intent_id, IntentState.RECOVERY_REQUIRED,
            "close filled but position not zero", correlation_id=intent_id)
        self.ledger.engage_kill(f"post-close non-zero position {intent_id}")
        self.ledger.set_position_fact(
            self.symbol, PositionFactState.UNKNOWN, source="close", note="non-zero after close")
        return {"success": False, "intent_id": intent_id,
                "state": "RECOVERY_REQUIRED", "reason": "position not zero after close"}

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
            if cancel_unknown:
                self.ledger.transition_intent(
                    iid, IntentState.RECOVERY_REQUIRED,
                    f"exchange-side close detected but sibling cancel/query unknown"
                    f" ({'+'.join(fired) if fired else 'external close'})",
                    correlation_id=iid)
                self.ledger.set_position_fact(
                    self.symbol, PositionFactState.UNKNOWN,
                    source="reconcile", note=f"sibling cancel unknown {iid}")
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
            elif pf.status == "CANCELLED":
                self.ledger.update_order(order["client_order_id"], state="CANCELLED")

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

        for tag, kind, deficit in (
            ("SL-TOPUP", OrderKind.STOP_LOSS, deficits["SL"]),
            ("TP-TOPUP", OrderKind.TAKE_PROFIT, deficits["TP"]),
        ):
            if deficit <= 1e-12:
                continue
            cid = self._leg_cid(intent_id, tag)
            try:
                sl_px, tp_px = self._protect_prices(intent_id)
                self._place_protection_leg(
                    intent_id, cid, kind, side, deficit,
                    stop_price=sl_px if tag.startswith("SL") else tp_px)
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

        def _recovery(reason: str) -> Dict[str, Any]:
            self.ledger.transition_intent(
                intent_id, IntentState.RECOVERY_REQUIRED, reason,
                correlation_id=intent_id)
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
            # 修复期间已平仓：不重建，直接对账收敛
            self.ledger.transition_intent(
                intent_id, IntentState.CLOSING,
                "flat confirmed during repair", correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.CLOSED,
                "already flat on exchange", correlation_id=intent_id)
            self.ledger.transition_intent(
                intent_id, IntentState.RECONCILED,
                "ledger matches exchange after repair-time close",
                correlation_id=intent_id)
            self.ledger.set_position_fact(
                self.symbol, PositionFactState.KNOWN_FLAT, source="repair")
            return {"success": True, "intent_id": intent_id,
                    "state": "RECONCILED", "reason": "flat during repair"}

        remaining = abs(pos.signed_qty)
        side = "LONG" if pos.signed_qty > 0 else "SHORT"

        # 3) 先提交并确认强制腿 SL
        self.ledger.transition_intent(
            intent_id, IntentState.PROTECTION_SUBMITTING,
            f"rebuild mandatory SL for remaining {remaining}",
            correlation_id=intent_id)
        try:
            sl_px, tp_px = self._protect_prices(intent_id)
            self._place_protection_leg(
                intent_id, self._leg_cid(intent_id, "SL-R"),
                OrderKind.STOP_LOSS, side, remaining, stop_price=sl_px)
        except SubmitUnknownError as exc:
            return _recovery(f"mandatory SL rebuild result unknown: {exc}")
        except OrderRejectedError as exc:
            self.ledger.transition_intent(
                intent_id, IntentState.PROTECTION_FAILED,
                f"mandatory SL rebuild rejected: {exc}", correlation_id=intent_id)
            return self._emergency_close(
                intent_id, trigger="mandatory SL rebuild failed")

        # 4) 再提交可选腿 TP；仅 TP 失败 = 安全但不完整，不紧急平仓
        tp_ok = True
        try:
            self._place_protection_leg(
                intent_id, self._leg_cid(intent_id, "TP-R"),
                OrderKind.TAKE_PROFIT, side, remaining, stop_price=tp_px)
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

    def _protect_prices(self, intent_id: str) -> tuple:
        sl, tp = 99.0, 101.0
        cached = self._protect_px.get(intent_id)
        if cached:
            sl, tp = float(cached[0]), float(cached[1])
        for order in self.ledger.orders_for_intent(intent_id):
            px = order.get("stop_price")
            if px is None:
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
        """ledger-first 挂保护腿；提交结果同步到账本。"""
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
            self.ledger.update_order(
                cid, state="ACTIVE" if ack.status == "NEW" else "FILLED",
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
        """迟到 Fill 事件分类处理（证据门控，P0-B2.2 修正）。

        DUPLICATE           fill_id 已存在 → 无经济影响
        COVERED_BY_FACT     存在明确把该 venue trade ID 列为已覆盖的
                            reconciliation fact → 仅关联审计，不重复记账。
                            累计数量"容得下"不再构成证据。
        SYNTHETIC_REPLACED  与未匹配合成调整确定性替换（同订单同数量）→
                            撤销合成经济影响、写入真实价格/费用/PnL，
                            仓位数量不重复变化
        LATE_NEW_FILL       无任何证据 → 修正订单累计成交/费用/PnL、拉取仓位、
                            重算保护；终态意图经证据门控逃逸边进入
                            RECOVERY_REQUIRED 并熔断
        """
        if self.ledger.fill_exists(fill.fill_id):
            return {"class": "DUPLICATE", "fill_id": fill.fill_id}

        order = self.ledger.get_order(fill.client_order_id)
        if order is None:
            # 孤儿成交：本地无订单可归属 —— 无法安全入账，直接熔断
            self.ledger.engage_kill(f"orphan fill event {fill.fill_id}")
            return {"class": "ORPHAN", "fill_id": fill.fill_id,
                    "action": "MANUAL_RECOVERY"}

        # 证据一：reconciliation fact 明确覆盖该 venue trade ID
        fact_id = self.ledger.evidence_covers_fill(fill.fill_id)
        if fact_id:
            realized = self._realized_pnl(order, fill)
            inserted = self.ledger.insert_fill(
                fill.fill_id, fill.client_order_id, fill.qty, fill.price,
                fill.fee, fill.side, fill.filled_at, realized_pnl=realized,
                covered_by_fact_id=fact_id, economic_effect_applied=False)
            if not inserted:
                return {"class": "DUPLICATE", "fill_id": fill.fill_id}
            return {"class": "COVERED_BY_FACT", "fill_id": fill.fill_id,
                    "evidence_fact_id": fact_id,
                    "order": fill.client_order_id, "realized_pnl": realized}

        # 证据二：确定性替换未匹配的合成调整
        synthetic = next(
            (s for s in self.ledger.open_synthetic_fills(fill.client_order_id)
             if abs(float(s["qty"]) - fill.qty) <= 1e-9), None)
        if synthetic is not None:
            realized = self._realized_pnl(order, fill)
            inserted = self.ledger.insert_fill(
                fill.fill_id, fill.client_order_id, fill.qty, fill.price,
                fill.fee, fill.side, fill.filled_at, realized_pnl=realized,
                replaces_synthetic_fill_id=synthetic["fill_id"])
            if inserted:
                self.ledger.mark_synthetic_replaced(
                    synthetic["fill_id"], fill.fill_id)
            return {"class": "SYNTHETIC_REPLACED", "fill_id": fill.fill_id,
                    "replaces": synthetic["fill_id"],
                    "realized_pnl": realized,
                    "order_qty_unchanged": True}

        # ---- LATE_NEW_FILL：无证据的新交易所事实 ----
        economic = sum(
            f["qty"] for f in self.ledger.fills_for_order(fill.client_order_id))
        realized = self._realized_pnl(order, fill)
        self.ledger.insert_fill(
            fill.fill_id, fill.client_order_id, fill.qty, fill.price,
            fill.fee, fill.side, fill.filled_at, realized_pnl=realized)

        new_filled = round(economic + fill.qty, 10)
        state = "FILLED" if new_filled >= float(order["quantity"]) - 1e-9 \
            else "PARTIALLY_FILLED"
        self.ledger.update_order(
            fill.client_order_id, state=state, filled_qty=new_filled)

        self._refresh_position_fact()
        pos = self._safe_position()

        intent = self.ledger.get_intent(order["intent_id"])
        intent_state = IntentState(intent["state"]) if intent else None
        if intent_state in (
            IntentState.RECONCILED, IntentState.REJECTED, IntentState.CLOSED,
        ):
            self.ledger.transition_intent(
                order["intent_id"], IntentState.RECOVERY_REQUIRED,
                f"EXCHANGE_FACT_CORRECTION late venue fact invalidates "
                f"terminal state (fill {fill.fill_id} qty {fill.qty})",
                correlation_id=order["intent_id"],
                exchange_fact=(f"late-fill:{fill.fill_id}", fill.fill_id))
            self.ledger.engage_kill(f"late fill after terminal state {fill.fill_id}")
        elif intent_state == IntentState.PROTECTED:
            self.sync_protection(order["intent_id"])

        return {"class": "LATE_NEW_FILL", "fill_id": fill.fill_id,
                "order": fill.client_order_id, "new_filled_qty": new_filled,
                "realized_pnl": realized,
                "position_after": abs(pos.signed_qty) if pos else None}

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

    def _apply_fills(self, client_order_id: str) -> None:
        order = self.ledger.get_order(client_order_id)
        for fill in self.exchange.fills(client_order_id):
            realized = self._realized_pnl(order, fill) if order else 0.0
            inserted = self.ledger.insert_fill(
                fill.fill_id, fill.client_order_id, fill.qty, fill.price,
                fill.fee, fill.side, fill.filled_at, realized_pnl=realized)
            if not inserted:
                continue  # 重复 Fill 事件不重复记账

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
