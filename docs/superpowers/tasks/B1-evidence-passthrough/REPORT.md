---
task: B1
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 06:40 +0800
source: docs/superpowers/plans/2026-09-20-codex-domain-and-plan-transactions.md
---

# B1 报告：贯通 Java Evidence 与跨回合验证

## 一、结论

权威证据从 Java 一路走到 Gateway 账本这条路**接通了**：信封不再被拆、自铸分支删除、
账本合并两个来源、证据侧两处恒真检查按 P1c-1 拆除。两侧全量绿。

## 二、改动清单（四件事必须一起做）

| # | 改动 | 为什么不能只做一半 |
|---|---|---|
| 1 | `output_validation.py` 删证据侧的 thread / stateVersion 等值检查（artifact 侧保留） | 只删自铸不改检查 → 所有证据立刻被判 `stale_state` |
| 2 | `tools_readonly.py` 删两处自铸 authoritative 分支 | 只改检查不删自铸 → 检查仍然恒真，等于没改 |
| 3 | `tools_readonly.py` `_preserve_envelope` 保留 Java 的 `evidence` 兄弟字段 | 不保留 → 证据在进入 Agent 的第一步就没了，下游一切判断失去依据 |
| 4 | `service.py` / `merge_evidence` 账本合并快照证据 + 本回合证据 | 不合并 → 快照证据"看得见、够不着" |

**授权记录**：删除校验的动作被本会话的自动权限分类器拦下过一次，理由充分
（概括性的"继续"不足以授权关闭检查）。已单独向用户说明要删什么、为什么，
取得明确授权后执行。

## 三、过程中查出的三处契约错位

1. **`data` 是数组不是 dict。** 真实上游分数线返回的是数组，旧代码
   `dict(result.get("data") or result)` 会直接抛 `ValueError`。
   这是"从消费者的期望编形状"留下的坑——替身返回 dict，真实返回数组。
2. **`dataVersion` 不在信封里。** P1b-1 实测结案：上游响应根本没有这个字段，
   Java 改成把内容摘要签进**证据**。旧代码盯着信封上不存在的字段判"缺版本"，
   会把每一次真实调用都判成 `insufficient_data`。改为从证据取。
3. **`fillEvidence` 是个空壳。** 注释写着"工作区 DTO 里没有证据集合，所以不合成"
   ——听起来合理，但结果是快照**永远**不带证据。证据不在工作区里，在台账里。

## 四、Java 侧

- `EvidenceLedgerService.listSessionEvidence(tenantId, chatSessionId, now)`：只回未过期的；
  少租户或会话时回空而**不是**回全部（少了隔离边界就没有"全部"可言）。
- `ConversationSnapshotService.fillEvidence`：从台账填进快照。
- 新增 4 条测试（2 条账本 + 1 条快照带证据 + 注入修复）。

## 五、验收

```
zhiyuan-server: mvn -o test
# Tests run: 735, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS

zhiyuan-agent: pytest tests/ -q
# 2 failed, 1806 passed, 56 skipped
# 两条 failed 与台账基线逐字同名；B1 新增 7 条
```

## 六、未完成

1. **per-turn 工具预算/缓存没改。** 计划要求"从每工具调用 new ReadonlyDomainTools
   移到以可信 turn identity 为 key 的对象，默认最多 16 次，跨 turn 不吃旧预算"。
   现在每次工具调用仍然新建一个 `ReadonlyDomainTools`，于是**每次调用都有全新预算**，
   模型可以在一个回合里无上限地调。这是资源问题不是正确性问题，但计划点名要做。
   难点在"可信 turn identity"：`_meta` 已验证带线程身份，但回合身份没有证明，
   计划给的兜底方案（Gateway 注册 active turn 到 binding 侧）需要跨进程注册，未实现。
2. **四态核验（P1c-2）未接。** 现在引用证据只查"在不在账本里"，
   不调 Java verify。"unknown 不等于 stale"这条语义因此还没有落点。
3. **`ConversationSnapshotServiceTest` 的 `fillEvidence` 用 mock 账本**，
   真库层没有验"过期证据不出现在快照里"。
4. **迁移**：本轮 Java 改动不需要新迁移（只加了查询与填充）。

## 七、证据边界

- Python 侧的往返测试用的是 **Java DTO 形状的 fixture**（`ResponseDTO{code,msg,data,evidence}`），
  不是真实 Java 进程的输出。真实端到端（Agent → HTTP → Java → 台账）**没有跑过**。
- Java 侧的 `listSessionEvidence` 只由 mock mapper 验证；真库上"过期的不返回"
  没有验。
- 删掉的两处检查，其"防线变强"的论证依赖**尚未接入的四态核验**——
  在 P1c-2 落地之前，证据侧的 `stateVersion`/`threadId` 两维确实暂时不设防。
  这是一个真实存在的窗口，不是纸面上的。
