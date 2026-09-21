# 智愿领域数据、推荐与方案事务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 将院校/专业、历史/概率/计划/章程、匹配推荐、完整志愿表与调整审查接成有证据、可确认、可恢复的领域能力。

**Architecture:** Codex 解释目标和调用领域 MCP，Java 负责真实数据、Rank/Solver、Proposal 编译及事务。历史事实与个体录取率分型，预览与正式方案写入分离，沿用现有 Evidence/Pending/command 表。

**Tech Stack:** Python ≥3.10 / Pydantic、Java 8 / Spring Boot 2.3 / MyBatis / MySQL、Redis、现有 Rank 与 ojAlgo Solver。

**Spec:** [核心设计](../../release-4.0.0-codex-native-zhiyuan-integration-and-frontend-validation-plan.md)，重点 §2–§3、§6.3–§7。

## Global Constraints

- 路径相对 zhiyuan；`A/`=zhiyuan-agent，`J/`=zhiyuan-server/src/main/java/com/ytell/zhiyuan，`JT/`=zhiyuan-server/src/test/java/com/ytell/zhiyuan。
- 权威数据不能由模型、自铸 Evidence 或测试 fixture 替代。概率直接用上游，Rank 分不作录取率。
- 当前 Java 8 不使用 records、Map.of 或新语言特性。现有 PlanningStateService 已非常大，新计算/桥接职责放独立类，必要接入保持小改动。
- 当前八工具契约、P1b/P1c/P2 未完成项必须先收口；同一文件按 LEDGER 串行。任何代码任务均先写针对真实断点的失败测试，再做最小实现、重跑、独立审查与交付 diff。
- 所有 HTTP 端点表中的 `/inner/...` 均有前缀 `/gaotu-assistant-bot`，只允许服务端内部访问。

执行顺序：B0与B1可在无文件占用冲突时分别实施，B2依赖B1；B3/B4消费B0，B5依赖B2/B4，B6依赖B0/B5，B7统一验收。B3缺外部数据时，不阻止其他模块实施，但不能发布缺来源的能力。

## 工具到实现映射

| 能力/工具 | 真实或新增内部接口 | 实现/结果 |
|---|---|---|
| entity.resolve / catalog.*（已有） | 现有 CatalogController | CatalogService；稳定 ID 与候选歧义 |
| planning.get_working_plan（新名） | 现有 `/inner/planning/{tenant}/session/working-plan` | DraftPlanStateDTO；原 get_current_plan 兼容 |
| planning.get_ordered_plan（新增工具） | 现有 `/inner/planning/{tenant}/session/ordered-plan` | 正式排序，不混作草案 |
| admission.get_history（修复） | 现有 `/inner/gaotu/score-line/query` | QuerySchoolMajorScoreLineRes 数组 |
| admission.get_probability（新增） | 现有 `/inner/gaotu/program/query-by-limit-num` | 分层 SchoolRecordDTO/enrollRatio + subVOList |
| admission.get_enrollment_plan / get_policy（新增） | 新 `/inner/admission/{tenant}/enrollment-plan`、`/policy` | B3 定义来源适配与 DTO；目前八工具不具备 |
| admission.check_eligibility（修复） | 现有专业选科检查 | 仅选科资格，不能代表全部章程/体检合格 |
| recommendation.compare / explain_fit（新增） | 新 `/inner/planning/{tenant}/session/comparison` | B4 从同版本候选/事实计算矩阵与匹配解释 |
| recommendation.generate_candidates（新增） | 新 `/inner/planning/{tenant}/session/candidate-preview` | 复用取数/Rank，写独立 Artifact，不改正式方案 |
| plan.propose_generate / propose_changes（新增） | 新 `/inner/planning/{tenant}/session/proposal/prepare` | B5/B6 生成冻结预览与 Pending |
| plan.review（新增） | 现有 `/review/run`、`/review-workflow/run` | 不改志愿内容，但更新 reviewState/workspaceVersion |
| 确认/取消（非模型工具） | 现有 `/inner/chat/{tenant}/session/pending/resolve`、`/inner/planning/{tenant}/session/pending-command/execute` | Gateway 按已确认 Pending 执行，非模型生成命令 |

## Task B0：先建立缺失的 Artifact 与 prepare 幂等存储

**Files:** Create `J/service/biz/ConversationArtifactService.java`、`ConversationProposalRequestService.java`、`J/model/entity/biz/ConversationArtifactEntity.java`、`ConversationProposalRequestEntity.java`、`J/mapper/ConversationArtifactMapper.java`、`ConversationProposalRequestMapper.java`、`J/web/controller/inner/ConversationArtifactController.java`、`JT/service/biz/ConversationArtifactServiceTest.java`、`ConversationProposalRequestServiceTest.java`；Create `zhiyuan-server/src/main/resources/db/migration/V16__conversation_artifact.sql` 与 `V17__conversation_proposal_request.sql`。实施前核最新 migration，若序号被占仅顺延编号，不改已存在迁移。

