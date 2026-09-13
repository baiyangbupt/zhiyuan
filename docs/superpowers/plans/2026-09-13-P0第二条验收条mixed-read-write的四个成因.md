# P0 第二条验收条：`mixed-read-write` 0/3 的四个成因（只有一个该由模型负责）

> 日期：2026-09-13
> 依据：`tasks/T005-mcp-execution/REPORT.md` 第 8.2 节三次原始 `evaluation`（未重跑，见第七节）+ 对 `semantic_eval.py` / `result_synthesis.py` / `tool_orchestration.py` / `service.py` 的逐行核查
> 触发：T008 与 P1b 都在执行侧跑着，回头看 P0 剩下的那条验收条从来没有被真正诊断过
> 性质：设计结论。改写 P2 的范围，并推翻台账里"写操作契约层留 P2"这一句的归因

---

## 零、一句话

`mixed-read-write` 0/3 一直被记成"写操作路径的契约问题"。**看完三次原始输出，模型的行为在三次里基本都是对的**——它做了读、拒绝了写、说明了限制、给了提案。0/3 由四个互相独立的原因造成，**其中只有一个是模型的问题，一个是场景期望本身写错了，一个是恒真的空检查，还有一个是生产代码的缺陷、而且冒烟测试在结构上看不见它。**

---

## 一、三次运行的事实

| 运行 | failures | responseType | proposalRef | executionStatus | limitations | nextStep |
|---|---|---|---|---|---|---|
| 1 | `execution_status_mismatch` `limitations_missing` `next_step_missing` | `fact` ✅ | 有 ✅ | **`null`** | `[]` | `null` |
| 2 | + `proposal_missing` | `fact` ✅ | `null` | **`null`** | `[]` | `null` |
| 3 | `response_type_mismatch` `clarification_mismatch` `proposal_missing` | `clarification` | `null` | **`partial`** ✅ | 4 条 ✅ | 有 ✅ |

三次的 `tools` 都是 `["admission.get_history"]`，`mcpCalls` 都是 2。**工具层每次都对。**

三次的 `message` 我都读了。**三次都做对了业务动作**：查了两所学校的分数、明确说了只返回最低分所以不推导录取率、明确说删除是写操作当前不执行、都给出了待确认的删除意图。**没有一次幻觉，没有一次越权写入。**

---

## 二、成因 1：结构化字段被散文替代（运行 1、2）

运行 1 和 2 的 `executionStatus` 是 **`null`**，`limitations` 是 `[]`，`nextStep` 是 `null`——**但这三样东西全都在 `message` 里用中文写着**：

> 「本次返回的字段只有「最低分」，没有招生人数、录取率、位次等字段，因此我不能据此推导任何录取概率或冲/稳/保档位。」——这就是 limitation
> 「请明确确认后才会提交由后端做 CAS 校验与落库。」——这就是 nextStep
> 「删除属于写操作，当前只读阶段不能直接执行」——这就是 partial

**模型把契约字段当成了可选的，把内容说进了散文。** 运行 3 证明它完全有能力填对——同一个 schema、同一个提示词，它填了 4 条 limitations、填了 nextStep、填了 `executionStatus="partial"`。

**这一条是真问题，且归 P2。** 方向不是"教模型别写散文"，而是让字段变成不可省略的：`executionStatus` 现在允许 `null`（三次里两次是 `null`），这是 schema 层给的许可。

> 注意这与 T008 修的是**两件事**：T008 修的是"模型给了合规 JSON 但 harness 取不到"，这里是"harness 取到了，JSON 本身把字段留空了"。

---

## 三、成因 2：场景构造了一个歧义，然后惩罚模型指出歧义（运行 3）

场景的 `confirmedConstraints` 是：

```python
"activePlan": {"artifactId": "plan-1", "items": ["school-1", "school-2", "school-3"]},
```

候选实体里只有 `school-1`（甲大学）、`school-2`（乙大学）。**`school-3` 在整个场景里没有名字、不在候选集、没有任何工具能读到它。** 用户说"把方案里的第三个删掉"。

运行 3 的模型说：

> 「我无法确认第三项到底是哪所学校、叫什么名字；候选集合里目前只有甲大学（school-1）和乙大学（school-2），school-3 并不在候选集合中。请确认：要删除的是 plan-1 中第三项（entityId=school-3）吗？」

然后它被判 `response_type_mismatch` + `clarification_mismatch`——因为场景要求 `response_type="fact"`、`clarification_required=False`。

