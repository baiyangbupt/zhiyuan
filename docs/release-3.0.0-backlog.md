# Release 3.0.0 Backlog

本文档汇总当前 `3.0.0` 上线、迁移、算法和运维层面的遗留问题与待完善点。它不是新的设计方案，而是 release 收口和后续迭代的 backlog。

当前处理原则：

- P0 项作为 `3.0.0` 最终生产可用包的准入条件。
- P1/P2 项不阻塞本期发布，统一延后到后续版本修复或优化。
- 已知算法展示问题需要在产品和研发侧保留风险认知，但不继续扩大本期发布范围。

相关文档：

- `docs/production-upgrade-implementation-steps.md`
- `docs/legacy-to-v2-upgrade-migration-plan.md`
- `docs/legacy-to-v2-upgrade-migration-status.md`
- `docs/system-health-and-ops-design.md`
- `zhiyuan-server/docs/plan-generation-engine-design.md`

## 1. 当前版本锁定状态

当前代码版本号已经统一为 `3.0.0`：

| 模块 | 版本位置 | 当前值 |
| --- | --- | --- |
| backend | `zhiyuan-server/pom.xml` | `3.0.0` |
| frontend | `zhiyuan-web/package.json` | `3.0.0` |
| agent | `zhiyuan-agent/pyproject.toml` | `3.0.0` |

Release 锁定原则：

1. 发布包必须基于固定 commit，不从本地脏工作区直接打包。
2. 后端 JAR、前端镜像、Agent 镜像、备份目录和部署记录必须使用同一个 release 标识。
3. `v3.0.0` tag 应在构建验证、真实样本验证、灰度前检查和生产关键链路确认后创建。
4. 生产环境不做编译构建，只接收已经验证过的 JAR、Docker 镜像或镜像 tar。
5. 当前本地允许存在 `.env`、`tsconfig.tsbuildinfo`、临时样本 JSON 等调试文件，但这些内容不能进入 release 包。

当前线上 3.0.0 记录以 `docs/production-upgrade-implementation-steps.md` 为准：

- 后端使用 `zhiyuan-server-3.0.0-prod.service`，当前生产记录的修复版 commit 为 `2221541`。
- 前端使用 `zhiyuan-web-3.0.0-prod`，当前线上镜像记录为 `zhiyuan-web:3.0.0-amd64-wsfix`。
- Agent 使用 `zhiyuan-agent-3.0.0-prod`，镜像记录为 `zhiyuan-agent:3.0.0-amd64`。
- Rank 暂不随本次迁移升级，继续使用既有容器。

## 2. P0：发布锁定前必须收口

### 2.1 固定最终 release commit

现状：

- 3.0.0 版本号已统一。
- 生产实施文档已经记录固定 commit、构建边界、产物路径和回滚命令。
- 近期生产热修包含新建会话不触发 legacy 懒导入、前端 WebSocket 地址修复等内容。

待完成：

- 确认 `develop` 已包含所有生产热修和文档补充。
- 执行 `git status --short --branch`，确保 release tag 前没有未确认的代码变更。
- 用最终 commit 更新生产实施文档中的 release commit 记录。
- 创建 `v3.0.0` tag 前再次确认本地调试文件未进入提交或 release 包。

验收：

- `git rev-parse --short HEAD` 与构建产物、部署记录、tag 记录一致。
- release 包可以追溯到唯一 commit。

### 2.2 前端生产包路径和 WebSocket 地址复核

现状：

- 正式生产入口是 `/assistant-pc`。
- 前端生产包必须使用 `APP_ENV=production` 或等价非 `dev` 构建，使 `basePath=/assistant-pc`。
- `NEXT_PUBLIC_AGENT_WS_BASE` 是 Next.js 构建期变量，不能只在容器运行时补充。

待完成：

- 每次重新构建前端镜像前，确认 `.env.prod` 包含 `NEXT_PUBLIC_AGENT_WS_BASE=wss://www.gaotuzhiyuan.com`。
- 构建后检查产物中不存在 `ws://localhost:8000`。
- 验证 `/assistant-pc/sessionDetailV2`、`/assistant-pc/sessionDetailLegacy` 和 `/assistant-pc/session` 均可访问。

