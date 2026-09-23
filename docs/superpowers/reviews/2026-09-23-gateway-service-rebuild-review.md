# `app/gateway/service.py` 重建复核

日期：2026-09-23
复核对象：`zhiyuan-agent/app/gateway/service.py`
依据：`2026-09-23-gateway-service-rebuild-review-brief.md`、恢复事故记录、P1b-3/P1c-2/P2d 报告及现有测试。

## 修复后复核结论（2026-09-23 晚）

**无新增阻断项，允许进入提交流程（有条件放行）。**

修复后的新指纹为 `cd873230408d61c0ee7af960fb17c9fe`。三项原阻断/行为缺口均已在代码中修正，并有新增回归测试：nullable `admissionMode` 的 enum 已包含 `None`；重查轮复用了首轮的 `on_notification`/`on_turn_started` 回调；没有 `start_turn_and_collect` 的 harness 会直接返回 `None`，不会把启动确认当成回合结果。修复后定向套件本轮独立跑到 `30 passed`，三个新增用例独立跑到 `3 passed`，schema 直接验证和编译检查也通过。

放行仍带两个证据边界：本轮完整套件的独立重跑复现了既知夹具失败，`--maxfail=1` 得到 `1 failed / 551 passed` 后停止；不带 `--maxfail` 的重跑在约 40% 后长时间无输出并被中断，没有本轮的 `1942 passed / 35 skipped` 自然收尾统计。当前 shell 也无法连接 `18090/18091/18092`，因此事故报告第十节记录的四项真栈结果（包括“重查后成功”）本轮只作为可追溯历史证据，不冒充新执行结果。若提交门槛要求本轮独立全量/真栈证据，应先恢复本地栈并重跑；就代码和回归测试复核本身，不再保留 P1/P2 阻断。

## 初始复核结论（修复前）

**有条件不通过，当前不建议放行。**

重建版与当前报告定义的主要正常路径基本一致，相关定向测试通过；但发现一个会直接拒绝合法模型输出的 JSON Schema 问题：契约允许 `EvidenceRef.admission_mode` 为 `None`，模型可见 schema 却在 `enum` 中遗漏 `null`。另外，`_recheck_turn` 的 `start_turn` 回退分支没有等待终态，重查轮也没有传递实时进度和 native turn 绑定回调。这两项目前不一定命中生产默认 harness，但属于实际行为缺口，应在放行前明确修复或作出有记录的兼容性决策。

本复核没有修改实现代码，也没有清理或回滚工作区。对象指纹核对如下：

```text
$ md5sum zhiyuan-agent/app/gateway/service.py /tmp/gateway-service-recovered.py
a7f406d97a49e9f73c22cbdec30db06c  zhiyuan-agent/app/gateway/service.py
a7f406d97a49e9f73c22cbdec30db06c  /tmp/gateway-service-recovered.py

$ cmp -s zhiyuan-agent/app/gateway/service.py /tmp/gateway-service-recovered.py; echo $?
0
```

## 逐项判定

### 1. `_recheck_turn` 的 `start_turn` 回退分支

**判定：有问题（中风险，兼容/降级路径）。**

位置：`zhiyuan-agent/app/gateway/service.py:1308-1328`。当前代码在没有 `start_turn_and_collect` 时直接调用 `start_turn`，把返回值转换后交给上层；但 `CodexAppServerHarness.start_turn()` 只发出 `turn/start` 请求并返回启动确认，等待终态是 `start_turn_and_collect()` 的职责（见 `app/harness/codex.py:87-121`）。这与 `_recheck_turn` 自身“拿不到结构化输出返回 `None`”的语义不一致：启动确认可能只有 `inProgress`，并不是完成回合。

最小复现（只有 `start_turn` 的替身）：

```text
$ PYTHONPATH=. .venv/bin/python - <<'PY'
import asyncio
from app.gateway.service import GatewayService

class StartOnlyCodex:
    async def start_turn(self, thread_id, input_items, output_schema):
        return {'turn': {'id': 'native-turn-1', 'status': 'inProgress'}}

async def main():
    service = object.__new__(GatewayService)
    service.codex = StartOnlyCodex()
    result = await service._recheck_turn('thread-1', 'retry')
    print(result)
    print('returned_before_terminal_wait=', result['turn']['status'] == 'inProgress')

asyncio.run(main())
PY
{'turn': {'id': 'native-turn-1', 'status': 'inProgress'}}
returned_before_terminal_wait= True
```

