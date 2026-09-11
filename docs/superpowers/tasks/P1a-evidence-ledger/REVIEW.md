---
task: P1a
verdict: ACCEPTED_WITH_FOLLOWUP
reviewer: 设计会话（Claude Opus 5）
reviewed_at: 2026-09-11
---

# P1a 回收判定

## 一、判定

`ACCEPTED_WITH_FOLLOWUP`。设计文档第七章 P1a 的六项内容全部落地，第八章四条验收我自己重跑全过，**且每条正向检查都有能证伪它的负向对照，对照全部正确区分**。这是四份报告里验收设计最扎实的一份。

实现方自报 `DONE_WITH_CONCERNS` 并把最需要确认的一条写在结论第一段——判断准确，那条确实是本片最大的风险。

跟进项四条，见第四节。其中第 1、2 条必须在 P1b 派发前定，第 3、4 条排进 P1b。

## 二、自行重跑的验收（不采信报告输出）

### 命令 1：Java 全量测试

```
Tests run: 708, Failures: 0, Errors: 0, Skipped: 5
BUILD SUCCESS
```

其中 `EvidenceLedgerServiceTest` 12 passed、`EvidenceParamsDigestTest` 6 passed。与报告一致，无失败。

### 命令 2：端到端验收（`bash scripts/evidence_p1a_acceptance.sh`）

`exit=0`，十步全过。**新一轮的 ULID 与报告里的完全不同**（本次 `ev_01M26TG7HJQVMRHYKMN4H3ADEK` / `ev_01M26TG7PNP2RE4YR4S8J19J8R`，报告里是 `ev_01M26SFE…` / `ev_01M26SFF…`），确认是真重跑，不是回放留档。

逐条对设计文档第八章：

| 设计验收条 | 本次实测 | 对照是否真的能证伪 |
|---|---|---|
| 同参数两次 → 不同 `evidenceId`、相同 `paramsDigest` | `evidenceId 不同 = true`，`paramsDigest 相同 = true` | 有：改 `year` 2025→2024，摘要 `d7e9bea1…` → `47605e6c…`，`变化 = true` |
| 取不到 `dataVersion` → 不签发 | 台账 3 → 3 行，`未产生新记录 = true` | 有：恢复版本后 3 → 4 行，`必须产生记录 = true` |
| `data_version` 与上游不一致 → `stale` | 上游推进到 `v18` 后旧记录返回 `"status":"stale"`，新记录 `"valid"` | 有：删掉该行后同一 ID 返回 `"unknown"`，两态确实可分 |
| `expires_at` 改到过去 → `expired` | `"status":"expired"` | 与上面三态互斥可分 |
| （超出设计要求，实现方自加）换会话核验同一 ID | `"unknown"`，且 `sourceSystem`/`paramsDigest` 全部 `null`，不泄露别会话台账 | — |
| （超出设计要求）`data_version NOT NULL` 负向探针 | `ERROR 1048 (23000): Column 'data_version' cannot be null`，`退出码 = 1`，探针行数 0 | — |

四态全部被真实构造出来并正确区分。**`stale` 与 `unknown` 可分是这张表存在的核心理由**（设计文档 4.3），实测成立。

## 三、实现质量评审

**签发点选对了。** 挂在 `GaotuClient` 的 `ResponseDTO` 包装层（`attachEvidence()`），三个查询方法共用一条路径，不是在各 BizService 里分别接——设计文档明写"那会漏，而且漏掉的那个正好就是不带证据的路径"，实现照办了。原方法签名保留、委托给带 `EvidenceScope` 的新重载，不破坏既有调用方。

**fail-closed 的默认方向处处正确，这是最值得肯定的地方。** 逐条核对代码：

