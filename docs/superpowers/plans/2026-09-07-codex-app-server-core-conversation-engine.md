# Codex App Server 核心对话引擎第一期实施计划

> 面向执行 Agent：必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项实施本计划；所有步骤使用复选框跟踪状态。

**目标：** 在不改变现有最终方案写入链路的前提下，交付一个可离线回放、生产 Shadow 和只读 Canary 的 Codex App Server 对话 Harness 第一版。

**架构：** 现有 zhiyuan-agent 保留对外 WebSocket 兼容协议，新增 Conversation Gateway、HarnessClient、版本化 Turn Snapshot、可信 Thread binding、只读 Domain MCP 和结构化 Evidence/Artifact 协议。Codex App Server 只承担 Thread/Turn、Skill、流式事件和模型编排；Java、数据库、现有招生单元录取率引擎、Rank、Solver 和 Proposal/CAS 仍是业务权威。第一期所有写能力继续走旧链路，Codex 只允许只读工具并以 Shadow/Canary 方式验证。

**技术栈：** Python 3.10、FastAPI、aiohttp、Pydantic、pytest；Java 8、Spring Boot、MyBatis-Plus、Flyway、JUnit 5、Maven；Codex App Server commit 89650c6，stdio JSONL transport；Domain MCP 使用与固定 Codex 版本兼容的 Python MCP SDK，版本写入 zhiyuan-agent/constraints.txt；SQLite 仅用于单实例离线回放，生产 binding 使用 Java 持久化表。

---

## 0. 实施边界和硬规则

本计划是第一期独立可验收增量，不在同一轮同时改造推荐算法、Solver、最终确认写链路和完整前端工作台。第一期必须交付可运行的 Harness、只读业务工具、Evidence/Artifact 校验和 Shadow 评测；第二期再基于真实差异拆分 Rank、Review Policy 和 Solver 计划。

执行期间遵守：

- 保留工作区已有未提交改动；修改重叠文件前先读取 git diff -- <file>。
- 不删除或回退现有 zhiyuan-agent 工具、Skill、WebSocket 兼容路径。
- 不让模型传入可信 userId、sessionId、tenantId 或 threadId。
- 不把 App Server dynamicTools 作为业务工具平面；固定业务工具通过 MCP 配置加载。
- 不开放 shell、文件写入、Git、浏览器、网络搜索、子 Agent 和任意代码执行。
- Shadow 模式所有 profile.propose_patch、plan.propose_changes、plan.propose_finalize 和旧链路 apply 都必须拒绝执行。
- 任何状态版本、Evidence、Artifact 或 binding 校验失败都必须 fail closed，返回结构化错误。
- 每个任务完成后先运行任务内测试，再由执行者提交一个小提交；提交只包含该任务声明的文件。

任务依赖顺序固定为 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11。任务 4 的 binding 验证是第一期 Go/No-Go 门槛；若为 NO-GO，只完成 Harness、协议和报告，不接入真实 Domain MCP。任务 9 的前端接入依赖任务 8 的稳定事件协议，但不阻塞任务 10 的离线回放。

## 1. 文件职责映射

### 1.1 Python 新增

- zhiyuan-agent/app/harness/protocol.py：App Server JSONL JSON-RPC 请求、响应和通知模型。
- zhiyuan-agent/app/harness/client.py：初始化、请求关联、通知分发、断线和进程生命周期。
- zhiyuan-agent/app/harness/codex.py：Codex thread/start、thread/resume、thread/inject_items、turn/start、turn/steer、turn/interrupt、skills/list 适配。
- zhiyuan-agent/app/harness/binding.py：Thread binding 注册、签名 handle、过期和能力校验。
- zhiyuan-agent/app/gateway/contracts.py：Gateway 输入、Snapshot、StatePatch、Artifact、Evidence、结构化输出和稳定事件。
- zhiyuan-agent/app/gateway/snapshot.py：Java 响应到紧凑 Snapshot 的投影和差异计算。
- zhiyuan-agent/app/gateway/output_validation.py：Evidence、Artifact、Proposal 引用和状态版本校验。
- zhiyuan-agent/app/gateway/event_adapter.py：Codex item 通知到 Zhiyuan WebSocket 事件的转换。
- zhiyuan-agent/app/gateway/service.py：新 Harness turn 编排，不复制旧 ChatService 业务逻辑。
- zhiyuan-agent/app/mcp_server/server.py：Domain MCP stdio 入口和工具注册。
- zhiyuan-agent/app/mcp_server/context.py：可信 binding 和 allowedCapabilities 解析。
- zhiyuan-agent/app/mcp_server/tools_readonly.py：第一期八个只读工具。
- zhiyuan-agent/app/mcp_server/response.py：统一工具信封和 Evidence 创建。
- zhiyuan-agent/constraints.txt：锁定 MCP SDK 版本。
- zhiyuan-agent/skills/codex/ 下六个规划 Skill 及 references。
- zhiyuan-agent/scripts/codex_app_server_poc.py：人工可运行的 PoC 检查器。
- zhiyuan-agent/scripts/codex_shadow_replay.py：固定快照和脱敏对话的 Shadow 回放器。

### 1.2 Python 修改

- zhiyuan-agent/app/config.py：新增 CODEX、GATEWAY、MCP 配置。
- zhiyuan-agent/app/util/internal_client.py：Snapshot、binding 和只读 Domain API 客户端方法。
- zhiyuan-agent/app/server.py：按配置选择 legacy、codex_shadow 或 codex_readonly。
- zhiyuan-agent/app/schemas/ws.py：增加稳定业务事件类型并保留已有 Literal 值。
- zhiyuan-agent/pyproject.toml：加入 MCP SDK 和测试依赖。

### 1.3 Java 新增

