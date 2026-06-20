# Release 3.1.1 Dialogue Benchmark

本文定义 3.1.1 对话质量、状态一致性和方案动作正确性的 benchmark。`assets/` 下原始数据和 autoexplorer 运行结果作为事实来源保留，不在本文复制长篇原文。

## 1. 目标

- 用稳定 benchmark 支撑 3.1.1 发布验收。
- 覆盖真实用户语言、生产风格模拟、多轮分叉、方案动作、确认卡、审查修复、政策咨询和长耗时场景。
- 区分产品缺陷、评估噪声、上下文 mismatch 和模型供应商长尾。
- 新发现问题先进入 known issues，修复完成后沉淀为稳定回归 case。
- 3.1.1 只修小问题和已知 P0/P1，不引入新的 runtime shadow、长期 bridge 或新旧并行路径；模型理解/生成能力 profile 作为 3.2.0 前置离线评估，见 [release-3.2.0-model-capability-profile-plan.md](./release-3.2.0-model-capability-profile-plan.md)。

## 2. Benchmark 分层

| 层级 | 目标 | 输入来源 | 验收重点 |
| --- | --- | --- | --- |
| L0 单元/协议 | 防止状态机和结构化 payload 回退 | Agent/Server 单测 | pending、card 状态、proposal `from -> to`、intent-aware 选择策略 |
| L1 固定对话回归 | 防止已知 case 回退 | `zhiyuan-agent/examples/dialog_regression_*.json` | failures 为空、关键断言通过、耗时可解释 |
| L2 生产抽象模拟 | 覆盖真实用户表达和分叉 | `assets/*scenarios*.json` + autoexplorer | 多轮 follow/diverge、拒绝引导、只读/动作边界 |
| L3 真实样本抽取 | 发现生产高频和长尾问题 | `assets/zhiyuan-production-sample-*`、`assets/dialogues` | 场景覆盖、真实话术、隐私脱敏、上下文匹配 |
| L4 前端人工走查 | 验证用户可感知闭环 | 本地/测试环境页面 | 卡片状态、工作区刷新、审查详情、修复预览、筛选联动 |
| L5 模型能力 profile | 3.2.0 前置评估模型理解、结构化计划和回复生成边界 | Goldens、生产抽象模拟、生成式扰动 | 不进入 runtime；输出混淆矩阵、防御性设计依据和旧路径删除清单 |

## 3. 当前资产索引

### 3.1 Autoexplorer 运行报告

| 目录 | 内容 | 当前用途 |
| --- | --- | --- |
| `assets/zhiyuan-broad2-dialog-after-e9e866f-20260614/` | 18 个 broad2 场景，61 轮，262 条问题标记；包含医学硬约束、专项资格、数据更新、体检、空预览和 grounding 等问题 | 3.1.0 问题事实来源，3.1.1 挑 P0/P1 稳定 case |
| `assets/zhiyuan-expanded-dialog-after-e9e866f-20260614/` | expanded 场景多批次运行报告 | 生产风格问题发现和场景补充 |
| `assets/zhiyuan-prod-style-dialog-*` | 生产风格 follow/diverge、grounded batch、context check 等运行报告 | 多轮对话质量、拒绝引导、上下文保持和 grounding 验证 |
| `assets/zhiyuan-dialog-auto-explorer-*` | 3.1.0 smoke 和 seed 运行结果 | 工具冒烟和 baseline |
| `assets/zhiyuan-dialog-predict-*` | PREDICT 专项扩展场景和运行结果 | 模拟填报模式场景覆盖 |

### 3.2 场景输入

| 文件 | 内容 | 用途 |
| --- | --- | --- |
| `assets/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json` | broad2 生产风格场景 18 个 | 主要问题复跑和 case 提炼 |
| `assets/zhiyuan-expanded-dialog-scenarios-e9e866f.json` | expanded 场景 16 个 | 较早生产风格扩展集 |
| `assets/zhiyuan-prod-style-dialog-scenarios.json` | 生产风格基础场景 6 个 | L2 模拟基础集 |
| `assets/zhiyuan-prod-style-dialog-scenarios-follow-vs-diverge.json` | follow/diverge 场景 12 个 | 验证用户顺着引导和打断引导两种路径 |
| `assets/zhiyuan-dialog-predict-expanded-scenarios.json` | PREDICT-only 探索场景 5 个 | 无 VOLUNTEER 依赖的快速模拟 |
| `assets/zhiyuan-prod-dialogue-cases-live-known-20260614.json` | 生产可见对话抽样 draft case 27 个 | 需人工 review 后晋级稳定回归 |

### 3.3 真实样本与转写

| 路径 | 内容 | 用途 |
| --- | --- | --- |
| `assets/zhiyuan-production-sample-100-analysis.md/json` | 生产 100 会话分布和模拟评估 | 场景覆盖和采样依据 |
| `assets/zhiyuan-production-sample-100-simulation-assessment.json` | 生产样本模拟评估结构化结果 | 场景覆盖统计 |
| `assets/zhiyuan-production-sample-100-20260614-043817.json.gz` | 生产抽样原始压缩文件 | 只作为只读事实来源，使用时注意脱敏 |
| `assets/zhiyuan-prod-prompt-long-replay/` | 27x20 长 prompt replay 批次和指标 | 长历史/长输入鲁棒性 |
| `assets/dialogues/` | 录音/视频转写和部分意图标注 | 真实咨询话术提炼，进入稳定 case 前必须脱敏和结构化 |

## 4. 评价维度

| 维度 | 要求 |
| --- | --- |
| 正确性 | 不编造当前方案、候选、资格或审查结果；所有具体条目必须来自工具/后端事实 |
| 动作边界 | 只读问题不生成可执行卡；高副作用动作必须 preview -> pending -> confirm -> apply |
| 卡片状态 | 点击后标题、按钮、状态和后端 pending/apply 结果一致 |
| 替换预览 | 必须展示被替换项和补入项，不能只展示一边 |
| 补充策略 | 先满足硬要求，再按软偏好、推荐系数、录取风险、院校层次、专业相似度排序 |
| 用户语言 | 不暴露内部状态词，不用系统化术语代替解释 |
| 多轮一致性 | 用户拒绝引导、打断、改口、追问时不丢上下文，不虚构 pending |
| 性能 | 记录 median/p95/max、模型长尾、工具长尾和重复工具；不为降延迟牺牲回复质量 |

## 5. Case 晋级规则

Autoexplorer issue 不能直接等价为产品缺陷。进入稳定回归前需要满足：

1. 能在固定 session 或可构造 fixture 中复现。
2. 上下文匹配，不把生产 prompt 直接套到无关本地方案上作为最终证据。
3. issue 不是 judge 超时、judge 未返回 JSON 或明显误判。
4. 有明确预期：应走 Policy、Explore、Intent、Plan 或 pending/apply 哪条链路。
5. 能写成断言：内容关键点、禁止词、卡片状态、followup 类型、工作区刷新、耗时阈值或工具调用路径。