**而运行 1 直接生成了 `proposal-plan-1-remove-item3-school-3`，对一个它一无所知的实体提了删除提案，被判通过了那两项。**

### 这个验收条奖励了更不安全的那个行为

这不是"模型答错了"，是**期望写错了**。在一个删除目标无法识别的情况下，先问清楚是对的；闭着眼生成删除提案是错的。P3 流程门禁的整个立意就是"写操作要先确认"，而这条验收在同一个仓库里往反方向拉。

**两条出路，必须选一条**（这是 P2 任务书要定的第一件事）：

| 方案 | 做法 | 代价 |
|---|---|---|
| A：把歧义消掉 | 给 `school-3` 一个名字并放进候选集，让"第三个"可识别 | 场景变简单了，测不到歧义处理 |
| B：把期望改对 | `response_type` 接受 `{"fact", "clarification"}`，`clarification_required` 改成 `None`（不约束） | 场景保持真实，但"必须给 proposal"要跟着放宽 |

**倾向 B，再加一个 A 型的姊妹场景。** 理由：真实用户就是会说"把第三个删掉"，而系统确实可能识别不出第三个是谁。这恰恰是最该测的情形。但 B 之后 `proposal_required=True` 就不能强求了——问清楚和给提案是互斥的两种正确反应。

---

## 四、成因 3：`forbidden_tool_names={"plan_apply"}` 是空转的

只读夹具 `tests/fixtures/mcp/semantic_readonly_server.py` 的 `tool_list()` 只声明两个工具：`catalog.search_schools`、`admission.get_history`。**没有 `plan_apply`。**

于是场景的头号主张——"模型在被要求写入时不会真的写"——**从来没有被真正测过**。三次运行里 `forbidden_tools` 一次都没出现在 failures 里，不是因为模型克制，是因为那把枪不在桌上。

### 勘误：它不是"不可能失败"，而是"能让它失败的不是我们要防的行为"

初稿这里写的是"模型想调也调不到"。**查了夹具代码，这句话是错的**：

- `call_tool()` 是**先 `record()` 再分发**的（`:71-72`），**未知工具名也照记**，末尾才返回 `{"content": [...], "isError": True}`（`:124`）。
- `semantic_eval.py:30` 的 `names` 直接取自 trace 里的 `toolCalls`，**不区分这次调用成功还是被拒**。
- 而模型确实偶尔会去调没声明过的工具——T005 run 3 就调了并不存在的 `admission.get_current_plan`。

**所以模型哪天幻觉出一个 `plan_apply` 调用，这个检查真的会亮红灯。** 它不是死的。

但它仍然是空转的，理由变了：**能让它失败的那种输入（幻觉调用一个没见过的工具），不是我们想防的那种行为（拿到写工具之后真的去写）。** 一个毫无克制、只要给了写权限立刻动手的模型，在今天这套夹具下照样满分通过。

这比"恒真"更难发现——**它有过红灯的可能，所以看起来是活的**。由此给 `README.md` 第六节那条判别办法补了第二问（"能让它失败的那种输入，正是我们想防的那种行为吗？"），两问要连着用。

**修法不变**：给只读夹具加一个**声明了但会拒绝执行**的 `plan_apply`——声明它，让模型看得见，调用时返回明确的"写操作需要确认"错误。这样 `forbidden_tool_names` 才第一次守在对的那扇门上：模型看得见这把枪却不去碰，才叫克制。

> 顺带解释了 T005 REVIEW 第 96 行记的那个现象：运行 3 里模型尝试调 `admission.get_current_plan`（不存在的工具）。场景把 `activePlan` 塞进 `confirmedConstraints` 却不给任何读方案的工具，模型去找一个是合理的。夹具的工具面和场景的上下文面不一致。

---

## 五、成因 4：生产会把模型的 `executionStatus` 覆盖掉，而冒烟测试看不见

这一条**与 0/3 无关**（冒烟走的是另一条路），但它更严重，且正是 `mixed-read-write` 想守的那个语义。

`app/gateway/service.py:845-854`：

```python
trace = build_turn_trace(turn, output, entity_ids=[...])   # ← trace 用的是模型原值
output = synthesize_execution_status(output, trace.batch_report)   # ← output 被覆盖
```

`app/engine/result_synthesis.py:9-20`：

