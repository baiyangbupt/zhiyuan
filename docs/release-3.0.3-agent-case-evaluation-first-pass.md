# Release 3.0.3 Agent Case Evaluation

本文记录 `3.0.2` 与 `3.0.3` 的 case 级对照结果，以及补充的质量评分和多模型对照结果。

发布收口说明：本文件是历史 first-pass 评估记录，不作为当前发布结论。当前总览、最终回归和升级口径以 `docs/release-3.0.3-summary-and-upgrade-plan.md` 为准。

状态说明：

- 本文件保留的是此前 `3.0.3` 快路径 / semantic shadow 试验期的 first-pass 评估结果，用于历史对照和问题复盘。
- 2026-05-29 起，运行时代码已回到 `prod-3.0.2` 基线，并已重新跑 88 个 dialogue-derived full agent case。
- 因此本文件中的 `3.0.3` 结果不能视为当前运行时代码状态；新的基线结论以 `docs/release-3.0.3-agent-effect-performance-deep-dive.md` 的 `4.9 full agent 88 case 基线复盘` 为准。

当前这轮先看：

- 路由是否更稳。
- 延迟是否下降。
- 确认边界是否还在。
- 有没有新增回退或失败。

说明：第一轮只覆盖修复前 / 修复后版本的第一层对照，不能单独代表整体结论。本文件后续补充了带完整回复文本的质量评估，以及同一批只读/预览 case 的多模型对照。

详细文本级评审见 `docs/release-3.0.3-agent-response-quality-review.md`，其中逐 case 记录了用户输入、实际回复、质量评分、问题和建议修复方向。

说明：

- 这一轮使用的是现成的 `dialog_regression_302_effect_perf_output.json` 和 `dialog_regression_303_effect_perf_output.json`。
- 当前输出还没有保留完整回复文本，所以这轮先做 **case 级效果 / 延迟 / 副作用** 分析。
- 下一轮要补文本级对照，需要用 `dialog_regression_runner.py --keep-response-text` 重跑。

## 1. 总体结果

| 版本 | steps | warnings | failures | median | p95 / max |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3.0.2 | 11 | 4 | 0 | 31.994s | 140.709s |
| 3.0.3 | 11 | 1 | 1 | 17.740s | 149.775s |

整体看：

- `3.0.3` 的中位延迟明显下降。
- 但极慢 case 还在，且新出现了一个确认链路的超时失败。

## 2. case 级对照

| case | prompt | 3.0.2 | 3.0.3 | 结论 |
| --- | --- | ---: | ---: | --- |
| 方案状态查看 | 看看现在的方案，给我一个结构化一点的结论 | 60.651s | 10.755s | 明显提升 |
| 职业方向承接 | 当前方案对体制内稳定就业方向承接得怎么样，先不要改方案 | 140.709s | 149.775s | 仍慢，且略回退 |
| 单志愿移动 preview | 把第2个志愿移到第4位 | 69.047s | 3.507s | 明显提升 |
| 单志愿移动 confirm | 确认 | 4.461s | 12.171s | 回退，但仍可接受 |
| 专业组移动 preview | 把第4个专业组移到第2位 | 62.857s | 15.289s | 明显提升 |
| 专业组移动 confirm | 确认 | 5.406s | 32.703s | 回退，且超出 20s 目标 |
| 局部查询 | 青岛城市学院相关专业是不是有多个，先帮我判断一下，不要直接改方案 | 17.496s | 58.836s | 回退，需继续看 |
| 专业对比 | 法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好 | 111.758s | 56.582s | 明显提升，但仍偏慢 |
| Intent preview | 我倾向法学和财政学，但护理不要 | 21.435s | 17.740s | 轻微提升 |
| Intent follow-up | 先不确认，看看这个偏好会影响方案吗 | 31.994s | 60.850s | 明显回退 |
| no pending guard | 确认 | 2.145s | 2.172s | 基本稳定 |

## 3. 这轮能确认的结论

### 3.1 已经明显改善的部分

- 方案概览类回复快了很多。
- 单志愿移动 preview 快了很多。
- 专业组移动 preview 快了很多。
- 专业对比只读回复明显下降。
- Intent 首轮预览略有下降。

