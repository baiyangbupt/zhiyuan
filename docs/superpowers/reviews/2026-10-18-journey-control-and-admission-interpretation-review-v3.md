# 用户旅程、对话控制与录取解读设计（v3）独立审查

对象：

- `docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`（v3）
- `docs/superpowers/plans/2026-10-18-journey-control-and-admission-interpretation.md`（v3）

基线：`616464c`（`wip/2026-09-28-p2-write-loop-green`，工作区含 add_units EXPAND 未提交改动）
日期：2026-10-18
方式：只读审查（未改设计稿/代码、未跑测试、未部署）

## 一、结论

**BLOCK。**

v3 对 N1/N3/N5/N6/N7 的修订是实质性且可落地的；N4 的主链路（有界事件 payload）
也可行。但仍有两个设计级 blocker 和一个计划级 blocker：

1. **§8.3 的 `slip_risk` 规则与真值表仍然互相矛盾**（N2 未真正解决）；
2. **J2b 的 `sourceLevel=computed` 证据在现有 `EvidenceLedgerService` 上签不出来**
   （硬编码 `authoritative`、请求/实体/表都没有 `sourceLevel`），且 Java 响应载体
   没有定义如何把证据带出；
3. **计划 J2a-T2 的算法描述与 §8.3 不一致**（`base=第一条非冲`、`slip` 漏
   `无法判断`、只测 9 行、`pathTier(schoolRatio)` 与“tier 为准”冲突），照计划实现
   会产出与规格不同的结果。

这三项都不是“实现时再定”的细节：J2a 的验收不可达（1/3），J2b 的证据验收不可达
（2），而 J2a 的实现文本会直接误导执行侧（3）。建议先完成“设计/计划修订”阶段
（纯文档），再进入 J2a。

## 二、N1–N7 状态

| # | 状态 | 一句话结论 |
|---|---|---|
| N1 | **resolved（有 2 个 major 衔接缺口）** | 三处 agent 投影/注入点已列全；但 `StatePatch` 白名单未同步、注入预算漏了 `plan_version` |
| N2 | **not resolved（blocker）** | 规则 3“所有保 ratio 缺失→高”与真值表行 6/7/10 的“中”直接冲突 |
| N3 | resolved | `system.action`/自动生成/“最可能”已只出现在否定句、反例或用户原话里 |
| N4 | **partially resolved** | §9.2 的有界 payload 路径可行；但 §12.3 与计划仍写“明细走 artifact”，§8.6/计划 J2c 的卡片字段与 payload 不一致 |
| N5 | resolved | `planning.interpret_admission` 通过 `test_domain_mcp_tools.py:45-46` 的 `plan.` 前缀断言 |
| N6 | resolved（1 个 minor） | `TOOL_INPUT_SCHEMAS`/`TOOL_KINDS`/`TOOL_OUTPUT_SCHEMA.kind`/`server.py`/`tool_listing()` 测试都在计划里；漏了 `TOOL_LABELS`/`TOOL_CONTRACTS` |
| N7 | resolved（措辞上仍有 1 处可收紧） | J4a 前“仅本次”已在 §5.1b/§6.2/§6.3/§10.4/§13.8/计划 J1b 落定；§6.2 的“目标口径默认持久”已被同一句的“J4a 落地前一律仅本次”限定 |

### N1（resolved，但有两个 major 缺口）

已核对：

- spec §4.4（spec:322-338）与 plan J1a-T1（plan:148-166）都列了
  `contracts.py::ConversationTurnSnapshot`、`snapshot.py::build_snapshot/diff_snapshots`、
  `service.py` 注入三处；对照代码，这正是 journey 块到模型的必经路径：
  `_snapshot_payload` → `build_snapshot`（`snapshot.py:42-172`）→
  `snapshot.model_dump(by_alias=True)`（`service.py:2483-2484`）。
- `diff_snapshots` 的 `allowed`（`snapshot.py:181-193`）确实需要增加 `journey`
  （或按 spec 的“或每轮全量注入”走第二条路）。

缺口（major，不阻塞到“模型看不到”，但会让计划里的 patch 路径静默失效）：

