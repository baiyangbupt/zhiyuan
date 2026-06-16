# 下一轮会话接续摘要

更新时间：2026-06-16

## 2026-06-16 本轮新增收口

- 这轮先处理了两个真实回归里最明确的产品问题：
  - 地域意向里，用户只明确说“只考虑江苏浙江 / 不想去天津”这类省份条件时，不再把模型抽到的宏观区域（如华东/华北）回填进确认卡片。
  - 职业方向的确认摘要继续沿结构化值输出，不再退回空泛标题。
- 代码修复：
  - `app/tools/intent_state_tool.py`
    - 新增 `_prune_inferred_region_area_values(...)`
    - 区域 `area/negative_area` 只在用户原话显式提到华东/华北/南方/北方/东三省/京津冀/长三角等宏观区域时保留
    - 只说省份时，卡片不再额外带出大区
  - `app/tools/intent_preview_tool.py`
    - `preview_current_region_intent_confirmation(...)` 统一先做区域保真归一化，再交给 intent analysis
  - `tests/unit/test_intent_state_tool.py`
    - 新增“只考虑江苏浙江”不再抬成“华东”的单测
  - `tests/unit/test_chat_service_history_persistence.py`
    - 新增职业方向摘要断言，确认会输出“体制内/考公导向”“不优先发展方向”等结构化结果
- 这轮验证：
  - `tests/unit/test_intent_state_tool.py` 相关最小回归：`5 passed`
  - `tests/unit/test_chat_service_history_persistence.py` 相关最小回归：`2 passed`
  - `examples/dialog_regression_runner.py --cases examples/dialog_regression_303_dialogue_derived_cases.json --case-name 303-dialogue-region-south-only --case-name 303-dialogue-region-beijing-tianjin-safety --case-name 303-dialogue-career-civil-service-major --case-name 303-dialogue-career-stability-vs-interest --response-timeout 120 --clear-history-per-case --clear-backend-pending-per-case --assert-plan-style`
    - 4/4 通过
  - `examples/dialog_regression_runner.py --cases examples/dialog_regression_310_constraint_plan_action_cases.json --case-name 310-constraint-only-keep-major-preview-and-apply --case-name 310-constraint-tuition-budget-preview --response-timeout 120 --clear-history-per-case --clear-backend-pending-per-case --assert-plan-style`
    - 2/2 通过
- 真实回归里顺带确认：
  - `only_keep_constraint` 仍能稳定生成并应用确认卡
  - `tuition_budget` 仍能稳定生成预算调整预览
  - 本轮改动没有打散现有 plan / intent 主协议

## 2026-04-30 换 thread 前最新状态

- 这轮已继续沿真实主线做联调，重点修掉了 `high_tuition -> replace_units` 的核心残留问题：
  - 旧问题已在 fresh session `80` 复现：
    - `直接给我弄一版 -> 确认 -> 把贵的换成正常收费的，别少名额 -> 确认`
    - 旧执行层虽然已经能把数量补回 `30/30`，但补入阶段仍会把高收费候选重新选进来
    - 替换后复审仍保留 `high_tuition`，最终还能查到 9 条高收费志愿被补回
- 根因已经确认：
  - backend 的 `high_tuition` 复审口径就是 `tuitionPerYear > 20000`
  - 候选池里并没有稳定可依赖的“高收费”枚举标签；这些候选主要表现为：
    - `tuitionPerYear` 字段大于 `20000`
    - `majorPlanTags / reasonCodes` 里带 `学费：xxxx/年`
  - agent 旧执行层在 `replace_units` 的补入阶段没有按 `review_issue_target=high_tuition` 做结构化过滤，所以会把这些候选重新补回
- 本轮代码修复：
  - `app/tools/plan_execution_tool.py`
    - `_query_candidate_pool_selection(...)` 新增 `replacement_issue_code`
    - 对 `high_tuition` 问题项按与 backend 一致的口径过滤候选：`tuitionPerYear <= 20000`
    - 若 `tuitionPerYear` 缺失，再从 `majorName / majorPlanTags / reasonCodes` 解析学费文本兜底
    - preview 预检和 apply 补入都统一走这层过滤，不再只靠话术或模糊标签
  - `tests/unit/test_plan_execution_tool.py`
    - 新增用例覆盖：
      - `high_tuition` 替换预检时只统计过滤后的可用候选
      - 真正补入时会跳过高学费候选、继续补正常收费候选
- 本轮回归：
  - `./.venv/bin/pytest tests/unit/test_plan_execution_tool.py -q` -> `57 passed`
  - `./.venv/bin/pytest tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_chat_agent_init_profile.py -q` -> `15 passed`
  - `./.venv/bin/python -m py_compile app/agent/chat_agent.py app/service.py app/tools/plan_execution_tool.py app/tools/plan_orchestration_models.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_chat_agent_init_profile.py` -> passed
- 本轮真实验证：
  - fresh session `81`
    - `直接给我弄一版 -> 确认 -> 把贵的换成正常收费的，别少名额 -> 确认`
      - 已稳定移出 `44` 条高收费相关志愿
      - 已稳定补回 `13` 个候选，方案保持 `30/30`
      - 替换后复审里 `high_tuition` 已消失
    - `调整后这版还有高收费吗`
      - 当前真实回复已变为“没有了”
      - 最终 ordered plan 中 `high_tuition` 命中明细为空
- 当前新的主线观察：
  - 在 session `81` 中，高收费清理后继续问：
    - `这版有啥问题`
    - `那接下来该怎么弄更稳`
    - `帮我顺一下 -> 确认`
  - 语义路由基本正确：
    - `review_plan`
    - `analyze_adjustment`
    - `regenerate_order`
  - 但 `regenerate_order` 后结构性问题并没有改善，说明“更稳”这类诉求当前仍更接近“替换/补稳”而不是单纯重排
- 另一个需要继续盯的点：
    - `帮我补几个更稳的` 在 `30/30` 满额场景下会先解释“没有名额缺口，需要替换调整”
    - 旧问题是：前一轮实际只做了 `preview_compensation(0项)`，但文字却转成“要不要做替换调整”，服务层仍把旧 `apply_compensation` 留成 pending，下一轮 `确认` 会错误直执行到补齐分支
    - 这轮已修：
      - `app/service.py`
        - `preview_compensation` 只有在确实存在可执行补齐动作时，才允许映射成 `apply_compensation` pending
        - 对“现在还不会改动方案”这类无 pending 的口头确认句，边界修正会明确提示“这一步不会因为你回复确认就直接改方案”
      - `tests/unit/test_chat_service_history_persistence.py`
        - 已新增 `0 项动作 / 预计补入 0 个志愿` 不生成 pending 的测试
        - 已新增空补齐预览不再留下假确认边界的测试

- 2026-06-16 这轮继续收口 intent 确认链路：
  - 修复 `pendingConfirmationCard` 恢复分支在 intent 场景下把 `reply` 清空的问题，恢复后会补回用户可读的主回复，不再出现“卡片有了但正文空白”。
  - 修复旧 `planEditCache` 清理对字符串 `session_id` 的 `int(...)` 强转异常，避免 `"toolless-no-plan-only-keep-session"` 这类测试/业务会话触发 warning。
  - `app/service.py` 新增 `_intent_card_primary_reply_from_card()`，用于从恢复出的卡片 payload 重新生成主回复。
  - `zhiyuan-agent/tests/unit/test_chat_service_history_persistence.py` 新增字符串会话号跳过旧缓存清理的最小回归断言。
  - 本次只改“输出和兼容清理”，确认协议、intent 路由和 pending 状态机边界保持不变；后续再扩文案时，仍要保住“卡片主回复必须可读、旧缓存清理不能被字符串 session 卡死”这两个约束。
    - 真实验证：
      - fresh session `82`
        - `帮我补几个更稳的`
          - 当前不会再错误挂 `apply_compensation` pending
        - 直接回 `确认`
          - 当前稳定走 no-pending guard，不再误执行错误工具分支
