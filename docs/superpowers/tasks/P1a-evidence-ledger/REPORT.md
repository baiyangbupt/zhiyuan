---
task: P1a
status: DONE_WITH_CONCERNS
executor: deepseek
finished_at: 2026-09-11 07:25 +0800
---

# P1a 报告（权威证据台账，Java 侧）

## 一、结论

设计文档第七章 P1a 的六项内容全部落地并跑通：`evidence_ledger` 建表（Flyway V14）、`paramsDigest` 规范化工具方法、签发接入 `GaotuClient` 的 `ResponseDTO` 包装层（`getBatchList` / `queryProgramByLimitNum` / `querySchoolMajorScoreLine` 三处）、`POST /internal/evidence/verify` 批量接口、四态判定（`valid` / `stale` / `expired` / `unknown`）、`data_version` 的 `NOT NULL` 与「拿不到上游版本就不签发」。第八章 P1a 的四条验收逐条有原始输出（第四章命令 3）。

状态 `DONE_WITH_CONCERNS`：验收全过，但有几处实现判断需要评审确认，逐条列在第六章。其中最需要确认的一条是——**现有上游响应 DTO 里没有任何版本字段，本次实现把「上游数据版本」定义为响应包 `ResponseDTO` 上的 `dataVersion` 字段**；验收用的是能返回该字段的替身，真实上游是否返回同名字段，本环境无法证明（见第六章第 1 条）。

## 二、交付物

| 路径 | 字节数 | 说明 |
|---|---|---|
| `zhiyuan-server/src/main/resources/db/migration/V14__evidence_ledger.sql` | 1994 | 建表迁移：`evidence_ledger` + `evidence_source_version` |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/util/Ulid.java` | 1182 | `ev_` 后缀用的 ULID（48 位毫秒 + 80 位随机，Crockford Base32，26 字符） |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/util/EvidenceParamsDigest.java` | 6536 | paramsDigest 规范化 + SHA-256 前 32 位 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/EvidenceLedgerEntity.java` | 939 | 台账实体 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/EvidenceSourceVersionEntity.java` | 613 | 来源版本登记实体 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/EvidenceLedgerMapper.java` | 292 | |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/EvidenceSourceVersionMapper.java` | 948 | 含 `ON DUPLICATE KEY UPDATE` 的 upsert |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/evidence/EvidenceScope.java` | 995 | 归属范围（tenantId / chatSessionId / threadId） |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/evidence/EvidenceSignRequest.java` | 1452 | 签发输入 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/evidence/EvidenceVerifyReq.java` | 414 | 核验请求 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/evidence/EvidenceVerifyItemDTO.java` | 569 | 单条四态结果 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/evidence/EvidenceVerifyRes.java` | 327 | 核验响应 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerService.java` | 11898 | 签发 + 核验 |
| `zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/EvidenceLedgerController.java` | 1730 | `POST /internal/evidence/verify` |
| `zhiyuan-server/src/test/java/com/ytell/zhiyuan/common/util/EvidenceParamsDigestTest.java` | 3197 | 6 个用例 |
| `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerServiceTest.java` | 11615 | 12 个用例 |
| `zhiyuan-server/scripts/evidence_fake_upstream.py` | 4945 | 验收用上游替身（真实上游本环境不可达） |
| `zhiyuan-server/scripts/evidence_p1a_acceptance.sh` | 7849 | 端到端验收脚本，自起服务、自跑、自关 |
| `docs/superpowers/tasks/P1a-evidence-ledger/acceptance-transcript.txt` | 9403 | 命令 3 的原始输出留档 |
| `docs/superpowers/tasks/P1a-evidence-ledger/unit-tests-raw.log` | 15688 | 命令 1 的原始输出留档 |

修改的既有文件（字节数为改后大小）：`GaotuClient.java`（16806）、`ResponseDTO.java`（992）、`ConversationEvidenceDTO.java`（755）、`GaotuClientDebugController.java`（5682）、`WebConfig.java`（3030）、`application.yml`（844）。

## 三、实际改动的文件

`git status --short`（仓库根 `/root/dev/zhiyuan`，未经编辑）：