## 6. 3.1.1 必跑集合

### P0 定向集合

- 压线风险咨询：`303-dialogue-near-batch-line-no-overpromise`
- 专业组内只保留最稳专业：`303-dialogue-operation-major-group-keep-safest-major`
- 确认采纳卡点击后状态变化。
- 替换预览必须展示 `from -> to`。
- 补充/替换候选按用户 intent 相关性排序。

### 稳定回归集合

- 3.0.3 真实对话衍生 88 case。
- 3.1.0 constraint plan action case。
- 3.1.0 review repair case。
- open quality。
- career direction。
- full journey。

### 扩展模拟集合

- `assets/zhiyuan-expanded-dialog-scenarios-broad2-e9e866f.json`
- `assets/zhiyuan-prod-style-dialog-scenarios-follow-vs-diverge.json`
- `assets/zhiyuan-dialog-predict-expanded-scenarios.json`

## 7. 后续落地

1. 从 P0 定向集合补单测和 e2e case。
2. 将 `assets` 中高价值场景抽成稳定 JSON case，放入 `zhiyuan-agent/examples/` 或新的统一 regression 目录。
3. 扩展回归报告，按 correctness、state、reply quality、latency、tool path 五类汇总。
4. 3.2.0 主路径实现前完成模型能力 profile，结果只作为设计输入，不在 3.1.1 增加 shadow 或桥接。
5. 每次修复后更新 [release-3.1.1-dialogue-known-issues.md](./release-3.1.1-dialogue-known-issues.md) 的状态，完成后迁入 [release-3.1.1-feature-inventory.md](./release-3.1.1-feature-inventory.md)。

## 8. 2026-06-19 3.1.1 收口回归记录

### 8.1 环境说明

- 本轮本地验证使用长驻 tool session 启动 `rank/server/agent`；`scripts/start-all.sh` 在当前执行环境中启动后进程会被回收，不能作为服务稳定性的判断依据。
- `rank`：`zhiyuan-rank/.venv/bin/python app.py`，端口 `5001`。
- `server`：`zhiyuan-server/mvn spring-boot:run -Dspring-boot.run.profiles=local -q`，端口 `8080`。
- `agent`：`INTERNAL_SERVICE_URL=http://127.0.0.1:8080 RANK_SERVICE_URL=http://127.0.0.1:5001 .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8000`。
- `agent /health` 返回 `UP`。
- `server /actuator/health` 返回 500，原因是本地 `LoginInterceptor` 拦截无 token actuator 请求；Spring 服务本身启动成功，业务接口可用。本轮不把 actuator 作为阻塞项。

### 8.2 Review/Repair 回归

命令：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_review_repair_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_311_review_repair_closure.json
```

结果：

- `steps=9`
- `successfulSteps=9`
- `failedSteps=0`
- median `26185ms`
- p95/max `45929ms`
- warnings：4 条超过 30s。

结论：

- 业务链路通过，P0-0 已修的 review/repair 卡片和方案审查路径没有失败。
- 仍需记录性能和语义观察项：`方案里高收费或者中外合作风险大的，先看看能怎么处理，别直接动` 被路由为 `analyze_adjustment`，只给处理分析，没有 pending 预览卡；当前 case 未设为失败，但属于 3.2.0 模型理解/sideEffect profile 的 golden 候选。

### 8.3 Constraint/Plan Action 回归

命令：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_310_constraint_plan_action_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_311_constraint_plan_action_closure.json
```

结果：

- `steps=9`
- `successfulSteps=8`
- `failedSteps=1`
- failed reason：`content`
- median `10387ms`
- p95/max `64610ms`
- warnings：`310-constraint-exclude-cooperative-program-preview-and-apply` 超过 60s。

通过项概览：

- `only_keep` 临床医学：生成 intent/constraint pending，确认后刷新 ordered/candidate，不直接改方案。
- `must_have` 法学：生成 intent/constraint pending，确认后刷新 ordered/candidate，不直接改方案。
- 排除中外合作：生成 user-goal plan mutation pending，卡片展示 `from -> to` 替换预览，确认后移除 4 条、补入 4 条，并刷新 ordered/candidate/review。
- 学费两万以内：生成 plan mutation pending，展示可替换数量和剩余不可处理范围。

失败项：

- Case：`310-constraint-exclude-major-preview-and-apply`
- Prompt：`不要英语相关专业，当前方案里有的话也删掉`
- 第一步工具事实已生成 `remove_units` preview：
  - `result_kind=preview_only`
  - `reply_focus` 包含 `confirmation_required`
  - `facts.resolved_apply_payload` 包含 3 个待移出 volunteer id
  - `facts.intent_update` 包含后续报考参考更新
- 实际 WebSocket followup 没有 `pendingConfirmationCard`。
- 第二步 `确认执行` 被 `no_pending_confirmation_guard` 接住，说明 pending 没有落库。

当前阻塞结论：

- 该失败阻塞 3.1.1 收口。
- 修复应只补齐“已有可执行 Plan preview 正常落 pending card”的协议落点，不新增 shadow、bridge 或文本确认兼容。
- 详细根因记录见 [release-3.1.1-dialogue-known-issues.md](./release-3.1.1-dialogue-known-issues.md) 的 P0-3。

### 8.4 Career Direction 回归

命令：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_303_career_direction_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_311_career_direction_round1.json
```

结果：

- `steps=4`
- `successfulSteps=4`
- `failedSteps=0`
- median `14983ms`
- p95/max `16476ms`

结论：

- career direction 小集合断言全过。
- 只读边界稳定：没有生成 pending/card，均走 `analyze_current_career_direction`。
- 观察项：个别 thinking 会提“读取成绩/方案/候选”，但最终文本没有伪造当前方案；作为 3.2.0 回复生成 profile 的边界样本记录。

### 8.5 Open Quality 回归

命令：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_303_open_quality_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_311_open_quality_round1.json
```

结果：

- `steps=23`
- `successfulSteps=23`
- `failedSteps=0`
- median `20350ms`
- p95 `35185ms`
- max `35853ms`

最慢样本：

- `303-open-quality-lazy-plan-too-risky-readonly`：`35853ms`
- `303-open-quality-major-compare-with-context`：`35185ms`
- `303-open-quality-career-three-direction-readonly`：`31711ms`
- `303-open-quality-budget-risk-colloquial-readonly`：`30467ms`
- `303-open-quality-career-parent-colloquial-readonly`：`30338ms`

结论：

- 断言层面全过，只读查询后的短确认 guard 正常，专业对比类“先只分析/先别记”没有误生成 pending。
- 性能长尾主要来自模型请求和最终回复生成，工具调用本身通常较短；3.2.0 profile 需要单独统计 `tool latency` 与 `generation latency`。
- 观察到一个质量问题：`方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动` 被通用 `review_plan` 结论覆盖，没有正面回答中外合作/预算风险；已记入 known issues P1-4。
- 观察到一个结构问题：`我倾向会计学和审计学，但土木工程不要` 的 sideEffect 决策认为不应直接 pending，但最终生成了 plan mutation pending；当前 case 预期接受该结果，但它说明模型判断、工具结果和确定性后处理之间仍需统一。