- 这轮继续顺着“更稳”主线往下收了一层语义：
  - 旧问题：
    - `按更稳的思路帮我弄一版`
    - 容易落到 `regenerate_order`
    - 但真实执行后只是整体重排，风险并没有降低，给用户造成“像是执行了正确动作，其实没有解决更稳目标”的假动作
  - 本轮已在 `app/tools/plan_orchestration_tool.py` 增加更硬的分流：
    - `preview_compensation` 在 `30/30` 满额场景下，不再优先走补齐，而是先收口到 `analyze_adjustment`
    - `regenerate_order` 只保留给明确“重排 / 顺一下 / 排一排 / 重新排”的话术
    - 对“按更稳的思路 / 更保守 / 风险低一点”这类话术，如果上游路由给到的是 `regenerate_order`，编排层会再收口到 `analyze_adjustment`
  - 配套测试：
    - `tests/unit/test_plan_orchestration_tool.py`
      - 保住 `帮我顺一下 -> regenerate_order`
      - 新增 `按更稳的思路帮我弄一版 -> analyze_adjustment`
  - 真实验证：
    - fresh session `83`
      - `直接给我弄一版 -> 确认 -> 把贵的换成正常收费的，别少名额 -> 确认 -> 按更稳的思路帮我弄一版`
      - 当前不再直接确认重排，而是先给“冲区过高 / 本省保底不足 / 梯度断层”的调整分析
- 仍未解决的下一层主线问题：
  - 在 session `83` 里，“按更稳的思路帮我弄一版”虽然已经不再误落到纯重排，但当前仍只停在 `analyze_adjustment`
  - 对用户来说，更接近预期的应该是：
    - 要么直接给出一个可确认的“更稳方案调整 preview”
    - 要么承接 backend `plan-adjustment/apply`
  - 当前 backend 真实 `plan-adjustment/analyze` 结果里：
    - `ratio_distribution / safety_guard` 这类问题仍主要给 `addSuggestions`
    - `session 82` 的真实 `planAdjustmentState.suggestions` 里没有 `replaceSuggestions / reorderSuggestions`
    - 所以即使 agent 收正到了 `analyze_adjustment`，下一步如何“真正执行更稳方案”还需要继续设计：
      - 走 backend `plan-adjustment/apply`
      - 或在 agent 侧把 `add/replace/reorder` 建议桥接到现有 `replace_units / regenerate_order`
  - 本轮继续向下验证后补充：
    - backend `plan-adjustment/apply` 当前仍是空壳：
      - `PlanningStateService.applyPlanAdjustment(...)` 现在只把 `planAdjustmentState.status` 改成 `pending_apply`
      - 不会真实改草稿 / 排序 / 审查结果
    - 因此短期不能指望直接接 backend apply 打通“更稳方案”主线
    - `session 84` 的真实链路确认了两个关键点：
      1. 高收费整批替换 preview -> confirm -> apply 现在是稳定可执行的
      2. 抽象“更稳”诉求在 `analyze_adjustment` 后，模型仍可能口头组织出“先去掉高收费、再补稳保”的两步方案，但如果没有真实 preview payload，服务层现在会稳定拦住下一轮 `确认`，不再误执行
    - 当前 service 层已新增一层更窄的 pending 保护：
      - 如果某轮只是 `adjustment_analysis` 且 `has_actionable_suggestions=false`
      - 后面同一轮再冒出 `generate_plan / regenerate_order / apply_compensation` 这类大动作 preview，不再允许挂成 pending
      - 这样至少可以挡住“分析后被模型偷偷篡改成覆盖重生成”的确认误执行
    - 但这也说明真正的业务缺口更明确了：
      - 当前系统已经能**识别**“更稳”的方向
      - 也能**阻止**错误执行
      - 但还不能把“更稳”的口头方案可靠地落成一个**真实可确认的第一步动作**
    - 下一轮建议优先解这个业务问题，而不是继续修 guard：
      1. 如果 review 里命中 `high_tuition`，优先直接给“整批高收费替换 preview”
      2. 如果命中 `major_group_safety_intent_alignment / probability_gap` 且有具体 `affectedVolunteerIds`，优先给“局部替换 preview”
      3. 只有拿到真实 `orderedVolunteerIds / replacementPairs / candidateVolunteerIds` 时，才把分析进一步升级成可确认动作
- 关于这层“规则 vs 模型理解”的当前结论：
  - 用户已明确要求：这里先不用急着迁到更纯的模型理解，先记录当前规则收口，优先打通主线业务
  - 当前实现定位为**过渡态**：
    - 语义层仍有少量编排侧规则收口，用来防止主线误执行
    - 状态守门（满额不能补齐、空预览不挂 pending、无 preview 不 confirm）应继续保留在代码层
  - 当前已收口的规则范围只保留在这几类：
    - `30/30` 满额时，`preview_compensation` 收口到 `analyze_adjustment`
    - 明确“重排 / 顺一下 / 排一排”才继续保留 `regenerate_order`
    - “按更稳的思路 / 更保守 / 风险低一点 / 弄一版”这类抽象调整话术，从 `regenerate_order` 收回到 `analyze_adjustment`
    - `preview_compensation` 只有存在真实可执行补齐动作时，才允许映射成 `apply_compensation` pending
  - 下一轮不要继续优先投入“去规则化”本身，先把业务主线闭环做出来，再回头把这层迁成“模型负责语义分类、代码负责状态守门”
- 关于 `非意向托底 / 组内安全垫` 的最新业务口径：
  - 用户已明确补充：
    - `非意向托底` 不是简单的“混入了不喜欢的专业”
    - 这类专业之所以被补进来，是为了让**最终主选专业里最低录取率不低于专业组整体录取率**，从而降低退档风险所做的牺牲
    - 也就是安全垫口径应按 `admissionRatio >= schoolEnrollRatio` 理解，不是必须严格 `>`
  - 当前核对结果：
    - backend Java 实现 `isSafetyMajorRatio(...)` 已经是 `>=`
    - 但 backend 若干文档和提示文案里仍残留“高于组整体录取率”的旧说法
    - agent 用户侧本轮已统一改成“不低于专业组整体录取率 / 防退档安全垫”的解释口径
  - 下一轮处理这类场景时，必须同时说清两面风险：
    1. 它偏离用户意向，是体验和兴趣上的牺牲
    2. 它可能正是在专业组里承担防退档的安全垫，直接去掉会增加退档或组内调剂失控风险
  - 因此不要再把 `major_group_safety_intent_alignment` 默认理解成“建议删掉非意向专业”
    - 更合适的处理方式应是：
      - 先确认是否接受这类牺牲项
      - 或寻找同等安全垫的替代专业 / 替代专业组

## 2026-04-30 口语化主线验证补充

- 这轮继续聚焦真实主线，不再纠结强迫式文案本身，重点验证用户更自然的话术是否还能稳定落到正确的 plan 语义：
  - `这版有啥问题`
  - `贵的先去掉`
  - `现在少的这些咋补`
  - `这版怎么排更合适`
  - `那你直接帮我顺一下`
- 已补代码 / 资产：
  - `app/agent/chat_agent.py`
    - 增加口语化调整建议问法 -> `analyze_adjustment`
    - 增加口语化直接改排问法 -> `regenerate_order` preview
  - `skills/plan_chat/SKILL.md`
    - 同步补充上述口语化方案话术和边界说明
  - `examples/dialog_regression_mainline_cases.json`
    - 新增 2 条口语化主线 case
  - `docs/test/planning-dialog-integration-checklist.md`
    - 新增话术包 G/H，明确真实联调优先用口语化问法
- 单测：
  - `./.venv/bin/pytest tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_chat_agent_init_profile.py -q` -> `15 passed`
  - `./.venv/bin/python -m py_compile app/agent/chat_agent.py app/service.py` -> passed
- 本轮真实验证：
  - fresh session `73`
    - `直接给我弄一版 -> 确认 -> 这版怎么排更合适`
      - 正常走 `collect_plan_context_inputs -> plan_next_action(action_family=analyze_adjustment) -> execute_plan_action`
      - 返回的是分析建议，不直接改方案
    - `那你直接帮我顺一下 -> 确认`
      - 已修正为 `regenerate_order` preview -> apply
      - 不再漂到“先处理高收费”分支
  - fresh session `74`
    - `直接给我弄一版 -> 确认 -> 这版有啥问题`
      - 正常走 `review_plan`
    - `贵的先去掉 -> 确认`
      - 预览范围稳定为 `共 13 个专业组，涉及 44 条志愿`
      - 确认后真实移除 `44` 条，并重新复审
    - `现在少的这些咋补`
      - 正常走 `preview_compensation`
      - 返回缺口 `13`，没有误走局部查询或删除/替换
  - fresh session `75`
    - `直接给我弄一版 -> 确认 -> 这版没啥大问题吧`
      - 正常按 `review_plan` 理解，先给“总体没硬风险、但有 3 个提醒”的口语化复盘
    - `那接下来该怎么弄更稳`
      - 正常走 `analyze_adjustment`
      - 当前会给出“先减法、再补稳、再微调排序”的建议，不会直接静默执行改动
