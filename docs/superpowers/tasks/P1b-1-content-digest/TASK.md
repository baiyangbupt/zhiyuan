# P1b-1：把证据的"数据版本"从上游字段改成 `data` 内容摘要

> 指派：DeepSeek
> 来源：`docs/superpowers/plans/2026-09-11-P1a上游版本契约实测与dataVersion改设计.md`（全文）；`docs/superpowers/plans/2026-09-10-P1权威证据台账设计.md` 4.2 / 4.3 / 第八章
> 类型：代码改动（Java 为主）
> 协议：`docs/superpowers/tasks/README.md`

---

## 一、目标

P1a 把"上游数据版本"实现为响应信封上的 `dataVersion` 字段。**这个契约实测为假**——真实上游根本不返回该字段。照现状上生产，`EvidenceLedgerService.sign()` 会因 `dataVersion` 为空而永远返回 `null`，**一条证据都签不出来**。

本任务把版本的来源换成 **Java 自己对 `ResponseDTO.data` 子对象算的内容摘要**，并把版本表的键改到正确粒度。

一句话验收：**把 `GaotuClient` 的三个查询方法接到真实上游（不是替身）时，`evidence_ledger` 里能落出记录，且同参数两次调用的 `data_version` 相同、换一个参数后不同。**

---

## 二、背景（你的会话没有这些上下文）

`zhiyuan-server` 是志愿填报系统的 Java 后端，`zhiyuan-agent` 是 Python 侧的对话引擎。P1 要做的事是：**把"招生事实的证据"从 Agent 自己造，改成 Java 签发、Java 可复验**。

P1a（已完成并通过复核，见 `docs/superpowers/tasks/P1a-evidence-ledger/`）建好了台账：建表、参数摘要、ULID 签发、`valid`/`stale`/`expired`/`unknown` 四态核验。核验的核心逻辑是：**拿记录里的"数据版本"跟"当前观测到的数据版本"比，不一致就是 `stale`（当时正确、现已失效，必须重查）**。

问题出在"数据版本"从哪来。设计文档当时写的是"取上游响应包上的 `dataVersion` 字段"——**那是设计会话（我）假设的，没有实测**。P1a 的验收用的是一个会返回该字段的替身脚本，于是九步验收全绿，验的却是一个不存在的契约。

2026-09-11 实测了真实上游（一次只读匿名 GET，走本地开发档已配置的灰度环境）：

```
成功：{"code":0,"data":{"area":{"key":"330000","data":"浙江"},"batchList":[]},"msg":"ok","timestamp":1789091573559,"errorMsg":"","isSuccess":true}
失败：{"code":-3,"msg":"参数：[subject]…不匹配","path":"/h5/batchData/anno/batchListByPolicy","timestamp":1789091573852,"errorMsg":"…"}
```

**两条路径都没有 `dataVersion`。**

两个看起来能顶上的候选也都否掉了，理由写在设计笔记里，这里只给结论：
- `timestamp` 每次调用都变 → 所有证据立刻 `stale` → 永久 fail-closed，等于没有证据机制；
- `year` 是**请求参数**、已经在 `paramsDigest` 里 → 对固定参数永不变 → **`stale` 在定义上不可达**，上游数据真变了也检测不出来，而台账看起来一切正常。这个比前一个危险得多。

所以改成 Java 自己算内容摘要。**这不是新发明**——`PlanningStateService.java:5668` 早就在用 `snapshot.getSourceDataHash()` 当数据版本，`VolunteerSourceDataSyncService.java:95/:192-200` 的 `buildDigest()` 就是 SHA-256 十六进制串。改回来是对齐本仓既有约定。

---

## 三、已核实的环境事实（不要重新调查，直接用）

