# Release 3.1.0 Performance Stress Test Targets

本文整理当前系统在高并发和高用户量场景下需要重点压测的接口与潜在性能瓶颈。目标是先识别风险面，再针对性设计压测脚本、观测指标和容量水位。

## 1. 压测目标

- 验证生产 3.x 架构在高并发会话、工作区浏览、候选池筛选、Agent 对话下的承载能力。
- 找出 CPU、内存、数据库、外部接口、LLM、文件/大 JSON 序列化等瓶颈。
- 区分可水平扩容的问题和需要代码优化的问题。
- 建立上线前容量基线：QPS、P95/P99、错误率、资源水位、降级策略。

## 2. 重点瓶颈类型

### 2.1 外部高途数据拉取

创建会话和生成候选池依赖高途方案数据与招生计划数据。典型风险：

- 外部接口延迟不可控。
- 单次拉取数据量大。
- 同一用户/同一会话重复生成会放大外部调用压力。
- 高途接口失败重试会放大峰值流量。

### 2.2 大 JSON 状态读写

工作区状态、候选池、方案、审查状态等会以完整规划状态读写。典型风险：

- 单会话候选池可能达到数千条。
- `loadPlanningState` / `savePlanningState` 涉及大 JSON 反序列化和序列化。
- 工作区高频刷新会重复读取大状态。
- 状态写入如果是整块覆盖，方案操作并发时容易形成热点。

### 2.3 候选池内存过滤与排序

候选池查询、筛选项生成和专业组聚合均会在内存中对候选项做过滤、去重、排序、分组。典型风险：

- `candidate-pool/query` 每次都要按多个字段过滤与排序。
- `candidate-pool/filter-options` 需要扫描候选池并构造筛选树。
- 专业组模式还要按 `planSchoolDataId` 聚合，候选数量越大越明显。

### 2.4 Agent / LLM / WebSocket

Agent 对话依赖 LLM、工具调用、后端内部接口和消息持久化。典型风险：

- WebSocket 长连接并发数。
- 单轮对话可能串行触发多个内部接口。
- LLM 请求耗时长且不稳定。
- Bocha web search 和候选池查询等工具调用会叠加延迟。
- 消息落库和卡片状态更新在高并发下形成数据库压力。

### 2.5 导出与审查

导出、审查、修复建议会遍历方案和候选数据并生成 Excel 或复杂结果。典型风险：

- Excel 在内存中生成，容易造成瞬时内存上涨。
- 审查和修复建议涉及多规则、多轮候选扫描。
- 多用户同时导出或审查时 CPU 与内存压力明显。

## 3. P0 压测接口

### 3.1 外部初始化创建会话

接口：

- `POST /gaotu-assistant-bot/chat/{tenantId}/integration/session/initialize`
- `POST /gaotu-assistant-bot/chat/{tenantId}/integration/v1/session/initialize`

风险原因：

- 创建会话、写用户信息、拉取高途数据、生成候选池、生成初始方案、返回工作区状态可能集中在一次请求里。
- 请求体较大，返回体也可能较大。
- 外部系统入口，峰值不可完全由本系统控制。

压测场景：

- 只创建会话，不生成候选池。
- 创建会话并生成候选池。
- 创建会话、生成候选池、生成初始方案、返回工作区状态。
- 相同 `externalRequestId` 幂等请求并发。
- 高途接口慢响应/失败下的超时和错误率。

核心指标：

- P95/P99 响应时间。
- 外部高途调用耗时与失败率。
- 数据库写入耗时。
- 单请求返回体大小。
- JVM 堆内存与 GC。

### 3.2 前端创建会话

接口：

- `POST /gaotu-assistant-bot/chat/{tenantId}/session/create`

风险原因：

- 与外部初始化类似，是用户高峰期入口。
- 可能触发高途数据拉取和新工作区初始化。
- 如果创建失败会影响主流程转化。

压测场景：

- 普通新建会话并进入详情页。
- 多用户并发新建。
- 同用户快速重复点击创建。
- 不同省份/批次/专业模式混合。

### 3.3 Agent 对话 WebSocket

接口：

- `WS /gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`
- `WS /ws/chat`

风险原因：

- 长连接并发。
- 每条消息可能触发 LLM、后端查询、候选池查询、工作区操作和消息持久化。
- LLM 和工具调用耗时不可控。