- 当前观察到一个次要现象：
  - session `74` 的 `贵的先去掉` 这轮里，模型出现过一轮重复的 plan 主链调用（两次 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`），但最终语义和结果正确。
  - 这更像是模型在同轮内自校正，不是执行层 scope 错；如果后面要继续压时延，可以再单独分析这一类重复 tool call。
  - session `75` 的最后一轮回复里仍会出现“二选一”这类偏产品式引导，但主链语义正确；当前先记录为低优先级话术问题，不阻塞主线验证。

## 2026-04-30 当前补充记录

- 先暂停继续堆执行补丁，补了一份 review issue 语义设计文档：
  - `docs/review_issue_semantics_design.md`
- 这份设计针对的是当前主线里更底层的问题：
  - backend 已有 `ReviewCheckDTO(code/summary/affectedUnitIds/affectedVolunteerIds...)`
  - agent 主链里缺少一等 `review issue` 对象，导致模型容易把审查“样例”当成“作用范围”
  - 当前 execution 对 broad issue 的处理仍主要靠少量关键词反推，不能泛化
- 文档里已经明确：
  - `review issue` 与 `sample items` 的区别
  - 当前所有 backend review code 的语义分类
  - `item_removal / structural / informational` 三类默认处理路径
  - 建议把 `review_issues` 接进 `PlanContextInputs`
  - 建议给 `PlanAtomicAction` 增加 `review_issue_target`
  - broad / narrow issue follow-up 的规划与执行边界
- 下一步实现应按文档里的顺序推进：
  1. `review_issues -> PlanContextInputs`
  2. `review_issue_target -> PlanAtomicAction`
  3. `plan_next_action` 承接 broad issue
  4. `execute_plan_action` 改为按 target 解 scope，不再靠关键词补丁
- 这轮后续已经把上述设计落到代码：
  - `app/tools/plan_context_tool.py`
    - `collect_plan_context_inputs` 现在会输出 `review_issues / review_issue_summary_lines`
  - `app/tools/plan_orchestration_models.py`
    - 新增 `PlanReviewIssueTarget`
    - `PlanAtomicAction` 现在可携带 `review_issue_target`
    - flat payload 归一化只在真有动作形状时才下沉为 `atomic_actions`
  - `app/tools/plan_orchestration_tool.py`
    - broad review issue 会按 issue 语义纠正 action family
    - `item_removal` broad follow-up 默认收口到 `remove_units`
    - `structural` broad follow-up 默认收口到 `analyze_adjustment / preview_compensation`
  - `app/tools/plan_execution_tool.py`
    - preview / apply 统一按 `review_issue_target` 解 scope
    - broad `item_removal` 支持按当前整批 issue scope 预览与执行
    - `structural` issue 不再误当删除清单
    - 对误规划成 `replace_units` 的 broad item-removal follow-up，执行层会防御性收口到整批移除
- 本轮回归：
  - `./.venv/bin/pytest tests/unit/test_plan_context_tool.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py -q` -> `138 passed`
  - `./.venv/bin/pytest tests/unit/test_mainline_dialog_scenarios.py -q` -> `8 passed`
  - `./.venv/bin/pytest tests/unit/test_chat_agent_init_profile.py -q` -> `7 passed`
  - `./.venv/bin/python -m py_compile app/agent/chat_agent.py app/service.py app/tools/review_issue_registry.py app/tools/plan_context_tool.py app/tools/plan_orchestration_models.py app/tools/plan_orchestration_tool.py app/tools/plan_execution_tool.py`
- 本轮真实验证补充：
  - backend fresh session：`chatSessionId=70`
  - 直接用当前 workspace 的 `ChatService` 跑真实链路，确认不是旧 websocket 进程：
    - `帮我审查一下当前方案 -> 先处理高收费 -> 确认`
      - 现已稳定预览为：`共 13 个专业组，涉及 44 条志愿`
      - 确认后实际移除 `44` 条，并触发复审
    - `先处理数量不足`
      - 现已走补齐预览，返回 `预计补入 13 个志愿`
      - 不再误走删除/替换类动作
- 仍需注意：
  - 当前本地 `8000` compat websocket 进程看起来仍是旧代码行为；同一 `session 70` 在该旧进程上仍会回到“先问预算上限”的旧路径。
  - 如果后续要继续做前端/compat 真链路验证，需要先确认 agent websocket 进程已重启到当前代码。

## 2026-04-29 当前补充记录

### 2026-04-29 晚间补充（majorGroup relation 计数修复）

- 已修正 `app/tools/planning_workflow_tool.py` 在 `majorGroup` 模式下把同一专业组内多个专业重复计入“较贴近/冲突”数量的问题。
  - 修复方式：沿用 backend `resolveDraftOrOrderedUnitId` 的口径，用 `volunteerId` 下划线前缀作为 unit key；只有当 `summary.unitTotal/total < items.len` 时才按 unit 聚合，避免误伤普通 `专业+院校` 模式。
  - 示例仍保留具体专业行，不改成抽象组名。
- 新增单测：
  - `test_run_planning_review_aggregates_major_group_relation_counts_by_unit`
- 本轮回归：
  - `./.venv/bin/pytest tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_execution_tool.py -q` -> `69 passed`
  - `./.venv/bin/pytest tests/unit/test_mainline_dialog_scenarios.py -q` -> `8 passed`
  - `./.venv/bin/python -m py_compile app/tools/planning_workflow_tool.py app/tools/plan_execution_tool.py tests/unit/test_planning_workflow_tool.py`
- 真实链路验证（当前代码 + 本地 backend/model）：
  - `session 67`，干净本地 history：
    - `帮我审查一下当前方案`
      - `ChatService.handle_message(...)` 回复里已不再出现 `62`，当前表述为“较贴近约 25 个志愿”
      - 直接 `run_planning_review(...)` 原始工具输出也为：`当前方案里较贴近的有25个，明显冲突的有0个`
  - `当前方案里湖北工程学院01组有哪些专业`
    - 当前真实 ordered plan 里该组只有 2 个条目：`电子信息工程`、`自动化`
    - agent 回复 2 个专业与 backend 当前状态一致；上一轮“3 个专业”的记录可视为旧状态/旧观察，不是 query 层漏数
- 后续继续修了两层真实链路问题：
  - `app/tools/plan_execution_tool.py`
    - ordered ref resolver 现在会为专业名生成“完整名 / 去掉尾部括号组后的变体 / 裸专业名”多组 label
    - 已修复这类 pending confirm 断点：preview 里是 `武昌理工学院(02)-智能科学与技术(华为精英班)@23`，ordered item 真实名是 `智能科学与技术(华为精英班)(28800元)` 时，确认阶段现在能重新定位到真实 `volunteerId`
  - `app/tools/plan_context_tool.py`
    - `collect_plan_context_inputs` 现在也会把 ordered/draft `summary` 传给 `_build_plan_intent_relation_lines`
    - 已修复 service 上游 `context_summary` 在 `majorGroup` 模式下继续泄漏 `62` 这类“组内专业重复计数”旧摘要的问题
- 本轮继续定位并修复了补齐链的真正根因：
  - backend `preview_planning_compensation` 在 `majorGroup` 模式下会同时返回：
    - `unitIds`：专业组数量口径
    - `volunteerIds`：组内专业拍平后的行数量口径
  - agent 之前错误地用 `volunteerIds.len` 当作“预计补入数量”，导致：
    - `28/30` 时 preview 明明是 `补 2 个专业组`
    - agent 却把拍平后的 `3` 个 `volunteerIds` 当成“补 3 个志愿”
    - 进而在 apply 前误拦截成“会超过目标数量”
  - 这次已修：
    - `app/tools/planning_workflow_tool.py`
      - compensation preview facts / 展示文案改为优先按 `unitIds` 计数，没有 `unitIds` 才退回 `volunteerIds`
    - `app/tools/plan_execution_tool.py`
      - compensation preview summary 和 apply blocker 都改为按 `estimated_fill_count` 判断
      - `_append_intent_relation_summary` 也补传 `plan_summary`，避免 apply 成功后的首段摘要再次泄漏 `63` 这类 row 口径
- 新增单测：
  - `tests/unit/test_plan_execution_tool.py`
    - `test_execute_plan_action_remove_resolves_major_ref_without_trailing_fee_suffix`
    - `test_execute_plan_action_runs_compensation_preview_counts_major_group_units`
    - `test_execute_plan_action_allows_major_group_compensation_apply_when_unit_gap_matches`
    - `test_append_intent_relation_summary_uses_major_group_unit_count`
  - `tests/unit/test_plan_context_tool.py`
    - `test_collect_plan_context_inputs_aggregates_major_group_relation_counts_by_unit`
  - `tests/unit/test_planning_workflow_tool.py`
    - `test_preview_planning_compensation_prefers_unit_count_in_major_group_mode`
- 新一轮回归：
  - `./.venv/bin/pytest tests/unit/test_plan_context_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_planning_workflow_tool.py -q` -> `75 passed`
  - `./.venv/bin/pytest tests/unit/test_mainline_dialog_scenarios.py -q` -> `8 passed`
  - `./.venv/bin/python -m py_compile app/tools/plan_context_tool.py tests/unit/test_plan_context_tool.py app/tools/plan_execution_tool.py tests/unit/test_plan_execution_tool.py`
- 最新真实链路验证（当前代码 + 本地 backend/model）：
  - `session 67`：
    - `帮我审查一下当前方案`：当前 service 回复已稳定到 `25`，不再出现 `62`
    - `帮我审查一下当前方案 -> 先处理高收费 -> 确认`：已通过
      - 成功移除 `北京城市学院(04)-护理学`、`武昌理工学院(02)-智能科学与技术(华为精英班)`
      - 该轮回归后曾短暂变为 `28/30`
      - apply 后复审摘要显示：`风险1项 / 提醒4项 / 数量不足2个 / 较贴近24个`
    - 最新继续回归：
      - `29/30 -> 先预览补偿建议 -> 确认`：已通过
      - preview 现在会正确按 `unitIds` 显示 `预计补入 1 个志愿`
      - apply 成功后首段摘要与复审结果都保持 unit 口径，不再出现前半段 `63` / 后半段 `26` 的冲突
      - 当前 `session 67` 最新状态已回到 `30/30`

### 2026-04-29 最新主线验证与收口

- 主线场景目录已补到 29 条，新增 5 条高价值闭环回归：
  - `risk-followup-remove-preview-apply-review`
  - `compensation-preview-apply-post-review`
  - `ordered-move-preview-apply`
  - `pin-unpin-after-review`
  - `school-major-group-query-then-replace`
- 这批新增 case 对应当前真实联调最值得盯的缺口：
  - 审查问题追问后能否直接进入 remove / replace preview 并确认执行
  - 补齐动作是否形成 preview -> apply -> post-review 闭环
  - `move_unit / pin_unit / unpin_unit` 是否持续可用
  - “学校 + 专业”与“院校专业组”混合表达下，局部查询与 replace 是否仍稳定命中
- 已确认当前 agent 调用模型配置来自本地 `.env`：
  - `LLM_PROVIDER=openai_compatible`
  - `LLM_MODEL_NAME=Pro/moonshotai/Kimi-K2.6`
  - `LLM_BASE_URL=https://api.siliconflow.cn/v1`
