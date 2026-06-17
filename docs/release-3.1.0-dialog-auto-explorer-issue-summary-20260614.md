# Release 3.1.0 Dialog Auto Explorer Issue Summary 2026-06-14

本文整理 2026-06-14 基于本机 3.1.0 测试环境的对话自动探索结果。目标是把问题、会话、报告和复跑入口串起来，方便后续按批次修复和回归验证。

## 1. 测试背景

- 代码版本：`e9e866f Improve agent review synthesis and only-keep intent handling`
- 分支：`develop`
- 环境：本机标准测试环境，Agent `18091`，Backend `18090`
- 模型：沿用 `.env.local302` 中的 LLM 配置
- 场景来源：生产采样问题类型抽象 + 本地稳定会话绑定，不提交原始生产用户数据
- 本轮未修改业务代码，只收集问题

## 2. 本地会话索引

| chatSessionId | 类型 | 关键上下文 | 适合验证的问题 |
| --- | --- | --- | --- |
| `110` | PREDICT / 专业模式 | 重庆，510 分，物化生，96 志愿，当前方案已生成并审查过，偏好集中在工科、公办、华东区域 | 医学硬约束、候选查询、费用/中外合作、低风险方案、确认/取消 pending、复合调整 |
| `114` | 审查修复场景 | 已生成方案，存在专业组安全垫/意向不匹配类审查提醒，`compensationPreview` 为空 | 审查修复、空预览、手动修复路径、是否可执行 |
| `115` | VOLUNTEER / 专业组模式 | 福建，597 分，物化生，专业组方案，数据更新状态为 changed，`requiresCandidateRefresh=true`，`requiresReview=true`，色觉正常，审查未完成 | 数据更新、候选刷新、重新审查、专业组调剂、专项计划、体检/选科规则、拒绝选项引导 |

人工页面入口示例：

```text
http://10.218.4.10:3001/assistant-pc/sessionDetailV2?chatSessionId=110&userId=1&userName=&page=1&pageSize=10
http://10.218.4.10:3001/assistant-pc/sessionDetailV2?chatSessionId=114&userId=1&userName=&page=1&pageSize=10
http://10.218.4.10:3001/assistant-pc/sessionDetailV2?chatSessionId=115&userId=1&userName=&page=1&pageSize=10
```

主站联调时从 `test-www.gaotuzhiyuan.com/assistant-pc` 进入，直接 IP 入口主要用于本机快速排查。

## 3. 报告索引

| 批次 | 报告 | JSON | 覆盖 | 结果 |
| --- | --- | --- | --- | --- |
| batch-1 | [/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-125836.md](/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-125836.md) | [/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-125836.json](/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-125836.json) | PREDICT 医学硬约束、电气/学校专业、复合偏好、审查后调整、只读候选 | 6 场景，24 轮，43 问题，12 error |
| batch-2 | [/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-133121.md](/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-133121.md) | [/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-133121.json](/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-133121.json) | 低风险方案、VOLUNTEER 专项、专业组调剂、数据更新、体检画像 | 6 场景，18 轮，110 问题，63 error |
| batch-3 | [/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-144530.md](/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-144530.md) | [/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-144530.json](/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-144530.json) | 手动修复、空预览确认、选择 A、拒绝选项、选科限制、复合调整撤销 | 6 场景，19 轮，109 问题，58 error |

合计：18 场景，61 轮，262 条问题标记。该数量包含重复问题和 LLM judge 标记，不能直接等价为 262 个产品缺陷。

## 4. 快速复跑方式

本轮扩展场景文件：

```text
/tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json
```

复跑单个场景：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario SCENARIO_NAME --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

复跑时建议：

- 修复前使用 `--clear-history --clear-backend-pending`，保证对话从干净状态开始。
- 如果要复现某个连续上下文污染问题，可以去掉 `--clear-history`，但需要记录起始会话历史状态。
- 对人工页面复验，优先用上面的 `chatSessionId` 入口打开对应详情页，再按报告里的 Turn Samples 逐轮输入。

## 5. P0 问题组

### P0-1 查询/动作边界不稳，出现“查询没有稳定收敛”

现象：

- 用户提出明确的信息查询或当前方案展示请求，助手返回“我已经查过当前方案和候选里的相关机会，但这轮查询没有稳定收敛”。
- 常见于医学硬约束、专业组调剂、体检核验、当前方案重点核验等场景。
- 该回复既是内部术语泄露，也是错误拒答；用户已经给出足够具体条件时不应要求“换一个更具体条件”。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `110` | `broad2-predict-medicine-only-hard-constraint-diverge` | T1-T3 | batch-1 |
| `115` | `broad2-volunteer-major-group-transfer-disliked-majors` | T2 | batch-2 |
| `115` | `broad2-volunteer-physical-new-info-conflicts-with-profile` | T3 | batch-2 |

关键对话：

```text
用户：我说的是只要医学类，不是医学优先。你不要再给我推荐计算机电气。
助手：我已经查过当前方案和候选里的相关机会，但这轮查询没有稳定收敛，先不继续重复查询。你可以换一个更具体的条件...
```