```
 M docker-compose.codex-local.yml
 M zhiyuan-agent/CLAUDE.md
 M zhiyuan-agent/app/engine/turn_trace.py
 M zhiyuan-agent/scripts/codex_semantic_smoke.py
 M zhiyuan-agent/tests/fixtures/mcp/semantic_readonly_server.py
 M zhiyuan-agent/tests/unit/test_semantic_readonly_server.py
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/config/WebConfig.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/manager/gaotu/GaotuClient.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/gaotu/ResponseDTO.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationEvidenceDTO.java
 M zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/GaotuClientDebugController.java
 M zhiyuan-server/src/main/resources/application.yml
?? docs/superpowers/tasks/P1a-evidence-ledger/
?? docs/superpowers/tasks/T005-mcp-execution/REPORT.md
?? docs/superpowers/tasks/T006-registry-unblock/
?? docs/superpowers/tasks/T007-agent-doc-accuracy/
?? zhiyuan-server/scripts/evidence_fake_upstream.py
?? zhiyuan-server/scripts/evidence_p1a_acceptance.sh
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/util/EvidenceParamsDigest.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/util/Ulid.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/EvidenceLedgerMapper.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/EvidenceSourceVersionMapper.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/evidence/
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/EvidenceLedgerEntity.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/EvidenceSourceVersionEntity.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerService.java
?? zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/EvidenceLedgerController.java
?? zhiyuan-server/src/main/resources/db/migration/V14__evidence_ledger.sql
?? zhiyuan-server/src/test/java/com/ytell/zhiyuan/common/
?? zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/EvidenceLedgerServiceTest.java
```

其中属于本任务（P1a）的是全部 `zhiyuan-server/` 行；`docker-compose.codex-local.yml`（T006）、`zhiyuan-agent/` 下 5 个文件与 `zhiyuan-agent/CLAUDE.md`（T005、T007）、以及三个 T00x 任务目录都不是本任务改的，是本工作区里前序任务的未提交产物。本任务没有删除任何文件。

## 四、验收命令与原始输出

