# Release 4.0.0 Zhiyuan Agent v2.43/v2.44 Issue Log

日期：2026-07-11

本文件记录 fresh8042 原始问题、后续 focused 复核、代码修复和验证结论。

## 验证结果

- 默认 live gate：`/private/tmp/zhiyuan_400_v243_live_gate_fresh8042_clean`
  - `228` steps，`177` passed，`51` failed
  - 失败原因聚合：`content=50`、`tool=3`、`environment=1`、`performance=1`
- clone-backed final-action gate：`/private/tmp/zhiyuan_400_v243_final_action_gate_fresh8042`
  - `151` steps，`112` passed，`39` failed
  - 失败原因聚合：`environment=1`、`content=26`、`tool=20`、`backend=27`

## 已确认稳定通过区域

- direct confirm execution：`4/4`
- candidate view / 山东排除：`2/2`
- 院校属性 final-action：`8/8`
- 专业门类 final-action：`2/2`
- 标签 final-action：`4/4`
- 真实口语扩展 v156：`10/10`
- 取消/组合 v157：`11/11`
- dialogue-derived 默认质量集：`88/88`

## v2.43 基线 P0 最终动作缺口

以下是原始 gate 观察，是否仍成立以文末 v2.44 focused 结论为准。

- 地域集合、城市圈、偏远地区 pending 多数能生成，但确认失败或落库不完整。
  - 典型 case：v212/v213/v216。
  - 现象：确认轮回复“这类待确认内容还不能由新确认工具执行，请重新生成预览。”
  - 后端状态：`pendingConfirmation.status=failed`，`planningState.version` 不增长，`mustIncludeRegions` / `mustExcludeRegions` 未写入。
  - 说明：v211 南北 case 里有一部分是区域标签被展开为省份后的断言表达不一致，需要和 v212/v213/v216 的真实确认失败分开看。
- active pending 追加/改写可能丢掉早先诉求。
  - 典型对话：`山东别去了` 后接 `再把民办也算了吧，一起记上`。
  - 现象：第二张 pending 只保留“民办”，丢失“山东”。
  - 后果：确认后 `mustExcludeRegions=[]`，正式方案仍含山东。
- 位置型方案动作不能稳定定位专业组。
  - 典型话术：`第三个专业组先不要了，拿掉看看`、`把第三个专业组挪到最前面`。
  - 现象：回复定位不到第三个专业组，不生成 pending。
  - 风险：前端/用户口径是专业组，但工具定位层可能仍按 item/unit 混合口径工作。
- ReplacementSpec 替换链路仍有 pending/spec 缺口。
  - 典型话术：`青岛理工那个中外合作建筑太贵了，换个正常收费的，最好不是中外合作`。
  - 现象：有时能定位旧项但不能生成替换 pending；有时生成 pending 但 `replacement_spec` 不完整。
  - 后果：后续 `就这样换` / `执行` 没有 active pending 可确认，或最终后端断言失败。

## P1 语义与路由问题

- `我只想学临床医学，其他专业先不要` 出现错误歧义澄清到“经济学”，没有生成专业要求 pending。
- `财经类可以优先，但是护理和中西医结合不要` 仍把“财经”落成院校要求，而不是专业/职业方向诉求。
- 命名方案动作定位不足。
  - `把中国海洋大学004专业组的国际经济与贸易改到第3位` 未出移动预览。
  - `把华中农业大学的建筑类加进来` 未出新增预览。
- 真实短口语仍有路由/回复质量波动。
  - 典型话术：`有啥问题，咋弄`、`保底够不够啊`、`青城那个是不是放多了`。
  - 现象：有时没有进入预期 review/query，或回复信息密度不足。
- `方案里的民办不要了` 在不同 fixture 组中表现不一致。
  - v155 等同类路径可通过，但 realistic user 组仍出现失败，需要比较会话状态和 pending shape。

## P1 回复协议与质量问题

- 排序预览仍可能暴露内部字段。
  - 典型回复：`按school_level重新排序当前方案`、`按recommendation_score重新排序当前方案`。
  - 用户侧应表达为院校层次、推荐系数等可理解文案。
- 只读查询后用户说“确认”的 no-pending 回复仍不贴合语境。
  - 当前回复常为“这类待确认内容还不能由新确认工具执行，请重新生成预览”。
  - 更合理边界是说明上一轮只是查询/分析，没有待采纳或待执行内容。
- 职业方向只读审查回复有时没有回应用户原话重点。
  - 典型话术：体制内、读研、稳定就业承接情况。
  - 现象：回复只给通用审查风险，没有覆盖“体制内/读研/承接/短板”等用户关心点。