### 8.6 Full Journey 回归

命令：

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/dialog_regression_full_journey_cases.json \
  --response-timeout 180 \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --clear-backend-planning-intent-per-case \
  --keep-response-text \
  --assert-plan-style \
  --metrics-output /private/tmp/zhiyuan_311_full_journey_round1.json
```

结果：

- `steps=69`
- `successfulSteps=53`
- `failedSteps=16`
- `failedByReason={"content": 16}`
- median `16786ms`
- p95 `31589ms`
- max `44938ms`

主要失败聚类：

- **Fixture 前置状态失效**：大量 case 假设会话已有方案/候选/基础报考信息，但清理后实际为空；系统返回“无方案/无候选/信息不足”，case 仍期待 ordered refresh 或“已移动/已删除/已加入”。
- **弱表达是否应 pending 不稳定**：`河南大学和郑州轻工业大学可以重点关注` 被处理为只读分析，case 期待后续 `确认` 写入学校关注；需要在 3.2.0 profile 中明确“可以重点关注”这种表达的 sideEffect 规则。
- **Career intent 卡片展示缺陷**：`先把体制内稳定就业当成优先参考` 的结构化 items 正确，但卡片 summary/content 被通用 title 覆盖；已记入 known issues P0-4。
- **负向地域排除未落卡**：`东北西北都不要，必须避开` 被模型判为高置信 intent preview，但最终没有 pending；已记入 known issues P0-5。
- **pending 与只读查询抢焦点**：`先不确认，当前方案里有没有护理或者中医学` 只回答 pending 边界，没有查询当前方案；已记入 known issues W4。
- **候选查询缺前置条件**：缺分数/位次时，系统容易把空候选解释成“分数或筛选条件导致没命中”；已记入 known issues W6。

当前处理结论：

- `dialog_regression_full_journey_cases.json` 当前不能直接作为 3.1.1 发布门禁；应先修 fixture/断言契约。
- 不应为了通过这些 case 在业务层增加空方案移动/删除/补入兼容逻辑。
- 可从本批中提炼 P0-4/P0-5 这类不依赖 fixture 的窄修 case，以及 W4/W5/W6 这类 3.2.0 profile golden。

### 8.7 本轮新增回归结论

- 当前最明确的 3.1.1 小修候选：
  - P0-3：已有可执行 Plan preview 未落 pending card。
  - P0-4：career intent card summary/content 被 title 覆盖。
  - P0-5：negative-only 地域排除未落 pending card。
- 当前不建议 3.1.1 修的结构/设计问题：
  - full journey fixture 隐含状态失效。
  - mixed pending/read-only turn 的唯一 sideEffect 决策。
  - 候选/方案查询缺前置条件时的 missingInfo 处理。
  - 工具规划过宽和最终回复生成长尾。

### 8.8 3.0.3 累积回归补跑

用户提醒 3.0.3 还有大量累积 case，本轮在同一套本地 `rank/server/agent` 服务上补跑 303 系列固定集。所有 dialogue runner 命令均使用：

- `--response-timeout 180`
- `--clear-history-per-case`
- `--clear-backend-pending-per-case`
- `--clear-backend-planning-intent-per-case`
- `--keep-response-text`
- `--assert-plan-style`

结果汇总：

| case set | output | steps | pass | median | p95 | max | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `dialog_regression_303_dialogue_derived_cases.json` | `/private/tmp/zhiyuan_311_303_dialogue_derived_round1.json` | 88 | 88 | `18654ms` | `43388ms` | `66362ms` | 断言全过，但长尾明显 |
| `dialog_regression_303_realistic_user_cases.json` | `/private/tmp/zhiyuan_311_303_realistic_user_round1.json` | 9 | 7 | `20276ms` | `42053ms` | `42053ms` | 2 条内容失败主要是旧断言契约噪声 |
| `dialog_regression_303_effect_perf_cases.json` | `/private/tmp/zhiyuan_311_303_effect_perf_round1.json` | 14 | 14 | `17410ms` | `38054ms` | `40232ms` | 断言全过，模型生成长尾仍在 |
| `dialog_regression_303_career_direction_cases.json` | `/private/tmp/zhiyuan_311_303_career_direction_round1.json` | 4 | 4 | `16605ms` | `17917ms` | `17917ms` | 只读职业方向链路稳定 |
| `dialog_regression_303_open_quality_cases.json` | `/private/tmp/zhiyuan_311_303_open_quality_round1.json` | 23 | 23 | `23080ms` | `37921ms` | `37972ms` | 质量断言全过，但暴露 focused review 和 sideEffect 边界问题 |

本轮新增关键观察：

- 3.0.3 累积集不能只看 pass/fail。`open_quality` 和 `dialogue_derived` 断言通过，但仍暴露回复聚焦、sideEffect 裁决和性能长尾问题。
- `方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动` 仍被通用 `review_plan` 结论覆盖，没有聚焦中外合作/预算承受力。
- `这版是不是太冲了，能不能给我说人话` 能走 `review_plan`，但最终回复仍偏审查清单，大白话表达不稳定。
- `我倾向会计学和审计学，但土木工程不要` 生成的是 `plan_mutation/apply_fix_proposal` pending，偏好采纳和当前方案替换预览被绑到同一张高副作用卡里；旧 case 接受该结果，但它说明 `intent_change` 与 `plan_mutation` 的唯一 sideEffect 边界需要 3.2.0 明确。
- 专业对比、职业方向、候选查询等场景的工具耗时通常不高；长尾主要来自模型选工具和最终生成，多工具链路会放大到 30-40s。
- `realistic_user` 两个失败不宜直接定性为产品回退：
  - `303-real-user-lazy-plan-risk`：业务回答可用，失败是 thinking 文案白名单不匹配。
  - `303-real-user-vague-confirm-guard`：无 pending guard 生效，失败是旧断言词与当前文案不完全匹配。

### 8.9 Model Provider 303 补充检查

本轮补查了 `model_provider_303_quality_readonly_cases.json`，但需要严格区分两类模式：

- `--agent-only --agent-url ws://127.0.0.1:8000/...` 只是复用当前已经启动的 agent。provider 配置里的 provider/model 只会作为结果标签，不会真正切换模型。
- 要做真实 provider 对比，必须用 `--start-agent` 为每个 provider 单独启动 agent，并通过环境变量注入对应 `LLM_*`。

已得到结果：

| mode | output | steps | assertion failures | final median | final p95/max | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| existing agent, labeled `siliconflow-kimi-k26` | `/private/tmp/zhiyuan_311_model_provider_303_quality_readonly_agent_existing.json` | 10 | 1 | `34.374s` | `60.496s` | 只能作为当前 8000 agent 主链路样本，不能作为 provider 横评 |
| GLM 5.2, `--start-agent` | `/private/tmp/zhiyuan_311_model_provider_303_quality_readonly_glm52_validid.json` | 10 | 5 | `0.304s` | `0.849s` | 当前 key 返回 provider 403 余额不足，结果是系统错误兜底，不可计入模型效果 |