### 3.2 还需要继续盯的部分

- 职业方向承接分析仍然很慢。
- 专业组确认链路出现了 32s 级别慢例。
- “先不确认，看看这个偏好会影响方案吗”这类追问仍偏慢。
- 局部查询出现了回退，需要继续定位是路由、后端读状态还是回复组织的问题。

### 3.3 这轮的新失败

- `302-effect-major-group-unit-move-preview-confirm` 的确认轮在 `3.0.3` 出现了 `maxElapsed FAILED`。
- 这说明 preview 虽然变快了，但 confirm / 后端状态重建这条链路还需要再拆。

## 4. 版本判断

`3.0.3` 不是整体回退，结论更像是：

- 方案预览主链路已经明显改善。
- 只读专业对比也明显改善。
- 但个别 confirm 和 Explore 追问链路还存在慢点。
- 所以这轮是 **局部改善明显，但还没到可放松验收的程度**。

## 5. 下一步

1. 对慢 case 单独做根因拆解：
   - 职业方向承接
   - 专业组 confirm
   - 局部查询回退
   - Intent follow-up
2. 继续补开放式 Explore / Intent case，避免只用快路径 case 评估模型。

## 6. 质量评分补跑

2026-05-25 使用 `dialog_regression_runner.py --keep-response-text` 重跑 `examples/dialog_regression_303_effect_perf_cases.json`，输出：

- `/private/tmp/dialog-regression-303-current-text.json`
- `/private/tmp/dialog-case-evaluation-303-quality-report.json`

结果：

| 指标 | 结果 |
| --- | ---: |
| steps | 13 |
| failedSteps | 0 |
| min | 2.117s |
| median | 2.319s |
| p95 | 3.616s |
| max | 4.922s |

代表性回复质量观察：

| case | 观察 |
| --- | --- |
| 方案状态 | 已输出数量、冲稳保、审查提醒、数量缺口、偏好承接和下一步，信息比早期“方案情况如下”更完整 |
| 局部查询 | 能直接返回命中数量和示例，未触发工作台联动卡片，也没有内部字段外露 |
| 方案移动/加入/排序预览 | 能明确“需要确认后才执行”，保持 `preview -> confirm -> apply` 边界 |
| 专业组移动 | 能说明按专业组顺序移动，不是按单条志愿位置移动 |
| 职业方向 | 有分析结论、当前判断、候选机会和下一步，但仍有模板感，后续需要继续优化自然度和个性化 |
| 专业对比 | 已保留足够信息，不再只是薄回复；能说明缺少个性化评分时不强行给系统分数 |
| Intent preview | 能说清待确认专业偏好和排除项，确认前不写入 |

本轮仍不能说明所有开放式回复都已经优秀。原因是这 13 个 step 中，很多已经走结构化快路径，回复主要由业务事实和 renderer 组成，模型生成影响较小。

## 7. 多模型对照

2026-05-25 使用同一批只读/预览 case 进行四模型对照，避免确认执行修改方案状态导致 provider 间上下文不一致。输出：

- `examples/model_provider_303_quality_readonly_cases.json`
- `/private/tmp/model-provider-303-quality-readonly-benchmark.json`
- `/private/tmp/dialog-case-evaluation-303-readonly-report.json`

模型候选：

| provider | model |
| --- | --- |
| siliconflow-kimi-k26 | `Pro/moonshotai/Kimi-K2.6` |
| siliconflow-minimax-m25 | `Pro/MiniMaxAI/MiniMax-M2.5` |
| siliconflow-deepseek-v4-flash | `deepseek-ai/DeepSeek-V4-Flash` |
| siliconflow-glm-51 | `Pro/zai-org/GLM-5.1` |

结果：

| provider | steps | assertion failures | median first | median final | max final |
| --- | ---: | ---: | ---: | ---: | ---: |
| siliconflow-kimi-k26 | 10 | 0 | 0.092s | 0.214s | 2.164s |
| siliconflow-minimax-m25 | 10 | 0 | 0.077s | 0.160s | 2.503s |
| siliconflow-deepseek-v4-flash | 10 | 0 | 0.079s | 0.176s | 2.368s |
| siliconflow-glm-51 | 10 | 0 | 0.065s | 0.155s | 2.339s |

