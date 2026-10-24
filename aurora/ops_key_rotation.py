"""TESTNET 密钥轮换核验工具（只读 + 指引，绝不代改 .env）。

用法（操作员在本地终端执行；密钥永不进入对话/代码/日志）：

  1. 在币安测试网控制台生成新 API key，删除旧 key。
  2. 把新 key/secret 写进一个临时 env 文件（如 /tmp/newkey.env）：
       BINANCE_API_KEY=...
       BINANCE_API_SECRET=...
  3. python3 -m aurora.ops_key_rotation --new-env /tmp/newkey.env
     → 只读核验新 key 可用、打印指纹与需要手动修改的 .env 行、
       提示命名空间状态的迁移要求。不写任何文件。
  4. 按指引手动改 .env → 再跑一次确认 ACCOUNT_IDENTITY 换绑。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, Optional

from aurora.config_source import ConfigSource, repo_default_env_file
from aurora.p0_boundary import RunMode, key_fingerprint


def verify_new_key(new_env_file: str) -> Dict[str, str]:
    """只读核验新 key：TESTNET 认证可用 + 计算指纹。"""
    source = ConfigSource.load(env_file=new_env_file)
    if source.mode() != RunMode.TESTNET:
        # 新 env 文件可不含 TRADING_MODE；默认按 TESTNET 校验
        values = dict(source.values)
        values["TRADING_MODE"] = "TESTNET"
        values.setdefault("TESTNET", "true")
        source = ConfigSource(env_file=new_env_file, values=values)
    key = source.get("BINANCE_API_KEY")
    if not key:
        raise SystemExit("[ROTATE] new env missing BINANCE_API_KEY")
    from aurora.safety import build_client

    client = build_client(RunMode.TESTNET, "key-rotation verification",
                          environ=source.as_environ())
    account = client.futures_account()
    if not isinstance(account, dict):
        raise SystemExit("[ROTATE] verification returned invalid payload")
    return {"status": "NEW_KEY_AUTHENTICATES",
            "newFingerprint": key_fingerprint(key),
            "note": "read-only authenticated GET succeeded"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TESTNET key rotation checker")
    ap.add_argument("--new-env", required=True,
                    help="临时 env 文件路径（含新 key/secret）")
    ap.add_argument("--current-env", default=None)
    args = ap.parse_args(argv)

    current = ConfigSource.load(
        env_file=args.current_env or repo_default_env_file())
    old_fp = key_fingerprint(current.get("BINANCE_API_KEY") or "")

    result = verify_new_key(os.path.abspath(args.new_env))
    new_fp = result["newFingerprint"]
    state_dir = os.path.join("state", "testnet")

    print(json.dumps({
        **result,
        "currentFingerprint": old_fp,
        "changed": new_fp != old_fp,
        "manualSteps": [
            f"编辑 .env：BINANCE_API_KEY / BINANCE_API_SECRET 换为新值",
            f"编辑 .env：AURORA_ACCOUNT_FINGERPRINT={new_fp}",
            f"命名空间状态目录随指纹变更：{state_dir}/{old_fp}/* → "
            f"按需归档；新目录 {state_dir}/{new_fp}/ 首次启动自动生成",
            "事故账本 state/kernel_ledger.db 不随轮换移动（历史事实）",
            "轮换后在币安控制台二次确认旧 key 已删除",
        ],
        "warranty": "本工具不写任何文件；.env 由操作员手动修改",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