| 事实 | 值 |
|---|---|
| Java 工程根 | `/root/dev/zhiyuan/zhiyuan-server` |
| 构建命令 | `mvn -o test`（离线模式；P1a 用的就是这条，`Tests run: 708, Failures: 0, Errors: 0, Skipped: 5`） |
| 本地 MySQL/Redis | `bash scripts/codex-local-infra.sh start`（T006 已解除镜像源阻塞，容器可正常起） |
| 台账建表脚本 | `src/main/resources/db/migration/V14__evidence_ledger.sql` |
| 签发入口 | `GaotuClient.attachEvidence()`，`src/main/java/com/ytell/zhiyuan/manager/gaotu/GaotuClient.java:333-342` |
| 签发实现 | `EvidenceLedgerService.sign()`，`:75` 起；版本空则返回 `null` 在 `:80-83` |
| 核验取当前版本 | `EvidenceLedgerService.currentDataVersion(String)`，`:219`；调用点 `:183` |
| 版本表 upsert 调用点 | `EvidenceLedgerService.java:114`（`evidenceSourceVersionMapper.upsert(sourceSystem, dataVersion, observedAt)`） |
| `paramsDigest` 算法 | `EvidenceParamsDigest.digest()`：键字典序 → 值转字符串 → 空值剔除 → UTF-8 → SHA-256 → 前 32 位十六进制 |
| 三个签发点 | `GaotuClient.java:150`（batchList）、`:302`（programByLimitNum）、`:325`（schoolMajorScoreLine） |
| 三个上游路径 | `/hl-wish/ci/h5/batchData/anno/batchListByPolicy`、`/hl-wish/ci/ci_feign/volunteer/queryProgramByLimitNum`、`/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine` |
| 真实上游地址 | `https://www.gaotuzhiyuan.com`，可达（返回 200）。`application-local.yml:88-89` 本来就把本地开发档指向它，配 `traffic-env: grayTest` 路由灰度 |
| 灰度环境的数据状况 | **`batchListByPolicy` 在试过的四组省份/批次组合下都返回 `batchList: []`。** 这一条很重要，见步骤 4 |
| 替身脚本 | `zhiyuan-server/scripts/evidence_fake_upstream.py`（P1a 验收用）。**本任务的步骤 4 明确禁止用它** |
| P1a 端到端脚本 | `zhiyuan-server/scripts/evidence_p1a_acceptance.sh`，十步，`exit=0` 为过 |

---

## 四、步骤

### 步骤 1：把版本改成 `data` 的内容摘要

新增一个工具方法（放在 `EvidenceParamsDigest` 旁边或同包内新建一个类，你定），对 `ResponseDTO.data` 算摘要：

- **算什么**：`data` 子对象的规范化 JSON 序列化——**键按字典序排序，数组保持上游给的原顺序**（数组顺序是数据的一部分，排序会抹掉真实变化）→ UTF-8 → SHA-256 → **取前 32 位十六进制**，与 `paramsDigest` 同一约定，便于人眼在日志里区分两个摘要。
- **不算什么**：**信封一律排除**。`code` / `msg` / `timestamp` / `errorMsg` / `isSuccess` / `path` 一个都不进摘要。

> **这是本任务最重要的一条约束，且它有实测依据，不是洁癖。** 实测确认 `timestamp` 每次调用都变（三次连续：`…573559` / `…573722` / `…574043`），把信封算进去就退化成上面否掉的候选一，永久 fail-closed。

- **`data` 为 `null` 或序列化失败**：**不签发**，返回 `null`。方向与现在 `dataVersion` 为空时一致，fail-closed 不变。

然后改 `GaotuClient.attachEvidence()`（`:337-338`）：

```java
// 现在
EvidenceSignRequest.query(sourceSystem, response.getDataVersion(), toParams(request), scope)
// 改成：第二个参数换成对 response.getData() 算出来的摘要
```

### 步骤 2：删掉 `ResponseDTO.dataVersion`

`src/main/java/com/ytell/zhiyuan/model/dto/gaotu/ResponseDTO.java:27`。它建模的是一个**不存在的上游契约**，留着会误导下一个人。

**设计会话已经替你 grep 过了**（`grep -rn "etDataVersion(" --include=*.java src/`），结论：

> **`ResponseDTO.getDataVersion()` 全仓只有一个调用方：`GaotuClient.java:338`**，正是步骤 1 要改的那一行。测试代码零引用。**改完步骤 1，这个字段就是死的，直接删。**

`ResponseDTO.evidence` 字段**保留**，它是对的。

> ### ⚠️ 同名陷阱：本仓有五个互不相干的 `dataVersion`
>
> **千万不要全局搜 `dataVersion` 然后批量改。** 逐个确认你动的是哪一个：
>
> | 家族 | 位置 | 处置 |
> |---|---|---|
> | ① 上游响应包（假契约） | `ResponseDTO` | **删**——本步骤的目标 |
> | ② 证据台账自己的 | `EvidenceLedgerService` / `EvidenceSignRequest` / `EvidenceLedgerEntity` / `EvidenceVerifyItemDTO` / `ConversationEvidenceDTO` | **保留，列名变量名都不要改**。语义"这条记录当时的数据版本"没变，只是取值来源变了 |
> | ③ 会话附加数据的版本号 | `ChatSessionExtraData` / `ChatSessionExtraDataVo`（`ChatSessionBizService:765/768/780/799`） | **完全无关，别碰。它是 `int`**，`setDataVersion(-1)` / `setDataVersion(0)` |
> | ④ 规划态的数据新鲜度 | `PlanningStateService` / `DataFreshnessStateDTO` / `DataFreshnessCheckReq` | **别碰。** 但值得读一眼 `PlanningStateService.java:5668`——`req.setDataVersion(snapshot.getSourceDataHash())` 就是本任务要照搬的既有做法 |
> | ⑤ 招生事实上的 | `AdmissionFactDTO` | **别碰。** 它是 Java→Agent 的另一条契约，跟 `ResponseDTO` 那个不是一回事（设计会话在本次实测中一度把这两个当成同一个，查了调用链才发现不是） |
>
> 改列名会把改动面从"一个字段"扩大到"一张表 + 一组测试"，而且会撞上家族 ②。