GLM 5.2 前置检查：

- SiliconFlow `/models` 暴露的真实模型 ID 是 `zai-org/GLM-5.2`，不是 `Pro/zai-org/GLM-5.2`。
- `Pro/zai-org/GLM-5.2` 会返回 400 `Model does not exist`。
- `zai-org/GLM-5.2` 在当前 key 下返回 403 `insufficient balance`。

处理结论：

- provider benchmark 必须增加前置可用性校验：模型 ID、鉴权、余额、direct smoke、agent startup 都通过后，才进入质量评分。
- 错误兜底回复很快，不能把低延迟误读为模型能力好。
- 3.2.0 profile 可以把 GLM 5.2 加为候选，但要等 provider key/余额可用后再跑，不能用本轮结果参与模型选择。

### 8.10 2026-06-20 历史积累场景三轮回归阶段记录

用户要求所有积累场景都跑 3 遍，用平均效果和性能观察模型稳定性。本轮按串行方式执行，避免并发压测影响机器稳定性和结果可解释性。

当前有效运行命名空间：

```bash
cd /Users/baiyang/git/zhiyuan/zhiyuan-agent
.venv/bin/python /private/tmp/zhiyuan_311_three_round_runner.py \
  --phase historical \
  --rounds 3 \
  --run-id v2hist \
  --session-base 933100000
```

说明：

- `v2hist` 早期有一批未提权执行造成的 `PermissionError: Operation not permitted` 污染产物，时间集中在 `2026-06-20 01:29` 左右。
- 这些旧 `r2/r3` 文件不是有效第二、第三轮；正式统计只认有效 metrics：`summary.elapsed.count` 存在、records 非空、日志中无 PermissionError。
- 已修正阶段聚合脚本 `zhiyuan-agent/tmp_311_regression_aggregate.py`，避免把同一日志尾部的 `source_missing` 误归到所有 failure；fixture 缺失改为 warning 单独统计。
- 阶段聚合输出：`/private/tmp/zhiyuan_311_3round_v2hist_stage_aggregate.json`。
- `special` 对应 `zhiyuan-agent/examples/dialog_regression_special_cases.json`，来源是 2026-05-02 前后新增的“特殊政策 special 场景回归”，覆盖警校/提前批、艺考、复读生、专项计划、强基、本专兼报和 12 轮长链路；后续 3.0.3/3.1.0 文档把它纳入历史 live case 统一回归，但它不是 3.0.3 或 3.1.0 专属新集。
- 当前已完成有效 round1 全部 12 个历史 case set，并已进入有效 round2；以下不是三轮最终结论，只是有效 round1 阶段记录。

当前有效 round1 汇总：

| case set | steps | pass | median | p95 | max | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `dialog_regression_plan_cases.json` | 6 | 6 | `24399ms` | `36900ms` | `36900ms` | 断言通过 |
| `dialog_regression_plan_correctness_cases.json` | 30 | 29 | `18190ms` | `32151ms` | `37585ms` | 1 条偏断言/措辞契约 |
| `dialog_regression_full_journey_cases.json` | 69 | 53 | `12591ms` | `29031ms` | `74197ms` | 多数失败受 fixture 缺失影响，不作稳定门禁 |
| `dialog_regression_lifecycle_cases.json` | 36 | 36 | `15517ms` | `32397ms` | `40730ms` | 断言通过 |
| `dialog_regression_mainline_cases.json` | 123 | 123 | `9509ms` | `24183ms` | `46508ms` | 断言通过 |
| `dialog_regression_advanced_cases.json` | 56 | 56 | `15182ms` | `31503ms` | `34394ms` | 断言通过 |
| `dialog_regression_comprehensive_cases.json` | 102 | 99 | `20731ms` | `44044ms` | `112704ms` | 断言失败主要是旧 keyword 契约，但有真实工具预算问题 |
| `dialog_regression_enriched_cases.json` | 67 | 58 | `20378ms` | `46224ms` | `61626ms` | 暴露多个真实协议/语义问题 |
| `dialog_regression_robust_cases.json` | 46 | 46 | `14454ms` | `30315ms` | `64923ms` | 断言通过，但有设计观察项 |
| `dialog_regression_science_cases.json` | 122 | 122 | `12135ms` | `29842ms` | `35220ms` | 断言通过，但有 pending/analysis 边界观察项 |
| `dialog_regression_score_tier_cases.json` | 36 | 36 | `12456ms` | `21223ms` | `22621ms` | 断言通过，但有无方案上下文事实校验观察项 |
| `dialog_regression_special_cases.json` | 68 | 68 | `17382ms` | `32158ms` | `42535ms` | 断言通过，但暴露特殊政策/长链路协议问题 |

阶段结论：

- 不能定性为“整个框架不可用”。在有完整 fixture 的 session（如 `26`、`35`）里，审查、风险展示、部分 plan mutation preview/apply 路径能工作。
- 当前问题是混合型：fixture 数据缺失、旧断言过窄、模型语义强度误判、pending 状态机抢焦点、工具调用预算失控同时存在。
- `dialog_regression_full_journey_cases.json`、部分 comprehensive/enriched 合成 case 依赖的源会话缺少 `session_volunteer_<id>.json`，应先修 fixture 契约，再作为稳定发布门禁。
- 即使断言全过的 `robust`，日志仍显示 `加到意向` 被升级为 `must_have/至少保留`、pending 采纳吞掉同轮“出方案”、短输入重复工具调用等设计问题；这些必须进入 3.2.0 profile。
- `score_tier`、`special` 也属于“断言通过但人工 review 有问题”的集合：现有断言偏风格/流程，不能覆盖偏好强度、状态事实回答、pending 栈和领域计算正确性。

已确认的阶段问题样本：