- zhiyuan-server/src/main/resources/db/migration/V13__add_codex_thread_binding.sql：Thread binding 表。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/CodexThreadBindingEntity.java：binding entity。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/CodexThreadBindingMapper.java：binding 查询和撤销。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationTurnSnapshotDTO.java：版本化 Snapshot。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationStatePatchDTO.java：状态增量。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationEvidenceDTO.java：Evidence 摘要。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CodexThreadBindingReq.java
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CodexThreadBindingRes.java
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotService.java：现有状态到 Snapshot 的投影。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/CodexThreadBindingService.java：绑定注册、解析和撤销。
- zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/CodexConversationController.java：Gateway 内部端点。

### 1.4 评测和文档

- zhiyuan-agent/tests/unit/test_harness_protocol.py
- zhiyuan-agent/tests/unit/test_codex_harness_client.py
- zhiyuan-agent/tests/unit/test_thread_binding.py
- zhiyuan-agent/tests/unit/test_snapshot_projection.py
- zhiyuan-agent/tests/unit/test_output_validation.py
- zhiyuan-agent/tests/unit/test_event_adapter.py
- zhiyuan-agent/tests/unit/test_domain_mcp_tools.py
- zhiyuan-agent/tests/integration/test_codex_app_server_poc.py
- zhiyuan-agent/tests/integration/test_shadow_gateway.py
- zhiyuan-agent/tests/fixtures/codex、mcp、shadow/
- zhiyuan-agent/docs/codex-app-server-poc-report.md
- zhiyuan-agent/docs/codex-shadow-runbook.md

## 2. 任务 1：冻结旧链路基线和回放样本

**目的：** 量化旧链路的工具调用、实体解析、响应延迟和方案差异，后续 Shadow 使用同一批输入和数据版本。

**文件：**

- Create: zhiyuan-agent/tests/fixtures/shadow/baseline_manifest.json
- Create: zhiyuan-agent/scripts/export_shadow_baseline.py
- Create: zhiyuan-agent/tests/unit/test_shadow_baseline_manifest.py
- Modify: zhiyuan-agent/examples/dialog_regression_runner.py（仅增加 JSONL 导出）
- Create: zhiyuan-agent/docs/codex-shadow-runbook.md

- [x] 步骤 1：写失败测试，固定 manifest 字段

    def test_baseline_manifest_requires_versions_and_cases():
        manifest = load_manifest("tests/fixtures/shadow/baseline_manifest.json")
        assert manifest["datasetVersion"]
        assert manifest["cases"]
        assert all(
            {"caseId", "sessionId", "input", "expectedMode"} <= set(case)
            for case in manifest["cases"]
        )

manifest 至少包含 12 个脱敏案例：普通招生查询、历年分数线、实体歧义、成绩缺失、方案只读审查、方案动作请求、待确认、状态过期、复合问题、重复问题、计划更新和数据不足。每个案例记录 caseId、sessionId、input、expectedMode、datasetVersion 和 writeAllowed=false。

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_shadow_baseline_manifest.py -q

预期：FAIL，manifest loader 和固定字段校验尚不存在。

- [x] 步骤 3：实现只读 manifest loader 和 JSONL 导出

export_shadow_baseline.py 只读取已有脱敏案例，不读取生产密钥、不写数据库。每行结果包含 caseId、toolCalls、resolvedEntities、responseType、latencyMs、writeAttempted 和 error。

- [x] 步骤 4：运行 GREEN 和静态检查

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_shadow_baseline_manifest.py -q
    .venv/bin/python -m compileall -q app scripts

预期：测试 PASS，compileall 返回 0。

- [x] 步骤 5：提交

    git add zhiyuan-agent/tests/fixtures/shadow/baseline_manifest.json \
      zhiyuan-agent/scripts/export_shadow_baseline.py \
      zhiyuan-agent/tests/unit/test_shadow_baseline_manifest.py \
      zhiyuan-agent/examples/dialog_regression_runner.py \
      zhiyuan-agent/docs/codex-shadow-runbook.md
    git commit -m "test: freeze conversation shadow baseline"

## 3. 任务 2：定义跨服务协议和版本化输出

**目的：** 先固定 Gateway、Java、MCP、前端之间的字段和错误语义，避免实现过程中从自由文本推导业务状态。

**文件：**

- Create: zhiyuan-agent/app/gateway/contracts.py
- Create: zhiyuan-agent/tests/unit/test_gateway_contracts.py
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationTurnSnapshotDTO.java
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationStatePatchDTO.java
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationEvidenceDTO.java
- Create: zhiyuan-server/src/test/java/com/ytell/zhiyuan/model/dto/planning/ConversationContractSerializationTest.java

- [x] 步骤 1：写失败测试，锁定字段

    def test_recommendation_output_requires_backend_refs():
        with pytest.raises(ValidationError):
            TurnOutput.model_validate({
                "responseType": "recommendation",
                "message": "候选已生成",
                "artifactRefs": [],
                "evidenceRefs": [],
            })

    def test_state_patch_rejects_wrong_base_version():
        with pytest.raises(ValidationError):
            StatePatch(baseVersion=41, targetVersion=43, changes=[], invalidations=[])

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_gateway_contracts.py -q

预期：FAIL，协议类型尚不存在。

- [x] 步骤 3：增加准确的 Pydantic 合同

实现 EvidenceRef、ArtifactRef、TurnOutput 和 StatePatch。TurnOutput 的 recommendation、fact 和 review 类型必须包含后端引用；所有模型使用 extra forbid；StatePatch 要求 targetVersion 大于 baseVersion，变化路径只来自协议白名单。

- [x] 步骤 4：实现 Java DTO JSON 对齐

ConversationTurnSnapshotDTO 至少包含 snapshotVersion、sessionId、planningStage、scoreContext、confirmedConstraints、preferences、activeProposal、missingFacts、allowedCapabilities 和 evidence。所有列表初始化为空列表，不能返回 null。Java 序列化字段与 Python camelCase 完全一致。

- [x] 步骤 5：运行 GREEN

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_gateway_contracts.py -q
    cd ../zhiyuan-server
    mvn -q -Dtest=ConversationContractSerializationTest test

