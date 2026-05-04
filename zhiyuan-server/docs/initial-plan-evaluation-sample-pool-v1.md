# 初始方案评估样本池 V1

## 1. 文档目的

本文档基于 [initial-plan-evaluation-matrix.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/initial-plan-evaluation-matrix.md) 的 8 维评估框架，给出第一批可执行样本池。

目标：

- 明确第一批建议测试哪些样本格子
- 标记哪些样本可直接复用本地真实会话
- 标记哪些样本需要人工补样

当前样本池只用于“初始方案生成 + 老版优选对照”。

## 2. 当前真实会话覆盖摘要

本地当前可直接复用的真实会话主要集中在以下三省：

- 河南
- 山东
- 安徽

现状问题：

- 省份覆盖不足
- 高分段样本明显不足
- 女生样本主要集中在山东
- `majorGroup` 真实样本主要集中在河南
- 选科组合不够丰富

因此第一批样本池采用：

- 真实样本优先占位
- 缺口格子由人工补样填充

## 3. 第一批样本池范围

第一批先覆盖 4 个省：

- 河南
- 山东
- 广东
- 河北

每省 8 个基础样本 x 2 个画像变体，共：

- `4 x 16 = 64`

## 4. 字段说明

每个样本统一记录以下字段：

- `sampleId`
- `sourceType`
  - `real_session`
  - `synthetic_profile`
- `sessionId`
- `province`
- `volunteerModel`
- `scoreBand`
- `subjectCombination`
- `gender`
- `strategyType`
- `majorIntentType`
- `regionIntentType`
- `coverageGoal`

## 5. 样本池

### 5.1 河南

河南优先承接：

- `majorGroup`
- 中低分到中高分
- 男生理工意向

| sampleId | sourceType | sessionId | province | volunteerModel | scoreBand | subjectCombination | gender | strategyType | majorIntentType | regionIntentType | coverageGoal |
|---|---|---:|---|---|---|---|---|---|---|---|---|
| HN-01A | real_session | 14 | 河南 | majorGroup | L2 | 物理/化学/生物 | 男 | traditional | 强理工 | 发达地区偏好 | 低分保守基线 |
| HN-01B | synthetic_profile | - | 河南 | majorGroup | L2 | 物理/化学/生物 | 女 | traditional | 泛专业 | 本省周边偏好 | 低分性别对照 |
| HN-02A | real_session | 11 | 河南 | majorGroup | M1 | 物理/化学/生物 | 男 | traditional | 强理工 | 华南偏好 | 中低分保守 |
| HN-02B | synthetic_profile | - | 河南 | majorGroup | M1 | 物理/化学/生物 | 女 | cautious | 泛专业 | 排除北京 | 中低分负向地域 |
| HN-03A | real_session | 15 | 河南 | majorGroup | M2 | 物理/化学/生物 | 男 | cautious | 理工+泛财经 | 华东偏好 | 中高分稳妥 |
| HN-03B | synthetic_profile | - | 河南 | majorGroup | M2 | 物理/化学/政治 | 女 | aggressive | 强理工 | 发达地区偏好 | 中高分激进女样本 |
| HN-04A | real_session | 16 | 河南 | majorGroup | M1 | 物理/化学/生物 | 男 | traditional | 强理工 | 发达地区偏好 | 当前核心回归样本 |
| HN-04B | synthetic_profile | - | 河南 | majorGroup | M1 | 物理/化学/生物 | 女 | cautious | 强文社科 | 本省优先 | 专业意向反差样本 |
| HN-05A | synthetic_profile | - | 河南 | majorGroup | H1 | 物理/化学/生物 | 男 | traditional | 强电气/计算机 | 华东偏好 | 高分保守 |
| HN-05B | synthetic_profile | - | 河南 | majorGroup | H1 | 物理/化学/政治 | 女 | cautious | 泛专业 | 华南偏好 | 高分女生稳妥 |
| HN-06A | synthetic_profile | - | 河南 | majorGroup | H1 | 物理/化学/生物 | 男 | aggressive | 强工科 | 发达地区偏好 | 高分激进 |
| HN-06B | synthetic_profile | - | 河南 | majorGroup | H1 | 物理/化学/生物 | 女 | aggressive | 强理工 | 排除北京/天津 | 高分负向地域 |
| HN-07A | synthetic_profile | - | 河南 | majorGroup | H2 | 物理/化学/生物 | 男 | cautious | 强工科 | 强地域偏好 | 头部段稳妥 |
| HN-07B | synthetic_profile | - | 河南 | majorGroup | H2 | 物理/化学/生物 | 女 | aggressive | 强理工 | 强地域偏好 | 头部段激进 |
| HN-08A | synthetic_profile | - | 河南 | majorGroup | L1 | 物理/化学/生物 | 男 | traditional | 泛专业 | 本省优先 | 贴线保底 |
| HN-08B | synthetic_profile | - | 河南 | majorGroup | L1 | 物理/化学/生物 | 女 | cautious | 泛专业 | 本省优先 | 贴线女生保底 |