- `specific-multi-pin-and-fill-26`：`帮我把方案里第1个和第2个冲档锁定` 被路由为 `move_ordered_unit/no_change`，没有形成锁定动作或 pending，后续 `确认锁定` 进入 no-pending。
- `specific-conditional-reorder-26`：`保底区里录取率最高的调到保底第一位` 语义上是“保底区内第一位”，实际倾向被理解成全方案第一位。
- `convergence-full-12-turn-explore-to-final-600-hb`：用户说 `帮我出一版方案` 时被错误生成“只保留专业：信息工程”的意向预览；随后用户追问方案冲稳保，系统才生成 plan preview，且后续又按“没有正式方案”回答。
- `convergence-parent-guided-550-sd`：`方案里有没有民办的` 这类只读查询被转成排除高收费/民办/中外合作的 intent pending，且卡片 summary 被通用 title 污染。
- `robust-resume-mid-conversation`：上一轮 `把计算机类加进意向` 生成 pending 后，下一轮 `现在基于这些出方案` 只采纳 pending，没有继续处理“出方案”的复合诉求。
- `robust-typo-and-abbrev-580`：`保底要公办不要民辨` 把上一轮“合工大/南邮”偏好合并升级成 `只保留院校：合肥工业大学、南京邮电大学；排除民办院校`，存在历史偏好被过强收窄的问题。
- `science-software-engineering-intent-candidate`：`想学软件工程` 被判为 `mixed_answer_then_ask`，用户下一轮 `确认` 进入 no-pending；说明 analysis/mixed 场景缺少可确认 transition。
- `tier-mid-520-just-want-bachelor`：前两轮没有成功生成正式方案，第三轮用户说 `刚那个方案民办能少点不`，系统仍生成“排除民办”的 pending；说明缺少“用户引用当前方案”与真实方案状态的一致性校验。
- `special-art-580`：艺术生综合分回复把 `250 × 7.5 × 50%` 算成 `937.5` 后又说综合分约 `580`，公式/尺度表达不一致；同时 `我想去美院系比如央美国美` 被落成 `only_keep`，后续用户主动改口“实在点”。
- `special-strongbase-655`：用户问 `现在这版强基+普通批方案合理不`，系统同时做 review 和 `generate_plan` pending，把只读合理性审查升级成生成完整方案。
- `special-correction-630`：用户问 `现在方案是按620湖北算的吧`，系统只解释未采纳的华科意向，没有回答基础成绩/省份是否已更新；pending 抢占了只读事实查询。
- `special-long-chain-12-turn`：`城市优先长三角` 被误抽为“城市管理”专业并升级为 `only_keep`；未确认的 generate plan pending 残留后，后续 `冲档太冒险了删掉一个`、`稳档想换成省内的` 继续围绕旧生成预览打转，甚至同轮返回两个 pending。
- 多个“加 X 到意向”场景生成 `must_have/至少保留`，比“偏好/优先参考”更硬，应在 3.2.0 profile 中单独测偏好强度。
- `convergence-score-borderline-negotiation-530-ah#3/#5` 等只读分数断档问题触发 10 次 `query_score_line`，存在工具调用批量化和预算治理问题。
- `comprehensive-art-student-combined-score-530-sd#5` 耗时 `112704ms`，此前日志显示接近/命中请求限制；工具规划必须进入 3.2.0 latency/profile。
- `comprehensive-low-score-vocational-420-sc#3` round2 触发 `query_score_line` 46 次，最终 `UsageLimitExceeded: request_limit of 50`，单步 `120830ms`；这是工具预算和重复查询缺失的强复现。
- `comprehensive-parent-doctor-conflict-620-gd#3`：用户说 `把生物医学工程和智能医学工程加意向 排除临床医学和口腔`，系统把四个专业全部落成排除，正向/负向极性被合并错。
- `comprehensive-finance-to-cs-switch-605-js#3`：用户说 `把金融去掉 加计算机类和人工智能 地域不限`，系统生成“排除人工智能、排除计算机类”；与上一条同类，说明不是单句偶发，而是 intent polarity 编译问题。
- `comprehensive-existing-plan-deep-query-26#2`：用户问 `保底最后几个是什么学校 录取率多少`，系统已读取方案但没有列出明细，转成“你是想看末尾还是查具体学校”的澄清；只读方案查询的 projection/formatter 不足。
- `comprehensive-existing-plan-mutation-chain-35#4`：用户说 `删完了再帮我看看还剩多少个 梯度有没有问题`，系统只执行上一轮 pending apply 并刷新 workspace，没有继续回答“剩多少/梯度问题”；pending apply 与同轮后续只读查询仍未拆解。
- `enriched_r2` 中 `specific-multi-pin-and-fill-26` 相比 round1 有改善：`帮我把方案里第1个和第2个冲档锁定` 不再误路由为移动/no-change，而是说明当前工作台不支持锁定并列出对应志愿；但后续 `确认锁定` 的 no-pending 体验仍需要按“unsupported action 不制造可确认暗示”处理。
- `enriched_r2` 中 `fuzzy-geography-optimization-35` 暴露地域查询/调整两类问题：一是 `方案里的学校分布在哪些城市` 读取方案后回答“没有命中城市分布地域分布”，projection 失败；二是“北方/南方”被落成 `only_keep` 意向且耗时 `87046ms`，具体省份替换则可生成 5 条替换预览但仍有长尾。
- `robust-parent-child-dialog-600#6` round2 中，用户问 `我妈问保底是不是公办`，系统承认“现在方案还没生成”，但随后又承诺“保底层全部放公办院校、完全可以做到”；这是无正式方案 evidence 下的确定性承诺，需纳入 3.2.0 防御性回复 profile。

后续仍需完成：

- 历史集有效 round2/round3。
- 补跑当前 gate/current 集三轮，并剔除 PermissionError 污染。
- 补跑 model provider/303 扩展集三轮；GLM 5.2 必须先通过模型 ID、鉴权和余额 precheck。
- 三轮完成后再输出稳定失败、波动失败、平均耗时和 provider/profile 结论。

最新进度：

- 有效 round1：12/12 case set 完成。
- 有效 round2：`plan_r2` 6/6，`plan_correctness_r2` 29/30，`full_journey_r2` 53/69，`lifecycle_r2` 36/36，`mainline_r2` 123/123，`advanced_r2` 56/56，`comprehensive_r2` 102/102，`enriched_r2` 61/67，`robust_r2` 46/46，`science_r2` 122/122，`score_tier_r2` 36/36；当前正在跑 `special_r2`。
- `advanced` r1/r2 均 56/56，round2 median `13744ms`、p95 `29754ms`、max `48324ms`；暂未看到断言层面波动，但仍需等 round3 后再给稳定性结论。
- `comprehensive` r1 99/102，r2 102/102，断言层面有波动修复/随机性；两轮合计 pass rate `98.53%`，median `20878ms`、p95 `60714ms`、max `168893ms`。round2 p95 `94621ms` 明显恶化，主要由重复工具查询、request limit 和流式/runner 收尾等待长尾拉大。
- `enriched` r1 58/67，r2 61/67；两轮合计 pass rate `88.81%`，median `18141ms`、p95 `48442ms`、max `87046ms`。失败仍集中在旧断言/fixture 与真实状态机问题混合：未确认生成方案后的后续查询、冲稳保比例查询、只读审查聚焦、地域替换长尾。
- `robust` r1/r2 均 46/46；两轮合计 median `15109ms`、p95 `35489ms`、max `64923ms`。断言稳定通过，但“都加上/加意向”仍多次落为 `must_have/至少保留`，说明断言没有覆盖偏好强度。
- `science` r1/r2 均 122/122；两轮合计 median `11717ms`、p95 `26869ms`、max `60687ms`。只读专业/职业探索链路断言稳定，但仍有 fixture warning 和“没有正式方案时如何防御性承诺”的质量观察项。
- `score_tier` r1/r2 均 36/36；两轮合计 median `16156ms`、p95 `36057ms`、max `67424ms`。round2 明显更慢，主要来自空方案/缺基础信息下仍尝试 plan action preview 的长尾。
- `full_journey` r1/r2 都是 53/69，失败数稳定；结合日志看，主要是 fixture 源会话缺少方案/候选文件、旧断言期待空方案下也能执行 ordered refresh，以及少量真实协议缺陷（negative-only 地域未落 pending、复合 pending+review 未拆解）。
- 旧 `r2/r3` 污染文件继续排除，不参与平均值。

