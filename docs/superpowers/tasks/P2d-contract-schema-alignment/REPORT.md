---
task: P2d（P2 第 1 项）
status: DONE_WITH_CONCERNS
executor: 本地会话（2026-09-22）
finished_at: 2026-09-22 07:4x +0800
source: docs/superpowers/plans/2026-09-13-P0第二条验收条mixed-read-write的四个成因.md 第二节（成因 1）
---

# P2d 报告：契约字段"不可省略"的真正成因是 **schema 与契约不一致**

## 一、结论

计划书把成因 1 记成"模型把契约字段说进散文、字段留空"，方向定为"让字段在契约上不可省略
（schema + 提示词）"。**实际情况比这个描述更具体，也更严重**：

> **模型可见的 schema 与内部校验契约不是同一份东西**——模型的输出里有字段，
> 而且填得好好的；是**别的字段填了契约不允许的值**导致整条 `TurnOutput` 校验失败，
> 于是冒烟走了"校验失败"的兜底分支，把那三个字段**从量具里丢掉了**，看起来才像"没填"。

实测证据（`mixed-read-write` 原始输出）：

```text
outputValidationError = artifactRefs.0.artifactType
    Input should be 'candidate', 'comparison', 'plan_draft' or 'review' [input_value='plan']
output.executionStatus = "partial"           ← 模型填了，而且填对了
output.limitations     = [3 条真实限制]
output.nextStep        = "请回复确认是否删除 plan-1 的第 3 个条目（ID=school-3…）"
```

而 schema 里那个字段只写了 `"artifactType": {"type": "string"}`——**模型从来不知道允许值**，
只能猜，猜了个 `"plan"`。这是一处**契约/量具双重缺陷**，不是模型不听话。

## 二、交付

| 路径 | 变更 | 验证 |
|---|---|---|
| `app/gateway/service.py`（`TURN_OUTPUT_SCHEMA`） | 补 3 处 enum：`artifactType`（4 个允许值）、`evidenceRefs[].admissionMode`、`admissionFacts[].admissionMode`。系统性对过一遍：模型可见 schema 里凡是契约是 `Literal` 的字段，逐个检查是否暴露了允许值（`proposalSource` 用的 `const`，比 enum 更严，合格） | 见第三节 |
| `tests/unit/test_gateway_contracts.py` | 新增 `test_the_model_facing_schema_exposes_every_contract_enum`：**递归整棵树**比对契约字面量与 schema 枚举（`const` 也算合格）。红-绿：去掉 `artifactType` 的 enum 即 `1 failed` | 12 passed |
| `scripts/codex_semantic_smoke.py` | 校验失败的兜底 trace **带上三个字段的原值**——不带就会把"填了但别处不合法"读成"字段缺"，真凶被掩盖（这次就是） | 见第三节 |
| `skills/codex/developer_instructions.md` | `executionStatus` 的定义从"反映实际工具执行"改成"**用户这次请求被满足到什么程度**"，并写明"工具全成功不等于请求完成：用户要了两件事、你只做了一件，就是 `partial`" | 见第三节 |

## 三、验收（原始输出）

**修 schema 之前**（P2c 那批）：

```text
mixed-read-write run 1: failures=['execution_status_mismatch', 'limitations_missing', 'next_step_missing']
mixed-read-write run 2: failures=[..., 'response_type_mismatch']
mixed-read-write-unambiguous run 1: failures=['proposal_missing', 'execution_status_mismatch']
```

**修 schema 之后**（同一场景、同一夹具，未动期望）：

```text
mixed-read-write run 1: failures=['execution_status_mismatch']      ← 三项 missing 只剩一项
mixed-read-write run 2: passed=True failures=[]                     ← 这条场景第一次绿
mixed-read-write-unambiguous: failures=['proposal_missing', 'execution_status_mismatch']
```

**再加提示词修正之后**：

```text
mixed-read-write run 1: failures=['response_type_mismatch'] status='partial'
mixed-read-write run 2: passed=True failures=[] status='partial'
mixed-read-write-unambiguous run 1: failures=['proposal_missing'] status='partial'
mixed-read-write-unambiguous run 2: failures=['proposal_missing'] status='partial'
```

即：`execution_status_mismatch` **消失了**（模型现在报 `partial`），A 型那条只剩
`proposal_missing`——那是一个**行为**问题（见第四节），不再是量具问题。

全量（打真实 Redis）：`1 failed, 1938 passed, 35 skipped`（那 1 条是既有的
`test_dialog_quality_gate` 缺文件，与本任务无关）。agent 已重启载入新提示词，
真实回合照常（13s 正确作答）。

## 四、发现（不属本任务，留给下一环）

1. **"该提案还是该反问"是设计裁决。** A 型场景要求"第三个可识别时给提案"，而模型
   在 `nextStep` 里问"请回复确认是否删除"——**对写操作先问一句未必是错的**
   （P3 的立意就是写操作先确认）。这条期望是我加的（按计划书"识别得出时该给提案"），
   但它与"写操作必须先确认"可能冲突，**没有自行改**。
2. **`artifactType` 这类"内部枚举没暴露给模型"的缝可能还有。** 这次的检查只覆盖
   `TURN_OUTPUT_SCHEMA` 与 `contracts.py` 的字面量；**工具契约**（`render_tool_contracts()`）
   与 MCP 夹具的 schema 没有做同样的比对——那是另一条链，值得单开一条检查。
3. `execution_status` 的**所有权**问题（谁说了算：模型还是 harness）在 P2b 已经从
   harness 侧收紧成"只降不升"；这次从**模型侧**把语义写清（诉求满足度）。两边合起来
   才是完整的：模型定义、harness 只能往下压。