预期：Python 和 Java 测试均 PASS。

- [x] 步骤 6：提交

    git add zhiyuan-agent/app/gateway/contracts.py \
      zhiyuan-agent/tests/unit/test_gateway_contracts.py \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationTurnSnapshotDTO.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationStatePatchDTO.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationEvidenceDTO.java \
      zhiyuan-server/src/test/java/com/ytell/zhiyuan/model/dto/planning/ConversationContractSerializationTest.java
    git commit -m "feat: add conversation gateway contracts"

## 4. 任务 3：实现 Codex App Server stdio HarnessClient

**目的：** 验证 Thread/Turn、流式通知、outputSchema、inject items、steer、interrupt 和 resume；不接业务数据库。

**文件：**

- Create: zhiyuan-agent/app/harness/protocol.py
- Create: zhiyuan-agent/app/harness/client.py
- Create: zhiyuan-agent/app/harness/codex.py
- Create: zhiyuan-agent/tests/unit/test_harness_protocol.py
- Create: zhiyuan-agent/tests/unit/test_codex_harness_client.py
- Create: zhiyuan-agent/tests/fixtures/codex/fake_app_server.py
- Create: zhiyuan-agent/tests/integration/test_codex_app_server_poc.py
- Create: zhiyuan-agent/scripts/codex_app_server_poc.py
- Modify: zhiyuan-agent/app/config.py
- Modify: zhiyuan-agent/pyproject.toml

- [x] 步骤 1：写 JSONL client 失败测试

    @pytest.mark.asyncio
    async def test_client_correlates_response_and_notification():
        client = AppServerClient(command=[sys.executable, "tests/fixtures/codex/fake_app_server.py"])
        await client.start()
        await client.initialize(client_name="zhiyuan_gateway", client_version="0.1.0")
        response = await client.request("thread/start", {"model": "test"})
        assert response["thread"]["id"] == "thr_test"
        notification = await client.next_notification()
        assert notification["method"] == "thread/started"
        await client.close()

另加测试：JSON-RPC error、通知先于 response、请求超时、stdout 非 JSON 日志隔离、进程退出时 pending future 失败和并发 request 不串 id。

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_harness_protocol.py tests/unit/test_codex_harness_client.py -q

预期：FAIL，HarnessClient 和 fake server 尚不存在。

- [x] 步骤 3：实现最小 JSONL transport

AppServerClient 使用 asyncio.create_subprocess_exec，stdin 每次写一行 JSON，stdout 逐行读取；请求 id 使用单调递增整数；stderr 只进入 logger；close 先关闭 stdin、等待进程、再取消 reader task。禁止把 stdout 全量读入内存。

Codex 适配固定提供 start、create_thread、resume_thread、inject_items、start_turn、steer_turn、interrupt_turn 和 events。默认命令为 codex app-server --stdio，配置读取 CODEX_APP_SERVER_BIN、CODEX_APP_SERVER_COMMIT 和 CODEX_APP_SERVER_TIMEOUT_SECONDS。

- [x] 步骤 4：实现 fake server 和集成测试

fake server 模拟 initialize、initialized、thread/start、thread/resume、thread/inject_items、turn/start、turn/steer、turn/interrupt、turn/completed、item/agentMessage/delta 和 item/mcpToolCall。测试不得依赖 OpenAI key。

- [x] 步骤 5：运行 GREEN 和真实版本协议检查（fake server 已验证；真实 binary 检查在任务 4 的 Go/No-Go 环节完成）

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_harness_protocol.py tests/unit/test_codex_harness_client.py tests/integration/test_codex_app_server_poc.py -q
    CODEX_APP_SERVER_BIN=../codex/codex-rs/target/debug/codex \
      .venv/bin/python scripts/codex_app_server_poc.py --check-protocol

预期：测试 PASS；真实检查输出 initialize=ok、thread_start=ok、turn_start=ok、output_schema=ok。若 binary 不存在，按 ../codex/AGENTS.md 构建，不能用另一个版本替代。

- [x] 步骤 6：提交

    git add zhiyuan-agent/app/harness zhiyuan-agent/app/config.py \
      zhiyuan-agent/pyproject.toml zhiyuan-agent/tests/unit/test_harness_protocol.py \
      zhiyuan-agent/tests/unit/test_codex_harness_client.py \
      zhiyuan-agent/tests/fixtures/codex/fake_app_server.py \
      zhiyuan-agent/tests/integration/test_codex_app_server_poc.py \
      zhiyuan-agent/scripts/codex_app_server_poc.py
    git commit -m "feat: add codex app server stdio harness"

## 5. 任务 4：实现可信 Thread binding 并完成 Go/No-Go 验证

**目的：** 证明 Domain MCP 普通工具调用不依赖模型自行填写身份字段；绑定失败时整轮拒绝业务工具。

**文件：**

- Create: zhiyuan-server/src/main/resources/db/migration/V13__add_codex_thread_binding.sql
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/CodexThreadBindingEntity.java
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/CodexThreadBindingMapper.java
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CodexThreadBindingReq.java
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CodexThreadBindingRes.java
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/CodexThreadBindingService.java
- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/CodexConversationController.java
- Create: zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/CodexThreadBindingServiceTest.java
- Create: zhiyuan-server/src/test/java/com/ytell/zhiyuan/web/controller/inner/CodexConversationControllerTest.java
- Create: zhiyuan-agent/app/harness/binding.py
- Create: zhiyuan-agent/app/mcp_server/context.py
- Create: zhiyuan-agent/tests/unit/test_thread_binding.py
- Create: zhiyuan-agent/tests/fixtures/mcp/echo_binding_server.py
- Modify: zhiyuan-agent/app/util/internal_client.py