- 少量重复工具调用继续观察。
  - 例：`read_state` 多次、`preview_intent_change` 或 `preview_plan_action` 重复。
  - 当前按低优先级效率问题处理，除非造成 pending 丢失或后端错误。

## 验证资产或环境噪音

- thinkingText 断言较窄导致多条 open-quality failure，不直接等同业务失败。
- 一次 backend clone/clear environment timeout，未进入有效对话。
- v211 地域 case 可能存在断言表达与实现展开方式不一致：实现写入省份列表，断言期待“南方/北方”区域标签。
- 部分 content failure 是回复措辞没有命中断言词表，需和真实链路错误分开处理。

## 后续处理顺序建议

1. 先修 final-action 确认失败：地域集合/城市圈/偏远地区 pending 的确认执行契约。
2. 修 active pending append/replace 合并语义，确保追加民办不会丢山东这类早先诉求。
3. 对齐专业组位置口径，确认“第三个专业组”从预览到确认都操作同一个方案层级。
4. 补齐 ReplacementSpec 结构化替换链路，重点覆盖便宜、正常收费、非中外合作、审查承接替换。
5. 再处理 P1 语义路由和回复质量，不引入工具层中文字符串匹配。

## v2.43 第一阶段处理进展

已完成代码与验证资产加固，尚未以 fresh live/final-action 回归结果关闭业务问题：

- pending 读取统一为 latest-only。latest 空对象作为墓碑，不再回读 version 0 复活旧 pending。
- Service 只将通过结构校验的 active pending 投影到本轮运行时和 Sandbox；`confirm_pending` 不再把孤立 raw JSON 当作执行权限。
- `PendingConfirmation` 增加 `pending_id`；确认前校验运行时 pending 与 Sandbox snapshot 的 `pendingId`，不一致时返回 `pending_snapshot_mismatch`，不执行、不改写 pending。
- no-pending 确认回复已改为说明上一轮可能只是查询/分析，没有待采纳或待执行内容。
- Sandbox、前端 follow-up 兼容桥和 regression runner 同步删除 version 0 pending fallback，避免生产与测试使用两套读取语义。
- runner 查询 latest pending 清理失败时计为 environment failure，不再静默只清 version 0 后继续跑。
- v211/v212/v213/v216 地域 final-action 和 review/repair fixture 已使用独立目标 session；runner 与 hard-cut audit 禁止 source/target 同 session 的伪 clone。
- 新增 latest tombstone、latest lookup failure、异形 pending、pendingId mismatch、latest clone、同源 clone 防护测试。相关测试 `594 passed, 29 skipped`。

## v2.44 focused 复核与处理结果

修正无正式方案、错误模式字段、旧目标 session 高版本墓碑和不存在的方案项锚点后，以下 focused live 均使用 clone-backed 正式方案、真实 LLM、latest-only pending 读取和最终后端断言：

- v216 偏远地区 final-action：`2/2`，metrics `/private/tmp/zhiyuan_400_v243_v216_corrected_fixture.json`。
  - active pending、`pendingId`、确认执行、`status=applied`、planning version 增长、`mustExcludeRegions`、正式方案过滤及 ordered/review 刷新全部通过。
- v173 第三个专业组移除/移动：修复前有效 fixture 为 `2/4`；修复后 `4/4`，metrics `/private/tmp/zhiyuan_400_v243_v173_group_position_after_fix.json`。
  - 根因一是模型有时只传 `action=remove` 而漏 `targets`；根因二是预览展示了组内明细的扁平 position，而不是 unit ordinal。
  - 修复只复用已有 ordinal parser：当 remove/move 已明确且漏 targets 时，从本轮原话恢复源组序号；定位后的预览使用组序号。没有增加按中文业务名扫描的兜底。
- v179 append/no-pending/ReplacementSpec：`7/7`，metrics `/private/tmp/zhiyuan_400_v243_v179_corrected_fixture.json`。
  - “山东别去了”后追加“民办”保留两项要求，确认后地域、院校性质和正式方案均更新。
  - 只读审查后“执行”走 no-pending guard，planning version 不变、无副作用。
  - 青岛理工中外合作财务管理替换生成 `tuition_decrease + cooperative` ReplacementSpec，确认后替换为正常收费非合作候选并刷新方案。

原 P0 结论调整：