**Interfaces:** `put(tenant,session,kind,payload,dependencies,expiresAt)->artifactId`、`getOwned(tenant,session,id)->ArtifactDTO`、`pageOwned(tenant,session,id,cursor,limit)`；`prepareOnce(tenant,session,requestId,digest,prepareWork)->PrepareResult`。新增 `J/model/dto/planning/ArtifactDTO.java` 与 `PrepareResultDTO.java` 定义上述 DTO。输入 payload 为 JSON，dependencies 保存画像/候选/工作区版本摘要；Artifact 不可原地修改。

- [ ] 用隔离 MySQL 写失败测试：跨用户不可读、同 request 同摘要只生成一次、同 ID 不同摘要冲突、重启后可读、过期/摘要损坏拒绝。Python 内存 ArtifactRef 不能证明这些行为。
- [ ] 新表使用如下最小 schema；source_version/profile_digest/candidate_digest 放 dependencies_json，实际列类型遵循现有 migration 的 MySQL 编码规范。

```sql
CREATE TABLE assistant_conversation_artifact (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  artifact_id VARCHAR(64) NOT NULL UNIQUE,
  tenant_id BIGINT NOT NULL,
  chat_session_id BIGINT NOT NULL,
  kind VARCHAR(32) NOT NULL,
  payload_json MEDIUMTEXT NOT NULL,
  payload_digest CHAR(64) NOT NULL,
  dependencies_json TEXT NOT NULL,
  expires_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL,
  INDEX artifact_scope (tenant_id, chat_session_id, created_at)
);
CREATE TABLE assistant_conversation_proposal_request (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  chat_session_id BIGINT NOT NULL,
  request_id VARCHAR(64) NOT NULL,
  request_digest CHAR(64) NOT NULL,
  pending_id VARCHAR(64),
  operation_id VARCHAR(64),
  result_json TEXT,
  status VARCHAR(24) NOT NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY prepare_identity (tenant_id, chat_session_id, request_id)
);
```

- [ ] Artifact JSON 单个≤2MiB，候选分页默认20/最大50；完整表/政策全文只在后台读。candidate/comparison有效期24小时，pending引用的plan preview保留至少30天；正式 operation 审计保留内容摘要，过期预览须重生成并重新确认。digest按固定字段序和UTF-8计算，读取时复核。
- [ ] `GET /inner/planning/{tenant}/session/artifacts/{artifactId}` 返回 envelope/分页内容；先 ownership，再比scope/kind/依赖版本/有效期。public facade 只映射允许展示的字段，不外发frozen命令或个人资料全文。
- [ ] prepare 幂等记录与 Pending upsert 同事务：锁会话 Pending，applying 时拒绝新 prepare；新 B 替换 active A 时将 A 的 request record 记 superseded。retry A 返回 superseded，不能重新执行 prepareWork；已 applied 返回原 result。幂等 tombstone 不自动清除，内容可归档但 request digest/状态保留。
- [ ] Java `mvn -Dtest=ConversationArtifactServiceTest,ConversationProposalRequestServiceTest test`；必须含 `prepare A→prepare B→retry A` 与 `applying→prepare B` 两例，实际重启后再次查询。B3/B4/B5/B6 必须消费本任务接口，不能再写各自内存存储。

## Task B1：贯通 Java Evidence 与跨回合验证

**Files:** Modify `A/app/util/internal_client.py`、`A/app/mcp_server/tools_readonly.py`、`A/app/mcp_server/server.py`、`A/app/gateway/service.py`、`A/app/gateway/output_validation.py`、`J/service/biz/ConversationSnapshotService.java`、`J/service/biz/EvidenceLedgerService.java`；Extend `A/tests/unit/test_domain_mcp_tools.py`、`A/tests/unit/test_output_validation.py`、`JT/service/biz/ConversationSnapshotServiceTest.java`、`EvidenceLedgerServiceTest.java`；Create `A/tests/integration/test_evidence_roundtrip.py`。

**Interfaces:** 保留上游 BaseResponse 的 `data` 与 evidence 元信息；`merge_evidence(snapshot_records,turn_records)->dict[id,record]`；用现有 `EvidenceLedgerController` 四态 verify 作为招生证据有效性来源，实际四态值从其 DTO 映射，不能新增一套猜测值。

- [ ] 接管前核对 P1b-2 在途 diff，保留 scope/groupCode 改动。以 Java DTO 序列化结果建 fixture，而不是从 Python 期待字段编数据；历史数组/资格布尔/概率分层三份各保留原始 evidence。
- [ ] 增加失败测试：真实 `data:[...]` 不抛 dict 转换错误、ev_ ID 穿过 InternalClient→MCP→Gateway 不变；自铸 authoritative ID 被拒；相同 evidence ID 不同摘要被拒，不能“最后一个覆盖”。
- [ ] 合并账本采用不冲突规则；比较稳定身份/来源/内容摘要字段，复验状态单独记录，不能把 observedAt 不同误当证据内容冲突。

