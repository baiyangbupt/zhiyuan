# T009 复核：拼好的 agentMessage 正文进 payload

> 日期：2026-09-13
> 复核人：设计会话（Claude Opus 5）
> 实现方：Claude Sonnet 5 subagent
> 实现方状态：`DONE`

---

## 一、判定

**`ACCEPTED_WITH_FOLLOWUP`**

核心交付物成立，且我自己重跑验证过，不是采信报告。三条"偏离"里**有一条根本不是偏离**（任务书授权了），一条是**我的任务书自相矛盾逼出来的**，只有一条是真实遗留。

---

## 二、我自己重跑了什么

协议第七节要求"自己重跑一遍验收命令，不采信报告里的输出"。以下全部是我这边跑出来的数。

### 1. 真实端点交叉验证：3 次，全部逐字节相等

```
run 1: nFrags=854  longestFrag=10 len(item)=2124 len(delta)=2124 EQUAL=True
run 2: nFrags=764  longestFrag=9  len(item)=1972 len(delta)=1972 EQUAL=True
run 3: nFrags=1033 longestFrag=12 len(item)=2761 len(delta)=2761 EQUAL=True
```

三次 `status=completed`、`evaluation.passed=True`、`agentMessages` 键均存在且长度为 1。

**加上实现方那 1 次，交叉验证 4/4。** 正文长度每次都不同（2124 / 1972 / 2761 / 2040），说明比对的不是一个常量。

**顺带确认了这条验收的前提**：delta 碎片最长 10 / 9 / 12 字符，`eventSummaries` 的 `[:500]` 截断**从未生效**。所以"用 delta 拼出来的正文"是一个合法的判准——如果碎片可能超过 500 字符，这个 oracle 本身就是坏的，比对相等只能说明两边一起坏了。

### 2. 全量单测：自己跑的

```
FAILED tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
FAILED tests/unit/test_ops_release_smoke.py::test_release_smoke_supports_production_and_dev_web_base_paths[None-/assistant-pc/session]
=========== 2 failed, 1714 passed, 34 skipped, 22 warnings in 27.81s ===========
```

与报告逐字一致。1714 = 1712（T008 后基线）+ 2（本任务新增单测），算术对得上。

### 3. 无条件写出：从代码结构核，不只看单测

```
195:  payload: dict[str, object] = _build_base_payload(expectation, result)
240:  return payload      ← outputValidationError 路径
251:  return payload      ← trace 路径 与 _missing_output_evaluation 路径 汇合于此
```

`:195` 在任何 `result.status` 分支之前，两条 `return` 全在其下游，`:195` 之前没有任何提前返回。**结构上保证，不依赖单测覆盖。**

### 4. 边界

`git status --short` 里 `zhiyuan-agent/` 下只有声明的那 2 个文件。其余全部在 `zhiyuan-server/` 下，是 `zhiyuan-48` 的 P1b-1 在飞——与 T009 零重叠，未被触碰。

---

## 三、我自己的复核脚本先红了一次，这件事要记下来

第一次跑交叉验证我得到 `EQUAL=False`，三次都不等（2124 vs 5183）。**是我的检查脚本错了**：我用 `'delta' in type.lower()` 去筛事件类型，把 `item/reasoning/textDelta`（模型的思考过程）和 `item/agentMessage/delta`（正文）一起拼进去了。改成精确匹配 `item/agentMessage/delta` 后三次全相等。

代码没问题，我的判准有问题。但这次失手有个意外的价值：

**它证明了这条交叉验证不是恒真的。** 本会话反复在查"永远通过的检查"，而验收条自己也要过这一关。第一问"有没有一种输入能让它失败"——**有，我刚刚亲手喂了一个，它立刻亮红灯，而且红得很干净（长度差了一倍多，一眼能看出是哪边错）**。第二问"能让它失败的输入正是我们想防的行为吗"——是：拼错、漏拼、截断、取错字段，全都会让长度对不上。

**这是本会话第一条经得起两问的验收条。** 前面查出来的三类缺陷（恒真、方向反、分辨力不足）它都不沾。

---

## 四、三条偏离逐条判

