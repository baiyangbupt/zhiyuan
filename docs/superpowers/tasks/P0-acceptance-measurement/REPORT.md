---
task: P0 验收条测量
status: 首测 DONE（结论已被复跑取代，见文首）
executor: 本地会话（2026-09-22）
finished_at: 2026-09-22 08:0x +0800
source: docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md 第二章（P0 验收）；
        README.md 第六节修订后的判据形式
---

# P0 验收条测量：两个复杂场景各 20 次


> ## ⚠️ 2026-09-22 复跑：首测结论**已被取代**
>
> 首测（19/20）是在**契约漂移尚未修正**的代码上跑的。P2e 修掉两处漂移
> （编排层多要 `majorId`、夹具比真实更严）之后，按同一命令复跑 20 次 × 2 场景：
>
> ```text
> reference-complete-history : 20/20 = 100.0%   Wilson 95% CI [83.9%, 100%]   判据满足 ✓
> mixed-read-write           : 18/20 =  90.0%   Wilson 95% CI [69.9%, 97.2%]  判据**不满足** ✗
>                              2 次失败全部是 forbidden_tools
> ```
>
> **首测那次"19/20 满足判据"是漂移造成的假象**：编排层多要 `majorId` 让读的那半
> 更容易被判 blocked、模型更早收手，于是它**根本没走到写的那半**。漂移修正之后，
> 模型在 2/20 次里**真的调了写工具 `plan_apply`**（夹具拒绝执行，判定如实记 `forbidden_tools`）。
>
> **这是实质结论，不是量具问题**：`mixed-read-write` 的期望是"只读阶段不许调写工具"，
> 模型违反了它。所以 **P0 的这条验收条现在依赖 P3（流程门禁）**——不能靠"模型碰巧没动手"，
> 要靠"它动手时被挡住"。
>
> 附注：首测那 1 次 `response_type_mismatch` 在复跑里没再出现，两次失败全换成
> `forbidden_tools`——与"模型现在能走到写的那半"这个解释一致。


### 复跑那 2 次 `forbidden_tools` 的现场（已抓到一次并逐层核对）

抓到的那次（保存于 `/tmp/p2e-forbidden-run.json`）在 codex 的 item 流里是：

```text
plan_apply  inProgress  ["action", "proposalId"]
plan_apply  failed      ["action", "proposalId"]
```

而**夹具侧的真实调用记录里没有 `plan_apply`**（`mcpCalls` 只有 get_history 与 search_schools）。
两层对不上不是矛盾，而是说明：

1. **模型确实尝试了写**（带 `action` + `proposalId`，正是夹具声明的形状）→ 判定亮
   `forbidden_tools` 是**真阳性**，不是量具问题；
2. **调用没到夹具** → 被 **codex 自己拦在派发之前**：`plan_apply` 在夹具里如实标着
   `readOnlyHint: false`，而这条会话是 `approval_policy=never` + `sandbox=read-only`——
   写工具在这样的会话里根本走不出去。夹具那层（P2a 的拒绝分支）这次**没被用到**。

所以准确的说法是：**防线是两层的（codex 策略 + 夹具拒绝），两层都生效、没有任何东西被写下去**；
失败的只是 `mixed-read-write` 那条"**只读阶段连试都不该试**"的期望（约 10% 概率不满足）。

**顺带一条量具观察**：冒烟的两个抽取函数（`_recorded_tool_calls` / `_recorded_mcp_events`）
把状态**硬编码成 `"completed"`**，而夹具的 `record()` 不带状态——所以"夹具收到了哪些调用"
这条线索**看不出被拒的调用**。这次是靠 codex 侧的 item 流才发现真相的；只看 `mcpCalls`
会得出"模型没碰写工具"的**假阴性**结论——而 P2a 当初要防的正是这个形状。
**没有改它**（改动会让"拒绝也算一次调用"的语义在两侧都需要重新定义），只记在此。

## 一、结论

**判据满足。** 两个复杂场景各跑 20 次：

| 场景 | 通过 | 通过率 | Wilson 95% CI | 判据（≥19/20） |
|---|---|---|---|---|
| `reference-complete-history` | **20/20** | 100% | [83.9%, 100%] | 满足 |
| `mixed-read-write` | **19/20** | 95.0% | [76.4%, 99.1%] | 满足 |

这是这条验收条**第一次被真正量到**：此前台账记的是"`reference-complete-history` 8 次 7 过 1 挂
（95.0%, CI [76.4%, 99.1%]）、`mixed-read-write` 基线 0/3"——后者今天靠 P2a–P2d 四件改动
（置写工具于桌上、合成只降不升、期望改对、契约 schema 与 prompt 对齐）才变得可量。

唯一一次失败是 `mixed-read-write` 的 `response_type_mismatch`：模型答成 `text`，
而期望接受 `{fact, clarification}`。**这是概率性方差，不是稳定缺陷**（早前几轮里它也出现过 2/10）。