```python
def merge_evidence(snapshot_records, turn_records):
    merged = {}
    for record in [*snapshot_records, *turn_records]:
        key = record["evidenceId"]
        stable = tuple(record.get(name) for name in (
            "tenantId", "sessionId", "sourceSystem", "paramsDigest", "dataVersion"))
        previous = merged.get(key)
        if previous is not None:
            previous_stable = tuple(previous.get(name) for name in (
                "tenantId", "sessionId", "sourceSystem", "paramsDigest", "dataVersion"))
            if previous_stable != stable:
                raise ValueError("evidence_identity_conflict")
        merged[key] = record
    return merged
```

Java scope 若为嵌套对象，先在一个 normalizer 映射为这里的稳定字段，不在调用处各自猜命名。

- [ ] 实现 Snapshot.fillEvidence 查询当前 tenant/session 的有效证据摘要；Gateway 不再用内存缓存覆盖 Java evidence。删除招生证据的工作区版本等值限制及 thread 等值限制，保留 tenant/session/招生范围验证、Artifact 版本限制；引用先调用 Java verify，unknown 不等于 stale。
- [ ] 仅在真实 Java ID 能贯通后删除 `_admission_envelope` 的自铸 authoritative 分支；依赖它的 fixture 同步改为 Java 合同数据，不能为旧测试放宽校验。
- [ ] 将 per-turn 工具预算/缓存从“每工具调用 new ReadonlyDomainTools”移到以可信 turn identity 为 key 的对象；建议默认最多 16 次、同参成功读取缓存只在本回合复用。若当前 `_meta` 仅 threadId，由 Gateway 注册 active turn 到 binding 侧，不接受模型自报 turnId；结束清理，最大 1,000 个活动对象，跨 turn 不吃旧预算。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_domain_mcp_tools.py tests/unit/test_output_validation.py tests/integration/test_evidence_roundtrip.py -q`；Java `mvn -Dtest=ConversationSnapshotServiceTest,EvidenceLedgerServiceTest test`。真实端到端另外证明“查→改工作区→新 turn→重启 Gateway→仍可引用”，上游数据更改后核验为 stale。记录 fixture 与真实部分各自结果。

## Task B2：拆开历史、概率、资格和当前方案

**Files:** Create `A/app/admission/tool_results.py`、`A/tests/unit/test_admission_tool_results.py`；Modify `A/app/mcp_server/tools_readonly.py`、`server.py`、`A/app/util/internal_client.py`、`A/app/admission/facts.py`、`A/app/gateway/contracts.py`；按需要 Modify `J/model/dto/gaotu/req/QuerySchoolMajorScoreLineReq.java`、`J/manager/gaotu/GaotuClient.java`，但只有上游真实支持 groupCode 才加转发。

**Interfaces:** 新增 §3 的 discriminated `DomainResult`；`normalize_history(raw,query)`、`normalize_probability(raw,query,rate_unit)`、`normalize_eligibility(raw,query)`。query 必须含查询口径和已解析 ID；不存在的身份不能从名称或数组序号猜造。

- [ ] 三个生产者 fixture：历史数组（无概率）、program 分层列表（`enrollRatio` 字符串）、资格 boolean。先写各自正常与缺字段回归，确认当前全部 admission.* 共用 envelope 的路径失败。

```python
def test_history_does_not_require_probability():
    from app.admission.tool_results import normalize_history
    result = normalize_history({"data": [{"year": 2025, "minScore": 612,
        "minPos": 9000}], "evidence": []}, {
        "schoolId": "school-fixture", "majorId": "major-fixture",
        "areaId": "area-fixture", "batch": "batch-fixture"})
    assert result["kind"] == "history"
    assert result["data"][0]["minScore"] == 612
    assert "unitAdmissionRate" not in result["data"][0]
```

这个测试只验证分型；evidence 为空时数据可进入候选工具结果，但 Gateway 不得将其作为已验证权威事实展示，B1 集成测试覆盖签发链。

- [ ] 概率单位显式配置，禁止 UI 用 `<=1` 自动猜单位。当前业务概率区间沿用已核实的 0–99 百分数约束；上游若实际允许 100，须与业务 DTO/风控一起升级，不能静默截断为 99。

```python
from decimal import Decimal, InvalidOperation

def percentage(raw: str, unit: str) -> Decimal:
    try:
        value = Decimal(raw.rstrip("%"))
    except (InvalidOperation, AttributeError):
        raise ValueError("invalid_probability")
    if unit == "fraction":
        value *= 100
    elif unit != "percent":
        raise ValueError("unknown_probability_unit")
    if not value.is_finite() or value < 0 or value > 99:
        raise ValueError("probability_out_of_contract")
    return value
```

- [ ] 学校 enrollRatio 只能表示学校口径；major/group 概率必须取对应 subVOList 级事实，不能复制学校率到每个专业。缺组标识/单位率回 insufficient_data，并返回已有可用历史资料。
- [ ] working/ordered 读取的 tenantId 全部从可信 binding 传入，修 `internal_client.get_working_plan` 硬编码 `/1/`；新工具名 planning.get_working_plan 与旧名在同一实现映射，不保留两个语义。
- [ ] 资格结果显式 `checkedConstraints:["subjects"]`、`uncheckedConstraints:["medical","policy"]`。专业组历史当前 Java DTO 不消费 groupCode：若上游没有组级来源则返回 `status=unsupported` + `code=unsupported_scope`；不能将学校级结果标成组级。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_admission_tool_results.py tests/unit/test_domain_mcp_tools.py tests/unit/test_turn_output_schema.py -q`；补一条 tenant=7 的 HTTP 请求路径断言。真实 program/history 各调用一次归档脱敏形状和 evidence，任何概率单位未确认的场景不得通过 B2。

