# Codex 原生交互与前端纵向切片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 让现有页面完成“真实工具进度 → 必要选项提问 → 回传答案 → 校验后的最终结果”，并可停止和恢复。

**Architecture:** Gateway 适配 App Server 双向协议；保留现有 compat 路由及 sessionDetailV2。单一 stdio reader、独立 WS 接收器、后台 Turn worker、唯一 WS writer；业务状态由 Java 提供。

**Tech Stack:** Python ≥3.10 / asyncio / Pydantic / FastAPI、Codex App Server、Redis、Next.js 13 / React 18 / TypeScript 4.9、node:test。

**Spec:** [核心设计](../../release-4.0.0-codex-native-zhiyuan-integration-and-frontend-validation-plan.md)，重点 §4–§6、§8。

## Global Constraints

- 路径相对 `/root/dev/zhiyuan`；`A/` 以下指 `zhiyuan-agent/`，`W/` 指 `zhiyuan-web/`，`J/` 指 `zhiyuan-server/src/main/java/com/ytell/zhiyuan/`。这些是本文路径缩写，执行时展开。
- 原生选项回答必须回原 request id；输出 JSON 未验证前不进 UI；现有事件名 `conversationAction.result` 不改名。
- 身份用 tenant+session；同一会话至多一个活动 Turn；首期 Gateway 一个 worker。
- 不覆盖未提交代码；先查 `docs/superpowers/tasks/LEDGER.md`，同一文件任务串行。下列步骤是实施时待执行，本轮文档不代表测试已运行。
- 代码块给出合同、关键算法与最小回归用例；按清单接入现有调用点，并保留现有测试，不通过孤立 helper 测试代替服务入口验证。

## 文件职责与依赖

| 文件 | 职责 | 任务 |
|---|---|---|
| `A/scripts/probe_codex_capabilities.py`（新增） | 无凭证输出的协议探针 | A1 |
| `A/app/gateway/ui_events.py`（新增） | 统一 envelope、事件类型/大小校验 | A2 |
| `A/app/gateway/session_runtime.py`（新增） | turn worker、会话锁、发送队列 | A3 |
| `A/app/gateway/user_input.py`（新增） | 原生待答 request 与业务澄清 | A4 |
| `A/app/gateway/event_store.py`（新增） | Redis cursor、事件、请求去重 | A5 |
| `W/src/utils/conversationSession.mjs`（新增） | 纯 reducer，供 node:test 与 React 共用 | A6 |
| `A/app/gateway/thread_recovery.py`（新增） | 业务绑定恢复与 Thread 重建 | A7 |

执行顺序 A1→A2→A5→A3→A4→A6→A7（保留编号方便审查引用）；A6 的 fixture 可在 A2 定稿后开发，但实际接线验收依赖 A4/A5。

## Task A1：固定运行时与原生能力兼容矩阵

**Files:** Modify `A/app/config.py`、`A/app/gateway/composition.py`、`A/app/harness/client.py`；Create `A/scripts/probe_codex_capabilities.py`、`A/tests/integration/test_codex_interaction_capabilities.py`；Extend `A/tests/fixtures/codex/fake_app_server.py`。

**Interfaces:** 消费 `CodexAppServerConfig`、`build_codex_command`、`AppServerClient.initialize`；产出 `initialize(..., capabilities: dict | None = None)` 和 JSON 报告 `{binaryPath,binaryVersion,sourceCommit,initialize,threadStart,resume,requestUserInput,elicitation,trustedMcpMetadata,toolAllowlist}`。每项状态 `passed|failed|not_run`，不使用默认 true。

- [ ] 在 fake app-server 增加带 id 的 requestUserInput、nested MCP item、进程退出用例；用现有 fixture 启动方式写测试：当前 initialize 不发送 capability，测试须失败。
- [ ] 运行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_codex_interaction_capabilities.py -q`，保存预期失败，随后扩展 initialize 原有参数，不重写 client。
- [ ] 探针先做无模型的 initialize/thread/start/resume，再按 `--real-model` 显式测试提问；退出码 0 仅表示所选 gates 全过。固定二进制绝对路径与版本；不要从 Git HEAD 推断 PATH 二进制版本。

```python
# initialize 的新增能力部分；结果继续走现有 request/notify。
params = {"clientInfo": {"name": client_name, "version": client_version}}
if capabilities is not None:
    params["capabilities"] = capabilities