- 地域集合/偏远地区确认失败：在有效正式方案 fixture 上已通过，不再作为当前 P0。
- active pending 追加丢历史诉求：fresh 正式方案复核已通过；原失败由旧 target session 的高版本墓碑遮蔽 version 0 新 pending，且 runner 断言仍回退 version 0 共同造成。
- 第三个专业组位置动作：已修复并完成 remove/move 最终动作验证。
- ReplacementSpec：真实存在的旧项锚点上已闭环；原“青岛理工中外合作建筑”并不在所用正式方案中，不能作为有效成功用例。

仍存在的结构性问题：

1. pending 仍使用 `(session, key, planningVersion)` extra-data；回归 clone 把 planningState 写在 version 0 时，历史更高版本墓碑会让 latest API 看不到新 pending。runner 已删除断言 fallback，不再掩盖该问题，但生产级解决仍需要独立 pending revision/CAS 资源。
2. `apply intent + regenerate`、`replace remove + select + regenerate` 仍是 Agent 侧多步编排，尚无幂等后端原子命令；中间步骤失败时仍可能出现部分成功与最终状态表达不一致。
3. v212/v213 全量地域组合、v173/v179 其余 case 和 P1 语义/回复质量仍需进入下一轮 fresh gate，不能由本次 focused 子集外推为全部关闭。

单测结果：direct 工具 `182 passed, 29 skipped`，runner `93 passed`；完整 unit suite `1520 passed, 29 skipped, 1 failed`。唯一失败为 `test_missing_info_checklist_uses_context_and_lists_core_gaps` 的既有措辞差异：测试期待“家庭约束”，当前输出“家庭预算与可接受学费上限”，与本轮改动无关。

仍需继续处理：

1. 将 pending 从 `(session, key, planningVersion)` extra-data 升级为独立 revision/CAS 资源，保证单 active pending、latest 一致性和原子 replace。
2. 将 `apply intent + regenerate`、`replace remove + select + regenerate` 下沉为幂等后端命令，消除部分成功后仍标记整体 failed/applied 的状态歧义。
3. 用修正后的正式方案 fixture 跑 v212/v213、v173/v179 全文件，再重跑 clone-backed final-action gate，更新真实剩余失败聚合。
4. 最后处理命名专业组动作和 P1 模型语义/回复质量，不通过工具层中文业务字符串扫描兜底。

## v2.45 独立 pending 资源推进结果

v2.44 记录的第一个结构性问题已完成第一阶段实现，不再使用 `(session, key, planningVersion)` extra-data 作为新 pending 的主状态源。

已完成：

- 后端 Flyway V7 新增 `assistant_chat_session_pending_confirmation`。每个 `(tenant_id, chat_session_id)` 只有一条当前快照，独立 `revision` 单调递增。
- 新增 pending GET、CAS upsert、CAS resolve 三个内部接口。stale revision 返回 `40901`，pendingId 或状态迁移不一致返回 `40902`。
- confirm 从 active 原子迁移到 applying；只有 `transitionApplied=true` 的调用者可以执行副作用。重复 confirm 返回幂等结果但不获得执行权。
- complete、cancel、expire/fail 均通过后端状态迁移完成，Agent 不再把终态覆盖写进 planning-version extra-data。
- service 卡片/短文本确认和 direct `confirm_pending` 均已接入 claim-before-side-effect；新增测试证明 claim 未获得时方案变更 API 不会被调用。
- regression runner 的 pending clear、clone、backend assertion 改用独立资源；删除旧 version 0/latest 双清理和 pending extra-data 写入。
- 删除被替换的 `save_pending_confirmation(version=...)`、`_pending_extra_data_version`、tool-return pending version 读取等兼容外壳。

迁移边界：

- 新写只写独立 pending 表，不双写旧 extra-data。
- 独立表没有记录时，Agent 和 runner 暂时允许读取旧 latest extra-data；配置为 `INTERNAL_SERVICE_PENDING_LEGACY_READ_FALLBACK`。存量 pending 在确认或新预览时物化到新表。
- 该 fallback 是发布迁移窗口，不是长期双状态设计。完成线上存量观察后应关闭开关并删除代码。

验证：

- Python pending/direct/runner 聚焦：`396 passed, 29 skipped`。
- Python 完整 unit：`1523 passed, 29 skipped, 1 failed`；唯一失败仍是既有 admission-policy “家庭约束”措辞断言。
- Maven pending service：`7 passed`。
- Maven 完整：489 个测试中 1 failed、4 skipped；失败为既有 `ReviewInvalidationPolicyTest.shouldMarkConstraintIntentStaleWithCandidatePool`，focused 复跑仍失败，与 pending 文件链无关。
- 真实本地 backend `18082`：Flyway 6 -> 7 成功；临时 session 依次验证 create r1、stale write `40901`、confirm claim r2、重复 confirm `transitionApplied=false`、complete r3、replace r4、cancel r5。临时服务已停止。

