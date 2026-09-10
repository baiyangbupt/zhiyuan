---
task: T003
status: DONE
executor: deepseek
finished_at: 2026-09-10 19:42 +0800
---

# T003 报告

## 一、结论

`TURN_OUTPUT_SCHEMA` 已按上游实测接受的写法归一化（24 处 `anyOf` 节点全部改写），`scan()` 两条不变量归零，`scripts/codex_semantic_smoke.py` 的 `reference-complete-history` 与 `mixed-read-write` 各连续 3 次 `status=completed`（6/6），全量单测仅剩任务书列出的 2 项基线失败。

## 二、交付物

| 路径 | 字节数 | 说明 |
|---|---|---|
| `/root/dev/zhiyuan/zhiyuan-agent/app/gateway/service.py` | 37372 | 新增 `_normalize_nullable_for_upstream()`（+52 行）并在导入期调用 |
| `/root/dev/zhiyuan/zhiyuan-agent/tests/unit/test_turn_output_schema.py` | 3832 | 新增 `scan()` 与 `test_turn_output_schema_is_accepted_by_deepseek_responses`，扩展 proposalRequest 断言 |
| `/root/dev/zhiyuan/docs/superpowers/tasks/T003-schema-compat/REPORT.md` | 本文件 | 报告 |
| `/root/dev/zhiyuan/.runtime/sse-capture/probe_schema_forms.py` | 4363 | 步骤 1 第一轮探测脚本（P0、E1–E7） |
| `/root/dev/zhiyuan/.runtime/sse-capture/probe-schema-forms.txt` | 5128 | 第一轮探测原始输出 |
| `/root/dev/zhiyuan/.runtime/sse-capture/probe_micro_forms.py` | 5004 | 步骤 1 第三轮探测脚本（微用例 A0–A3、C0–C5、B1–B2、X1） |
| `/root/dev/zhiyuan/.runtime/sse-capture/probe-micro-forms.txt` | 3452 | 第三轮探测原始输出 |
| `/root/dev/zhiyuan/.runtime/sse-capture/probe_real_schema.py` | 6301 | 步骤 1 第二轮探测脚本（真实 schema 的 V0–V5 变体） |
| `/root/dev/zhiyuan/.runtime/sse-capture/probe-real-schema.txt` | 1495 | V0–V3 原始输出 |
| `/root/dev/zhiyuan/.runtime/sse-capture/probe-real-schema-v45.txt` | 976 | V4–V5 原始输出 |
| `/root/dev/zhiyuan/.runtime/sse-capture/t003_summarize.py` | 2562 | 代理 dump 汇总脚本（供复核） |
| `/root/dev/zhiyuan/.runtime/sse-capture/t003-unit-tests.log` | 211182 | 全量单测原始日志 |
| `/root/dev/zhiyuan/.runtime/sse-capture/req-0022..0036-*.log` | 8082865（15 份） | 步骤 4 的代理抓包 dump |
| `/root/dev/zhiyuan/.runtime/sse-capture/t003-run-ch-1..3.json` | 193189 / 177119 / 380181 | 场景 1 三次运行 stdout |
| `/root/dev/zhiyuan/.runtime/sse-capture/t003-run-mrw-1..3.json` | 886554 / 554863 / 420744 | 场景 2 三次运行 stdout |

## 三、实际改动的文件

`git status --short` 原始输出（仓库根 `/root/dev/zhiyuan`）：