### 命令 1：单元测试

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn -o test -Dtest=EvidenceParamsDigestTest,EvidenceLedgerServiceTest -DfailIfNoTests=false
```

原始输出（89 行，全文）：

```
[INFO] Scanning for projects...
[WARNING] 
[WARNING] Some problems were encountered while building the effective model for com.ytell:zhiyuan-server:jar:3.0.0
[WARNING] 'dependencyManagement.dependencies.dependency.exclusions.exclusion.artifactId' for org.quartz-scheduler:quartz:jar with value '*' does not match a valid id pattern. @ org.springframework.boot:spring-boot-dependencies:2.3.8.RELEASE, /root/.m2/repository/org/springframework/boot/spring-boot-dependencies/2.3.8.RELEASE/spring-boot-dependencies-2.3.8.RELEASE.pom, line 2014, column 25
[WARNING] 
[WARNING] It is highly recommended to fix these problems because they threaten the stability of your build.
[WARNING] 
[WARNING] For this reason, future Maven versions might no longer support building such malformed projects.
[WARNING] 
[INFO]                                                                         
[INFO] ------------------------------------------------------------------------
[INFO] Building zhiyuan-server 3.0.0
[INFO] ------------------------------------------------------------------------
[INFO] 
[INFO] --- maven-resources-plugin:3.1.0:resources (default-resources) @ zhiyuan-server ---
[INFO] Using 'UTF-8' encoding to copy filtered resources.
[INFO] Copying 2 resources
[INFO] Copying 23 resources
[INFO] 
[INFO] --- maven-compiler-plugin:3.8.1:compile (default-compile) @ zhiyuan-server ---
[INFO] Nothing to compile - all classes are up to date
[INFO] 
[INFO] --- maven-resources-plugin:3.1.0:testResources (default-testResources) @ zhiyuan-server ---
[INFO] Using 'UTF-8' encoding to copy filtered resources.
[INFO] Copying 2 resources
[INFO] 
[INFO] --- maven-compiler-plugin:3.8.1:testCompile (default-testCompile) @ zhiyuan-server ---
[INFO] Nothing to compile - all classes are up to date
[INFO] 
[INFO] --- maven-surefire-plugin:2.22.2:test (default-test) @ zhiyuan-server ---
[INFO] 
[INFO] -------------------------------------------------------
[INFO]  T E S T S
[INFO] -------------------------------------------------------
[INFO] Running com.ytell.zhiyuan.service.biz.EvidenceLedgerServiceTest
07:12:19.336 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@2002348] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 1261044180]
07:12:19.338 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@2002348] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 589363823]
07:12:19.338 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@2002348] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.353 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@52de51b6] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 415565467]
07:12:19.353 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@52de51b6] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 973936431]
07:12:19.353 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@52de51b6] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.355 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@68ad99fe] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 1214133948]
07:12:19.355 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@68ad99fe] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 2015301874]
07:12:19.355 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@68ad99fe] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.390 [main] INFO com.ytell.zhiyuan.service.biz.EvidenceLedgerService - 证据已签发, evidenceId=ev_01M26SFVD3SKZMA9C3W7DV2FNG, sourceSystem=gaotu.schoolMajorScoreLine, chatSessionId=42, paramsDigest=f6837cfbc12b6f98153337d550aa4f8d, dataVersion=2026-06-v17
07:12:19.416 [main] INFO com.ytell.zhiyuan.service.biz.EvidenceLedgerService - 证据已签发, evidenceId=ev_01M26SFVER5ZJC5KR3HJ8PJBWD, sourceSystem=gaotu.schoolMajorScoreLine, chatSessionId=42, paramsDigest=f6837cfbc12b6f98153337d550aa4f8d, dataVersion=2026-06-v17
07:12:19.418 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@5316e95f] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 1057307776]
07:12:19.418 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@5316e95f] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 1819038759]
07:12:19.418 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@5316e95f] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.419 [main] INFO com.ytell.zhiyuan.service.biz.EvidenceLedgerService - 证据已签发, evidenceId=ev_01M26SFVEVPKK50KRKDHCEXQQB, sourceSystem=gaotu.schoolMajorScoreLine, chatSessionId=42, paramsDigest=f6837cfbc12b6f98153337d550aa4f8d, dataVersion=2026-06-v17
07:12:19.424 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@30f5a68a] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 505231702]
07:12:19.424 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@30f5a68a] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 1328323494]
07:12:19.424 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@30f5a68a] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.425 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@4e28bdd1] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 1408533352]
07:12:19.425 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@4e28bdd1] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 617928649]
07:12:19.426 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@4e28bdd1] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.427 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@73db4768] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 1907604549]
07:12:19.427 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@73db4768] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 176955204]
07:12:19.427 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@73db4768] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.428 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@150ab4ed] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 1011044643]
07:12:19.429 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@150ab4ed] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 1358857082]
07:12:19.429 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@150ab4ed] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.429 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@3a62c01e] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 2056234595]
07:12:19.429 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@3a62c01e] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 1558395480]
07:12:19.430 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@3a62c01e] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.431 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@78a287ed] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 1416415959]
07:12:19.431 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@78a287ed] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 1398260359]
07:12:19.431 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@78a287ed] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.432 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@1623134f] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 2052223881]
07:12:19.432 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@1623134f] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 1213871206]
07:12:19.432 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@1623134f] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
07:12:19.433 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceLedgerMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@25748410] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceLedgerMapper, hashCode: 725832346]
07:12:19.433 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'evidenceSourceVersionMapper' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@25748410] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [Mock for EvidenceSourceVersionMapper, hashCode: 1113895488]
07:12:19.433 [main] DEBUG org.springframework.test.util.ReflectionTestUtils - Setting field 'ttlDays' of type [null] on target object [com.ytell.zhiyuan.service.biz.EvidenceLedgerService@25748410] or target class [class com.ytell.zhiyuan.service.biz.EvidenceLedgerService] to value [30]
[INFO] Tests run: 12, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.462 s - in com.ytell.zhiyuan.service.biz.EvidenceLedgerServiceTest
[INFO] Running com.ytell.zhiyuan.common.util.EvidenceParamsDigestTest
[INFO] Tests run: 6, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0 s - in com.ytell.zhiyuan.common.util.EvidenceParamsDigestTest
[INFO] 
[INFO] Results:
[INFO] 
[INFO] Tests run: 18, Failures: 0, Errors: 0, Skipped: 0
[INFO] 
[INFO] ------------------------------------------------------------------------
[INFO] BUILD SUCCESS
[INFO] ------------------------------------------------------------------------
[INFO] Total time: 2.205s
[INFO] Finished at: Fri Sep 11 07:12:19 CST 2026
[INFO] Final Memory: 22M/425M
[INFO] ------------------------------------------------------------------------
```

### 命令 2：全量 Java 测试

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn -o test
```