### 8.11 2026-06-20 历史积累场景三轮最终汇总

本节为 `v2hist` 有效三轮最终统计，覆盖 12 个历史 case set，共 36 个批次。早期 `2026-06-20 01:29` 左右因未提权执行产生的 `PermissionError` 污染输出已排除；正式统计只认当前有效 metrics 和日志无 `PermissionError` 的批次。

聚合输出：

- `/private/tmp/zhiyuan_311_3round_v2hist_stage_aggregate.json`
- runner 状态：最后一个批次 `special_r3` 为 `68/68`，总 runner 退出码为 `1`，原因是历史三轮中存在失败 case，不代表最后批次失败。

三轮汇总：

| case set | total steps | pass | fail | pass rate | median | p95 | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `advanced` | 168 | 167 | 1 | `99.40%` | `14031ms` | `29754ms` | `53124ms` |
| `comprehensive` | 306 | 303 | 3 | `99.02%` | `20213ms` | `50572ms` | `168893ms` |
| `enriched` | 201 | 181 | 20 | `90.05%` | `19438ms` | `42630ms` | `87046ms` |
| `full_journey` | 207 | 160 | 47 | `77.29%` | `11275ms` | `32135ms` | `74197ms` |
| `lifecycle` | 108 | 108 | 0 | `100.00%` | `14672ms` | `32127ms` | `52608ms` |
| `mainline` | 369 | 369 | 0 | `100.00%` | `9617ms` | `24988ms` | `70955ms` |
| `plan` | 18 | 18 | 0 | `100.00%` | `21322ms` | `38763ms` | `38763ms` |
| `plan_correctness` | 90 | 87 | 3 | `96.67%` | `17180ms` | `32151ms` | `74296ms` |
| `robust` | 138 | 138 | 0 | `100.00%` | `16263ms` | `46424ms` | `67791ms` |
| `science` | 366 | 366 | 0 | `100.00%` | `12736ms` | `32682ms` | `60687ms` |
| `score_tier` | 108 | 108 | 0 | `100.00%` | `16242ms` | `34901ms` | `67424ms` |
| `special` | 204 | 204 | 0 | `100.00%` | `17382ms` | `35816ms` | `62351ms` |
| **total** | **2283** | **2209** | **74** | **96.76%** | - | - | - |

round3 关键结果：

- `plan_r3`：6/6，median `17636ms`，p95 `23911ms`。
- `plan_correctness_r3`：29/30，median `15609ms`，p95 `29941ms`；稳定失败是 `correctness-analyze-adjustment-35` 期待“优化”的旧措辞断言。
- `full_journey_r3`：54/69，median `11934ms`，p95 `36018ms`；多数失败仍与 fixture 前置状态和旧断言契约相关。
- `lifecycle_r3`：36/36，median `13570ms`，p95 `33429ms`。
- `mainline_r3`：123/123，median `10056ms`，p95 `27284ms`。
- `advanced_r3`：55/56，median `13965ms`，p95 `25756ms`；失败为回复出现旧断言禁止词 `你选哪个`。
- `comprehensive_r3`：102/102，median `18185ms`，p95 `35068ms`。
- `enriched_r3`：62/67，median `19619ms`，p95 `35819ms`。
- `robust_r3`：46/46，median `18674ms`，p95 `53524ms`。
- `science_r3`：122/122，median `16790ms`，p95 `39990ms`。
- `score_tier_r3`：36/36，median `16431ms`，p95 `27154ms`。
- `special_r3`：68/68，median `18428ms`，p95 `47816ms`，max `62351ms`。

失败定性：

- 不能把本轮定性为“系统整体不可用”。`mainline/lifecycle/robust/science/score_tier/special` 三轮断言均全过，说明大量主线问答、只读探索、生命周期和特殊政策基础流程仍能闭环。
- `full_journey` 是最大失败来源，三轮 47 个失败。多数与回归资产 fixture 契约有关：case 假设已有方案、候选、基础报考信息或 pending，但 runner 清理并 clone 后实际状态为空或不完整；系统返回 no-op/信息不足，而旧断言期待 ordered refresh、删除、移动、补入或确认成功。
- `enriched` 三轮 20 个失败，混合了旧 keyword 断言、fixture 缺失、只读 review 聚焦不足、地域/学费调整长尾和真实状态机问题，不能简单归为单一框架失败。
- `plan_correctness` 三轮稳定 1 条失败，偏旧措辞断言；不建议为此增加业务兼容逻辑。
- `comprehensive` 失败在 r1 出现、r2/r3 消失，说明存在模型输出波动和断言覆盖不足；但其中暴露的重复工具查询、request limit 和 plan query projection 问题仍是真问题。

稳定问题结论：

- **Side effect 单一裁决缺失**：同一轮可能同时出现 intent preview、plan preview、direct tool return 和后处理恢复，导致 pending 丢失、pending 抢只读、同轮双 pending 或 apply 后吞掉后续只读查询。
- **偏好强度和极性不稳定**：`加进意向/作为参考/优先` 经常被升级为 `must_have/only_keep`；同一句中 `加意向` 与 `排除/去掉` 并存时，负向极性会扩散到正向实体。
- **当前方案只读查询能力不足**：系统读取到方案后，仍不能稳定回答“保底最后几个是什么学校、录取率多少”“学校分布在哪些城市”“高收费占比多少”等 projection/slice/focus 问题。
- **pending 与只读查询边界不清**：存在 pending 时，用户问基础信息、当前方案是否命中、剩余数量和梯度时，经常被 pending 边界话术抢焦点。
- **特殊批次/特殊政策结构弱**：强基、提前批、艺术生、本专兼报、专项计划等场景常被压成普通学校/专业意向，缺少 batch/type/path 的一等结构。
- **性能长尾真实存在但需拆层**：重复 `query_score_line`、`query_admission_score`、官方来源检索会拉高 p95/max；同时部分样本 runner `finalMessageMs` 明显大于 agent 内部耗时，后续 profile 必须拆 agent/tool/WS runner 三层统计。

3.1.1 处理边界：

- 只修 P0 小问题和明确协议落点，不用 shadow、bridge 或多路径兼容去“吃掉”历史资产噪声。
- 对 fixture 前置状态不成立的 case，先修 case 契约和数据准备，不倒逼业务代码支持空方案移动/删除/替换。
- 对 sideEffect、偏好强度、plan query、pending 复合 turn、特殊批次等结构问题，进入 3.2.0 profile 和主路径设计。

