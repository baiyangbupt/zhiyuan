---
task: B7（只做了"接线"这一片）
status: PARTIAL
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 14:45 +0800
source: docs/superpowers/plans/2026-09-20-codex-domain-and-plan-transactions.md
---

# B7 部分报告：技能接线（发现"技能根本没到模型眼前"）

> 本报告只覆盖 B7 的**接线**部分。任务书里的其余内容（16×3 场景评估、能力发布、
> 提示词体积与 compaction 预算）**没做**，状态记 PARTIAL。

## 一、结论

**技能从来没到过模型眼前。** 这条线跑了 A1–A7 一路，没有任何一步验过
"模型到底看不看得见我们写的技能"。实测（在 rollout 里 grep 技能名）结果是 0 次命中：
模型的 `<skills_instructions>` 里只有系统技能（imagegen / openai-docs / plugin-creator），
六个业务技能一个都没有。表现是"模型能力不行"，实际是**技能没接上**。

任务书 B7 第 336 行已经预言过这一类失败：

> 检查 Skills 在该 App Server 的实际发现/加载方式（**配置 root 不等于自动注入所有内容**）

## 二、四处断链（都实测过）

| # | 断链 | 证据 |
|---|---|---|
| 1 | `skills/codex/plugin.json` 是**手写的自定义清单**，codex 只认 `.codex-plugin/plugin.json` + marketplace 注册 | 模型技能清单里 0 个业务技能；该清单的 `skills` 字段是名字列表，codex 从不读它。设计书 §7.3 早就画对了布局，实现时拍平了一层 |
| 2 | 三份 reference（提问指南 / 解释规范 / 证据政策）**没有任何技能引用** | `grep references/` 全仓库只命中那个手写清单 |
| 3 | 没有任何"该走哪个技能"的**路由**技能 | 面对"计算机和物理哪个好"，模型只能自己猜，猜成了"要参数" |
| 4 | `base_instructions.md` 规则 7 禁止 shell/文件，而技能**只能靠读文件**才能到模型眼前 | 模型的推理里明确写了："base rules rule 7 says don't use shell"，于是放弃读技能（run ④ 一次都没读）。**整个技能机制在自己的规则下不可用**，行为还是摇摆的（run ③ 读了、run ④ 没读） |

另外两处规则打架（同一天发现）：

- 技能「停止条件：实体歧义先澄清」 vs `developer_instructions:32`「先回答用户当前问题」——
  没有第三条路，于是最常见的问法（"A 和 B 哪个好"）一律滑成"要参数"。
- 只读工具集 9 个里**没有 `compare_entities`**。4.0 direct 线里它是"法学和财经哪个更适合我"
  的固定走向（见 4.0 设计文档 v2.70），迁到 Codex 原生这条线时没带过来。

## 三、改了什么

| 位置 | 改动 |
|---|---|
| `skills/codex-marketplace/`（新增） | 按设计书 §7.3 做真插件：`.agents/plugins/marketplace.json` + `plugins/zhiyuan-codex-planner/{.codex-plugin/plugin.json, skills/, references}`；已注册 `zhiyuan-local` 并安装 |
| `skills/codex/` | 只剩 `base_instructions.md` + `developer_instructions.md`（composition 从这里读，路径不变） |
| 六个技能的 SKILL.md | 顶部加引用：「执行口径以 `r1/<归属技能>/references/<文件>` 为准，**动手前先读它**」 |
| `references/*.md` | 放到**各自归属技能**的 `references/` 下（codex 要求 `skills/` 下每个子目录都必须是技能，所以没有共享 references 目录——校验器会报 `skill 'references' is missing SKILL.md`） |
| `skills/.../planner-routing/SKILL.md`（新增） | 入口技能：先说出路由 → 一张路由表 → **"缺门禁事实不阻塞解释性内容"** → 交接点名。对应 `superpowers` 的 `using-superpowers` |
| `school-major-exploration` | 停止条件补"**先给不绑定实体的通用维度对比，再澄清**；不允许只回一句'没有统一答案'就收尾" |
| `skills/codex/base_instructions.md` 规则 7/8 | 允许**只读地**读本轮技能与它的 references；其余 shell/文件/网络照旧禁止 |