```
 M zhiyuan-agent/CLAUDE.md
 M zhiyuan-agent/app/gateway/service.py
 M zhiyuan-agent/app/models/__init__.py
 D zhiyuan-agent/app/models/intent_frame.py
 D zhiyuan-agent/app/models/typed_actions.py
 D zhiyuan-agent/app/resolver/__init__.py
 D zhiyuan-agent/app/resolver/action_resolver.py
 M zhiyuan-agent/examples/dialog_quality_gate.py
 D zhiyuan-agent/tests/integration/test_resolver_vs_legacy.py
 M zhiyuan-agent/tests/regression/test_keyword_matchers.py
 D zhiyuan-agent/tests/unit/models/test_intent_frame.py
 D zhiyuan-agent/tests/unit/models/test_typed_actions.py
 D zhiyuan-agent/tests/unit/test_action_resolver.py
 M zhiyuan-agent/tests/unit/test_turn_output_schema.py
 D zhiyuan-web/tsconfig.tsbuildinfo
?? .codex-capture-home/
?? "docs/superpowers/plans/2026-09-10-\345\257\271\350\257\235\346\211\247\350\241\214\345\274\225\346\223\216\346\216\250\350\277\233\350\256\241\345\210\222\344\277\256\350\256\242.md"
?? docs/superpowers/tasks/
?? zhiyuan-agent/scripts/sse_capture_proxy.py
```

本任务只改了其中两行对应文件：

- `M zhiyuan-agent/app/gateway/service.py`（本任务，+52 行）
- `M zhiyuan-agent/tests/unit/test_turn_output_schema.py`（本任务，+46 -1 行）

其余条目在本任务开始前即已存在，属另一会话的改动：`zhiyuan-agent/CLAUDE.md`、`app/models/__init__.py`、`app/models/intent_frame.py`、`app/models/typed_actions.py`、`app/resolver/*`、`examples/dialog_quality_gate.py`、`tests/integration/test_resolver_vs_legacy.py`、`tests/regression/test_keyword_matchers.py`、`tests/unit/models/*`、`tests/unit/test_action_resolver.py`、`zhiyuan-web/tsconfig.tsbuildinfo`；未跟踪的 `.codex-capture-home/`、`zhiyuan-agent/scripts/sse_capture_proxy.py` 来自 T001，`docs/superpowers/*` 为任务书/台账。

本任务改动的 diff：

