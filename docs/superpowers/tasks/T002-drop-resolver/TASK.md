# 任务 B：清理悬空的 resolver 模块并修正过时文档

> 指派：DeepSeek 实现会话
> 来源计划：`docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md` 的 P4
> 类型：删除 + 小幅改写。**范围严格限定在本文列出的文件，不要扩散**

---

## 一、目标

删除一套约 2900 行、只被测试引用、生产代码零调用的悬空模块，同时保住它间接提供的一处生产测试覆盖，并修正 `CLAUDE.md` 中三处与代码不符的描述。

---

## 二、你需要知道的背景（你的会话没有这些上下文）

`/root/dev/zhiyuan/zhiyuan-agent` 是一个高考志愿咨询系统的 Python Agent 服务。它历史上有一套「结构化意图 → 类型化动作」的确定性解析引擎（`IntentFrame` + `ActionResolver` + `typed_actions`），设计意图是替代早期基于关键词匹配的路由。

这套东西写完了、测试很全，**但从未接入生产运行时**。真正在跑的是 `app/service.py` 里基于 `ConversationPhase` 的状态机。项目正在迁移到新的 codex 对话引擎，这套中间产物不会被使用，留着只会增加维护面和阅读成本。

以下事实**已经过核实，直接用，不要重新调查**。

---

## 三、Part 1：删除这些文件

```
app/models/intent_frame.py                    (225 行)
app/models/typed_actions.py                   (293 行)
app/resolver/action_resolver.py               (609 行)
app/resolver/__init__.py
tests/unit/test_action_resolver.py            (881 行)
tests/unit/models/test_intent_frame.py        (284 行)
tests/unit/models/test_typed_actions.py       (356 行)
tests/integration/test_resolver_vs_legacy.py  (247 行)
```

`app/resolver/` 整个包删掉（删完如果目录空了，把目录也删掉，注意可能残留 `__pycache__`）。

---

## 四、Part 2：改写 `tests/regression/test_keyword_matchers.py`（**不要删它**）

这个文件也 import 了 `IntentFrame` 和 `ActionResolver`，看起来应该一起删。**但不能删**，原因：

它同时 import 了 `app/tools/review_issue_registry.py` 的 5 个函数：

```python
from app.tools.review_issue_registry import (
    normalize_review_issue_code,
    review_issue_default_action_family,
    review_issue_label,
    review_issue_scope_kind,
    review_issue_supported_action_families,
)
```

而 `app/tools/review_issue_registry.py` **被生产代码 `app/zhiyuan_agent/tools.py` 使用**，并且 `test_keyword_matchers.py` 是它在整个测试套件里的**唯一覆盖**（已用 `grep -rln "review_issue_registry" tests/` 确认只有这一个文件）。删掉它等于静默移除一个在跑的生产模块的全部测试。

**要做的**：改写这个文件，去掉 `IntentFrame` / `ActionResolver` / `make_plan_context_inputs` 相关的用例和 import，**保留并保住** 那 5 个 `review_issue_registry` 函数的契约断言。如果原有断言是通过 resolver 间接验证的，就改成直接对这 5 个函数断言。文件名保持不变（原文件头注释写明"保留原文件名，避免测试清单漂移"）。

改写后这个文件必须仍然能独立通过。

---

## 五、Part 3：编辑这两个文件

### 1. `app/models/__init__.py`

删除这些 re-export（当前在第 11、17 行附近，以及 `__all__` 里的第 20-26 行附近）：

```python
from app.models.intent_frame import IntentFrame, TargetSpec, ScopeSpec
from app.models.typed_actions import PlanAction
```

以及 `__all__` 中的 `"IntentFrame"`、`"TargetSpec"`、`"ScopeSpec"`、`"PlanAction"` 四项。文件顶部 docstring 里描述 `intent_frame` 和 `typed_actions` 的两行说明也一并删掉。

### 2. `examples/dialog_quality_gate.py`

它的 `LOCAL_PYTEST_TARGETS` 列表（约第 35 行）包含 `"tests/unit/test_action_resolver.py"`。该文件被删后这一项会让门禁脚本失败，**移除这一项**。

已核实：全仓库只有 `tests/unit/test_release_410_plan_change_contract.py:279` 对 `LOCAL_PYTEST_TARGETS` 做了断言，而它断言的是另一个文件（`test_release_410_plan_change_contract.py`）在不在列表里，与本次改动无关。所以这处编辑是安全的。

---

## 六、Part 4：修正 `CLAUDE.md` 三处过时描述

以下三处已核实与代码不符：

