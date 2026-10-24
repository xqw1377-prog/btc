/** V2 capability semantics — must be visually distinct in UI */
export const CAP = Object.freeze({
  PARTIAL: "PARTIAL",
  PROPOSED: "PROPOSED",
  UNKNOWN: "UNKNOWN",
  FIXTURE: "FIXTURE",
  D2_HOLD: "D2 HOLD",
  STATIC_SNAPSHOT: "STATIC SNAPSHOT",
  READ_ONLY_SEMANTICS: "READ-ONLY-SEMANTICS",
  READ_ONLY_DECISION: "READ-ONLY-DECISION",
});

export const CAP_HINT = Object.freeze({
  PARTIAL: "有真实基础，能力不完整",
  PROPOSED: "产品已冻，工程未实现",
  UNKNOWN: "当前事实不可得",
  FIXTURE: "仅原型演示",
  "D2 HOLD": "D2 未接入 · BTC NAV 非权威",
  "STATIC SNAPSHOT": "静态快照 · 非实时 feed",
  "READ-ONLY-SEMANTICS": "只读语义链 · 非 live ingestion",
  "READ-ONLY-DECISION": "P3 统一资本判断 · 只读镜像",
});
