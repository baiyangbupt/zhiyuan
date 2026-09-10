# T003：使 `TURN_OUTPUT_SCHEMA` 通过 DeepSeek 校验并跑通复杂回合

> 指派：DeepSeek 实现会话
> 来源：T001 的采集结论（`../T001-sse-capture/REVIEW.md`）
> 类型：代码改动 + 真实端点验证
> 协议：`docs/superpowers/tasks/README.md`

---

## 一、目标

`zhiyuan-agent/app/gateway/service.py` 的 `TURN_OUTPUT_SCHEMA` 被 DeepSeek `/responses` 拒绝，导致所有复杂回合在请求发出后 60–400ms 内以 HTTP 400 失败，从未进入流式阶段。本任务把这个 schema 改成上游接受的形式，**且不改变它对模型输出的约束语义**。

一句话验收：用真实的 `TURN_OUTPUT_SCHEMA`，`scripts/codex_semantic_smoke.py` 的两个复杂场景各连续 3 次 `status=completed`。

---

## 二、背景（你的会话没有这些上下文）

`/root/dev/zhiyuan` 是一个高考志愿咨询对话系统。`zhiyuan-agent` 用 OpenAI 开源的 codex 作为对话引擎宿主，通过 `codex app-server --stdio` 通信，模型接 DeepSeek。

`turn/start` 支持一个协议原生字段 `output_schema`，用于约束模型本回合的最终输出。`TURN_OUTPUT_SCHEMA` 就是传给它的值。codex 会把它包装成：

```json
{"text": {"format": {"type": "json_schema", "name": "codex_output_schema", "schema": <我们的 schema>}}}
```

这个 schema 是本系统「模型必须结构化输出、事实必须绑定 Evidence」的载体，**不能为了通过上游校验而削弱它**。

### 上一个任务已经查清的事（直接用）

T001 搭了透传代理抓到了完整现场，结论：

- 上游拒绝的原文：``{"error":{"message":"Invalid json schema: field `anyOf`: field `anyOf`: missing field `type`", ...}}``
- 10 次协议运行 + 1 次不经代理的直连对照，逐字相同的 400。
- **DeepSeek 没有流式断开问题。** 同一复杂场景、同一上下文与 MCP 工具，只把 schema 换成一个手工简化版（无 `anyOf`），3/3 完成，7 条流最长 9.736s / 691 chunk，全部正常收尾。所以流式链路是好的，唯一的阻塞就是这个 schema。

---

## 三、已核实的环境事实（不要重新调查，直接用）

| 事实 | 值 |
|---|---|
| Python 环境 | `/root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python`（3.10.14） |
| 系统 python3 | 3.6.8，**不要用** |
| Rust 工具链 | cargo 1.72.1，codex-rs 要求 1.95.0 + edition 2024，**不要尝试编译 codex** |
| codex 二进制 | `/root/.nvm/versions/node/v20.20.2/bin/codex`，`codex-cli 0.154.0` |
| 抓包用 codex home | `/root/dev/zhiyuan/.codex-capture-home`（T001 建好，`base_url = http://127.0.0.1:18999/`，可直接复用） |
| 生产 codex home | `/root/dev/zhiyuan/.codex-semantic-home`，**不要动** |
| 透传代理 | `zhiyuan-agent/scripts/sse_capture_proxy.py`（T001 建好，监听 18999，逐块透传、`Authorization` 打码） |
| 鉴权 | 在 `$CODEX_HOME/auth.json`。probe 脚本可从该文件读取，**不要打印、不要写进任何脚本或报告** |
| 复现脚本 | `zhiyuan-agent/scripts/codex_semantic_smoke.py` |
| schema 定义 | `app/gateway/service.py:25` 起的字面量 dict，`:206` `_strict_model_schema()`，`:218-222` 拼装 `$defs` 和 `proposalRequest` |

### 上游已知的两条 schema 约束

1. `anyOf` 节点必须带 `type`。
2. `required` 必须覆盖对象的全部 `properties`（S3 探测报错原文：`Required properties must match all properties in the object`）。

**第 2 条当前已满足**（`required` 未覆盖全部 properties 的对象数 = 0，由 `_strict_model_schema()` 强制）。**改动不得让它退化。**

### 当前不合规的节点

24 个。用这段代码复现清单（也是后面写回归测试的基础）：