- `sign()`：`sourceSystem` 空、`dataVersion` 空、`scope` 不完整 —— 任一缺失即返回 `null` 不签发（`:76-86`）。
- `sign()` 写库异常：记 ERROR 返回 `null`，**取数结果照常返回**（`:114-119`）。取证失败不放大成取数失败，同时调用方拿不到证据只能降级。方向正确。
- `verify()`：`tenantId` 或 `chatSessionId` 缺失 → 全部 `unknown`（`:148-151`），不是全部放行。
- `currentDataVersion()`：来源无版本记录时返回 `""`，于是台账记录永远比不中，落到 `stale` 而非 `valid`（`:219-225`，注释写明了这个意图）。**"不知道"倒向"必须重查"而不是"可引用"**，正是设计要的方向。

**`sourceLevel: "authoritative"` 的唯一写入点收归 Java 成立。** `EvidenceLedgerService.SOURCE_LEVEL_AUTHORITATIVE` 是全仓 Java 侧唯一赋值处（`:193`）。设计原则一（"权威性来自签发者，不来自标签"）在 Java 侧兑现。Agent 侧那两处自铸分支还在，属 P1b。

**超范围文件四个，逐个核对，全部最小且已在报告第六节声明：**

| 文件 | 改动 | 判定 |
|---|---|---|
| `ConversationEvidenceDTO.java` | +3 字段（`sourceSystem` / `paramsDigest` / `expiresAt`） | 与设计文档第三章一字不差，接受 |
| `ResponseDTO.java` | +2 字段（`dataVersion` / `evidence`），带说明性 `@ApiModelProperty` | 接受，但 `dataVersion` 见第四节第 1 条 |
| `WebConfig.java` | 1 行 `excludePathPatterns` | 接受。与既有 `/**/inner/**` 同级，内部接口靠网络隔离；实现方还在第八节给出了不加这行时的原始报错，属实 |
| `application.yml` | `evidence.ledger.ttl-days: 30` | 接受。设计文档说"待产品确认"，做成配置项比写死更合适 |

`ResponseDTO.java` 原本就缺文件末尾换行（`\ No newline at end of file` 在改动前后都在），不是本次引入。

**多建 `evidence_source_version` 表的决定是对的。** 报告第六节第 2 条的论证成立：只有一张台账表时，"当前版本"只能取自台账自身，被核验的记录会同时充当基准，`stale` 在定义上就构造不出来。这是设计文档 4.2/4.3 之间的一处遗漏，实现方发现并补上了，理由写得比我的设计文档更清楚。

## 四、跟进项

### 1. `dataVersion` 的上游契约是假设的，不是事实（P1b 派发前必须定）

实现方在结论第一段就点明了，判断准确。核查确认：`ResponseDTO`、`BatchDataResponseDTO`、`QueryProgramByLimitNumRes`、`QuerySchoolMajorScoreLineRes` 四个类原本都没有版本字段，仓库里也没有真实上游报文留存。本次把版本定义为响应包上的 `dataVersion` 字段，验收用的是会返回该字段的替身。

风险是明确的：**如果真实上游不返回 `dataVersion`，那么按当前 fail-closed 逻辑，生产上一条证据都签不出来**，P1b/P1c 接上去之后所有 `fact` 输出会整轮 fail closed。

这不是实现缺陷——设计文档确实没说版本从哪来，是我的遗漏。但它必须在 P1b 派发前用一次真实上游调用定下来，**不能靠继续在替身上验证**。若上游确实不提供版本，需要改设计：要么取 HTTP 响应头/网关侧的数据批次号，要么由 Java 侧按取数时间窗自定义版本口径。

### 2. 生产路径当前一条证据都不签（P1b 派发前必须定）

我自己 grep 核对（`src/main/java` 全量，排除 `GaotuClient` 自身）：

```
GaotuClientDebugController.java:48/108/118   → EvidenceScope.of(tenantId, chatSessionId, threadId)   ← 签发
GaotuService.java:603/617                     → 2 参重载 → EvidenceScope.none()                      ← 不签发
```

即**唯一会签发的调用方是 inner 下的 debug controller**。报告第六节第 4 条与第七节都如实说了，不是隐瞒。