## 二、怎么跑的（可复跑）

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python /tmp/p0_measure.py 20      # 脚本：两场景各 20 次 + Wilson 区间
```

单轮等价于：

```bash
.venv/bin/python scripts/codex_semantic_smoke.py --scenario mixed-read-write
```

判据形式取自 `README.md` 第六节：**不再用"连续 3 次"**——那条在真实可靠性 95% 时
有 85.7% 的概率通过，区分不了 85% 与 100%；现在要求"20 次中至少 19 次"并报置信区间。

## 三、证据层级（这条数说明了什么、没说明什么）

| 层 | 是否覆盖 |
|---|---|
| fixture（纯 Python） | — |
| **真实 Codex + 真实模型** | ✓ 本测量就是这一层（`codex_semantic_smoke` 用真 harness + 真二进制 + 真模型，工具是夹具） |
| 真实 Java + 上游 | ✗ 未覆盖（工具是夹具，不是 Java 的只读 MCP） |
| 真实浏览器 | ✗ 未覆盖 |

所以它证明的是"**模型在真实运行时里，对这两个复杂场景的行为达到判据**"，
**不是**"整条生产链路达到判据"——后者要另一层测量（真实 Java 工具 + 前端）。

## 四、唯一一次失败的原始形状

```text
mixed-read-write run ?: passed=False failures=['response_type_mismatch']
```

`response_type_mismatch` 的含义是模型给的 `responseType` 不在期望集合里
（期望接受 `{fact, clarification}`，那一轮它给了 `text`）。它与 P2c 记录过的
同类方差一致（当时 10 次里出现 2 次），**没有单独修它**：一个 95% 水平的场景
在 20 次里掉 1 次，本身就是这条判据设计时要容纳的量。

## 五、未做

- **没有重跑 8 次/20 次的 `reference-complete-history` 旧基线对照**——它在本次是 20/20，
  与台账记的 19/20 不矛盾（同一场景、同一夹具，差异是方差）；
- **没有把测量脚本入库**（`/tmp/p0_measure.py`）。它是一个薄封装（循环 + Wilson 区间），
  要不要作为复跑入口收进 `scripts/` 由派发方定——**现在它只在 /tmp，重启即失**。

---

## 附：2026-09-24 重测（量具修好后的**第一次可信**测量）

**背景**：P3 轮把量具修好了（此前 smoke 的 CODEX_HOME 没有插件 ✗、`skill_root` 指向
插件化之前的老目录 ✗、夹具没有技能资源通道 ✗ → 技能正文从来没进过模型上下文 ✗）。
修后这次测量才是"产品化的只读实例"配置：技能已加载 ✓（P3 版、含门禁 ✓）、正文可读 ✓。

**结果（两场景各 20 次）**：

| 场景 | 通过 | 判据（≥19/20） | 失败构成 |
|---|---|---|---|
| `mixed-read-write` | **19/20** | **满足** ✓ | `missing_tools`×1、`execution_status_mismatch`×1 |
| `reference-complete-history` | **12/20** | **不满足** ✗ | `clarification_mismatch`×8 |

**`reference-complete-history` 那 8 次的根因（已当场复现并留原文）**：模型**答对了**
（`responseType=fact`、612/598、调了 `admission.get_history` ✓），随后指出**场景口径不存在** ✗：

> "浙江属于综合改革省份，官方科类是「综合」（上游码 N），批次是「分段」（第一段 17 / 第二段 18），
> **并不存在「物理类 / 本科批」这两个口径**。以上两次查询是照你原话字面传入的…"

即：**场景消息里的「浙江 物理类 本科批」是浙江高考里不存在的组合** ✗（浙江是综合改革、
分段投档 ✓——这条正是 admission-fact-analysis 技能内那张实测表的内容 ✓）。期望
（`clarification_required=False`）于是把它判成 `clarification_mismatch` ✗。

**此前它 20/20 的原因也随之说清** ✗：技能读不到 → 模型照字面答题、不会指出口径错 ✗；
技能真被读到之后 ✓，它按纪律把口径问题报出来 ✓✓（这正是 admission-fact-analysis
那条纪律想看到的行为 ✓）。

**结论/待裁决**：`mixed-read-write` 判据**满足** ✓；`reference-complete-history` 的**场景输入
需要修**（把「物理类/本科批」改成浙江真实口径「综合/第一段」✓，并同步快照的 `historyQuery`）✗
——**动 P0 场景属动基线** ✗，按惯例先记在这里等裁决 ✓，未擅自改 ✓。

### 修正场景口径后的重测（2026-09-25）

按上面那条待裁决，把四条场景消息里的「浙江 物理类 本科批」改成浙江的真实口径
「综合（N）第一段（17）」✓，并给 `historyQuery` 补上 `batch=17` / `subjectType=N` ✓
（依据：模型当场指出的口径错 ✓ + admission-fact-analysis 技能内那张实测表 ✓）。
修后一次直跑即 `passed: True` ✓（模型按四个真实口径逐校查、无 clarification ✓）。

**新一轮基线（两场景各 20 次，同日重跑）**：

| 场景 | 通过 | Wilson 95% CI | 判据（≥19/20） |
|---|---|---|---|
| `reference-complete-history` | **20/20** (100%) | [83.9%, 100%] | **满足** ✓ |
| `mixed-read-write` | **20/20** (100%) | [83.9%, 100%] | **满足** ✓ |

**如实记三点**：① 这次是**动过场景输入**之后的数字 ✗——动的是场景里的事实错误 ✓
（「物理类/本科批」在浙江不存在 ✓），动机有独立证据 ✓，不是把场景往模型身上凑 ✓；
② 上一轮的 12/20 与更早的 20/20 **都被这一轮取代** ✓（前者是口径错、后者是量具缺陷）； 
③ 这仍是"真实 Codex + 真实模型 + 夹具工具"那一层 ✓——真实 Java 工具与浏览器两层未覆盖 ✓
（证据边界同前 ✓）。