验收：

- 浏览器侧发送消息后，Agent 日志能看到真实 `session_id` 进入处理。
- 公网 WebSocket 路径返回 `101 Switching Protocols`。

### 2.3 新建会话主链路回归

现状：

- 生产曾出现新建会话被 legacy 懒迁移逻辑污染的问题，远端已修复。
- 当前新建会话应走 V2 初始化和初始方案生成，不应把候选池全量塞入排序区。

待完成：

- 覆盖 `major` 和 `majorGroup` 两种模式的新建会话回归。
- 检查 `orderedPlanState.generationMode` 应为 `initial_auto`，不是 `legacy_plan_import / legacy_submitted`。
- 检查排序区数量与目标数量一致：专业模式看专业条目数，专业组模式看专业组 unit 数。

验收：

- 新建会话不会读取老方案 JSON。
- 候选池、草稿、排序区边界清晰，不再出现几百到几千条原始候选进入排序区。

### 2.4 真实老会话迁移抽样

现状：

- 老方案文件选择口径已修正：`_final.json` 优先，`_temp.json` 次之，无后缀原始文件只作为兜底。
- 已补充专业+大学和院校专业组两种模式的样本测试。

待完成：

- 继续用生产样本目录做小范围真实会话对账。
- 每个抽样会话尽量包含无后缀、`_temp.json`、`_final.json` 三件套，用于验证文件选择逻辑。
- 已提交历史方案应从 `_final.json` 进入排序区并锁定；提交前推荐方案应从 `_temp.json` 进入排序区；原始全量候选不应被当作优选。

验收：

- 迁移日志能明确记录 source、item/unit 数量和 generationMode。
- 单会话回滚脚本 dry-run 可用，必要时能删除对应 `planningState` 重新触发迁移。

## 3. P1：算法和产品展示遗留问题

状态：延后到 `3.0.x` 或后续规划版本处理，不阻塞 `3.0.0` 最终生产包。

### 3.1 `probability_gap` 不是硬约束

现状：

- 当前初始方案生成会尝试修复相邻录取率断层，但属于 best-effort。
- 判断阈值为相邻 `admissionRatio` 差值 `> 8`。
- 修复动作需要同时改善整体 gap 指标，且不能恶化冲稳保配额偏差。
- 生产会话 `2076` 已出现 `gapFixCount=3` 后仍剩余 `unresolvedGapCount=2` 的情况。

问题：

- 产品和用户容易理解为“系统保证相邻录取率差值不超过 8”，但当前实现无法保证。
- 当候选池缺少中间梯度候选，或修复会破坏冲稳保配额时，系统会返回仍存在断层的方案。

待完善：

- 明确产品口径：`probability_gap` 是提醒项、软约束，还是生成阶段硬约束。
- 如果要升级为硬约束，需要重新设计生成策略：扩大替换窗口、允许跨 tier 小幅借位、或无法满足时返回需要人工确认的状态。
- 增加 `2076` 类似的 `majorGroup` 回归样本，覆盖“已修复但仍 unresolved”的情况。

### 3.2 `gradientOk` 与 review 结论不一致

现状：

- `orderedPlanState.summary.gradientOk` 当前更接近顺序/倒挂检查。
- `reviewState.checks.probability_gap` 才能表达相邻录取率断层。

问题：

- 可能出现 `gradientOk=true`，但 `reviewState.checks.probability_gap.passed=false`。
- 如果前端只展示 summary，会让用户误以为梯度完全通过。

待完善：

- 方案一：把 `probability_gap` 纳入 `gradientOk`。
- 方案二：把 `gradientOk` 改名为 `sequenceOk`，另增 `gapOk` 或直接展示 review 结果。
- 前端方案页优先读取并展示 `reviewState.checks.probability_gap`。

### 3.3 `majorGroup` 断层详情展示不足

现状：