### 5.2 山东

山东优先承接：

- `major`
- 女生样本
- 低分和中高分对照

| sampleId | sourceType | sessionId | province | volunteerModel | scoreBand | subjectCombination | gender | strategyType | majorIntentType | regionIntentType | coverageGoal |
|---|---|---:|---|---|---|---|---|---|---|---|---|
| SD-01A | real_session | 17 | 山东 | major | L1 | 新高考综合偏文商 | 女 | aggressive | 财经商科 | 发达地区偏好 | 当前核心回归样本 |
| SD-01B | synthetic_profile | - | 山东 | major | L1 | 新高考综合偏理工 | 男 | traditional | 强理工 | 本省优先 | 贴线男样本 |
| SD-02A | real_session | 7 | 山东 | major | M1 | 新高考综合偏文商 | 女 | traditional | 财经商科 | 华东偏好 | 中低分保守 |
| SD-02B | synthetic_profile | - | 山东 | major | M1 | 新高考综合偏理工 | 男 | cautious | 强理工 | 发达地区偏好 | 中低分男样本 |
| SD-03A | synthetic_profile | - | 山东 | major | M2 | 新高考综合偏理工 | 女 | cautious | 强理工 | 本省周边 | 中高分稳妥 |
| SD-03B | synthetic_profile | - | 山东 | major | M2 | 新高考综合偏文商 | 男 | aggressive | 泛专业 | 华东偏好 | 中高分激进 |
| SD-04A | synthetic_profile | - | 山东 | major | H1 | 新高考综合偏理工 | 女 | traditional | 强理工 | 强地域偏好 | 高分保守 |
| SD-04B | synthetic_profile | - | 山东 | major | H1 | 新高考综合偏理工 | 男 | aggressive | 强工科 | 发达地区偏好 | 高分激进 |
| SD-05A | synthetic_profile | - | 山东 | major | H2 | 新高考综合偏理工 | 女 | cautious | 强理工 | 发达地区偏好 | 头部段女生 |
| SD-05B | synthetic_profile | - | 山东 | major | H2 | 新高考综合偏文商 | 男 | cautious | 强财经 | 华东偏好 | 头部段文商 |
| SD-06A | synthetic_profile | - | 山东 | major | L2 | 新高考综合偏理工 | 女 | traditional | 泛专业 | 本省优先 | 低分保守 |
| SD-06B | synthetic_profile | - | 山东 | major | L2 | 新高考综合偏文商 | 男 | cautious | 泛专业 | 排除北京 | 低分负向地域 |
| SD-07A | synthetic_profile | - | 山东 | major | M1 | 新高考综合偏理工 | 女 | aggressive | 强理工 | 发达地区偏好 | 中低分激进 |
| SD-07B | synthetic_profile | - | 山东 | major | M1 | 新高考综合偏理工 | 男 | traditional | 强理工 | 本省优先 | 中低分本省稳态 |
| SD-08A | synthetic_profile | - | 山东 | major | H1 | 新高考综合偏理工 | 女 | aggressive | 强理工 | 排除一线城市 | 高分负向地域 |
| SD-08B | synthetic_profile | - | 山东 | major | H1 | 新高考综合偏文商 | 男 | traditional | 强财经 | 华东偏好 | 高分男商科 |