- 本轮继续补了一个干净 real session：
  - 用 `examples/create_real_session.py` + `/tmp/create_session_req_major_group.json` 创建 backend `session 67`
  - 创建结果：`441分 / 北京 / 物化生 / majorGroup`
- `session 67` 在当前代码下的真实联调结果：
  - `直接生成一版方案 -> 确认生成 -> 现在方案怎么样`：通过，生成后为 `30/30`，`冲9 / 稳9 / 保12`
  - `把第3个志愿固定住 -> 确认 -> 再把第3个志愿取消固定 -> 确认`：通过，preview / apply / ordered+review followup 都正常
  - `当前方案里湖北工程学院01组有哪些专业`：通过，能列出专业组内 3 个专业及位置
  - `把湖北工程学院的计算机科学与技术换成电子信息类 -> 确认`：当前代码下已不再出现“按会计/审计重新定位”的错误文案；会执行 remove + candidate refill，并在未新增成功时明确说明“匹配到候选但方案数量没有增加”
- 本轮新修的主线问题：
  - `app/tools/plan_execution_tool.py`
    - `move_unit / pin_unit / unpin_unit` 现在和 `remove_units / replace_units` 一样，都会先把 `@20`、`第3位`、`学校+专业`、`专业组+专业` 解析成真实 `volunteerId`
    - ordered ref 未命中时的 fallback 文案收口为通用“按当前方案重新定位”，不再残留会计/审计场景硬编码
  - `app/agent/chat_agent.py` + `skills/plan_chat/SKILL.md`
    - 明确要求对“把第20个往前挪到第3个 / 把第3个固定住 / 取消第3个固定”这类位置表达，直接按 `@20` / `@3` 规划 `move_unit / pin_unit / unpin_unit`，不要先追问学校名
- 真实回归补充说明：
  - 旧的本地 agent `127.0.0.1:8004` 没法确认是否已热更新；本轮为了验证最新代码，临时起了 `127.0.0.1:8005`
  - 在 `8005` 上复跑 `session 67` 的 `把第20个志愿往前挪到第3个 -> 确认` 已通过
- 仍未收口的主线问题：
  - `session 66` 上 `还差几个怎么补更贴合这个方向` 在 `8005` 仍触发了 websocket `105s` 超时兜底，说明补齐/补位主链在这类会话上仍有性能长尾，不是单纯旧 session 污染
- 真实回归（更新后本地 agent `127.0.0.1:8004`）：
  - `session 66`
    - `帮我审查一下当前方案`：本次未再复现 105s 超时；约 45s 内完整返回，并附带 `review` workspace followup
    - `当前方案怎么兼顾这两个方向`：继续通过，仍明确基于“当前 45 个志愿里已有 14 个承接网络与新媒体/跨境电子商务”
    - `现在方案怎么样`：通过，走 `query_state`
    - `给我一份调整建议清单`：能返回，但本次观察到它主要依赖历史上下文整理，没有再次拉工具
    - `给我列出建议移除的志愿名称`：旧链路存在明显性能问题，曾跑到 `5 次模型请求 / 12 次工具调用 / 约 102s`，核心是 `analyze_adjustment` 只给了结构判断，没有给可落地名单，模型后续只能反复 `query_volunteer_plan`
- 新定位出的根因：
  - backend `planAdjustment/analyze` 当前只承接结构性规则；
  - `high_tuition / cooperative_program / edge_score` 这类审查提醒仍留在 `reviewState`，不会进入 `planAdjustmentState.suggestions`
  - 因此像“列出建议移除的志愿名称”这类请求，如果只看 `analyze_adjustment`，会拿到：
    - `summary_text=部分专业组主要依靠非意向专业托底`
    - `suggestion_counts = add/reorder/replace/remove 全 0`
  - 这不是纯 prompt 问题，而是主链 facts 不足
- agent 侧本轮补强：
  - `app/tools/planning_workflow_tool.py`
    - 为 `review_result` 和 `adjustment_analysis` facts 增加 `issue_hit_plan_examples / review_issue_hit_plan_examples`
    - 将 `reviewState.checks[].affectedVolunteerIds` 映射成可读的志愿示例（带学校/专业/档位/位置）
    - 同时补齐 `query_planning_state / query_planning_plan_overview / run_planning_review / analyze_planning_plan_adjustment / _rerun_review_and_fetch_state` 的 latest-profile merge，避免 mutation 后的复审摘要再次回退到旧 `explicitProfile`
  - `app/tools/plan_execution_tool.py`
    - `review_plan` 摘要现在会带“典型涉及 …”示例
    - `analyze_adjustment` 在 backend 没给结构化 suggestions 时，会回退引用 review 的受影响志愿示例，避免用户继续追问时只能靠模型盲查
    - `execute_plan_action` 对不完整 payload 增加结构化错误返回，不再因为模型少传 `stage` 直接抛 `ValidationError` 打崩整轮
    - 增加 recent result cache，用于 websocket timeout 后直接回填最近一次已成功完成的 `execute_plan_action` 结果
  - `app/service.py` / `app/server.py`
    - websocket timeout 时优先消费 recent `execute_plan_action` 结果，替代通用超时文案
    - compat 分支会保留 `planningWorkspaceAction` followups
  - `app/agent/chat_agent.py` + `skills/plan_chat/SKILL.md`
    - 增加约束：如果 `review_plan / analyze_adjustment` 已给出问题样例或受影响志愿，先直接基于这些 facts 回答；不要围绕同一问题把多个学校逐个 `query_volunteer_plan`
