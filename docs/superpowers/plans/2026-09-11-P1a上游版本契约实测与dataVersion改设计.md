# P1a 上游版本契约实测：`dataVersion` 不存在，改用内容摘要

> 日期：2026-09-11
> 起因：`docs/superpowers/tasks/P1a-evidence-ledger/REVIEW.md` 第四节第 1、3 条
> 影响：`2026-09-10-P1权威证据台账设计.md` 4.2 / 4.3 / 第八章；P1b 的前置
> 结论：**P1a 的 `dataVersion` 契约实测为假。** 版本改由 Java 侧按响应内容摘要自定义，顺带把版本表的键修正到正确粒度。

---

## 一、为什么要实测

P1a 把"上游数据版本"定义为响应包上的 `dataVersion` 字段，`data_version` 列设 `NOT NULL`，取不到就不签发。四个上游 DTO 原本都没有版本字段，验收用的是会返回该字段的替身（`zhiyuan-server/scripts/evidence_fake_upstream.py`）。

复核时把这条列为 P1b 的头号前置，理由是：**如果真实上游不返回 `dataVersion`，按 fail-closed 逻辑生产上一条证据都签不出来**，P1b/P1c 接上之后所有 `fact` 输出会整轮 fail closed。替身不可能回答这个问题——它返回什么是我们自己写的。

原以为上游从验收环境不可达（替身脚本的文件头就是这么写的）。实测发现可达：`https://www.gaotuzhiyuan.com` 返回 200，且 `application-local.yml:88-89` 本来就把本地开发档指向它、用 `traffic-env: grayTest` 路由到灰度环境。也就是说，调它一次就是本地开发档的正常行为，不是额外授权的动作。

## 二、实测方法（可重复）

一次只读 GET，走本地开发档同款配置，匿名接口（路径里的 `anno`），无凭据：

```bash
curl -s -H 'traffic-env: grayTest' -H 'content-type: application/json' \
  'https://www.gaotuzhiyuan.com/hl-wish/ci/h5/batchData/anno/batchListByPolicy?areaId=330000&prepareType=VOLUNTEER&subject=L'
```

`subject` 取值先探错再取对：传 `1` 时上游报 `参数：[subject]的传入值：[1]与预期的字段类型：[com.xiaowo.ci.ci.enums.SubjectType]不匹配`，于是按 `ChatSessionBizService.java:503` 的 `"L"` / `"W"` 口径重试，成功。

## 三、实测结果

### 成功路径的信封原文

```json
{"code":0,"data":{"area":{"key":"330000","data":"浙江"},"batchList":[]},"msg":"ok","timestamp":1789091573559,"errorMsg":"","isSuccess":true}
```

### 失败路径的信封原文

```json
{"code":-3,"msg":"参数：[subject]的传入值：[1]与预期的字段类型：[com.xiaowo.ci.ci.enums.SubjectType]不匹配","path":"/h5/batchData/anno/batchListByPolicy","timestamp":1789091573852,"errorMsg":"Failed to convert value of type 'java.lang…"}
```

### 三条结论

1. **信封里没有 `dataVersion`。** 成功路径键集 `{code, data, msg, timestamp, errorMsg, isSuccess}`，失败路径键集 `{code, msg, path, timestamp, errorMsg, isSuccess}`。两条路径都验过，不是抽样。
2. **`timestamp` 每次调用都不同**（三次连续调用 `…573559` / `…573722` / `…574043`），它是响应时刻，不是数据版本。
3. **`data` 子对象在多次调用间逐字节相同**（`timestamp` 变而 `data` 不变）。这一条后面要用。

### 附带发现：我们在丢弃上游的信号

`ResponseDTO` 只建模 `code` / `msg` / `data`（P1a 之后又加了 `dataVersion` / `evidence`）。上游实际还返回 `errorMsg`、`isSuccess`、`path`、`timestamp` 四个字段，fastjson 默认忽略未知字段，于是全部被静默丢掉。

其中 `isSuccess` 是上游自己给的成功判别，`errorMsg` 是比 `msg` 更细的错误原文。我们现在靠 `code` 自行判断。不在本次范围内改，但记一笔：**这是一处"上游明明说了、我们没听"的地方。**

