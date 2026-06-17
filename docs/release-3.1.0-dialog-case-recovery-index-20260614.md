# Release 3.1.0 Dialog Case Recovery Index 2026-06-14

本文是 `release-3.1.0-dialog-auto-explorer-issue-summary-20260614.md` 的 case 级恢复索引。目标是让研发或测试可以快速恢复一个问题对话，确认修复前后是否一致。

## 1. 基础入口

### 会话页面

| session | 页面入口 | 用途 |
| --- | --- | --- |
| `110` | `http://10.218.4.10:3001/assistant-pc/sessionDetailV2?chatSessionId=110&userId=1&userName=&page=1&pageSize=10` | PREDICT 专业模式，验证医学硬约束、候选查询、pending/确认取消、费用/中外合作 |
| `114` | `http://10.218.4.10:3001/assistant-pc/sessionDetailV2?chatSessionId=114&userId=1&userName=&page=1&pageSize=10` | 审查修复场景，验证空预览、手动修复、补偿预览状态 |
| `115` | `http://10.218.4.10:3001/assistant-pc/sessionDetailV2?chatSessionId=115&userId=1&userName=&page=1&pageSize=10` | VOLUNTEER 专业组，验证数据更新、未审查状态、专项、体检、选科、专业组调剂 |

### 自动复跑模板

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario SCENARIO_NAME --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

替换 `SCENARIO_NAME` 即可复跑对应 case。报告会输出到 `/tmp/zhiyuan-dialog-verify`。

### 原始报告

| 批次 | Markdown | JSON |
| --- | --- | --- |
| batch-1 | `/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-125836.md` | `/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-125836.json` |
| batch-2 | `/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-133121.md` | `/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-133121.json` |
| batch-3 | `/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-144530.md` | `/tmp/zhiyuan-broad2-dialog-after-e9e866f-20260614/dialog-auto-explorer-20260614-144530.json` |

## 2. 核心 Case 索引

### CASE-001 医学硬约束被误拒答

| 字段 | 内容 |
| --- | --- |
| session | `110` |
| scenario | `broad2-predict-medicine-only-hard-constraint-diverge` |
| report | batch-1 |
| 风险 | “只要医学类”这种明确硬约束被回复“查询没有稳定收敛”，并重复拒答 |

人工恢复对话：

```text
T1 用户：我说的是只要医学类，不是医学优先。你不要再给我推荐计算机电气。
T2 用户：如果分数不够临床，就说不够。能不能看口腔、影像、检验、护理这些，分别有多少？
T3 用户：不要给我编学校，你按当前候选池能查到的说，查不到就说查不到。
```

修复后预期：

- 不出现“查询没有稳定收敛”。
- 明确承认当前方案与“只要医学类”冲突。
- 如果没有可靠医学候选数据，应说明数据能力边界，不能编造 286 个医学候选。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-predict-medicine-only-hard-constraint-diverge --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

### CASE-002 空预览被包装成可执行预览

| 字段 | 内容 |
| --- | --- |
| session | `114` |
| scenario | `broad2-review-repair-confirm-with-empty-preview` |
| report | batch-3 |
| 风险 | `compensationPreview` 为空时仍说“预计移出1条、补入1条” |

人工恢复对话：

```text
T1 用户：可以，你先修一下，但修之前必须把具体移出和补入告诉我。
T2 用户：如果你没有具体预览，就不要让我确认，也不要说预计移出1条补入1条。
T3 用户：现在能执行的动作到底是什么？只是建议、生成预览，还是已经应用？
T4 用户：我确认之前，当前方案不应该变化，对吧？
```

修复后预期：

- 没有具体 `actions` 时，只能说“当前没有生成可确认的具体预览”。
- 不输出“预计移出/补入”这种无来源数字。
- 明确当前方案未变更，且不存在待确认的有效预览。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-review-repair-confirm-with-empty-preview --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

### CASE-003 无 pending action 时误识别“选择A”

| 字段 | 内容 |
| --- | --- |
| session | `110` |
| scenario | `broad2-cross-intent-choose-a-without-pending-action` |
| report | batch-3 |
| 风险 | 没有待确认选项时，用户输入“选择A”，助手直接生成或执行预览 |

人工恢复对话：

```text
T1 用户：选择A
T2 用户：你刚才说的那个策略用这个吧
T3 用户：如果你不知道我选的是哪个A，就问我，不要自己猜。
```

修复后预期：

- T1 应澄清“当前没有可确认的 A 选项”。
- 不生成高收费/中外合作处理预览。
- 不执行方案更新，不说“已按处理建议更新方案”。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-cross-intent-choose-a-without-pending-action --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

### CASE-004 VOLUNTEER 数据更新后未审查被说成 0 风险

| 字段 | 内容 |
| --- | --- |
| session | `115` |
| scenario | `broad2-volunteer-data-update-affected-detail` |
| report | batch-2 |
| 风险 | `requiresReview=true`、`reviewStatus=not_reviewed` 时仍说“风险0项、提醒0项” |

人工恢复对话：

```text
T1 用户：页面说志愿数据更新了，具体影响我当前方案里的哪几条？
T2 用户：能不能说旧值新值分别是什么？比如计划数、专业、选科要求有没有变。
T3 用户：候选刷新和重新审查哪个已经做了，哪个还没做？你按当前状态说。
```

