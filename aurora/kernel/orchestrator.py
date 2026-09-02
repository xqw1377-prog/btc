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

from .ledger import Ledger, PositionFactState
from .port import (
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

    # ---------- 公共 API ----------

    def recover(self) -> Dict[str, Any]:
        """启动恢复：解决未决订单 + 以交易所为真源重建持仓事实。"""
        report = {"resolved": [], "unresolved": [], "kill_engaged": False}

        for order in self.ledger.pending_orders():
            intent_id = order["intent_id"]
            cid = order["client_order_id"]
            fact = self.exchange.query_order(cid)
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
                else:
                    self.ledger.update_order(cid, state="ACTIVE" if fact.status == "NEW" else "FILLED")
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
        # 仍处于 PROTECTED 的意图：按入场单最新事实补足保护量（OUO）
        for intent in self.ledger.list_intents(states=[IntentState.PROTECTED.value]):
            self.sync_protection(intent["intent_id"])
        kill = self.ledger.kill_state()
        report["kill_engaged"] = bool(kill["engaged"])
        return report

    def open_position(
        self, side: str, quantity: float,
        intent_id: Optional[str] = None, reason: str = "manual",
    ) -> Dict[str, Any]:
        kill = self.ledger.kill_state()
        if kill["engaged"]:
            return self._refuse(f"kill switch engaged: {kill['reason']}")

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

        ok = True
        for tag, kind in (("SL", OrderKind.STOP_LOSS), ("TP", OrderKind.TAKE_PROFIT)):
            cid = f"{intent_id}-{tag}"
            try:
                self.ledger.record_order_submitting(
                    client_order_id=cid, intent_id=intent_id,
                    order_kind=kind.value,
                    side="SELL" if side == "LONG" else "BUY", position_side=side,
                    quantity=filled_qty, stop_price=99.0 if tag == "SL" else 101.0,
                    reduce_only=True,
                )
            except Exception as exc:
                raise _LedgerWriteFailed(str(exc)) from exc
            req = OrderRequest(
                client_order_id=cid, symbol=self.symbol, order_kind=kind,
                side="SELL" if side == "LONG" else "BUY", position_side=side,
                quantity=filled_qty,
                stop_price=99.0 if tag == "SL" else 101.0, reduce_only=True,
            )
            try:
                ack = self.exchange.submit_order(req)
                # 保护单挂上即处于工作状态（ACTIVE）；成交留待交易所触发后对账入账
                self.ledger.update_order(
                    cid,
                    state="ACTIVE" if ack.status == "NEW" else "FILLED",
                    exchange_order_id=ack.exchange_order_id,
                    filled_qty=ack.filled_qty, avg_price=ack.avg_price)
            except (OrderRejectedError, SubmitUnknownError) as exc:
                self.ledger.update_order(cid, state="REJECTED")
                ok = False
                break

        if not ok:
            self.ledger.transition_intent(
                intent_id, IntentState.PROTECTION_FAILED,
                "protection unconfirmed within deadline", correlation_id=intent_id)
            return self._emergency_close(intent_id, trigger="protection failed")

        self.ledger.transition_intent(
            intent_id, IntentState.PROTECTED,
            f"SL/TP confirmed for qty={filled_qty}", correlation_id=intent_id)
        self.ledger.set_position_fact(
            self.symbol, PositionFactState.KNOWN_OPEN, qty=filled_qty, side=side,
            source="protection", note="protected")
        return {"success": True, "intent_id": intent_id, "state": "PROTECTED",
                "protected_qty": filled_qty}

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
        pos = self.exchange.position(self.symbol)
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
        pos = self.exchange.position(self.symbol)
        if pos is None or abs(pos.signed_qty) >= 1e-12:
            return  # 交易所仍有仓位或事实不可知：不收敛

        for intent in self.ledger.list_intents(states=[IntentState.PROTECTED.value]):
            iid = intent["intent_id"]
            fired = []
            for order in self.ledger.orders_for_intent(iid):
                if order["order_kind"] not in ("STOP_LOSS", "TAKE_PROFIT"):
                    continue
                cid = order["client_order_id"]
                fact = self.exchange.query_order(cid)
                if fact.status == "FILLED":
                    self._apply_fills(cid)
                    self.ledger.update_order(
                        cid, state="FILLED", filled_qty=fact.filled_qty,
                        avg_price=fact.avg_price)
                    fired.append(order["order_kind"])
                elif fact.status == "NEW":
                    # OCO 兄弟腿撤销：仓位已平，残留保护单成为孤儿挂单
                    if self.exchange.cancel_order(cid):
                        self.ledger.update_order(cid, state="CANCELLED")
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
        """OUO 语义：入场单后续成交增量超过已保护量时，为差额补挂保护腿。

        吸收自 NautilusTrader bracket 的 update-on-update：部分成交→补量→
        再成交，保护数量必须跟随实际持仓，否则出现裸奔增量。
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
        fact = self.exchange.query_order(entry["client_order_id"])
        filled = fact.filled_qty if fact.status != "NOT_FOUND" else entry["filled_qty"]
        if fact.status in ("FILLED", "PARTIALLY_FILLED"):
            self._apply_fills(entry["client_order_id"])
            self.ledger.update_order(
                entry["client_order_id"],
                state="FILLED" if fact.status == "FILLED" else "PARTIALLY_FILLED",
                filled_qty=fact.filled_qty, avg_price=fact.avg_price)

        # 保护覆盖量 = 每侧（SL/TP 各自覆盖全部持仓）数量之和的最大值，
        # 而不是两腿相加——两腿是同一仓位的两个退出路径
        leg_totals = {"STOP_LOSS": 0.0, "TAKE_PROFIT": 0.0}
        for o in self.ledger.orders_for_intent(intent_id):
            if o["order_kind"] in leg_totals and o["state"] in ("SUBMITTING", "ACTIVE", "FILLED"):
                leg_totals[o["order_kind"]] += o["quantity"]
        protected = max(leg_totals.values())
        delta = round(filled - protected, 10)
        if delta <= 1e-12:
            return {"success": True, "intent_id": intent_id, "protected_qty": protected,
                    "reason": "protection already matches filled qty"}

        side = intent["side"]
        for tag, kind in (("SL-TOPUP", OrderKind.STOP_LOSS),
                          ("TP-TOPUP", OrderKind.TAKE_PROFIT)):
            cid = f"{intent_id}-{tag}"
            try:
                self.ledger.record_order_submitting(
                    client_order_id=cid, intent_id=intent_id, order_kind=kind.value,
                    side="SELL" if side == "LONG" else "BUY", position_side=side,
                    quantity=delta, stop_price=99.0 if tag.startswith("SL") else 101.0,
                    reduce_only=True,
                )
            except Exception as exc:
                raise _LedgerWriteFailed(str(exc)) from exc
            req = OrderRequest(
                client_order_id=cid, symbol=self.symbol, order_kind=kind,
                side="SELL" if side == "LONG" else "BUY", position_side=side,
                quantity=delta,
                stop_price=99.0 if tag.startswith("SL") else 101.0, reduce_only=True,
            )
            try:
                ack = self.exchange.submit_order(req)
                self.ledger.update_order(
                    cid, state="ACTIVE" if ack.status == "NEW" else "FILLED",
                    exchange_order_id=ack.exchange_order_id,
                    filled_qty=ack.filled_qty, avg_price=ack.avg_price)
            except (OrderRejectedError, SubmitUnknownError) as exc:
                self.ledger.update_order(cid, state="REJECTED")
                # 走合法路径标记保护失败；PROTECTED 状态无 PROTECTION_FAILED
                # 出边，直接进入紧急平仓（PROTECTED→CLOSING 合法）
                current = IntentState(self.ledger.get_intent(intent_id)["state"])
                if current in (IntentState.FILLED_UNPROTECTED, IntentState.PROTECTION_SUBMITTING):
                    self.ledger.transition_intent(
                        intent_id, IntentState.PROTECTION_FAILED,
                        f"protection top-up rejected (delta={delta})",
                        correlation_id=intent_id)
                elif current == IntentState.PARTIALLY_FILLED:
                    self.ledger.transition_intent(
                        intent_id, IntentState.FILLED_UNPROTECTED,
                        "top-up rejected; position unprotected", correlation_id=intent_id)
                    self.ledger.transition_intent(
                        intent_id, IntentState.PROTECTION_FAILED,
                        f"protection top-up rejected (delta={delta})",
                        correlation_id=intent_id)
                return self._emergency_close(
                    intent_id, trigger="protection top-up failed")

        total = protected + delta
        # 持仓事实唯一真源是交易所（_refresh_position_fact）；
        # 此处不得用入场成交量覆写——保护腿可能已部分触发
        return {"success": True, "intent_id": intent_id, "protected_qty": total,
                "topped_up": delta}

    def _apply_fills(self, client_order_id: str) -> None:
        for fill in self.exchange.fills(client_order_id):
            inserted = self.ledger.insert_fill(
                fill.fill_id, fill.client_order_id, fill.qty, fill.price,
                fill.fee, fill.side, fill.filled_at)
            if not inserted:
                continue  # 重复 Fill 事件不重复记账

    def _exchange_flat(self) -> bool:
        pos = self.exchange.position(self.symbol)
        return pos is not None and abs(pos.signed_qty) < 1e-12

    def _refresh_position_fact(self) -> None:
        pos = self.exchange.position(self.symbol)
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
