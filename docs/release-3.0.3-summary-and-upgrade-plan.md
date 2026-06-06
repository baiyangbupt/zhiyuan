# Release 3.0.3 Summary And Upgrade Plan

本文是 3.0.3 的发布收口文档，作为功能范围、问题修复、回归验证和 3.0.2 -> 3.0.3 升级准备的主入口。生产可执行部署步骤以 `docs/release-3.0.3-production-upgrade-plan.md` 为准。

阶段性 deep-dive、评估、旧交互设计文档仍保留历史过程，但最终口径以本文和 `release-3.0.3-agent-intent-plan-mutation-confirmation-design.md` 为准。

## 1. 当前结论

3.0.3 的核心目标是提升 Agent 对话质量、确认边界和方案操作可靠性。当前主路径结论：

- 不恢复按用户话术字符串匹配的快路由；质量优先于延迟。
- 高副作用动作统一走结构化 `preview -> pendingConfirmation -> card/short-text confirm -> apply`。
- 卡片点击是主确认入口；短文本确认只作为当前 active pending 的兜底，不能凭历史文本或模型自然语言执行。
- 软偏好和硬要求分开处理；采纳后影响后续推荐、方案检查和调整参考，不会永久缩小基础候选池，也不会自动删除当前方案。
- 只读查询、方案分析、方案审查、政策/流程咨询不应误生成确认卡片或方案调整。
- 方案动作同时覆盖专业+大学和院校专业组两种结构，移动、删除、排序和高收费问题处理都必须先生成预览卡片。
- `origin/develop` 中曾出现的“非 SUPER_VIP 全局开关”已在合并时回退，不进入 3.0.3；智能填报权益仍按 `prepareType=VOLUNTEER` 每日 2 次限制执行。

## 2. 主要功能与修复范围

### 2.1 统一确认协议

本版本把意向更新、硬要求更新和方案调整收口到 `pendingConfirmation`：

- 新增统一卡片类型 `pendingConfirmationCard`，前端支持采纳、处理中、已采纳、已过期/已替代等状态展示。
- 后端使用 `pendingConfirmation` extra-data 作为主状态源。
- `planEditCache` 只作为旧会话和旧卡片的兼容适配来源，不再作为新链路主状态。
- `pending_plan_action`、`pending_intent_change` 保留为运行时兼容字段，但模型和工具指令已明确以 `conversation_phase.pending` / 后端 `pendingConfirmation` 为准。
- 新 pending 会替代旧 active pending，旧卡片置灰，不允许继续执行。
- 无 active pending 时，用户说“确认 / 可以 / 执行吧”不会执行历史动作。

### 2.2 意向、偏好和约束

本版本补齐软偏好和硬要求的语义边界：

- `preference`：非排他偏好，影响推荐系数、专家优选推荐、方案解释和后续排序参考。
- `constraint`：排他或强限制，影响后续推荐、方案检查和方案调整边界。
- 负向软偏好和硬排除不再混淆；例如“不太想去江苏”应作为偏好，“不去江苏 / 只去北京”应作为要求。
- 正向偏好卡片不再写“降低优先级”。
- 采纳说明避免“候选池变小 / 不再进入候选 / 自动过滤”等误导表达，统一说明基础候选池不被物理缩小。
- 对已在当前方案中命中的冲突项，卡片只披露简明影响；真正删除或替换仍需再走方案调整确认卡片。

### 2.3 方案操作和方案审查

已覆盖的方案动作：

- 查询当前方案状态、局部命中、候选机会。
- 方案审查和风险解释。
- 按学校/专业/专业组命名移动。
- 按展示序号移动排序单元。
- 添加、删除、替换、调稳和排序预览。
- 高收费、中外合作、概率倒挂等审查问题的只读分析和后续删除预览。

关键修复：

- 只读问题不生成删除/替换卡片，例如“有没有高收费风险”只做方案审查。
- 明确操作才生成预览，例如“把太贵的那几个先去掉看看”生成 `remove_units` 预览卡片，确认前不执行。
- 高收费审查数量从“示例条数”修正为“总量 + 典型例子”，避免把 2 条示例误说成总量。
- 方案风险回复能感知候选池中保区不足或没有保底可补，不再空泛要求“补保底”。
- 移动/排序预览会披露当前位置、目标位置、影响对象和确认边界。

### 2.4 只读分析、政策检索和回复质量

本版本收紧工具边界，避免模型自由试工具导致副作用或空泛回复：