修复方向：

- 区分“信息查询失败”“候选搜索无结果”“方案调整无可执行预览”三类状态。
- 禁止面向用户输出“稳定收敛”等内部术语。
- 当前方案可读数据不足时，应说明“当前只看到/无法确认哪些字段”，而不是伪装成查询过程失败。

### P0-2 无 pending action 时误取消、误执行、误识别“选择A”

现象：

- 当前没有待确认动作时，用户说“选择A”或“前面的思路先不要用了”，助手会生成处理预览、执行方案更新，或说“已取消本次待采纳内容”。
- 该问题容易造成真实方案被误改或用户误以为方案已改。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `110` | `broad2-cross-intent-choose-a-without-pending-action` | T1-T3 | batch-3 |
| `110` | `broad2-predict-multi-turn-composite-adjust-and-undo` | T1-T2 | batch-3 |
| `110` | `broad2-predict-low-risk-safe-plan-parent` | T2 | batch-2 |

关键对话：

```text
用户：选择A
助手：我已经整理好当前方案的处理预览...预计移出 21 条、补入 21 条...
```

```text
用户：等等，我又不想太冒险，风险比城市更重要，前面的思路先不要用了。
助手：已取消本次待采纳内容。你可以继续说明想怎么调整，我会重新给出预览。
```

修复方向：

- 只有明确存在 pending action/card 且用户引用内容可解析时，才能执行确认/取消。
- 无 pending 时应澄清：“当前没有可确认的 A 选项，请说明你指的是哪个策略。”
- 取消动作也必须依赖真实 pending 状态，不允许只靠自然语言猜测。

### P0-3 空预览被包装成可执行预览

现象：

- `compensationPreview.status=empty`、`totalActions=0` 时，助手仍输出“预计移出/补入 21 条、4 条、1 条”等。
- 会把“审查发现的问题数量”误说成“已生成的替换预览”。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `110` | `broad2-predict-review-audit-then-adjust-boundary` | T3-T4 | batch-1 |
| `114` | `broad2-review-repair-confirm-with-empty-preview` | T1-T4 | batch-3 |
| `110` | `broad2-cross-intent-choose-a-without-pending-action` | T1-T2 | batch-3 |

关键对话：

```text
用户：如果预览不完整，你就说不完整，别说已经修好了。
助手：当前预览确实不完整...处理高收费：预计移出21条、补入21条...
```

```text
用户：如果你没有具体预览，就不要让我确认，也不要说预计移出1条补入1条。
助手：没有具体预览。系统返回的是抽象数字（“预计移出1条、补入1条”）...
```

修复方向：

- 输出层必须以 `compensationPreview.actions` 为唯一预览来源。
- 没有 actions 时，只能说“当前没有生成具体可确认预览”。
- 审查问题数量、受影响数量、预览动作数量需要明确分字段展示，不能混用。

### P0-4 VOLUNTEER 未审查/需刷新状态被说成 0 风险

现象：

- `reviewState.status=idle`、`workflowStatus.reviewStatus=not_reviewed`、`requiresReview=true` 时，助手仍说“风险0项、提醒0项”。
- 用户会误以为当前智能填报方案已经完成审查。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `115` | `broad2-volunteer-data-update-affected-detail` | T1-T3 | batch-2 |
| `115` | `broad2-volunteer-physical-new-info-conflicts-with-profile` | T1-T3 | batch-2 |
| `115` | `broad2-cross-intent-reject-option-and-ask-new-topic` | T1-T3 | batch-3 |
| `115` | `broad2-volunteer-province-policy-and-subject-restriction` | T1-T3 | batch-3 |

关键对话：

```text
用户：页面说志愿数据更新了，具体影响我当前方案里的哪几条？
助手：根据审查结果，当前方案没有新增风险或提醒...
```

```text
用户：当前方案里有没有选科不符合的？
助手：系统审查：风险0项，提醒0项。
```

修复方向：

- `not_reviewed/idle` 必须表达为“尚未审查”，不能表达为“0 风险”。
- 数据更新后应优先说明“候选需刷新、方案需重新审查”，再给当前可见信息。
- 对“当前风险”类问题，应把“未审查”“审查通过”“审查发现问题”三种状态分开。

### P0-5 当前方案 grounding 不稳，编造不在方案内学校/专业

现象：

- 用户明确要求“只说当前方案”，助手仍列出不在当前方案里的学校、专业或位置。
- 已出现中央民族大学、华北电力、湖南师范大学制药工程、第58/64位等不可靠输出。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `115` | `broad2-volunteer-major-group-transfer-disliked-majors` | T1-T3 | batch-2 |
| `115` | `broad2-volunteer-normal-color-current-plan-only` | T1-T3 | batch-2 |
| `114` | `broad2-review-repair-manual-operation-path` | T1-T3 | batch-3 |
| `115` | `broad2-volunteer-province-policy-and-subject-restriction` | T3 | batch-3 |

关键对话：