## 四、验收（同一问题，五次对照）

问题固定为「计算机和物理哪个好」，每次新建空会话、同一模型。

| # | 状态 | 输出 |
|---|---|---|
| ① | 技能没注册 | "我没法直接给「哪个好」的答案…" + 缺参数清单 |
| ② | 注册了插件 | 候选枚举 + 歧义解释 + 维度清单 + 聚焦追问（仍无实质对比） |
| ③ | 停止条件补第三条路 | 8 条通用维度对比 + "为什么现在不能给结论" + 3 问（模型主动 `cat` 了 SKILL.md） |
| ④ | 加了路由技能 | **退化**：一次文件都没读，只剩两次目录检索——规则 7 与"先读我"冲突 |
| ⑤ | 规则 7 放宽 | 读取顺序 `planner-routing → school-major-exploration → profile-discovery/references/planner-questioning-guide.md`；回答含**首句路由**、8 条经验性对比（**逐条标注 planner_experience 等级**）、门禁事实只挡结论、末尾 3 问 |

第 ④ 次值得单独记：**加了正确的东西反而退化**，因为新加的路由技能要求"先读它"，
而规则 7 禁止读。两份规则各自看都对，放一起就死锁——这和"歧义先澄清 vs 先回答问题"
是同一个失败形状。

代码侧：

```text
$ .venv/bin/python -m pytest tests/unit tests/integration -q
1 failed, 1865 passed, 50 skipped, 22 warnings in 30.38s
（失败项为 test_dialog_quality_gate，与本次无关，缺 data/tmp 下的 fixture）
```

`tests/unit/test_codex_skill_manifest.py` 从 5 条扩到 7 条，其中两条是新形状的守卫：

- `test_codex_plugin_manifest_is_a_real_codex_plugin`：测**消费方认不认这个形状**，
  不再只测"文件里写了什么"——手写清单就是死在这一点上。
- `test_every_skill_that_needs_a_reference_points_at_a_real_path`：引用的目标必须真实存在。
  只测"有没有引用"的话，一个指向不存在文件的引用同样全绿。

## 四之二、过程脚本与一个会持续咬人的超时（2026-09-21 下午续）

### 过程脚本

`school-major-exploration` 从"动作清单"改写成**分阶段对话流程**（brainstorming 形态）：

```
阶段 0 分类并把分类说出来（信息不全 / 方向对比 / 具体查询 —— 没有"必须先填表"这一类）
阶段 1 建立基线（门禁事实只挡录取结论，不挡方向性内容）
阶段 2 取权威数据（每条事实要能说出用哪个工具；取不到就明说，不许用记忆补）
阶段 3 维度对比（事实与 planner_experience 分开标；每条注明"落实成结论还缺什么"）
阶段 4 收敛成 2–3 个可判定选项
<HARD-GATE> 用户确认取舍前不进候选/方案；探索永远只读
交接：点名下一轮走哪个技能
```

换了一个**没测过的问题**「学医累不累」验收，脚本被完整执行：首句给分类与路由；
专业名与 majorId 标注"来自本轮目录检索的真实返回，不是我的印象"；经验性内容逐条标
`planner_experience`；"具体学制要以当年招生计划和章程为准，**本轮查不到，也不能由我凭记忆补**"
（对应阶段 2 表里"章程当前不可用"那一行）；末尾给 A/B/C 三个可判定选项并点名下一轮技能。
它还自查出一个没提示过的实体歧义：**临床医学/口腔医学/中医学在本科与专科两个层次同名存在**。

### 超时预算不一致（会持续咬人）

| 层 | 预算 | 行为 |
|---|---|---|
| 前端 `ANSWER_TIMEOUT` | 30s | 只提示"可放弃等待" |
| **harness 整轮截止**（`CodexAppServerConfig.timeout_seconds`） | **30s** | **掐断整轮** → `turn_timeout` → 用户看到"引擎不可用" |
| compat 层 `_CHAT_SERVICE_TIMEOUT_SECONDS` | 180s | 服务超时 |