1. **`StatePatch` 还有第二份白名单。** `contracts.py:557-574`
   `StatePatch._validate_change_paths` 的 `allowed` 同样不含 `journey`。只改
   `snapshot.py::diff_snapshots` 的话，`StatePatch(...)` 会抛
   `unsupported state path: journey`；`service.py:2284-2287` 会 `except ValueError:
   state_patch = None`，于是每轮退化成全量快照。功能上仍能看到 journey，但计划写的
   “进 diff_snapshots”并没有真正生效。计划 J1a-T1 必须同时列
   `contracts.py::StatePatch`，或明确选择“journey 每轮全量注入、不进 patch”。
2. **注入预算漏了 `plan_version`。** spec:333-334 写“只注入
   phase/available/blocked/recommended_next”，但 `JourneyContext` 的 `plan_version`
   （spec:310）是 `planning.interpret_admission` 的**必填**参数（spec:916）。模型
   能看到 `snapshotVersion`（同值），但工具参数叫 `planVersion`；若提示词/技能不
   显式教它“用 snapshotVersion 填 planVersion”，工具调用会缺必填参数。建议把
   `plan_version` 加进注入预算，或在 skill 里写死映射。

### N2（not resolved，blocker）

§8.3 规则 4（spec:769-776）按顺序命中：

```
1. 所有条目 unknown            → 无法判断
2. 没有任何保                  → 高
3. 所有保的校线 ratio 都缺失    → 高
4. 恰好 1 条保，或最后一条保缺失，
   或 >=2 条保中任意一条缺失    → 中
5. >=2 条保且全部 ratio 已知   → 低
6. 其余                        → 无法判断
```

真值表（spec:800-814）与规则 3 冲突：

| 行 | 输入 | 规则 3 | 表里的 slip_risk | 结论 |
|---|---|---|---|---|
| 6 | 冲, 稳, 保（最后保 ratio 缺失） | 只有 1 条保，其 ratio 缺失 → **高** | **中** | 冲突 |
| 7 | 冲, 稳, 保（全部 ratio 缺失） | 所有保（1 条）ratio 缺失 → **高** | **中** | 冲突 |
| 10 | major 模式 entry join 不到 ratio | 若保的 ratio 全缺失 → **高** | **中** | 冲突/未定义 |

行 12“恰好 1 条保、ratio 已知 → 中”与规则 4 一致；行 6/7 是同一形态但 ratio 缺失，
规则 3 先命中。J2a 的“逐行全绿”按当前文本不可能同时满足。

最小修复二选一：

- 规则 3 加限定“且 `>=2` 条保”；即单保缺失落到规则 4 的“恰好 1 条保 → 中”；
- 或把行 6/7/10 的 `slip_risk` 改为 `高`，并补行 10 的保数量/已知比例前提。

同时把 §11/§12.2、plan J2a-T2/验收里的“9 行”改为 13 行（表实际有 13 行）；否则
行 11–13（混合缺失、单保已知、双保已知）不会被测试，恰好是 N2 要锁死的边界。

### N3（resolved）

逐项 grep 复核：

- `system.action` 只出现在“不新增/不允许/如果没有”的否定句、§9.2/§10.1 的纠偏
  段落和 §10.4 的“没有 system.action”里；
- “最可能”只出现在 §8.1 的用户原话（spec:685）、§8.3.10 的禁用规则
  （spec:796-797）、§10.2 的禁用句（spec:1025）、§12.2 的断言（spec:1149）；
- “自动生成/自动重排/自动审查”只出现在“当前没有生产者”“undo 前不做自动改方案”
  这类限定句里；§10.5 的自动动作表也明确“不静默重排/不自动生成”。

### N4（partially resolved）

**可行的部分：**

- `ui_events.py:18-37` 的 `EVENT_TYPES`、`event_store.py:171-179` 的类型/16KB
  校验、`conversationSession.mjs` 的 reducer、`conversationEvents.mjs` 的
  `V1_PAYLOAD_WHITELIST`、`MessageList/index.tsx` 的渲染分支、`server.py:1561`
  的 `_LEGACY_FRAME_TYPE` 都是真实存在的改动点；plan J2c-T1 已列全。