- 新增/更新单测：
  - `tests/unit/test_ws_compat.py`
    - timeout fallback + followup workspace action
  - `tests/unit/test_plan_execution_tool.py`
    - recent result cache
    - review summary 带 affected examples
    - analyze_adjustment 在零 suggestions 时回退到 review issue examples
    - execute_plan_action 对不完整 payload 返回结构化 error
- 本轮回归：
  - `./.venv/bin/pytest tests/unit/test_plan_execution_tool.py tests/unit/test_ws_compat.py -q`
  - `./.venv/bin/python -m py_compile app/tools/planning_workflow_tool.py app/tools/plan_execution_tool.py app/agent/chat_agent.py app/service.py app/server.py tests/unit/test_plan_execution_tool.py tests/unit/test_ws_compat.py`
  - 结果：`56 passed, 1 warning`
- 干净 history 验证（同 backend `session 66`，临时 history db）：
  - `给我列出建议移除的志愿名称`
    - 不再因 `execute_plan_action` 缺 `stage` 崩溃
    - 输出直接落到高收费 / 中外合作 / 非意向托底的具体志愿示例
    - usage 从此前真实 websocket 观察到的 `12` 次工具调用下降到 `4` 次工具调用
  - `先处理高收费和中外合作 -> 确认`
    - 现已能先产出可确认 preview，再执行 apply
    - apply 后复审摘要中的偏好保持为最新 `网络与新媒体 / 跨境电子商务`
    - 不再回退成旧的 `哲学类 / 金融学类 / 经济与贸易类`

### 2026-04-29 最新主线修复补充

- 已修正 `session 66` 上 review / adjustment 链路里的“方案承接事实和直接查询不一致”问题。
- 根因确认：
  - `collect_plan_context_inputs` 之前只读 backend `planning_state.profileState.explicitProfile`；
  - 但 `session 66` 的 backend `explicitProfile` 里仍是旧的 `哲学类/金融学类/...`，而真实 `userprofile.major_intent.level3` 已经有 `网络与新媒体/跨境电子商务`；
  - 导致 `collect_plan_context_inputs -> plan_next_action` 以及后续 `execute_plan_action(review/analyze_adjustment)` 的关系分析都被旧偏好污染。
- agent 侧本轮修复：
  - `app/tools/planning_workflow_tool.py`
    - 新增 `merge_planning_state_with_user_profile(...)`，用于把最新 `userprofile` 覆盖到只供对话分析使用的 `planning_state` 视图里；
    - 对专业偏好采用 specificity 优先：`level3 > level2 > level1`，仅用于当前对话分析/承接判断，不改 backend 持久化结构。
  - `app/tools/plan_context_tool.py`
    - `collect_plan_context_inputs` 改为并行读取 `planning_state + userprofile`，再构建上下文摘要；
  - `app/tools/plan_execution_tool.py`
    - `query_state / review_plan / analyze_adjustment / refresh_review_and_state` 读取状态时同步合并最新 `userprofile`，避免执行层再次退回旧 `explicitProfile`。
- 新增单测：
  - `tests/unit/test_plan_context_tool.py`
    - 覆盖“stale explicitProfile + latest level3 userprofile”时，`positive_majors` 与 relation lines 应展示 `网络与新媒体/跨境电子商务`
  - `tests/unit/test_plan_execution_tool.py`
    - 覆盖 `analyze_adjustment / review_plan` 执行层读取 merged state 后，`intent_relation` 不再回退到旧专业
- 本地最小回归：
  - `./.venv/bin/pytest tests/unit/test_plan_context_tool.py tests/unit/test_plan_execution_tool.py -q`
  - `./.venv/bin/python -m py_compile app/tools/plan_context_tool.py app/tools/planning_workflow_tool.py app/tools/plan_execution_tool.py tests/unit/test_plan_context_tool.py tests/unit/test_plan_execution_tool.py`
  - 结果：`40 passed, 1 warning`
- 真实结构化验证（`session 66`）：
  - `collect_plan_context_inputs` 现已返回：
    - `positive_majors = ["网络与新媒体", "跨境电子商务"]`
    - `承接情况：当前方案里较贴近的有14个，明显冲突的有0个`
  - `plan_next_action(action_family="analyze_adjustment")` 的 `context_summary` 已同步为上述新事实
  - `execute_plan_action(review_plan / analyze_adjustment)` 的 `facts.intent_relation.lines` 也已同步到 `14` 条承接，而不是旧的 `1` 条
- 真实 websocket 新增验证：
  - 使用更新后的本地 agent 服务 `127.0.0.1:8003`
  - `session 66`：
    - `当前方案怎么兼顾这两个方向`：已通过
      - 用户侧最终回复已明确基于“当前 45 个志愿里已有 14 个包含网络与新媒体或跨境电子商务”
    - `帮我审查一下当前方案`：**工具层结果已正确，但完整 websocket 仍会在最终模型整理回复阶段触发 105 秒超时**
      - 也就是说当前剩余问题已不再是数据错位，而是 review 场景最后一跳的性能/编排耗时
      - 结构化 `review_plan` 结果已正确，后续若继续优化，应优先看如何让 final answer 更快产出，或如何在超时前优雅降级到已有 tool summary

- 学校泛问法（如“广州工商学院怎么样”）在真实链路里可能自动扩展到学校介绍 + 录取方案 + 历年分数线，当前主要问题是**容易触发 105 秒超时兜底**。
- 现阶段先**记录为性能/编排过长问题**，不要因为这次超时就收缩学校相关能力边界；如果自动补充分数线/方案信息对业务回复更有帮助，能力先保留，后续再从耗时和调用顺序上优化。
- 本轮仅保留两个主线修复：
  - `pending intent` 的短确认由服务层直执，不再把纯“确认/可以/好的”再交回模型；
  - 专业比较后的指代式确认（如“那两个方向都先作为偏好”）补了基于近期对话上下文的本地恢复。
- 后续又补了两层与主线直接相关的边界修复：
  - `app/service.py` 不再把历史轮次里的旧 `plan` tool call 误算进当前 `intent` 预览，避免首轮偏好预览尾部被错误拼上“我还没有拿到可执行的调整预览”。
  - `app/tools/intent_state_tool.py` 给 `update_volunteer_intent_state(action="confirm")` 增加确认边界：如果当前轮开始前并没有 pending intent，就不能在“想学网络与新媒体”这种首轮表达里同轮直接生效，必须等用户下一轮明确确认。

### 2026-04-29 真实链路验证新增结果

- 使用更新后的本地 agent 服务 `127.0.0.1:8001` 继续验证 `session 65/66`。
- `session 65`
  - `想学跨境电商 -> 确认`：通过
    - 首轮成功进入专业偏好预览；
    - 第二轮 `确认` 已由服务层 direct pending intent apply，未再回模型绕一轮。
  - 同时定位到一处已修问题：
    - 因 `session 65` 历史里有旧 plan tool call，首轮 intent 预览尾部曾被误拼接 Plan 的“还没有拿到可执行预览”提示；
    - 现已修为只看当前轮 tool call，不再受旧历史污染。
  - 还定位到一处更关键的已修问题：
    - `想学网络与新媒体` 一度被模型在同轮里 `preview -> confirm` 直接生效，导致下一轮用户再回“确认”时提示“没有上一轮待确认的方案动作”；
    - 现已通过 `update_volunteer_intent_state` 的确认边界兜住。
- `session 66`
  - `想学网络与新媒体 -> 确认`：通过；
  - `网络与新媒体和跨境电子商务哪个更适合我 -> 那两个方向都先作为偏好 -> 确认`：通过；
    - 第二轮能够正确理解“两个方向”里的上下文指代；
    - 因 `网络与新媒体` 已存在，实际预览为“保留已记录的网络与新媒体 + 新增跨境电子商务”；
  - `直接生成一版方案 -> 确认生成 -> 帮我审查一下当前方案`：通过；
    - 生成后为 `45/45`；
    - 审查能给出风险/提醒和专业匹配度问题；
  - `当前方案怎么兼顾这两个方向`：通过；
    - 能基于已生成方案返回双方向兼顾的替换思路和区间建议。