### 步骤 3：版本表的键改成 `(source_system, params_digest)`

新建 `V15__evidence_source_version_params.sql`（**不要改 V14**，它已经在本地库里执行过了，改历史 migration 会让已有环境校验失败）：

- `evidence_source_version` 主键从 `(source_system)` 改成 `(source_system, params_digest)`，新增 `params_digest CHAR(32) NOT NULL`。
- 已有数据怎么办：这张表只是"最近一次观测到的版本"的缓存，**直接 `TRUNCATE` 或删表重建都可以**，不需要迁移数据。但请在 migration 里写一行注释说明为什么可以丢。

代码侧两处跟着改：
- `EvidenceLedgerService.java:114` 的 `upsert(...)` 带上 `paramsDigest`（它在 `:82` 附近已经算好了，直接用）；
- `currentDataVersion(String)`（`:219`）改成 `currentDataVersion(String sourceSystem, String paramsDigest)`，调用点 `:183` 传 `entity.getParamsDigest()`。

**`currentDataVersion` 查不到记录时返回 `""` 的行为不要改。** 那是 P1a 有意写的 fail-closed：查不到 → 记录永远比不中 → 落到 `stale` 而不是 `valid`，"不知道"倒向"必须重查"。

> 这两处签名变了，`EvidenceLedgerServiceTest`（12 个用例）会跟着编不过。**改它是本任务的一部分**，但只改到能编过为止——**不要削弱任何断言**。特别是 `:186` 那条 `stale`/`valid` 的判定，以及 `:78/88/177` 对 `"2026-06-v17"` 的断言（那是测试自己造的版本串，与上游无关，不受本次改动影响）。

> 为什么这一步是**必须**而不是"顺手"：内容摘要天然按参数分（不同参数当然是不同内容）。继续按 `source_system` 单行，等于让所有参数共用一个格子，后一次查询必然挤掉前一次，全体立刻 `stale`——又退回被否掉的候选一。

### 步骤 4：用真实上游验响应内容的稳定性（**不要用替身**）

摘要机制有一个前提风险：**如果某个接口的 `data` 里含逐次调用都变的内容**（服务端时间戳、无序集合的随机序、分页游标），摘要会无谓翻动，该来源的证据全部永久 `stale`。

对三个接口各做：

1. **同一组参数连调两次，`data` 摘要必须相同。**
2. **对照：故意换一个参数**（比如 `year` 从 2025 改 2024），摘要必须不同。

> **第 2 条不是可选的。** 没有它，"两次相同"也可能是因为摘要算法坏了、恒定返回同一个值——这正是 `mcpCalls` 恒为 `[]` 那次的翻版（见 `README.md` 规则 4）。

**如果某接口两次不同**：先贴**原始 diff** 定位是哪个字段在动，再报告。**不要自行决定把该字段从摘要里排除**——排掉的可能正是真实的数据变化，这个判断归设计会话。

**关于灰度环境没有数据这件事，请如实处理：**

设计会话自己试过 `batchListByPolicy`，四组省份/批次组合都返回 `batchList: []`。**空响应两次相同，不能证明非空响应也相同。** 另两个接口需要真实的院校/专业 ID 才能调通。

所以这一步允许出现三种结局，**如实报哪一种**：

- **能拿到非空真实数据** → 跑完两条，贴原始输出。
- **拿不到非空数据** → 这一步报 `BLOCKED`，贴出你试过的**每一组参数和原始响应**，明确写"本项未验证"。**其余步骤照常完成，整体状态用 `DONE_WITH_CONCERNS`。**
- **只能验摘要函数本身**（用一次真实响应的留档，对同一份留档算两次）→ 可以做，但**必须写明这验的是"摘要函数是确定性的"，不是"上游响应是稳定的"**，两者是不同的断言。

**任何情况下都不要用 `evidence_fake_upstream.py` 来完成这一步。** 替身返回什么是我们自己写的，它不能替外部系统作证——P1a 就是这么错的，本任务的存在本身就是那次错误的代价。

---

## 五、陷阱