压测场景：

- 仅普通问答。
- 候选池查询类问题，例如“有没有 211 计算机”。
- 方案生成、排序、审查、修复建议。
- 意向确认卡片生成与点击应用。
- 长连接空闲保持和断开重连。

核心指标：

- 并发连接数。
- 首包延迟、完整回复耗时。
- LLM 调用耗时和失败率。
- 工具调用次数和耗时。
- 消息落库耗时。

## 4. P1 压测接口

### 4.1 获取工作区状态

接口：

- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/workspace-state?chatSessionId={id}`
- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/state?chatSessionId={id}`

风险原因：

- 页面详情页核心加载接口。
- 读取规划状态并裁剪/组装工作区状态。
- 用户进入详情页、刷新页面、Agent 操作后都会触发。

压测场景：

- 同一热门会话多次刷新。
- 多会话并发打开详情页。
- 大候选池会话和普通会话混合。

建议关注：

- `state` 是完整状态，返回体更大，应限制前端直接高频调用。
- `workspace-state` 是轻量状态，应作为详情页主接口基线。

### 4.2 查询候选池

接口：

- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/query?chatSessionId={id}`

风险原因：

- 前端下拉加载和筛选会频繁调用。
- 内存中过滤、排序、分页。
- 专业组模式需要统计 entry/unit 数。

压测场景：

- 无筛选分页加载。
- 院校省份/城市/院校名筛选。
- 院校标签筛选，如 `211`、`双一流`、`公办`。
- 专业大类/专业名称筛选。
- 多条件组合筛选。
- 高并发滚动加载下一页。

### 4.3 获取候选池筛选项

接口：

- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/filter-options?chatSessionId={id}`

风险原因：

- 需要扫描候选池构造省市树、专业树、院校标签分组。
- 如果详情页每次打开都请求，峰值下会明显占 CPU。

压测场景：

- 打开详情页后的首次加载。
- 大候选池会话多用户并发。
- recommendation overlay stale 时触发刷新叠加。

### 4.4 生成候选池

接口：

- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/candidate-pool/generate?chatSessionId={id}`

风险原因：

- 从高途推荐数据转候选项。
- 候选池较大，转换、排序、落盘成本高。
- 可能与创建会话或意向变化后刷新联动。

压测场景：

- 新会话批量生成。
- 已存在候选池强制重生成。
- 意向变化后生成。
- 高途接口慢或返回大数据。

### 4.5 生成初始推荐/方案

接口：

- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/initial-recommendation/generate?chatSessionId={id}`

风险原因：

- 需要从候选池中按冲稳保和专业组规则选取初始方案。
- 专业组模式涉及组内专业选择与安全垫判断。

压测场景：

- 专业模式。
- 专业组模式。
- 候选池 1000/3000/6000+ 分档。

### 4.6 排序方案与审查

接口：

- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/sort?chatSessionId={id}`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/review/run?chatSessionId={id}`
- `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/fix-proposals/generate?chatSessionId={id}`

风险原因：

- 多规则扫描方案和候选池。
- 修复建议会查找替换候选。
- Agent 常触发这些接口。

压测场景：

- 普通 40/45/96 个志愿方案。
- 专业组模式组内 4-6 专业。
- 候选池大、方案不完整、存在多个风险项。

### 4.7 工作区写操作

接口：

- `POST /session/working-plan/select`
- `DELETE /session/working-plan/items`
- `POST /session/ordered-plan/items/move`
- `POST /session/ordered-plan/units/move`
- `DELETE /session/ordered-plan/units`

风险原因：

- 读完整状态、修改、重算 summary、写回完整状态。
- 同一会话多操作并发时存在版本冲突和覆盖风险。

压测场景：

- 单用户连续快速操作。
- 同一会话双端同时操作。
- Agent 操作和前端手动操作并发。

## 5. P2 压测接口

### 5.1 导出

接口：

- `POST /gaotu-assistant-bot/chat/{tenantId}/volunteer/export?chatSessionId={id}`
- `GET /gaotu-assistant-bot/inner/planning/{tenantId}/session/ordered-plan/export?chatSessionId={id}`

风险原因：

- 内存中生成 Excel。
- 大方案、多专业组时文件生成耗 CPU 与内存。