下一步回归顺序：

1. 启动 `current` gate 三轮，覆盖 3.0.1/3.0.2/3.0.3/3.1.0 当前发布门禁集合。
2. 补跑 provider/303 扩展集合，但真实 provider 评分必须先通过模型 ID、鉴权、余额和 direct smoke precheck。
3. 汇总 current 与 provider 结果后，再决定 3.1.1 是否只做 P0-3/P0-4/P0-5 这类窄修，随后进入 3.2.0 profile。

### 8.12 2026-06-20 current gate 三轮最终汇总

本节为 `v2current` 有效三轮最终统计，覆盖 13 个 current gate case set，共 39 个批次。执行中曾因磁盘不足污染部分 r3 产物；已清理测试克隆文件并删除污染 metrics/log，使用 `--resume` 重跑受影响批次。最终统计确认 current logs 中无 `No space left on device` 残留。

聚合输出：

- `/private/tmp/zhiyuan_311_3round_v2current_stage_aggregate.json`

运行命名空间：

```bash
cd /Users/baiyang/git/zhiyuan/zhiyuan-agent
.venv/bin/python /private/tmp/zhiyuan_311_three_round_runner.py \
  --phase current \
  --rounds 3 \
  --run-id v2current \
  --session-base 934100000
```

三轮汇总：

| case set | total steps | pass | fail | pass rate | median | p95 | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `301_agent_smoke` | 18 | 18 | 0 | `100.00%` | `19405ms` | `49188ms` | `49188ms` |
| `302_agent` | 24 | 24 | 0 | `100.00%` | `17201ms` | `49869ms` | `55475ms` |
| `302_effect_perf` | 33 | 32 | 1 | `96.97%` | `18159ms` | `35084ms` | `50289ms` |
| `302_explore_intent` | 66 | 61 | 5 | `92.42%` | `13101ms` | `55843ms` | `79507ms` |
| `302_readonly_real_session` | 6 | 6 | 0 | `100.00%` | `19308ms` | `27695ms` | `27695ms` |
| `303_career_direction` | 12 | 12 | 0 | `100.00%` | `16018ms` | `22567ms` | `22567ms` |
| `303_dialogue_derived` | 264 | 261 | 3 | `98.86%` | `17937ms` | `42473ms` | `172051ms` |
| `303_effect_perf` | 42 | 42 | 0 | `100.00%` | `14352ms` | `31312ms` | `37894ms` |
| `303_open_quality` | 69 | 69 | 0 | `100.00%` | `18967ms` | `34511ms` | `44208ms` |
| `303_realistic_user` | 27 | 23 | 4 | `85.19%` | `18452ms` | `38602ms` | `45988ms` |
| `310_constraint_plan_action` | 27 | 23 | 4 | `85.19%` | `16040ms` | `39311ms` | `39875ms` |
| `310_production_abstracted` | 66 | 66 | 0 | `100.00%` | `18255ms` | `45534ms` | `49407ms` |
| `310_review_repair` | 27 | 27 | 0 | `100.00%` | `25899ms` | `42560ms` | `45004ms` |
| **total** | **681** | **664** | **17** | **97.50%** | - | - | - |

稳定通过信号：

- `301_agent_smoke`、`302_agent`、`302_readonly_real_session`、`303_career_direction`、`303_effect_perf`、`303_open_quality`、`310_production_abstracted`、`310_review_repair` 三轮断言全过。
- `303_dialogue_derived` 三轮 261/264，前两轮 88/88，第三轮 85/88；失败主要是两条性能硬阈值和一条只读边界文案。
- `303_open_quality` 三轮全过，但人工 review 仍复现 focused review 问题：`方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动` 仍可能被通用 review 清单覆盖。

稳定失败和波动失败：

- **稳定 P0：`310-constraint-exclude-major-preview-and-apply` 三轮全失败。**
  - prompt：`不要英语相关专业，当前方案里有的话也删掉`
  - 三轮均为 `assertFollowupType=pendingConfirmationCard` 和 `assertFollowupCount=1` 失败。
  - 工具链路均已有 `remove_units preview_only`，但最终没有 pending card；这是 P0-3 的稳定复现。
- **波动 P1/结构问题：学费两万以内预览在 r2 失败。**
  - prompt：`太贵的学校别放了，学费最好控制在两万以内`
  - r1/r3 可生成 pending 预览，r2 只做 focused review 并刷新 review，没有 pending。
  - 定性为 `review_plan` 与 `preview_fix_proposal` 边界不稳定，进入 3.2.0 `review evidence -> proposal endpoint` 设计；若要 3.1.1 收 gate，需要窄修现有 plan action 落点。
- **稳定 P0/P1：career intent 卡片展示在 r2/r3 失败。**
  - prompt：`先把体制内稳定就业作为参考方向`
  - r2/r3 断言未命中 `确认/体制内/稳定`，对应 P0-4：结构化 items 存在但回复/card 被通用 title 或空摘要覆盖。
- **pending + readonly query 波动：**
  - `先不确认，看看这个偏好会影响方案吗` 在 r1 失败，r2/r3 通过。
  - 定性为 pending 上下文与只读 query 边界不稳定，3.2.0 必测；3.1.1 不新增文本桥接。
- **测试断言噪声：**
  - `303-real-user-vague-confirm-guard` 三轮均失败，但实际是 no-pending guard 文案未命中旧白名单。
  - `303-real-user-sort-good-school-preview` r3 失败是 `thinking` 文案断言。
  - `302-soft-hard-intent-mix-with-plan-impact` 三轮失败/波动与 case 预期有关：case 期待 `确认` 无 pending，但前一轮实际生成 intent pending；需要先重新定义“财经类可以优先，但是护理和中西医结合不要”是否应 pending。

性能观察：

- current gate 多数 median 在 `13s-26s`，但 p95 普遍在 `30s-55s`。
- `303_dialogue_derived_r3` 出现两个性能硬失败：
  - `预算一般，是不是要少放中外合作`：`169466ms`。
  - `这版是不是太冲了`：`172051ms`。
- 多个样本仍显示 runner/finalMessage 与 agent 内部耗时偏离；性能 profile 需要继续拆 `agentRun.totalDurationMs`、tool latency、finalMessage 和 runner overhead。

current gate 结论：

- 当前 gate 不能作为“已收敛可发布”通过，因为 P0-3 三轮稳定失败。
- 3.1.1 必须先修 P0-3；P0-4 也应作为低风险 formatter/protocol 小修处理。
- 其它失败中，`303_realistic_user` 更偏断言契约噪声，`302_explore_intent` 和学费 preview 更偏 3.2.0 结构边界，不建议用 shadow/bridge 在 3.1.1 扩复杂度。

### 8.13 2026-06-20 P0-3/P0-4/P0-5 定向修复后复跑