### 5.3 广东

广东当前本地无真实会话，首轮全部采用人工补样。

广东优先承接：

- `major`
- 高分段
- 发达地区供给密集场景

| sampleId | sourceType | sessionId | province | volunteerModel | scoreBand | subjectCombination | gender | strategyType | majorIntentType | regionIntentType | coverageGoal |
|---|---|---:|---|---|---|---|---|---|---|---|---|
| GD-01A | synthetic_profile | - | 广东 | major | L1 | 物理/化学/生物 | 男 | traditional | 泛专业 | 本省优先 | 贴线保守 |
| GD-01B | synthetic_profile | - | 广东 | major | L1 | 历史/政治/地理 | 女 | cautious | 泛专业 | 本省优先 | 贴线文向 |
| GD-02A | synthetic_profile | - | 广东 | major | L2 | 物理/化学/生物 | 男 | cautious | 强理工 | 大湾区优先 | 低分稳妥 |
| GD-02B | synthetic_profile | - | 广东 | major | L2 | 历史/政治/地理 | 女 | traditional | 强文社科 | 广深以外优先 | 低分地域约束 |
| GD-03A | synthetic_profile | - | 广东 | major | M1 | 物理/化学/生物 | 男 | traditional | 强计算机/电子 | 大湾区优先 | 中低分理工 |
| GD-03B | synthetic_profile | - | 广东 | major | M1 | 物理/化学/政治 | 女 | aggressive | 强理工 | 发达地区偏好 | 中低分激进 |
| GD-04A | synthetic_profile | - | 广东 | major | M2 | 物理/化学/生物 | 男 | cautious | 强工科 | 珠三角优先 | 中高分稳妥 |
| GD-04B | synthetic_profile | - | 广东 | major | M2 | 历史/政治/地理 | 女 | cautious | 强财经/语言 | 华南偏好 | 中高分文商 |
| GD-05A | synthetic_profile | - | 广东 | major | H1 | 物理/化学/生物 | 男 | aggressive | 强计算机/自动化 | 发达地区偏好 | 高分激进 |
| GD-05B | synthetic_profile | - | 广东 | major | H1 | 物理/化学/生物 | 女 | traditional | 强理工 | 排除中外合作 | 高分约束 |
| GD-06A | synthetic_profile | - | 广东 | major | H2 | 物理/化学/生物 | 男 | cautious | 强工科 | 强地域偏好 | 头部段稳妥 |
| GD-06B | synthetic_profile | - | 广东 | major | H2 | 物理/化学/生物 | 女 | aggressive | 强理工 | 强地域偏好 | 头部段激进 |
| GD-07A | synthetic_profile | - | 广东 | major | M1 | 物理/化学/生物 | 男 | traditional | 泛专业 | 排除北京/上海 | 中低分负向地域 |
| GD-07B | synthetic_profile | - | 广东 | major | M1 | 历史/政治/地理 | 女 | traditional | 泛专业 | 本省周边 | 中低分保守 |
| GD-08A | synthetic_profile | - | 广东 | major | H1 | 物理/化学/生物 | 男 | traditional | 强电子信息 | 大湾区优先 | 高分保守 |
| GD-08B | synthetic_profile | - | 广东 | major | H1 | 历史/政治/地理 | 女 | cautious | 强文社科 | 发达地区偏好 | 高分文向 |

### 5.4 河北

河北首轮以 `majorGroup` 为主，当前本地无真实会话，先人工补样。