因此，替身 harness、旧版 harness 或降级路径可能把尚未完成的重查当作已返回结果；后续虽然可能在结构化输出校验处失败，但不会按函数契约返回 `None`，也没有等待终态。当前生产 harness 具备 `start_turn_and_collect`，所以本项暂未证明会命中默认生产路径；这不消除回退分支本身的问题。

### 2. 重查轮没有传递 `emit`/`on_turn_started`

**判定：有问题（P2，实时交互和回合绑定缺口）。**

初始回合在 `service.py:986-1002` 构造并传递 `on_notification`、`on_turn_started`；重查调用在 `service.py:1092` 和 `1308-1326` 只传 `thread_id`、输入和 schema，没有接收或传递 `emit`，也没有建立重查 native turn 的绑定。`start_turn_and_collect` 的文档明确说明 `on_notification` 是实时进度的注入点（`app/harness/codex.py:107-125`）。

最小复现（采集替身收到的关键字参数）：

```text
$ PYTHONPATH=. .venv/bin/python - <<'PY'
import asyncio
from dataclasses import dataclass
from app.gateway.service import GatewayService

@dataclass
class Result:
    status: str = 'completed'
    output: dict | None = None
    events: list | None = None
    payload: dict | None = None

class Collector:
    def __init__(self):
        self.kwargs = []

    async def start_turn_and_collect(self, thread_id, input_items, schema, **kwargs):
        self.kwargs.append(kwargs)
        return Result(output={}, events=[], payload={})

async def main():
    codex = Collector()
    service = object.__new__(GatewayService)
    service.codex = codex
    await service._recheck_turn('thread-1', 'retry')
    print(codex.kwargs)

asyncio.run(main())
PY
[{}]
```

这意味着 stale/expired 触发重查时，浏览器不会收到重查过程的实时通知；重查事件只能在回合完成后随返回值合并到 `events`。同时，重查轮没有走 `on_turn_started`，`session_runtime` 仍只知道首轮绑定，停止或转述操作存在指向已结束首轮的风险。

原文件已经丢失，无法证明事故前版本是否传了这些回调；但就当前 harness 契约和初始回合的对称行为而言，重查轮缺少实时事件和 native turn 绑定是可观察的行为缺口。该项不一定阻断纯后端调用，但应在放行记录中明确处理。

### 3. 可空 `admissionMode` 的 schema `enum` 不含 `null`

**判定：有问题（P1，阻断合法结构化输出）。**

位置：`zhiyuan-agent/app/gateway/service.py:90-96`。契约 `EvidenceRef.admission_mode` 在 `app/gateway/contracts.py:33` 定义为：

```python
admission_mode: Literal["major", "major_group"] | None = None
```

但模型可见 schema 为：

```python
{"type": ["string", "null"], "enum": ["major", "major_group"]}
```

JSON Schema 的 `type` 和 `enum` 同时生效；`type` 允许 `null` 不代表 `enum` 会自动允许 `null`。实际验证：

```text
$ PYTHONPATH=.venv/lib/python3.10/site-packages:. .venv/bin/python - <<'PY'
from jsonschema import Draft202012Validator
from app.gateway.service import TURN_OUTPUT_SCHEMA

node = TURN_OUTPUT_SCHEMA['properties']['evidenceRefs']['items']['properties']['admissionMode']
print(node)
for value in ('major', 'major_group', None):
    errors = list(Draft202012Validator(node).iter_errors(value))
    print(repr(value), 'accepted' if not errors else f'rejected: {errors[0].message}')
PY
{'type': ['string', 'null'], 'enum': ['major', 'major_group']}
'major' accepted
'major_group' accepted
None rejected: None is not one of ['major', 'major_group']
```

当真实证据没有招生模式时，模型输出合法的 `null` 会被模型侧 schema 拒绝，可能触发修复回合或最终 `output_schema_invalid`。现有 `test_the_model_facing_schema_exposes_every_contract_enum` 只核对 Literal 字面量是否出现在 `enum`，没有覆盖 nullable union 的 `null` 可接受性，因此没有捕获此问题。

### 4. 新增日志文案

**判定：无法判定（低风险、非协议问题）。**

位置：`zhiyuan-agent/app/gateway/service.py:1124-1131`，新增文案为：

```text
evidence settlement failed the turn code=%s detail=%s cited=%s
```

