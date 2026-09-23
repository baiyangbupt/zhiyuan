# P1d：rank 理由结构化（P1 第 8 条，P1c 之后另开）

> 指派：待定（任务书由本地会话按推进计划第 8 条 + 代码核查结果写，2026-09-22）
> 来源：`docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md` 第 8 条（line 227-237）
> 类型：代码改动（`zhiyuan-rank` + `zhiyuan-server` 两处，各自独立）
> 协议：`docs/superpowers/tasks/README.md`

---

## 一、目标

推荐结论现在只能给"分数"和一个**拼起来的中文串**（`college_remark = '院校负向减分;城市正向加分;'`）。
计划要求把这层变成**稳定的结构化理由**：

```
{score, factors: [{name, weight, delta, reason}]}
```

三条硬约束：

1. **对话层只消费这一层**，不直接读 rank 的内部字段名（`college_remark` / `province_gdp` / `school_flag`…）；
2. 映射层**落在 Java**（`zhiyuan-rank/docs/tag-mapping.md`：*统一标签体系由 backend 负责对外收口*）；
3. rank 的内部标签可以继续存在，但不得成为对外语义。

一句话验收：**给一条推荐，能拿到逐因子的 `{name, weight, delta, reason}`，而不是只有分数与一串中文。**

---

## 二、代码核查结果（本任务书写作时核过，不要重新调查）

| 事实 | 位置 / 值 |
|---|---|
| 理由串怎么来的 | `zhiyuan-rank/services/recommendation.py:513-681`：命中哪个分支就 `college_remark += '院校负向减分;'` 这样拼；**同一串里可能有多段**（院校/城市/省份/标签各一段） |
| 熵权（打分权重） | 同文件 `entropy(...)`（`:95`）；学校侧因子 `province_gdp / city_level / upgrade_ratio / postgraduate_recommend_ratio / gaotu_rank / level_score`（`:301`），专业侧 `gender_index / satisfy_index / salary_avg / hot_index`（`:167`、`:247`） |
| Java 拿到的 rank 响应 | `zhiyuan-server/.../model/dto/QueryWeightResponse.java`：**顶层就有**逐因子权重（`Double province_gdp` 等）；每个 `QueryResultItem` 有逐因子**值**、`college_score`（调整前）、`college_score_new`（调整后）、`college_remark` |
| Java 现在怎么用它 | `VolunteerRecommendBuilder.java:630` 把 `college_remark` 原样塞进 `tags`；`VolunteerSchoolGroup.java:48` 也有这个字段——**纯透传，没有任何结构** |
| 客户端 | `zhiyuan-server/.../manager/rank/VolunteerRankClient.java`（本地 `volunteer.rank.url=http://127.0.0.1:18092`，gunicorn 起在 `zhiyuan-rank/`） |

### ⚠️ 核查发现：`delta` **今天不存在**，计划书那句假设不成立

计划书写的是"把 `college_remark` 串 + `weight_Query` 逐因子字段 + 熵权权重字典转成
`{score, factors:[{name, weight, delta, reason}]}`"。可实际代码里，调整是**就地**做掉的：

```python
college_score_new = college_score_new * 0.1 * school_value      # 负向：乘
college_score_new += (100 - college_score_new) * (college_score_new / 100) * 1 * school_value   # 正向：加
college_remark = '院校负向减分;'                                  # 只留下标签
```

即：**只有"调整前 / 调整后"两个总分和一个标签串，逐因子各自的增量没有被记录**，
而且多个因子会叠加（先院校、再城市、再省份、再标签），事后**无法从响应里反推**。
所以 `delta` 必须由 **rank 侧在调整时顺手记下**——这是本任务比计划书多出来的一步。

**不要**在 Java 侧用 `weight × 值` 之类去"算"一个 delta：那会把一个**观测值**换成
一个**推断值**，而理由是要给人看的（"为什么它加分"），推断出来的理由比没有更糟。

---

## 三、步骤

### 步骤 1（rank，Python）：记录逐因子增量

在 `college_score_new` 每次被改动的地方（`:540-681` 那一串分支）把
`(标签, 调整前, 调整后)` 记进一个列表，随结果一起返回（新增字段，**不动现有字段**）。
专业侧同理（`major_remark` 那条链）。