1. **`ResponseDTO.data` 的泛型是三种不同的形状。** `getBatchList` 是 `BatchDataResponseDTO`（对象），另两个是 `List<...>`（数组）。摘要函数要能吃下对象和数组两种，不要假设是 `Map`。
2. **JSON 序列化的默认行为会咬人。** fastjson 默认**不输出 null 值字段**。如果上游某次返回 `{"a":1,"b":null}`、另一次返回 `{"a":1}`，规范化后两者会算出同一个摘要——这是可接受的（语义上确实一样）；但要注意**不要开启会随环境变化的序列化特性**（比如按运行时字段顺序输出）。键必须显式排序。
3. **不要改 `EvidenceParamsDigest`。** 它算的是**请求参数**摘要，和本次的**响应内容**摘要是两回事。共用算法约定（SHA-256 前 32 位）是为了人眼好认，不是让你复用同一个方法去处理两种输入。
4. **`evidence_p1a_acceptance.sh` 会因为本次改动而失效。** 它的第 4 步靠替身的控制面把 `dataVersion` 置 null 来验"取不到版本就不签发"。改完之后"取不到版本"的含义变成"`data` 为 null"，脚本要相应调整。**调整它是本任务的一部分**，不是额外工作。
5. **`evidence_p1a_acceptance.sh:65` 把 MySQL 口令作为命令行参数传给 Spring Boot**，于是它在该进程存活期间对 `ps` 可见。本地开发环境可接受（口令是每次随机生成的），**不要求你修**，但如果你正好要大改这个脚本，顺手改成环境变量更好。

---

## 六、验收

按顺序执行，全部必须通过：

```bash
cd /root/dev/zhiyuan/zhiyuan-server

# 1. 新增单测：摘要函数的确定性与判别性
#    必须包含这四条，每条都要能失败：
#      a) 同一份 data 算两次 → 相同
#      b) 键序不同、内容相同的两份 data → 相同（证明排序生效）
#      c) 数组元素顺序不同 → 不同（证明没有误排数组）
#      d) data 为 null → 不签发
mvn -o test -Dtest=<你的新测试类> -DfailIfNoTests=false

# 2. 台账相关单测不回归
mvn -o test -Dtest=EvidenceParamsDigestTest,EvidenceLedgerServiceTest -DfailIfNoTests=false

# 3. Java 全量
mvn -o test

# 4. 端到端（按陷阱 4 调整过的脚本）
bash scripts/codex-local-infra.sh start
bash scripts/evidence_p1a_acceptance.sh ; echo "exit=$?"

# 5. 版本表键的对照（新增到脚本里，或单独跑）
#    同一 source_system、两组不同参数各签一条证据，
#    第二条签发后第一条必须仍是 valid。
#    对照：把键退回按 source_system 单行，第一条必然变 stale。
#    —— 这条对照证明"键确实起作用了"，没有它，"仍是 valid" 也可能
#       只是因为核验逻辑压根没跑。

# 6. 步骤 4 的真实上游实测（三种结局之一，如实报）
```

验收 1 的四条子项**逐条贴原始输出**，不要合并成一句"全部通过"。

### 已知失败基线（不是你造成的，不要去修）

Java 侧：`mvn -o test` 当前为 `Tests run: 708, Failures: 0, Errors: 0, Skipped: 5`，**无失败**。出现任何 `Failures` 或 `Errors` 都是本次引入的。

Python 侧本任务不涉及，无需跑。

---

## 七、边界：不要做这些

- **不要动 `zhiyuan-agent/`。** Agent 侧的三处断链是 P1b-2 的事，两边同时改会让复核无法定位问题。
- **不要动 `V14__evidence_ledger.sql`。** 新建 V15。
- **不要改 `evidence_ledger` 表的列名。** 见步骤 2 的理由。
- **不要动 `GaotuService.java`、`GaotuClientDebugController.java`。** 接会话上下文是 P1b-2 的事。
- **不要改 `currentDataVersion` 查不到时返回 `""` 的行为。**
- 不要"顺手"重构、格式化、改 import 顺序。
- **不要 commit。** 改完等 review。

---

## 八、报告

把报告写到：

```
/root/dev/zhiyuan/docs/superpowers/tasks/P1b-1-content-digest/REPORT.md
```

格式见 `docs/superpowers/tasks/_templates/REPORT.md`，逐节填写，不要增删小节。

要点：状态词只用 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`；验收命令贴**原始输出**；**不写修复建议、不写下一步、不写根因推测**。

步骤 4 如果没能拿到真实非空数据，**明确写出来**，不要用替身补位、也不要含糊带过。如实报"这项没验成"是本任务可接受的结局；用替身冒充真实验证不是。