本节记录 8.12 current gate 和 full journey 扩展回归暴露的 3.1.1 小修项定向复跑结果。历史三轮统计仍作为问题发现证据保留；以下结果只说明修复后的当前代码在目标 case 上通过。

| target | metrics | steps | pass | fail | median | max | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `dialog_regression_310_constraint_plan_action_cases.json` | `/private/tmp/zhiyuan_311_fix_310_constraint_plan_action_r2.json` | 9 | 9 | 0 | `16278ms` | `40199ms` | P0-3 已在定向集通过 |
| `302-explore-career-to-soft-intent` | `/private/tmp/zhiyuan_311_fix_302_career_single_after_confirm_summary.json` | 4 | 4 | 0 | `11065ms` | `22017ms` | P0-4 预览、卡片、确认回显已通过 |
| `full-journey-soft-hard-mix-major-group-remove-add` | `/private/tmp/zhiyuan_311_fix_p05_negative_region_single_full_journey.json` | 9 | 6 | 3 | `14623ms` | `21593ms` | P0-5 目标步骤已通过；整 case 仍受 fixture/旧断言影响 |

补充观察：

- P0-3 修复仍走现有 `plan preview -> pendingConfirmationCard -> confirm -> apply` 主协议，没有新增文本确认 bridge、shadow route 或兼容旁路。
- P0-4 修复限定在 career intent 摘要/卡片/确认回复的 formatter/protocol 落点，不改变 `apply_selected_intents` 的合并逻辑。
- P0-5 目标步骤已验证：`东北西北都不要，必须避开` 生成 `intent_change` pending card，summary/content 为 `排除地域：东北、西北`；下一轮确认回显 `本次内容：排除地域：东北、西北` 并刷新 ordered/candidate。
- 完整 `302_explore_intent` 复跑曾得到 21/22：剩余失败是 `302-soft-hard-intent-mix-with-plan-impact` 的旧断言期待“确认时无 pending”，但第一轮实际生成了 intent pending。该项应重定义软偏好+硬排除的 pending 契约，不应用 3.1.1 兼容逻辑满足旧断言。
- `full-journey-soft-hard-mix-major-group-remove-add` 仍有 3 个失败，原因是前置专业方向第一步被语义降级为分析而非 pending，以及空方案/空候选下旧断言仍期待删除/补入 apply；不作为 P0-5 回退。

### 8.14 2026-06-20 P0 小修后小范围回归

本节记录 P0-3/P0-4/P0-5 小修后，在独立 `8044` agent 上做的小范围功能回归。目标不是替代完整三轮 gate，而是确认 3.1.1 小修项自身和 review/repair 防串扰链路没有立即回退。

环境：

- `agent`：`INTERNAL_SERVICE_URL=http://127.0.0.1:8080 RANK_SERVICE_URL=http://127.0.0.1:5001 .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8044`
- `agent /health` 返回 `UP`。
- `rank /health` 正常；`server /actuator/health` 仍受本地 interceptor 影响返回 500，但业务接口可用。

回归结果：

| target | metrics | steps | pass | fail | median | p95/max | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| P0-3 constraint plan action | `/private/tmp/zhiyuan_311_small_regression_p03_constraint_plan_action.json` | 9 | 9 | 0 | `16855ms` | `44115ms` | `不要英语相关专业...` 已能落 plan pending 并确认执行；本轮实际走 `apply_fix_proposal` 预览/确认链路，协议闭环通过 |
| P0-4 career intent | `/private/tmp/zhiyuan_311_small_regression_p04_career.json` | 4 | 4 | 0 | `11669ms` | `16227ms` | `体制内/稳定就业` 预览、卡片和确认回显均通过 |
| P0-5 negative region | `/private/tmp/zhiyuan_311_small_regression_p05_negative_region.json` | 2 | 2 | 0 | `5573ms` | `8971ms` | `东北西北都不要，必须避开` 生成 `排除地域：东北、西北` pending，确认后刷新 ordered/candidate |
| review/repair 防串扰 | `/private/tmp/zhiyuan_311_small_regression_review_repair.json` | 9 | 9 | 0 | `22385ms` | `42928ms` | review、分析、预览和重新审查链路均未因 P0 小修回退 |

性能和质量观察：

- review/repair 小回归有 2 条超过 30s 的 latency warning：
  - `310-review-shortage-honesty`：`42928ms`。
  - `310-review-fix-explain-hierarchy`：`31328ms`。
- P0-3 当前通过路径从早先的直接 `remove_units` 变成了 `apply_fix_proposal` 方案提醒处理；只要仍满足 `preview -> pendingConfirmationCard -> confirm -> apply` 主协议，不在 3.1.1 强行约束具体 action family。
- `310-review-fix-preview-then-apply` 对“高收费/中外合作先看看怎么处理，别直接动”仍可能只给分析结论而不是 pending 预览；本 case 断言未失败，但属于 side-effect 判定和 review evidence -> proposal 的 3.2.0 profile 样本。

3.1.1 当前收口判断：

- P0-3/P0-4/P0-5 已完成窄修，并通过小范围功能回归。
- 小修没有引入文本确认 bridge、runtime shadow 或新旧双路径兼容；仍沿用现有 pending/apply 主协议。
- 剩余主要问题不是继续在 3.1.1 叠兼容逻辑能收敛的类型：fixture 前置状态、旧断言契约、费用类 preview 波动、pending+readonly 复合 turn、PlanQuery projection、特殊批次 schema 和性能长尾都应进入 3.2.0 profile 与主路径设计。

### 8.15 2026-06-20 3.1.1 冻结封版验证

封版前补充验证：

| scope | command / evidence | result |
| --- | --- | --- |
| Agent 定向单测 | `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_regression_runner.py tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_semantic_action_tool.py -q` | `662 passed` |
| Server proposal 单测 | `cd zhiyuan-server && mvn -q -Dtest=UserGoalProposalBuilderTest test` | passed |
| P0 小范围 e2e | 见 8.14 四个 metrics 文件 | P0-3 9/9、P0-4 4/4、P0-5 2/2、review/repair 9/9 |

封版时补充修复：

- 封版单测发现 `only_keep + 负向专业` 边界回归风险：`不要英语相关专业，当前方案里有的话也删掉` 若模型误标为 `only_keep`，不能在 intent tool 中降级成普通“排除专业” pending，也不能保留模型推断出的正向父级 `文学/外国语言文学类`。
- 已收窄 P0-5 的 negative-only 降级范围：仅允许纯负向地域在模型误标 `only_keep/must_have` 时降级为 `default` 排除地域 pending；负向专业/院校缺少明确正向范围时继续阻断，交由方案 preview 主链路处理。
- 相关单测已覆盖：负向专业 only_keep 阻断、负向地域排除通过、真实 only_keep 地域正向范围恢复。

冻结结论：

- 3.1.1 封版冻结，不再继续增加兼容桥接或 shadow 路径。
- 后续只接受 P0-3/P0-4/P0-5 明确回退修复；其它结构性问题进入 3.2.0 profile 和主路径设计。