### 偏离 1（`_build_base_payload` 重构）——**不是偏离，任务书授权了**

实现方说"任务书没有明确授权把整个 payload 字典构造都抽出来"。**它把自己的权限说小了。** 任务书第三节 `:105` 原文：

> 具体字段名之外的实现形式（要不要抽个小函数、放在哪一行）你自己定。

而且更强的一点：**任务书的验收第 1 条实际上要求了这次抽取**——它要求"构造三个假的 `CodexTurnResult`，断言三种情况下 `"agentMessages" in payload`"。`run_scenario` 是个要跑完整 harness 生命周期的 async 函数，不留一个纯函数接缝，这条验收就只能靠 mock 整个 harness 来做。**我写下那条验收的时候就已经隐含要求了一个可单测的接缝。**

核查结果：从 diff 逐键比对，九个原有键 `scenario` / `status` / `errorCode` / `output` / `outputExtraction` / `eventTypes` / `eventSummaries` / `errors` / `contextCandidateIds` 的构造表达式**与原代码语义相同**，差别只有整体缩进少 4 格（从 `run_scenario` 函数体内移到模块级函数体内），`agentMessages` 插在 `eventSummaries` 与 `errors` 之间。`eventSummaries` 里那段 `str(... or ... or ... or "")[:500]` 一字未动。

**判定：合规。** 记这一笔是为了立个先例——**实现方主动把"我可能越界了"写进偏离节，是对的**，哪怕最后判下来没越界。宁可多报。

### 偏离 2（形状统计来自另一次运行）——**是我的任务书自相矛盾**

这条实现方报得准确，但**账不该记在它头上**。

任务书两处互相打架：

- `:170` 验收第 4 条："**在同一次运行里**统计 `item["text"]` 是 `str` 的有几个、是 list 的有几个"
- `:103-105` 交付物规格：`agentMessages` 只有 `itemId` / `text` 两个字段

**形状信息按我自己定的规格就不会被留下来。** 于是验收第 4 条要的那个数字，从交付物里**读不出来**。实现方只有两条路：加字段（超出"改动 1/改动 2"的字面范围），或者走交付物之外的临时探针。它选了后者，并且把"这是第二次真实调用、不是第 3 条那次"明明白白写进报告——**处理方式是对的**。

由此得到**第四类验收缺陷**，已补进 `README.md` 第六节：

> **验收条要的观测，交付物在规格上产不出来。**
> 前三类问的是"这条判据好不好"，这一类问的是"这条判据**够得着吗**"。
> 判别办法：每写完一条验收条，问一句——**这个数字，从交付物的哪个字段、哪条输出里读出来？** 答不上来，就是在逼实现方要么超范围加东西、要么走交付物外的一次性探针，两条都是偏离，而且是**我造成的偏离**。

**判定：合规，账记在设计会话。**

### 偏离 3（多元素 list 拼接未被真实数据覆盖）——**真实遗留，接受**

见下一节。

---

## 五、`list` 分支：真实证据是零，而且"照抄 codex.py"这句不准确

任务书 `:72` 我自己写过一句：

> 我**没有**实测过这两种形状各自出现的频率，`codex.py` 里两条分支都写了但可能有一条从没走到过。

**现在这句话有答案了，答案是最没意思的那个：**

| 来源 | `str` | `list` |
|---|---|---|
| 实现方 2 次真实调用 | 2 | **0** |
| 我 3 次真实调用（交叉验证全过，说明走的是能取到正文的分支） | 3 | **0** |
| 全仓测试树里喂过 list 形状的文件 | — | **只有 T009 这次新加的那个单测** |

最后一行是我 `grep -rln '"text":\s*\['` 查出来的：**整个仓库里，唯一一处构造 list 形状 `text` 的地方，就是读它的那段代码自己的单测。** `app/harness/codex.py` 的 list 分支同样没有任何真实形状的留档。

这正是本会话一直在编目的那个形状——**一条分支的全部证据，来自读它的那段代码**。但**这次不判它是缺陷**，理由要说清楚，否则规则会被滥用：