- Explore 方向问题优先输出综合分析，而不是把工具事实薄直返给用户。
- 地域、专业、职业取舍问题按语义进入对应只读工具，只有明确要求列当前方案/候选命中时才调用局部查询。
- 候选查询 `query_volunteer_plan` 仍是只读工具；当工具结果不足以回答完整问题时交由模型综合补充，不直接空回复。
- 报考政策、资格、流程、学校章程等问题引入官方来源检索工具；通用政策、省级政策、学校招生章程按不同 source scope 处理。
- 转专业、专项资格、体检限制、口试、学费预算等场景优先给决策框架，必要时结合官方来源，不把检索结果直接当最终结论。

### 2.5 实体识别和歧义处理

本版本加强了专业、学校、地域实体处理：

- 专业识别基于官方专业层级，补充常用简称和别名，例如财会、财管、计科等。
- 大模型抽取后再走本地规范化，避免模型把具体专业误归为门类或漏掉用户明确提到的专业。
- 对“工商管理”和“工商管理类”等可能既是具体专业又可能出现在招生计划自定义大类里的表达，后续仍需要更强的歧义澄清机制。
- 地域取舍不再依赖单一话术关键词，而是按“接受度、排斥度、是否纳入、就读体验、家庭距离、保底空间”等语义判断。

### 2.6 前端和工作区联动

前端配合点：

- 消息列表支持 `pendingConfirmationCard` 展示和按钮状态。
- 点击确认后显示处理中状态，避免用户重复点击旧卡片。
- 被替代或失效的卡片不再可点击。
- 方案工作区操作后保留当前视图，避免无意切回候选或自动展开第一条。
- 对话中的超时/处理中提示需要继续优化，避免挤占正常消息内容。

## 3. 回归和验证结果

### 3.1 Agent 单测与回归

已记录的最近回归结果（develop 合并后，2026-06-06 本地复验）：

| 验证项 | 结果 | 输出或说明 |
| --- | ---: | --- |
| Agent 全量本地测试 | `2367 passed, 8 skipped` | `cd zhiyuan-agent && .venv/bin/python -m pytest tests -q`；同步修正了过期测试断言：`confirm` 不再作为 `IntentFrame.verb`，`pin/unpin` 已从结构化 verb 移除 |
| open-quality live | `23/23` | `/private/tmp/zhiyuan_303_open_quality_live_after_candidate_pool_semantics_final_pass.json` |
| dialogue-derived live | `88/88 functional steps` | `/private/tmp/zhiyuan_303_dialogue_derived_after_develop_merge.json`；功能断言通过，但 3 个 case 超过 100s 最大耗时阈值，runner 非零退出 |

develop 合并后 88 case 指标：

| 指标 | 数值 |
| --- | ---: |
| steps | 88 |
| successfulSteps | 88 |
| failedSteps | 0 |
| median | 16.911s |
| p95 | 65.123s |
| max | 182.723s |

超过最大耗时阈值的 3 个 case：

| case | elapsed | 归因 |
| --- | ---: | --- |
| `303-dialogue-region-developed-city-opportunity` | 182.723s | 地域机会只读分析，模型整合阶段长尾后进入安全兜底 |
| `303-dialogue-extra-points-need-record` | 182.649s | 加分项政策/信息补充问题，首轮模型请求长尾后进入安全兜底 |
| `303-dialogue-region-lanzhou-yinchuan-backup` | 182.257s | 兰州/银川兜底分析，地域分析工具或模型等待长尾后进入安全兜底 |

其余 6 个延迟 warning 中，方案风险、高收费、保底不足等高价值分析内容正确；主要剩余问题是模型供应商长尾、地域/政策类重复工具或长耗时工具调用，以及前端 progress hint 需要更自然。

最新 open-quality 指标：

| 指标 | 数值 |
| --- | ---: |
| steps | 23 |
| successfulSteps | 23 |
| failedSteps | 0 |
| median | 17.350s |
| p95 | 28.323s |
| max | 33.794s |

### 3.2 后端权益 hotfix 回归

`origin/develop` 合并后，确认不引入 `volunteer-super-vip-only` 全局开关。

保留当前权益口径：

- `SUPER_VIP` 不受智能填报每日 2 次限制。
- 非 `SUPER_VIP` 创建 `prepareType.code=VOLUNTEER` 会话每天最多 2 次。
- `PREDICT` 模拟填报不新增日限。
- 缺失 `prepareType.code` 的创建请求由后端默认补 `VOLUNTEER`，避免智能填报期绕过日限。

