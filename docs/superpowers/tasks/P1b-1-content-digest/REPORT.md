---
task: P1b-1
status: DONE_WITH_CONCERNS
executor: deepseek
finished_at: 2026-09-13 19:15 +0800
---

# P1b-1 报告

## 一、结论

「数据版本」已从上游信封字段改为 Java 对 `ResponseDTO.data` 的内容摘要，假契约 `dataVersion` 字段已删，版本表键已改到 `(source_system, params_digest)`；单测与端到端全部通过。

**偏差**：验收第 6 条（步骤 4 真实上游稳定性）三种结局里落到第二种——**只有 1/3 个接口拿到非空真实数据并跑完「两次相同 + 换参数不同」两条**，另两个接口（`querySchoolMajorScoreLine`、`queryProgramByLimitNum`）在灰度环境取不到非空内容，**本项未验证**，详见第四节命令 6。

## 二、交付物

| 路径 | 字节数 | 说明 |
|---|---|---|
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/util/EvidenceContentDigest.java` | 7282 | 新增。响应内容摘要：对象键字典序、null 值键剔除、数组保原序、SHA-256 前 32 位 |
| `zhiyuan-server/src/test/java/com/ytell/zhiyuan/common/util/EvidenceContentDigestTest.java` | 4732 | 新增。确定性与判别性 5 例（任务书要求 4 例 + 1 例 null 键等价） |
| `zhiyuan-server/src/main/resources/db/migration/V15__evidence_source_version_params.sql` | 1490 | 新增。版本表键改 `(source_system, params_digest)`，旧数据不迁移 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/manager/gaotu/GaotuClient.java` | 17160 | 修改。`attachEvidence` 改取 `EvidenceContentDigest.digest(response.getData())` |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/gaotu/ResponseDTO.java` | 853 | 修改。删除 `dataVersion` 字段 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/EvidenceSourceVersionMapper.java` | 1774 | 修改。`upsert` 加 `paramsDigest`；新增 `selectBySourceAndParams` |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/EvidenceSourceVersionEntity.java` | 716 | 修改。去掉 `@TableId`（改复合键）、新增 `paramsDigest` |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerService.java` | 12339 | 修改。upsert 带 paramsDigest；`currentDataVersion(sourceSystem, paramsDigest)`；核验缓存键带 paramsDigest |
| `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerServiceTest.java` | 11906 | 修改。仅改 mock 桩的方法名/参数，断言一条未动 |
| `zhiyuan-server/scripts/evidence_fake_upstream.py` | 5924 | 修改。删掉伪造的 `dataVersion` 控制面，改 `dataNull` / `content` 控制 |
| `zhiyuan-server/scripts/evidence_p1a_acceptance.sh` | 11130 | 修改。步骤 4 改判据、步骤 6 改内容、新增步骤 11 键对照 |

`git diff --stat`：`8 files changed, 141 insertions(+), 59 deletions(-)`（另 3 个新增文件未跟踪）。

## 三、实际改动的文件

```
 M zhiyuan-server/scripts/evidence_fake_upstream.py
 M zhiyuan-server/scripts/evidence_p1a_acceptance.sh
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/manager/gaotu/GaotuClient.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/EvidenceSourceVersionMapper.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/gaotu/ResponseDTO.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/EvidenceSourceVersionEntity.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerService.java
 M zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerServiceTest.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/util/EvidenceContentDigest.java
?? zhiyuan-server/src/main/resources/db/migration/V15__evidence_source_version_params.sql
?? zhiyuan-server/src/test/java/com/ytell/zhiyuan/common/util/EvidenceContentDigestTest.java
```

未 commit。`zhiyuan-agent/` 一行未动。`V14__evidence_ledger.sql`、`evidence_ledger` 列名、`currentDataVersion` 查不到返回 `""` 的行为、`GaotuService.java`、`GaotuClientDebugController.java` 均未动。

## 四、验收命令与原始输出

### 命令 1（验收 1）：摘要函数四条子项，逐条单独跑

```bash
for m in sameDataDigestsIdentically keyOrderDoesNotChangeDigest arrayOrderChangesDigest \
         nullDataIsNotSigned absentKeyAndNullValuedKeyDigestIdentically; do
  mvn -o test -Dtest="EvidenceContentDigestTest#$m" -DfailIfNoTests=false
done
```