```diff
diff --git a/zhiyuan-agent/app/gateway/service.py b/zhiyuan-agent/app/gateway/service.py
index 4a1bc9d..24f3a45 100644
--- a/zhiyuan-agent/app/gateway/service.py
+++ b/zhiyuan-agent/app/gateway/service.py
@@ -222,6 +222,58 @@ TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"] = {
 }
 
 
+def _normalize_nullable_for_upstream(schema: dict[str, Any]) -> dict[str, Any]:
+    """把 ``anyOf: [X, {"type": "null"}]`` 改写成 DeepSeek ``/responses`` 接受的等价写法。
+
+    上游实测约束（T003 步骤 1 探测表）：
+    1. ``anyOf`` 分支里出现 ``$ref`` 时该节点必须带 ``type``，而带 ``type: "object"`` 的节点必须有
+       非空 ``properties``；
+    2. ``type`` 数组只接受 ``string`` / ``number`` / ``integer`` / ``boolean`` / ``null``，不接受
+       ``object`` / ``array``。
+
+    于是三类可空节点分别改写为：标量 → 类型数组；``$ref`` → ``$def`` 自身声明
+    ``["object", "null"]`` 后用裸 ``$ref``；内联对象 → 把对象自身的键提升到同层，``anyOf`` 原样保留。
+
+    只改表达形式：可空性、``enum`` / ``minimum`` / ``exclusiveMinimum`` 等约束一律保留；
+    ``required`` 覆盖全部 ``properties`` 的性质由 ``_strict_model_schema()`` 保证，此处不触碰。
+    """
+    definitions = schema.get("$defs", {})
+
+    def rewrite(node: Any) -> Any:
+        if isinstance(node, dict):
+            for key, value in list(node.items()):
+                node[key] = rewrite(value)
+            any_of = node.get("anyOf")
+            if not isinstance(any_of, list) or len(any_of) != 2:
+                return node
+            branches = [item for item in any_of if item != {"type": "null"}]
+            if len(branches) != 1 or not isinstance(branches[0], dict):
+                return node
+            branch = branches[0]
+            if "$ref" in branch:
+                definition = definitions.get(str(branch["$ref"]).rsplit("/", 1)[-1])
+                if definition is not None:
+                    definition["type"] = ["object", "null"]
+                node.pop("anyOf")
+                node.update(branch)
+            elif branch.get("type") == "object":
+                node.update({**branch, "anyOf": any_of})
+            elif isinstance(branch.get("type"), str):
+                node.pop("anyOf")
+                node.update({**branch, "type": [branch["type"], "null"]})
+            return node
+        if isinstance(node, list):
+            for index, value in enumerate(node):
+                node[index] = rewrite(value)
+        return node
+
+    rewrite(schema)
+    return schema
+
+
+_normalize_nullable_for_upstream(TURN_OUTPUT_SCHEMA)
+
+
 def _maybe_await(value: Any) -> Any:
     return value if inspect.isawaitable(value) else _Immediate(value)
 
diff --git a/zhiyuan-agent/tests/unit/test_turn_output_schema.py b/zhiyuan-agent/tests/unit/test_turn_output_schema.py
index 2d89e7d..bffeb4d 100644
--- a/zhiyuan-agent/tests/unit/test_turn_output_schema.py
+++ b/zhiyuan-agent/tests/unit/test_turn_output_schema.py
@@ -1,6 +1,23 @@
 from app.gateway.service import TURN_OUTPUT_SCHEMA
 
 
+def scan(node, path="$", bad_any=None, bad_req=None):
+    bad_any = [] if bad_any is None else bad_any
+    bad_req = [] if bad_req is None else bad_req
+    if isinstance(node, dict):
+        if "anyOf" in node and "type" not in node:
+            bad_any.append(path)
+        if node.get("type") == "object" and "properties" in node:
+            if set(node["properties"]) != set(node.get("required", [])):
+                bad_req.append(path)
+        for key, value in node.items():
+            scan(value, f"{path}.{key}", bad_any, bad_req)
+    elif isinstance(node, list):
+        for index, value in enumerate(node):
+            scan(value, f"{path}[{index}]", bad_any, bad_req)
+    return bad_any, bad_req
+
+
 def test_turn_output_schema_keeps_admission_facts_and_confirmation_fields() -> None:
     properties = TURN_OUTPUT_SCHEMA["properties"]
 
@@ -27,8 +44,36 @@ def test_turn_output_schema_keeps_admission_facts_and_confirmation_fields() -> N
     assert major_items["items"]["additionalProperties"] is False
     assert "clarification" in properties
     assert "proposalRef" in properties
-    proposal_schema = TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]["anyOf"][0]
+    proposal_node = TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]
+    proposal_schema = proposal_node["anyOf"][0]
     assert proposal_schema["additionalProperties"] is False
     assert proposal_schema["required"] == list(proposal_schema["properties"])
+    # 归一化后：可空对象节点自己带 type + properties，null 分支仍留在 anyOf 里
+    assert proposal_node["type"] == "object"
+    assert proposal_node["additionalProperties"] is False
+    assert set(proposal_node["properties"]) == set(proposal_schema["properties"])
+    assert proposal_node["required"] == list(proposal_node["properties"])
+    assert {"type": "null"} in proposal_node["anyOf"]
     assert TURN_OUTPUT_SCHEMA["$defs"]["ProposalScope"]["additionalProperties"] is False
     assert TURN_OUTPUT_SCHEMA["additionalProperties"] is False
+
+
+def test_turn_output_schema_is_accepted_by_deepseek_responses() -> None:
+    bad_any, bad_req = scan(TURN_OUTPUT_SCHEMA)
+    assert bad_any == []
+    assert bad_req == []
+
+    # 可空标量必须是类型数组，且不丢约束
+    min_count = TURN_OUTPUT_SCHEMA["$defs"]["ProposalTierRange"]["properties"]["minCount"]
+    assert min_count["type"] == ["integer", "null"]
+    assert min_count["minimum"] == 0
+    raw_text = TURN_OUTPUT_SCHEMA["$defs"]["ProposalScope"]["properties"]["rawText"]
+    assert raw_text["type"] == ["string", "null"]
+
+    # 只在可空位置被引用的 $def 自己声明可空，引用处是裸 $ref
+    for name in ("ProposalTierQuota", "ProposalTierRange"):
+        assert TURN_OUTPUT_SCHEMA["$defs"][name]["type"] == ["object", "null"]
+    assert TURN_OUTPUT_SCHEMA["$defs"]["ProposalTierQuota"]["properties"]["sprint"] == {
+        "default": None,
+        "$ref": "#/$defs/ProposalTierRange",
+    }
```