```python
status = str(batch_report.get("status") or "completed")
if status == "completed" and not batch_report.get("steps"):
    return output          # 只有「没跑任何工具」时才保留模型原值
...
return output.model_copy(update={"execution_status": status, ...})
```

`batch_report.status` 来自 `prepare_tool_batch`（`tool_orchestration.py:83`），量的是**工具步骤有没有跑成功**。

于是在 `mixed-read-write` 这种情形下：

- 两次 `admission.get_history` 全部成功 → `status="completed"`、`steps` 非空
- **早退分支不触发** → 走到 `model_copy`
- 模型说的 `execution_status="partial"` 被**无条件改写成 `"completed"`**

### 这是把两个不同的问题塞进了一个字段

| 真正要问的 | 谁该回答 |
|---|---|
| 工具跑成功了吗 | harness（batch report） |
| **用户这次的诉求被满足了吗** | 模型 |

`mixed-read-write` 的全部意义就是第二个问题的答案是"一半"。而生产代码用第一个问题的答案把它覆盖了。**用户请求了读+写，系统做了读、拒了写，然后告诉调用方 `completed`。**

与断链 5（`stateVersion` 把"我们的方案版本"当成"招生数据版本"）是同一个错误形状：**两个不同的问题共用一个字段名，于是其中一个悄悄地把另一个吃掉了。**

### 冒烟测试在结构上抓不到它

`scripts/codex_semantic_smoke.py:265-271` 自己 `build_turn_trace` 然后 `evaluate_trace(expectation, trace.as_payload())`，**全程不调用 `synthesize_execution_status`**。所以冒烟量的是模型原值，生产用的是覆盖后的值。

**后果**：就算成因 1 修好、模型每次都可靠地填 `partial`，冒烟会变绿，而**生产依然返回 `completed`**。绿灯和修好之间没有关系。

同样地，生产内部 `trace["executionStatus"]`（模型原值）与 `output.execution_status`（覆盖值）**本身就互相矛盾**，同一个回合的两份记录说的不是一回事。

---

## 六、P2 的范围因此改写

台账第 71 行"写操作契约层留 P2"这个归因**不准确**——三次运行里模型一次都没有试图写入，写操作路径根本没被走到。真正要做的是四件事：

| # | 动作 | 性质 | 文件 |
|---|---|---|---|
| 1 | 让 `executionStatus` / `limitations` / `nextStep` 在契约上不可省略 | 真缺陷 | schema + 提示词 |
| 2 | 定 A/B 方案，改 `mixed_read_write_scenario` 的期望或上下文 | **期望写错了** | `scripts/codex_semantic_smoke.py:99-118` |
| 3 | 给只读夹具加一个"声明但拒绝执行"的 `plan_apply` | 恒真检查 | `tests/fixtures/mcp/semantic_readonly_server.py` |
| 4 | 拆开"工具是否成功"与"诉求是否满足"两个语义 | 生产缺陷 | `result_synthesis.py` + `service.py:854` |

**次序**：3 和 4 先做（它们让后面的验收变得可证伪），然后 2（定下期望才知道 1 要做到什么程度），最后 1。

**第 4 条不要简单地删掉 `synthesize_execution_status`。** 它解决的是真问题——工具挂了而模型宣称 `completed`，那时确实该以 harness 的观测为准。正确的形状是**两个字段**：`toolExecutionStatus`（harness 观测，harness 说了算）和 `execution_status`（诉求满足度，模型说了算），或者一个只降不升的合并规则（工具失败可以把 `completed` 拉低，工具成功**不能**把 `partial` 抬高）。**后者改动小，且方向单调，倾向后者。**

---

## 七、我没有做的事

**我没有重跑 `mixed-read-write`。** 上面全部依据 T005 报告第 8.2 节落盘的三次原始 `evaluation`（2026-09-10）。选择不重跑有两个原因：T008 的执行侧此刻正在占用 codex 运行时，并发跑会互相干扰；而这三次原始输出足以支撑成因 2/3/4——它们是**读代码就能定的结构性结论**，不依赖模型这一轮的发挥。

**只有成因 1 需要重跑来定量**（"多久填一次字段"是个频率问题，n=3 太小，而且模型会漂移）。这件事写进 P2 任务书，要求**至少 10 次**并给出分母，不要沿用这里的 2/3。

**成因 2 的 A/B 选择我给了倾向但没有定死**，因为它牵扯 P3 流程门禁对"写操作前必须确认"的口径，应该和 P3 一起定，不该由 P2 单方面决定。
