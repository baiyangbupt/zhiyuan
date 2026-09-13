# T009：冒烟 payload 存一份拼好的 agentMessage 正文

> 派发日期：2026-09-13
> 来源：T008 REVIEW 第六节（**注意读那一节的第八节勘误**，范围比最初说法小得多）
> 实现方只读本文。**不要去读 T008 的 REPORT/REVIEW**，本文已自足。

---

## 一、背景：这不是"数据丢了"，是"读的人得会拼"

`scripts/codex_semantic_smoke.py` 跑完一次会把整个 payload 落成 JSON。里面有 `eventSummaries`，构造代码在 `scripts/codex_semantic_smoke.py:202-214`：

```python
"eventSummaries": [
    {
        "type": event.get("type"),
        "keys": sorted(str(key) for key in event),
        "text": str(
            event.get("text")
            or event.get("message")
            or event.get("delta")
            or ""
        )[:500],
    }
    for event in result.events
],
```

它只读事件**顶层**的 `text` / `message` / `delta`。于是：

- `item/agentMessage/delta` 事件有顶层 `delta` 键 → **正文碎片被采到了**，一个事件一片。
- `item/completed` 事件的正文在 `event["item"]` 里 → **顶层没有 `text`，摘要是空串**。

**结论：模型写的字一直在 payload 里，只是碎成几百片，拼好的那一份被丢掉了。**

以下是实测数据（2026-09-13，`reference-complete-history`，两次真实运行）：

| | run A | run B |
|---|---|---|
| `eventSummaries` 条数 | 1725 | 1477 |
| `item/agentMessage/delta` | 671 | 756 |
| `item/reasoning/textDelta` | 1034 | 696 |
| `item/completed`（`text` 全为 `""`） | 6 | 8 |
| payload 大小 | 260 KB | 228 KB |
| 最长的单个 delta 片段 | **10 字符** | 同量级 |

最后一行要留意：**没有任何片段接近那个 `[:500]` 上限**，所以截断不是问题，分散才是。把 671 片按序拼起来能得到完整的 2460 字符原文，一字不差——**这件事已经手工验证过了**。

### 为什么这值得修

前几天有一次运行 `evaluation.passed == false`，要判断是解析器出了问题还是模型真的没给输出，唯一的办法是：打开 260 KB 的 JSON，筛出 671 个 delta，按序拼接，再喂给解析器。**一个需要知道诀窍才做得了的诊断，在真出事的时候就是不会有人做的诊断。**

修法很小：`item/completed` 里本来就带着拼好的那一份，把它也存下来。

---

## 二、已核实的环境事实（不要重新调查）

1. **仓库根**：`/root/dev/zhiyuan`，要改的脚本在 `/root/dev/zhiyuan/zhiyuan-agent/scripts/codex_semantic_smoke.py`。
2. **Python 解释器**：`/root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python`。
3. **agentMessage 事件怎么认**：`app/harness/codex.py:163-164` 已经在这么做了，照抄它的判据：

   ```python
   item = event.get("item") or {}
   if event.get("type") == "item/completed" and item.get("type") == "agentMessage":
   ```

4. **正文有两种形状，都要处理。** `app/harness/codex.py:301-315` 是现成的、已经在真实端点上跑通的读法：`item["text"]` **可能是 `str`，也可能是 list**，list 的每个元素是 dict、正文在其 `["text"]` 里。

   **不要只写 `str(item.get("text"))`**——碰上 list 形状会得到 `"[{'text': ...}]"` 这种垃圾字符串，而且它看起来像成功了。

   我**没有**实测过这两种形状各自出现的频率，`codex.py` 里两条分支都写了但可能有一条从没走到过。所以第五节验收里有一条要求你**报出实际出现的是哪种、各多少次**——这是观测任务，不是让你去猜。

5. **真实端点可用**，`.venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history` 单次约 8–15 秒。它有约 5% 的概率返回 `evaluation.passed=false`（模型自身抖动），**这不是你的改动造成的**，照实记录即可。

6. **已知失败基线**（`bash scripts/run_unit_tests.sh`）：

   ```
   FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
   FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
   2 failed, 1712 passed, 34 skipped
   ```

   这两条与本任务无关，**不要去修**。基线以外的失败才需要报告。

7. **同一个工作树里有另一个会话在干活**（改 `zhiyuan-server/` 下的 Java）。见第六节。

---

## 三、要做的事

### 改动 1：payload 里加 `agentMessages`

在 payload 里新增一个**顶层**键 `agentMessages`，值是一个 list，每项对应一条走完的 agentMessage：

```python
{"itemId": <item.get("id") 之类的标识，取不到就 None>, "text": <完整正文>}
```

要求：

- **不截断。** 不要加 `[:500]` 或任何上限。截断正是这次要解决的毛病。
- **两种形状都要能拿到正文**（`str` 和 list-of-dict，见第二节第 4 条）。取不到就存空串，不要抛异常。
- **顺序**按事件出现顺序。
- 具体字段名之外的实现形式（要不要抽个小函数、放在哪一行）你自己定。

### 改动 2：这个键必须**无条件**写

`agentMessages` 必须在**所有**返回路径上都出现，包括：

- `status != "completed"`
- `status == "completed"` 但 output 解析失败
- 正常成功

**理由不是洁癖。** 这个脚本上一个 bug 就是这个形状：某个键只在成功路径上写，失败时根本不写，于是 `d.get('evaluation', {}).get('passed')` 读出 `None`——不报错、不为真、看起来就像一次普通的不通过，**藏了很久**。

`agentMessages` 恰恰是**失败时才需要看**的东西。只在成功路径上写等于没写。