- 4 条场景、每条只带
  `{label,likelihoodBand,landingEntry{schoolName,majorName,position},caveatCount}`
  的 payload 远小于 16KB，事件合同可行。
- artifact store 只存身份摘要也核对属实（`artifact_store.py:140-190`）；§9.2
  明确“不按 artifactRef 取数”是正确的。

**未解决/仍矛盾的部分：**

1. **规范文本仍在要求“明细走 artifact”。**
   - spec:1158（§12.3）：“解读卡事件只带摘要，**完整内容在 artifact**”；
   - plan:14（Architecture）：“解读卡走‘工具结果 → artifact → 摘要事件’”；
   - plan:268（验收口径）：“J2c 卡片只发摘要，**明细走 artifact**”；
   - plan:204（Phase J2c 标题）：“事件/artifact/reducer”。
   这与 §9.2 的“artifact 只存身份摘要、不要声称按 ref 取明细”直接冲突。按
   plan:268 验收会要求一个不存在的取数链路。必须删除/改写这些句子。
2. **卡片字段与 payload 字段不一致。**
   - §8.6（spec:875-876）要求卡片展示“4 条场景路径、基准落点、滑档风险、
     证据缺口”；
   - §9.2 的 payload 没有 `path`，只有 `landingEntry`；没有 caveat 文本，只有
     `caveatCount`；
   - plan J2c（plan:224）又写“卡片展示……证据缺口、caveat”。
   卡片无法展示不存在的字段。要么把卡片要求改成“场景摘要 + 落点 + 缺口数量”，
   要么把有界的 `caveats`（如前 3 条）放进 payload。
3. **截断规则不自洽。** §9.2.3 写“超限时只保留 base/downside/slip + 前 3 条
   caveat”，但 payload 只有 `caveatCount`，没有 caveat 数组。需统一。
4. **事件发射时机未定义。** plan 说在 `service.py` “拦截工具结果→有界摘要事件”。
   若在原生 tool notification 到达时就 emit，而整轮随后被修复/判废
   （`service.py` 的 `_validate_round`/`_settle_evidence` 路径），卡片会留在
   一个失败/被替换的回合里。与 `proposal.preview` 的处理方式对齐（先进入已验证的
   turn result，再由 `server.py::_emit_turn_terminal` 发），或在设计里明确“只读卡
   允许先发、失败不回滚”的取舍。

### N5（resolved）

`planning.interpret_admission` 与现有 `planning.get_working_plan` 同族，
`test_domain_mcp_tools.py:45-46` 的断言是
`not any(name.endswith("apply") or name.startswith("plan."))`，新名通过。
`CAPABILITIES` 里 `planning.get_working_plan` 已挂 `admission_read`
（`tools_readonly.py:31-34`），新工具沿用同一能力是正确归属。

### N6（resolved，1 个 minor）

已核对 `tool_listing()`（`server.py:442-453`）会对
`READONLY_TOOL_NAMES` 的每个名字取 `TOOL_INPUT_SCHEMAS[name]`，缺条目即
`KeyError`。plan J2b-T2 已明确列 `server.py` 与 `tool_listing()` 测试，正确。
`TOOL_KINDS` 实际在 `tools_readonly.py:99-135`，不在 `server.py`；计划把位置
写混了，但文件列表同时包含 `tools_readonly.py`，执行侧能找到。

仍漏两个注册点（minor）：

- `ui_events.py:41-78` 的 `TOOL_LABELS` 没有新工具：`adapt_notification`
  会把 `known=False`，进度条显示“正在处理查询”、tool token 变成 `domain`；
- `engine/tool_orchestration.py:184-209` 的 `TOOL_CONTRACTS` 没有新工具，
  `render_tool_contracts()` 的编排约束不会提到它（MCP 工具清单仍能看到，故非阻塞）。

### N7（resolved）

- 正确侧：§5.1b（spec:399）、§6.2（spec:514，已带“J4a 前一律仅本次”）、
  §6.3（spec:532）、§10.4（spec:1051，已改“本次生效；J4a 落地后才默认持久”）、
  §13.8（spec:1188）、plan J1b（plan:190）。
- 错误的旧口径已清：§6.2/§6.3/§10.4 的“默认持久/后续生效/以后都生效”都已加上
  J4a 限定或移到 J4a 之后；plan J4a 的“卡片写本次/以后都生效”属于 J4a 任务本身。
