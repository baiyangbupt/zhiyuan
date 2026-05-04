# 初始方案评估 P1 执行方案

## 1. 目标

`P1` 聚焦高分样本，目的不是继续验证“能不能出结果”，而是专门看：

- 高分段是否还能维持合理的冲稳保结构
- `major / majorGroup` 两种模式下，高分供给充足时是否会出现过度保守
- 前置审查规则后，是否仍能保住高质量候选，而不是被规则修成“只剩安全”

首批目标样本沿用当前样本池中的 `P1`：

- `HN-07A`
- `HN-07B`
- `SD-05A`
- `SD-05B`
- `GD-06A`
- `GD-06B`
- `HE-06A`
- `HE-06B`

## 2. 当前可执行现状

目前仓内已跑通的评测方式只有两类：

### 2.1 真实会话只读回放

优点：

- 直接复用真实 `planningState`
- 能看到真实候选池、真实画像和真实旧链路结果

缺点：

- 受本地样本限制明显
- 当前高分段真实样本不足，无法覆盖 `P1`

### 2.2 单测内 mock `recommendVolunteerList(...)`

优点：

- 可控，适合构造极端高分样本
- 能直接制造“供给充足 / 供给偏斜 / 保区稀缺”等特定结构

缺点：

- 不是 live 数据，更多是算法机制测试
- 若夹具构造得太人工，容易偏离真实省份分布

## 3. 结论：P1 先采用“双阶段执行”

### 阶段 A：先补 mock 型高分评测

先不强求 live synthetic 样本直接打通，而是优先补一组可复用的 mock 夹具测试，目的：

- 把高分段最关键的结构性问题先验证掉
- 减少对临时真实数据和创建会话链路的依赖

优先覆盖：

1. `majorGroup` 高分稳妥样本
2. `majorGroup` 高分激进样本
3. `major` 高分理工样本
4. `major` 高分文商样本

### 阶段 B：再补 live synthetic 样本链路

当 mock 结果稳定后，再决定是否补一个“由 executable yaml 直接生成评分画像 + 候选池”的集成测试入口。

这一阶段的目标不再是校验规则本身，而是校验：

- synthetic profile 到推荐链路的映射是否正确
- region / major / strategy 等画像字段是否被 live rank 链路正确消费

## 4. P1 首轮建议执行顺序

### 4.1 第一优先级

- `HN-07A`
- `SD-05A`
- `GD-06A`
- `HE-06A`

原因：

- 先看稳妥型高分样本
- 先覆盖男女之外更稳定的高分主干
- 先覆盖 `major / majorGroup` 两种模式

### 4.2 第二优先级

- `HN-07B`
- `SD-05B`
- `GD-06B`
- `HE-06B`

原因：

- 激进策略和非主流画像更容易暴露结构偏移
- 应在第一轮稳态样本验证后再补

## 5. P1 重点观察指标

高分段不再只看“有没有保区”，还要重点看以下 6 项。

### 5.1 tier 目标落地

- `requiredTierCounts`
- `initialTierCounts`
- `orderedTierCounts`

关注：

- 是否仍能贴近目标数
- 是否因修规则导致过度收缩冲区

### 5.2 高质量候选保留度

看 `v2.examples` 与老版代表项对比，关注：

- 高分头部院校是否仍能进入冲区
- 是否大量退化成安全但质量偏低的候选

### 5.3 未解决规则

重点观察：

- `probability_gap`
- `probability_inversion`
- `ratio_distribution`
- `unit_major_count_validation`
- `group_inner_safety_guard`

高分段若仍频繁 unresolved，说明规则组装策略还不够稳。

### 5.4 候选池供给充足度

必须同时打印：

- `candidatePool.summary.tierCounts`

否则无法区分：

- 候选池本身没有
- 还是初始方案没组出来

### 5.5 画像对齐度

重点看：

- 强理工是否真的更偏工科
- 高分女生医学/电子类意向是否被体现
- 发达地区偏好是否仍被保留

### 5.6 模式差异

- `majorGroup` 看组层目标是否稳定、组内安全垫是否存在
- `major` 看高分供给下是否还能维持九宫格与梯度

## 6. 当前缺口

### 6.1 还没有 live synthetic 可执行入口

目前 YAML 样本只是定义，不是可直接运行的测试输入。

缺的能力包括：

- 从 `sample_id` 生成 `CreateSessionReq`
- 从 `sample_id` 生成 `UserProfileData`
- 用 synthetic profile 驱动 `recommendVolunteerList(...)` 或其等价链路

### 6.2 还没有统一的高分候选夹具库

如果直接在单测里一条条手写候选，会很快失控。

需要后续补一层可复用夹具：

- 高分 `major` 候选集夹具
- 高分 `majorGroup` 候选集夹具
- 可控制“保区充足 / 不足 / 为零”的变体

## 7. 建议的下一步落地

1. 先新增 `P1` mock 型结构评测测试，最少覆盖 `major` 和 `majorGroup` 各 2 个高分样本。
2. 测试输出延续 `P0` 的只读报告格式，补 `candidatePoolTierCounts`。
3. 跑完第一轮后，再决定是否继续建设 live synthetic 样本入口。

## 8. 当前已落地的首轮测试

当前已在 `PlanningStateServiceTest` 中补入 4 个高分 mock 结构测试：

- `shouldKeepTierTargetsForHighScoreMajorModeWhenSupplyIsSufficient`
- `shouldKeepSprintQuotaForHighScoreMajorModeUnderAggressiveTargets`
- `shouldKeepTierTargetsForHighScoreMajorGroupModeWhenSupplyIsSufficient`
- `shouldKeepSprintQuotaForHighScoreMajorGroupModeUnderAggressiveTargets`

这四个测试当前覆盖了：

- `major / majorGroup` 两种模式
- 高分供给充足场景
- 稳态与激进两类结构目标

当前验证结论：

- `majorGroup` 在高分供给充足时可稳定维持目标组层数量
- `major` 在高分充足场景下，`initialRecommendation` 可贴近目标；进入 `orderedPlan` 后存在极轻微的一条冲区收缩，因此当前断言按“不明显塌冲/塌保”约束，而不是强绑完全逐条等于目标
- 高分 mock 回归现已补入“推荐系数高分优先命中”断言：`major` 模式按 tier 校验已入选条目落在 `finalScore` 头部区间；`majorGroup` 模式按组代表项校验已入选专业组来自各 tier 头部组集合，避免后续改动把初始化方案退化成中低分候选混入
- 高分候选视图现已补入“负向地域约束”回归：`shouldExcludeForbiddenProvinceInHighScoreCandidateView` 使用 `30/30/30` 的高分 mock 候选，验证在排除 `北京` 后，候选视图会完整剔除冲区禁入省份，且筛选后 `tierCounts` 会稳定收口为 `冲=0 / 稳=30 / 保=30`
- 高分 `major` 文商画像现已补入“头部主导”回归：`shouldPreferHighScoreBusinessAndLawCandidatesWhenSupplyIsSufficient` 用 `法学/财经` 高推荐分候选对照次级理工候选，验证初始方案在各 tier 内仍以目标画像头部集合为主；当前口径明确收口为“主导占比”，不强绑到 100% 纯净，因为现有结构修复阶段仍可能混入少量次级候选

后续若继续往下做，优先补两类样本：

- live synthetic 高分画像链路
- 高分画像下的旧版/新版对照输出