修复后预期：

- 明确当前数据已变化，候选需刷新、方案需重新审查。
- 没有重新审查前，不能说“当前风险0项”。
- 没有旧值新值明细时，应说“当前只知道影响范围，无法列明旧值新值”。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-volunteer-data-update-affected-detail --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

### CASE-005 当前方案 grounding 编造学校

| 字段 | 内容 |
| --- | --- |
| session | `115` |
| scenario | `broad2-volunteer-normal-color-current-plan-only` |
| report | batch-2 |
| 风险 | 用户要求只列当前方案，助手输出中央民族大学、华北电力等不在当前方案中的学校 |

人工恢复对话：

```text
T1 用户：我色觉正常，系统应该有。现在当前方案还需要担心色盲色弱限制吗？
T2 用户：只列当前方案里的学校专业组，不要拿华北电力、南京邮电这种不在方案里的举例。
T3 用户：如果只是通用提醒，就明确说这是通用提醒，不是当前方案风险。
```

修复后预期：

- 不引入“右眼失明”。
- 不列当前方案外学校。
- 审查未跑时说明“当前未完成审查”，不能说“系统审查风险0项”。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-volunteer-normal-color-current-plan-only --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

### CASE-006 高校专项资格与当前方案口径混淆

| 字段 | 内容 |
| --- | --- |
| session | `115` |
| scenario | `broad2-volunteer-special-plan-current-plan-eligibility` |
| report | batch-2 |
| 风险 | `specialPlan=false`、当前方案是否含专项、通用专项资格三者混淆 |

人工恢复对话：

```text
T1 用户：高校专项招生计划有吗？我现在这个方案里有没有高校专项的专业组？
T2 用户：中国海洋大学某个专业组如果是高校专项，普通考生能不能直接报？
T3 用户：你别把高校专项当普通志愿推荐，先说需要什么资格。
```

修复后预期：

- 先说明当前用户画像未启用专项资格。
- 当前方案条目如果没有专项属性字段，应说无法从当前数据确认方案里是否有专项属性。
- 区分普通考生、已获专项资格考生、普通批次和专项批次。
- 时间线按 `examYear=2026`，不能无说明引用 2024。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-volunteer-special-plan-current-plan-eligibility --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

### CASE-007 手动修复路径编造具体志愿

| 字段 | 内容 |
| --- | --- |
| session | `114` |
| scenario | `broad2-review-repair-manual-operation-path` |
| report | batch-3 |
| 风险 | 用户问页面如何手动修，助手编造第58/64位、湖南师范大学制药工程等具体条目 |

人工恢复对话：

```text
T1 用户：我不想一键重排，只想手动修一个风险点，页面上应该怎么操作？
T2 用户：你先指出最应该动的那一条，为什么动它，不要说一堆内部术语。
T3 用户：如果要替换，候选从哪里选？选完以后要不要重新审查？
```

修复后预期：

- 如果无法从当前数据定位具体页面位置，应明确说明。
- 优先给真实页面操作路径，不编造位次和专业名。
- 候选来源、替换后是否重新审查需要说明动作边界。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-review-repair-manual-operation-path --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

### CASE-008 选科限制与福建规则口径错误

| 字段 | 内容 |
| --- | --- |
| session | `115` |
| scenario | `broad2-volunteer-province-policy-and-subject-restriction` |
| report | batch-3 |
| 风险 | 未审查状态被说成选科符合；福建规则、专业组和系统字段口径混乱 |

人工恢复对话：

```text
T1 用户：当前方案里有没有选科不符合的？比如要求物化但我条件不满足那种。
T2 用户：你按福建专业组规则说，哪些是系统已经过滤掉的，哪些需要人工核验。
T3 用户：不要只说一般政策，要结合当前方案举例。
```

修复后预期：

- 如果当前审查未完成，应说明“尚未审查选科符合性”。
- 结合当前方案时只能引用真实方案条目。
- 政策规则和系统内部展示字段要分开解释。

自动复跑：

```bash
/bin/bash -lc 'set -a; . /root/dev/zhiyuan/zhiyuan-agent/.env.local302; set +a; export DIALOG_AUTO_EXPLORER_TEMPERATURE=0.2; export DIALOG_AUTO_EXPLORER_MAX_TOKENS=1600; cd /root/dev/zhiyuan/zhiyuan-agent; ./.venv/bin/python -u examples/dialog_auto_explorer.py --scenarios /tmp/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json --scenario broad2-volunteer-province-policy-and-subject-restriction --max-turns 6 --extra-turns-after-issue 2 --issue-limit 8 --llm-judge --clear-history --clear-backend-pending --output-dir /tmp/zhiyuan-dialog-verify'
```

## 3. 验证判定标准

一个 case 视为修复通过，需要同时满足：

- 自动复跑不再出现同一 P0/P1 根因。
- 人工页面按同样对话输入时，前端卡片状态、方案状态和助手文本一致。
- 对“当前方案”类问题，不出现报告中记录的不在方案内学校或专业。
- 对“确认/取消/执行”类问题，只有真实 pending action 存在时才允许确认或取消。
- 对 VOLUNTEER 数据更新链路，未刷新/未审查状态必须明确展示，不能说成 0 风险。
