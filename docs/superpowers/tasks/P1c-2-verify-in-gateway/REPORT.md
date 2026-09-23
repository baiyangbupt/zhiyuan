---
task: P1c-2
status: DONE_WITH_CONCERNS
executor: 本地会话（2026-09-22）
finished_at: 2026-09-22 05:5x +0800
source: docs/superpowers/tasks/P1c-2-verify-in-gateway/TASK.md
---

# P1c-2 报告：四态核验接入 Gateway + 第六章分流表 + 重查一次

## 一、结论

**核验这一步从"端点存在但没人调"变成"每次引用都问一次"**，并按设计文档第六章逐行分流。
两处改动各自独立：Java 那条修的是"版本记录缺失被判成 stale"（诊断污染），
Python 那条是新接入。

真栈上验过两条互为对照的路径（同一句事实题）：

```text
核验端点被代理打成 500 → 整轮硬失败：type=error、18 字"当前对话引擎暂时不可用"
                          日志：evidence verification unavailable: … code=500
                          用户侧**没有任何事实性回答**（不放行）
核验端点正常            → 同一句正常作答（17.2s，707 分）
backend 访问日志        → /internal/evidence/verify 200，入参带 evidenceIds=[ev_…]
```

第三条是**"接进去了没有"的独立证据**：只看前两条的话，一个"根本没调用核验"的实现
也能全绿（那就变成"仪表恒为 `[]`"的翻版）。

## 二、交付

| 路径 | 变更 | 验证 |
|---|---|---|
| `zhiyuan-server/.../EvidenceLedgerService.java` | `verifyOne`：`currentDataVersion` 返回空串 → `unknown`（不再 `stale`） | 单测（版本行缺失 → unknown；对照：摘要不同 → stale） |
| `zhiyuan-agent/app/util/internal_client.py` | 新增 `verify_evidence()`：调 `/internal/evidence/verify`，**失败转异常** | 见第四节 |
| `zhiyuan-agent/app/gateway/evidence_verification.py` | 新增：分流表纯函数（`classify` / `recheck_instruction` / `strip_evidence_refs`） | 9 条单测，六行逐行 |
| `zhiyuan-agent/app/gateway/service.py` | `evidence_verifier` 注入；`_settle_evidence`（分流 + 重查一次）；`_evidence_inputs`（重查后重建账本）；事件展开挪到核验之后 | 7 条流程单测 |
| `zhiyuan-agent/app/gateway/composition.py` / `app/server.py` | 接线（`gateway_evidence_verifier` 可覆盖） | 真栈 |
| `zhiyuan-agent/tests/unit/test_evidence_verification.py` | 新增 9 条 | 通过 |
| `zhiyuan-agent/tests/unit/test_gateway_evidence_flow.py` | 新增 7 条 | 通过 |

## 三、两条 fail-closed 的写法（本任务最要紧的地方）

| 情形 | 实现 | 为什么这么写 |
|---|---|---|
| 任一 `unknown` | `classify` 返回 `fail`，**不带重查指令** | 台账里没有就是没发生过；重试只会让模型把同一段编造再说一遍 |
| Java 不可达 | 客户端层**抛**，服务层转 `evidence_verification_unavailable`，不放行 | `http_client.post` 本身是"失败也返回 dict"的形状（异常 → `{"error":…, "success": False}`），对核验来说那是 **fail-open**：拿不到答案时它长得像"没有证据要核验"。这个转换就是本任务要防的那次手滑 |

`unknown` 那一行还**不区分输出类型**（散文里编造也是编造），只有 `stale`/`expired`
才看是不是被 `fact` 引用。

## 四、验收（原始输出）

```text
$ mvn -o -Dtest=EvidenceLedgerServiceTest test      → Tests run: 19, Failures: 0
$ mvn -o test                                        → Tests run: 786, Failures: 0, Skipped: 6
$ .venv/bin/python -m pytest tests/unit/test_evidence_verification.py \
      tests/unit/test_gateway_evidence_flow.py -q    → 16 passed
$ CODEX_TEST_REDIS_URL=… pytest tests/unit tests/integration -q
                                                     → 1 failed, 1932 passed, 35 skipped
```