下一步优先级：

1. 为 applying 增加 claim token、lease expiry 和受控恢复，解决 Agent 在 claim 后崩溃导致 pending 长期停留 applying 的问题。
2. 把 `apply intent + regenerate` 和 `replace remove + select + regenerate` 下沉为带 operationId/expectedPlanVersion 的幂等后端命令；pending CAS 目前只保证不重复发起，不能保证多步业务原子性。
3. 用新版 backend + Agent 重跑 clone-backed final-action gate，重点观察并发重复确认、服务重启和中间步骤失败。
4. 线上迁移窗口确认无旧 pending 读依赖后，关闭并删除 `pending_legacy_read_fallback`，完成 hard cut。

## v2.46 applying 租约与崩溃恢复结果

v2.45 记录的“claim 后进程崩溃会永久停留 applying”已完成第一阶段闭环：

- V8 新增 `claim_token`、`claim_expires_at` 和 expiry 索引；既有 V7 migration 保持不变。
- 后端固定 5 分钟执行租约。confirm 必须携带 claim token，首次 claim 写入 owner/expiry。
- 未过期 applying 不允许其他 token 接管；同 token 重放和其他 token 重试都返回 `transitionApplied=false`。
- 过期 applying 可由新 token 按 expectedRevision CAS 接管，revision、owner 和 expiry 一起更新。
- complete/fail 必须匹配当前 owner。租约接管后，旧 owner 的迟到终态提交返回 `40902 pending claim ownership mismatch`。
- Agent 只把 active 和已过期 applying 投影为可执行 pending；未过期 applying 的重复点击回复“正在处理中”，不会再次 claim 或执行业务变更。
- claim token/expiry 仅作为 `_pendingClaimToken/_pendingClaimExpiresAt` 运行态传输字段，不污染持久化业务 payload；新 preview 会清空旧 lease。

真实验证：

- backend `18082` 成功执行 Flyway 7 -> 8。
- token A claim：active r1 -> applying r2。
- token B 在租约有效期内：`transitionApplied=false`，revision 保持 2。
- 将临时测试租约设为过期后，token B 接管：applying r2 -> applying r3。
- token A complete：`40902`；token B complete：applied r4。
- 临时 backend 已停止，测试行已删除。

测试：

- Java pending service：`10 passed`。
- Python pending/service/direct/runner 聚焦：`399 passed, 29 skipped`。
- Python 完整 unit：`1528 passed, 29 skipped, 1 failed`，仍是 admission-policy 既有措辞差异。
- Maven 完整：492 个测试中 1 failed、4 skipped，仍是既有 ReviewInvalidationPolicy 断言。

当前最高优先级转为多步业务命令幂等：

1. 为 intent apply + candidate/order regenerate 定义单一 command，携带 operationId、pendingId、expectedPlanVersion。
2. 为 replace remove + select + regenerate 定义后端命令和可恢复 operation result，避免租约接管后重复执行部分步骤。
3. 命令端记录已完成步骤或最终结果；同 operationId 重放必须返回同一结果，不再次修改方案。
4. 完成命令下沉后再跑进程中断、租约过期接管和最终状态一致性专项回归。

## v2.47 多步规划命令幂等推进结果

v2.46 记录的高优先级多步动作已下沉，继续审计后发现的 add 两步调用也在同一轮完成，Agent 不再自行串联这些后端副作用：

- `apply constraint/tuition + optional regenerate` 统一为 `apply_constraint_and_regenerate` 命令。
- `add select + regenerate` 统一为 `add_units` 命令。
- `replace remove + select + regenerate` 统一为 `replace_units` 命令。
- 后端在同一 Spring 事务内校验 pending claim owner 和未过期 lease、锁定 pending 与 planningState、校验 `expectedPlanVersion`、执行全部步骤并写入 operation 结果；失败整体回滚。
- operationId 全局唯一。同 operationId/同业务请求重放返回相同结果并标记 `replayed=true`；不同请求占用同一 operationId 返回 `40903`；规划版本漂移返回 `40904`。
- 并发请求在等待 planningState 行锁后重新读取 operation，避免第一次读取发生在首事务提交前，等待后却按旧 expected version 误报冲突。
- pending 行在命令事务期间使用 `SELECT ... FOR UPDATE`，执行中的 lease 不会被并发接管；缺失、错误或过期 claim owner 都不能执行命令。
- 请求 SHA-256 覆盖全部稳定业务字段，但排除 claim token。租约恢复后的新 owner 可以重放原命令，不能改变目标、约束或替换项。
- operation 只保存恢复所需的压缩结果：版本、完成步骤和 ordered plan。candidate pool、profile、constraint、review 等大对象不进入命令日志。