事故取证已确认原始 `service.py` 无可用 golden copy，无法据此证明日志文案与事故前版本相同。日志不是对外契约；本轮也没有发现该文案导致行为失败的证据。因此不能判为通过原版等价性，只能标记为无法判定，风险不构成当前放行阻断项。

### 5. `_extract_output` / `_validate_round` 抽取重构

**判定：通过（以可验证行为为限）。**

位置：`zhiyuan-agent/app/gateway/service.py:1024` 起。重建版将结构化输出抽取/修复和回合校验拆为两个 helper；现有证据覆盖了首轮、重查、unknown、Java 不可达、快照证据来源及契约 enum 等行为。定向验证结果：

```text
$ .venv/bin/python -m pytest \
    tests/unit/test_gateway_evidence_flow.py \
    tests/unit/test_gateway_contracts.py \
    tests/unit/test_evidence_verification.py -q
...........................                                              [100%]
27 passed in 0.25s

$ .venv/bin/python -m pytest \
    tests/integration/test_shadow_gateway.py::test_evidence_follows_the_snapshot_not_the_process_memory -q
.                                                                        [100%]
1 passed in 0.17s

$ .venv/bin/python -m compileall -q app/gateway/service.py app/harness/codex.py app/gateway/contracts.py
compileall=passed
```

这些结果支持“当前覆盖到的行为没有发现由 helper 抽取引入的回归”。但原文件已丢，无法证明 helper 的结构、注释、未覆盖 fallback 分支与原版逐字节或逐结构相同；第 1 项的 fallback 问题也应独立看待，不能归因给抽取本身。

## 测试边界

本轮按 brief 启动过全量命令：

```text
$ CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9 \
    .venv/bin/python -m pytest tests/unit tests/integration -q
```

运行约到 29% 时出现历史上已知的 `test_dialog_quality_gate` 夹具失败，之后长时间无新输出；等待约一分钟后手动 `Ctrl-C` 中断。本轮没有自然结束，因此没有最终统计，不能把全量写成通过，也不能在本轮重新确认 brief 中记录的 `1 failed / 1939 passed / 35 skipped`。

## 未验证/无法验证项

1. 原始网关文件已被覆盖且没有 golden copy，无法做逐字节等价复核；只能依据报告、测试和当前可观察行为判断。
2. 无法证明事故前版本的日志文案，故第 4 项只能“无法判定”。
3. `_recheck_turn` 的 `start_turn` fallback 没有真实生产路径验证；当前生产 harness 走的是 `start_turn_and_collect`。
4. 真栈上“重查后第二次核验返回 `valid` 并继续成功”本轮未复现；历史单测覆盖该组合，不能将其写成此次真栈实测。
5. 本轮全量测试被中断，没有最终统计。
6. brief 中真栈 fact、断依赖、恢复和重查命令本轮没有重新执行；恢复事故记录中的真栈结果属于历史证据，不应冒充本轮复核结果。

## 建议的放行前动作

1. 修正 `evidenceRefs[].admissionMode` schema，使 `null` 同时出现在允许的枚举约束中，并增加针对 nullable enum 的回归测试。
2. 明确 `_recheck_turn` 的兼容语义：回退到只有 `start_turn` 的 harness 时必须等待终态或显式返回失败，不得把启动确认当作结构化回合结果。
3. 为重查轮设计并测试进度事件转发和 native turn 绑定；至少补一条断言，确保重查调用收到与首轮一致的 `on_notification`/`on_turn_started` 能力，或记录明确不支持该能力的产品决策。
4. 修复后重新跑定向测试、带 Redis 的全量测试，并按需重跑真栈断依赖与重查成功路径，再更新放行结论。

## 修复后逐项复核证据

### 指纹与代码修复

```text
$ md5sum zhiyuan-agent/app/gateway/service.py
cd873230408d61c0ee7af960fb17c9fe  zhiyuan-agent/app/gateway/service.py

$ git diff --numstat HEAD -- zhiyuan-agent/app/gateway/service.py
520	129	zhiyuan-agent/app/gateway/service.py
```

修复点与代码位置：

- `service.py:95-98`：`evidenceRefs[].admissionMode` 为 `type: ["string", "null"]`，`enum` 为 `["major", "major_group", None]`。
- `service.py:993-999`、`:1095-1098`、`:1314-1355`：首轮构造的 `collect_kwargs` 原样传给重查轮。
- `service.py:1331-1343`：缺少 `start_turn_and_collect` 时记录 warning 并返回 `None`，不调用只返回启动确认的 `start_turn`。