## 2026-04-28 本轮已收口内容

### 2026-04-28 晚间补充进展

- `app/service.py`
  - 已移除 direct pending plan confirmation 对旧 `planEditCache` 的额外阻塞；
  - 现在只要当前 session 确实有 `pending_plan_action`，用户回复“确认”就直接走 apply，不再因为陈旧 intent cache 回退给模型。
- `app/tools/planning_workflow_tool.py`
  - `remove_planning_ordered_items()` 不再按“请求过就算删掉”汇总；
  - 现在会按最终 after-state 判断是否真的移除；
  - 若 `draft/remove` 后目标还残留，会自动 fallback 到 `draft/ban`，再重排并重新核对最终状态；
  - 若 fallback 后仍残留，会明确报“仍保留的志愿”，不再假成功。
- `app/tools/plan_orchestration_models.py`
  - 增加 `intent_relation` 同义值归一化；
  - 已把真实线上跑出来的 `match` 归一到 `support`，避免 `execute_plan_action` 因 schema 校验直接崩掉。
- `app/tools/plan_execution_tool.py`
  - `replace_units` 在“没找到新增候选”之外，又补了一类专业组计数说明：
  - 如果补入结果提示“匹配到了候选，但当前方案数量没有增加”，会额外说明这里统计的是方案项/专业组数量，组内专业替换时总数可能不变，不等于替换失败。
- 新增/更新单测：
  - `tests/unit/test_chat_service_history_persistence.py`
    - `test_chat_service_directly_applies_pending_replace_on_confirm_even_with_stale_intent_cache`
  - `tests/unit/test_planning_workflow_tool.py`
    - `test_remove_planning_ordered_items_falls_back_to_ban_when_target_still_remains`
    - `test_remove_planning_ordered_items_reports_lingering_target_after_ban_fallback`
  - `tests/unit/test_plan_execution_tool.py`
    - `test_execute_plan_action_normalizes_intent_relation_match_alias`
    - `test_execute_plan_action_replace_with_matched_candidates_but_no_count_increase_explains_unit_total_semantics`
- 最新回归：
  - `./.venv/bin/pytest tests/unit/test_plan_execution_tool.py tests/unit/test_planning_workflow_tool.py tests/unit/test_chat_service_history_persistence.py -q`
  - `./.venv/bin/python -m py_compile app/tools/plan_orchestration_models.py app/tools/plan_execution_tool.py app/tools/planning_workflow_tool.py app/service.py`
  - 结果：`118 passed, 1 warning`

### 2026-04-28 晚间真实链路验证

- 使用本地 `ChatService + 本地 backend` 继续对 `session 61` 做端到端验证。
- 验证 1：
  - 输入：`把广西师范大学的统计学换掉`
  - 结果：当前主链会先追问“换成什么方向”，不会直接生成 replace preview；
  - 这条链路没有误改状态，但也说明如果用户没给 replacement scope，当前产品行为仍是追问而不是直接预览。
- 验证 2：
  - 输入：`把广西师范大学的统计学换成计算机类` -> `确认`
  - 第一轮能生成 replace preview；
  - 第二轮能 direct pending apply；
  - backend draft 最终确认 `62020261003653_62020262014501` 已不在 `广西师范大学006专业组` 下，`TARGET_STILL_IN_DRAFT=False`；
  - 这次不需要 `ban` fallback，说明正常 remove 链路在该 session 上已可工作。
- 同时在真实链路里确认了一个新的已修问题：
  - 模型曾产出 `intent_relation=\"match\"`，旧代码会在 `PlanActionPlan.model_validate(...)` 处直接抛错；
  - 现已通过 schema 归一化兜住。
- 仍建议下一轮继续观察：
  - 专业组内 replace 成功后，“补入结果”里如果提示“数量没有增加”，文案是否仍足够自然；
  - 对“换掉”但没给 replacement scope 的话术，是否需要继续从技能/提示词层提高一次性补全能力。

- `app/agent/chat_agent.py` 已移除对 `extract_city_intent / extract_negative_city_intent / extract_major_intent / extract_negative_major_intent / extract_school_intent` 的无用导入，不再通过模块 import side-effect 暴露低层 extractor。
- `tests/unit/test_chat_agent_tools.py`、`tests/unit/test_city_intent_tool.py` 已删除这类只校验 `chat_agent` 模块是否“顺手导入了内部工具”的旧断言，改为围绕真正的 tool registration surface 回归。
- 清理了本地回归留下的临时文件 `chat_history.db`。
- 最新回归已通过：
  - `./.venv/bin/python -m py_compile app/agent/chat_agent.py app/tools/intent_preview_tool.py app/tools/intent_state_tool.py app/tools/plan_execution_tool.py app/tools/plan_orchestration_tool.py app/service.py app/server.py examples/dialog_regression_runner.py`
  - `./.venv/bin/pytest tests/unit/test_chat_agent_tools.py tests/unit/test_city_intent_tool.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_plan_execution_tool.py tests/unit/test_plan_orchestration_tool.py -q`
  - 结果：`262 passed, 1 warning`

## 2026-04-28 业务链新增进展

- `session 57` 的“想学网络与新媒体”问题已重新定位：
  - 不是候选池或当前方案里“匹配不到网络与新媒体”；
  - 真实 backend state 里既有 `上海建桥学院第01组-网络与新媒体`，也已经在 `orderedPlanState` 中；
  - 问题出在 `intent_relation_tool` 生成辅助分析时，示例沿用了原始顺序，没优先展示用户已明确偏好的地区，导致上海相关样例被埋得太后。
- 已修：
  - `app/tools/intent_relation_tool.py`
    - 为 `currentPlanFit` / `currentPlanConflict` / `candidateOpportunity` 增加仅展示层的排序；
    - 排序优先参考 `explicitProfile` 中已有的地区、学校、专业正负向偏好，其次再看 `preferred`、冲稳保、`finalScore`；
    - 只改变展示顺序，不改变候选池、方案状态或工具执行逻辑。
- 新增单测：
  - `tests/unit/test_intent_state_tool.py`
    - `test_enrich_plan_relation_analysis_prioritizes_fit_examples_by_existing_region_preferences`
    - `test_enrich_plan_relation_analysis_prioritizes_candidate_opportunities_by_existing_region_preferences`
- 本轮回归已通过：
  - `./.venv/bin/pytest tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py -q`
  - `./.venv/bin/python -m py_compile app/service.py app/tools/intent_relation_tool.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py`
  - 结果：`147 passed, 1 warning`

- `replace_units` 之前的核心问题已从“确认链断裂”收敛为更具体的“preview 过早认为可确认”：
  - 旧行为：只要 `plan_next_action/execute_plan_action` 拿到文本形式的 `volunteer_ids`，就可能返回 `preview_only` 并留下 pending。
  - 结果：即使当前方案里还没成功定位到真实志愿，回复尾部也会出现“确认后执行”，形成假确认。
- 已修：
  - `app/tools/plan_execution_tool.py`
    - `replace_units` 在 `preview` 阶段先解析当前方案里的真实志愿引用；
    - 没解析到时直接返回 `error + needs_volunteer_selection`，不再产出可复用 pending。
  - `app/tools/plan_query_tool.py`
    - 增强方案内局部命中匹配，支持“学校名 + 专业名”跨字段组合匹配；
    - 支持去掉 `006专业组` 这类中间层后再匹配。
- 新增单测：
  - `tests/unit/test_plan_execution_tool.py`
    - `test_execute_plan_action_replace_preview_requires_resolved_refs_before_confirmation`
  - `tests/unit/test_chat_service_history_persistence.py`
    - `test_extract_pending_plan_action_ignores_replace_preview_error_result`
  - `tests/unit/test_plan_query_tool.py`
    - `test_matches_query_supports_school_major_combined_lookup_across_group_name`
    - `test_query_volunteer_plan_matches_school_and_major_across_group_name`
- 本轮最小回归已通过：
  - `./.venv/bin/python -m py_compile app/tools/plan_execution_tool.py app/tools/plan_query_tool.py`
  - `./.venv/bin/pytest tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py -q`
  - 结果：`110 passed, 1 warning`