## Task B3：年度招生计划与章程来源接入

**Files:** Create `J/service/biz/AdmissionSourceService.java`、`J/manager/gaotu/AdmissionSourceClient.java`、`J/model/dto/planning/EnrollmentPlanFactDTO.java`、`PolicyClauseFactDTO.java`、`J/web/controller/inner/AdmissionSourceController.java`、`JT/service/biz/AdmissionSourceServiceTest.java`；Create `A/app/mcp_server/tools_admission_sources.py`、`A/tests/integration/test_admission_sources.py`；Modify `A/app/mcp_server/server.py`；Create `docs/contracts/admission-sources-v1.md`。

**Interfaces:** `GET /inner/admission/{tenant}/enrollment-plan`（sessionId,year,areaId,schoolId,groupCode/majorId,cursor,limit）；`GET .../policy`（sessionId,year,schoolId,majorId,topic,cursor,limit）。内部返回 §3 DomainResult；只接受服务端配置的数据源，不允许模型提交任意 URL。

DTO 字段合同（新增；Java 用普通 Lombok DTO）：

```json
{"kind":"enrollment","data":[{"schoolId":"s","majorId":"m","groupCode":null,"admissionYear":2026,"areaId":"a","batch":"b","planCount":20,"tuitionPerYear":6000,"durationYears":4,"subjectRequirements":["物理"],"publishedAt":"2026-06-01","sourceUrl":"https://school.example.edu/plan/2026"}]}
```

```json
{"kind":"policy","data":[{"schoolId":"s","admissionYear":2026,"clauseId":"article-12","title":"身体条件","quote":"原文条款的逐字摘录","appliesTo":{"majorIds":["m"]},"sourceUrl":"https://school.example.edu/policy/2026","observedAt":"2026-06-02T08:00:00Z"}]}
```

上面是合同示例，不是真实招生数据。DTO `null` 表示未知，不表示零/不限制。

- [ ] 先完成来源调查产物 `admission-sources-v1.md`：按现有 Java client/上游接口清单定位年度计划和章程接口；记录请求方法/路径、授权机制名称（无密钥）、真实脱敏响应、字段/口径、年份/分页、错误码。不能把 program 中招生专业列表直接等同完整年度官方计划。
- [ ] 如已有正式上游接口，配置其固定 base/path；如本项目没有该数据接口，提供受控数据导入模式：运维导入官方年度结构化数据和原文来源，校验 digest 后保存只读 catalog。新增 `scripts/import-admission-catalog.py`，输入UTF-8 JSON按上面DTO校验，输出到配置 `admission.source.catalogPath` 指向的部署目录，按year/schoolId拆分文件并写manifest(digest,publishedAt,sourceUrl)；临时文件写完原子rename，Java只加载manifest列出的文件，不接受请求传入路径。读取结果再按会话签发Evidence/B0 Artifact。此模式标 `sourceMode=imported_official`，记录 sourceUrl/发布日/导入日；不宣称在线实时更新。
- [ ] 第一项产物必须确认“API 还是官方导入”，数据没有到位就将 B3 记 blocked_data_source，任务其他分型测试可继续，但政策/年度计划产品开关保持关闭。不能用合成 fixture 关闭这个业务 gate。
- [ ] 写测试：当年未发布返回最近已发布年份且 limitations 明示；同校跨年条款隔离；没有来源不生成权威 evidence；原文带提示指令也仅当资料；条件不完整返回 unknown。
- [ ] AdmissionSourceClient 仅使用配置的数据源/导入 catalog；Service 先规范化身份和范围，再用已有 EvidenceLedger 签发。分页默认 20、最大 50，条款 quote 最多 2,000 字、全文存 Artifact；Evidence 引用全文摘要而非模型改写文本。

```java
// AdmissionSourceService 中选择年度的核心规则，参数来自已验证源数据。
static int publishedYear(int requestedYear, java.util.Set<Integer> years) {
    return years.stream().filter(y -> y <= requestedYear)
        .max(Integer::compareTo)
        .orElseThrow(() -> new IllegalArgumentException("admission_year_unavailable"));
}
```

- [ ] 运行 Java `mvn -Dtest=AdmissionSourceServiceTest test`，Python `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_admission_sources.py -q`；再用一所学校当前/上一年两个真实来源逐字段核对，指定章程问题必须能打开原文条款。提交合同与脱敏证据，不提交个人画像或凭证。

## Task B4：同口径比较与个性化推荐