迁移处理：

- V9 创建 operation 表后已在本地数据库应用。后续加入 request digest 时没有修改或 repair V9，而是新增 V10 列迁移。
- 启动验证显示 Flyway 成功校验 10 个 migration，schema 从 9 升到 10。已发布 migration 必须保持不可变，后续字段继续使用新版本前向迁移。

Agent 清理：

- intent apply、add 与 replace 三条旧多 API 编排已删除，统一调用 `execute_pending_planning_command`。
- operationId 使用 `pendingId + commandType` 的稳定 UUID5，断连后仍能提交同一 operation。
- 无响应、传输错误和 `planning command is already running` 保持 pending applying，等待重放；`operationId was used by another command` 是确定性一致性冲突，不再因同为 40903 被误判为 running。
- hard-cut 审计同时覆盖 add/replace，禁止旧 select/remove/regenerate 组合回流。remove/move/sort/regenerate 已各自是单后端动作，不再重复增加命令外壳。

真实 backend 验证：

- 隔离 session `990499993` 从已有正式规划状态复制，初始 planning version 为 473。
- 首次命令成功，完成步骤为 `constraint_updated`，版本 `473 -> 474`。
- 同 operationId/同载荷重放返回 `replayed=true`，结果版本仍为 474，没有二次写入。
- 同 operationId 改载荷返回 `40903 operationId was used by another command`。
- 新 operationId 使用旧 expected version 返回 `40904 current=474 expected=473`，且没有插入 operation 行。
- request digest 长度为 64；压缩 result_json 包含 orderedPlanState，不包含 candidatePoolState。
- pending complete 到 applied 后，operation、pending、planningState 三类临时记录计数均为 0；backend `18082` 已停止。

测试结果：

- Java pending + command 聚焦：`20 passed`，其中 command 10 条，覆盖成功重放、lease owner 变化后重放、等待 planning 锁后重放、版本冲突、owner/expiry 拒绝、载荷冲突和三类命令步骤。
- Python pending client/direct/hard-cut 聚焦：`228 passed, 29 skipped`。
- Python 完整 unit：`1533 passed, 29 skipped, 1 failed`；唯一失败仍为 admission-policy 既有“家庭约束”措辞断言。
- Maven 完整：502 个测试中 1 failed、4 skipped；唯一失败仍为既有 `ReviewInvalidationPolicyTest.shouldMarkConstraintIntentStaleWithCandidatePool`。

下一步优先级：

1. 发布迁移窗口确认后关闭并删除 `INTERNAL_SERVICE_PENDING_LEGACY_READ_FALLBACK`，完成 pending 旧 extra-data 读路径 hard cut。
2. 增加真实 Agent 提交后断连、服务重启、lease 过期接管和同 operationId 恢复 E2E，最终断言 planning version 只增长一次且 pending applied。
3. 定义 succeeded operation 日志的观测、保留与清理策略，防止长期无界增长；恢复窗口内的 running/相关记录不能提前清理。

## v2.48 pending 存量回填与旧读 hard cut 结果

v2.47 剩余的 pending extra-data 旧读已关闭，但不是直接删开关，而是先完成数据审计和 latest-only 回填：

- 旧 `pendingConfirmation` extra-data 共 6861 行，独立 pending 表为 0。
- 1142 条历史记录结构完整且状态为 active/applying；其中 569 条能关联主会话获得 tenant，573 条是缺主会话的历史测试夹具，不能伪造租户归属。
- V11 首版直接筛任意 active，因同一 session 存在多个 dataVersion，在 session 17 撞单活唯一键失败。该设计即使绕开唯一键，也会复活已被高版本 failed/空墓碑覆盖的旧 active，因此没有保留。
- 首次失败是单条 INSERT，确认独立表仍为 0 后，仅删除 `version=11, success=0` 的失败历史记录；未执行 Flyway repair，V7-V10 的成功记录和 migration 文件均未修改。
- 修订 V11 按 `data_version DESC`、同版本 `id DESC` 选每会话唯一 latest，再过滤 active/applying；同时 join 主会话获取 tenant，校验 JSON/必填字段/列长度，并清理旧 revision、claim、legacy 和 extra-data transport metadata。
- latest-only 后得到 552 条，比 569 条少 17 条；17 条均属于被更高版本终态覆盖的旧 active。真实迁移成功，Flyway schema 为 11。
- 552 条回填行全部 `revision=1`、`status=active`，transport metadata 残留 0。session 17 latest=failed，未写入独立表；抽样 session `934413008` 可通过独立 pending API 读取完整 active 快照。

