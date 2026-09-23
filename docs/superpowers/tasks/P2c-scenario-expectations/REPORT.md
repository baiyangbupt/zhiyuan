---
task: P2c（P2 第 2 项）
status: DONE_WITH_CONCERNS
executor: 本地会话（2026-09-22）
finished_at: 2026-09-22 07:2x +0800
source: docs/superpowers/plans/2026-09-13-P0第二条验收条mixed-read-write的四个成因.md 第三节（成因 2）
---

# P2c 报告：把 mixed-read-write 的期望改对，并加一条 A 型姊妹场景

## 一、结论

计划书给的两条出路里**它自己有倾向**：「倾向 B，再加一个 A 型的姊妹场景」——照此执行：

- **B**：`mixed-read-write` 的期望放宽——`response_type` 接受 `{fact, clarification}`、
  `clarification_required` 不约束（原来 `False`）、`proposal_required` 撤掉（原来 `True`）。
  理由：场景里的 `school-3` **没有名字、不在候选集**，识别不出它是对的判断；
  旧期望却奖励了"闭眼给它提删除提案"（运行 1 提了就过），惩罚了"先问清楚"（运行 3 被判 mismatch）。
- **A 型姊妹场景** `mixed-read-write-unambiguous`：**同样的读+写请求**，
  唯一差别是 `school-3` 在候选集里有名字（丙大学）→ "第三个"可识别 → 这时**要求给提案**。
  只留 B 的话，一个"永远反问、从不提案"的实现也能全绿，等于把 P3 的写入门禁测没了。

## 二、交付

| 路径 | 变更 |
|---|---|
| `scripts/codex_semantic_smoke.py` | `mixed_read_write_scenario` 的期望按 B 放宽（含裁决理由的注释）；新增 `unambiguous_mixed_read_write_scenario()` 与 CLI 选项 `mixed-read-write-unambiguous` |

场景构造自检（跑之前先确认两条只差一个变量）：

```text
歧义  : 候选=[school-1, school-2]              response_type={fact, clarification} proposal_required=False
可识别: 候选=[school-1, school-2, school-3]    response_type={fact, clarification} proposal_required=True
```

## 三、验收（原始输出）

```text
── mixed-read-write（B，3 次）──
run 1: passed=False failures=['execution_status_mismatch', 'limitations_missing', 'next_step_missing'] responseType=fact proposalRef=无
run 2: passed=False failures=['response_type_mismatch', 'execution_status_mismatch', 'limitations_missing', 'next_step_missing'] responseType=text proposalRef=无
run 3: passed=False failures=['execution_status_mismatch', 'limitations_missing', 'next_step_missing'] responseType=fact proposalRef=无

── mixed-read-write-unambiguous（A，3 次）──
run 1: passed=False failures=['proposal_missing', 'execution_status_mismatch'] responseType=fact proposalRef=无
run 2: passed=False failures=['proposal_missing', 'execution_status_mismatch', 'limitations_missing', 'next_step_missing'] responseType=fact proposalRef=无
run 3: passed=False failures=['proposal_missing', 'execution_status_mismatch', 'limitations_missing', 'next_step_missing'] responseType=fact proposalRef=无
```

**B 的效果**：`proposal_missing` 在歧义场景里**消失了**（3/3）——不再因为"没给提案"扣分，
也不再因为"先问清楚"扣分（`clarification_required` 不约束）。

## 四、这次跑出来的新事实（**已更正**，见 P2d）

**初版结论（"模型把写请求整个忽略了"）是错的**，依据是当时能看到的 `trace`——
它少了 `executionStatus`/`limitations`/`nextStep` 三个键，而那是**冒烟的量具缺陷**
（`TurnOutput` 校验失败 → 走了手搓 trace 的分支），不是模型的行为。
P2d 查清了：模型的原始输出里 **`nextStep` 明确写着"请回复确认是否删除 plan-1 的第 3 个条目"**，
`limitations` 有 3 条，`executionStatus` 标了 `completed`。

所以真正的事实是：

| 场景 | 模型实际做了什么 | 失败项（P2d 修好量具之后） |
|---|---|---|
| 歧义（B） | 答读 + 列出限制 + **在 `nextStep` 里问**是否删除；`executionStatus` 标 `completed` | `execution_status_mismatch`（标了 completed 而写没做） |
| 可识别（A） | 同上，且**没有给提案** | `proposal_missing` + 同上 |

两条都指向同一件事：**读+写请求里，写的那半被"问了"或"跳过了"，而状态仍报 `completed`。**
A 那条"该给提案却只问了一句"是否算错，取决于"写操作该先问还是先提案"——**属设计裁决**，
本任务不改期望、只记事实。

## 五、边界与未做

- **没有**碰成因 1（`executionStatus`/`limitations`/`nextStep` 留空）——计划书规定它排最后；
- **没有**改任何其它场景的期望；`forbidden_tools` 的判定一行未动；
- **未做**：把"写请求被无视"变成一条正式验收（那要先定"该提案还是该反问"的判据，
  属设计裁决；本任务只把它作为观察如实记下）。