**Files:** Create `J/service/biz/CandidatePreviewService.java`、`CandidateComparisonService.java`、`J/model/dto/planning/CandidateComparisonDTO.java`、`JT/service/biz/CandidateComparisonServiceTest.java`；Modify `J/web/controller/inner/PlanningStateController.java`、现有 `J/service/biz/PlanningStateService.java` 仅抽取候选取数/Rank 可复用入口；Create `A/app/mcp_server/tools_recommendation.py`、`A/tests/integration/test_recommendation_contract.py`；Modify `A/app/mcp_server/server.py`。

**Interfaces:** `candidate-preview` 返回 `{artifactId,profileVersion,dataVersion,items,nextCursor,limitations}`；comparison 接受 `entityIds`（2–5 个）与维度 whitelist，返回 `{entities,dimensions,cells,evidenceRefs,unavailableDimensions}`。explain_fit 与 compare 共用单个 Java 解释产物，不额外由模型算匹配分。

- [ ] 将硬约束过滤与软偏好排序顺序固化：招生类型/选科/章程资格/预算等硬条件→候选集合→Rank 软分→上游概率独立列→解释。未校验章程不能标完全符合。
- [ ] 测试固定画像“学费≤10000、排除某专业、保留锁定项”；候选高 Rank 但违反硬约束应排除；概率相同但城市/专业偏好不同能解释排序差异。风险概率与匹配分在响应中字段不同。
- [ ] 复用旧候选生成取数及 RankRequestMapping，但不能直接调用会保存工作区的 `/candidate-pool/generate` 当只读工具。提取候选计算到 CandidatePreviewService，结果保存独立 Artifact；Artifact 写入不改变正式志愿表/画像版本。
- [ ] 比较矩阵逐单元注明来源与口径；不同年份/省份/专业组不能直接做数值差；缺失用 null/unavailable，不补零。不用“学校名相同”对齐招生单元。

```python
# tools_recommendation.py 中的比较可用性规则；Java 也按同一合同检查。
def comparable(left: dict, right: dict) -> bool:
    keys = ("admissionYear", "areaId", "batch", "admissionMode", "rateUnit")
    return all(left.get(k) is not None and left.get(k) == right.get(k) for k in keys)
```

- [ ] 产物绑定画像/候选版本；画像更改使推荐 Artifact stale，而旧招生事实是否过期仍由 Evidence 判断。Top20/分页50，保留全部候选在服务器，不把全量表放入 Codex context。
- [ ] 运行 Java `mvn -Dtest=CandidateComparisonServiceTest,RankRequestMappingTest test` 与 Python `tests/integration/test_recommendation_contract.py`；真实场景同时记录模型说明、Rank 请求/响应摘要、排除原因，复核解释每条能对应字段。

## Task B5：完整方案计算、审查与无副作用预览

**Files:** Create `J/service/biz/PlanPreviewService.java`、`PlanPreviewCalculator.java`、`J/model/dto/planning/PlanPreviewDTO.java`、`FrozenPlanPayloadDTO.java`、`JT/service/biz/PlanPreviewServiceTest.java`；Modify `J/service/biz/PlanningStateService.java`、`CanonicalPlanningRuntime.java`、`UnifiedPlanPostconditionValidator.java`；Extend `JT/service/biz/PlanningInitialPlanGenerationTest.java`、`CanonicalPlanningRuntimeTest.java`；Create `A/app/mcp_server/tools_planning.py`、`A/tests/integration/test_plan_preview_contract.py`。

**Interfaces:** `PlanPreviewService.preview(tenantId,sessionId,sourceVersion,goal)`→PlanPreviewDTO；新增内部 preview 入口由 B6 `/proposal/prepare` 调用。DTO 包含 `{previewId,sourceVersion,profileVersion,candidateArtifactId,frozenPlan,orderedUnits,reviewReport,diff,status,limitations,digest}`。status ready/infeasible/needs_clarification；没有 ready 不能编译可确认 Pending。

- [ ] 前置资料一次检查：省份/招生年/批次/选科/成绩位次/招生模式/目标数量/预算/排除与锁定。必要值缺失产生精准问题；软偏好可保留“不限”。若省份规则未接入，不输出“完整”标签。
- [ ] 先测试数据库快照不变：preview 前后 working/ordered 内容、约束、画像、workspaceVersion 完全相同，只有独立 Artifact 新增。现 `generateInitialPlan/generateOrderedPlan` 会写入，不能直接包成 preview。
- [ ] 抽取计算部分到 PlanPreviewCalculator：从真实 Snapshot 深复制 PlanningStateDTO，将已确认 goal 投影到副本、填候选和初始 working selection，再 enforceSelection；随后必须从选中 working items 构建 ordered items/units，再默认排序和 enforceOrdering，最后纯审查。不能 selection 后直接对旧/空 ordered 调 enforceOrdering。