```
### sameDataDigestsIdentically
[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.431 s - in com.ytell.zhiyuan.common.util.EvidenceContentDigestTest
### keyOrderDoesNotChangeDigest
[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.402 s - in com.ytell.zhiyuan.common.util.EvidenceContentDigestTest
### arrayOrderChangesDigest
[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.433 s - in com.ytell.zhiyuan.common.util.EvidenceContentDigestTest
### nullDataIsNotSigned
[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.377 s - in com.ytell.zhiyuan.common.util.EvidenceContentDigestTest
### absentKeyAndNullValuedKeyDigestIdentically
[INFO] Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.411 s - in com.ytell.zhiyuan.common.util.EvidenceContentDigestTest
```

**这四条不是空断言，已用变异验证「每条都能失败」**：把 `appendObject` 的 `TreeMap` 换成保持上游顺序的 `LinkedHashMap`、同时把 `appendArray` 改成对元素排序，重跑：

```
[ERROR] Tests run: 5, Failures: 2, Errors: 0, Skipped: 0, Time elapsed: 0.449 s <<< FAILURE! - in com.ytell.zhiyuan.common.util.EvidenceContentDigestTest
[ERROR] keyOrderDoesNotChangeDigest  Time elapsed: 0.048 s  <<< FAILURE!
[ERROR] arrayOrderChangesDigest  Time elapsed: 0.002 s  <<< FAILURE!
[ERROR]   EvidenceContentDigestTest.arrayOrderChangesDigest:87 expected: not equal but was: <ac47f8ccd32effd84a3f1a183117a3d9>
[ERROR]   EvidenceContentDigestTest.keyOrderDoesNotChangeDigest:79 expected: <f6837cfbc12b6f98153337d550aa4f8d> but was: <424163b98738bbdcb59a93561344652b>
```

变异已还原，还原后 `diff` 为空、重跑 `Tests run: 5, Failures: 0`。

### 命令 2（验收 2）：台账相关单测不回归

```bash
mvn -o test -Dtest=EvidenceParamsDigestTest,EvidenceLedgerServiceTest -DfailIfNoTests=false
```

```
[INFO] Tests run: 12, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.494 s - in com.ytell.zhiyuan.service.biz.EvidenceLedgerServiceTest
[INFO] Tests run: 6, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.005 s - in com.ytell.zhiyuan.common.util.EvidenceParamsDigestTest
[INFO] Tests run: 18, Failures: 0, Errors: 0, Skipped: 0
[INFO] BUILD SUCCESS
```

### 命令 3（验收 3）：Java 全量

```bash
mvn -o test
```

```
[WARNING] Tests run: 713, Failures: 0, Errors: 0, Skipped: 5
[INFO] BUILD SUCCESS
```

### 命令 4（验收 4）：端到端（按陷阱 4 调整过的脚本）

```bash
bash scripts/evidence_p1a_acceptance.sh ; echo "exit=$?"
```

```
exit=0
```

关键判据（原始响应片段）：

```
## 4. 响应 data 缺失 → 不签发（对照：data 存在时必须签发）
--- 原始响应 ---
{"code":0,"msg":"ok","data":null,"evidence":null}
调用前台账行数 = 3
调用后台账行数 = 3
未产生新记录   = true
恢复 data 后再调用，台账行数 = 4
对照：data 存在时必须产生记录 = true

## 5. 四态核验：valid
{"data":{"results":{"ev_01M2D7FCV1JS9M9WT1WKG5DSD1":{"status":"valid",...,"dataVersion":"012003c0771e06bdd6303bec0dafc3a2",...}}}

## 6. 四态核验：stale（上游内容变了）
{"ok": true, "scoreLineMinScore": "620"}
旧记录与新记录一起核验：
{"data":{"results":{"ev_01M2D7FCV1JS9M9WT1WKG5DSD1":{"status":"stale",...,"dataVersion":"012003c0771e06bdd6303bec0dafc3a2",...},"ev_01M2D7FCZFMMRS1BQF9HBKSTAQ":{"status":"valid",...,"dataVersion":"de005c21acb19adf0036a2f967bebaab",...}}}}
--- 对照：删掉 ev_01M2D7FCV1JS9M9WT1WKG5DSD1 之后必须返回 unknown ---
{"status":"unknown",...}
```