压测场景：

- 10/50/100 并发导出。
- 专业模式与专业组模式分别测。
- 大候选池、大方案会话导出。

### 5.2 会话列表与消息分页

接口：

- `POST /gaotu-assistant-bot/chat/{tenantId}/session/page`
- `POST /gaotu-assistant-bot/chat/{tenantId}/message/page`

风险原因：

- 高频页面接口。
- 依赖数据库分页和索引。
- 消息量增加后可能成为慢查询。

压测场景：

- 单用户大量会话。
- 多用户并发打开会话列表。
- 单会话消息 100/500/1000 条分页。

### 5.3 目录与基础数据接口

接口：

- `/gaotu-assistant-bot/inner/catalog/**`
- `/province-city` 等基础数据接口

风险原因：

- 前端初始化和 Agent 代码标准化会调用。
- 多为缓存/内存读，单次风险低，但高并发下应确认缓存命中。

压测场景：

- 页面首次加载并发。
- Agent 抽取归一化并发。

## 6. 建议压测组合

### 6.1 页面浏览基线

模拟用户打开系统：

1. 会话列表。
2. 会话详情。
3. 工作区状态。
4. 候选池第一页。
5. 筛选项。
6. 消息分页。

用于确定纯浏览场景最大并发。

### 6.2 新建会话峰值

模拟高峰期用户从高途进入：

1. 外部初始化或前端创建会话。
2. 生成候选池。
3. 生成初始方案。
4. 打开详情页。

用于确定创建链路吞吐和外部高途接口压力。

### 6.3 Agent 对话峰值

模拟用户集中咨询：

1. WebSocket 建连。
2. 普通问答。
3. 候选查询。
4. 方案审查。
5. 方案修改确认。

用于确定 Agent、LLM、后端内部接口整体容量。

### 6.4 工作区操作峰值

模拟深度使用：

1. 候选池筛选和翻页。
2. 加入方案。
3. 移动排序。
4. 审查。
5. 导出。

用于确定 CPU、内存和状态写入压力。

## 7. 观测指标

服务指标：

- Java 后端 QPS、P50/P95/P99、错误率。
- Agent WebSocket 并发连接、首包耗时、完整响应耗时。
- Nginx 入口请求数、4xx/5xx、upstream time。
- Docker CPU、内存、网络、重启次数。

JVM 指标：

- Heap 使用率。
- GC 次数和停顿时间。
- 线程数。
- 大对象分配和 Full GC。

数据库指标：

- 慢查询。
- 连接池使用率。
- `chat_session_extra_data` 大 JSON 读写耗时。
- `chat_message` 分页和写入耗时。

外部依赖：

- 高途接口耗时和失败率。
- Rank 服务耗时。
- LLM provider 耗时和失败率。
- Bocha web search 耗时和失败率。

业务指标：

- 创建会话成功率。
- 候选池生成成功率。
- Agent 回复成功率。
- 工作区加载成功率。
- 导出成功率。

## 8. 初步优化关注点

压测前建议先确认：

- `workspace-state` 是否已替代前端高频 `state` 完整状态读取。
- 候选池查询是否避免每次返回过多条目。
- `filter-options` 是否可按状态版本缓存。
- 同一会话的生成类接口是否有互斥和幂等保护。
- Agent 是否有 LLM 超时、工具超时和并发限流。
- 导出是否需要并发限制。
- 创建会话是否需要对外部初始化加限流和幂等缓存。

## 9. 推荐优先级

P0 必测：

- 外部初始化创建会话。
- 前端创建会话。
- Agent WebSocket 对话。
- 工作区状态加载。
- 候选池查询。

P1 必测：

- 候选池生成。
- 候选筛选项生成。
- 初始方案生成。
- 排序、审查、修复建议。
- 工作区写操作。

P2 视资源补测：

- 导出。
- 会话列表和消息分页。
- 目录与基础数据接口。

## 10. 结论

当前系统最可能的性能瓶颈不是单个普通查询接口，而是“创建/初始化 + 高途数据拉取 + 大 JSON 状态读写 + 候选池内存计算 + Agent/LLM 工具链”叠加后的链路压力。3.1.0 压测应先覆盖 P0 主链路，再对候选池、审查、导出等重计算接口做专项压测。