要求：
- **加法**：`delta = 调整后 - 调整前`；**乘法**：同一个定义（差值），不要报倍数——
  下游要的是"它对分数做了什么"，不是"它乘了几倍"。
- 现有 `college_remark` / `major_remark` 字符串**保持原样**：它们是既有前端/导出在用的字段，
  这次是**新增**一条结构化通道，不是替换。（哪天下线由设计裁决，不在这里顺手做。）
- 单测：构造一条只命中"院校正向加分"的记录，断言 `factors` 里恰好一条、`delta > 0`、
  `tag` 与 remark 串一致；**对照**：再构造一条命中两个因子的，断言两条各自的 delta 之和
  与总分差对得上（`sum(delta) ≈ new - old`，浮点用容差）。

### 步骤 2（Java）：映射层

新增映射（放 `VolunteerRecommendBuilder` 一带，或单开一个
`service/biz/RankReasonMapper.java`）：

- **输入**：rank 返回的逐因子增量 + 顶层权重字典 + 现有 remark 串；
- **输出**：`{score, factors: [{code, name, weight, delta, reason}]}`
  - `code`：**稳定标识**（自己定义并写死，例如 `school.negative` / `city.positive` / `province.positive` / `tag.985.positive`），
    **不许直接把 rank 的中文标签当 code**；
  - `name`：给人看的中文短语（可以就是现在的标签，但由 Java 决定，不是 rank 决定）；
  - `weight`：来自顶层权重字典里对应的那一项；取不到就**不下结论**（省略该字段，不要补 0）；
  - `reason`：一句话说明"这条为什么加/减分"（含具体值，例如"该校在你省属意向院校（权重 0.42），加 3.1 分"）；
  - `delta`：直接用步骤 1 的观测值。
- **未知标签**：映射表里没有的标签 → **原样保留一个 `code="unknown:" + 原标签`** 并在
  `reason` 里标注"未纳入统一标签体系"，**不要静默丢弃**（静默丢理由会让"为什么加分"少一条，
  而少的那条恰恰是新加的规则）。同时打一条 WARN 日志，让新标签能被发现。
- 单测：一条已知标签映射正确；**对照**：喂一个未知标签，断言它以 `unknown:` 前缀出现在结果里 + 日志有 WARN。

### 步骤 3（Java）：挂到推荐结果上

`VolunteerSchoolGroup` 增加结构化理由字段（与现有 `college_remark` **并存**），
由 `VolunteerRecommendBuilder` 填充。

**不要**顺手改前端消费：这是给对话层用的新通道，前端接入属 C 线。

---

## 四、验收

```bash
# rank
cd zhiyuan-rank && .venv/bin/python -m pytest tests/ -q

# Java
cd zhiyuan-server && mvn -o -Dtest=RankReasonMapperTest test && mvn -o test
```

1. 给一条**只命中一个因子**的推荐 → `factors` 恰好一条，`delta` 与总分差一致；
2. **对照**：给一条命中两个因子的 → 两条 delta 之和 ≈ 总分差（浮点容差），
   且**不是**"把总分差平均分给两条"（那是一种看起来很对的编造）；
3. 未知标签 → `unknown:` 前缀 + WARN，**不丢**；
4. 权重取不到 → 省略 `weight`，不补 0；
5. 现有的 `college_remark` 字符串与既有单测**一个都不许变**（这次是新增通道）。

端到端（可选，需本地栈）：一次推荐里能同时看到旧串与新结构，且新结构的因子数与旧串的分号段数一致
（多一个少一个都说明映射漏了或重了）。

---

## 五、边界

- 不动 `entropy()` 的算法本身；不动现有 remark 字符串的拼法。
- 不在 Java 里重算 rank 的打分（那会变成第二套评分实现）。
- 不替设计裁决"哪些因子该露给模型"——本任务只保证**结构存在且可映射**。

## 六、进展（2026-09-22，本地会话）

**步骤 1（rank 侧）、2（映射器）、3（挂到推荐结果）都已完成**；端到端未验（见文末）。

### 步骤 2 已完成的部分（映射器本体）

| 路径 | 内容 | 验证 |
|---|---|---|
| `model/dto/volunteer/RankReasonDTO.java` | `{code, name, weight, delta, reason}`，`weight` 可为 null | — |
| `service/biz/RankReasonMapper.java` | 标签表（院校 16 条 / 专业 11 条）+ **动态标签按后缀模式**归类（`计算机类（类）标签正向加分` → `major.group.tag.positive`，具体标签进 name）+ 未知标签 `unknown:` 保留 + WARN | `mvn -o -Dtest=RankReasonMapperTest test` → **7 passed** |