归一化前后三类节点的形状对照（用 `_strict_model_schema(ProposalRequest)` 复刻归一化前的拼装后打印；为可读性，A 类的 `description` 与 `properties` 内容以 `...` 节选，其余键值逐字保留）：

```
## A 类 proposalRequest 节点
  before: {"anyOf": [{"additionalProperties": false, "description": "...", "properties": {...}, ...}, {"type": "null"}]}
  after : 顶层键 ['additionalProperties', 'anyOf', 'description', 'properties', 'required', 'title', 'type']，anyOf 原样保留（含 {"type": "null"} 分支）
## B 类 $defs.ProposalScope.properties.rawText
  before: {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Rawtext"}
  after : {"default": null, "title": "Rawtext", "type": ["string", "null"]}
## B 类 $defs.ProposalTierRange.properties.minCount
  before: {"anyOf": [{"minimum": 0, "type": "integer"}, {"type": "null"}], "default": null, "title": "Mincount"}
  after : {"default": null, "title": "Mincount", "minimum": 0, "type": ["integer", "null"]}
## C 类 $defs.ProposalTierQuota.properties.sprint
  before: {"anyOf": [{"$ref": "#/$defs/ProposalTierRange"}, {"type": "null"}], "default": null}
  after : {"default": null, "$ref": "#/$defs/ProposalTierRange"}
```

## 四、验收命令与原始输出

### 命令 0（步骤 1 探测，六条必录 + 追加用例）