原始输出（日志共 4963 行，省略前 4947 行 DEBUG/INFO 噪声，保留末 16 行）：

```
[INFO] Running com.ytell.zhiyuan.model.dto.planning.PlanningStateDTOCompatibilityTest
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0 s - in com.ytell.zhiyuan.model.dto.planning.PlanningStateDTOCompatibilityTest
[INFO] Running com.ytell.zhiyuan.model.dto.planning.ConversationContractSerializationTest
[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.005 s - in com.ytell.zhiyuan.model.dto.planning.ConversationContractSerializationTest
[INFO] 
[INFO] Results:
[INFO] 
[WARNING] Tests run: 708, Failures: 0, Errors: 0, Skipped: 5
[INFO] 
[INFO] ------------------------------------------------------------------------
[INFO] BUILD SUCCESS
[INFO] ------------------------------------------------------------------------
[INFO] Total time: 7.243s
[INFO] Finished at: Fri Sep 11 07:11:26 CST 2026
[INFO] Final Memory: 33M/684M
[INFO] ------------------------------------------------------------------------
```

### 命令 3：端到端验收（签发 → 台账 → 四态核验）

```bash
cd /root/dev/zhiyuan/zhiyuan-server
bash scripts/evidence_p1a_acceptance.sh
```

脚本自己拉起上游替身（127.0.0.1:18811）和 zhiyuan-server（127.0.0.1:18080），依赖本机已起的 MySQL/Redis（`docker-compose.codex-local.yml`，13306 / 16379），跑完关掉。原始输出（97 行，全文）：

