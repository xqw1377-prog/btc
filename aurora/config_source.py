"""G0-5A Runtime identity & config isolation：唯一配置真源。

规则（冻结）：
- 显式 env 文件路径，默认仓库根 ``.env``；绝不向上级目录搜索
  （无文件名搜索、无逐级探测）。
- 进程环境优先于文件同名键；本模块**从不改写 os.environ**——
  取值一律经 :attr:`values` 显式传递给下游
  （``p0_boundary.resolve_mode(environ=...)`` 等均已支持注入）。
- 导入本模块零副作用：不读文件、不读环境快照以外的东西；
  加载只发生在显式 :meth:`load` 调用。
- 交易相邻入口（production_main / safety_check / dashboard_feed /
  ops_position_mode / ArmedRuntime 的调用方）必须从同一 ConfigSource
  取值，禁止各自加载环境文件到进程环境。

ops_testnet_probe 不在本包范围，不得借 G0-5 一并落地。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from aurora.p0_boundary import RunMode, resolve_mode


def repo_default_env_file() -> str:
    """仓库根 ``.env`` 的显式绝对路径（由本文件位置推导，不经搜索）。"""
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, ".env"))


@dataclass
class ConfigSource:
    """解析后的配置快照：env_file + 合并值 + 派生的运行身份要素。"""

    env_file: str
    values: Dict[str, str] = field(default_factory=dict)
    loaded_from_disk: bool = False

    @classmethod
    def load(
        cls,
        env_file: Optional[str] = None,
        environ: Optional[Dict[str, str]] = None,
    ) -> "ConfigSource":
        """显式加载。进程环境键优先；文件缺失不报错（记录 loaded_from_disk）。"""
        src = os.environ if environ is None else environ
        path = os.path.abspath(env_file or repo_default_env_file())
        file_values: Dict[str, str] = {}
        loaded = False
        if os.path.isfile(path):
            # dotenv_values 只解析不注入：os.environ 保持零改写。
            from dotenv import dotenv_values

            parsed = dotenv_values(path)
            file_values = {
                k: v for k, v in (parsed or {}).items() if v is not None
            }
            loaded = True
        merged = dict(file_values)
        for key in src:
            merged[key] = src[key]  # 进程环境优先（含显式空串=明确置空）
        return cls(env_file=path, values=merged, loaded_from_disk=loaded)

    def get(self, key: str, default: str = "") -> str:
        return (self.values.get(key) or default).strip()

    def as_environ(self) -> Dict[str, str]:
        """供 p0_boundary.* (environ=...) 消费的只读映射。"""
        return self.values

    def mode(self) -> RunMode:
        return resolve_mode(self.as_environ())

    def config_summary(self) -> Dict[str, str]:
        """可审计的配置身份摘要（不含任何密钥值）。"""
        return {
            "env_file": self.env_file,
            "env_file_loaded": str(self.loaded_from_disk),
            "trading_mode": self.mode().value,
            "expected_position_mode": self.get("AURORA_EXPECTED_POSITION_MODE") or "HEDGE",
            "account_exclusivity": self.get("AURORA_ACCOUNT_EXCLUSIVITY") or "false",
            "ledger_path_override": self.get("AURORA_LEDGER_PATH"),
            "p0_state_override": self.get("AURORA_P0_STATE"),
        }