- 唯一可再收紧的是 §6.2 的“目标口径默认持久”这半句；建议改为“产品目标是默认
  持久；**J4a 落地前**一律仅本次”，避免被单独摘出来当规范。

## 三、新增 blocker

### NB1. J2b 的 `sourceLevel=computed` 证据签不出来，响应载体也未定义

**证据**

- spec §8.2（spec:737-743）要求：J2b 必须由 Java `EvidenceLedgerService` 签发
  `sourceSystem=planning.interpret_admission`、`scope=session`、
  `sourceLevel=computed` 的计算证据；plan J2b-T1（plan:99-102）照写。
- 实际 `EvidenceLedgerService.sign`（`EvidenceLedgerService.java:76-127`）只接受
  `sourceSystem/dataVersion/params/scope/...`，**没有 `sourceLevel` 入参**；
  `toEvidenceDTO`（`:274-277`）硬编码
  `evidence.setSourceLevel(SOURCE_LEVEL_AUTHORITATIVE)`，且
  `EvidenceLedgerEntity`/`V14__evidence_ledger.sql` 没有 `source_level` 列。
  也就是说，按当前链路签出来的证据一定是 `authoritative`，与“computed 推演”的
  语义相反，模型会把它当成上游取数。
- plan J2b-T1 的 Files 只有 `PlanningStateController`、`PlanningStateService`、
  测试；**没有** `EvidenceLedgerService.java`、`EvidenceSignRequest.java`、
  `ConversationEvidenceDTO.java`、实体/迁移。按计划实施，`sourceLevel=computed`
  无处落地。
- 另有一个响应载体问题：`PlanningStateController` 现有风格返回
  `BaseResponse<T>`（`BaseResponse.java` 只有 `data/code/msg`，**没有 evidence**）；
  而 agent 的 `InternalClientBackend._preserve_envelope`
  （`tools_readonly.py:893-920`）只认**顶层** `evidence`，`_envelope` 才把它放进
  `evidenceRefs`。若新接口把证据放在 `data` 里，`evidenceRefs` 会是空数组。
- 若选择“没有签发能力就不伪造”，返回的 `evidenceRefs` 必须为空并在 caveats
  说明；但 §11/§12.2 的验收又写“Java 计算证据已签发”。两条不能同时成立。

**为什么阻塞**

J2b 的核心验收之一就是“解读服务自己带回 `reviewState`/计算证据，模型只叙述”。
在现有台账上只有两条路：改成 `authoritative`（语义错误）或返回空证据（达不到
验收）。都不满足设计。

**最小修复**

1. 明确扩展台账：`EvidenceSignRequest` 增加 `sourceLevel`（`authoritative`/
   `computed`），`EvidenceLedgerEntity` + 迁移增加 `source_level`（或明确按
   `source_system` 前缀映射到 `computed`，并写清理由）；`toEvidenceDTO` 按入库值
   输出，不再硬编码 `authoritative`。
2. 把 `EvidenceLedgerService`/`EvidenceSignRequest`/实体/迁移/`toEvidenceDTO`
   写进 plan J2b-T1 的 Files。
3. 定义响应载体：返回 `ResponseDTO<AdmissionInterpretationRes>`（带顶层
   `evidence`），或给新接口一个带 `evidence` 字段的响应 DTO；agent 的 handler 用
   `_preserve_envelope`/显式 lift，确保 `evidenceRefs` 非空。
4. 若本批决定不签，就把 §8.2 的“必须签发”和 §11/§12.2 的验收改成“只返回
   caveats、无 evidenceRefs”，并删掉 `sourceLevel=computed` 的承诺。

### NB2. §8.3 的 `slip_risk` 规则 3 与真值表行 6/7/10 冲突（N2 未解决）

见 §二 N2。证据：spec:769-776 规则 3 vs spec:807/808/811；plan J2a-T2
（plan:72-76）要求“严格按 spec §8.3”，但同一份计划又只列 9 行、把 `base` 写成
“第一条非冲”、把 `slip` 写成“只在 slip_risk 中/高时输出”。按计划写代码会在行
6/7/10 和行 8 上给出与表不同的结果。

