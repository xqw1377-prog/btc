"""P1-GOV-3：LIVE endpoint 正式合同（从 PLANNED 落地）。

背景事实（G0-4D 探测实测）：
- SDK Client(testnet=False) 构造期会 ping 现货 api.binance.com；
- 交易期请求走 fapi.binance.com；
- 现行 ALLOWED_LIVE_HOSTS 只含 fapi → 未满授权的 armed-LIVE 在构造前
  拒绝（BLOCKED_BEFORE_CLIENT）。这是策略正确行为，本合同将其形式化。

合同（冻结）：
1) 主机集合按阶段定义：
   LIVE_CONSTRUCTION_HOSTS = {"api.binance.com", "fapi.binance.com"}
   LIVE_TRADING_HOSTS     = {"fapi.binance.com"}
2) 构造集只在【完整 LIVE 授权事实】成立时激活：
   dual-auth 环境齐 + AURORA_ARM_LIVE 武装令牌 + LIVE endpoint 合同
   版本匹配。任一缺失 → 维持默认集（仅 fapi）→ 构造期 spot ping
   被出网守卫拒绝 → BLOCKED_BEFORE_CLIENT。
3) 未授权状态绝不因"改白名单方便测试"而放宽；授权状态缺 spot 主机
   同样违约（构造必然失败，必须显式暴露而非静默）。
4) 本模块只做判定与说明，不构造客户端、不出网。
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Optional

from aurora.p0_boundary import (
    ALLOWED_LIVE_HOSTS,
    RunMode,
    SafetyViolation,
    live_execution_armed,
)

LIVE_ENDPOINT_CONTRACT_VERSION = "live-endpoint-v1"

LIVE_CONSTRUCTION_HOSTS: FrozenSet[str] = frozenset(
    {"api.binance.com", "fapi.binance.com"})
LIVE_TRADING_HOSTS: FrozenSet[str] = frozenset({"fapi.binance.com"})


def live_authorization_facts(
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, bool]:
    """收集完整 LIVE 授权事实（不校验、只观察）。"""
    import os

    src = environ or os.environ
    return {
        "dual_auth": (
            (src.get("ALLOW_LIVE_TRADING") or "").strip().lower() == "true"
            and (src.get("AURORA_LIVE_CONFIRM") or "").strip()
            == "I_UNDERSTAND_LIVE_RISK"
        ),
        "arm_token": live_execution_armed(src),
        "endpoint_contract": (
            (src.get("AURORA_LIVE_ENDPOINT_CONTRACT") or "").strip()
            == LIVE_ENDPOINT_CONTRACT_VERSION),
    }


def effective_live_hosts(environ: Optional[Dict[str, str]] = None,
                         ) -> FrozenSet[str]:
    """按授权事实给出 LIVE 出网允许集。

    未满授权 → 默认集（仅 fapi，保持 BLOCKED_BEFORE_CLIENT 行为）。
    完整授权 → 构造集（含 spot ping 主机）。
    """
    facts = live_authorization_facts(environ)
    if all(facts.values()):
        return LIVE_CONSTRUCTION_HOSTS
    return ALLOWED_LIVE_HOSTS


def assert_live_endpoint_policy(
    host: str,
    phase: str = "construction",
    environ: Optional[Dict[str, str]] = None,
) -> None:
    """阶段化主机断言：策略不满足 → 构造/请求前拒绝（fail closed）。

    phase: "construction"（允许 spot+fapi）或 "trading"（仅 fapi）。
    即使完整授权，交易阶段出现 spot 主机也是违约（显式暴露）。
    """
    if phase not in ("construction", "trading"):
        raise SafetyViolation(f"unknown endpoint phase {phase!r}")
    allowed = (
        LIVE_CONSTRUCTION_HOSTS if phase == "construction"
        else LIVE_TRADING_HOSTS)
    facts = live_authorization_facts(environ)
    if not all(facts.values()) and host in (
            LIVE_CONSTRUCTION_HOSTS - ALLOWED_LIVE_HOSTS):
        raise SafetyViolation(
            "[LIVE-ENDPOINT] host not reachable without full LIVE "
            f"authorization (facts={facts}); refusing before client")
    if host not in allowed:
        raise SafetyViolation(
            f"[LIVE-ENDPOINT] host {host!r} not in {phase} host set {sorted(allowed)}")