`CODEX_APP_SERVER_TIMEOUT_SECONDS` 在 `scripts/start-codex-local.sh` 里从未设置，吃的是 30s 默认值。
实测：加了技能读取之后，一轮（3 次文档读取 + 4 次工具调用）**必然超过 30s**，被掐掉那一轮
rollout 里是 `turn_aborted … reason: interrupted`，WS 侧只看到一句"引擎不可用"。
已把 `CODEX_APP_SERVER_TIMEOUT_SECONDS=180` 写进启动脚本（与 compat 层对齐），重跑通过。

**这条不只影响验证栈**：任何"读技能 + 取数 + 长推理"的真实回合都在这个预算里跑。

## 四之三、权威数据入口：对比接上了，但**证据链断在哪**被挖出来了（续）

### 交付：`admission.compare`

- Java：`POST /inner/planning/{tenantId}/session/compare`（薄端点），复用 B4 的
  `CandidateComparisonService`（口径身份 5 字段 + 维度白名单 + 2–5 实体 + 整列不可比）。
  **不取数**：值由调用方从各自来源链路取（那里签证据），端点只管"能不能并排"。
- 只读 MCP 工具 `admission.compare`：一次调用取 2–5 个实体的分数线，装配口径身份，
  交给 Java 判定，返回 cells / unavailableDimensions / limitations + **各实体自己的证据**。
  取不到请求年份时取最新一年，但把该实体的 `admissionYear` 标成实际年份 → 口径不一致 →
  **整列不可比**（悄悄拿另一年的数字顶上才是危险的）。
- 技能：阶段 2 表格加上这一行，阶段 3 写明"两个以上对象且口径齐全时用它，不要自己调 N 次"。
- 单测 3 条（口径缺项拒绝 / 跨年标成不一致 / 证据去重）。

### 证据链上挖出两处断点（这是本轮最值钱的发现）

第一次真实调用 `admission.compare` 时整轮被拒：`evidence_not_found: ev_01M31…`。
顺着查下去是**两处**，都在"最后一跳"：

| # | 断点 | 后果 |
|---|---|---|
| 1 | MCP 工具结果长这样：`item["result"] = {"content":[{"type":"text","text":"<我们的信封 JSON>"}]}`——证据在那个 **JSON 字符串**里，而 `_collect_records` 只遍历 dict/list、**不解析字符串** | 工具签发的证据**永远进不了账本**；模型一引用就 `evidence_not_found` |
| 2 | 修掉 1 之后变成 `evidence_scope_violation`：Java 证据把作用域放在 `scope.chatSessionId`（**嵌套 + 数字**），而校验器 `_scoped_field(entry, "sessionId", "session_id")` 找的是顶层 | 任何真实签发的证据都被判成"越权"，fail closed |

结论：**"带证据的最终答案"（第一批目标）在 Codex 这条线上从来没通过**——
不是模型不引用，是它引用的证据在链路上被丢了一次、又被误判了一次。
`_collect_records` 现在会解析 JSON 字符串；校验器改成同时认 `chatSessionId`/`chat_session_id`
并按**字符串**比 tenant/session（Java 给数字，我们手上是字符串，值一样类型不同曾被判成越权）。

两条都有回归测试（`test_gateway_collects_evidence_from_the_mcp_text_result`、
`test_evidence_in_the_producers_shape_passes_scope_checks`）。

### 章程/政策：**没有接**，理由是不该接

B3 已经把结论写死：上游端点在该校没有规则时回**占位文案**（"正在更新中"）而**响应没有标志位**区分，
年份缺失时取的是全局默认年份。B3 因此**不签发证据**。把它接进工具集，等于把一段可能是
"正在更新中"的文本递给模型当条款——所以没接，并在技能的阶段 2 表里如实标成"当前不可用"。

### 更正：上游**有**数据——"取不到非空数据"是**批次码**用错了

我先前据"各种口径一律 `data: []`"下过"上游没数据"的结论，**这是错的**，已由一次直连上游推翻：

```text
POST https://www.gaotuzhiyuan.com/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine
  {"areaId":"330000","batch":"17","schoolId":"1","year":2024,"subjectType":"N"}
→ 200 {"code":0,"data":[{... "minScore":"707", "minPos":"2", "enrollNum":"31" ...}]}
```