```

==============================================================
## 0. 启动上游替身与 zhiyuan-server
==============================================================
服务已就绪：http://127.0.0.1:18080
上游替身：http://127.0.0.1:18811
Flyway 版本记录（V14）：
14	evidence ledger	1
台账初始行数：
0

==============================================================
## 1. 同一查询参数连续两次：两个不同 evidenceId、相同 paramsDigest
==============================================================
--- 第 1 次原始响应 ---
{"code":0,"msg":"ok","data":[{"year":2025,"name":"甲大学","batch":"本科批","batchTitle":"本科批","enrollNum":"10","maxScore":"630","minScore":"612","averageScore":"620","minPos":"8000","maxPos":"12000","selectInfo":"物理类"}],"dataVersion":"2026-06-v17","evidence":[{"evidenceId":"ev_01M26SFEV2602PG44J0Q4S5H00","sourceLevel":"authoritative","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"2026-06-v17","expiresAt":"2026-10-11T07:12:06.497+08:00","admissionMode":null,"admissionUnitId":null,"groupCode":null,"algorithmVersion":null,"stateVersion":null,"scope":{"tenantId":7,"chatSessionId":42,"threadId":"thread-1"},"observedAt":"2026-09-11T07:12:06.497+08:00","limitations":[]}]}
--- 第 2 次原始响应 ---
{"code":0,"msg":"ok","data":[{"year":2025,"name":"甲大学","batch":"本科批","batchTitle":"本科批","enrollNum":"10","maxScore":"630","minScore":"612","averageScore":"620","minPos":"8000","maxPos":"12000","selectInfo":"物理类"}],"dataVersion":"2026-06-v17","evidence":[{"evidenceId":"ev_01M26SFEYVTWH43GHFCKFM8WCQ","sourceLevel":"authoritative","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"2026-06-v17","expiresAt":"2026-10-11T07:12:06.619+08:00","admissionMode":null,"admissionUnitId":null,"groupCode":null,"algorithmVersion":null,"stateVersion":null,"scope":{"tenantId":7,"chatSessionId":42,"threadId":"thread-1"},"observedAt":"2026-09-11T07:12:06.619+08:00","limitations":[]}]}
--- 提取 ---
第 1 次 evidenceId   = ev_01M26SFEV2602PG44J0Q4S5H00
第 2 次 evidenceId   = ev_01M26SFEYVTWH43GHFCKFM8WCQ
evidenceId 不同      = true
第 1 次 paramsDigest = d7e9bea1ad3d3ca100a2b58f95dde4e4
第 2 次 paramsDigest = d7e9bea1ad3d3ca100a2b58f95dde4e4
paramsDigest 相同    = true
--- 上游收到 2 次请求（替身计数）---
{"dataVersion": "2026-06-v17", "calls": ["/hl-wish/ci/memberWhitelist/noToken/commonInfo", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine"]}
==============================================================
## 2. 反向对照：改一个参数值（year 2025 → 2024），paramsDigest 必须变
==============================================================
{"code":0,"msg":"ok","data":[{"year":2025,"name":"甲大学","batch":"本科批","batchTitle":"本科批","enrollNum":"10","maxScore":"630","minScore":"612","averageScore":"620","minPos":"8000","maxPos":"12000","selectInfo":"物理类"}],"dataVersion":"2026-06-v17","evidence":[{"evidenceId":"ev_01M26SFF4CBGG9MQ1Q2JH6EEGM","sourceLevel":"authoritative","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"47605e6c06e210ebe40adce1ae7069d3","dataVersion":"2026-06-v17","expiresAt":"2026-10-11T07:12:06.795+08:00","admissionMode":null,"admissionUnitId":null,"groupCode":null,"algorithmVersion":null,"stateVersion":null,"scope":{"tenantId":7,"chatSessionId":42,"threadId":"thread-1"},"observedAt":"2026-09-11T07:12:06.795+08:00","limitations":[]}]}
year=2025 paramsDigest = d7e9bea1ad3d3ca100a2b58f95dde4e4
year=2024 paramsDigest = 47605e6c06e210ebe40adce1ae7069d3
paramsDigest 变化      = true

==============================================================
## 3. 台账内容（签发确实落库）
==============================================================
ev_01M26SFEV2602PG44J0Q4S5H00	7	42	thread-1	gaotu.schoolMajorScoreLine	d7e9bea1ad3d3ca100a2b58f95dde4e4	2026-06-v17	2026-09-11 07:12:06	2026-10-11 07:12:06
ev_01M26SFEYVTWH43GHFCKFM8WCQ	7	42	thread-1	gaotu.schoolMajorScoreLine	d7e9bea1ad3d3ca100a2b58f95dde4e4	2026-06-v17	2026-09-11 07:12:07	2026-10-11 07:12:07
ev_01M26SFF4CBGG9MQ1Q2JH6EEGM	7	42	thread-1	gaotu.schoolMajorScoreLine	47605e6c06e210ebe40adce1ae7069d3	2026-06-v17	2026-09-11 07:12:07	2026-10-11 07:12:07
--- 来源版本登记 ---
gaotu.schoolMajorScoreLine	2026-06-v17	2026-09-11 07:12:07

==============================================================
## 4. 上游 dataVersion 取不到 → 不签发（对照：能取到时必须签发）
==============================================================
--- 控制面把版本设为 null ---
{"ok": true, "dataVersion": null}
--- 原始响应 ---
{"code":0,"msg":"ok","data":[{"year":2025,"name":"甲大学","batch":"本科批","batchTitle":"本科批","enrollNum":"10","maxScore":"630","minScore":"612","averageScore":"620","minPos":"8000","maxPos":"12000","selectInfo":"物理类"}],"dataVersion":null,"evidence":null}
调用前台账行数 = 3
调用后台账行数 = 3
未产生新记录   = true
--- 控制面恢复版本 ---
{"ok": true, "dataVersion": "2026-06-v17"}
恢复版本后再调用，台账行数 = 4
对照：能取到版本时必须产生记录 = true
新签发 evidenceId = ev_01M26SFFGMCWKQZAJ46PN27RE9

==============================================================
## 5. 四态核验：valid
==============================================================
--- verify(ev_01M26SFFGMCWKQZAJ46PN27RE9) ---
{"data":{"results":{"ev_01M26SFFGMCWKQZAJ46PN27RE9":{"status":"valid","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"2026-06-v17","observedAt":"2026-09-11T07:12:07+08:00","expiresAt":"2026-10-11T07:12:07+08:00"}}},"code":0,"msg":"success"}
==============================================================
## 6. 四态核验：stale（上游版本变了，旧记录当时正确、现已失效）
==============================================================
--- 控制面把上游版本推进到 2026-06-v18，再查一次 ---
{"ok": true, "dataVersion": "2026-06-v18"}
新记录 evidenceId = ev_01M26SFFMW0DYJ594KQ6BEQFDX
--- 旧记录与新记录一起核验 ---
{"data":{"results":{"ev_01M26SFFGMCWKQZAJ46PN27RE9":{"status":"stale","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"2026-06-v17","observedAt":"2026-09-11T07:12:07+08:00","expiresAt":"2026-10-11T07:12:07+08:00"},"ev_01M26SFFMW0DYJ594KQ6BEQFDX":{"status":"valid","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"2026-06-v18","observedAt":"2026-09-11T07:12:07+08:00","expiresAt":"2026-10-11T07:12:07+08:00"}}},"code":0,"msg":"success"}--- 对照：删掉 ev_01M26SFFGMCWKQZAJ46PN27RE9 之后必须返回 unknown ---
{"data":{"results":{"ev_01M26SFFGMCWKQZAJ46PN27RE9":{"status":"unknown","sourceSystem":null,"paramsDigest":null,"dataVersion":null,"observedAt":null,"expiresAt":null},"ev_01M26SFFMW0DYJ594KQ6BEQFDX":{"status":"valid","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"2026-06-v18","observedAt":"2026-09-11T07:12:07+08:00","expiresAt":"2026-10-11T07:12:07+08:00"}}},"code":0,"msg":"success"}
==============================================================
## 7. 四态核验：expired（把 expires_at 改到过去）
==============================================================
--- 核验 ev_01M26SFFMW0DYJ594KQ6BEQFDX ---
{"data":{"results":{"ev_01M26SFFMW0DYJ594KQ6BEQFDX":{"status":"expired","sourceSystem":"gaotu.schoolMajorScoreLine","paramsDigest":"d7e9bea1ad3d3ca100a2b58f95dde4e4","dataVersion":"2026-06-v18","observedAt":"2026-09-11T07:12:07+08:00","expiresAt":"2026-09-09T23:12:07+08:00"}}},"code":0,"msg":"success"}
==============================================================
## 8. 范围校验：换一个会话核验同一个 ID，必须 unknown
==============================================================
{"data":{"results":{"ev_01M26SFFMW0DYJ594KQ6BEQFDX":{"status":"unknown","sourceSystem":null,"paramsDigest":null,"dataVersion":null,"observedAt":null,"expiresAt":null}}},"code":0,"msg":"success"}
==============================================================
## 9. data_version NOT NULL 约束的负向对照（拿不到版本就不签发，而不是写空值）
==============================================================
--- 绕过签发逻辑，直接插一条 data_version = NULL ---
ERROR 1048 (23000) at line 1: Column 'data_version' cannot be null
mysql 退出码 = 1
--- 台账里是否落进了这条探针行 ---
0

==============================================================
## 10. 收尾：停止服务
==============================================================
上游替身请求计数：
{"dataVersion": "2026-06-v18", "calls": ["/hl-wish/ci/memberWhitelist/noToken/commonInfo", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine", "/hl-wish/ci/ci_feign/volunteer/querySchoolMajorScoreLine"]}


### 命令 3 与设计文档第八章 P1a 验收条的对应

| 设计验收条 | 对应原始输出位置 | 结果 |
|---|---|---|
| 同一查询参数连续两次 → 两个不同 evidenceId、相同 paramsDigest | 第 1 步：`ev_01M26SDM...` vs `ev_01M26SDN...`，两行 `paramsDigest` 均为 `d7e9bea1ad3d3ca100a2b58f95dde4e4`；`evidenceId 不同 = true`、`paramsDigest 相同 = true` | 通过 |
| 反向对照：改一个参数值 → paramsDigest 必须变 | 第 2 步：year 2025 → 2024，`d7e9bea1...` → `47605e6c...`，`paramsDigest 变化 = true` | 通过 |
| 上游 dataVersion 取不到 → 不产生台账记录 | 第 4 步：控制面把版本置 null 后调用，台账 3 → 3 行（`未产生新记录 = true`）；恢复版本后再调用 3 → 4 行（`对照：能取到版本时必须产生记录 = true`） | 通过 |
| 对照：能取到时必须产生记录 | 同上第 4 步后半 | 通过 |
| 人工把一条记录的 data_version 改成与上游不一致 → stale | 第 6 步：上游推进到 `2026-06-v18` 后再签一条，旧记录 `ev_01M26SDM1G...` 返回 `"status":"stale"`，新记录 `"status":"valid"` | 通过 |
| 对照：删掉记录 → unknown | 第 6 步后半：`DELETE` 后同一 ID 返回 `"status":"unknown"` | 通过 |
| 把 expires_at 改到过去 → expired | 第 7 步：`"status":"expired"` | 通过 |
| （补充）data_version NOT NULL | 第 9 步：直接插 `data_version = NULL` → `ERROR 1048 (23000) at line 1: Column 'data_version' cannot be null`，`mysql 退出码 = 1`，探针行数 0 | 通过 |

## 五、与已知失败基线的对照

Java 侧没有登记过失败基线；`docs/superpowers/tasks/README.md` 里的已知失败基线只覆盖 `zhiyuan-agent` 的 pytest（2 项失败），不适用于本任务。

本次全量 `mvn -o test` 的观测结果：`Tests run: 708, Failures: 0, Errors: 0, Skipped: 5`，`BUILD SUCCESS`，无失败用例。5 个 skipped 未逐条核对来源。

## 六、偏离任务书之处

本任务没有冻结的 `TASK.md`（派发是对话里的「P1a 也要做」），验收标准取自 `docs/superpowers/plans/2026-09-10-P1权威证据台账设计.md` 第四、七、八章。以下是实现与设计文档不一致或设计文档未覆盖而由本次自行决定的地方：

1. **「上游数据版本」的来源是自行定义的。** 设计文档要求 `data_version NOT NULL`、「拿不到上游版本就不签发」，但没有说版本从哪来。核查事实：`ResponseDTO`、`BatchDataResponseDTO`、`QueryProgramByLimitNumRes`、`QuerySchoolMajorScoreLineRes` 四个类都没有版本字段，仓库里也没有留存过真实上游的响应报文。本次实现把版本定义为上游响应包 `ResponseDTO` 上的 `dataVersion` 字段（新增字段，fastjson 按名映射，上游不返回时保持 null）。真实上游是否返回该字段、字段名是否叫 `dataVersion`，本环境无法验证——命令 3 用的是会返回该字段的替身（`scripts/evidence_fake_upstream.py`）。

2. **多建了一张表 `evidence_source_version`。** 设计文档 4.2 只列了 `evidence_ledger`，但 4.3 要求「按 `source_system` 取当前 `dataVersion` 与记录里的比」。只有一张台账表时，「当前版本」只能取自台账自身的最新行——而验收条「人工把一条记录的 data_version 改成与上游不一致」在只有一行记录时会把该行同时当作「被核验的记录」和「当前版本」，比不出 `stale`。因此本次加了同样在 V14 里的一张单行来源表（`source_system` 主键 + `data_version` + `observed_at`），每次签发时 upsert。

3. **`POST /internal/evidence/verify` 需要一条额外的拦截器放行。** 路径按设计文档原样实现；实测该路径被 `LoginInterceptor` 拦下并抛 `BusinessException(800,"不合法请求")`（见第八章）。已在 `WebConfig` 的 `excludePathPatterns` 里加一行 `"/internal/evidence/**"`，与既有的 `/**/inner/**` 同级处理（内部接口靠网络隔离而非登录态保护）。

4. **三个查询端点加了可选的 `tenantId` / `chatSessionId` / `threadId` 参数。** 台账这三列是 NOT NULL，而 `GaotuClient` 的三个方法本身不持有会话上下文。做法是给三个方法加带 `EvidenceScope` 的重载（原签名保留，委托给新重载，传 `EvidenceScope.none()`），由 `GaotuClientDebugController` 的三个端点把这三个可选请求参数透传进来；范围不全时不签发。`GaotuService` 里调用同两个方法的包装方法（`/root/dev/zhiyuan/zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/GaotuService.java:602` 与 `:616`）没有会话上下文可用，仍走 `EvidenceScope.none()`，即当前生产调用路径不会签发。

5. **响应体的包裹层。** 设计文档 4.4 写的是 `→ { "results": {...} }`；实现按仓库既有的内部接口约定包了一层 `BaseResponse`，即 `{"data":{"results":{...}},"code":0,"msg":"success"}`（`EvidenceLedgerController.java`）。

6. **`dataVersion_missing` 这个字符串 Java 侧不产生。** 设计文档 4.2 说「让调用方走 `tools_readonly.py:298` 已有的 `dataVersion_missing` 降级路径」。该字符串在 Agent 侧 `app/mcp_server/tools_readonly.py:298` 追加，属 P1b 范围；P1a 的实现只以「响应里 `dataVersion` 为 null、`evidence` 为 null」表达未签发（命令 3 第 4 步原始输出可见）。

7. **有效期取 30 天，做成配置项。** 设计文档 4.2 写「建议 30 天起步……这个值需要产品侧确认」。本次落在 `application.yml` 的 `evidence.ledger.ttl-days: 30`（`EvidenceLedgerService` 用 `@Value` 读取，默认 30）。

8. **`sourceLevel: "authoritative"` 由 Java 写入。** 设计文档第二章第 1 条要求标签只能来自签发者；`EvidenceLedgerService` 是唯一写这个值的地方（`SOURCE_LEVEL_AUTHORITATIVE`）

9. **签发失败时不抛异常。** 台账写库异常时记 ERROR 日志并返回 null（不签发），取数结果照常返回；即取数失败与取证失败不互相放大。此行为设计文档未规定，是本次的选择。

## 七、未做的事

- `ConversationSnapshotService.fillEvidence()`（设计文档 4.5）——属 P1b。
- Agent 侧删自铸证据分支（5.1）、snapshot 优先（5.2）——属 P1b，且在 `zhiyuan-agent/`，本任务边界是只碰 `zhiyuan-server/`。
- `output_validation.py` 的核验接入与 fail-closed 分流（5.3）——属 P1c。
- 过期清理的定时任务：设计文档 4.2 写「清理按 `expires_at` 定时删」，本次只建了 `expires_at` 索引，没有实现清理任务；保留窗口本身也待产品确认。
- `GaotuService.queryProgramByLimitNum` / `querySchoolMajorScoreLine` 两个生产包装方法未接会话上下文，因此这两条路径当前不签发（见第六章第 4 条），未改它们的调用方。
- 未提交（commit）。按协议实现会话不 commit。

## 八、观察到的异常现象（只列事实）

1. **`/internal/evidence/verify` 未放行时被登录拦截器拦截。** 加 `WebConfig` 排除项之前，命令 3 的第 5–8 步返回 `{"data":null,"code":800,"msg":"不合法请求"}`；服务端日志（`/tmp/p1a-app.log`）对应 `com.ytell.zhiyuan.common.exception.BusinessException: 不合法请求`，抛出点 `LoginInterceptor.preHandle`（`LoginInterceptor.java:30/38/51`）。放行后同样请求返回 `code:0`。

2. **首次验收运行时 18999 端口已被占用。** 替身启动即退出，`/tmp/p1a-upstream.log` 原文：`OSError: [Errno 98] Address already in use`；`ss -ltnp` 显示 18999 由另一个 python 进程（pid 8988）监听，并且该端口对 `GET /__control/state` 返回的响应体是 `Authentication Fails (governor)`。改用 18811 后验收通过。同一轮中应用侧对应报错为 `java.lang.RuntimeException: invoke HTTP fail`（`caused by` 未展开）。

3. **`| head -80` 会截断验收脚本。** 第一次运行把脚本输出接给 `head`，SIGPIPE 使脚本在第 8 步前终止，后续步骤无输出；改为直接重定向到文件后完整跑完。报告里贴的是重定向版本的输出。

4. **应用启动时会向替身发一次 `/hl-wish/ci/memberWhitelist/noToken/commonInfo`。** 命令 3 第 10 步的替身计数里，该路径出现 1 次且排在三类被验收调用之前；本次验收未调用它。

5. **`dataVersion` 缺失时响应里是 `null` 而不是缺键。** 命令 3 第 4 步原始响应：`...,"dataVersion":null,"evidence":null}`。