```python
import json
from app.gateway.service import TURN_OUTPUT_SCHEMA

def scan(node, path="$", bad_any=None, bad_req=None):
    bad_any = [] if bad_any is None else bad_any
    bad_req = [] if bad_req is None else bad_req
    if isinstance(node, dict):
        if "anyOf" in node and "type" not in node:
            bad_any.append(path)
        if node.get("type") == "object" and "properties" in node:
            if set(node["properties"]) != set(node.get("required", [])):
                bad_req.append(path)
        for k, v in node.items():
            scan(v, f"{path}.{k}", bad_any, bad_req)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            scan(v, f"{path}[{i}]", bad_any, bad_req)
    return bad_any, bad_req
```

24 处分三类：

| 类别 | 例子 | 数量 |
|---|---|---|
| A. 内联对象 or null | `$.properties.proposalRequest` → `anyOf:[<内联 proposal 对象>, {"type":"null"}]` | 1 |
| B. 标量 or null | `$defs.ProposalScope.properties.rawText` → `anyOf:[{"type":"string"},{"type":"null"}]`；带约束的如 `{"minimum":0,"type":"integer"}` | 19 |
| C. `$ref` or null | `$defs.ProposalTierQuota.properties.sprint` → `anyOf:[{"$ref":"#/$defs/ProposalTierRange"},{"type":"null"}]` | 4 |

C 类涉及的两个 `$def` 已核实**只在可空位置被引用**：`ProposalTierQuota` 用 1 次（`tierQuotaGoal`），`ProposalTierRange` 用 3 次（`sprint`/`stable`/`protect`）。

---

## 四、步骤

### 步骤 1：先探清上游到底接受什么（不要跳过）

上游的确切规则没有文档，**不要靠猜**。写一个一次性 probe 脚本，直接向 `https://api.deepseek.com/responses` 发最小请求（一个只有一个可空字段的 schema，`max_output_tokens` 取小值省额度），逐个验证下列写法，记录每种的 HTTP 状态与错误原文：

| 编号 | 写法 | 说明 |
|---|---|---|
| E1 | `{"type": ["string", "null"]}` | 类型数组，JSON Schema 标准写法，OpenAI strict 模式用的就是这种 |
| E2 | `{"anyOf": [{"type":"string"}, {"type":"null"}], "type": "string"}` | 保留 anyOf，补一个 `type` |
| E3 | `{"type": "string", "nullable": true}` | OpenAPI 风格 |
| E4 | 带约束的类型数组：`{"type": ["integer","null"], "minimum": 0}` | 验证约束关键字能否与类型数组共存 |
| E5 | `$defs` + `$ref` 是否被支持（用一个非空的 `$ref` 字段即可） | **这条决定 C 类怎么修**，必须单独验 |
| E6 | 若 E5 通过：`$def` 自身写 `"type": ["object","null"]`，引用处用裸 `{"$ref": ...}` | C 类的首选修法 |

把六条的结果做成表放进报告。**这张表是本任务最有价值的产出**，后续换模型时不用重新探。

### 步骤 2：按探测结果实现归一化

在 `app/gateway/service.py` 中，对拼装完成的 `TURN_OUTPUT_SCHEMA` 施加一个归一化函数（建议名 `_normalize_nullable_for_upstream`，紧跟在第 218-222 行的拼装之后调用），把 24 处改成步骤 1 中被接受的写法。

**必须满足：**

1. **语义不变。** 归一化前后，模型被允许输出的 JSON 集合必须一致。可空仍然可空，非空仍然非空，`enum`、`minimum`、`exclusiveMinimum` 等约束一个都不能丢。
2. **不削弱契约。** 不允许通过下列手段绕过问题：删字段、把对象降级成 `{"type":"object"}` 不带 properties、去掉 `additionalProperties: false`、把字段从 `required` 里拿掉、把 `proposalRequest` 整块删掉。
3. **`required` 覆盖率不退化。** 改完 `bad_req` 必须仍然是 0。
4. **不改 Pydantic 模型。** `ProposalRequest` 及其子模型不动，归一化只作用于生成出来的 schema 字典。
5. **不改 `validate_turn_output` 的校验逻辑**，也不改模型输出的解析路径。这次只动 schema 的表达形式。