- [x] 步骤 1：写失败测试，覆盖安全拒绝

    def test_binding_ignores_model_supplied_identity():
        binding = ThreadBinding(threadId="thr_test", sessionId="session-1", userId="user-1",
                                allowedCapabilities={"catalog.search_schools"})
        context = binding.resolve_tool_context(
            {"threadId": "thr_test", "sessionId": "session-2", "userId": "user-2"}
        )
        assert context.sessionId == "session-1"
        assert context.userId == "user-1"
        assert context.modelIdentityOverride == "ignored"

    def test_expired_binding_fails_closed():
        binding = make_expired_binding()
        with pytest.raises(BindingError, match="binding_expired"):
            binding.authorize("catalog.search_schools")

Java 测试覆盖租户/会话不匹配、重复 thread 注册、过期 binding、能力不在 allowlist、撤销后查询和同一 thread 绑定另一用户。

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_thread_binding.py -q
    cd ../zhiyuan-server
    mvn -q -Dtest=CodexThreadBindingServiceTest,CodexConversationControllerTest test

预期：两侧因类型、表和服务不存在而失败。

- [x] 步骤 3：增加数据库和 Java binding 服务

迁移表固定包含 id、tenant_id、chat_session_id、user_id、thread_id、handle_hash、allowed_capabilities、expires_at、revoked_at、create_time 和 update_time。thread_id 与 handle_hash 唯一。服务只返回短期 opaque handle 的 hash 结果，不返回数据库内部 user/session 信息给模型。

- [x] 步骤 4：实现 Gateway binding handle

Gateway 使用 secrets.token_urlsafe(32) 生成 handle，只把明文 handle 放进本进程内存和签名 MCP 启动上下文；MCP tool 参数不包含 handle。每个 turn 的 context 由 Gateway 根据 threadId 从 Java 解析，不能由模型覆盖。

- [x] 步骤 5：运行 binding fixture 和真实 MCP metadata 检查

echo_binding_server.py 提供不访问业务数据的 MCP echo 工具。PoC 依次断言 thr-A 映射到 session-A/user-A；模型伪造 session-B 仍解析为 session-A；撤销 binding 返回 capability_denied。

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_thread_binding.py -q
    .venv/bin/python scripts/codex_app_server_poc.py --check-binding \
      --mcp-server tests/fixtures/mcp/echo_binding_server.py
    cd ../zhiyuan-server
    mvn -q -Dtest=CodexThreadBindingServiceTest,CodexConversationControllerTest test

预期输出 binding=trusted、model_identity_override=ignored、revoked=denied。任一项失败，本期为 NO-GO，不接入真实 Domain MCP。

真实 Codex App Server 的额外检查使用 `codex_metadata_server.py`，断言
`mcp_metadata=trusted`、`model_identity_override=ignored`，并验证 `_meta.threadId`
与 `thread/start` 返回的线程一致。该检查使用固定 0.144.1 binary（源码 commit
89650c6），不会调用模型或外部业务数据。

- [x] 步骤 6：提交

    git add zhiyuan-server/src/main/resources/db/migration/V13__add_codex_thread_binding.sql \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/entity/biz/CodexThreadBindingEntity.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/CodexThreadBindingMapper.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CodexThreadBindingReq.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CodexThreadBindingRes.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/CodexThreadBindingService.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/CodexConversationController.java \
      zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/CodexThreadBindingServiceTest.java \
      zhiyuan-server/src/test/java/com/ytell/zhiyuan/web/controller/inner/CodexConversationControllerTest.java \
      zhiyuan-agent/app/harness/binding.py zhiyuan-agent/app/mcp_server/context.py \
      zhiyuan-agent/app/util/internal_client.py \
      zhiyuan-agent/tests/unit/test_thread_binding.py \
      zhiyuan-agent/tests/fixtures/mcp/echo_binding_server.py \
      zhiyuan-agent/scripts/codex_app_server_poc.py
    git commit -m "feat: add trusted codex thread binding"

## 6. 任务 5：实现 Java Turn Snapshot 和状态增量

**目的：** 把现有成绩、画像和 planning workspace state 投影成版本化、按任务使用的事实快照。

**文件：**

- Create: zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotService.java
- Modify: zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/PlanningStateController.java（任务 5 扩展任务 2 已创建的 Snapshot DTO，不重复创建 DTO 文件）
- Create: zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotServiceTest.java
- Modify: zhiyuan-agent/app/util/internal_client.py
- Create: zhiyuan-agent/app/gateway/snapshot.py
- Create: zhiyuan-agent/tests/unit/test_snapshot_projection.py

- [x] 步骤 1：写失败测试，固定快照投影

    def test_candidate_projection_contains_authoritative_score_and_allowed_capabilities():
        snapshot = build_snapshot(fake_backend_workspace())
        assert snapshot.snapshotVersion == 42
        assert snapshot.scoreContext["province"] == "浙江"
        assert snapshot.scoreContext["rank"] == 18420
        assert "admission_read" in snapshot.allowedCapabilities
        assert "plan_apply" not in snapshot.allowedCapabilities
        assert "workingPlanState" not in snapshot.model_dump()

Java 测试覆盖成绩缺失、planning version 为 null、active pending、stale flag、审查摘要、当前 phase、能力集合和用户隔离。

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_snapshot_projection.py -q
    cd ../zhiyuan-server
    mvn -q -Dtest=ConversationSnapshotServiceTest test

- [x] 步骤 3：实现 Snapshot service 和内部端点

在 PlanningStateController 增加 GET /session/turn-snapshot，参数为 tenantId、chatSessionId 和可选 skill。ConversationSnapshotService 复用 getPlanningWorkspaceState(tenantId, chatSessionId) 和现有成绩/画像加载逻辑，按 skill 只输出必要字段。后端计算 allowedCapabilities，不接受请求覆盖。

candidate-recommendation 只能得到权威成绩、硬约束、confirmed 偏好、排除项、phase、version 和候选/审查摘要；不能得到完整 operation log。

- [x] 步骤 4：实现 StatePatch

Gateway 对相邻快照做结构化 diff，字段路径只允许 scoreContext、confirmedConstraints、preferences、planningStage、activeProposal、missingFacts 和 allowedCapabilities。完整候选列表、方案表和原始 Evidence 不进入 Patch。