| sampleId | sourceType | sessionId | province | volunteerModel | scoreBand | subjectCombination | gender | strategyType | majorIntentType | regionIntentType | coverageGoal |
|---|---|---:|---|---|---|---|---|---|---|---|---|
| HE-01A | synthetic_profile | - | 河北 | majorGroup | L1 | 物理/化学/生物 | 男 | traditional | 泛专业 | 本省优先 | 贴线保底 |
| HE-01B | synthetic_profile | - | 河北 | majorGroup | L1 | 历史/政治/地理 | 女 | cautious | 泛专业 | 本省优先 | 贴线女生 |
| HE-02A | synthetic_profile | - | 河北 | majorGroup | L2 | 物理/化学/生物 | 男 | traditional | 强理工 | 京津冀偏好 | 低分保守 |
| HE-02B | synthetic_profile | - | 河北 | majorGroup | L2 | 物理/化学/政治 | 女 | cautious | 强理工 | 排除北京 | 低分负向地域 |
| HE-03A | synthetic_profile | - | 河北 | majorGroup | M1 | 物理/化学/生物 | 男 | cautious | 强工科 | 京津冀偏好 | 中低分稳妥 |
| HE-03B | synthetic_profile | - | 河北 | majorGroup | M1 | 历史/政治/地理 | 女 | traditional | 强文社科 | 本省优先 | 中低分文向 |
| HE-04A | synthetic_profile | - | 河北 | majorGroup | M2 | 物理/化学/生物 | 男 | aggressive | 强计算机/电子 | 发达地区偏好 | 中高分激进 |
| HE-04B | synthetic_profile | - | 河北 | majorGroup | M2 | 物理/化学/生物 | 女 | cautious | 泛专业 | 华北偏好 | 中高分女生 |
| HE-05A | synthetic_profile | - | 河北 | majorGroup | H1 | 物理/化学/生物 | 男 | traditional | 强理工 | 京津冀偏好 | 高分保守 |
| HE-05B | synthetic_profile | - | 河北 | majorGroup | H1 | 物理/化学/政治 | 女 | aggressive | 强理工 | 发达地区偏好 | 高分激进 |
| HE-06A | synthetic_profile | - | 河北 | majorGroup | H2 | 物理/化学/生物 | 男 | cautious | 强工科 | 强地域偏好 | 头部段稳妥 |
| HE-06B | synthetic_profile | - | 河北 | majorGroup | H2 | 物理/化学/生物 | 女 | aggressive | 强理工 | 强地域偏好 | 头部段激进 |
| HE-07A | synthetic_profile | - | 河北 | majorGroup | M1 | 物理/化学/生物 | 男 | traditional | 泛专业 | 本省优先 | 中低分本省稳态 |
| HE-07B | synthetic_profile | - | 河北 | majorGroup | M1 | 历史/政治/地理 | 女 | cautious | 泛专业 | 排除北京/天津 | 中低分负向地域 |
| HE-08A | synthetic_profile | - | 河北 | majorGroup | H1 | 物理/化学/生物 | 男 | aggressive | 强计算机/自动化 | 发达地区偏好 | 高分工科激进 |
| HE-08B | synthetic_profile | - | 河北 | majorGroup | H1 | 历史/政治/地理 | 女 | traditional | 强财经/语言 | 华北偏好 | 高分文商保守 |

## 6. 第一批执行优先级

建议先按以下顺序执行。

### P0：真实样本回归

先跑：

- HN-01A
- HN-02A
- HN-03A
- HN-04A
- SD-01A
- SD-02A

目的：

- 快速确认当前 backend 在真实链路上的稳定性
- 先验证 `major` 和 `majorGroup`

### P1：高分补样

优先补：

- HN-07A / HN-07B
- SD-05A / SD-05B
- GD-06A / GD-06B
- HE-06A / HE-06B

目的：

- 弥补当前本地真实会话高分段明显不足的问题

### P2：负向地域 / 约束补样

优先补：

- HN-02B
- SD-06B
- GD-07A
- HE-07B

目的：

- 验证硬约束和软意向对初始方案的影响

## 7. 当前结论

当前第一批样本池共：

- `64` 个样本

其中：

- 真实样本：`7`
- 人工补样：`57`

说明：

- 当前本地真实会话足以支撑“链路回归”和“局部真实对照”
- 但不足以支撑跨省份、跨高分段、跨性别的系统性评估
- 第一批评估必须显式引入人工补样

## 8. 下一步

建议下一步按本样本池继续做：

1. 生成每个样本的标准化输入
2. 批量跑老版优选结果
3. 批量跑新版初始方案结果
4. 输出新旧对照报告和异常样本清单