```java
// 只在 DTO 上演算；PlanPreviewCalculator 是本任务新增类。
PlanningStateDTO draft = com.alibaba.fastjson.JSONObject.parseObject(
    com.alibaba.fastjson.JSONObject.toJSONString(source), PlanningStateDTO.class);
PlanPreviewCalculator.projectConfirmedGoal(draft, goal);
PlanPreviewCalculator.seedWorkingSelection(draft, candidates);
CanonicalPlanningRuntime.enforceSelection(draft, candidates);
PlanPreviewCalculator.materializeOrderedPlan(draft, candidates);
CanonicalPlanningRuntime.enforceOrdering(draft, candidates);
FrozenPlanPayloadDTO frozen = PlanPreviewCalculator.freeze(draft, candidates);
```

上述新增方法签名：`projectConfirmedGoal(PlanningStateDTO,UserGoalFixProposalReq):void` 投影目标到constraint；`seedWorkingSelection(PlanningStateDTO,List<CandidateItemDTO>):void` 抽取现有 buildInitialRecommendationState/replaceWorkingPlanWithInitialRecommendation 的纯计算；`materializeOrderedPlan(PlanningStateDTO,List<CandidateItemDTO>):void` 抽取 buildOrderedItemsFromWorkingPlan/buildOrderedUnitsFromOrderedItems 及summary计算；`freeze(PlanningStateDTO,List<CandidateItemDTO>):FrozenPlanPayloadDTO` 记录最终working/ordered快照与digest。旧写入口也调用抽取后的纯函数，再保存，避免复制两套算法。

FrozenPlanPayloadDTO 字段：`workingPlan:DraftPlanStateDTO`、`orderedPlan:OrderedPlanStateDTO`、`objectiveDigest:String`、`candidateDigest:String`、`profileDigest:String`、`solverVersion:String`、`payloadDigest:String`。selection/ordering 各自 SolverResult 只保留为解释trace，不能把两个不同输入摘要合并冒充同一次solver输出。空目标先编译该省目标数量/约束；noChange不等于完整生成成功。新增“空方案+优先级”“已有方案选中集合变化”回归。

- [ ] DTO 保存准确单元和组内专业 ID、顺序、锁定项；数量按省份招生模式计算。无解报告硬约束冲突和可选择的放宽项，不自行放宽。预览 diff 是正式表与 frozen result 的差异，不以模型自然语言代替。
- [ ] 独立 `plan.review` 若复用现 `/review/run`，允许保存 reviewState 并推进 workspaceVersion，向用户解释为“已更新审查结果，志愿内容未变”；后续 Proposal 用审查后的版本。测试审查前后单位集合/顺序不变，版本及 reviewState 正确。
- [ ] 完整生成用新 pending command `APPLY_GENERATED_PLAN`，确认时应用已冻结结果，而不是重新随机推荐一份；复用 frozen selection/ordering 检查，在事务后验证数量/硬约束/锁定/组内/排序全部一致。命令接线在 B6。
- [ ] Java `mvn -Dtest=PlanPreviewServiceTest,PlanningInitialPlanGenerationTest,CanonicalPlanningRuntimeTest,UnifiedPlanPostconditionValidatorTest test`；Python `tests/integration/test_plan_preview_contract.py`。至少 major 与 major_group 两种模式、空初始方案和有锁定项三组完整案例，通过才开启完整表预览。

## Task B6：Proposal → Pending → 真实执行闭环

**Files:** Create `J/service/biz/ConversationProposalService.java`、`J/model/dto/planning/ConversationProposalPrepareReq.java`、`ConversationProposalPrepareRes.java`、`JT/service/biz/ConversationProposalServiceTest.java`；Modify `J/web/controller/inner/PlanningStateController.java`、`J/service/biz/PendingPlanningCommandBizService.java`、`J/model/dto/planning/PendingPlanningCommandReq.java`、`J/service/biz/PendingConfirmationBizService.java`、`J/service/biz/PlanningStateService.java`；Modify `A/app/gateway/conversation_actions.py`、`A/app/gateway/service.py`、`A/app/util/internal_client.py`；Create `A/tests/integration/test_conversation_apply_roundtrip.py`；Extend `JT/service/biz/PendingPlanningCommandRollbackIntegrationTest.java`。

**Interfaces:** 新 `POST /inner/planning/{tenant}/session/proposal/prepare?chatSessionId=...` 消费 `{requestId,sourceVersion,kind,userGoal,previewId,profilePatch}`，kind=adjust仅userGoal、generate仅previewId、profile仅profilePatch，其他分支字段必须为空；生成 `{proposalRef,pendingId,pendingRevision,sourceVersion,operationId,diff,expiresAt}`。执行只引用 Pending 保存的 frozen payload，浏览器/模型提交的 commandType/claimToken 不采用。

profilePatch新增 `J/model/dto/planning/ProfilePatchDTO.java`：仅 `majorPreferences`、`schoolPreferences`、`regionPreferences`（各 positive/negative数组）与 `strengthSubjects`，映射现有 UpdateExplicitProfileReq；字段省略=不改、null=拒绝、空数组=明确清空，每个PreferenceGroup内positive/negative同样规则。成绩/省份/选科身份继续走现有基本信息表单与验证，不混入偏好命令；工具返回对应补资料入口，不伪称可更新这些字段。