result = await self.request("initialize", params)
await self.notify("initialized", {})
```

- [ ] 对原生提问能力使用以下配置进行单独验证；未通过时在配置中记录 `user_input_mode=structured_final`，A4 自动采用终态澄清路径。不要静默切 Plan，也不要用异步提问协议冒充同步 request。

```toml
[features]
default_mode_request_user_input = true
[tools.experimental_request_user_input]
enabled = true
```

```json
{"clientInfo":{"name":"zhiyuan-gateway","version":"1"},"capabilities":{"experimentalApi":true,"extensions":{"openai/standard-form-input":{}}}}
```

`thread/start` 明确 `threadSource:"user"`；experimental 字段以运行二进制 schema 为准。Form elicitation 的能力先用受控测试 MCP 发出，不依赖模型恰好选择它。

- [ ] 核对 effective tool list：只允许 Domain MCP 与已批准的用户提问工具。显式关闭 shell/exec/web 任意访问/文件修改；Skills 只读资源仅限定部署技能目录。现有 sandbox/approval 设置不能替代工具级验证。探针验证 MCP `_meta` 的 thread 身份实际存在；不能拿模型传入 ID 顶替。
- [ ] 执行 `codex app-server generate-json-schema --help` 后按其实际选项导出 schema 至 `.runtime`；将上述请求 fixtures 与生成 schema 校验。真实探针一次独占调用，报告路径 `.runtime/codex-capabilities.json`；不存 token、提示词全文。
- [ ] 复跑能力测试与 `tests/integration/test_gateway_composition.py`；任务报告包含源码版本、二进制版本、支持/降级矩阵、未执行项。审查后只提交本任务文件；共享工作树未获独占时只交 diff，不执行 git add/commit。

## Task A2：冻结事件与状态，不把工具成功当诉求完成

**Files:** Create `A/app/gateway/ui_events.py`、`A/tests/unit/test_ui_events.py`、`A/tests/fixtures/conversation_v1.jsonl`；Modify `A/app/schemas/ws.py`、`A/app/gateway/event_adapter.py`、`A/app/engine/result_synthesis.py`、`A/tests/unit/test_result_synthesis.py`；Extend `A/tests/unit/test_ws_compat.py`。

**Interfaces:** `SessionKey(tenant_id:str,session_id:str)`；`UiEvent` 字段见下；`adapt_notification(notification:dict, ui_turn_id:str)->list[dict]` 产生尚未编号的 `{type,payload}`；最终事件由 A5 `append` 编号。UiEvent.type 在实现中约束为主设计白名单，不能让下游任意字符串绕过。session.resync 为独立控制快照，允许 sequence=0，不经过普通 UiEvent 追加。`executionStatus` 表示用户诉求，`toolStatus` 表示调用结果，两者分别保存。

```python
from dataclasses import dataclass
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

@dataclass(frozen=True)
class SessionKey:
    tenant_id: str
    session_id: str

class UiEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    protocol_version: Literal[1] = Field(default=1, alias="protocolVersion")
    type: str
    session_id: str = Field(alias="sessionId")
    turn_id: str = Field(alias="turnId")
    stream_epoch: str = Field(alias="streamEpoch", min_length=1)
    sequence: int = Field(ge=1)
    payload: dict[str, Any]
```

- [ ] 从 A1 录到的原生形状建 fixture；至少包含 nested item 开始/结束、工具失败、agent JSON delta、reasoning、终态。未知 type 不展示，参数/result 原文不外发。
- [ ] 先添加此回归并运行，当前 adapter 对 nested 形状将失败：

```python
def test_nested_mcp_start_is_progress_without_arguments():
    from app.gateway.event_adapter import adapt_notification
    raw = {"method": "item/started", "params": {
        "threadId": "t", "turnId": "c", "item": {
            "id": "i", "type": "mcpToolCall", "server": "zhiyuan_domain",
            "tool": "admission.get_history", "status": "inProgress",
            "arguments": {"private": "do-not-display"}}}}
    assert adapt_notification(raw, "u") == [{"type": "tool.progress", "payload": {
        "itemId": "i", "tool": "admission.get_history", "status": "started",
        "label": "正在查询历年录取"}}]