`batch` 必须是**该省的批次码**，而它是地区相关的字典值：

```text
浙江：batchListByPolicy(areaId=330000) → 17=第一段 / 18=第二段
上海：batchListByPolicy(areaId=310000) → 01=本科批
```

传"本科批""第一段"这类**中文名，上游不报错、只返回空**。而只读工具集里**没有任何工具能取批次码**，
于是模型只能编一个名字 → 每次查询都空 → 看起来像"上游没有数据"。

**这条同时更正了 P1b-1 的挂起结论**（`P1b-1/REVIEW.md`：`querySchoolMajorScoreLine` 三组参数
一律 `data: []`、"灰度环境取不到非空数据"）。真相不是上游没数据，而是**缺一个字典步骤**。

补的东西：

| 位置 | 改动 |
|---|---|
| Java | 无需改动——`/inner/gaotu/batch/info` 早就有了（`GaotuClientDebugController`），只是没人用 |
| Python | `internal_client.get_batch_info(...)` + 只读工具 `catalog.list_batches`（能力 `catalog_read`，schema 要求 `areaId`） |
| 技能 | `school-major-exploration` 阶段 2 表格加"批次码"一行；`admission-fact-analysis` 开头加"取数前先取字典" |

### 证据链：又两处（一个是我自己踩响的）

批次码修好之后，整轮仍然被拒，继续挖出两处：

| # | 断点 | 说明 |
|---|---|---|
| 3 | `_collect_records` 用 `id()` 做去重，而**解析 JSON 字符串会临时造对象**：临时对象被回收后 `id()` 被复用，第二条证据的包裹体被误判成"已遍历过"而整条跳过 | 实测三条工具结果只进账本一条，而模型引用的**恰好是被丢的那条**。这条是**我加"解析字符串"时踩响的**——以前不解析字符串就永远碰不到。修法：解析出来的对象用 keepalive 持有到遍历结束 |
| 4 | 会话比对两边类型不一致：Java 给数字（`chatSessionId: 900021`），快照里是字符串 | `900021 != "900021"` → 合规证据被判越权。两边都按字符串比；同时加了一条"**别的会话的证据仍然必须拒**"的反向测试，免得下次有人为了让它通过而删掉比较 |

### 现状：证据链第一次跑通

```text
turn output rejected：无
codex turn failed：无
最终输出：responseType=clarification, evidenceRefs=['ev_01M31EA62F1XCEBCHZSKP1Y6AM']
```

模型这一轮还自己说出了那个坑：「直接传『第一段』这类中文名，上游不报错但会返回空数据，
容易误判成『没数据』」——正是技能里新加的那条。它同时如实报告
`admission.get_history` 返回 `needs_clarification: missingFields=[majorId]`（历史录取是**按招生单元**存的，
给不出"学校整体最低分"），**没有编数字**。

### 招生单元与招生计划：接上了，A6 的验收样本第一次真正答出来

前面查出"专业级录取分拿不到"，继续挖发现**门在后面那道**：

```text
GET /hl-wish/ci/h5/school/noToken/planMajorFilterList?schoolId=1&areaId=330000
  → 年份 → 科类 → 批次 → 招生单元：
    2025 → N(综合) → 17(第一段) → {value: "9701372467122640", label: "北京大学", code: "1103"}
  （value 就是 planMajorDataList 的必填 schoolUnitId，**全程免分数**）
POST /h5/school/noToken/planMajorDataList {schoolUnitId, ...}
  → 该单元的招生专业：001 工商管理类 / 002 文科试验班类 / 005 理科试验班类(元培，含**计算机类**) / 006 理科试验班类
```

补的东西：

| 位置 | 改动 |
|---|---|
| Java | `GaotuClient.getPlanMajorFilterList` + `PlanMajorFilterNode`（四层同形，不按层拆 DTO）；两个 inner 端点：`/plan/filter-list`、`/plan/major-data`（后者是 `AdmissionSourceService.listEnrollment` 的**第一个调用方**——B3 建好之后一直没人调） |
| Python | `get_plan_major_filter_list` / `get_enrollment_plan` + 两个只读工具 `catalog.list_admission_units`（四层树**摊平成行**）、`admission.get_enrollment_plan` |
| 技能 | 阶段 2 表格加一行；`admission-fact-analysis` 的"口径现状"重写：**"这所学校在我省按什么招生"可查且免分数**，专业级录取分仍不可查 |