- direct validation（当前仓库代码直接跑 `ChatService.handle_message`，临时 history db）：
  - 负例：`把广西师范大学的生物科学换掉`
    - 第一轮不再留下假 pending，也不会再补“确认即可执行”。
    - 第二轮 `确认` 仍会明确说明当前没定位到目标志愿，继续要求用户给出准确目标。
  - 正例：`把广西师范大学的工业设计换掉`
    - 第一轮已能首轮命中 `广西师范大学006专业组-工业设计`，并生成 preview + pending。
    - 第二轮 `确认` 能直接 apply，返回替换结果并刷新 followups。
- 同时确认了一条旁路线索：
  - `gaotu-assistant-backend` 里的 `VolunteerFilterChain.filterMajors()` 确实把 `isMajorFiltered()` 调用注释掉了；
  - 但用户已明确表示“那个目前应该没用到 / 不用修复”，所以这轮未动后端该链路。

## 2026-04-28 换 thread 前最新状态

用户最新口径需要优先沿用：

- 模型可以自然输出标题、Markdown、列表、表格、长篇分析。
- 让用户选择、多选菜单、下一步选项本身没有问题，不要作为错误修复。
- 需要兜底的是严重体验问题：训斥/拒答、内部词暴露、压迫式“必须/没有第三个选项/不再回应”、以及承诺“确认即可执行”但实际没有 pending action。
- 之前“不让自动长篇分析”主要是为了避免污染会话里模型输出生硬、多路线强迫选择、偏离工具事实；现在判断应回到未污染新会话做用户层验证，不把长篇本身当问题。
- 后续 agent 层涉及用户流程的改动，都要尽量从用户对话层面触发验证，优先创建干净新会话验证，不只本地调工具。

当前代码改动已进行但尚未完成最终验证：

- `app/service.py` 已把 Plan 样式兜底收窄为只处理严重表达，不再拦普通 `方案A/方案B`、`回复 A 或 B`、`选哪个` 这类普通选择提示。
- `app/agent/chat_agent.py` 已调整 prompt：允许小标题、列表、表格、长篇分析和自然下一步选项；禁止的是压迫式/训斥式口吻。
- `examples/dialog_regression_runner.py` 已同步收窄 style banned list，并保留 `--response-timeout`。
- `app/server.py` 仍保留 websocket `handle_message` 105 秒超时兜底，避免用户一直收不到 end 包。
- `tests/unit/test_chat_service_history_persistence.py` 里还有旧断言需要继续改：旧测试仍把普通菜单/方案 A-B 当作应删除内容，下一轮要改成“菜单保留，严重词删除”。
- `tests/unit/test_chat_agent_init_profile.py` 也需要跟最新 prompt 文案同步。

下一轮先做：

1. 更新上述旧单测，使其符合“用户选择可以保留”的最新口径。
2. 跑 `./.venv/bin/pytest tests/unit/test_chat_agent_init_profile.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_mainline_dialog_scenarios.py -q`。
3. 跑 `./.venv/bin/python -m py_compile app/service.py app/server.py app/agent/chat_agent.py examples/dialog_regression_runner.py`。
4. 再创建或复用干净新会话做用户对话层验证，重点验证长篇/菜单不会被误拦，且严重话术不会出现。
5. 继续定位两个主线问题：`replace_units` 确认链断裂，以及后端生成方案漏过滤初始负向专业。

当前不要误提交的无关未跟踪文件：

- `enroll_impl/`
- `kimi_test.py`
- `test_batch_mapping.py`

## 当前目标

把志愿填报对话能力做成可用产品，而不是堆规则。当前主线是从用户使用路径出发，打通 Explore、Intent、Plan 三层能力：

- Explore：回答用户“我适合什么方向”“某个方向适不适合我”“有哪些机会可看”，先做个人适配分析，再结合方案和候选机会。
- Intent：把用户表达的偏好/要求沉淀到当前状态，但不把普通探索问题误当成意向修改。
- Plan：围绕方案查询、分析、调整、审查、重排、补偿形成稳定链路，用户确认前不要擅自改工作台。

## 2026-04-28 场景验证进展

本轮按用户要求使用后端正式接口创建新会话，再通过 agent websocket 做用户对话层验证，不只本地调工具。

### 新会话创建

- 通过 `POST /gaotu-assistant-bot/chat/1/session/create` 创建测试会话。
- 湖北物理组第一次创建失败：
  - `batch.code=14` 返回 `未查询到批次信息`。
  - 改用批次查询接口确认湖北物理本科批为 `code=01` 后，创建进入全量志愿阶段，但上游返回 `当前策略已失效，请刷新页面`。
- 后续改用本地历史验证过的甘肃物理本科批 payload 创建成功：
  - session 60：`469分/甘肃/物理.化学.生物`
  - session 61：同类干净会话，用于继续验证主线流程。

### 已验证通过的点

- `session 61` 上 “计算机科学与技术适合我吗” 能正常走 Explore 问答，约 50 秒内返回，不再复现旧的 120 秒 websocket 无响应。
- “不想学土木工程” 能识别为负向 Intent 预览，没有再出现“画像/加入画像”表达。
- 负向 Intent 预览会发 candidate 工作台 followup，确认后能写入当前报考参考信息。
- “直接生成一版方案” 能走 Plan 主链：`collect_plan_context_inputs -> plan_next_action -> execute_plan_action`，先给预览，用户确认后生成方案。
- 生成完成后会返回 ordered/review 工作台 followup。
- “方案有了么” 能重新读取当前 plan 状态，返回当前 45 个排序志愿、冲稳保分布、风险/提醒数量。
- “当前方案对计算机方向承接怎么样” 能查询当前方案和候选，给出计算机相关数量、档位分布和注意点。
- “帮我审查一下当前方案” 能触发 review，并刷新 review 工作台。

### 已复现的问题

1. **初始负向专业没有完全过滤到生成方案**

   session 61 初始创建时已带 `unacceptableMajors=[土木工程, 生物科学]`，但生成后的排序方案仍出现：

   - `广西师范大学006专业组-生物科学...`，保档。

   说明生成方案或后端筛选链路没有完全把初始负向专业作为硬过滤，至少在专业组/组内专业场景下仍可能漏入。审查阶段能识别冲突，但生成阶段没有避免。

2. **替换预览后确认链断裂**

   用户说“把广西师范大学的生物科学换掉”后，模型给出了替换预览，并提示“回复确认即可执行替换”。但下一轮用户回复“确认”时，系统返回：

   - “我这边没有上一轮待确认的方案动作。”

   说明这一类 `replace_units` 预览没有稳定留下 pending plan payload，或者模型生成的预览没有经过可复用的 preview tool result。后续需要查 `plan_next_action` / `execute_plan_action` / `ChatService.pending_plan_action` 的衔接。

### 本轮代码侧调整

- 新增 `examples/dialog_regression_science_cases.json`：40 个偏理工场景案例，覆盖计算机、软件、数据、AI、电子信息、自动化、机械、土木、材料、生医、选科限制、负向专业、plan preview/apply/review 等。
- 更新 `tests/unit/test_mainline_dialog_scenarios.py`：校验 40 个理工案例的数量、flow、coverage tags。
- `app/server.py` 增加 websocket 服务层超时兜底：
  - `handle_message` 超过 105 秒时返回自然兜底文案，避免用户一直等不到 end 包。
  - 这是严重体验问题兜底，不改变主链路模型/tool 编排。
- `examples/dialog_regression_runner.py`：
  - 增加 `--response-timeout`。
  - 移除旧的“非空行超过 8 行失败”和 Markdown 表格 `|` 失败规则，适配当前“模型可自然使用标题/Markdown”的要求。
  - 多选菜单、下一步列表、Markdown 表格不作为错误；只检查强迫式决策、训斥式拒答、内部词暴露等严重体验问题。

### 已跑验证

- 单测：
  - `./.venv/bin/pytest tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_chat_agent_init_profile.py -q`
  - 结果：`15 passed, 1 warning`
- py_compile：
  - `./.venv/bin/python -m py_compile app/server.py examples/dialog_regression_runner.py`
  - 结果：通过。

### 下一步优先级

1. 先修 `replace_units` 预览后确认链断裂：用户看到“确认”就应能执行上一轮预览，不应丢 pending action。
2. 再查初始负向专业没有过滤进生成方案的问题：重点看后端生成候选/排序时是否只按专业类过滤，未覆盖专业组内 level3。
3. 继续用新会话做对话层回归，不只跑工具：
   - “想学软件工程” -> “确认” -> “当前方案怎么调”
   - “不想学生物科学” -> “把冲突换掉” -> “确认”
   - “补几个稳一点的计算机方向” -> preview -> confirm
   - “重排一下解决倒挂” -> preview -> confirm -> review