即：`data` 为 null 不签发（且对照证明 data 存在时必然签发）；内容从 612 变 620 后旧记录 `stale`、新记录 `valid` 且 `dataVersion` 确实变了（`012003c0…` → `de005c21…`）。

### 命令 5（验收 5）：版本表键的对照

```bash
mysql_exec "SELECT source_system, params_digest, data_version FROM evidence_source_version ORDER BY params_digest;"
verify "[\"${IDA}\",\"${IDB}\"]"
```

正向（键是复合键）：

```
gaotu.schoolMajorScoreLine  32da00b3fc17a4569cf1e37bf58be2eb  012003c0771e06bdd6303bec0dafc3a2
gaotu.schoolMajorScoreLine  47605e6c06e210ebe40adce1ae7069d3  012003c0771e06bdd6303bec0dafc3a2
gaotu.schoolMajorScoreLine  d7e9bea1ad3d3ca100a2b58f95dde4e4  de005c21acb19adf0036a2f967bebaab
--- 核验：后签的 B 不得让先签的 A 失效 ---
{"data":{"results":{"ev_01M2D7FDFFNRSE200R9QXFRDTJ":{"status":"valid","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"de005c21acb19adf0036a2f967bebaab",...},
                  "ev_01M2D7FDJAS6EPJE4VSPCHECC0":{"status":"valid","paramsDigest":"32da00b3fc17a4569cf1e37bf58be2eb","dataVersion":"012003c0771e06bdd6303bec0dafc3a2",...}}}}
```

两条 `paramsDigest` 不同 = `true`，两条 `dataVersion` 不同 = `true`，两条都 `valid`。

**对照（把键退回按 source_system 单行）**：把 `selectBySourceAndParams` 的 WHERE 子句临时改成忽略 `params_digest`（`WHERE source_system = #{sourceSystem} ORDER BY observed_at DESC LIMIT 1`），重新打包后跑同一段：

```
两条 paramsDigest 不同 = true
两条 dataVersion 不同   = true
{"data":{"results":{"ev_01M2D7GHZ9664SMHXG5752RKF4":{"status":"stale","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"de005c21acb19adf0036a2f967bebaab",...},
                  "ev_01M2D7GJ23RJEWNXNF0MKGYRX8":{"status":"valid","paramsDigest":"32da00b3fc17a4569cf1e37bf58be2eb","dataVersion":"012003c0771e06bdd6303bec0dafc3a2",...}}}}
```

先签的那条由 `valid` 变成 `stale`——键确实在起作用，且对照方向正确。变异已还原（`diff` 为空）并重新打包。

### 命令 6（验收 6 / 步骤 4）：真实上游，三种结局

对三个接口各做「同参数连调两次」+「换一个参数对照」。**未使用 `evidence_fake_upstream.py`**，全部打 `https://www.gaotuzhiyuan.com`（`application-local.yml` 的本地档本就指向它，`evn: grayTest`）。

**接口 1 `batchListByPolicy`：✅ 拿到非空真实数据，两条都跑通**

```bash
GET /gaotu-assistant-bot/inner/gaotu/batch/info?areaId=330000&prepareType=VOLUNTEER&subject=N&tenantId=7&chatSessionId=42&threadId=thread-1
```

```
第 1 次原始响应: {"code":0,"msg":"ok","data":{"year":null,"baseYear":null,"converYear":null,"area":{"key":"330000","data":"浙江"},"batchList":[{"id":"17999086548836864","year":"2027","batch":"17","batchTitle":"第一段","score":"494.0000","pos":184816,"subject":{"code":"N","desc":"综合"},"level":{"key":"01","data":null}},{"id":"17999086550278656","year":"2027","batch":"18","batchTitle":"第二段","score":"266.0000","pos":292753,"subject":{"code":"N","desc":"综合"},"level":{"key":"02","data":null}}],"type":null},"evidence":[{"...","dataVersion":"fc7bd2c8d3cd6dad653afc03d4c7b40a","paramsDigest":"5c0e803deaefc0e3ee3be13497f84de9",...}]}
第一次摘要: fc7bd2c8d3cd6dad653afc03d4c7b40a
第二次摘要: fc7bd2c8d3cd6dad653afc03d4c7b40a      → 两次相同 = true
对照(areaId=310000)摘要: 4a7877443bc49de9f75b848cd4634f5b   → 摘要变化 = true
```