完成的 hard cut：

- 删除 `pending_legacy_read_fallback` 配置。
- 删除 `get_last_pending_confirmation()` 对 `get_last_extra_data(..., "pendingConfirmation")` 的调用。
- 删除 `_pendingLegacySnapshot` marker、后端 marker 清洗分支和 legacy fallback 测试。
- 独立资源无行时统一返回空，不再恢复旧 pending；claim revision 0 的合法物化守护保留，但不读取旧存储。
- hard-cut 审计锁定 V11 latest-only 条件和 Agent 单资源读取，防止双读回流。

验证：

- Python pending/client/direct/hard-cut：`229 passed, 29 skipped`。
- Java pending/command：`20 passed`。
- Python 完整 unit：`1534 passed, 29 skipped, 1 failed`，仍为既有 admission-policy 文案差异。
- Maven 完整：502 个测试中 1 failed、4 skipped，仍为既有 ReviewInvalidationPolicy 断言。

下一步只保留两个结构项：

1. 真实 Agent/backend 的提交后断连、服务重启、lease 过期接管和 operation 重放 E2E。
2. succeeded operation 日志的指标、保留期与安全清理策略。

## v2.49 operation 日志保留与清理结果

operation 结果用于命令断连后的幂等重放，但不应无限增长。本轮完成以下治理：

- V12 新增 `(status, update_time, id)` 索引。
- 默认只删除 30 天前的 `succeeded`，每小时最多 500 条；running 不论多旧都不会被自动删除。
- Mapper DELETE 固定包含 succeeded、cutoff、ORDER BY id 和 LIMIT，不接受动态状态条件。
- shared service 将批量限制在 1-5000，并拒绝空 cutoff。
- scheduler 使用运行锁避免单实例重入；异常只记录日志，finally 释放锁，后续周期可以继续执行。
- 配置为 `planning.pending-command.retention.enabled/fixed-delay-ms/retention-days/batch-size`，默认启用。

真实数据库验证：

- 插入 40 天前 succeeded、当前 succeeded、40 天前 running 三条隔离日志。
- backend 启动后 Flyway 11 -> 12 成功，临时调度周期为 1 秒。
- 调度日志记录 `deleted=1 retentionDays=30 batchSize=500`。
- 查询只剩当前 succeeded 和 40 天前 running，证明恢复/调查状态未被误删。
- V12 索引列顺序为 status、update_time、id；测试记录清零，临时服务已停止。

测试：

- retention task/shared service：`7 passed`。
- pending command service：`10 passed`。
- 完整 Maven：509 个测试中 1 failed、4 skipped，唯一失败仍为既有 ReviewInvalidationPolicy 断言。

Release 4.0 pending 架构当前只剩真实断连恢复 E2E：首次命令已提交但 Agent 未收到响应、服务重启、lease 过期接管、同 operationId 重放、最终 complete，并断言 planning version 只增长一次。

## v2.50 断连、重启与租约接管恢复 E2E 结果

最后一个 pending 结构项已完成。新增 opt-in `tests/e2e/test_pending_command_recovery.py`，不经过模型语义层，直接复现 Agent 与 backend 之间最危险的结果不确定窗口：

- 隔离 session 创建 pending 并以 claim token A 取得 applying 执行权。
- 客户端用 10ms timeout 调用幂等 planning command，确定未收到响应；backend 仍完成事务，operation 进入 succeeded，planning version 只增长一次。旧进程日志出现预期 `ClientAbortException/Broken pipe`。
- operation 提交后测试写 ready 文件并阻塞，外部停止旧 backend、启动新 backend，健康后写 resume 文件。
- 测试自行读取监听 PID，要求 resume 前后 PID 集合不相交；正式运行旧 JVM PID `56306`、新 JVM PID `56671`，因此不是仅等待后继续使用原进程。
- 新进程下把 lease 调为过期，以 claim token B 完成 `applying -> applying` 接管；同 operationId、同业务载荷重放返回 `replayed=true`，resultPlanVersion 与第一次提交一致。
- pending complete 到 applied 后再次读取 planningState，版本仍只比初始值增加 1。