## 已确认的架构原则

- 主链路使用 `ChatAgent + skill + tool`。模型负责理解语义、编排技能、组织最终回复。
- 尽量不要新增正则、字符串硬匹配、固定回复模板。只有状态变更、执行动作、稳定性兜底可以保留硬规则。
- tool 只提供业务事实、状态读取、状态执行、候选/方案数据分析，不负责最终面向用户的话术组织。
- 最终回复由大模型生成，可以使用轻量 Markdown，避免卡片化、模板化、碎片化。
- Explore、Intent、Plan 的语义边界要清晰。探索不等于意向修改，询问适不适合不应该直接写入意向缓存。
- 用户侧说法尽量使用“偏好/要求”，不要使用“约束”等理解成本高的词。
- 对话里不要说“左侧/右侧”，统一说“对话框/工作台”，兼容移动端。
- 工作台内容刷新要克制：审查结果可以自动刷新；硬要求采纳后可以联动；普通探索和候选查询不应自动改工作台。

## 关键状态和数据约定

- PlanningState 是方案侧状态入口，后续应显式包含目标志愿数量，用于判断方案数量是否不足。
- 用户画像和 latent profile 是用户态事实输入，Plan 分析和调整建议需要读取当前画像/状态，而不是只看初始画像。
- intent 已经作为状态存在，不需要在 Plan 层另起一套 intent 结构；Plan 工具应把已有画像/偏好/要求作为输入事实使用。
- 专业组模式下，候选和方案都要以专业组为主要单位，但组内专业仍要参与匹配、解释和安全垫提醒。
- 每个专业组理论上有组录取率；如果组内专业与用户意向差异较大，需要在提醒里体现。
- 数量上限是不能超过；数量不足可能是专业组天然现象，不应作为错误提醒。

## 当前重点待修问题

### 1. session 57：网络与新媒体候选漏匹配

用户说“想学网络与新媒体”后，系统回复“候选库里暂时没看到特别明显的补位机会”，但用户确认候选里有 `上海建桥学院(01)` 的 `网络与新媒体`。

高度疑似问题点：

- `app/tools/intent_relation_tool.py`
- `_item_matches_any_intent()` 只看了候选顶层字段，可能没有递归看专业组内的 `majorItems`、`majorList` 或类似嵌套字段。
- `_format_candidate_brief()` 可能也只展示顶层专业，导致专业组内命中的专业没有进入候选机会描述。

下一步应先查看 session 57 的 planningState/candidate item 结构，确认 `上海建桥学院(01)` 和 `网络与新媒体` 的实际字段，再修匹配和展示。

预期修复：

- 专业 intent 匹配要覆盖专业组内所有专业项。
- 候选机会摘要应能输出类似 `上海建桥学院(01)-网络与新媒体`。
- 增加单测：嵌套专业项命中时不能返回“候选里暂时没看到机会”。

### 2. session 57：回复变成一坨文字

当前回复示例：

> 网络与新媒体是个挺适合你的方向，既能发挥英语优势，也契合当下数字内容产业的需求。 我整理一下这个想法。你想增加的专业意向： 网络与新媒体。 跟当前方案的匹配情况。

问题：

- Markdown/段落结构没有稳定保留。
- tool 输出和 ChatAgent 改写之间出现碎片句。
- `intent_response_tool.format_text_sections()` 仍可能输出普通标题，不如 Explore 那边稳定。

下一步：

- 让 Intent 侧也使用轻量 Markdown 章节标题。
- ChatAgent 对 Intent 回复加约束：保留结构，不要压平成碎片段落。
- 前端 Markdown 样式已调整过，但还要以真实对话验证。

### 3. Explore 和 Intent 边界仍需继续压实

历史问题：

- “体制内适不适合”曾被写入 `planEditCache`。
- “我适合什么方向”曾误走 `analyze_volunteer_intent_change`。

已确认设计：

- 职业、学校、专业、地域等主题探索应走对应 skill。
- 用户明确表达“想要/不要/加上/去掉/必须/不考虑”时才进入 Intent 状态变更链路。
- 探索阶段可以引导用户是否要记为偏好/要求，但不要自动写入。

后续验证要重点覆盖：

- “体制内适不适合”
- “我适合什么方向”
- “网络与新媒体适合我吗”
- “我想学网络与新媒体”
- “不想去体制内”

### 4. Plan 动作链路仍要继续打透

历史出现过的问题：

- 增加志愿后工作台草稿/方案没有自动同步。
- 系统没有目标志愿数量概念，无法判断方案数量不足。
- 调整后没有稳定触发方案分析和审查。
- 专业组模式里回复“48 个志愿”但实际应表达为专业组/方案项，前端草稿也曾错位。

已确认方向：

- 用户直接说“加这个”“删掉这个”“换成北京的”“把某个往前放”，也要走分析、审查、建议、确认、执行链路。
- 执行前要给用户看影响，不要未确认就刷新工作台。
- 执行后应触发必要审查，并把工作台状态和审查状态同步清楚。
- `generate_plan`、`query_volunteer_plan` 等工具语义要和 `docs/plan_action_orchestration_design.md` 保持一致。

## 前端和工作台约定

- 工作区方案顶部只保留紧凑的一行：标签/状态 + 导出按钮。
- 有风险或提醒时才显示惊叹号；没有问题或提醒时不要显示。
- 警告/提醒清单应收进惊叹号 hover，不要单独铺开占空间。
- 初始进入的“系统初排”提示可以保留；用户手调后的长提示和建议区域应删除。
- 会话详情页应恢复老版本“会话列表”入口，不要变成侧边栏。
- 欢迎语要更自然，介绍“孙老师”能做什么和用户简要情况；快捷入口不要带具体城市/专业等可能违背用户偏好的默认指向。

## 重要文件入口

- Agent 主编排：`app/agent/chat_agent.py`
- Explore：`skills/explore_chat`、`app/tools/explore_direction_tool.py`
- Career 分析：`skills/career_path_chat` 只负责语义边界说明，运行时主入口是 `app/tools/intent_preview_tool.py::analyze_current_career_direction`
- Intent 状态与预览：`app/tools/intent_state_tool.py`、`app/tools/intent_preview_tool.py`、`app/tools/intent_response_tool.py`
- Intent/候选关系分析：`app/tools/intent_relation_tool.py`
- Plan skill：`skills/plan_chat`、`skills/plan_query`
- Plan 设计：`docs/plan_action_orchestration_design.md`、`docs/planning_agentize_design.md`
- PlanningState 设计：`docs/planning_state_full_design.md`、`docs/planning_state_overview.md`
- 前端对话展示：`gaokao-volunteer-pc/src/pageComponents/sessionDetail/MessageList`
- 前端工作台方案区：`gaokao-volunteer-pc/src/pageComponents/sessionDetail/Volunteer`
- Java 欢迎语/会话初始化：`gaotu-assistant-backend/src/main/java/com/ytell/salesbot/service/biz/ChatSessionBizService.java`

## 建议下一轮启动语

新会话可以从这里开始：

> 请从 `/Users/baiyang/git/zhiyuan/gaotu-zy-agent-v3/docs/next_session_handoff.md` 接续。先处理 session 57 “网络与新媒体”候选漏匹配和回复格式问题：确认 `上海建桥学院(01)` 在 planningState/candidate 中的字段结构，修复专业组内嵌套专业匹配与候选摘要展示，补充单测和真实对话回归。继续遵守“模型 + skill + tool，tool 给事实，模型生成最终回复，不新增硬编码模板”的原则。

## 回归测试建议

优先用真实会话做端到端验证，之前批量创建的 session 可用，污染明显的先跳过。

- Explore：我适合什么方向、体制内适不适合、网络与新媒体适合我吗。
- Intent：想学网络与新媒体、不想进体制内、想去北京、不要中外合作。
- Plan 查询：方案有了么、现在稳不稳、有哪些风险、保底够不够。
- Plan 动作：加一个北京的、删掉三亚学院、把某个学校往前放、换成更适合就业的。
- 工作台：审查后标签和惊叹号是否刷新；无提醒时惊叹号是否隐藏；未确认时是否没有擅自改工作台。