```

- [ ] 实现 adapter 只抽取白名单字段，工具名称只接受本次能力表的映射；未知工具显示统一标签，不展示其名字或参数。

```python
def adapt_notification(notification: dict, ui_turn_id: str) -> list[dict]:
    method = notification.get("method")
    params = notification.get("params") or {}
    item = params.get("item") or {}
    if method not in {"item/started", "item/completed"}:
        return []
    if item.get("type") != "mcpToolCall":
        return []
    labels = {"admission.get_history": "正在查询历年录取"}
    tool = item.get("tool", "")
    status = "started" if method == "item/started" else (
        "failed" if item.get("status") == "failed" else "completed")
    return [{"type": "tool.progress", "payload": {
        "itemId": item["id"], "tool": tool if tool in labels else "domain",
        "status": status, "label": labels.get(tool, "正在处理查询")}}]
```

实现时 labels 扩为已冻结工具清单，单元测试仍用上面的具体工具。`ui_turn_id` 由调用方 envelope 使用，不从原生 turnId覆盖。

- [ ] 修 P2 状态覆盖：保持模型/业务校验所得 `executionStatus`；只允许工具失败让 completed 降到 partial/blocked，不允许反向升级。用现有 `test_result_synthesis.py` 的模型构造器增加 partial+all-tools-ok 场景；再经 `GatewayService.handle_turn` 验相同输出，避免只测覆盖前的数据。
- [ ] WSMessage 接受 v1 的 protocolVersion/clientRequestId/turnId 和控制消息。控制消息保留 `content:""`；`conversationAction` 继续作为 chat 字段。新增 `WSResponse` 或 v1 专用响应模型，别把新事件发进不接受它的旧 Literal。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_ui_events.py tests/unit/test_result_synthesis.py tests/unit/test_ws_compat.py -q`。预期全部通过；fixture 禁止原始 reasoning/claimToken/完整工具结果。代码审查后交付本任务 diff 与协议 fixture。

## Task A3：实际流式事件与可响应的 WebSocket

**Files:** Modify `A/app/harness/client.py`、`A/app/harness/codex.py`、`A/app/gateway/service.py`、`A/app/server.py`；Create `A/app/gateway/session_runtime.py`、`A/tests/integration/test_gateway_live_events.py`；Extend `A/tests/unit/test_codex_harness_client.py`。

**Interfaces:** 依赖 A5 完成 append/admit。给 `start_turn_and_collect(..., on_notification:Callable[[dict],Awaitable[None]]|None=None)` 和 `GatewayService.handle_turn(..., emit:Callable[[dict],Awaitable[None]]|None=None)` 增加可选回调，旧调用不变；`SessionRuntime.submit(key, client_request_id, ui_turn_id, work)` 返回 accepted/busy/duplicate，`interrupt(key,ui_turn_id)` 与 `steer(key,ui_turn_id,text)` 只命中本会话活动 Turn。新增入站 turnSteer，把可信映射的 codexTurnId 传给 expectedTurnId；active/mismatch/completed 三种情况分别测试，拒绝跨回合更正。

- [ ] fake app-server 用 asyncio Event 闸门卡住终态，在先收到 MCP start 后保持 Turn 活动。集成测试必须在释放终态前看到进度，向同一 WS 发 interrupt 后收到停止确认。native/compat 两个路由参数化覆盖。
- [ ] 运行新测试确认当前行为无法在终态前得到事件；随后只在现有 collect 循环中添加回调，不增第二个通知消费者。

```python
# start_turn_and_collect：匹配 thread/turn 后、提取最终输出前。
if on_notification is not None:
    await on_notification(notification)
event = _notification_to_event(notification)
```

- [ ] 回调执行快速规范化并追加有界事件存储，不等待慢浏览器。WS writer 订阅已编号事件；每连接队列最多 256 项，慢消费者达到上限关闭该连接并让其 resume，不能拖垮模型 reader。关键终态先存后发。
- [ ] 新 SessionRuntime 管理后台工作而非在 `receive_json` 循环里 await 完整 `handle_turn`；两个 WS 路由共用它。基础结构如下，实际鉴权 key 从 C1 注入：

```python
# SessionRuntime 内部使用 asyncio.Task；接收器只分发，不等待 work 完成。
import asyncio
from app.gateway.ui_events import SessionKey

active: dict[SessionKey, asyncio.Task] = {}

def launch(key: SessionKey, work):
    current = active.get(key)
    if current is not None and not current.done():
        return "busy"
    task = asyncio.create_task(work())
    active[key] = task
    def release(done):
        if active.get(key) is done:
            active.pop(key, None)
        if not done.cancelled():
            done.exception()  # 错误事件由 work 的统一 finally/error 分支写入。
    task.add_done_callback(release)
    return "accepted"
```