探测请求体的外层是 codex 的真实包装 `{"text": {"format": {"type": "json_schema", "name": "codex_output_schema", "strict": true, "schema": <被探 schema>}}}`，模型 `deepseek-v4-flash`，`max_output_tokens` 16–64，鉴权从 `$CODEX_HOME/auth.json` 读取且未落盘。第一轮（`probe_schema_forms.py`）用 `stream: false`，第二、三轮（`probe_real_schema.py`、`probe_micro_forms.py`）用 `stream: true`。

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python /root/dev/zhiyuan/.runtime/sse-capture/probe_schema_forms.py
```

第一轮：六条必录 + 现状对照 P0 + object 类型数组对照 E7（原始输出在 `probe-schema-forms.txt`）：

| 编号 | 写法 | HTTP | 上游原文（错误即全量） |
|---|---|---|---|
| P0 | `{"anyOf": [{"type":"string"}, {"type":"null"}]}`（现状标量写法，对照） | 200 | 无错误，`"status": "completed"` |
| E1 | `{"type": ["string", "null"]}` | 200 | 无错误，`"status": "completed"` |
| E2 | `{"anyOf": [{"type":"string"}, {"type":"null"}], "type": "string"}` | 200 | 无错误，`"status": "completed"` |
| E3 | `{"type": "string", "nullable": true}` | 200 | 无错误，`"status":"incomplete"`，`"incomplete_details":{"reason":"max_output_tokens"}`（该次 `max_output_tokens` 取 64） |
| E4 | `{"type": ["integer","null"], "minimum": 0}` 与 `{"type": ["integer","null"], "exclusiveMinimum": 0}` | 200 | 无错误，`"status":"incomplete"`，`"incomplete_details":{"reason":"max_output_tokens"}` |
| E5 | 根级 `$defs` + `{"$ref": "#/$defs/Inner"}`（非可空字段） | 200 | 无错误，`"status": "completed"` |
| E6 | `$def.Inner.type = ["object","null"]` + 引用处裸 `{"$ref": ...}` | 200 | 无错误，`"status": "completed"` |
| E7 | 内联对象写 `{"type": ["object","null"], "properties": {...}}` | 400 | `{"error":{"message":"Invalid json schema: field `type`: unknown variant `object`, expected one of `string`, `number`, `integer`, `boolean`, `null`","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}` |

```bash
.venv/bin/python /root/dev/zhiyuan/.runtime/sse-capture/probe_micro_forms.py
```

第三轮微用例（原始输出在 `probe-micro-forms.txt`；A=内联对象分支，C=`$ref` 分支，B=标量，X=类型数组探边界）：

| 编号 | 写法 | HTTP | 上游原文 |
|---|---|---|---|
| A0 | `anyOf[对象, null]`，节点无 `type` | 200 | 无错误 |
| A1 | `anyOf[对象, null]` + `type:"object"`（无 `properties`） | 400 | `An object with no properties is not allowed.` |
| A2 | `anyOf[对象, null]` + `type:"object"` + 把对象自身键提升到同层 | 200 | 无错误 |
| A3 | 仅对象（无 anyOf、无 null 分支） | 200 | 无错误 |
| C0 | `anyOf[$ref, null]`，节点无 `type`（现状 C 类） | 400 | `Invalid json schema: field `anyOf`: missing field `type`` |
| C1 | `anyOf[$ref, null]` + `type:"object"`（无 `properties`） | 400 | `An object with no properties is not allowed.` |
| C2 | `$def` 自身 `type:["object","null"]` + 裸 `$ref`（E6 形态） | 200 | 无错误 |
| C3 | `$def` 自身 `type:["object","null"]` + `anyOf[$ref, null]` | 400 | `Invalid json schema: field `anyOf`: missing field `type`` |
| C4 | `anyOf[$ref, null]` + `type:"object"` + 把 `$def` 键内联提升到同层 | 200 | 无错误 |
| C5 | `anyOf[$ref, null]` + `type:"object"` + `properties: {}` | 400 | `An object with no properties is not allowed.` |
| B1 | `{"type": ["string", "null"]}` | 200 | 无错误 |
| B2 | `{"type": ["integer", "null"], "minimum": 0, "default": null}` | 200 | 无错误 |
| X1 | `{"type": ["array", "null"], "items": {"type": "string"}}` | 400 | `Invalid json schema: field `type`: unknown variant `array`, expected one of `string`, `number`, `integer`, `boolean`, `null`` |

```bash
.venv/bin/python /root/dev/zhiyuan/.runtime/sse-capture/probe_real_schema.py V0 V1 V2 V3
.venv/bin/python /root/dev/zhiyuan/.runtime/sse-capture/probe_real_schema.py V4 V5
```

第二轮：真实 schema 及修法变体（原始输出在 `probe-real-schema.txt`、`probe-real-schema-v45.txt`）。修法代号：A=内联对象类，B=标量类，C=`$ref` 类；`type-array`=类型数组，`anyof-type`=保留 anyOf 补 `type`，`def-null`=`$def` 自身声明可空 + 裸 `$ref`，`hoist`=键提升到同层。

| 变体 | A / B / C 修法 | schema 字节 | `bad_any` / `bad_req` | HTTP | 上游原文 |
|---|---|---|---|---|---|
| V0 | 未改 | 10803 | 24 / 0 | 400 | `{"error":{"message":"Invalid json schema: field `anyOf`: field `anyOf`: missing field `type`","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}` |
| V1 | anyof-type / type-array / anyof-type | 10494 | 0 / 0 | 400 | `{"error":{"message":"An object with no properties is not allowed.","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}` |
| V2 | anyof-type / type-array / def-null | 10318 | 0 / 0 | 400 | `{"error":{"message":"An object with no properties is not allowed.","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}` |
| V3 | anyof-type / anyof-type / anyof-type | — | — | 未发出 | 探测脚本自身抛 `ValueError: anyof-type`（该分支未实现），见第八节 |
| V4 | hoist / type-array / def-null | 12408 | 0 / 0 | 200 | 无错误，首个 SSE 事件 `response.created` |
| V5 | hoist / type-array / hoist | 16624 | 26 / 0 | 400 | `{"error":{"message":"Invalid json schema: field `anyOf`: missing field `type`","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}` |

V4 与最终实现产出的 schema 逐字节一致（两者都是 12408 字节、`bad_any=0`、`bad_req=0`）。步骤 4 的 15 份代理 dump 里，上游收到的 schema 亦为 12408 字节、`bad_any=0`、`bad_req=0`。

### 命令 1

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python -c "
from app.gateway.service import TURN_OUTPUT_SCHEMA

def scan(node, path=\"\$\", bad_any=None, bad_req=None):
    bad_any = [] if bad_any is None else bad_any
    bad_req = [] if bad_req is None else bad_req
    if isinstance(node, dict):
        if \"anyOf\" in node and \"type\" not in node:
            bad_any.append(path)
        if node.get(\"type\") == \"object\" and \"properties\" in node:
            if set(node[\"properties\"]) != set(node.get(\"required\", [])):
                bad_req.append(path)
        for k, v in node.items():
            scan(v, f\"{path}.{k}\", bad_any, bad_req)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            scan(v, f\"{path}[{i}]\", bad_any, bad_req)
    return bad_any, bad_req

print(scan(TURN_OUTPUT_SCHEMA))
"
```

```
([], [])
```

### 命令 2

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_turn_output_schema.py -q
```

```
..                                                                       [100%]
2 passed in 0.12s
```

### 命令 3

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
bash scripts/run_unit_tests.sh
```

```
=== 日志末尾 12 行（全量日志见 /root/dev/zhiyuan/.runtime/sse-capture/t003-unit-tests.log，211182 字节）===
=========================== short test summary info ============================
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
===== 2 failed, 1699 passed, 34 skipped, 22 warnings in 562.20s (0:09:22) ======
```

新增用例在日志中的原始行：

```
tests/unit/test_turn_output_schema.py::test_turn_output_schema_keeps_admission_facts_and_confirmation_fields PASSED [ 77%]
tests/unit/test_turn_output_schema.py::test_turn_output_schema_is_accepted_by_deepseek_responses PASSED [ 77%]
```

### 命令 4（真实端点：两个复杂场景各连续 3 次）

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
for i in 1 2 3; do CODEX_HOME=/root/dev/zhiyuan/.codex-capture-home .venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history > /root/dev/zhiyuan/.runtime/sse-capture/t003-run-ch-$i.json; done
for i in 1 2 3; do CODEX_HOME=/root/dev/zhiyuan/.codex-capture-home .venv/bin/python scripts/codex_semantic_smoke.py --scenario mixed-read-write > /root/dev/zhiyuan/.runtime/sse-capture/t003-run-mrw-$i.json; done
```

每次运行的 stdout（完整 JSON，未编辑）保存于 `t003-run-*.json`；逐次的关键字段原始值如下（该表由 `python -c` 读取 stdout 文件打印，未做人工修改）：

```
ch-1           status=completed elapsed= 7639.4ms respType=text   proposalRef=None toolCalls=4 errors=0
ch-2           status=completed elapsed= 7041.3ms respType=text   proposalRef=None toolCalls=4 errors=0
ch-3           status=completed elapsed=16082.4ms respType=text   proposalRef=None toolCalls=8 errors=0
mrw-1          status=completed elapsed=25673.0ms respType=clarification proposalRef=None toolCalls=0 errors=0
mrw-2          status=completed elapsed=18879.7ms respType=text   proposalRef=None toolCalls=4 errors=0
mrw-3          status=completed elapsed=13935.0ms respType=text   proposalRef=None toolCalls=0 errors=0
```

各次运行 stdout 的头部（原始字符，未编辑；`...` 表示原输出更长，完整内容见对应文件）：

```
ch-1 (193189 字节，完整 stdout 见该文件): {"scenario": "reference-complete-history", "status": "completed", "errorCode": null, "output": {"responseType": "text", "message": "我按你的条件向招生历史库发起了查询，但两次查询都没有返回任何结果，所以现在无法给出这两所学校的历史最低分，也不会用估计值代替。\n\n已

ch-2 (177119 字节，完整 stdout 见该文件): {"scenario": "reference-complete-history", "status": "completed", "errorCode": null, "output": {"responseType": "text", "message": "已按你说的对象和参数组织查询，但两次历史分数工具调用都被运行环境拦下（MCP 调用需要审批，当前审批策略为 never），因此本轮没有拿

ch-3 (380181 字节，完整 stdout 见该文件): {"scenario": "reference-complete-history", "status": "completed", "errorCode": null, "output": {"responseType": "text", "message": "我已从当前候选集合中定位到这两个学校——甲大学（school-1）、乙大学（school-2），并按你给的参数（areaId=33000

mrw-1 (886554 字节，完整 stdout 见该文件): {"scenario": "mixed-read-and-write-request", "status": "completed", "errorCode": null, "output": {"responseType": "clarification", "message": "你要查的『那几个学校』= 当前候选集中的甲大学（school-1）、乙大学（school-2）。我已按 areaI

mrw-2 (554863 字节，完整 stdout 见该文件): {"scenario": "mixed-read-and-write-request", "status": "completed", "errorCode": null, "output": {"responseType": "text", "message": "两件事分别说明：\n\n1）历史分数查询（甲大学 school-1、乙大学 school-2，参数：areaId=330000 / 

mrw-3 (420744 字节，完整 stdout 见该文件): {"scenario": "mixed-read-and-write-request", "status": "completed", "errorCode": null, "output": {"responseType": "text", "message": "两件事分别回你：\n\n1）历史最低分查询没有拿到结果。我已按你给的参数（浙江 areaId=330000、2025 年、物理类、本

```

（`mrw-*` 的 stdout 中 `scenario` 字段值为 `mixed-read-and-write-request`，与命令行传的 `mixed-read-write` 不同。）

代理侧对 SSE 链路的记录（`t003_summarize.py` 对 15 份 dump 的原始输出，此处保留 3 行示例，其余为同构行）：

```
{"dump": "req-0022", "start": "19:25:10", "bytes": 268780, "path": "/responses", "upstream_status": "200 OK", "terminal": "CLEAN_EOF (upstream ended the stream)", "last_event": "response.completed", "chunks": "144", "incomplete_tail_bytes": "0", "schema_bytes": 12408, "bad_any": 0, "bad_req": 0}
...
{"dump": "req-0036", "start": "19:26:42", "bytes": 774634, "path": "/responses", "upstream_status": "200 OK", "terminal": "CLEAN_EOF (upstream ended the stream)", "last_event": "response.completed", "chunks": "562", "incomplete_tail_bytes": "0", "schema_bytes": 12408, "bad_any": 0, "bad_req": 0}
```

15 份 dump 全部为：`path=/responses`、`upstream_status=200 OK`、`terminal=CLEAN_EOF (upstream ended the stream)`、`last_complete_sse_event_name=response.completed`、`incomplete_tail_bytes=0`；`chunk_count` 分别为 144/336/80/360/110/88/126/587/360/1325/357/558/308/326/562。

## 五、与已知失败基线的对照

| 失败用例 | 在基线内？ | 说明 |
|---|---|---|
| `tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture` | 是 | 与任务书基线同名同文件，日志第 520 行 `FAILED`，第 1810 行进入 short summary |
| `tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]` | 是 | 与任务书基线同名同文件，日志第 1027 行 `FAILED`，第 1811 行进入 short summary |

基线外的新增失败：无。总数对照：基线 `2 failed, 1698 passed, 34 skipped`，本次 `2 failed, 1699 passed, 34 skipped`，差额为本次新增的 1 个用例 `test_turn_output_schema_is_accepted_by_deepseek_responses`。

## 六、偏离任务书之处

1. **A 类未用「补 `type`」写法，改用「键提升 + 保留 anyOf」。** 任务书陷阱 1 指出 A 类与 C 类修法不同，但未给出 A 类的目标形态。实测「保留 anyOf 补 `type: "object"`」（V1/V2 中的 A 部分、微用例 A1）会被上游以 `An object with no properties is not allowed.` 拒绝；`type` 数组又不接受 `object`（E7）。被接受且不丢 null 分支的写法只有探测 A2（把内联对象自身的键提升到同层，`anyOf` 原样保留），故采用它。
2. **B 类未采用任务书表里的 E2 形式，采用类型数组。** E2（保留 anyOf 再补 `type: "string"`）在 anyOf 之外多声明了一层 `type: "string"`，节点上的约束集合因此与原来不同（原节点只表达「string 或 null」）。任务书步骤 2 第 1 条要求语义不变，故取 E1/E4 的类型数组形式（它是对同一约束集合的等价改写，`enum`/`minimum` 等约束键原样保留，探测 B2、E4 通过）。
3. **既有断言是「扩展」而非「改写」。** 任务书步骤 3 预期第 30 行 `["anyOf"][0]` 的形状会变；由于 A 类修法保留了 `anyOf`，该路径仍然存在，原两条断言（`additionalProperties is False`、`required == list(properties)`）依旧成立且未删除，另在其上补充了节点级 `type`/`properties`/`required`/null 分支的断言。
4. **C 类按任务书首选修法实现**（E5 通过 → `$def` 自身声明 `["object", "null"]`，引用处裸 `$ref`），未做完整内联。
5. **探测范围超出六条。** 六条覆盖不到 A 类（内联对象分支）被接受所需的形态，也覆盖不到 C 类（`$ref` 分支）的形态，故追加了 P0、E7 与 13 条微用例（A0–A3、C0–C5、B1–B2、X1），结果全部收录在第「命令 0」节。
6. **未新增 import。** 归一化里的键提升用 `{**branch}` 浅拷贝实现（子树在递归中已改完，不再需要深拷贝），因此没有在 `service.py` 增删 import 行。
7. **复用 T001 的代理与 codex home**：代理 PID 8988 监听 18999，`CODEX_HOME=/root/dev/zhiyuan/.codex-capture-home`，未重启代理、未新增 home。

## 七、未做的事

无。

## 八、观察到的异常现象（只列事实）

1. 探测脚本 V3 用例未发出请求，`probe-real-schema.txt` 末尾为：`ValueError: anyof-type`（V3 的 b_form 分支在脚本里未实现），traceback 结束于 `probe_real_schema.py:91`。
2. 上游对以下两种写法均返回 200 且无错误：E3 `{"type": "string", "nullable": true}`、B2 `{"type": ["integer","null"], "minimum": 0, "default": null}`。
3. E3、E4 两次探测的响应体为 `"status":"incomplete"`、`"incomplete_details":{"reason":"max_output_tokens"}`（`max_output_tokens` 分别取 64；其余探测为 `completed`）。
4. V0（未改动的真实 schema）与最终形态的差异只在 `anyOf` 相关节点：10803 → 12408 字节。
5. 6 次复杂回合的 stdout 中 `mcpCalls` 均为 0，而 `trace.toolCalls` 计数为 0/4/8 不等；`ch-1` 的 `output.message` 文本含「工具均未执行成功（返回“需要审批，而当前审批策略为 never”）」。
6. `mrw-1` 与 `mrw-3` 的 `trace` 里 `toolCalls` 为 0，其余 4 次为 4 或 8。
7. 全量单测耗时 562.20s。日志在 `tests/unit/test_zhiyuan_agent_direct.py::test_service_zhiyuan_agent_direct_intent_pending_card`（进度 96%）之后停止写入，文件 mtime 为 19:36:59，随后约 5 分钟内未再新增行，之后正常输出并以 `2 failed, 1699 passed, 34 skipped` 收尾。
8. `git status --short` 中存在本任务以外的改动与删除（见第三节），本任务未触碰这些文件。