若 E5 探测显示上游不支持 `$ref`/`$defs`，则 C 类改为**完整内联**（`ProposalTierRange` 内联 3 次是可接受的，schema 总量当前 10803 字节，内联后仍在合理范围）。这种情况下在报告里写明。

### 步骤 3：加回归测试

在 `tests/unit/test_turn_output_schema.py` 里新增一个用例，用步骤 1 的 `scan()` 断言两条不变量：

```python
bad_any, bad_req = scan(TURN_OUTPUT_SCHEMA)
assert bad_any == []
assert bad_req == []
```

同时**更新**该文件第 30 行附近的既有断言——它现在写的是
`TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]["anyOf"][0]`，
改完形状会变。**改成匹配新形状，不要删掉这条断言**，它在保护 proposal 子 schema 的结构。

### 步骤 4：真实端点验证

启动 T001 的透传代理，用 `.codex-capture-home` 跑 `scripts/codex_semantic_smoke.py`，两个复杂场景（`reference-complete-history`、`mixed-read-write`）**各连续 3 次**。

要求每次都 `status=completed`。若仍有 400，**贴出上游错误原文和当次的 schema 片段**，不要反复试探性改动。

---

## 五、陷阱

1. **`$.properties.proposalRequest` 是内联对象不是 `$ref`**（第 220-222 行由 `_strict_model_schema()` 返回后直接内联），它和 C 类的修法不同，别套用。
2. **`_strict_model_schema()` 会强制 `required = list(properties)`**，归一化函数如果重建了对象节点，必须保留这个性质。
3. **不要动 `.codex-semantic-home/`**，那是生产语义烟测在用的目录。用 `.codex-capture-home`。
4. **不要为了让请求通过而给 codex 加重试或降级逻辑。** 400 是确定性的，重试没有意义。
5. `TURN_OUTPUT_SCHEMA` 是模块级可变字典，被 `service.py` 三处（`:670`、`:691`、`:832`）和 `scripts/codex_semantic_smoke.py:191` 共享引用。归一化必须在模块导入期一次性完成，不要在每次调用时改它。
6. **鉴权信息不要出现在报告、脚本、dump 里。**

---

## 六、验收

```bash
cd /root/dev/zhiyuan/zhiyuan-agent

# 1. 两条不变量归零
.venv/bin/python -c "
from app.gateway.service import TURN_OUTPUT_SCHEMA
<粘贴步骤 1 的 scan 函数>
print(scan(TURN_OUTPUT_SCHEMA))
"

# 2. schema 专项测试
.venv/bin/python -m pytest tests/unit/test_turn_output_schema.py -q

# 3. 全量单测
bash scripts/run_unit_tests.sh

# 4. 真实端点：两个复杂场景各连续 3 次
#    命令按 codex_semantic_smoke.py 的 argparse 自行确定，写进报告
```

### 已知失败基线（不是你造成的，不要去修）

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
2 failed, 1698 passed, 34 skipped
```

第一条因 `zhiyuan-server/data/tmp/session_volunteer_*.json` 本地夹具缺失（94 条），第二条与 web base path 有关。出现基线以外的失败时逐条列出用例名和报错原文。

---

## 七、边界：不要做这些

- 不要动 `app/service.py`（8882 行）、`app/zhiyuan_agent/tools.py`（11402 行）。
- 不要动 `app/engine/`、`app/harness/`、`app/mcp_server/`。
- `app/gateway/service.py` 只改 schema 的构造与归一化，**不改回合流程、不改 `validate_turn_output`、不改 `_repair_turn_output`**。
- 不要改 `.codex-semantic-home/`，不要改 `models.json` 里的模型参数，不要换模型。
- 不要"顺手"重构、格式化、改 import 顺序。
- 不要 commit。改完等 review。

---

## 八、报告

把报告写到：

```
/root/dev/zhiyuan/docs/superpowers/tasks/T003-schema-compat/REPORT.md
```

格式见 `docs/superpowers/tasks/_templates/REPORT.md`，逐节填写，不要增删小节。

额外要求：**步骤 1 的六条探测结果表必须完整收录**，包括被拒绝的那些和它们的错误原文——失败的探测和成功的一样有价值。

状态词只用 `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`。验收命令贴**原始输出**。**不写修复建议、不写下一步、不写根因推测。**