- `majorGroup` 模式下 review 详情偏向展示首个断层样例。
- summary 里有剩余断层数量，但用户不一定能看到。

待完善：

- review 结果中补充断层列表或至少展示断层数量。
- 前端用用户能理解的语言展示：例如“有 2 处相邻专业组录取率跨度较大，建议重点确认这几个位置”。

## 4. P1：运维和部署完善

状态：发布必须保留当前已有健康检查和回滚命令；脚本化、一键化和观测面板延后完善。

### 4.1 健康检查脚本纳入发布流程

现状：

- 已新增 `ops/healthcheck.sh` 和 `ops/migration-status.sh`。
- 生产实施文档已记录健康检查、迁移日志观察和回滚命令。

待完善：

- 将健康检查结果作为发布前和发布后固定记录项。
- 在部署记录中保存每次 release 的健康检查输出摘要。
- 补充失败时的处理分支：后端失败、前端失败、Agent WebSocket 失败、迁移异常分别对应不同回滚动作。

### 4.2 混合部署形态继续收口

现状：

- backend 由 systemd 托管。
- web / agent / rank 使用 Docker 容器。
- 短期不要求为了 V2 迁移改成全容器或 Kubernetes。

待完善：

- 后续可以考虑把 backend 也容器化，减少 systemd + Docker 混合部署的认知成本。
- 前端根路径部署和 `/assistant-pc` 部署需要拆成明确环境，不再依赖 `APP_ENV=dev` 规避 `basePath`。
- 镜像仓库或离线 tar 包流程需要固定，避免生产环境临时构建。

### 4.3 敏感配置管理

现状：

- `LLM_API_KEY` 等敏感信息不写入仓库文档。
- Agent 的大模型配置通过容器环境变量传入。

待完善：

- 生产 `.env`、systemd env 文件、Docker Compose override 文件需要统一纳入服务器侧备份和权限管理。
- 文档中只记录配置项名称、用途和示例占位值，不记录真实 key。
- 发布前检查提交中不包含真实 `API_KEY / token / password`。

## 5. P2：后续能力建设

状态：不进入 `3.0.0` 发布范围。

### 5.1 初始方案 benchmark 常态化

待完善：

- 将大模型效果/性能 benchmark 与端到端场景样本固定下来。
- 记录硅基流动、百家平台、Kimi 官方等模型在真实对话和规划场景下的响应质量、延迟和失败率。
- benchmark 不应只看首 token 或总耗时，也要覆盖工具调用、结构化 planning 输出和用户可读性。

### 5.2 老版本迁移观测面板

待完善：

- 汇总 legacy 懒迁移成功/失败/跳过数量。
- 按 source 类型统计 `_final / _temp / original` 使用比例。
- 记录异常会话 ID、失败原因和是否已回滚。

### 5.3 移动端体验继续验证

待完善：

- 继续按老版本 mobile 分支的关键交互验证新版移动端。
- 重点检查会话列表悬浮入口、方案页、候选列表、快捷入口隐藏策略和标题栏错位问题。
- 方案页移动端已隐藏顶部统计概览，后续需要观察是否影响用户理解方案总量和冲稳保分布。

## 6. Release 3.0.0 最小收口清单

创建 `v3.0.0` tag 前，建议至少完成 P0 项；P1/P2 项已确认不阻塞本期发布：

1. `develop` 包含所有生产热修、文档和 changelog。
2. 本地工作区无待提交的 release 相关改动。
3. 后端单测和关键 planning 回归通过。
4. 前端生产包确认 `basePath=/assistant-pc`，且不包含 `ws://localhost:8000`。
5. Agent 健康接口和兼容 WebSocket 验证通过。
6. 新建会话 `major / majorGroup` 两种模式验证通过。
7. 老会话懒迁移样本验证通过，至少覆盖 `_final / _temp / original` 文件选择。
8. 生产回滚命令已验证或至少 dry-run 确认路径存在。
9. 生产部署记录更新最终 commit、产物 tag、sha256 和回滚点。
10. tag 创建后，所有模块产物使用同一个 release 标识。