- [ ] `work` 在开始发 turn.started、终态发一次 turn.completed；超时是 timed_out，中断是 interrupted。Codex 原生终态为 `turn/completed` 中 `turn.status`，没有 `turn/interrupted` 通知。所有异常路径也解除活动锁。
- [ ] client 进程退出时同时唤醒 `_pending`、`_notification_waiters`，回收所有 server-request task。backlog 最大 1,024 条、TTL 60 秒，溢出对受影响运行报告 protocol_overflow，不能无声丢终态。等待回答单独暂停推理 deadline，超时策略见 A4。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_gateway_live_events.py tests/unit/test_codex_harness_client.py tests/integration/test_gateway_composition.py -q`；证明“终态闸门没开，前端已收到进度”，而不是只比最终 events 数量。交付 diff/测试日志。

## Task A4：原生问答桥与统一澄清卡合同

**Files:** Create `A/app/gateway/user_input.py`、`A/tests/integration/test_gateway_user_input.py`；Modify `A/app/gateway/composition.py`、`A/app/gateway/service.py`、`A/app/server.py`、`A/app/schemas/ws.py`；Extend fake app-server。

**Interfaces:** `UserInputBroker.handle_server_request(raw)->dict` 挂到现有 `set_server_request_handler`；`answer(key, ui_request_id, response)->dict`；`snapshot(key)->list[dict]` 输出仍可答卡片与有效期；`resolve_native(runtime_generation,rpc_id,reason)->None`；`expire_runtime(runtime_generation)->None`。broker 记录未来结果，只由 client `_handle_server_request` 回原 rpc id 一次。

真实协议 fixture：

```json
{"id":41,"method":"item/tool/requestUserInput","params":{"threadId":"thr_1","turnId":"turn_1","itemId":"call_1","questions":[{"id":"major","header":"专业范围","question":"你指哪一种？","isOther":true,"isSecret":false,"options":[{"label":"计算机类","description":"包含多个专业"},{"label":"计算机科学与技术","description":"具体本科专业"}]}],"isBlocking":false,"autoResolutionMs":null}}
```

```json
{"id":41,"result":{"answers":{"major":{"answers":["计算机类"]}}}}
```

- [ ] 写测试：发原生 request 后看到 clarification.requested，原 Turn 未结束；回答后 fake server 收到原 id=41 result；不能收到第二次 turn/start。断言跨 session 回答、重复不同答案、过期请求均不完成 Future。
- [ ] 对 `UserInputBroker` 保存如下数据结构并校验答案。isSecret=true 不支持存储或展示，返回受控错误；choice 类型题目 ≤3、单题自由文本 ≤2,000 字、每答数组长度≤1；工具明确要求多选时才扩展新协议版本。

```python
from dataclasses import dataclass
import asyncio
from app.gateway.ui_events import SessionKey

@dataclass
class PendingInput:
    key: SessionKey
    runtime_generation: str
    rpc_id: int | str
    ui_turn_id: str
    question_ids: frozenset[str]
    future: asyncio.Future

def deliver(record: PendingInput, key: SessionKey, answers: dict) -> bool:
    if record.key != key:
        raise PermissionError("clarification_scope_mismatch")
    if set(answers) != record.question_ids:
        raise ValueError("clarification_answer_shape")
    if record.future.done():
        return False
    record.future.set_result({"answers": answers})
    return True