**最小修复**：规则 3 加“且 `>=2` 条保”，或把行 6/7/10 改为 `高`；统一
规则/表/计划三处；把“9 行”改为 13 行。

### NB3. 计划 J2a-T2/T1 的算法文本与 §8.3 不一致，照做会实现出另一套算法

**证据**

- plan:75：“`base=第一条非冲`”。spec:753 明确“`unknown` 一律跳过，不参与落点”，
  `base` 只可能是 `稳/保`。`unknown` 也是“非冲”；照计划实现会把 `unknown` 当
  base（或至少语义不明），行 8/10 会错。
- plan:76：“`slip` 只在 `slip_risk` 中/高时输出”。spec:760-761 写“`中/高/无法判断`
  时输出”。行 8（slip_risk=无法判断）会漏掉 slip 场景。
- plan:75：“`upside=冲里校线 ratio 最高`”，漏了 spec:756-759 的“全都没有 ratio
  时取最早的冲/部分缺失时取已知最高”。
- plan:57-59（J2a-T1）：`pathTier(schoolRatio)` 的 null/越界 → unknown，且把
  `pathTier` 说成由 ratio 派生；spec §8.2 明确方案条目的 `pathTier` 以
  `OrderedItemDTO.tier` 为准，ratio 只用于确认和 band。行 10（tier 已知、join
  不到 ratio）按计划的 `pathTier` 可能变成 unknown，base/downside 直接消失。
- plan:72 与 plan:264 的“9 行”与 spec 的 13 行表不一致；plan 测试清单只覆盖
  行 1–9（外加 major join 缺失），漏行 11–13。
- plan J2a-T2/§12.2 都没有 **unit 模式** fixture；spec §11/§12.2 验收要求
  unit/major 各一组。反事实 remove 的“删除最后一条保底 → slip_risk 上升”也没有
  在计划测试清单里。

**为什么阻塞**

J2a 是纯函数切片，测试就是它的规格。计划和规格不一致时，执行侧只能二选一；
无论选哪边，验收的另一边都会挂。这是“实现失败/用户可见输出错误”的直接来源。

**最小修复**

把 plan J2a-T1/T2 的 Interfaces/checkbox 改成：

- `pathTier` 对方案条目读 `OrderedItemDTO.tier`；`schoolRatio` 只计算 band/slip
  与 `ratioCoverage`；ratio 缺失不改变已给出的 tier；
- `base` = 按 position 的第一条 `稳/保`（跳过 `unknown`）；
- `upside` = `冲` 中已知校线 ratio 最高（同率取前）；全部缺失取最早冲；
- `slip` 在 `中/高/无法判断` 时都输出；
- 13 行真值表逐行测试；unit/major 各一组；remove 反事实补“删最后一条保”测试。

## 四、B1–B9 抽查

| # | 状态 | 抽查结论 |
|---|---|---|
| B1 | resolved | `pathTier`/`majorAdmissionRatio` 已拆分；join/unknown/粒度都写清。残留：spec:700 仍引用 `VolunteerIntervalService.java:96-102`（v2 审查指出生产是九区间 + `VolunteerSorterAndMerger`），边界结论不变，属引用陈旧 |
| B2 | resolved | Java `journey` 块 + 两层派生已定义，`hasProfile`/`hasCandidates`/`hasPlan`/`stale` 都有定义；N1 的三处 agent 投影已列。major：StatePatch 白名单、plan_version 注入 |
| B3 | **partially** | 顺序扫描、remove-only、粒度、历史不参与 band 都已写；但 N2 规则/表冲突未解 |
| B4 | resolved | J4a 前置 + “仅本次”口径已在 §5.1b/§13.8 落定；N7 的旧口径已清 |
| B5 | resolved | §5.1（spec:374）已改回 `only_keep_scope/exclude_scope/requirements(include)/priority_rules`，无 `prefer`；§5.3（spec:437-441）已加“J6 未落地前只给建议”；§5.1b 载体/状态/失败行为齐全 |
| B6 | resolved | 结论段、§9.2、§10.1、§10.4 都不再新增 `system.action`；J3 只扩 `conversationAction.result` |
| B7 | resolved | supersede、`pending_applying` 409、派生状态与 `prepareOnce` 行为一致；§4.4 新增 `pendingStatus` 解决“applying 无来源”。minor：`getCurrent` 返回任意状态行，journey 侧应只取 active/applying |
| B8 | **partially** | 有界事件合同可行；但 N4 的 artifact 旧措辞/卡片字段仍不一致 |
| B9 | resolved | `review_read` no-op 修法已删；`plan-final-review` 保持人工审查、不签 review artifact；§4.4 的 `review_plan` 已改为“人工审查（无专用工具）” |