但要把这条结论的分量说清楚：P1a 建成的是一台**装好但没接进产线**的机器。设计文档第七章把 P1a 定义为"建表 + 摘要 + 签发接入 + verify + 四态"，字面上都做到了；"签发接入"是否包含把会话上下文打通到 `GaotuService`，文档没写清楚——这是我的切片定义不够锐利。判定不因此降级，但 **P1b 必须把会话上下文接到生产取数路径**，否则 P1c 的验收（"模型任何 `fact` 输出的 evidenceRefs 都能回解到 Java 权威记录"）在生产上恒为不可能。

### 3. `evidence_source_version` 按 `source_system` 单行，跨参数会互相打脸（排进 P1b）

`upsert(sourceSystem, dataVersion, observedAt)` 与 `currentDataVersion(sourceSystem)` 都只按来源系统取键，一个来源全局一行。

后果：**同一来源、不同查询参数**若合法地携带不同 `dataVersion`（比如分省分批次各自的数据版本），后一次查询会把前一次的版本挤掉，于是前一条证据在下一回合核验时变成 `stale`——尽管它其实没失效。表现是无谓的重查，最坏情况是重查一次仍不一致 → 整轮 fail closed（设计文档第六章）。

本次验收没暴露这一点，因为替身对所有参数返回同一个版本。**这正是替身验证的盲区。**

与第 1 条同源：都取决于真实上游的版本语义。若版本是全局批次号，现状正确；若版本随参数变化，键必须扩成 `(source_system, params_digest)` 或按业务维度分组。定第 1 条时一并定。

### 4. `threadId` 只在双方都非空时才校验（排进 P1b）

`verifyOne()` `:167-170`：

```java
if (!isBlank(entity.getThreadId()) && !isBlank(request.getThreadId())
        && !entity.getThreadId().equals(request.getThreadId())) {
    return EvidenceVerifyItemDTO.of(STATUS_UNKNOWN);
}
```

请求省略 `threadId` 即跳过线程校验。`tenantId` + `chatSessionId` 仍强制（`:163-166`），所以影响面封在单个会话内部，不构成跨会话泄露——第 8 步验收也证明了换会话必 `unknown`。

但设计文档 5.3 保留的 `output_validation.py:126-145` 是**三重 scope 校验**，`strict_scope=True` 时要求 scope 字段必须存在。Java 侧这里比 Agent 侧松。P1c 接上去后两层口径不一致会造成"Agent 严、Java 松"的错位。P1b 统一：要么 Java 侧也要求 `threadId` 必填，要么显式记录"线程级隔离由 Agent 侧负责"并写进注释。

## 五、未做项的确认

报告第七节列的五项我逐条核对属实，且都正确地落在 P1a 边界之外：`fillEvidence()`（P1b）、Agent 侧删自铸分支与 snapshot 优先（P1b）、`output_validation.py` 核验接入（P1c）、过期清理定时任务（待产品确认保留窗口）、生产包装方法未接会话上下文（见第四节第 2 条，升级为 P1b 必做项）。

`git status` 与报告声明的文件清单逐行核对一致，无未声明改动，无删除。未 commit，符合协议。

## 六、次要观察（不阻塞，不单独排期）

**两个新脚本可以入库，都没有硬编码凭据。** `evidence_fake_upstream.py` 的文件头把"这是替身、控制面是真实上游没有的"写得很清楚，不会被误当成生产组件；`evidence_p1a_acceptance.sh` 的 MySQL 口令是运行时从容器环境变量取的（`docker exec … printf %s "$MYSQL_ROOT_PASSWORD"`），用完 `unset`，仓库里不落密。

一处小瑕疵：`evidence_p1a_acceptance.sh:65` 把口令作为 `--spring.datasource...password=` 命令行参数传给 Spring Boot，于是它在该进程存活期间对宿主机的 `ps` 可见。只影响本地开发环境（口令是 `codex-local-infra.sh` 每次随机生成的），不改也能用。将来若把这个脚本挪到共享环境，改走环境变量或临时配置文件。

