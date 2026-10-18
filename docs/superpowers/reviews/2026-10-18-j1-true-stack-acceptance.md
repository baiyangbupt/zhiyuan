# J1 旅程块真栈验收（2026-10-18）

## 部署与版本

- Java jar 重新打包：`zhiyuan-server/target/zhiyuan-server.jar`（2026-10-18 17:24）。
- Java 18290：pid 19547，`Started Application in 10.057 seconds`。
- Agent 18291：pid 21810（第二次重启加载 fresh 口径文案），
  `GET /health` 200；日志无 ERROR/Traceback。
- codex 插件：`1.0.0+codex.20261018092455`，已重装到
  `CODEX_HOME=/root/dev/zhiyuan/.local/codex-local/runtime-home`。
- 已提交 `f66b78a`（含同源码树前置批次；web 改动未提交）。
- 共享栈重启已获用户批准。

## 证据 1：turn-snapshot 返回完整 journey（会话 10041984）

`GET /gaotu-assistant-bot/inner/planning/1/session/turn-snapshot?chatSessionId=10041984`
（带 `X-Internal-Service-Token`）返回 `code=0`，顶层新增 `journey`：

```json
{
  "hasProfile": true,
  "profileMissing": [],
  "hasCandidates": true,
  "candidateEntryCount": 571,
  "candidateSourceVersion": 2,
  "hasPlan": true,
  "planEntryCount": 45,
  "orderedEntryCount": 45,
  "planInterpretable": true,
  "selectionTargetCount": null,
  "selectionCurrentCount": 45,
  "planVersion": 5,
  "planContentDigest": "bdbca1bd…",
  "candidateFreshness": "fresh",
  "planFreshness": "fresh",
  "planAdjustmentStale": true,
  "reviewFreshness": "fresh",
  "refreshRequirement": "none",
  "reviewSourceVersion": 4,
  "reviewStale": false,
  "tierQuotaGoal": false,
  "stale": true,
  "staleReasonCode": "plan_structure_changed",
  "staleMessage": "方案内容或顺序已调整，需要重新审查。",
  "pendingStatus": null
}
```

关键点：`planAdjustmentStale=true` 但 `planFreshness=fresh`、`reviewFreshness=fresh`，
证明“每次写方案都会置位 planAdjustment”不再误判方案数据过期（复审发现 #20）。

## 证据 2：只读回合按 freshness 推荐（会话 900040，用户 900002）

- 取票 + WS `/ws/chat` 一次只读回合（未占用 10041984 用户连接）。
- 第一问：“当前方案有多少条？现在最适合先做什么？”
  模型回答：**80 条**；“先按现在的成绩和条件把候选重新筛一遍……现有候选和当前
  档案已经对不上，想加、补、换现在都会被挡住”。与 snapshot 的
  `candidateFreshness=stale`、`refreshRequirement=candidates`、
  `recommended_next=recommend_candidates` 一致。
- 第二问（重启加载新口径后）：“规则审查现在是否最新？方案结构调整过吗？”
  模型回答：“规则审查现在是最新的……方案结构确实调整过……结构调整不等于规则
  审查过期，审查仍按最新算。” 证明注入块的新鲜度优先级覆盖了兼容 `staleFlags`
  文案（复审发现 #20/#21 的 Agent 侧收口）。

## 证据 3：applying 对账端点接线

`POST /gaotu-assistant-bot/inner/chat/1/session/pending/reconcile?chatSessionId=900040`
返回：

```json
{"data":{"pendingId":"fba9683a-…","revision":6,"pendingStatus":"applied",
"operationStatus":null,"outcome":"not_applying","resultCode":null,
"resultPlanVersion":null,"receiptAvailable":false},"code":0,"msg":"success"}
```

非 applying 幂等返回，未改状态、未重发命令。applying 的
succeeded/running/无台账分支已由 Java 单测覆盖（19 例）。

## 未在真栈覆盖 / 说明

1. `applying` 竞态（取快照后 claim 再写）用 Java 交错单测覆盖；真栈未人为制造。
2. working-only / 补录后 freshness 用 Java/Agent 单测覆盖；未改用户会话做真栈写入。
3. 900380 的 snapshot 触发 OSS `bucket does not exist`（合成会话没有志愿文件），
   是既有环境限制，与 J1 无关。
4. `PlanningStateServiceTest` 8 个既有 J5.2 失败未修（14→15 probe、策略/计数断言），
   与 J1 改动无关；J1 相关 Java 55 例、Python 全量 2897 passed / 33 skipped。