- [x] 步骤 5：运行 GREEN

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_snapshot_projection.py -q
    cd ../zhiyuan-server
    mvn -q -Dtest=ConversationSnapshotServiceTest,PlanningStateServiceTest test

- [x] 步骤 6：提交

    git add zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotService.java \
      zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/controller/inner/PlanningStateController.java \
      zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotServiceTest.java \
      zhiyuan-agent/app/gateway/snapshot.py zhiyuan-agent/app/util/internal_client.py \
      zhiyuan-agent/tests/unit/test_snapshot_projection.py
    git commit -m "feat: add versioned conversation turn snapshot"

## 7. 任务 6：实现只读 Domain MCP 工具平面

**目的：** 让 Codex 只看到目标导向、结构化、可审计的业务工具；内部调用现有 Java HTTP/规划服务。

**文件：**

- Create: zhiyuan-agent/app/mcp_server/server.py
- Create: zhiyuan-agent/app/mcp_server/context.py
- Create: zhiyuan-agent/app/mcp_server/response.py
- Create: zhiyuan-agent/app/mcp_server/tools_readonly.py
- Create: zhiyuan-agent/tests/unit/test_domain_mcp_tools.py
- Create: zhiyuan-agent/tests/fixtures/mcp/fake_backend.py
- Modify: zhiyuan-agent/pyproject.toml
- Modify: zhiyuan-agent/app/util/internal_client.py

- [x] 步骤 1：写失败测试，固定八个工具和能力拒绝

    async def test_readonly_catalog_tool_returns_standard_envelope():
        result = await call_tool("catalog.search_schools", {"query": "华师大", "province": "上海"},
                                 context=trusted_context("catalog.search_schools"))
        assert result["status"] == "needs_clarification"
        assert result["resolvedEntities"]
        assert result["evidence"]
        assert result["stateVersion"] == 42

    async def test_readonly_context_cannot_call_write_capability():
        result = await call_tool("plan.propose_changes", {"action": "remove"},
                                 context=trusted_context("admission_read"))
        assert result["status"] == "capability_denied"

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_domain_mcp_tools.py -q

- [x] 步骤 3：锁定 MCP SDK 并实现 stdio server

安装并验证与 Codex commit 89650c6 的 initialize、固定 MCP server 配置和 tool result 兼容的 SDK 版本，将实际版本写入 constraints.txt。第一期只注册 entity.resolve、catalog.search_schools、catalog.get_school、catalog.search_majors、catalog.get_major、admission.get_current_plan、admission.get_history 和 admission.check_eligibility。recommendation、plan 和 profile 写工具不注册。

- [x] 步骤 4：实现统一工具信封

    def ok(data, *, state_version, evidence, entities=(), limitations=()):
        return {"status": "ok", "data": data, "resolvedEntities": list(entities),
                "evidence": list(evidence), "limitations": list(limitations),
                "stateVersion": state_version}

    def error(status, message, *, state_version):
        return {"status": status, "data": {"message": message},
                "resolvedEntities": [], "evidence": [], "limitations": [],
                "stateVersion": state_version}

自由文本必须先经过 entity.resolve；admission.get_history 返回可比性、dataVersion、scope、coverage 和 limitations，不把缺失结果返回为零值。

- [x] 步骤 5：运行 fake backend 和调用治理测试

覆盖相同参数去重、失败最多重试一次、调用预算、旧 stateVersion 的 stale_state、Evidence 所属 thread 和跨 thread 结果拒绝。

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_domain_mcp_tools.py -q
    .venv/bin/python -m app.mcp_server.server --self-check

预期：测试 PASS；self-check 输出八个工具名和 write_tools=0。

- [x] 步骤 6：提交

    git add zhiyuan-agent/app/mcp_server zhiyuan-agent/app/util/internal_client.py \
      zhiyuan-agent/pyproject.toml zhiyuan-agent/constraints.txt \
      zhiyuan-agent/tests/unit/test_domain_mcp_tools.py \
      zhiyuan-agent/tests/fixtures/mcp/fake_backend.py
    git commit -m "feat: add readonly zhiyuan domain mcp"

## 8. 任务 7：接入六个 Codex Skills 和常驻规则

**目的：** 把规划师流程从 Python 单体 Prompt 中移到可按需加载的 Skill。

**文件：**

- Create: zhiyuan-agent/skills/codex/profile-discovery/SKILL.md
- Create: zhiyuan-agent/skills/codex/school-major-exploration/SKILL.md
- Create: zhiyuan-agent/skills/codex/admission-fact-analysis/SKILL.md
- Create: zhiyuan-agent/skills/codex/candidate-recommendation/SKILL.md
- Create: zhiyuan-agent/skills/codex/plan-construction/SKILL.md
- Create: zhiyuan-agent/skills/codex/plan-final-review/SKILL.md
- Create: zhiyuan-agent/skills/codex/references/evidence-policy.md
- Create: zhiyuan-agent/skills/codex/references/planner-questioning-guide.md
- Create: zhiyuan-agent/skills/codex/references/recommendation-explanation-guide.md
- Create: zhiyuan-agent/skills/codex/plugin.json
- Create: zhiyuan-agent/tests/unit/test_codex_skill_manifest.py

- [x] 步骤 1：写失败测试

    def test_codex_skill_manifest_is_complete():
        names = load_skill_names("skills/codex")
        assert names == {"profile-discovery", "school-major-exploration",
                         "admission-fact-analysis", "candidate-recommendation",
                         "plan-construction", "plan-final-review"}

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_codex_skill_manifest.py -q

- [x] 步骤 3：编写 Skill 内容

每个 SKILL.md 使用 YAML frontmatter name、description、version，正文固定包含适用条件、不适用条件、前置状态、允许能力、标准步骤、证据要求、单轮调用预算、停止条件、输出结构和降级策略。每轮只选择一个主 Skill。candidate-recommendation 缺少省份、年份、位次/成绩或存在硬约束冲突时必须澄清，不能直接给候选。plan-construction 和 plan-final-review 第一期只读，禁止 Proposal。