已跑过受影响后端测试：

```bash
cd zhiyuan-server
mvn -Dtest=UserBizServiceTest,ChatSessionBizServiceTest test
```

结果：`16 tests, 0 failures, 0 errors`。

### 3.3 模块自身回归

本轮补充了 Agent 以外模块的自身回归：

| 模块 | 命令 | 结果 |
| --- | --- | --- |
| `zhiyuan-server` targeted | `mvn -Dtest=UserBizServiceTest,ChatSessionBizServiceTest test` | `16 tests, 0 failures, 0 errors` |
| `zhiyuan-server` full | `mvn test` | sandbox 内 `231 tests, 0 failures, 1 error, 3 skipped`；唯一错误为 `InitialPlanEvaluationP0ReportTest` 连接本地 MySQL 被 sandbox 拦截 |
| `zhiyuan-server` failing test rerun | `mvn -Dtest=InitialPlanEvaluationP0ReportTest test`（非 sandbox） | `1 test, 0 failures, 0 errors`，确认 full test 错误是环境连接限制 |
| `zhiyuan-rank` | `.venv/bin/python -m unittest discover -s tests -v` | `11 tests, OK`；当前 rank venv 未安装 pytest，使用 unittest 入口 |
| `zhiyuan-web` | `./node_modules/.bin/tsc --noEmit --pretty false` | 未通过，失败集中在既有 TS 债务：`src/pageComponents/session/ModalForm/index.tsx`、`src/pages/userCenter/index.tsx`、`src/service/index.ts`、`src/service/request/index.ts` |

结论：Agent/Server targeted/Rank 回归通过；Server full 的唯一失败可复现为 sandbox 环境问题；Web 仍需单独清理既有 type debt，当前 3.0.3 触达的消息/工作区文件不在这批 TS 报错范围内。

## 4. 3.0.2 -> 3.0.3 升级准备

### 4.1 升级范围

| 模块 | 是否升级 | 说明 |
| --- | --- | --- |
| `zhiyuan-agent` | 是 | Agent 对话、pending 协议、工具边界、回归框架 |
| `zhiyuan-server` | 是 | Planning state 显式偏好/约束、stale 标记、pending/工作区联动接口 |
| `zhiyuan-web` | 是 | pending 确认卡片、工作区刷新/视图保持、消息展示 |
| Rank 服务 | 否 | 本轮不改 Rank 服务；意向采纳后的推荐刷新仍调用既有后端/rank 能力 |
| 数据库结构 | 否 | 当前不需要 DDL；新增状态通过 extra-data / planning state JSON 承载 |

### 4.2 配置检查

上线前检查：

- 不配置 `gaotu.zhiyuan.volunteer-super-vip-only`，该全局开关已废弃。
- 保留 3.0.2 已验证的 `prepareType` 默认补齐和日限逻辑。
- Agent 模型配置以当前线上主模型为准；回复质量优先，不为了延迟切低质量模型；仓库只记录 `LLM_` 配置变量名和脱敏占位，真实 `LLM_API_KEY` 只放运行环境。
- 如果启用官方来源检索，需要确认 `BOCHA_API_KEY`、`BOCHA_BASE_URL`、`BOCHA_TIMEOUT_SECONDS` 已在运行环境配置；仓库只记录变量名和脱敏占位，未配置 key 时会降级为通用判断框架和官方核验提醒。
- Web 生产构建仍需确认 `/assistant-pc` basePath 和生产 rewrite 指向线上域名；本地功能验证必须使用 local-api 构建或本地 dev server，避免误请求线上接口。

### 4.3 生产升级执行入口

生产部署、类生产演练、资产 hash 记录、上线 smoke、观察项和回滚方案已收口到：

```text
docs/release-3.0.3-production-upgrade-plan.md
```

执行口径：

- Backend、Web、Agent 升级；Rank 不升级。
- 不执行新的数据库 migration。
- 构建正式 Web 镜像必须使用 `APP_ENV=prod`。
- 本地功能验收如需请求本地 Backend / Agent，使用单独 `prod-3.0.3-local-api` 验证镜像，不覆盖正式发布 tag。
- 生产切换顺序为 Backend -> Agent -> Web。
- 上线前必须补齐 Git commit、JAR sha256、Web/Agent 镜像 digest 和 release 包 hash。

当前已完成 `f7dd564177e16c793d55e8179b46e00a114145b2` 的构建资产记录：

