---
task: P1d
status: DONE_WITH_CONCERNS
executor: 本地会话（2026-09-22）
finished_at: 2026-09-22 07:0x +0800
source: docs/superpowers/tasks/P1d-rank-structured-reasons/TASK.md（本任务书由执行方按推进计划第 8 条 + 代码核查写成）
---

# P1d 报告：rank 理由结构化

## 一、结论

计划书写的是"把 `college_remark` 串 + `weight_Query` 逐因子字段 + 熵权权重字典转成
`{score, factors:[{name, weight, delta, reason}]}`"。**核查发现这里少了一步**：

> **`delta` 今天不存在。** rank 的调整是就地做掉的
> （`college_score_new = college_score_new * 0.1 * school_value` 之后只留一个中文标签），
> 多个因子还会叠加，**事后无法从响应里反推**逐因子增量。所以 `delta` 必须由 rank
> 在调整时顺手记下——这是计划书没写、但绕不过去的一步。

按这个修正做完三步：rank 侧记增量 → Java 映射成稳定结构 → 挂到推荐结果上。

## 二、交付

| 路径 | 变更 | 验证 |
|---|---|---|
| `zhiyuan-rank/services/recommendation.py` | **75 处**调整点各记 `{tag, delta}`（college 28 字面量 + 14 动态、major 21 + 12），新增 `college_factors` / `major_factors`（**与既有 `*_remark` 串并存**，旧字段一字未动）；5 处挂载到结果对象；新增 `_record_factor()`（`delta` 一律取差值——正向是加、负向是乘，两种写法用同一口径） | 新增 3 条单测；全量 **14 passed** |
| `zhiyuan-server/.../model/dto/volunteer/RankReasonDTO.java` | `{code, name, weight, delta, reason}`，`weight` 可为 null | — |
| `zhiyuan-server/.../service/biz/RankReasonMapper.java` | 标签表（院校 16 / 专业 11）+ **动态标签按后缀归类**（`计算机类（类）标签正向加分` → `major.group.tag.positive`，具体标签进 name）+ 未知标签 `unknown:` 保留 + WARN | **7 passed** |
| `zhiyuan-server/.../manager/rank/VolunteerRankClient.java` | 拿到 rank 响应后就地 `fillReasons(...)`（**放在 rank 边界**：映射只做一次，所有调用方都拿到带好理由的组对象） | **3 passed**（含"旧串不许被动"） |
| `VolunteerSchoolGroup` / `VolunteerRecommendBuilder` | 原始字段 + `collegeReasons`/`majorReasons`；新通道进 tags（`college_reasons`），与旧串并存 | 全量 796 |

三条口径写死在类注释并各有专测：**未知标签不丢**（静默丢弃会让"为什么加分"少一条，
而少的那条恰是新规则）、**权重取不到不补 0**（补 0 会让"没有权重"与"权重是零"混成一个样子）、
**不在 Java 重算 delta**（那是把观测值换成推断值，而理由是要给人看的）。

## 三、验收（原始输出）

rank 侧（`unittest`，该工程没有 pytest）：

```text
$ .venv/bin/python -m unittest discover -s tests
Ran 14 tests in 0.071s
OK
```

实测数字（单测里打印，可复核）：

```text
只命中院校 ：{'院校正向加分': 24.0}                          总分 60.0 → 84.0
院校 + 层次：{'院校正向加分': 24.0, '院校层次正向加分': 8.0}   总分 60.0 → 92.0
            delta 之和 32.0 == 总分差 32.0；且 24 ≠ 8
专业侧     ：{'计算机类（类）标签正向加分': 4.0}
```

对照测试断言的是**"先发生的那个因子"在两次运行里 delta 相同** +
"各 delta 之和 ≈ 总分差" + "两个 delta 不相等"——最后一条挡的是"把总分差平均分给两条"
那种看起来很对的编造。

Java：`mvn -o test` → **796 passed**；重打包 + 重启后端后真实回合正常。

## 四、查证过程中发现的两条约束

1. **`zhiyuan-server` 是 Java 1.8**（`pom.xml:23`）——`record` / `Map.of` / `List.of` 都不能用，
   第一版因此编译失败，已改回 Java 8 写法。
2. **`getRecommendVolunteer` 用 fastjson `TypeReference<List<VolunteerSchoolGroup>>`
   直接反序列化 rank 响应** → 新字段只要名字对上就会自动到家，不用改解析代码。

## 五、未验（如实记）

- **端到端没跑**：需要一次真实推荐调用，而**本地只读栈从不调用 rank**
  （`grep -c "调用志愿排序接口" /tmp/backend-18090.log` = **0**）。那条路径属 P2 的写闭环。
- **HTTP 级冒烟也没成**：直接 POST rank 的 `recommend_volunteer` 需要一份**真实（Java 形状）
  载荷**，手上的测试桩载荷缺 `sex` / `subjectList` 等字段——逐字段补就是猜形状，停下了。

## 六、过程中的两次自伤（留痕）

1. 改写器第一版把 26 处**后一行代码覆盖掉**（`lines[i] = x + lines[i]` 是前缀拼接、不产生行位移，
   我却按位移修了索引）——用备份还原后改成**逐行改写**才对。
2. 一次 `cp` 撞上交互式别名、一次 `pkill` 把自己的 shell 带走；两处都用 md5 核对过还原结果，
   没有留下半改状态。