测试与清理：

- 强断言真实运行：`1 passed in 87.96s`。
- 未开启 opt-in：`1 skipped`；`py_compile` 通过。
- 完整 Python：`1534 passed, 29 skipped, 1 failed`；完整 Maven：509 个测试中 1 failed、4 skipped。失败仍是已登记的 admission-policy 旧文案断言和 `ReviewInvalidationPolicyTest`，没有新增失败。
- finally 删除 operation、pending、隔离 planningState 与屏障文件；实查三类数据库记录计数均为 0。
- 新 backend 已正常停止，18082 无监听。

结论：v2.45-v2.50 已关闭本问题日志发现的 pending 结构风险，包括独立 revision/CAS、单 active 快照、applying lease/owner、幂等事务命令、旧 extra-data latest-only 回填与 hard cut、operation 保留治理，以及提交后断连跨进程恢复。旧 extra-data pending 读写、Agent 多 API 执行编排和对应兼容测试均已删除，不再作为备用实现维护。

后续推进从“继续改 pending 架构”切换为发布门禁：运行完整 Python/Java 回归并只处理新增失败；观察 retention 删除日志与 running operation；在预发布环境做一次同样的进程重启演练。除非门禁发现新的确定性缺口，不再增加第二套 pending 存储、双写或兼容恢复路径。

## v2.51 发布门禁历史红项清理结果

v2.50 后完整门禁仍有两个长期登记的失败。本轮没有继续把它们作为可忽略基线，而是逐项复核责任边界：

- Python `test_missing_info_checklist_uses_context_and_lists_core_gaps` 仍期待“家庭约束”，当前生产输出早已细化为“家庭预算与可接受学费上限”。后者信息更具体且可直接采集，测试已切到当前完整字段名。
- Java `shouldMarkConstraintIntentStaleWithCandidatePool` 与生产实现、服务层测试和 4.0 候选池边界设计冲突。确认报考要求只影响有效候选、推荐、排序和审查，基础 candidatePool 保持全量可恢复后，将测试改为 `shouldMarkConstraintIntentStaleWithoutCandidatePool` 并断言 false。
- 真正需要刷新候选源的数据更新链路仍会设置 candidatePool stale，本轮没有放宽这类生产保护。

验证结果：

- admission-policy 聚焦：`9 passed`。
- ReviewInvalidationPolicy + PlanningStateService 聚焦：通过。
- 完整 Python：`1535 passed, 29 skipped`。
- 完整 Maven：509 个测试无失败、4 skipped。
- 生产代码改动：0；兼容实现新增：0。

结论：此前两个“已知失败”均属于被当前设计替代的旧测试资产，现已删除旧口径。Release 4.0 的 Python/Java 单元发布门禁现在全绿；历史章节保留当时失败数字作为验证记录，但不再允许后续变更沿用可忽略失败名单。

## v2.52 命名志愿动作与空方案执行结果

本轮继续复核 issue log 中“真实用户命名某校某专业进行新增/移动”的能力，确认原实现仍有三个确定性缺口：

- `add` 主要依赖候选 ID/现有 selector，模型给出结构化学校和专业时没有完整的后端候选解析闭环。
- `_item_unit_id()` 未读取真实候选常用的 `planSchoolDataId`，会把带多个下划线的 volunteerId 错误截成学校计划 ID，而不是专业组 ID。
- 空方案 summary 直接返回时丢弃 planning version，导致 pending 的 `sourceBackendVersion=0`，确认后被后端版本 CAS 正确拒绝。

实现与边界：

- `preview_plan_action(add)` 接受 `filters.school + filters.major` 和 `学校.专业` target，先查缓存候选，再按同一结构化 query 查 backend；唯一候选创建 `add_units` pending，同 `planSchoolDataId` 多专业按组选择，跨组多解列出选项澄清，零命中和已存在均不创建 pending。
- 工具层没有对 `raw_user_text` 做中文关键词扫描；学校/专业语义识别仍由模型结构化输出负责。
- 专业组身份优先读取 `unitId/unit_id/planSchoolDataId/plan_school_data_id`；空方案 summary 保留 `phase/version`。
- “当前没有待确认操作”回复统一说明上一轮查询/分析没有可执行内容，不会产生变更，并给出下一步；短文本“确认”仍走零模型请求 direct guard。

测试资产也做了 hard cut：