## 五、Majors（不阻塞到“无法开工”，但必须在对应切片前定）

1. **`StatePatch` 白名单未同步**（contracts.py:557-574）。只改
   `snapshot.py::diff_snapshots` 会导致 `state_patch` 被 `except ValueError` 吞掉，
   每轮全量快照。计划 J1a-T1 二选一：补白名单，或明确全量注入。
2. **`plan_version` 不在注入预算**（spec:333-334 vs spec:916/plan J2b-T2）。
   `planning.interpret_admission` 必填 `planVersion`；模型只有 `snapshotVersion`。
   把 `plan_version` 加进注入，或在 skill 里写死“planVersion = 快照 snapshotVersion”。
3. **解读卡事件发射时机**（plan J2c）。若在 tool notification 时直接 emit，
   整轮后续被判废/修复时卡片会留在无效回合。建议像 `proposal.preview` 一样，
   先放进已验证的 turn result，再由 `server.py::_emit_turn_terminal` 发；或在
   设计里明确“只读卡允许先发、失败不回滚”。
4. **`available_actions` 校验口径仍分裂**。§5.5（spec:468-470）说“动作不在
   `available_actions` 就阻断”，§9.3（spec:982-985）/plan J1c 说“只做硬不变量”。
   前者会把 `interpret`/`verify`/`review` 这类 post-model 意图挡掉（`available_actions`
   里 `interpret_admission` 还标着 planned）。必须二选一：要么 `available_actions`
   只做提示、不做白名单；要么把只读动作全集放进 available，并随 J2b 把
   `interpret_admission` 改成已实现。
5. **`blocked_actions` 的 “stale working plan item” 没有数据来源**。
   `UserGoalProposalBuilder.java:263-275` 需要把当前方案 volunteerId 与有效候选池
   求差；journey 块（spec:322-327）只有 `staleFlags`/`hasPlan`/counts，没有池成员
   关系。要么在 journey 块加一个 `stalePlanItemCount`（Java 计算），要么把该阻断
   降级为“agent 层只能提示、不保证列出”。
6. **`JourneyAction` 不存在**。plan J1b-T1（plan:186-188）要求“动作在
   `JourneyAction` 里”，但全仓没有该枚举，J1a-T2 也没有创建任务。把枚举定义写进
   `app/gateway/journey.py`（或 fixture schema），并让契约校验器引用它。
7. **`$ref` 解析器不存在/未复核**。spec:936-938 与 plan:32/90 说“实测
   planningState 里 workingPlanState 可能只是 `{"$ref": ...}`，必须用既有状态
   解析器”；但 Java 侧没有任何 `$ref`/reference 处理（全仓 grep 只有 agent 的
   JSON Schema `$ref`），`loadPlanningStateReadOnly` 走 Fastjson 反序列化。若真实
   库确实有 `$ref`，J2b 需要先补解析器；否则应删掉这句，避免执行侧找一个不存在
   的入口。
8. **MCP 5s backend timeout 与 4–29MB 冷加载**。`ReadonlyDomainTools.call`
   （tools_readonly.py:350,453-457）默认 `backend_timeout=5.0`，超时会**整段重试
   一次**。解释服务首次冷缓存需要读/解析候选池；若超过 5s，用户看到
   `backend_unavailable`，且重试重复同一冷读。计划没有任何预热/超时配置项。建议
   给该工具单独的超时（或先 warm 索引），并在 J2b-T1 的缓存任务里明确“缓存的是
   解析后的池/索引，不只是 volunteerId 映射”。