1. 形状知识**取自生产者侧的读取器**（`codex.py`），不是从消费者的期望编出来的。这与 P1a 那次"桩照着消费者期望写"是两回事。
2. 分支有 `isinstance(value, list)` 把门，**不可能误触发**；`str` 形状永远走不到它。
3. 成本是 6 行。删掉它换来的是"哪天真来了 list 就静默拼出垃圾字符串"。

**但有一处措辞要改。** `_agent_message_text` 的 docstring 写着 "Mirrors the read logic in app/harness/codex.py:301-315"——**不准确**。核对 `codex.py:296-318`，它对 list 的处理是**遍历元素、返回第一个能解析成 JSON 对象的**（它在找 JSON）；而 `_agent_message_text` 是**把所有元素依次拼接**（它在还原正文）。多元素 list 一来，两者行为不同。

**两边各自都是对的**——找 JSON 就该取第一个命中的，还原正文就该按序拼全——**但"照抄"这个说法把一个自主决定说成了继承**，会让下一个读代码的人以为这个拼接规则有 `codex.py` 背书。

**已由我在合入时直接改掉 docstring**（见第七节），并把"list 形状 5 次真实运行 0 次"这个分母写进代码里——分母写在注释里会烂，写在它描述的那段代码旁边才不会。

---

## 六、新发现的一处小隐患（不阻断，记账）

`_collect_agent_messages` 里：

```python
item = event.get("item") or {}
if event.get("type") == "item/completed" and item.get("type") == "agentMessage":
```

`event["item"]` 如果是个**非空 list**，`or {}` 保留 list，`.get` 直接 `AttributeError`。

平时无所谓，**但它现在坐在无条件路径上**：T009 之前，payload 构造是纯 dict/list 推导，不可能抛；现在多了一次 `.get` 调用。真抛了，**三条返回路径一条都写不出来，整个脚本直接崩**——恰好毁掉 T009 建立的那个性质。

严重度低（`result.events` 的元素在真实数据里一直是 dict，`codex.py:163-164` 是同样的写法），**不阻断合入**。记在这里，谁下次动这个文件谁顺手加个 `isinstance(item, dict)`。

---

## 七、合入时我自己改的（透明记录）

只改了 `_agent_message_text` 的 docstring，**一行可执行代码没动**：把"Mirrors ... codex.py:301-315"改成如实描述——形状知识取自 `codex.py`、拼接规则是本函数自主决定且与 `codex.py` 不同，并写上"list 形状在 5 次真实运行里出现 0 次，此分支是防御性的、未被证明"。

依据：`scripts/codex_semantic_smoke.py` 此刻已无其他实现方占用（T009 收口、P2 第 2 项尚未派发），合入时改安全。

---

## 八、遗留与后续

| # | 遗留 | 处置 |
|---|---|---|
| 1 | 多元素 list 拼接：真实数据 0 次覆盖 | **接受**，理由见第五节。分母已写进 docstring |
| 2 | `_collect_agent_messages` 对非 dict `item` 会抛 | 记账，下次动此文件时顺手加 `isinstance` 守卫 |
| 3 | 6 条 `item/completed` 里另 5 条是什么 `item.type`，payload 里看不出来 | **不开任务。** `eventSummaries` 只记事件的 `keys`、不记 `item.type`，我自己复核时也确认从产物反推不出来。真需要时并入下一个动此脚本的任务 |

**不新开任务。** 三条都是小口径观测项，单开一个任务的协议开销大过收益。

**T009 本身闭环。** T008 REVIEW 第六节留下的那个问题——"payload 里没有拼好的那份正文"——现在有了，且经 4 次真实运行逐字节验证。

---

## 九、对 P0 的影响：零

说清楚免得下次误读：T009 是**观测能力**，不改变任何判定逻辑。P0 第一条验收条的可靠性分母仍是 T008 复核时的 **19/20，Wilson 95% CI [76.4%, 99.1%]**。

我这 3 次是拿来验交叉验证的，**不计入那个分母**——它们跑的是同一个场景、同一份代码，但目的不同，混进去等于事后挑样本。真要更新分母，应该按 `README.md` 第六节新的"带分母"要求重新设计一轮，而不是把零散跑的次数攒起来。