### 不要做的事

- **不要动 `eventSummaries` 的现有结构**（字段名、`[:500]`、delta 的采集方式一律不改）。碎片留着，它是 `agentMessages` 的独立交叉验证来源，第五节验收第 3 条要用。
- **不要**顺手去优化 payload 体积 / delta 洪流。那是另一件事，不在本任务范围内。
- **不要**改 `app/harness/` 下的任何文件。正文读法从 `codex.py` **抄**，不要去重构它、不要把它抽成公共函数。

---

## 四、验收

每条都要在报告里贴**未经编辑的原始输出**。命令没跑就写没跑，不要写预期结果。

**1. 新增单测：三条路径都写 `agentMessages`。**

构造三个假的 `CodexTurnResult`（`status="failed"`；`status="completed"` 但 output 解析不出；`status="completed"` 正常），断言三种情况下 payload 里 **`"agentMessages" in payload` 都为真**。

**用 `in`，不要用 `.get()`**——缺键必须看得见。

**2. 新增单测：两种正文形状都取得到。**

一个事件的 `item["text"]` 是 `str`，另一个是 `[{"text": "..."}]`，断言两者都取出正确正文。**list 那条要断言取出的是里面的字符串，不是 `"[{'text': ...}]"`。**

**3. 真实端点交叉验证（本任务的核心验收）。**

跑一次真实场景，然后用**两条互相独立的路径**从同一个 payload 里取模型正文，断言二者相等：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
.venv/bin/python scripts/codex_semantic_smoke.py --scenario reference-complete-history \
  > /tmp/t009-run.json 2>/tmp/t009-run.err
.venv/bin/python - <<'PY'
import json
d = json.load(open('/tmp/t009-run.json'))
assert 'agentMessages' in d, "agentMessages 键缺失"
from_item = "".join(m['text'] for m in d['agentMessages'])
from_delta = "".join(
    e['text'] for e in d['eventSummaries']
    if e.get('type') == 'item/agentMessage/delta'
)
print(f"agentMessages 条数: {len(d['agentMessages'])}")
print(f"从 item/completed 取: {len(from_item)} 字符")
print(f"从 delta 碎片拼:     {len(from_delta)} 字符")
print(f"两者相等: {from_item == from_delta}")
if from_item != from_delta:
    print("MISMATCH head(item) :", repr(from_item[:200]))
    print("MISMATCH head(delta):", repr(from_delta[:200]))
PY
```

**这条能失败，而且失败了是有意义的**：如果 `item/completed` 并不携带完整正文，两边就对不上，那说明改动 1 的前提错了——**照实报 `BLOCKED` 或在报告里写清楚，不要去改断言迁就结果**。

**4. 报出正文的实际形状。** 在同一次运行里统计 `item["text"]` 是 `str` 的有几个、是 list 的有几个，把数字写进报告。**允许某一种是 0**，如实写 0 即可。

**5. 全量单测。**

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
bash scripts/run_unit_tests.sh 2>&1 | tail -6
```

与第二节第 6 条的基线逐条对照。通过数应为 1712 + 你新增的条数。

---

## 五、边界：不要动这些

- `app/harness/` 下的**任何**文件（`codex.py`、`turn_result.py` 等）
- `app/engine/` 下的任何文件
- `tests/fixtures/` 下的任何文件（尤其是只读 MCP 夹具）
- 任何含 `TURN_OUTPUT_SCHEMA` 的文件
- `docker-compose.codex-local.yml`
- **整个 `zhiyuan-server/` 目录**——那是另一个会话正在改的，碰了就是事故
- `.codex-semantic-home/` 下任何文件（**尤其不要原地改 `config.toml`**）

## 六、两条硬约束

1. **不要运行任何会改动工作树的 git 命令。** `checkout` / `restore` / `stash` / `reset` / `clean` / `add` / `commit` **全部禁止**。只读的 `status` / `diff` / `log` 可以。

   **这条不是形式主义**：另一个会话此刻在同一个工作树里有大量未提交的 Java 改动，一条 `git stash` 能悄无声息地删掉它几小时的工作。

2. **不要 commit。** 改完等复核，由设计会话统一提交。

   另外：跑全量单测时如果撞到基线以外的失败，**先看它落在谁的改动面上**。落在 `zhiyuan-server/` 或 Java 相关的，照实记录并注明"疑似并发改动导致，未处理"，**不要去修**。

3. **鉴权信息不要出现在报告、脚本、dump 里。** 不要打印 `auth.json` 的内容。

---

## 七、报告

把报告写到：

```
/root/dev/zhiyuan/docs/superpowers/tasks/T009-agent-message-capture/REPORT.md
```

**报告文件不存在 = 任务未交付**，无论对话里说了什么。如果你的工具不允许写这个文件，**不要绕过限制**（不要改用 shell heredoc、不要转派），如实说明并把全文作为文本返回。

格式：

```markdown
---
task: T009
status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
executor: <你是谁>
finished_at: <时间>
---

## 一、结论
## 二、交付物（路径 + 说明）
## 三、实际改动的文件（git status --short，只列本任务的）
## 四、验收命令与原始输出（逐条，贴原文）
## 五、与已知失败基线的对照
## 六、偏离任务书之处
## 七、未做的事
## 八、观察到的异常现象（只列事实）
```

**第八节只写事实**：改了什么、命令输出是什么、报错原文是什么。**不写修复建议、不写根因推测、不写下一步计划**——定性是设计会话的活。你观察到异常，如实记录现象本身即可。

状态词只能是上面四个之一。`DONE` 的意思是"我认为验收过了"，不是结论；结论由复核给出。