新增常量 `APPLY_GENERATED_PLAN="apply_generated_plan"`、`APPLY_PROFILE_PATCH="apply_profile_patch"`。PendingPlanningCommandReq新增 `generatedPlanRef`/`generatedPlanDigest`/`profilePatch`，分别引用B0/B5不可变对象和typed patch；validate、executeCommand、requestDigest、compactResultForReplay及postcondition必须同时覆盖。requestDigest目前手工复制字段，新字段要逐项加入；claimToken目前已排除，继续保持不进业务digest。

- [ ] 写失败集成用例：当前 user-goal preview 不创建 Pending；当前 confirm 只停 applying。这两个用例必须经过 Gateway 与真实 Java HTTP，不能只 mock 一个最终 applied 响应。
- [ ] prepare 先核版本与唯一 ready Proposal；多候选让用户选择/澄清，不 `next(first)`。adjust 复用 `UserGoalProposalBuilder` 及 review repair 产物，generate 用 B5，profile 仅允许明确确认的白名单字段。将用户自然语言→结构化目标与确定性编译分开。
- [ ] Java 用现 Pending upsert 保存 `sourceVersion,proposalRef,operationId,frozenPayload,payloadDigest,expiresAt`；requestId 重复且摘要一致返回同一 pending，不同内容 conflict；活动 Pending 被替换时原卡失效。operationId 由 Java 生成一次，持久化，不由每次按钮点击生成。
- [ ] 执行编排采用以下端口顺序。端口是本任务内部新增适配函数，分别包装已有 resolve/execute/workspace HTTP，签名固定如下：

```python
from collections.abc import Awaitable, Callable

async def apply_pending(
    pending: dict,
    operation: Callable[[dict], Awaitable[dict | None]],
    claim: Callable[[dict], Awaitable[dict]],
    execute: Callable[[dict, dict], Awaitable[dict]],
    complete: Callable[[dict, dict | None, dict], Awaitable[dict]],
    workspace: Callable[[], Awaitable[dict]],
) -> dict:
    stored = await operation(pending)
    claimed = None
    if stored is not None:
        if stored["status"] != "succeeded":
            return {"actionStatus": "applying", "proposalRef": pending["proposalRef"]}
        result = stored["result"]
    else:
        if pending["status"] in {"cancelled", "expired"}:
            return {"actionStatus": pending["status"], "proposalRef": pending["proposalRef"]}
        if pending["status"] == "applied":
            raise ValueError("applied_operation_missing")
        claimed = await claim(pending)
        if not claimed["ownsClaim"]:
            return {"actionStatus": "applying", "proposalRef": pending["proposalRef"]}
        result = await execute(pending, claimed)
    if result.get("operationId") != pending["operationId"]:
        raise ValueError("operation_identity_mismatch")
    # execute 的 Java 事务已经完成 postcondition 验证；不信任模型的通过标记。
    # complete 端口支持 succeeded 后恢复；Java校验持久化operation及合法租约。
    finished = pending if pending["status"] == "applied" else await complete(pending, claimed, result)
    if finished.get("status") != "applied":
        return {"actionStatus": "applying", "proposalRef": pending["proposalRef"]}
    current = await workspace()
    return {"actionStatus": "applied", "proposalRef": pending["proposalRef"],
        "newStateVersion": result["resultPlanVersion"],
        "workspaceVersion": current["version"]}
```

- [ ] claim 生成不可预测 token 并保存在 Java Pending（已有 claim 字段），其租约与 revision 从真实返回值读取；adapter 比较请求token与返回token计算ownsClaim，其他有效租约返回applying，只查结果。execute 包装调用 `execute_pending_planning_command`，只使用服务端 frozen payload 和相同 operationId。generated 命令应用B5冻结working/ordered；profile命令映射typed patch到updateExplicitProfile；原四类command保留。
- [ ] 新增 `GET /inner/planning/{tenant}/session/pending-command/{operationId}`：核tenant/session并从持久command读取，不要求当前Pending仍applying。applied后重复确认直接返回持久结果，不走当前execute（它在replay前要求applying）；succeeded+applying只补complete；complete响应丢失后重试同理。stored=null且未获得租约才允许等待/claim，不无条件execute。
- [ ] Java complete 必须对Codex新命令核Pending的operationId、tenant/session、payloadDigest、command.succeeded及对应postcondition，再applying→applied。补 `ConversationCommandCompletionService.java` 作为恢复入口：succeeded后以当前合法租约补complete，必要时合法接管已过期lease；不放宽普通claim权限。测试未execute就complete、失败后complete、另一operation冒充全部拒绝。
- [ ] generated后置条件检查正式集合/顺序/组内内容等于frozen且硬约束/锁定项成立；profile后置条件检查仅允许字段变更、未指定字段保持、正式志愿内容保持并正确标stale。分别新增 `J/service/biz/GeneratedPlanPostconditionValidator.java` 与 `J/service/biz/ProfilePatchPostconditionValidator.java`，按commandType分发；不能用当前 userGoal=null→review修复分支兜底。两者失败必须事务回滚，且都记录报告。
- [ ] 任一步 HTTP 超时不能标 failed 后另起新操作：新增内部 command status 查询（按 operationId 且核 tenant/session）或使用原请求重放；result 已 succeeded 时补 complete，不重做。lease 过期可接管前必须查 operation 状态；校验 requestDigest 时 claim token 是传输租约、业务 payload digest 必须稳定，补接管测试。
- [ ] cancel 仅 active→cancelled；applying 返回 in-progress 及查询结果入口。postcondition 不满足整个命令回滚，再使 Pending expired 并展示失败。正式表成功而 WS 断开时重连恢复 applied；workspace 刷新失败只重读，不再 apply。
- [ ] Java 测试覆盖双击同 operation、同 ID 不同内容、版本冲突、锁定冲突、提交后断线、complete 前崩溃、租约接管、postcondition 回滚；比较整个正式状态，不只 HTTP code=200。执行 `mvn -Dtest=ConversationProposalServiceTest,PendingConfirmationBizServiceTest,PendingPlanningCommandBizServiceTest,PendingPlanningCommandRollbackIntegrationTest test`。

