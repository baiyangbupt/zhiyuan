# P3：流程门禁（superpowers 手法迁移）

> 指派：待定（任务书由本地会话按推进计划 §五 + 2026-09-22 实测数据写）
> 来源：`docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md` 第五章
> 类型：**提示词/技能内容**（不是代码）
> 协议：`docs/superpowers/tasks/README.md`
> 前置：P1（权威证据台账）已完成——多数门禁的判定依据是"结论是否绑定权威证据"。

---

## 一、目标

把 superpowers 里那套"门禁"手法搬到志愿填报的主流程阶段上，**落点是那 6 个 skill 的语义**：

画像收集 → 候选探索 → 数据核验 → 方案生成 → 方案审查 → 用户确认 → 结果复盘

**计划书的映射表（照抄，不自行加行）**：

| superpowers 手法 | 志愿系统落点 |
|---|---|
| `<HARD-GATE>` 硬门禁标签 | 画像/成绩/选科不全 → 禁止生成方案，只能澄清 |
| 分类只能升级不能降级的棘轮 | 发现约束冲突时任务复杂度只能上调，不能退回简单答复 |
| ledger 状态文件对抗上下文压缩 | Snapshot/WorkingSet 增加阶段级"已完成/未完成"显式记录 |
| 受限词表汇报协议（四态） | 已有 `executionStatus`，扩展到阶段级 |
| implementer ≠ reviewer 双 agent | 方案生成与方案审查分离，审查侧接 `ReviewRuleRegistry` |
| 修复循环上限 + 强制记录裁决 | 方案调整反复不收敛 → 熔断交回用户，裁决写入会话记录 |
| verification-before-completion | 任何推荐结论必须绑定 P1 的权威 Evidence 才允许表述 |
| No-Placeholders 反模式清单 | 禁止"建议参考往年分数"这类无引用表述（**可 grep 校验**） |

**硬约束（计划书原文）**：**不得在 Gateway 增加关键词规则替代模型理解。**

---

## 二、为什么现在派：今晚的两条实测

1. **模型会在只读阶段尝试写操作。** `mixed-read-write` 场景 20 次里 **2 次**调用了
   `plan_apply`（带 `action` + `proposalId`），判定如实亮 `forbidden_tools`。
   拦截是好的（codex 的 `readOnlyHint: false` + 只读 sandbox 把它拦在派发之前，
   夹具那层甚至没被用到），**缺的是"不让它起念"**——而那正是 `<HARD-GATE>` 的职责。
2. **信息其实已经在上下文里，只是没人用它。** 快照里带 `allowedCapabilities`
   （实测值 `["catalog_read", "admission_read"]`）与 `planningStage`，也就是说
   "这一阶段允许做什么"**已经发给模型了**；门禁要做的不是再传一遍数据，
   而是**把许可与行为的对应关系写进技能语义**。

明细见 `tasks/P0-acceptance-measurement/REPORT.md`（含被抓现场的逐层核对）。

---

## 三、步骤

1. **逐个 skill 补门禁语义**（`zhiyuan-agent/skills/codex-marketplace/plugins/zhiyuan-codex-planner/skills/`
   下的 6 个：`profile-discovery` / `school-major-exploration` / `admission-fact-analysis` /
   `candidate-recommendation` / `plan-construction` / `plan-final-review`；入口
   `planner-routing` 负责把阶段判对）。
2. **每条门禁必须能说清"什么情况下它该拦住什么"**，且**能从现有场景里找到一条能证伪它的**。
   找不到对应场景的门禁，要么补场景、要么先不写——写一条量不到的门禁等于没有。
3. **技能是内容不是代码**：不许在 `app/` 里加"如果用户说 X 就拒绝"这类规则
   （计划书硬约束）。判定权留给模型，技能给的是判据与话术。
4. **改完必须重装才生效**（`update_plugin_cachebuster.py` → `codex plugin add …`，
   见 `CLAUDE.md` 的「Skills 机制」一节）。

---

## 四、验收

```bash
cd /root/dev/zhiyuan/zhiyuan-agent

# ① 主判据：只读阶段不再尝试写操作（可证伪，用的是现有量具）
.venv/bin/python scripts/measure_p0_acceptance.py 20
#    达标：mixed-read-write 的 failures 里 **不再出现 forbidden_tools**（20 次 0 次）

# ② 不回归
.venv/bin/python -m pytest tests/unit tests/integration -q
#    已知失败基线：tests/unit/test_dialog_quality_gate.py::…volunteer_fixture（缺文件，与本任务无关）
```

**② 的另一半（对照）**：改**之前**必须先把 ① 跑一遍留底——否则"改完没出现"分不清是门禁生效
还是这一轮运气好。今晚的留底是：`mixed-read-write` 20 次里 `forbidden_tools` **2 次**
（`P0-acceptance-measurement/REPORT.md`）。

---

## 五、边界

- **不改**任何场景期望（`forbidden_tool_names` 等一律不动）；
- **不改** Gateway / MCP server 的代码——本任务的改动面只有 skill 内容；
- **不动** `allowedCapabilities` 的取值（那是 Java 的事）；
- 门禁不等于"更啰嗦"：每条门禁要说的是"**什么不满足时不许做什么**"，不是加一段免责声明。
