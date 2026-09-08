# PRE-EXECUTION CONFORMANCE

> 状态：**ALIGNED TO 6b2cc7c / NOT AUTHORIZED TO EXECUTE**  
> 边界真源：EXECUTION WORK PACKAGE `6b2cc7c`  
> 本包只把实现偏差对齐到冻结合同。**不是开工令。不是 permit。**

```text
PRE-EXECUTION CONFORMANCE      ALIGNED     eb0536b / 6ed46be
EXECUTION BOUNDARY             FROZEN      6b2cc7c

EXECUTE_AUTHORIZED             FALSE
                               仍是写盘前门 ≠ legacy dead-man
EXECUTION AUTHORIZATION        NOT ISSUED
SCOPED PERMIT                  NOT ISSUED
REAL WRITE PATH                DENIED
SYSTEM EXECUTION               NOT QUALIFIED
LIVE                           NO-GO
```

五个 conformance 点已收平：exact 0.001、固定三腿 client ID、session 独立 ledger、新 harness restart、SELL+LONG 权威 close。  
`441 passed` ≠ 真实写授权。

## 对齐项

```text
1  qty                         必须 exactly 0.001
2  client id                   AURORA-CTR-<session>-ENTRY/SL/CLOSE
                               禁止 AURORA-CLOSE-*
3  qualification ledger        state/testnet/<fp>/qualification/<session-id>/ledger.db
4  restart recovery            停 runtime → 新 harness 实例 → recover
                               同进程 orch.recover() 不算通过
5  qualification close         SELL + LONG；实际 qty；ACK ≠ confirmed
                               权威 fill 或 position → FLAT
6  write gates                 构造写客户端之前同时满足
                               EXECUTE_AUTHORIZED == true
                               + 有效 scoped permit
                               + permit.session_id 精确匹配
                               + single_use = true
                               + scope 精确匹配 BTCUSDT / LONG / 0.001
                               + permit 未过期
                               + 正式 Execution Start Order 已签发
```

通过本包 ≠ 可以交易。下一步若要写 0.001，只接受明确引用 `6b2cc7c` 的 Execution Start Order，并配套唯一 session 的 scoped permit。在此之前 `WRITE = DENIED`。