常驻规则放在 zhiyuan-agent/skills/codex/base_instructions.md，内容只包括事实优先、不得猜测、实体歧义必须澄清、Evidence 必须引用、写操作需 Proposal 和旧状态不得覆盖新 Snapshot。

- [x] 步骤 4：调用固定 Codex 版本检查 Skill 发现

    cd zhiyuan-agent
    CODEX_APP_SERVER_BIN=../codex/codex-rs/target/debug/codex \
      .venv/bin/python scripts/codex_app_server_poc.py --list-skills skills/codex

预期：六个 Skill enabled，skills/list 返回 description，正文仅在对应 skill item 注入时加载。

- [ ] 步骤 5：提交

    git add zhiyuan-agent/skills/codex zhiyuan-agent/tests/unit/test_codex_skill_manifest.py \
      zhiyuan-agent/scripts/codex_app_server_poc.py
    git commit -m "feat: add codex planner skills"

## 9. 任务 8：实现 Gateway turn 编排、输出校验和事件适配

**目的：** 保留现有 /ws/chat 协议，在 Shadow/readonly 模式完成 Snapshot → Codex Turn → MCP → 结构化输出 → 稳定事件。

**文件：**

- Create: zhiyuan-agent/app/gateway/output_validation.py
- Create: zhiyuan-agent/app/gateway/event_adapter.py
- Create: zhiyuan-agent/app/gateway/service.py
- Create: zhiyuan-agent/tests/unit/test_output_validation.py
- Create: zhiyuan-agent/tests/unit/test_event_adapter.py
- Create: zhiyuan-agent/tests/integration/test_shadow_gateway.py
- Modify: zhiyuan-agent/app/server.py
- Modify: zhiyuan-agent/app/schemas/ws.py
- Modify: zhiyuan-agent/app/config.py

- [x] 步骤 1：写失败测试

    def test_output_validator_rejects_unknown_evidence():
        with pytest.raises(OutputContractError, match="evidence_not_found"):
            validate_turn_output(turn_output=fact_output(evidence_refs=["ev-missing"]),
                                 current_snapshot=snapshot(version=42),
                                 evidence_ledger={"ev-known": authoritative_evidence()},
                                 artifacts={})

    def test_event_adapter_never_exposes_raw_tool_arguments():
        event = adapt_codex_item({"type": "mcpToolCall", "tool": "admission.get_history",
                                  "arguments": {"userId": "secret"}, "status": "completed"})
        assert event["type"] == "planning.status"
        assert "arguments" not in event
        assert "userId" not in json.dumps(event)

- [x] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_output_validation.py tests/unit/test_event_adapter.py -q

- [x] 步骤 3：实现 Gateway turn 流程

GatewayService.handle_turn 固定执行：解析 binding；读取 Snapshot；计算 StatePatch；确保 Thread；启动带 outputSchema 的 turn；转发安全事件；解析 TurnOutput；校验 Evidence、Artifact 和状态版本。任何 stale_state、未知引用或 Schema 解析失败都返回 recoverable.error，不发送未校验结论。

- [x] 步骤 4：保留旧 WebSocket 协议和配置切换

server.py 增加 GATEWAY_MODE=legacy|codex_shadow|codex_readonly。legacy 完全调用当前 ChatService；codex_shadow 旧链路向用户输出、Codex 并行 dry-run；codex_readonly 通过 WSResponse 和稳定事件输出，写操作返回只读限制。保留 reply、card、thinking，新增 assistant.delta、assistant.completed、planning.status、evidence.updated、recommendation.card、recoverable.error。

- [x] 步骤 5：运行 fake server 端到端测试

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_output_validation.py \
      tests/unit/test_event_adapter.py tests/integration/test_shadow_gateway.py -q

断言用户和旧链路消息仍持久化；Shadow 不产生画像/方案写入；相同 turnId 重试只产生一条助手消息。

- [ ] 步骤 6：提交

    git add zhiyuan-agent/app/gateway zhiyuan-agent/app/server.py \
      zhiyuan-agent/app/schemas/ws.py zhiyuan-agent/app/config.py \
      zhiyuan-agent/tests/unit/test_output_validation.py \
      zhiyuan-agent/tests/unit/test_event_adapter.py \
      zhiyuan-agent/tests/integration/test_shadow_gateway.py
    git commit -m "feat: add codex conversation gateway"

## 10. 任务 9：接入前端稳定事件但保持只读

**目的：** 让现有前端消费新事件和 Artifact，不解析模型 Markdown，不改变现有方案写入授权路径。

**文件：**

- Create: zhiyuan-web/src/interface/api/conversation.ts
- Create: zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/ArtifactRenderer.tsx
- Create: zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/EvidenceDrawer.tsx
- Create: zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/PlanningStatus.tsx
- Create: zhiyuan-web/src/utils/conversationEvents.mjs（纯函数事件归一化和后端数值格式化）
- Create: zhiyuan-web/src/utils/conversationEvents.test.mjs（使用 Node 内置 test runner 验证事件归一化和 Artifact 数值格式化）
- Modify: zhiyuan-web/src/interface/api/volunteer.ts
- Modify: zhiyuan-web/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx

- [ ] 步骤 1：写失败事件合同测试

    import assert from "node:assert/strict";
    import test from "node:test";
    import {
      formatAdmissionProbability,
      formatRank,
      normalizeConversationEvent,
    } from "./conversationEvents.mjs";

    test("formats backend artifact values without parsing assistant markdown", () => {
      assert.equal(formatAdmissionProbability(0.68), "68%");
      assert.equal(formatRank(18320), "18320");
      assert.equal(normalizeConversationEvent({ type: "planning.status", payload: {} }).type,
        "planning.status");
    });