同一接口 `subject=WL` / `subject=LS`（`batchList` 为空数组，`area.key` 仍随 areaId 变）：两次摘要均 `46d37eec0b89b02bfd9091993f73d02d` 相同，对照（areaId 330000→310000）摘要 `39b038a699ed033e6a9ddbe1c771c8de` 不同 —— 两条也都成立。

**接口 2 `querySchoolMajorScoreLine`：❌ 本项未验证（拿不到非空数据）**

试过 3 组参数，上游一律返回 `data: []`：

```
B1 {"areaId":"330000","batch":"本科批","majorId":"major-cs","schoolId":"school-1","year":2025,"subjectType":"物理类"}
   原始响应: {"code":0,"msg":"ok","data":[],"evidence":[{...,"dataVersion":"4f53cda18c2baa0c0354bb5f9a3ecbe5","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4",...}]}
   两次摘要相同 = true；对照(year 2025→2024)摘要 = 4f53cda18c2baa0c0354bb5f9a3ecbe5 → 摘要变化 = false
B2 {"areaId":"330000","batch":"本科批","majorId":"1001","schoolId":"1","year":2025,"subjectType":"物理类"}
   同样 data:[]，两次相同 = true；对照摘要变化 = false
B3 {"areaId":"330000","batch":"本科批","year":2025,"subjectType":"物理类"}
   原始响应: {"code":-9,"msg":"学校id不能为空","data":null,"evidence":null} → 不签发
```

`4f53cda18c2baa0c0354bb5f9a3ecbe5` 是空数组 `[]` 的摘要。**空响应两次相同，不能证明非空响应也相同**；对照（换 year）摘要不变，正是因为内容是空数组——这条对照在空数据上不具备判别力，因此本接口**未验证**。

**接口 3 `queryProgramByLimitNum`：❌ 本项未验证（响应里没有任何随参数变化的数据）**

```
C1 {"prepareType":"VOLUNTEER","subjectType":"N","score":494,"subjects":"N","areaId":"330000","batch":"17","recordNumLimit":10}
   原始响应: {"code":0,"msg":"ok","data":[{"volunteerLevel":"SPRINT","records":[]},{"volunteerLevel":"SAFE","records":[]},{"volunteerLevel":"PROTECT","records":[]}],"evidence":[{...,"dataVersion":"cc3b887e58105033952746a0821c3c09",...}]}
   两次摘要相同 = true；对照(score 494→480)摘要 = cc3b887e58105033952746a0821c3c09 → 摘要变化 = false
C2 {"prepareType":"VOLUNTEER","subjectType":"WL","score":620,"subjects":"WL","areaId":"330000","batch":"17","recordNumLimit":10}
   原始响应 data:[]，两次摘要 = 4f53cda18c2baa0c0354bb5f9a3ecbe5 相同；对照(score 620→600)摘要变化 = false
```

C1 的 `data` 形状非空但三个分档的 `records` 全为空数组，换 score 内容不变、摘要自然不变。**未验证**。

> 说明：步骤 4 对「摘要函数本身是否确定性」另有独立证据——命令 1 的变异验证与命令 5 的键对照都在用同一套摘要机制；上面两处「未验证」针对的是**这两个接口的真实上游响应是否稳定**，与摘要函数无关，两者是不同的断言。

## 五、与已知失败基线的对照

| 失败用例 | 在基线内？ | 说明 |
|---|---|---|
| 无 | — | `mvn -o test`：`Tests run: 713, Failures: 0, Errors: 0, Skipped: 5` |

Java 侧基线与任务书一致（`708, Failures: 0, Errors: 0, Skipped: 5`），当前 713 = 708 + 本次新增 5 例，**无任何 Failures / Errors**。任务书提到的 Python 侧基线（`2 failed, 1714 passed, 34 skipped`）本任务不涉及，未跑。

## 六、偏离任务书之处