#### 两处"必填项对不上"，都是靠实机暴露的

1. **上游错误被吞成 `upstream_error`**：`_preserve_envelope` 把非 0 码压成一句状态，丢掉了 `code` 与 `msg`。
   实测模型因此**连调三次都因同一个必填项失败**而看不出缺什么。现在错误码与原文一起进 `limitations`。
2. **工具必填项比上游少**：`admission.get_enrollment_plan` 起初只要求 `schoolUnitId`，
   而 Java 侧还要 `schoolId`、上游还要 `(areaId, year, subject, batch)`。
   **上游在缺项时返回空列表而不是报错**——于是模型连查四年、年年"0 行"，最后如实报告"取不到数据"，
   而数据本来就在。现在六项一起必填，缺项时一次性列出并指明从 `catalog.list_admission_units` 取。

#### 验收：A6 的验收样本第一次被真正回答

问题「北大在浙江招不招计算机专业」（新会话，真实链路）：

```text
工具链：entity.resolve → catalog.list_admission_units → catalog.list_batches
        → admission.get_enrollment_plan（六项口径齐全）
输出：responseType=fact
  "北大在浙江**没有**把'计算机'单列成一个招生专业条目；'计算机类'是作为
   「理科试验班类（元培）」的包含专业出现的。所以：招，但走元培理科试验班大类
   （计划 2 人，选考物理＋化学），不是一条独立的'计算机科学与技术'计划。
   这 2 人是该试验班在浙江的总计划数，不是计算机类单独的名额。"
```

它同时如实标注了"招生单元列表没有 evidenceRefs，这条由招生计划证据间接支撑"——
这正是 `evidence-policy` 里"事实与解释分级"的用法。

### 专业级录取分：查清楚了，卡在**招生单元字典没接**

实验（同一端点，只改 `majorId`）：

```text
school=8 (浙大)  majorId=574 → rows=0   | 不传 majorId → rows=1 (enrollNum=1889)
school=3 (清华)  majorId=574 → rows=0   | 不传 majorId → rows=1 (enrollNum=29)
school=15536480217090560        → rows=0 | 不传 majorId → rows=0（专科，浙江一段本就没有）
```

**上游那条端点的 `majorId` 不是我们目录的 majorId**——对任何学校都是 0 行。
上游的录取数据按**招生单元**组织（`schoolUnitId`/`planMajorId`/`majorEnrollCode`），
而 `planMajorDataList` 反过来**要求 `schoolUnitId` 作为入参**（实测报
"院校省份招生单位编号不能为空"）。也就是说：拿单元身份要先有单元字典（`z_school_unit` 那套，
契约文档 §二列过），而只读工具集里没有这个入口。

因此现状是：**学校级可查、专业级不可查**，而 A6 的验收样本（"查北大计算机"）恰恰是专业级。
技能里已按事实写明这一点，并明确要求**不要让用户先挑专业再来落空**。

接它属于 B2/B3（招生来源接入）的范围，需要一份任务书：先确认上游有没有"按 (schoolId, areaId, year, batch, subject) 列招生单元"的端点（契约文档是从上游源码推的，没有真实调用样本），
再接成只读工具。

### 顺带：回合预算仍然偏紧

最后一轮跑成 `turn_timeout`（已从 30s 提到 180s）。一轮里"读 2–3 份技能 + 4 次工具调用 + 长推理"
在 180s 内仍可能超；预算调多少、要不要缓存技能读取，需要按真实分布定，不该随手再加。

## 四之四、身份层级与筛选：系统性结论 + 一处 fail-open（续）

按"结合上游页面端与 zhiyuan-server 的筛选，看准确数据如何定义"做了一次跨仓调查
（上游 `hl-wish-server` + 页面端仓库 + 本仓 + 四省真机），结论落成契约文档
**`docs/contracts/admission-identity-and-filters.md`**。要点：