另加测试：unknown artifact 返回空值；Evidence payload 显示 dataVersion 和 limitations；planning.status 不暴露工具名和参数；旧 reply/card 仍按原组件渲染。测试使用 Node 内置 runner，不引入当前项目没有的 Jest/Vitest 依赖。

- [ ] 步骤 2：运行 RED

    cd zhiyuan-web
    node --test src/utils/conversationEvents.test.mjs

- [ ] 步骤 3：实现只读 Artifact renderer

conversation.ts 定义 Gateway 事件和 Artifact 类型；conversationEvents.mjs 提供无 UI 依赖的归一化和格式化纯函数；ArtifactRenderer 只接受 Gateway 校验后的 artifact，不接受 assistant 文本作为数字源；EvidenceDrawer 通过 evidenceId 请求后端数据。

- [ ] 步骤 4：接入 WorkspacePanel

增加事件 reducer，只更新对话、Evidence 和只读候选区域；收到 action.proposed 只显示 pending 预览，不调用 apply。第一期 Codex 写动作统一返回 capability_denied。

- [ ] 步骤 5：运行前端和现有回归

    cd zhiyuan-web
    node --test src/utils/conversationEvents.test.mjs
    npm run build:dev

预期：测试和生产构建 PASS。

- [ ] 步骤 6：提交

    git add zhiyuan-web/src/interface/api/conversation.ts \
      zhiyuan-web/src/interface/api/volunteer.ts \
      zhiyuan-web/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx \
      zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents \
      zhiyuan-web/src/utils/conversationEvents.mjs \
      zhiyuan-web/src/utils/conversationEvents.test.mjs
    git commit -m "feat: render codex conversation artifacts"

## 11. 任务 10：Shadow 回放、指标和验收门禁

**目的：** 在用户不可见的情况下比较旧引擎和 Codex Harness 的工具、实体、证据、延迟和只读回答差异。

**文件：**

- Create: zhiyuan-agent/scripts/codex_shadow_replay.py
- Create: zhiyuan-agent/tests/fixtures/shadow/golden_cases.json
- Create: zhiyuan-agent/tests/fixtures/shadow/adversarial_cases.json
- Create: zhiyuan-agent/tests/unit/test_shadow_metrics.py
- Create: zhiyuan-agent/app/observability/conversation_trace.py
- Create: zhiyuan-agent/docs/codex-app-server-poc-report.md
- Modify: zhiyuan-agent/docs/codex-shadow-runbook.md

- [ ] 步骤 1：写失败测试，固定 trace 和硬门槛

    def test_shadow_trace_contains_required_correlation_ids():
        trace = run_shadow_case("readonly-admission-001")
        assert {"conversationId", "turnId", "threadId", "snapshotVersion", "skillName"} <= trace.keys()

    def test_shadow_hard_gates_are_zero():
        report = aggregate_shadow_report(load_fixture_report())
        assert report["unauthorizedWrites"] == 0
        assert report["unknownAdmissionUnits"] == 0
        assert report["factsWithoutEvidence"] == 0
        assert report["crossSessionProposalUse"] == 0

- [ ] 步骤 2：运行 RED

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_shadow_metrics.py -q

- [ ] 步骤 3：实现 trace、回放和报告

每个 turn 输出一行 JSONL，至少包含 conversationId、turnId、threadId、snapshotVersion、skillName、toolCallCount、duplicateToolCallCount、resolvedEntityCount、evidenceRefCount、writeAttempted、latencyMs 和 status。runner 只接受固定 manifest、golden 和 adversarial 文件，不接受任意生产 session id。

- [ ] 步骤 4：执行离线回放

    cd zhiyuan-agent
    .venv/bin/python scripts/codex_shadow_replay.py \
      --manifest tests/fixtures/shadow/baseline_manifest.json \
      --golden tests/fixtures/shadow/golden_cases.json \
      --adversarial tests/fixtures/shadow/adversarial_cases.json \
      --output /tmp/zhiyuan-codex-shadow.jsonl
    .venv/bin/python -m pytest tests/unit/test_shadow_metrics.py -q

预期：硬门槛全部为 0；差异写入报告，不自动判定新引擎优于旧引擎。

- [ ] 步骤 5：生成 PoC 报告

报告必须记录 Codex commit、transport、MCP SDK 版本、binding 结果、Thread/Turn/compaction/interrupt/resume 结果、性能、失败样例和 GO/NO-GO。binding 失败时结论固定为 NO-GO。

- [ ] 步骤 6：提交

    git add zhiyuan-agent/scripts/codex_shadow_replay.py \
      zhiyuan-agent/tests/fixtures/shadow \
      zhiyuan-agent/tests/unit/test_shadow_metrics.py \
      zhiyuan-agent/app/observability/conversation_trace.py \
      zhiyuan-agent/docs/codex-app-server-poc-report.md \
      zhiyuan-agent/docs/codex-shadow-runbook.md
    git commit -m "test: add codex shadow evaluation"

## 12. 任务 11：第一期整体验证和部署检查

**目的：** 验证 Python、Java、Web、Codex 版本和旧链路没有被破坏。

- [ ] 步骤 1：运行 Python 目标测试

    cd zhiyuan-agent
    .venv/bin/python -m pytest tests/unit/test_harness_protocol.py \
      tests/unit/test_codex_harness_client.py tests/unit/test_thread_binding.py \
      tests/unit/test_snapshot_projection.py tests/unit/test_domain_mcp_tools.py \
      tests/unit/test_output_validation.py tests/unit/test_event_adapter.py \
      tests/unit/test_shadow_metrics.py tests/integration/test_codex_app_server_poc.py \
      tests/integration/test_shadow_gateway.py -q

预期：全部 PASS；未执行的真实 LLM e2e 必须在报告注明。

- [ ] 步骤 2：运行 Java 目标测试

    cd ../zhiyuan-server
    mvn -q -Dtest=ConversationContractSerializationTest,ConversationSnapshotServiceTest,\
      CodexThreadBindingServiceTest,CodexConversationControllerTest,PlanningStateServiceTest test