- 删除真实 fixture 中不存在的“中国海洋大学 + 国际经济与贸易”“华中农业大学”等样本。
- 命名 move 改为 session 16 真实的“电子科技大学中山学院第101组 + 光电信息科学与工程”。
- 命名 add 改为 session 17 真实的“厦门大学嘉庚学院 + 建筑学”；“建筑类”会列出建筑学和城乡规划并澄清。
- session 17 没有 formal/ordered plan，相关 case 从错误的 `formal_plan_present` 改为 `empty_plan + candidatePool`；被统一进度文案替代的 thinking 白名单不再制造假红项。

真实执行先后暴露了两种不同问题：第一次确认因 `expected=0/current=1724` 失败，属于上述空方案版本缺陷；修复后第二次因 `127.0.0.1:5001` 未启动而在排序生成阶段连接拒绝，属于测试拓扑缺失。启动 rank 后，隔离 session `9906517` 的精确新增最终通过：pending 为 applied，planning version 增长，ordered items 包含 `37020261000269_37020262005080_709`，并返回 ordered/review 刷新动作。没有为缺少 rank 增加跳过排序或假成功路径。

验证结果：

- direct 单测：`192 passed, 29 skipped`。
- 命名 move、精确 add 两轮最终动作、宽泛类别澄清：`4/4`。
- 查询后确认 no-pending guard：`2/2`；确认内部 direct bridge 109ms，无模型请求、无副作用。
- 完整 Python：`1629 passed, 38 skipped`。
- 完整 Maven：509 个测试无失败、4 skipped。

结论：命名新增已从“模型能说出目标但工具不一定能落到真实候选”推进到结构化解析、pending 预览和最终后端生效闭环；同时清除了错误 fixture 和旧断言。后续不再围绕这些已闭合路径增加兼容分支，发布验证只保留更多真实命名样本扩展、完整服务拓扑健康检查和全量门禁。

## v2.53 发布拓扑与 smoke 验证结果

v2.52 关闭命名新增后，本轮按发布验证阶段继续检查正式门禁和四服务拓扑：

- local quality gate：`433 passed`。
- runtime hard-cut：`36 passed`。
- 完整 gate dry-run：1 个 local、13 个 live、19 个 clone-backed final-action、3 个 model 命令以及对应报告链均可生成。
- 开发端口 healthcheck：Web 3001、Backend 8080、Agent 8000、Rank 5001 及 Backend base-data 全部 PASS；Docker/systemd/nginx 在开发机缺失只产生预期 WARN。

前端启动发现两个可维护性问题并已清理：

- `NEXT_PUBLIC_AGENT_API_BASE_URL`、`NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE` 是可选覆盖项，但 `next.config.mjs` 直接注入 undefined，Next 每次启动都报告 invalid config；现在缺省为空字符串，运行时 fallback 不变。
- session 页面唯一一处 `Tooltip.overlayStyle` 已被 Ant Design 5 标记弃用，替换为等价的 `styles.root`。重启并实际请求 `/session` 后，配置和 Tooltip 两类警告均消失。

初次只读 `release-smoke --local` 中 Backend、review rules、Agent、Rank 全部通过，但两个 Web 页面固定请求 `/assistant-pc/*`，对标准开发态空 basePath 必然 404。该脚本此前没有 Web basePath 覆盖能力，因此新增：

- `ZHIYUAN_WEB_BASE_PATH` 默认 `/assistant-pc`，继续保持生产 smoke 契约。
- 显式设置为空时检查开发态 `/session`、`/sessionDetailV2`，不要求 production routes manifest。
- 页面内容统一检查 Next `__NEXT_DATA__`，不再检查路径字符串是否偶然出现在 HTML。

修复后真实只读 smoke：两个 Web 页面、Backend health/base-data/review rules、Agent health/WebSocket、Rank health 全部 PASS，`failures=0`；未指定 session，因此 workspace/data-freshness 按设计 SKIP，没有创建或修改规划状态。新增 fake-curl 测试覆盖默认生产和显式空开发 basePath，结果 `2 passed`；完整 Python `1631 passed, 38 skipped`。

全量 `tsc --noEmit` 仍有 26 个既有类型错误，位于旧 session ModalForm/subjectScores、userCenter、service/request 等模块，本轮修改文件不在错误列表。该门禁不能标为通过，后续应单列前端类型债治理，不能混入 Agent 结构修复。

维护清账：G12/G25、G1-G32 direct 多轮验证、pending/旧链路 hard cut 均已完成，从“后续 P0”移除。当前唯一发布 P0 是在稳定完整拓扑上执行全部 13 个 live 和 19 个 clone-backed final-action 命令；分析数据、候选质量和 shadow 扩展属于 P1 持续增强。