### 新增回归测试

```text
$ .venv/bin/python -m pytest \
    tests/unit/test_gateway_evidence_flow.py \
    tests/unit/test_gateway_contracts.py \
    tests/unit/test_evidence_verification.py -q
..............................                                           [100%]
30 passed in 0.25s

$ .venv/bin/python -m pytest \
    tests/unit/test_gateway_contracts.py::test_nullable_contract_literals_are_expressible_in_the_model_facing_schema \
    tests/unit/test_gateway_evidence_flow.py::test_recheck_round_gets_the_same_progress_callbacks_as_the_first_round \
    tests/unit/test_gateway_evidence_flow.py::test_recheck_without_a_collect_harness_returns_none_instead_of_the_ack -q
...                                                                      [100%]
3 passed in 0.18s

$ .venv/bin/python -m pytest tests/integration/test_shadow_gateway.py -q
..............                                                           [100%]
14 passed in 0.19s
```

schema 直接验证：

```text
$ PYTHONPATH=.venv/lib/python3.10/site-packages:. .venv/bin/python - <<'PY'
from jsonschema import Draft202012Validator
from app.gateway.service import TURN_OUTPUT_SCHEMA
from app.gateway.contracts import EvidenceRef

node = TURN_OUTPUT_SCHEMA['properties']['evidenceRefs']['items']['properties']['admissionMode']
print(node)
for value in ('major', 'major_group', None):
    errors = list(Draft202012Validator(node).iter_errors(value))
    print(repr(value), 'accepted' if not errors else f'rejected: {errors[0].message}')
print('contract_default=', EvidenceRef(evidenceId='e', sourceLevel='authoritative', dataVersion='v').admission_mode)
PY
{'type': ['string', 'null'], 'enum': ['major', 'major_group', None]}
'major' accepted
'major_group' accepted
None accepted
contract_default= None
```

编译检查：

```text
$ .venv/bin/python -m compileall -q app/gateway/service.py app/gateway/contracts.py app/harness/codex.py
compileall=passed
```

### 本轮完整套件边界

带 Redis 的完整套件 `CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9` 本轮两种方式均未得到自然完成的完整统计。加 `--maxfail=1` 的证据为：

```text
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
1 failed, 551 passed, 7 warnings in 22.68s
```

失败内容是缺失 `zhiyuan-server/data/tmp/session_volunteer_*.json` 的既知夹具问题。去掉 `--maxfail=1` 后测试在约 40% 处长时间无输出，手动中断，未得到最终计数。事故报告第十节记录的两次自然完成结果 `1 failed / 1942 passed / 35 skipped` 未在本轮独立重现。

额外组合运行 `tests/integration/test_shadow_gateway.py tests/integration/test_gateway_live_events.py` 在前 21 个用例后长时间等待并被中断；单独运行 `test_shadow_gateway.py` 已自然完成并为 `14 passed`。这次长等待与本次三项修复无直接失败断言，但说明 live-events 集成验证仍依赖可用的本地运行环境。

### 真栈边界

本轮对 `18090`、`18091`、`18092` 的连接检查均失败：

```text
port=18090 curl: (7) couldn't connect to host at 127.0.0.1:18090
port=18091 curl: (7) couldn't connect to host at 127.0.0.1:18091
port=18092 curl: (7) couldn't connect to host at 127.0.0.1:18092
```

因此本轮没有再次执行 fact、断依赖和重查成功脚本。事故报告第十节中的真栈证据仍可追溯到会话 `900338`：首次 stale、第二次核验后成功、verify 两次、`type=text`，并记录了靶子行恢复和 `FLIP-` 残留为 0；该部分应标记为历史执行证据。

### 修复后最终逐项结论

| 复核项 | 修复后判定 | 证据 |
|---|---|---|
| 可空 `admissionMode` enum | **通过** | nullable 回归测试、`None accepted` 直接验证 |
| 重查轮进度/native turn 回调 | **通过** | 两轮 kwargs 相同、两次 `bind_codex_turn` 的新增测试 |
| `start_turn` 回退终态语义 | **通过** | 无 collect harness 返回 `None` 的新增测试 |
| 新增日志文案 | **无法判定** | 原版丢失，日志非对外契约，保留 |
| `_extract_output` / `_validate_round` 抽取 | **通过** | 原有定向测试和新增回归测试通过 |