```

- [ ] 每个问题选项由服务器保存，不能信任浏览器提交 label/id 之外任意结构；自由文本只作为用户输入传模型，不解析成后台命令。重复同请求同答案返回已接收，不同答案返回 conflict。
- [ ] 接 `serverRequest/resolved`（只有 threadId/requestId，没有 reason）清理卡；原因由本地 timeout/interrupt 状态确定，否则标 resolved。必要问题过期必须先调用 turn/interrupt、等待终态，再清理 handler；不要只 raise 后让 client 回 RPC error，Runtime 可能将其视为 answers:{} 继续。client 跟踪 server-request task：已 resolved 则取消任务并禁止迟到 result/error。原生 pending 最长10分钟，waiting_user 不消耗模型执行预算；Gateway退出作废，重启重问。
- [ ] 澄清消息增加 `inputKind:"choice"|"form"` 判别。choice 响应 `{inputKind:"choice",answers:{questionId:{answers:[text]}}}`；form 卡携带仅通过白名单验证的 requestedSchema，响应 `{inputKind:"form",action:"accept"|"decline"|"cancel",content:object|null}`。服务端保存 schema，accept 校验 bool/enum/string 与 required，decline/cancel 要 content=null；不从字符串猜布尔。上述 deliver 只用于 choice，form 分支直接完成 `{action,content,_meta:null}`。
- [ ] MCP form 单独适配：params 的 mode/requestedSchema 在顶层，响应 `{action:"accept",content:{...},_meta:null}`；decline/cancel 不等于 Proposal 取消。白名单字段仅短字符串/布尔/枚举，拒绝 URL/secret/未知复杂 schema；turnId=null 且无法唯一定位活动业务回合时拒绝，不绑定到随便一个会话。
- [ ] 能力降级时校验最终 TurnOutput.clarification，发 origin=gateway 卡并结束本轮；回答作为显式用户输入开启新 turnId，与原卡 requestId 关联。为该路径写独立测试：恰好多一次 turn/start。不依赖关键词路由。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_gateway_user_input.py tests/integration/test_gateway_live_events.py -q`。原生 choice、form 布尔/枚举/decline/cancel、降级路径、跨会话/重复/过期、进程退出都需通过；过期后断言模型未继续发后续工具调用。审查后交付。

## Task A5：事件重放、请求幂等与断线恢复

**Files:** Create `A/app/gateway/event_store.py`、`A/tests/integration/test_conversation_replay.py`；Modify `A/app/config.py`、`A/pyproject.toml`（若尚无异步 Redis 依赖才添加）；Modify `docker-compose.codex-local.yml`（仅隔离测试 Redis 开启 AOF）。

**Interfaces:** 本任务先于 A3 执行；只建立可独立测试的 store，WS 接线由 A3/A6/A7 完成。`RedisEventStore.append(key,event:dict)->UiEvent`；`replay(key,epoch:str,after:int)->list[UiEvent]|None`（None 表示需 resync）；`admit(key,request_id,request_digest)->accepted|duplicate|conflict`；`finish_request(key,request_id,result_ref)`。命名空间使用 hash-tag session key，使 Lua 的键同槽。

- [ ] 集成测试使用隔离 Redis：200 个并发 append、两个 tenant 同 sessionId、重复请求不同 payload、trim 后重连、进程重启重放。不要用内存 mock 证明原子性。
- [ ] 原子追加采用一段 Lua，计数器与事件写入不可拆成两个 Python await。stream ID 用 Redis 自动 ID，sequence 独立；replay 遍历最多 2,000 条按 sequence 过滤，窗口外返回 None。

```lua
-- KEYS: counter, stream, epoch；ARGV: event JSON（无 sequence）, ttl, random epoch
local epoch = redis.call('GET', KEYS[3])
if not epoch or redis.call('EXISTS', KEYS[1]) == 0 or redis.call('EXISTS', KEYS[2]) == 0 then
    redis.call('DEL', KEYS[1], KEYS[2])
    epoch = ARGV[3]
    redis.call('SET', KEYS[3], epoch)
end
local seq = redis.call('INCR', KEYS[1])
local ev = cjson.decode(ARGV[1])
ev.sequence = seq
ev.streamEpoch = epoch
redis.call('XADD', KEYS[2], 'MAXLEN', '=', 2000, '*', 'event', cjson.encode(ev))
redis.call('EXPIRE', KEYS[1], ARGV[2])
redis.call('EXPIRE', KEYS[2], ARGV[2])
redis.call('EXPIRE', KEYS[3], ARGV[2])
return cjson.encode(ev)
```