- 后端 JAR：`sha256:822908fcd0876eb9ca83be21ade6040600716cfd26f9be4ee3c47f56d2bbe726`
- Web 镜像：image `sha256:ef5142e0b9b0d80f5ca037a5790c3f95b2ed063efc7fe1d21b529c62aa7a02af`；tar `sha256:fded71e883499cfe519383ed5db3071d29c2949e574696d63c3556682bef0808`
- Agent 镜像：image `sha256:0d038dc02e4f9bee2e3026851377a37f717cfac94859d67d76a8fbeee86a9e8f`；tar `sha256:129de22376ad80c4ad0c1df19a9574e0f1f83bf85298e73e19ab0569cfb53fa5`
- Release 包：`/tmp/zhiyuan-release-3.0.3-f7dd564.tar.gz`，`sha256:00591deca182da8b45bf203d4fef7ce3df3c27e596073fda263ff52f022a1607`

`prod-3.0.3` tag 已创建；本地类生产演练已完成，结果见 `docs/release-3.0.3-production-upgrade-plan.md` 的 `7.4 本地类生产演练记录`。压缩包内不记录自身 hash，避免自引用导致 hash 反复变化；生产传输校验以本节记录为准。

## 5. 遗留问题和后续优化

### 5.1 性能

- 弱收尾、保存思路等无工具场景仍可能出现 `30-40s` 主模型长尾。
- 转专业政策类 case 存在重复官方来源检索。
- 复杂开放分析仍会走多轮模型综合，open-quality p95 仍在 28s 左右。
- 后续优化方向：工具事实压缩、上下文裁剪、重复工具调用抑制、官方检索缓存、更自然的前端 progress hint。

### 5.2 回复质量

- 个别回复仍可能偏“是否需要整理确认卡片”，需要继续口语化。
- 学校/专业自定义招生大类与官方专业层级存在歧义，例如“工商管理” vs “工商管理类”，需要用户确认型消歧。
- 专业对比和职业分析需要继续保证学校层次、冲稳保、专业热度、家庭约束等关键分布覆盖。

### 5.3 状态和旧链路清理

- `planEditCache` 仍作为旧会话 adapter 存在，后续可在确认新协议稳定后进一步删除旧入口。
- `pending_plan_action`、`pending_intent_change` 等运行时兼容字段后续应减少模型可见性。
- 旧 `intentSelect` / `planEditSelect` 前端入口需要继续确认是否还有真实使用方；无使用方后统一迁到 `pendingConfirmation`。

### 5.4 产品和运营

- 意向采纳后推荐系数和专家优选推荐刷新需要继续做前端人工走查，确认用户能感知变化。
- 高收费、民办、中外合作这类敏感风险需保持“总量 + 典型例子 + 下一步”的表达，不用示例条数替代总量。
- 权益侧模拟填报每天 10 个会话的规则仍未在本版本实现，保留为后续 TODO。

## 6. 文档收口

当前文档口径：

| 文档 | 状态 | 用途 |
| --- | --- | --- |
| `release-3.0.3-summary-and-upgrade-plan.md` | 当前主入口 | 发布范围、回归、升级、遗留问题 |
| `release-3.0.3-production-upgrade-plan.md` | 当前生产部署计划 | 3.0.2 -> 3.0.3 生产升级步骤、资产记录、smoke、回滚 |
| `release-3.0.3-agent-intent-plan-mutation-confirmation-design.md` | 当前协议 | 意图、意向、方案更新和确认协议 |
| `release-3.0.3-agent-effect-performance-deep-dive.md` | 历史流水 + 最新回归明细 | 保留完整 deep-dive 和结果证据 |
| `release-3.0.3-agent-case-evaluation-framework.md` | 当前评估框架 | 质量评分和回归标准 |
| `release-3.0.3-agent-case-evaluation-report-template.md` | 当前报告模板 | case 级报告格式 |
| `release-3.0.3-agent-intent-plan-update-interaction-design.md` | 历史阶段设计 | 已被 mutation confirmation 设计收口 |
| `release-3.0.3-agent-response-quality-review.md` | 历史质量样例 | 早期回复质量对照，不代表当前运行时 |
| `release-3.0.3-agent-case-evaluation-first-pass.md` | 历史首次评估 | 早期试验结果，不作为当前结论 |

清理原则：

- 不删除带有测试证据和问题复盘价值的历史文档。
- 所有旧文档必须在顶部说明是否为历史记录，并指向当前主入口。
- 后续新增 3.0.3 结论优先写入本文；细节证据再追加到 deep-dive。