解读：

- 这批只读/预览 case 中，四个模型都没有断言失败。
- 由于多数 case 已经走结构化快路径，回复文本基本一致，不能据此断言某个模型的开放式表达能力更好。
- 这批结果主要证明：当前 Plan 快路径、确认边界、只读查询、Intent preview 在不同模型配置下都稳定。
- 真正需要继续对比模型效果的是开放式 Explore / Intent follow-up，例如职业方向展开、多个专业类选择、家庭约束下的专业取舍、方案影响分析等。

## 8. 当前判断

截至本轮评估，`3.0.3` 的优化方向是成立的：

- 关键 Plan 操作明显变快。
- 结构化回复可以保留足够信息，不是单纯变短。
- 确认边界没有被破坏。
- 多模型在结构化快路径下差异不大。

仍需继续推进：

- 补开放式场景质量评估，重点看内容是否僵化、是否丢信息。
- 对“职业方向承接”“Intent 追问影响方案”“局部复杂查询”继续做根因分析。
- 质量评分目前仍偏启发式，需要后续增加人工打分或 LLM-as-judge 辅助，但不能完全替代人工验收。

## 9. P1 回复质量修复补充

2026-05-25 已开始按文本级评审修复 P1 问题：

- Intent preview 不再暴露 `level3`。
- Intent confirm 不再使用“候选结果收紧”这类容易误解的表达。
- 职业方向承接分析补“当前方案承接强弱 / 数量 / 示例”。
- 专业对比在缺少系统量化评分时，也会使用本轮用户显式给出的“普通家庭 / 女生”等约束。
- 3.0.3 quality 主 case 新增方案审查场景，覆盖 review 工作台刷新和审查文本边界。