1. **新增了 `canonical(Object)` 公开方法**（任务书只要求「新增一个工具方法」算摘要）。理由：与同包的 `EvidenceParamsDigest.canonical` 保持一致的排查手段，且测试可直接断言规范形式。
2. **`EvidenceLedgerService.verifyOne` 的批量核验缓存键一并加了 `paramsDigest`**（任务书未提）。这是步骤 3 的必要后果：缓存原本按 `sourceSystem` 汇总，键改到「来源+参数」后若不同参数共用缓存，同一批里第二条记录会拿到第一条的当前版本，键改动会被缓存架空。缓存键改成 `sourceSystem + " " + paramsDigest`。
3. **`evidence_fake_upstream.py` 的改动比「调整」更大**：删掉了 `/__control/version` 与 `payload["dataVersion"]` 注入。理由：该替身此前在伪造一个**不存在的上游契约**，P1a 的误判正源于此；留着它会让本次端到端在假契约上再次通过。改为 `/__control/data`（data 置 null/恢复）与 `/__control/content`（改内容）两个控制面。
4. **验收 5 的对照另跑了一次**（临时把 `selectBySourceAndParams` 的 WHERE 改成忽略 `params_digest`、重新打包、跑完还原、重新打包）。任务书允许「新增到脚本里，或单独跑」；因该对照需要改动生产代码，无法在脚本内完成，故单独跑并把原始输出并入报告。
5. **验收 1 多写了第 5 例** `absentKeyAndNullValuedKeyDigestIdentically`（任务书要求 4 条，此为额外一条，用于把「null 值键剔除」这条约定固定下来）。
6. **任务书第四节写的 `bash scripts/codex-local-infra.sh start` 不存在**（`scripts/` 下无此文件）。未执行该命令；MySQL/Redis 容器此前已由 T006 起好并 `healthy`，直接使用。验收命令 4 的其余部分原样执行。
7. 顺带改了两处**因本次改动而失真的注释**：`SOURCE_GAOTU_*` 上方的「按来源分别比对」改为「按来源 + 查询参数分别比对」，`sign()` 里「让调用方走已有的 `dataVersion_missing` 降级路径」改为「调用方按『证据不可用』降级」（前者引用的路径已不存在）。

## 七、未做的事

- 步骤 4 中接口 2、接口 3 的「真实上游内容稳定性」**未验证**（原因见第四节命令 6；属于任务书列明的第二种结局，不是遗漏）。
- 未跑 Python 侧测试（任务书明确本任务不涉及）。

## 八、观察到的异常现象（只列事实）

1. `batch/info` 传中文 `subject` 时，本地 Tomcat 直接返回 HTTP 400 的 HTML 页面（未到上游）：

```
<!doctype html><html lang="en"><head><title>HTTP Status 400 – Bad Request</title>...</head><body><h1>HTTP Status 400 – Bad Request</h1></body></html>
```

2. `batch/info` 的 `subject` 期望的是一枚上游枚举 `com.xiaowo.ci.ci.enums.SubjectType`，非枚举值一律被拒。试过 `1` / `physics` / `PHYSICS` / `PHYSIC` / `物理` / `物理类`，错误原文逐字相同（仅传入值不同）：

```
{"code":-3,"msg":"参数：[subject]的传入值：[1]与预期的字段类型：[com.xiaowo.ci.ci.enums.SubjectType]不匹配","data":null,"evidence":null}
```

`prepareType` 同理（`com.xiaowo.ci.ci.enumeration.PrepareType`）。可用的 `subject` 取值来自本仓 `CreateSessionReq.SubjectType` 的注释（`WL、LS、N`），据此才调通。

3. **任务书第二节与设计笔记称 `batchListByPolicy` 在灰度环境「四组省份/批次组合都返回 `batchList: []`」——本次实测在 `areaId=330000&prepareType=VOLUNTEER&subject=N` 下拿到了非空 `batchList`（两条真实记录）**，见第四节命令 6。原结论对当时试过的参数成立，但不是该接口的普遍行为。

4. `queryProgramByLimitNum` 的 `subjects` 在本仓 Python 侧声明为 **`str`**（`app/util/internal_client.py:1665`）。首次试探时按数组传（`["物理","化学"]`），上游返回：

```
{"data":null,"code":-1,"msg":"系统错误"}
```

改为字符串后返回 200。

5. 用 `git status --short` 观察：本任务开始时 `zhiyuan-server` 与 `zhiyuan-agent` 下另有多份他人未提交改动（T005/T006/T007/P1a）；报告落盘时这些已不在工作树中（已被提交）。本任务只改动了第三节列出的 11 个路径。