| 位置 | 现在写的 | 实际 | 怎么改 |
|---|---|---|---|
| 第 65 行 | `**ChatAgent** (app/agent/chat_agent.py) — 继承 BaseAgent，……注册意向提取工具和技能目录` | **这个类和文件都不存在**。`app/agent/` 下只有 `base_agent.py`、`context.py`、`usage_tracker.py`、`instructions/` | 删掉这一条 |
| 第 98 行 | `技能定义在 skills/ 目录下，当前有 skills/intake_chat/SKILL.md。Agent 运行时通过 pydantic-ai-skills 的 SkillsToolset 按需发现和加载技能。` | `skills/` 下现有 8 个目录；且**生产的 `ZhiyuanAgent` 从不传 `skill_dirs`**，`SkillsToolset` 在生产运行时不生效。真正传 `skill_dirs=["./skills"]` 的只有 `examples/demo_agent.py` | 改成如实描述：`skills/` 下的 7 个 `SKILL.md` 目前仅由 `examples/demo_agent.py` 加载，生产 `ZhiyuanAgent` 未启用 `skill_dirs`；`skills/codex/` 是给外部 codex 二进制用的独立格式，不走 `SkillsToolset` |
| 第 13 行 | `pydantic-ai-skills — 技能按需加载` | 同上，容易被读成生产机制 | 补一句限定，说明当前仅 demo 使用 |

**不要删 `skills/` 下任何目录。** 那 7 个 skill 是 `examples/demo_agent.py` 的技能集，而 `demo_agent.py` 在 `AGENTS.md:31` 和 `CLAUDE.md:39` 中被记为可运行示例，还有 `tests/integration/test_agent_integration.py:62` 的 `test_demo_agent_subclass` 覆盖。

---

## 七、陷阱（会让你踩坑或误伤的地方）

1. **`PlanAction` 有同名冲突**。`app/zhiyuan_agent/tools.py:85` 自己定义了
   `PlanAction = Literal["add", "remove", "move", "replace", "sort", "generate", "regenerate_order", "pin_lock"]`
   这是**完全不同的类型**，和 `app/models/typed_actions.PlanAction` 无关。你 grep `PlanAction` 会在生产代码里看到命中（`tools.py:85`、`tools.py:10269`），**那些不要动**。同理 `app/zhiyuan_agent/agent.py:209` 的 `invalidPlanActionLocatorRejected` 只是个字符串键，无关。

2. **不要删 `tests/regression/test_keyword_matchers.py`**（理由见 Part 2）。这是本任务最容易犯的错。

3. **不要删 `skills/` 下任何东西**（理由见 Part 4）。

4. `app/models/__init__.py` 里除了这四个名字还导出别的东西，**只删这四个及其 import 行**，其余保持原样。

5. 删除后可能残留 `.pyc` 和 `__pycache__`，清掉，避免 import 假成功掩盖问题。

---

## 八、验收

按顺序执行，全部必须通过：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent

# 1. 确认悬空模块已无任何引用（应无输出）
grep -rn "intent_frame\|typed_actions\|action_resolver\|ActionResolver\|IntentFrame" --include=*.py app/ tests/ examples/

# 2. 确认生产模块的测试覆盖还在（应有输出）
grep -rln "review_issue_registry" --include=*.py tests/

# 3. 改写后的文件独立通过
.venv/bin/python -m pytest tests/regression/test_keyword_matchers.py -q

# 4. 全量单测
bash scripts/run_unit_tests.sh
```

第 4 步如果有失败，**逐条列出失败用例名和报错**，不要自行猜测修复范围外的代码。

---

## 九、边界：不要做这些

- 不要动 `app/service.py`（8882 行）和 `app/zhiyuan_agent/tools.py`（11402 行）。本任务与它们无关。
- 不要动 `app/gateway/`、`app/engine/`、`app/harness/`、`app/mcp_server/` 下任何文件。
- 不要"顺手"重构、格式化、改 import 顺序、加类型标注。只做本文列出的删除和改写。
- 不要删 `skills/`、不要删 `examples/demo_agent.py`、不要删 `examples/dialog_quality_gate.py`。
- 不要 commit。改完等 review。

---

## 十、汇报格式

只用以下四种状态之一开头：

- `DONE` — 四步验收全过
- `DONE_WITH_CONCERNS` — 完成但有偏差（例如某个测试失败但你判断与本次改动无关），说明偏差和判断依据
- `BLOCKED` — 被挡住，附原始报错
- `NEEDS_CONTEXT` — 任务书信息不足，说明缺什么

报告里附：实际删除的文件清单、`test_keyword_matchers.py` 改写后保留了哪几条断言、验收第 4 步的输出尾部。
