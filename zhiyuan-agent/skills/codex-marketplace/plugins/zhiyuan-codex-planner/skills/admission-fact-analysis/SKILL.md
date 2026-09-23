---
name: admission-fact-analysis
description: Use when a user asks about current plans, historical admission data, subject eligibility, or the factual basis for whether a school-major choice can be submitted.
version: 1.0.0
---

> 执行口径以 `r1/admission-fact-analysis/references/evidence-policy.md`（跨技能引用，路径以插件根为基准） 为准（提问顺序、冲突处理、单轮问题数等细则在那里）。
> **动手前先读它**——读一次比凭印象写更省事，也避免和规范悄悄分叉。

# Admission Fact Analysis

## 适用条件

- 用户询问招生计划、选科要求、历年分数/位次、招生单元或填报资格。
- 候选推荐或方案审查需要补充可审计的招生事实。

## 不适用条件

- 仅讨论兴趣、培养路径或个人偏好时，不主动调用招生接口。
- 用户要求修改画像、方案或最终确认时，保持只读并转交 Proposal/CAS 流程。

## 前置状态

- 已确认省份、考试年份、科目/选科、批次和招生类别。
- 院校、专业和招生单元必须有标准 ID；实体歧义先澄清。
- 读取当前 `stateVersion`，所有查询结果必须带数据版本和适用范围。

## 允许能力

- `entity.resolve`、`catalog.get_school`、`catalog.get_major`
- `admission.get_current_plan`、`admission.get_history`、`admission.check_eligibility`
- 只读招生事实；不重算系统录取率，不调用 Solver 或写工具。

## 标准步骤

**口径现状（2026-09-21 实测）**：
- **录取分有三种口径，`majorId` 传不传决定了查哪一层**（实测江苏·北大·物理·本科批 2025）：

  | 怎么查 | 返回 | 有分数吗 |
  |---|---|---|
  | **不传 `majorId`** | 院校/**专业组**级一行（`name` 就是招生单元名，如"北京大学05专业组"） | **有**（minScore/minPos） |
  | `majorId="0"` | 专业级 · **大类招生**行（几十行，列全部专业/大类） | 该省恒为 0 |
  | `majorId="<具体>"` | 专业级 · 具体专业，**可回多年序列** | 该省恒为 0 |

  → **"某校某专业组多少分"走"不传 majorId"**；专业级分数在多数省**上游就不公布**，
  所以不要因为专业级没数就说"查不到"——先按专业组口径给出来，并标明这是**单元级**投档线。
  返回里带 `caliber_unit_level_not_major` 就是这条口径。
- **"这所学校在我省按什么招生"可查，而且免分数**：`catalog.list_admission_units(schoolId, areaId)`
  给出招生单元（含年份/科类/批次/单位编号），再用 `admission.get_enrollment_plan(schoolUnitId, ...)`
  拿到该单元的招生专业、计划数、学费、选考要求。**名校常按试验班/大类招**——用户问的
  "计算机"可能只出现在某个试验班的**包含专业**里，这一条能如实说清，而不是回答"查不到"。
- **专业级录取分仍不可查**：分数线上游只吃学校级 + 一个我们拿不到的 `majorId` 口径
  （实测传单元编号、传专业代码都是 0 行）。要如实说"这条口径还没接上"，
  **不要让用户先去挑专业再来落空**。

**身份五层，取值口径各不相同（2026-09-21 实测四省）**：

| 层 | 传什么 | 取值来源 | 例 |
|---|---|---|---|
| 省 | `areaId` 六位码 | — | 浙江 330000、江苏 320000 |
| 年 | `year` | 招生计划年（**不是**录取年） | 2026 |
| 科类 | `subjectType` 用**码**：`N`/`WL`/`LS` | `catalog.list_admission_units` 的 `subjectType` | 浙江 `N`(综合)、江苏 `WL`(物理)/`LS`(历史)。**传中文"物理"上游不报错、只返回空** |
| 批次 | `batch` 用**地区码** | `catalog.list_batches` | 浙江 17/18、江苏·河北 01 |
| **招生单元** | `schoolUnitId` | `catalog.list_admission_units` 末层 | 浙江=学校级(1103)；**3+1+2 省份就是"专业组"**（江苏 310107 = 北大 07 专业组，物理/历史各一个） |

**"专业组"不是另一张表，就是 `schoolUnitId`**：同一个学校在同一批次下可能有多个单元
（按选科要求分组），物理与历史科类各自独立。`label` 是给人看的（"07专业组""第一段"），
`value`/`subjectType`/`batch` 才是拿来查的——**两者都要用对**：拿 label 去查会查空，
拿 value 去跟用户说话会念代码。

**章程/招生简章**：`admission.get_charter(schoolId, year?)` 取的是**学校发布的招生章程全文**
（免分数、标题自带年份）。正文可能很长，返回里带 `charter_content_truncated` 就是被截断过；
带 `platform_copy_check_school_site` 表示这是平台收录版、**最终以学校官网为准**。
列表为空时它说"平台未收录"，那不是"该校没有章程"。**不要**引用 `getSchoolRule` 的返回——
那是录取规则摘要，该校没有规则时它回占位文案"正在更新中"，而响应里没有标志位区分。

**取数前先取字典**：`batch` 必须是 `catalog.list_batches` 返回的**批次码**
（按省份不同：浙江第一段=`17`、上海本科批=`01`）。传"本科批"这类名字上游**不报错**、
只返回空数据——那会让整条查询看起来像"没有数据"。


1. 检查查询口径是否完整：省份、年份、批次、科目模式、招生单元和专业。
2. 先检查资格，再查询当前计划和历史数据；避免对无资格项目做概率解释。
3. 对历史数据检查 `comparability`、scope、coverage、dataVersion 和 limitations。
4. 原样展示系统提供的录取率/位次结论，区分招生单元与学校整体口径。
5. 说明缺失、未发布、不招生、不适用和未收录的区别，提出下一步澄清。

## Evidence 要求

- 每个关键数字必须引用对应 Evidence、数据版本、省份/年份和招生口径。
- `admission.get_history` 的缺失字段不能转为 0；若不可比，明确 `not_comparable` 或限制。
- 录取率只使用系统针对招生单元、结合成绩和位次计算的结果，第一期不自行重算。

## 单轮调用预算

- 最多 5 次只读调用；相同参数去重，失败最多重试一次。
- 缺少必要查询字段时调用次数为 0，直接请求补充信息。

## 停止条件

- 省份、年份、选科/批次或标准实体缺失时停止，不猜测。
- stateVersion stale、Evidence 越权或后端不可用时停止并返回可恢复错误。

## 输出结构

- `responseType=fact`，包含 `evidenceRefs`、`uncertainties` 和 `limitations`。
- 展示 `eligibility`、`currentPlan`、`history`、`comparability` 和 `dataVersion`，不把多个口径拼成单一结论。

## 降级策略

- 历史数据不完整时只报告实际覆盖范围，允许用户选择更窄的比较口径。
- 后端超时或版本过期时返回 `recoverable.error`，先刷新 Snapshot，不继续基于旧数据推理。