本轮已完成真实 WebSocket 复跑：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` 共 14 steps 全部通过，输出 `/private/tmp/dialog-regression-303-after-p1-quality-rerun.json`，中位耗时约 `2212ms`，最大耗时约 `4350ms`。补充单测回归覆盖 ChatService、场景稳定性、方案执行/查询和快路由，结果为 `310 passed`。

随后补充两项文本质量收口：

- 方案审查回复从一整段长句改为“审查结论 / 主要问题 / 典型涉及 / 下一步建议”的结构化要点。
- 职业方向多方向承接回复去掉重复结论和重复下一步提示，保留当前方案承接、分方向数量、方案示例和候选机会。

最终复跑结果：`/private/tmp/dialog-regression-303-after-review-and-career-polish.json`，真实 WebSocket `14/14` steps 通过，中位耗时约 `2240ms`，最大耗时约 `4140ms`；合并单测 `336 passed`。

## 10. 路由边界复核

2026-05-28 针对真实对话派生集暴露的误路由问题补做边界复核。重点不是继续把回复做短，而是避免 fast route 把开放咨询、政策资格和专业比较误接成局部查询或意向确认。

修复范围：

- 方案局部查询必须有学校或专业实体；没有实体时不再用空查询接管。
- “冷门是不是坑 / 怎么排优先级”这类开放探索或专业比较问法不走方案局部查询。
- 体检、色弱、口试、专项、资格、限制、美术基础等政策/要求类问法不生成专业意向 pending。
- 专业比较快路由补充“怎么排优先级”和 `财管 -> 财务管理` 简称。

复跑结果：

| 验证集 | steps | verdict | median | p95 | max |
| --- | ---: | --- | ---: | ---: | ---: |
| 3.0.3 effect/perf | 14/14 | `strong=14 / fail=0` | 2.249s | 3.797s | 4.156s |
| 3.0.3 open-quality | 23/23 | `strong=23 / fail=0` | 2.188s | 3.501s | 3.800s |
| 3.0.3 realistic-user 聚焦复查 | 9/9 | 无断言失败 | 约 2.168s | - | 约 3.571s |

结论：

- 前一次“专业组预览后确认失败”没有复现，单独顺序复跑确认正常，判断为并发 runner 共用同一 session 的 pending/history 干扰。
- 本轮修复后，质量基线仍保持 effect/perf 与 open-quality 全 strong，没有出现只读误联动、pending 误确认或内部字段外露。
- 80+ dialogue-derived 仍是后续主战场；这次只是先修掉 P0 误路由边界，不能把它视为整体质量完成。

归档输出：

- `/private/tmp/zhiyuan_303_effect_perf_after_route_boundary_fix_rerun.json`
- `/private/tmp/zhiyuan_303_effect_perf_after_route_boundary_fix_rerun_eval_summary.json`
- `/private/tmp/zhiyuan_303_effect_perf_after_route_boundary_fix_rerun_eval.md`
- `/private/tmp/zhiyuan_303_open_quality_after_route_boundary_fix.json`
- `/private/tmp/zhiyuan_303_open_quality_after_route_boundary_fix_eval_summary.json`
- `/private/tmp/zhiyuan_303_open_quality_after_route_boundary_fix_eval.md`

## 11. Semantic Router Shadow 模型评估

2026-05-28 补充 `SemanticIntentRouter` 阻塞 shadow 评估，验证轻量 LLM 做路由的效果与延迟。测试仍使用 `dialog_regression_303_effect_perf_cases.json`，运行时不改变真实主路由，只把 semantic frame 写入 metrics 后生成报告。

本轮报告工具同步增强：

- 每个 case 增加 `semanticMappedRoute`，把 semantic frame 映射成当前最接近的 routing path。
- summary 增加 `semanticRouterSummary.mappedRoute / currentRouteComparison / expectedRouteComparison`，便于后续形成 confusion matrix。
- semantic 实体解析兼容非字符串实体，避免模型输出 `positions: [3, {"from":4,"to":2}]` 时整条记录变成 error。

结果：

| 配置 | semantic status | 质量 verdict | latency | 结论 |
| --- | --- | --- | --- | --- |
| 主模型 `Pro/moonshotai/Kimi-K2.6` 阻塞 | success `4` / timeout `10` | strong `12` / fail `2` | median `22.261s`，p95 `22.782s` | 路由本身可解释，但阻塞成本过高 |
| `deepseek-ai/DeepSeek-V4-Flash` 默认 | success `4` / timeout `10` | strong `12` / fail `2` | median `10.428s`，p95 `14.554s` | 延迟下降但 timeout 仍多，且有确认 apply 风险 |
| `deepseek-ai/DeepSeek-V4-Flash` Non-think 修复前 | success `6` / timeout `6` / error `2` | strong `12` / fail `2` | median `10.164s`，p95 `12.196s` | Non-think 改善部分稳定性，但实体类型输出需兼容 |
| `deepseek-ai/DeepSeek-V4-Flash` Non-think 实体规范化后 | success `7` / timeout `7` | strong `12` / fail `2` | median `10.168s`，p95 `11.269s` | 解析错误清零，但仍不适合全量阻塞 |

最新 Non-think 报告：

- `/private/tmp/semantic_router_303_effect_perf_deepseek_v4_flash_nonthink_normalized_shadow_report.json`
- `/private/tmp/semantic_router_303_effect_perf_deepseek_v4_flash_nonthink_normalized_shadow_report.md`

关键结论：

- DeepSeek V4 Flash Non-think 适合作为 semantic router 候选继续 shadow，不适合直接替换主路由。
- `confirm/apply` 必须继续由确定性 pending 状态机控制，LLM semantic frame 只能参与候选判断，不能授权执行。
- 当前 prompt/context 偏重，后续要先缩小路由输入，再看是否能在低超时下用于候选冲突仲裁。

补充复核：

- router prompt 已改为预算内完整 JSON 压缩，并在 shadow 结果中记录 `promptChars`。
- 4 step Non-think 小样本中，`promptChars=368-1124`，但仍只有 `1/4` semantic success，其余 `3/4` 在 8 秒超时。
- 因此后续评估报告要同时看 `promptChars` 和 `durationMs`；如果短 prompt 仍超时，应归类为模型/平台响应问题，而不是继续无效压缩上下文。