预期：全部 PASS。

- [ ] 步骤 3：运行前端测试和构建

    cd ../zhiyuan-web
    node --test src/utils/conversationEvents.test.mjs
    npm run build:dev

- [ ] 步骤 4：运行协议和安全检查

    cd ../zhiyuan-agent
    CODEX_APP_SERVER_BIN=../codex/codex-rs/target/debug/codex \
      .venv/bin/python scripts/codex_app_server_poc.py --check-protocol --check-binding
    .venv/bin/python -m app.mcp_server.server --self-check

预期：protocol=GO、binding=GO、write_tools=0。

- [ ] 步骤 5：检查旧协议回归

    .venv/bin/python -m pytest tests/unit/test_ws_compat.py \
      tests/unit/test_chat_service_history_persistence.py tests/unit/test_state_sync.py -q

- [ ] 步骤 6：记录发布门禁

未授权写操作、跨会话 binding/Proposal、无 Evidence 的关键事实、虚假招生单元、过期版本写入和冲稳保分类不一致必须全部为 0；Codex commit 固定为 89650c6；MCP 工具为 8 个只读工具、0 个写工具。

- [ ] 步骤 7：提交整体验收记录

    git add docs/superpowers/plans/2026-09-07-codex-app-server-core-conversation-engine.md \
      zhiyuan-agent/docs/codex-app-server-poc-report.md \
      zhiyuan-agent/docs/codex-shadow-runbook.md
    git commit -m "docs: record codex conversation engine pilot verification"

## 13. 第一期开关和回退

生产 Shadow：

    GATEWAY_MODE=codex_shadow
    CODEX_APP_SERVER_BIN=/opt/codex/0.144.1/codex
    CODEX_APP_SERVER_COMMIT=89650c6
    CODEX_APP_SERVER_TRANSPORT=stdio
    MCP_MODE=readonly
    MCP_WRITE_TOOLS_ENABLED=false
    CODEX_ALLOWED_CAPABILITIES=catalog,admission,entity

只读 Canary 只有在 Shadow 报告连续三个固定批次满足硬门槛后启用 GATEWAY_MODE=codex_readonly。

App Server 启动失败、binding 失败、MCP 初始化失败或输出校验失败时，当前 turn 返回可恢复错误并回退 legacy；不自动重试完整 turn。Shadow 失败不影响用户旧链路。写操作第一期统一走旧链路的现有 pending-confirmation 流程。

## 14. 第二期进入条件和拆分计划

第一期完成后不要直接把 recommendation.generate_candidates、plan.generate_draft 或任何 apply 工具加入 Codex。根据 Shadow 报告另建以下计划：

1. 录取率与 Evidence：接入招生单元录取率、算法/数据版本、边界 [0,50) / [50,70) / [70,99] 和数据缺失协议。
2. Plan Review Policy：从 ReviewRuleRegistry、PlanValidationService、RepairCandidateSelector 和旧审查回放统一冲稳保框架、录取率梯度、有效保底和 repair options。
3. Rank/Solver：拆分 Eligibility、Admission Probability、Preference Fit、Data Confidence，复用现有确定性 Solver，禁止重新计算录取率。
4. Proposal/CAS：Codex 只能 preview/create Proposal，用户确认由 Gateway 调既有 CAS，重新读取权威版本并验证 postcondition。
5. 规划工作台：扩展候选、Evidence、Review finding、Plan diff 和最终 Artifact，全部由稳定 Gateway 事件驱动。

第二期每个计划都必须有独立设计审阅、golden/replay/adversarial 数据集、Shadow 结果和回退开关；第一期不提前实现写能力。

## 15. 计划自审

### 15.1 规格覆盖

- App Server 生命周期、流式事件、outputSchema、skills、steer、interrupt、resume：任务 3、7、8。
- 可信 Thread/MCP binding：任务 4，且为整体 Go/No-Go。
- Snapshot、StatePatch、Thread 非权威状态：任务 2、5。
- Domain MCP 读写分离、统一错误和调用预算：任务 6。
- Evidence、Artifact、结构化输出校验：任务 2、8、9。
- 现有招生单元录取率和老审查规则：第一期仅保留权威摘要和只读结果；第二期任务 14 明确拆分，不在第一期重新计算。
- 规划师式 Skills 和主动澄清：任务 7。
- 前端稳定事件和后端 Artifact：任务 9。
- Shadow、评测、可观测性、灰度和回退：任务 1、10、11、13。

### 15.2 占位符检查

本计划不使用 TODO、TBD 或未定义的“稍后补充”步骤。所有第一期任务都给出文件、测试命令、预期结果和提交边界；第二期能力明确列为独立计划入口。

### 15.3 类型和命名一致性

- Python 统一使用 ConversationTurnSnapshot、StatePatch、TurnOutput、EvidenceRef 和 ArtifactRef。
- Java 统一使用 ConversationTurnSnapshotDTO、ConversationStatePatchDTO 和 ConversationEvidenceDTO。
- 状态字段统一为 snapshotVersion/stateVersion。
- 工具统一使用 status/data/resolvedEntities/evidence/limitations/stateVersion。
- Gateway 模式统一为 legacy/codex_shadow/codex_readonly。
- 录取率风险边界统一为 [0,50) 冲、[50,70) 稳、[70,99] 保。

## 16. 执行交接

本计划完成后，执行者必须从任务 1 开始，按任务顺序逐项运行测试和提交。第一期最终交付物是：

- Codex App Server stdio HarnessClient。
- 可信 Thread binding Go/No-Go 报告。
- 版本化 Turn Snapshot 和 StatePatch。
- 八个只读 Domain MCP 工具。
- 六个 Codex Skills。
- Gateway 稳定事件和 Evidence/Artifact 校验。
- 前端只读 Artifact/Evidence 渲染。
- Shadow 回放、硬门禁和回退运行手册。

只有这些交付物全部通过第 12 节验收，才可以创建第二期 Rank/Solver/Proposal/最终方案实施计划。