三条口径写死在类注释里：未知标签不丢、权重取不到不补 0、**不在 Java 重算 delta**。
测试里两条"不装懂"各有专条（`shouldOmitTheWeightInsteadOfDefaultingToZero`、
`shouldKeepAnUnknownTagWithAPrefixInsteadOfDroppingIt`）。

**发现的约束**：`zhiyuan-server` 是 **Java 1.8**（`pom.xml:23`）——`record` / `Map.of` /
`List.of` 都不能用，第一版因此编译失败，已改回 Java 8 写法。

### 步骤 3 已完成（挂到推荐结果）

| 路径 | 变更 | 验证 |
|---|---|---|
| `VolunteerSchoolGroup` | 加 `college_factors` / `major_factors`（rank 原样透传）+ `collegeReasons` / `majorReasons`（Java 映射结果）。旧字段 `college_remark` 一字未动 | `VolunteerRankClientTest` 3 条 |
| `VolunteerRankClient.getRecommendVolunteer` | 拿到响应后就地 `fillReasons(...)` —— **放在 rank 边界**：映射只做一次，所有调用方拿到的组对象都带好理由，不必各自记得补（漏补一个调用方 = 那条路少一套理由且不报错） | 同上 |
| `VolunteerRecommendBuilder.buildSchoolAlgTagMap` | 新通道进 tags（`college_reasons`），与旧串并存 | 全量 |

**权重传 null 是刻意的**：推荐接口的响应里没有权重字典（它在另一个接口的响应里），
而按本任务书的口径"取不到就省略"；rank 的调整类因子本来也没有熵权（熵权属于基础分因子）。

一个查证过程中的事实：`getRecommendVolunteer` 用 **fastjson** `TypeReference<List<VolunteerSchoolGroup>>`
直接反序列化 rank 响应——所以新字段只要名字对上就会自动到（不需要改解析代码）。

### 端到端未验（如实记）

**本地只读栈从不调用 rank**：`grep -c "调用志愿排序接口" /tmp/backend-18090.log` = **0**。
所以"推荐里同时看到旧串与新结构"这条端到端**没有可跑的场景**（它属于 P2 的写路径）。
已验到的是：映射器 7 条 + 边界填充 3 条 + Java 全量 796，且重打包重启后正常回合不受影响。

| 项 | 结果 |
|---|---|
| 插桩 | **75 处**调整点（college 28 字面量 + 14 动态；major 21 字面量 + 12 动态）+ 5 处挂载（`plan`/`school` 的 `college_factors`、`majordict`/`major`×2 的 `major_factors`） |
| 动态标签 | 站点是 `major_remark += tag + '标签负向减分;'` 这类**算出来的段名**——先落到 `_segment` 再记账，行为与原实现逐字一致 |
| 新增字段 | `college_factors` / `major_factors` = `[{tag, delta}]`，**与既有 `*_remark` 串并存**（不改旧字段） |
| 单测 | `tests/test_recommendation_mapping.py` 新增 3 条；全量 **14 条通过** |

实测数字（单测里打印出来的，可复核）：

```text
只命中院校   ：{'院校正向加分': 24.0}                       总分 60.0 → 84.0
院校 + 层次  ：{'院校正向加分': 24.0, '院校层次正向加分': 8.0} 总分 60.0 → 92.0
              delta 之和 32.0 == 总分差 32.0；且 24 ≠ 8（"平均分"那种编造会被这条挡住）
专业侧       ：{'计算机类（类）标签正向加分': 4.0}
```

**未做的验证（如实记）**：
- **HTTP 级冒烟**：直接 POST rank 的 `recommend_volunteer` 需要一份**真实（Java 形状）载荷**，
  我手里的测试桩载荷缺 `sex` / `subjectList` 等字段，逐字段补是猜形状——停下了。
  rank 侧行为由单测证明；HTTP 那一层留给步骤 2/3 的 Java 集成顺带覆盖。
- 步骤 2/3（Java 映射层 + 挂到推荐结果）与它们的两条对照测试**未开始**。