```text
用户：只列当前方案里的学校专业组，不要拿华北电力、南京邮电这种不在方案里的举例。
助手：...中央民族大学(专业组500)...中央民族大学(专业组999)...
```

```text
用户：我不想一键重排，只想手动修一个风险点，页面上应该怎么操作？
助手：第58位：西南交通大学...第64位：湖南师范大学...制药工程...
```

修复方向：

- “当前方案”回答只能使用 ordered plan / working plan 明确返回的条目。
- 如果上下文摘要只采样前 N 条，不能说“完整当前方案”，应明确“当前只看到样本，无法完整列出”。
- 禁止模型从偏好、候选池或通用知识补全当前方案内容。

## 6. P1 问题组

### P1-1 专项计划资格、当前方案、普通批次口径混淆

现象：

- `specialPlan=false` 被混用为“当前方案没有专项计划”或没有被用于说明“当前用户未启用专项资格”。
- 助手会给出专项规则，但没有区分普通批次、专项批次、用户资格和当前方案内容。
- 出现 2026 会话中引用 2024 时间线的问题。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `115` | `broad2-volunteer-special-plan-current-plan-eligibility` | T1-T3 | batch-2 |

关键对话：

```text
用户：高校专项招生计划有吗？我现在这个方案里有没有高校专项的专业组？
助手：当前方案结论：没有高校专项的专业组。
```

修复方向：

- 先说当前用户资格状态，再说当前方案是否可判定，再说通用规则。
- 若方案条目没有专项属性字段，应明确“当前系统返回的数据里无法确认专项属性”。
- 时间线必须跟随 `examYear=2026`。

### P1-2 体检信息和上下文串场

现象：

- 用户补充“右眼失明”时，助手没有把它作为新的用户输入与系统画像冲突处理，而是直接给当前方案审查结论。
- 之后色觉正常对照场景中，助手又把“右眼失明”带入，发生上下文污染。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `115` | `broad2-volunteer-physical-new-info-conflicts-with-profile` | T1-T3 | batch-2 |
| `115` | `broad2-volunteer-normal-color-current-plan-only` | T1-T3 | batch-2 |

关键对话：

```text
用户：我色觉正常，系统应该有。现在当前方案还需要担心色盲色弱限制吗？
助手：基于你右眼失明的情况...
```

修复方向：

- 用户新增体检信息不能直接写成系统事实，应提示“这与当前系统记录不一致，需要更新档案/重新审查”。
- 清历史复跑时仍出现串场，说明 prompt 或工具摘要里可能把前场景信息带入了模型上下文，需要检查 history/runtime context 拼接。

### P1-3 医学硬约束没有稳定持久化

现象：

- 用户明确“只要医学类”，助手仍围绕原工科方案或要求补充学校/城市。
- 后续又虚构医学候选 286 个、录取率、学校性质等。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `110` | `broad2-predict-medicine-only-hard-constraint-follow` | T1-T4 | batch-1 |
| `110` | `broad2-predict-medicine-only-hard-constraint-diverge` | T1-T4 | batch-1 |

修复方向：

- 将“只要医学类”识别为硬约束或强偏好变更，先确认影响范围和可行性，不应当立即进入替换。
- 如果候选池不支持医学类查询，应明确查询能力边界。

### P1-4 用户拒绝 A/B/C 或要求直接回答时，仍会绕回系统选项/审查模板

现象：

- 用户说“不要给我 A/B/C”，助手仍给结构化审查结论，并把未审查状态说成 0 风险。
- 用户要求“当前方案科学性”，助手应先说明当前方案状态，而不是进入选项引导。

证据：

| session | 场景 | 轮次 | 报告 |
| --- | --- | --- | --- |
| `115` | `broad2-cross-intent-reject-option-and-ask-new-topic` | T1-T3 | batch-3 |

修复方向：

- 建立“拒绝选项题”的 intent，后续回复应直接回答当前问题。
- 在方案状态不完整时，先说明状态，再给下一步优先级。

## 7. 工具和评估噪声

需要和产品问题分开处理：

- batch-1 有多次 `llm_judge_failed`，原因是 judge LLM 未返回 JSON 或超时，不代表产品回复一定有问题。
- batch-2/3 调低 judge 温度和提高 token 后，judge 稳定性明显改善。
- 报告中的 issue 数包含重复轮次和同一根因的多个标签，修复排期应按问题组而不是 issue 条数估算。

## 8. 建议修复顺序

1. P0-2/P0-3：先修 pending action 与 empty preview。风险最高，可能导致用户误以为方案已改或可执行。
2. P0-4：修 VOLUNTEER 审查/刷新状态口径。智能填报升级后该链路是重点。
3. P0-1/P0-5：修查询边界和当前方案 grounding。影响面最大，能显著减少“稳定收敛”和编造学校。
4. P1-1/P1-2：修专项计划和体检画像逻辑。属于高频政策/资格问答风险。
5. P1-3/P1-4：修偏好变更和非跟随引导的对话体验。

每个问题组修复后，至少复跑本文件对应的 2-3 个核心场景，并人工打开对应 session 页面验证前端状态、卡片和对话文本是否一致。