那 1 条失败是 `test_dialog_quality_gate` 读缺失的 `session_volunteer_*.json`（旧账，
A7 报告第四节已记）。

**重查上限那条**断言的是**恰好一次**（`len(codex.turns) == 2` 且核验调用两次），
不是"小于等于"——写成 `<=` 的话，"一次都不重查"也会通过。

**真栈那条"打断依赖"**：设计文档要求不能用 mock 断言，所以用一个只把
`/internal/evidence/verify` 打成 500 的本地代理（其余路径透传），让 agent 指向它——
这样隔离出来的是"核验这一步在失败"，而不是"整个后端挂了所以什么都没跑成"。
代理脚本在 `/tmp/verify_breaker.py`（未入库；它是一次性验收工具，不是生产件）。

## 四之二、端到端（P1c-2 接入之后，整套验收 1 遍 × 16 case）

`14 通过 / 0 业务失败 / 2 环境失败`（`.runtime/zhiyuan-acceptance-p1c2.json`），
两次环境失败都不是本任务引入的：

| case | 用时 | 原因码 | 归属 |
|---|---|---|---|
| `policy-charter` | 180.1s | `turn_timeout` | 上游模型流卡住（与 A7 报告四之三记的是同一类） |
| `major-group-province` | 30.2s | `engine_unavailable` | 日志是 `output_schema_invalid`：模型与修复轮都没给出结构化输出（模型侧老毛病，T008 那一类） |

**没有出现** `dropping … cached thread binding`（重拉）或 `stdout line exceeded`——
即这次接入没有把链路带进任何已知的"进程/流"故障形状。本轮 `verify` 端点被调用 12 次
（backend 访问日志），核验确实在每一轮引用证据时发生。


## 六、真栈实测：重查那条路径的两种收场（2026-09-22）

重查平时很难碰到（要"证据在签发与核验之间失效"），所以用一个只在回合进行中反复改
`gaotu.batchList` 版本表摘要的小工具把它逼出来（`/tmp/flip_version.py`，一次性工具，
退出时还原；实测中我 kill 早了导致没还原，已手工补回并核对无 `FLIP-` 残留）。

```text
会话 900283：stale evidence cited (ids=[ev_01M32ZKR…]) → 重查
             模型回复："已按**完全相同的参数**重新取数（catalog.list_batches(areaId=330000…),
                       paramsDigest 5c0e…，与上一轮一致）" → 重新作答 ✓
会话 900284：stale evidence cited (ids=[ev_01M32ZMA…]) → 重查后**仍失效**
             → 整轮 fail closed：`evidence_recheck_failed`，用户拿到 18 字"引擎不可用" ✓
```

两条正是分流表里的一对：**给一次机会**，以及**只给一次**。回注指令里带 `paramsDigest`
是有效的——模型真的照着同样的参数重查了（回复里自己复述了参数摘要）。

## 五、边界与未做

- **没动** `output_validation.py` 的逐条检查、`listSessionEvidence`、`evidence_ledger` 参数的既有语义
  （后者收窄为"本回合工具结果的自洽性检查"，两层都要过——任务书要求的正是这个）。
- **分流表改过一行（2026-09-22 裁决，设计文档第六章已同步修订）**：原本"仅被非 `fact`
  输出引用 → 剥离引用"那一行**作废，失效一律重查**。依据是实测而不是偏好：全量 rollout
  统计（~200 回合）`fact` 引用证据 83 条、`clarification` **6 条**、`text` 3 条、`recommendation` 0 条；
  抽查那 6 条 `clarification`，**正文在报具体数字**（"已核到的事实……第一段控制线 494 分"）——
  剥离引用之后用户看得见的正文里仍带着可能失效的数字，而机器检查会通过。
  这消掉的是一个**用户可见**的形状，代价是多一轮重查。
- **未做**：`recheck` 之后如果拿到了新的证据、但新证据恰好又是 `unknown`，现在的处置是
  整轮 fail closed（不是再查一次）——这是"上限 1 次"的自然结果，但没有单独用例覆盖，
  只有"第二次仍 stale"那条。