9. **J3 的 `origin/actionType/scope/receipt` 没有生产者**。
   `ConversationActionResult`（conversation_actions.py:60-78）只有
   action_status/proposal_ref/new_state_version/actual_changes/review_state/code/
   message；plan J3 只说“扩展 `_action_result_payload`”，没说这些值从 pending
   的 kind/actionFamily、actualChanges 还是 Java 新字段来。J3 开工前要定来源。
10. **J4a 学费双源**。`ChatSessionBizService.updateTuitionRange` 写
    `userScoreDetail`（v2 M10），plan J4a 又要 `applyUserGoalTargetToPlanningState`
    持久化 `tuitionRange`；唯一事实源/回读/迁移规则仍未写。J4a 前必须定。
11. **`hasPlan`/`stale`/`hasProfile` 的判定精度**。
    - `StaleFlagsDTO` 永远非 null（`StaleFlagsDTO.java`），spec:196 的
      “`staleFlags` 非空”必须写死为“任一布尔 true（或 reasonCode/message 非空）”，
      否则 `stale` 恒 true；
    - `hasPlan` 应同时看 items 与 units（现有
      `currentOrderedOrDraftUnitCount`，PlanningStateService.java:11685-11687），
      只数 items 在 unit-only working plan 上会误判 false；
    - `hasProfile` 的“科类”不在 `StudentPlanningSummaryDTO`（只有 subjects/
      strengthSubjects），需要明确用 `loadScoreDetail` 的 subjectType 还是放宽为
      “省份+年份+批次+成绩/位次”。
12. **`path` 未定义/未限长**。`LandingScenario.path`（spec:836）没有“包含到落点
    为止还是整份方案”的定义；45 条 × 4 场景的完整 EntryRef 可能几十 KB。事件
    payload 有界，但工具结果/模型上下文没有。建议 `path` 只保留到 landing entry，
    完整方案留在 `query_plan`。
13. **`pendingStatus` 终态过滤**。`PendingConfirmationSharedService.getCurrent`
    （:14-20）返回任意状态（包括 applied/cancelled），journey 块应只输出
    active/applying，否则 agent 会把已结束的 pending 当“待确认”。
14. **计划头部版本引用过期**。plan:19 写 `Spec: ...（v2）`、plan:20 只引用 v1
    review；应指向 v3 与 v1+v2 两份 review。

## 六、Minors

1. `TOOL_LABELS`（ui_events.py:41-78）与 `TOOL_CONTRACTS`
   （engine/tool_orchestration.py:184-209）未列；前者影响进度文案，后者影响编排
   约束提示。
2. spec:700 引用未生产调用的 `VolunteerIntervalService.java:96-102`；生产是九区间
   `:61-79` + `VolunteerSorterAndMerger.java:59,161-175`。改引用即可。
3. spec:226-227 有整段重复的“最终 `journeyPhase = taskIntent ?? statePhase`”，
   删一段。
4. `LandingScenario.scenario_id`/`generated_at`、`path` 的生成规则未定义。
5. `removeEntryRefs` 删除全部条目/重复 id/不存在 id 的返回未定义。
6. `interpretation.preview` 与 `assistant.completed`/`turn.completed` 的相对顺序
   未写；前端 reducer 终态守卫需要明确“卡在终态前”。
7. `dataCoverageBand` 的分档（完整/有缺口）没有写死阈值；`min(tierCoverage,
   ratioCoverage)` 是内部值，面向用户转述时不要露小数。
8. `TOOL_KINDS` 在计划里被写成 `server.py` 的改动，实际在
   `tools_readonly.py:99-135`；文件列表虽包含，建议写准。
9. `test_domain_mcp_tools.py` 的 `plan.` 前缀断言之外，新增工具后还要确认
   `test_server_registers_exactly_the_readonly_tools`/`test_production_stdio_loop`
   不会因排序/数量断言失败（计划已提，但未列具体断言）。
10. `planning.interpret_admission` 的 5s 超时/重试在 plan J2b-T2 的测试清单里没有
    覆盖（可用 fake backend 模拟慢响应）。

## 七、计划与规格对齐

已对齐：

- 切片顺序：J2a/J2b（文本）→ J1a/J1b/J1c → J2c → J4a → J4b；J3 只扩回执；J5/J6
  另立路线图（spec:1123-1124，plan:7-9）；