- [ ] append 前验证 UiEvent 类型和 UTF-8 JSON ≤16KiB；只存脱敏事件。超限改为 Artifact 引用；不能截断 JSON。stream/counter/epoch 过期、部分丢失、epoch不同、cursor>current 都要求 resync，不能让老 cursor 无穷等待。
- [ ] 请求占位 `SET requestKey digest NX EX 86400`，现存值相同返回 duplicate，不同返回 conflict；结果以 session+requestId 持久关联。worker 起不来时明确 terminal failure；重启遗留 running 进入 recovery，不未经判断重新发模型或写操作。
- [ ] 固定 A3/A7 的恢复合同并用 store 测试 high-water 快照；WS 接线时 resume 要求 C1 重新鉴权；先重放，再原子转入实时订阅：以同一会话锁截取 high-water mark，缓存其后的新事件，发送 replay 后刷缓存。A7 集成测试在订阅切换期间插入终态，断言不丢且只展示一次；resync 同锁采样 activeTurn、UserInputBroker.snapshot、Java业务版本和日志 high-water。Java数据不同事务更新时记录各自版本，以后端结果为准。
- [ ] 单 worker 锁不跨进程；启动明确校验 workers=1。未来多实例需要租约/fencing，未实现前不把 Redis event store 描述成集群调度器。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_conversation_replay.py -q`；需要 `CODEX_TEST_REDIS_URL` 指向隔离库，缺配置显式 skip 并阻止公网 gate，不记为通过。交付原始计数结果与恢复边界。

## Task A6：复用前端组件，接通页面级状态

**Files:** Modify `W/src/pageComponents/sessionDetailV2/MessageList/index.tsx`、`W/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx`、`W/src/pages/sessionDetailV2/index.tsx`、`W/src/utils/conversationEvents.mjs`、`W/src/utils/conversationEvents.test.mjs`、`W/src/hooks/useWebSocket.tsx`；Create `W/src/utils/conversationSession.mjs`、`.test.mjs`、`W/src/interface/conversationProtocol.ts`、`W/src/pageComponents/sessionDetailV2/ConversationEvents/ClarificationCard.tsx`、`UnderstandingCard.tsx`；Extend 现有 `PlanningStatus.tsx`。

**Interfaces:** `reduceConversation(state,event)->state`；state `{sessionId,streamEpoch,lastSequence,turns,needsResync}`；页面持有 conversationEvents/conversationArtifacts 并同时传 MessageList 与 WorkspacePanel。现有 `normalizeConversationEvent` 先拆 v1 envelope，再兼容旧 text 内 JSON。

- [ ] 先写实际事件 reducer 测试：重复 seq 不重复终态；旧会话事件不污染当前页；乱序/gap 标 resync；applying 不刷成 applied。示例：

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { reduceConversation } from './conversationSession.mjs';
test('重复事件不产生第二次完成', () => {
  const initial = { sessionId: '42', streamEpoch: 'e1', lastSequence: 0, turns: {}, needsResync: false };
  const event = { sessionId: '42', streamEpoch: 'e1', turnId: 't', sequence: 1,
    type: 'turn.completed', payload: { executionStatus: 'partial' } };
  const once = reduceConversation(initial, event);
  assert.deepEqual(reduceConversation(once, event), once);
  assert.equal(once.turns.t.executionStatus, 'partial');
});
```

- [ ] reducer 的顺序校验使用同一合同；非 v1 事件先走兼容转换，不把缺 sequence 的历史消息直接送入本函数。

```javascript
export function reduceConversation(state, event) {
  if (event.sessionId !== state.sessionId) return state;
  if (event.type === 'session.resync') return { ...event.payload.baseline, needsResync: false };
  if (event.streamEpoch !== state.streamEpoch) return { ...state, needsResync: true };
  if (event.sequence <= state.lastSequence) return state;
  if (event.sequence !== state.lastSequence + 1) return { ...state, needsResync: true };
  const prior = state.turns[event.turnId] || {};
  const next = event.type === 'turn.completed'
    ? { ...prior, ...event.payload, terminal: true }
    : { ...prior, lastEvent: event };
  return { ...state, lastSequence: event.sequence,
    turns: { ...state.turns, [event.turnId]: next } };
}
```

在该骨架的 type 分支补 steps/by-item、clarification、proposal；最终答案、Artifact 继续使用现有渲染器。历史加载使用 session.resync 的完整基线重置 reducer，不能假装第一帧 sequence 必须是 1。

