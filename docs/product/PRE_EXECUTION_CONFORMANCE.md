# PRE-EXECUTION CONFORMANCE

> 状态：**ALIGNED TO 6b2cc7c / NOT AUTHORIZED TO EXECUTE**  
> 边界真源：EXECUTION WORK PACKAGE `6b2cc7c`  
> 本包只把实现偏差对齐到冻结合同。**不是开工令。不是 permit。**

```text
PRE-EXECUTION CONFORMANCE      ALIGNED
EXECUTION BOUNDARY             FROZEN   6b2cc7c
EXECUTE_AUTHORIZED             FALSE
SCOPED PERMIT                  NOT ISSUED
REAL WRITE PATH                DENIED
SYSTEM EXECUTION               NOT QUALIFIED
LIVE                           NO-GO
```

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
                               + permit.session_id == execution session_id
                               + permit.single_use == true
                               + permit.scope == BTCUSDT/LONG/0.001
                               + permit.expiry valid
```

通过本包 ≠ 可以交易。下一步若要写 0.001，仍须另发引用 `6b2cc7c` 的开工令 + scoped permit。