- J2b 工具名/参数/身份纪律：`planning.interpret_admission`、不收
  chatSessionId/tenantId/sessionId/userId、`_trusted_arguments` 丢弃身份字段；
- J2c 文件清单与 N4 的六个改动点；
- J1c 硬不变量：一轮一个写、pending 才能 confirm、applying 拒绝、版本守卫、
  已知阻断；
- J4a/J4b 拆分。

未对齐/需补：

- J2a 的“9 行/第一条非冲/slip 漏无法判断/pathTier 由 ratio”与 spec §8.3 冲突
  （NB2/NB3）；
- J2a 缺 unit 模式 fixture 与 remove 反事实测试（spec §11/§12.2）；
- J2b 缺 `EvidenceLedgerService` 等证据文件（NB1）；
- J2c 的 phase 标题/架构/验收仍写 artifact 明细（N4）；
- J1a 缺 `contracts.py::StatePatch` 白名单与 `plan_version` 注入；
- J1b 缺 `JourneyAction` 定义；
- J3 缺 `origin/actionType/scope` 来源。

## 八、建议的实施顺序

**阶段 0：设计/计划修订（不改代码）**

1. 修 NB2/NB3：统一 §8.3 规则 3 与 13 行真值表；把 plan J2a-T1/T2 的
   `pathTier`/`base`/`upside`/`slip`/测试清单改成与 spec 一致。
2. 修 NB1：决定 `sourceLevel=computed` 的落法（扩展台账 + 迁移/映射 + 响应载体），
   并把文件写进 J2b-T1；若本批不签，就同步改 §8.2/§11/§12.2 的验收。
3. 修 N4：删除 spec:1158、plan:14/204/268 的“artifact 明细”；统一卡片字段与
   payload（caveat 文本或 caveatCount），定义事件发射时机。
4. 修 N1 的两个 major：`StatePatch` 白名单或全量注入；`plan_version` 注入。
5. 修 major 5/6/8/9/10（blocked_actions 数据源、JourneyAction、5s 超时、J3 来源、
   J4a 双源）——这些可以在对应切片前完成，不阻塞 J2a。

**阶段 1：J2a（纯函数 + 13 行真值表）**

- 先写失败 fixture：13 行 + unit/major 各一组 + remove 反事实（删最后保）；
- `pathTier` 以 `OrderedItemDTO.tier` 为准；ratio 只算 band/slip/coverage；
- 不接 Spring/DB，`mvn -Dtest=PlanAdmissionInterpretationServiceTest test`。

**阶段 2：J2b（Java inner + MCP，先文本）**

- 证据台账扩展 + 响应载体 + 进程内缓存（缓存解析后的池/索引，不只是映射）；
- `planning.interpret_admission` 注册全（schema/description/kind/label/contracts）；
- 版本/stale/no_plan/join 缺失/remove-only 反事实；真栈文本先通。

**阶段 3：J1a/J1b/J1c**

- journey 块 + agent 投影/注入（含 `StatePatch`、plan_version）；
- 触发目录 + 契约校验器（先定义 `JourneyAction`）；
- 硬不变量校验（不要用 post-model 的 available_actions 做严格白名单）。

**阶段 4：J2c**

- 有界事件合同 + reducer/MessageList/legacy 映射；只发摘要；16KB 内；
- 事件在已验证 turn result 之后发（或明确只读卡不回滚）。

**阶段 5：J4a → J4b**（先在 J4a 前解决学费双源）

## 九、审查边界

- 只读代码与文档；未运行测试、未调用模型、未部署。
- 未复核 4–29MB 候选池/1–4MB planningState 的实际解析耗时；5s 超时判断基于
  `ReadonlyDomainTools` 的默认值与冷加载路径，不是实测。
- 未验证真实库中 `workingPlanState`/`majorItems` 的 `$ref` 形态；只确认 Java
  侧没有可见的 `$ref` 解析器。
- 未验证 `planningState` 的 `loadScoreDetail` 是否总能给出 subjectType；
  `hasProfile` 的“科类”判定以 `StudentPlanningSummaryDTO` 的可见字段为准。