## 四、两个看起来能用的候选，都不能用

### 候选一：拿 `timestamp` 当版本 → 永久 fail-closed

`timestamp` 每次调用都变。按 4.3 的判定逻辑，任何一条已签发记录在下一次同源查询之后都会与"当前版本"不一致，于是**全部立刻变成 `stale`**。`stale` 触发重查，重查再次刷新 `timestamp`，上一条记录又 `stale`。

结果：证据永远引用不了，每轮都走 fail-closed。方向是安全的，但系统等于没有证据机制。

### 候选二：拿响应里的 `year` 当版本 → fail-open，更糟

`QuerySchoolMajorScoreLineRes` 有 `year`，`BatchDataResponseDTO` 有 `year` / `baseYear` / `converYear`，看着像数据年份。

但 `QuerySchoolMajorScoreLineReq` 里 **`year` 是请求参数**。它已经进了 `paramsDigest`。查 2025 年的数据永远返回 2025，所以对固定参数而言这个"版本"**永远不变**，什么都不会变成 `stale`。

这比候选一危险得多：候选一是过度保守，候选二是**假装在做失效检测而实际恒为 `valid`**——上游数据真的更新了也检测不出来。它会让四态里最重要的那一态（`stale`：当时正确、现已失效）在定义上不可达，而台账看起来一切正常。这正是规则 4 第一问要挡的东西：**想不出这条指标失败长什么样，它就不是指标。**

## 五、决定：版本 = Java 对 `data` 子对象算的内容摘要

### 这不是新发明，是本仓已有的约定

`PlanningStateService.java:5668`：

```java
req.setDataVersion(snapshot.getSourceDataHash());
```

`VolunteerSourceDataSyncService.java:95` 的 `sourceDataHash` 就是 `buildDigest(dataJson)`，而 `buildDigest`（`:192-200`）是 SHA-256 十六进制串——与 `EvidenceParamsDigest` 同一族。

**这个仓库在数据新鲜度这条线上，早就用"源数据内容哈希"当数据版本了。** P1a 引入 `dataVersion` 字段契约，反而是偏离了既有约定。改回来不是妥协，是对齐。

### 具体口径

- **算什么**：`ResponseDTO.data` 子对象的规范化 JSON 序列化（键排序，数组保持上游给的顺序），SHA-256，取前 32 位十六进制——与 `EvidenceParamsDigest` 同一约定，便于人眼在日志里区分两个摘要。
- **不算什么**：**信封一律排除。** 第三节第 2 条已经证明 `timestamp` 每次都变，把信封算进去就退化成候选一，永久 fail-closed。**这是本次最重要的实现约束，且它有实测依据，不是凭直觉的洁癖。**
- **取不到怎么办**：`data` 为 null 或不可序列化 → 不签发。与现在 `dataVersion` 为空时的行为一致，fail-closed 方向不变。

### 改动点很小

`GaotuClient.attachEvidence()` 现在是：

```java
EvidenceSignRequest.query(sourceSystem, response.getDataVersion(), toParams(request), scope)
```

把第二个参数从 `response.getDataVersion()` 换成对 `response.getData()` 算出来的摘要即可。`ResponseDTO.dataVersion` 字段随之删除——它建模的是一个不存在的上游契约，留着会误导下一个人。

## 六、顺带修好版本表的键

复核第四节第 3 条指出 `evidence_source_version` 按 `source_system` 单行全局，同源不同参数会互相挤掉版本。

换成内容摘要之后，这个问题不是"顺带也能修"，而是**必须修**：内容摘要天然是按参数分的（不同参数当然是不同内容），继续按来源单行就等于让所有参数共用一个格子，后一次查询必然挤掉前一次，全体立刻 `stale`——又退回候选一。

所以键改成 `(source_system, params_digest)`，存该参数组合最近一次观测到的内容摘要与观测时刻。

## 七、四态重新推导