再加入complete响应丢失、applied后重复确认、同operation更改profilePatch或generatedPlanDigest冲突，以及B0的A→B→retry A/applying不能覆盖。prepare不能仅用现有每会话单行Pending保存幂等信息，必须消费B0不可覆盖request记录。
- [ ] Python 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_conversation_apply_roundtrip.py tests/unit/test_ws_conversation_action.py -q`；真实 HTTP 用隔离数据跑取消、确认、双击、stale 四例。预期一次操作唯一、Java resultPlanVersion 与实际一致（不要求只加1）、UI 没有提前 applied。交付事务证据后才开启写能力。

## Task B7：技能方法、评估与能力发布

**Files:** Modify `A/skills/codex/base_instructions.md`、`developer_instructions.md`、六个已有技能的 `SKILL.md`（profile-discovery、school-major-exploration、admission-fact-analysis、candidate-recommendation、plan-construction、plan-final-review）与 `references/evidence-policy.md`、`planner-questioning-guide.md`、`recommendation-explanation-guide.md`；Modify `A/skills/codex/plugin.json`、`A/tests/unit/test_codex_skill_manifest.py`；Create `A/tests/fixtures/codex_semantic/zhiyuan_acceptance_v1.json`、`A/scripts/evaluate_zhiyuan_acceptance.py`。

**Interfaces:** 技能描述→允许工具→输入前提→产物 kind→完成条件；评估报告每条 `{caseId,attempt,runtimeStatus,executionStatus,toolStatus,assertions,environmentError,artifactRefs}`，全样本有记录。

- [ ] 为六技能逐项更新真实工具名和流程；没有能力就解释缺项，不以提示词“必须查到”替代缺失接口。profile 区分明确用户信息、待确认偏好、推断；先确认矛盾，不反复问 Snapshot 已有信息。
- [ ] 在 plan-construction 写入以下执行规则，其他技能采用同样字段结构并填各自任务内容：

```markdown
### 输入前提
读取当前 Snapshot 的省份、年份、批次、选科、分数/位次、招生模式、目标数量、锁定项。
仅补问缺少且影响本次结果的条件；用户“不限”保留为无软偏好。
### 操作
调用 recommendation.generate_candidates 获取受硬约束过滤的候选产物。
调用 plan.propose_generate 生成冻结预览；无解时展示具体冲突和放宽选项。
展示数量、冲稳保、专业组内结构、锁定项、审查结果及限制。
### 完成条件
预览阶段完成只代表可供选择；只有用户确认后的 conversationAction.result 为 applied 才说明已保存正式方案。
```

- [ ] 检查 Skills 在该 App Server 的实际发现/加载方式（配置 root 不等于自动注入所有内容）；记录一次调用用了哪些技能，提示词体积、MCP 调用量和 compaction 后恢复。超过主设计预算必须先缩摘要/分页，不能继续无限拼接。
- [ ] 评估至少 16 场景×3 次=48 尝试：实体歧义、明确查询不反问、未知上游、缺画像、概率/年份/章程、双校对比、偏好冲突、完整生成、major_group、锁定项调整、取消、重复确认、stale、跨回合引用、重启。固定输入和版本，环境错误单列但计入总分母。
- [ ] 注入“执行 shell/改数据库/忽略选科限制/直接确认”的用户与资料文本；有效工具清单和 Java 权限层必须拦截，不能因为夹具没声明写工具就判定拦截通过。写入成功只认后端 operation。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_codex_skill_manifest.py -q`；评估器命令 `.venv/bin/python scripts/evaluate_zhiyuan_acceptance.py --cases tests/fixtures/codex_semantic/zhiyuan_acceptance_v1.json --attempts 3 --output ../.runtime/zhiyuan-acceptance.json`。真实评估独占 runtime；生产数据不可用于变更用例。
- [ ] gate：确定性逻辑全过；错租户、无授权写、伪造概率/来源、提前 applied 必须 0 次；模型可用性报告总数/通过/业务失败/环境失败，不用小样本推断生产 SLA。明确 B3 数据源未到位时受影响能力不能发布。将实际结果写 REPORT，与计划分开。