- **身份是五层**（省/年/科类/批次/招生单元），**页面端筛选级联止于「招生单元」**，
  页面上叫「招生方向」——**就是 `schoolUnitId`（= 专业组）**，不是另一张表。
- **"专业类"是行的属性，不是筛选层**：只在志愿填报页的「筛选专业」Cascader 里作为一层出现；
  计划/录取行同时持有 `category_id`/`sub_category_id`。
- **`major_id = 0` 是"大类招生"哨兵**（SQL 里 `sub_category_id = #{subId} AND major_id = 0`）——
  这解释了实测里北大计划行的 `majorId="0"`：不是缺数据，是按大类招。
- **录取数据的三种查询模式**（真机）：不传 `majorId` → 院校/**专业组**级（`name`="北京大学05专业组"，
  **有真分数** 686/126）；`majorId=0` → 专业级·大类行（81 行）；`majorId=<具体>` → 专业级·具体专业（跨年序列）。
  **专业级行的分数列在该省恒为 0**——"专业级录取分查不到"不是我们没接，是上游对该省只公布到专业组口径。

### 顺带修掉一处 fail-open（比 fail-closed 更糟）

`admission.check_eligibility`（选科资格）**对任何专业都返回"通过"**，两层都错：

| 层 | 缺陷 | 后果 |
|---|---|---|
| Java | agent 把 `majorId` 塞进 `majors["level2"]`，而 `PlanValidationService` 只读 `level3` | 空循环 → `return true`，日志还打印"所有专业的选科要求都满足" |
| 工具 | 布尔结论被判成"后端没返回结构化数据" | 模型连"合格/不合格"都读不到，只收到 `insufficient_data` |

两处都已修（落到 `level3` + 缺参拒绝；布尔包成 `{"eligible": bool, "checked": "subject_requirement"}`），
各带一条防回归。**用户会据此填报，所以这不是"体验问题"。**

## 四之五、把口径接进工具：录取分第一次真正答出来（续）

调查发现 `admission.get_history` **强制要求 `majorId`**，而上游按"`majorId` 是否非空"分流：
非空 → 专业级表（该省分数多为 0）；**空 → 院校/专业组级表（投档线在这里）**。
也就是说**工具正好拒绝了唯一能返回数据的查法**——模型收到 `needs_clarification: majorId`，
而它问的那条本来查得到。

改了两处：

| 位置 | 改动 |
|---|---|
| `ReadonlyDomainTools.call` 的 get_history 前置校验 | 去掉 majorId/groupCode 必填，只保留五项口径（省/批次/学校/年/科类） |
| `get_history` 返回 | 不传 `majorId` 时加 `caliber_unit_level_not_major` limitation |
| `_history_envelope` | 上游信封的 `limitations` **带出去**（重建信封时丢掉了，会把单元级投档线当成默认口径的"专业级数据"） |
| 技能 `admission-fact-analysis` | 写清三种口径的表：不传 majorId=单元级（**有分数**）/ `0`=大类行 / 具体 id=专业级（分数多为 0） |

验收（新会话，真实链路）：

```text
工具链：entity.resolve → catalog.list_batches → catalog.list_admission_units
        → admission.get_history（不传 majorId）
输出：responseType=fact
  "北京大学 2024 年浙江第一段（综合改革）录取最低分：707 分。
   最低分 707 | 最低位次 2 | 招生人数 31 | 最高分 未返回（上游为空，本查询不把缺失当 0）
   口径说明：这是招生单元级（学校级）投档线，不是某个专业的专业录取分。
   系统返回中带有 caliber_unit_level_not_major"
```

注意最后两行：它引用了口径标记，并且**没把缺失的最高分写成 0**——
这正是 `evidence-policy` 与"不许把没查到写成没有"那两条在真实回合里的样子。

## 四之六、招生章程：接上了，而且推翻了我先前"不该接"的结论（续）

用户提示"章程应该是一个 pdf，页面上也会有招生章程"——查下去发现**我先前把两个端点当成一件事**：

| 端点 | 内容 | 判断 |
|---|---|---|
| `GET /school/noToken/getSchoolRule`（本仓已接） | `z_school_admission_rule` 的**录取规则摘要**，没规则时回占位文案"正在更新中"且响应无标志位 | **仍然不签发证据、不当原文** ✓ B3 的原判断对这条成立 |
| `POST /h5/school/noToken/newsPage` + `GET /school/noToken/getNewsInfo` | **招生章程全文**（院校资讯里的"招生简章"；页面入口在院校库「招生简章」tab） | **原文条款就在这里** —— 我先前根本没找到它 |

实测四校（北大/清华/浙大/福建师大）各有 2024–2026 三年，标题自带年份、有 `isPublish`；
正文是 **HTML 而非 PDF**（福建师大 2026 那条 95KB、去标签 5581 字，开头"第一章 总则 第一条…"）。

交付：Java 两个客户端方法 + 两个 inner 端点 + 新证据源 `gaotu.schoolNews`；
Python 只读工具 `admission.get_charter(schoolId, year?)`（按标题里的年份选题、HTML 转纯文本、
上限 4000 字符并标 `charter_content_truncated`；列表为空时说"**平台未收录**"而不是"该校没有章程"）；
两个技能写清"用这条、不要用 getSchoolRule"。

验收（新会话，真实链路）：

```text
工具：entity.resolve → catalog.search_schools → admission.get_charter(1,2025) → admission.get_charter(2,2025)
输出：responseType=fact（有证据）
  "这份章程本身没有逐专业列出选考科目要求。第九条：非综合改革省份按理工/文史分类录取；
   综合改革省份按其方案执行。第十九条：外语类专业只招英语语种（语种限制，不是选考限制）。
   检索「北京大学」命中两个独立实体——本部(schoolId=1) 与 医学部(schoolId=2)，医学部单独投档。
   '某专业在你省要选什么科目'来自各省招生计划，**不在章程里**。"
```

模型自己想到了医学部是独立实体、并点明"选考要求在招生计划不在章程"——这条链路的信息已经够它讲清楚了。

### 顺带修掉一个会咬很多轮的解析缺陷

章程那轮第一次跑挂了：`output_schema_invalid: output_missing`。查下去是**抽取层**的问题——

```text
模型的输出（2435 字、按"第一章/第几条"分段）在 line 1 column 76 报
Invalid control character：JSON 字符串里是**真换行**而不是 
 转义。
json.loads 默认严格 → 三层抽取全失败 → missing → output_missing → 整轮失败，
而内容本身完全合规（responseType=fact、引了章程条款）。
```

修法：三层 `json.loads` 改用 `strict=False`（只影响字符串内的控制字符；尾逗号、单引号照旧拒绝），
**契约校验仍在 pydantic 那一层**——不是放松校验，是"先把话听清再判"。两条测试钉住：
`test_extraction_tolerates_raw_control_characters_in_strings` 与
`test_extraction_still_rejects_genuinely_broken_json`（后者防"总能解析"）。

## 四之七、评估基线：评估器与 16 场景用例（续）

任务书点名要的两个资产先前**都不存在**（`tests/fixtures/codex_semantic/zhiyuan_acceptance_v1.json`、
`scripts/evaluate_zhiyuan_acceptance.py`）。已按任务书给命令的形状补齐。

### 评估器怎么保证"测的是用户看得见的东西"

驱动与浏览器一致：**Java 建会话 → 取票（带 Origin）→ 带票连 compat WS → 发一句话 → 收终态**。
断言只落在两个通道上，并且**分开标注来源**：

| 通道 | 能断言 | 不能断言 |
|---|---|---|
| WS（进度事件 + 终态文本） | 用了哪个工具、回复里有没有某个词、有没有越权写痕迹 | `responseType`、证据 id —— **compat 回的是模型散文（`reply`）** |
| rollout | `responseType`、`evidenceRefs`、读了哪些技能、MCP 调用、输入/输出 token | 用户此刻看到什么 |

结构化断言必须走 rollout——这一点是**跑出来的**：第一次把 `expectResponseType` 挂在 WS 文本上，
一条完全正确的回答（707 分、口径标注齐全）被判成"没给结构化输出"。

判定分三态：`pass` / `business`（断言不过）/ `env`（超时、引擎不可用）。
**环境失败单列但计入总分母**（计划要求：把超时从分母剔掉，报出来的通过率是假的）。

### 评估器刚跑起来就抓到两处

1. **`admission.get_charter` 没有进度标签** → 前端看到的是掩码 `domain`，验收脚本也断言不了用了它。
   已补，并把"每个能力都要有标签"变成测试（`test_every_capability_has_a_progress_label`）——
   这类漏配靠人眼查，下次还会漏。
2. **评估器自己的顺序错**：`_judge` 跑在合并 rollout 指标之前，于是每条结构化断言都判成"没给"。
   （记录里明明有 `responseType=fact`。）已改成先取指标再判定。

### 用例集

16 条，对齐任务书列的场景：实体歧义、明确查询不反问、未知上游、缺画像、概率/年份/章程、双校对比、
偏好冲突、完整生成、major_group、锁定项调整、取消、重复确认、stale、跨回合引用、重启、注入。

**只读阶段的边界写进用例本身**：写链路（生成/调整/确认）在当前阶段验不了，
所以这些用例只断言 `expectNoWrite`——"没有写痕迹"，而不是假装验了写成功。
其中"重启"与"跨回合引用"两条单轮跑不出真结论，用例里 `notes` 明确写了这一点。

## 四之八、提示词体积与工具计量（任务书点名的那项）

计划要求："记录一次调用用了哪些技能，提示词体积、MCP 调用量和 compaction 后恢复；
超过主设计预算必须先缩摘要/分页"。评估器已经把**技能、MCP 调用、token** 三个计量接上
（从 rollout 读，与 WS 侧结论分开标注）。体积拆解（样本：一轮真实回答，rollout 实读）：

| 组成 | 字符 | 占比 |
|---|---|---|
| **工具结果（累计）** | 10545 | 49% |
| 开发者指令（`developer_instructions.md`） | 5947 | 28% |
| `turn_snapshot`（Java 快照） | 2517 | 11% |
| `AGENTS.md`（仓库说明，被 codex 当项目指令注入） | 2193 | 10% |
| **合计（可见注入）** | **21202** | 100% |

另外两块**不在 rollout 里**、但同样占预算：

- `skills_instructions` 块 **4261 字符**（6 个系统技能 + 我们 7 个，`r0`/`r1` 两个技能根）——
  这是模型选技能的**唯一索引**，删不得；
- 实测**单次模型调用输入 ≈33.5k token**，扣掉上面约 10k 可见注入，
  **余下约 23k token 是 codex 自己的系统提示与 MCP 工具 schema**——**这是大头，而且不在我们手里**。

结论（供设计侧定预算）：我们能控的三块按影响排序是
**① 工具结果的每轮累计（49%）→ ② 开发者指令（28%）→ ③ 快照（11%）**。
①已经有局部上限（章程正文 4000 字符），但**分数线/计划那几条还没有**——多查几次就会线性堆。
②是常驻成本，任何一轮都要付。

## 五、没做 / 留给下一环

1. **B7 的主体没做**：16 场景×3 次评估、提示词体积与 MCP 调用量测量、compaction 后恢复、
   能力发布口径。这些是任务书正文，本报告不覆盖。
2. **经验性内容还是空的**：`planner_experience` 这一档在证据政策里已经存在，但**没有内容**。
   run ⑤ 里那 8 条对比是**模型自己**按"给维度"的要求生成的，不是我们写下来的经验。
   从哪来（4.0 线的 200 条生产回捞 / 13 文件 live 基线 / 人工整理）需要设计侧定。
3. **只读工具集仍缺 `compare_entities`**：对比现在没有工具证据，只有解释。
4. **过程脚本没写**：技能仍是契约式（适用条件/停止条件/…），不是 `superpowers` 那种
   分阶段带用户走的流程；"逐步让用户理清思路"这条没实现。
5. **插件是 copy 进 codex 缓存的**：改技能要 `update_plugin_cachebuster.py` + `codex plugin add`
   重装，重启 agent 才生效。这条流程容易忘，已写进项目记忆。