| 状态 | 判定 | 含义 |
|---|---|---|
| `valid` | 记录的内容摘要 == 该 `(来源, 参数)` 最近观测到的摘要，且未过 `expiresAt` | 可引用 |
| `stale` | 最近观测到的摘要与记录不同 | **同样的查询现在给出不同数据** → 当时正确、现已失效 → 必须重查 |
| `expired` | 已过 `expiresAt` | 新鲜度不明 → 必须重查 |
| `unknown` | 无此记录 / scope 不匹配 | 从未成立 → 伪造或 bug |

`stale` 的语义比原设计**更强也更准**：原设计是"上游宣称的版本号变了"，现在是"同样的查询确实返回了不同的数据"。前者依赖上游诚实报版本（而它根本不报），后者是我们自己观测到的事实。

`valid` 与 `expired` 的分工不变：摘要比对回答"变没变"，`expiresAt` 回答"多久没看了"。两个问题互相独立，所以两个字段都要留。

## 八、P1b 必须先验的一条风险

**如果某个接口的 `data` 里含有逐次调用都变的内容**（服务端时间戳、无序集合的随机序、分页游标），摘要会无谓翻动，该来源的证据全部永久 `stale`——又是候选一。

我在 `batchListByPolicy` 上验过 `data` 稳定，但那次 `batchList` 是空的（灰度环境下四个省份/批次组合都返回 0 条），**空响应相同不能证明非空响应也相同**。另两个接口（`querySchoolMajorScoreLine`、`queryProgramByLimitNum`）需要真实的院校/专业 ID 才能调通，我没有。

> **勘误（2026-09-13，P1b-1 实测推翻）**：上面那句"灰度环境下四个省份/批次组合都返回 0 条"，我把它写成了这个接口的**普遍行为**，这是过度概括。P1b-1 用
> `areaId=330000&prepareType=VOLUNTEER&subject=N` 拿到了**非空 `batchList`（两条真实记录）**，并在真实非空数据上把"两次相同 + 换 areaId 不同"两条对照都跑通了。
>
> 关键在 `subject` 这个参数：它要的是上游枚举 `SubjectType`，合法值是 `WL` / `LS` / `N`，而我当初试的是 `L`、`1` 之类，**全部被上游参数校验拒掉或落到空集**。所以我记下的"都返回空"其实是"我没调对参数"。
>
> **教训不是"多试几组参数"，是措辞**：我把「我试的这几次是空的」写成了「这个接口是空的」。前者是观测，后者是关于外部世界的断言，而我没有做够支撑后者的实验。任务书里凡是写「上游会返回 X」「上游不返回 X」，都要带上**试过哪些参数**这个限定，否则下一个人会拿它当已知事实用——P1b-1 的任务书第二节就是这么被我写坏的。
>
> 这一条的实质影响是**正面的**：三个接口里唯一拿到真实非空数据、唯一真正验证了版本稳定性的，就是这个被我判过死刑的接口。

所以这条留给 P1b，并且写成必须有对照的验收条：

- 三个接口各用**同一组参数连调两次**，`data` 摘要必须相同。
- 对照：**故意换一个参数**（比如 `year` 从 2025 改 2024），摘要必须不同。没有这条对照，"两次相同"也可能是因为摘要算法坏了恒定返回同一个值——这正是 `mcpCalls` 恒为 `[]` 那次的翻版。
- 若某接口两次不同，**先定位是哪个字段在动**（贴原始 diff），再决定是从摘要里排除该字段还是换机制。不要直接排除，排除掉的可能正是真实变化。

## 九、这次复盘留下的方法论

设计文档里写"上游数据版本"的时候，我没问过上游到底给不给。实现方按文档做了，在替身上验收全绿，九步对照一条不落——**验收做得对，但验的是一个我编出来的契约**。

替身能证明代码按设计工作，不能证明设计与外部世界相符。两者之间的缝隙，只有真实调用能填。这次的代价还算小（一次 GET 就问清楚了），因为替身脚本的文件头老老实实写了"真实上游不可达，所以用替身"——那句话既是坦白也是路标，照着它走就找到了要验的东西。

推论写进任务协议：**凡是任务书里出现"上游会返回 X"这类关于外部系统的断言，派发前必须注明它是实测过的还是假设的。** 假设的，就在验收里留一条"用真实调用确认 X"，而不是让替身替它作证。