- [ ] MessageList 对进度只更新 reducer，不 `fetchLatestMessageList()`、不结束 loading；assistant.completed 合并同 turn 消息，turn.completed 停止本轮 loading。新消息列表拉取仅初载、resync、最终持久化对齐；保证不会出现两份答案。
- [ ] ClarificationCard 按 inputKind 分支：choice 每题 radio + 自由输入；form 对 boolean 渲染布尔选择、enum 渲染单选、string 渲染输入，保存类型化 content；支持 decline/cancel，不发 choice.answers。可编辑尚未提交答案、等待/已答/过期可区分。button 的 disabled 为提交中或过期，提交发送 A4 的 payload；按 Enter 与 Tab 可用，错误后允许重试同 clientRequestId。
- [ ] 页面把新事件与产物传入已有 WorkspacePanel props；理解摘要修改在 active 时发送 turnSteer，完成后作为新 chat；steer失败显示回合已结束，用户可另发新消息，不自动重复。候选/排序沿用 targetView=candidate|ordered；新增 comparison/review 的明确视图值、标签与移动端切换后才声称支持四视图。
- [ ] 应用结果只在 `actionResult.actionStatus=applied` 后调用现有 workspace API；与 newStateVersion 比对：响应落后重读，等于展示，更新版本更大则展示最新并标已更新，不能因并发新版本永远等待相等。applying 显示结果确认中。
- [ ] useWebSocket 清空跨 URL/session 队列；队列上限 20、只留当前会话稳定 ID 消息；连接后先 ticket/协商/resume，再根据服务器去重状态重发。确认动作不盲目重发，先查 Pending/operation；切换 session 移除旧 listeners。
- [ ] 运行 `cd zhiyuan-web && node --test src/utils/conversationEvents.test.mjs src/utils/conversationSession.test.mjs`；再 `npx --no-install tsc --noEmit --incremental false`。若项目已有类型错误保存基线并要求无新增错误；Next build 忽略类型/ESLint 错误，不能据其成功声称类型通过。浏览器行为交 C4，交付 reducer 测试与页面截图证据。

## Task A7：Thread 恢复与跨回合上下文

**Files:** Create `A/app/gateway/thread_recovery.py`、`A/tests/integration/test_gateway_thread_recovery.py`；Modify `A/app/gateway/service.py`、`A/app/harness/binding.py`、`A/app/util/internal_client.py`、`J/service/biz/CodexThreadBindingService.java`、`J/web/controller/inner/CodexConversationController.java`、`J/mapper/CodexThreadBindingMapper.java`；Extend `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/CodexThreadBindingServiceTest.java`。

**Interfaces:** 新增 `GET /inner/codex/{tenantId}/thread-binding/current?chatSessionId=...`（完整前缀 `/gaotu-assistant-bot`）；只供认证内部客户端，查询 tenant+session 最新有效绑定。Python `load_or_resume(key,snapshot)->str` 返回 threadId；已有 resolve-by-thread API 保留。

- [ ] 将 Gateway `_threads`、snapshot cache、working set、turn cache、locks 的 key 全改 SessionKey；缓存以版本淘汰，不能把两个 tenant 的 sessionId 相同当成同一用户。
- [ ] 测试两租户同 sessionId、Gateway 重启、rollout 丢失、resume 报不兼容。断言成功恢复沿用 thread，失败重建但业务 Pending/evidence 不消失；旧原生问答卡 expired。
- [ ] load_or_resume 的算法固定：查当前绑定→核 ownership/状态→resume；仅在 missing/not-resumable 时新建，鉴权失败不可自动绕过新建。新建注册成功后更新缓存；注册失败不暴露无绑定 thread 给 MCP。

```text
current binding exists AND resume succeeds → cache(threadId)
no binding OR known resume-not-found → create → register → load Snapshot → cache
permission/config/transport failure → recoverable.error, no alternate identity
```

- [ ] Snapshot 注入做硬 token/分页上限，历史 Evidence 通过 B1 verify；压缩前后的已确认偏好、锁定项、活动 Proposal 都来自 Java，不能从模型历史反向写入权威状态。
- [ ] 执行 `cd zhiyuan-agent && .venv/bin/python -m pytest tests/integration/test_gateway_thread_recovery.py tests/unit/test_codex_binding_client.py -q`；Java 执行 `mvn -Dtest=CodexThreadBindingServiceTest,CodexConversationControllerTest test`（cwd zhiyuan-server）。补重放窗口失效但原生卡仍活动、epoch重置、恢复订阅期间终态三个服务入口测试。再做一次真实 runtime 重启验证，记录 threadId 变化与业务版本，不记录用户原始画像。
- [ ] 交付 A1–A7 证据索引；A 能力完成的门槛是同一实际前端、真实 Codex、受控 MCP 走通问答和恢复，不仅是 Python helper 全绿。
