# release-4.0.0 人工检查问题记录

## 2026-07-13 会话 11802969：上海候选查询与“更优先”调整链路不一致

### 上下文

- 当前环境已切到 4.0 新版 `zhiyuan_agent_direct` 链路。
- 会话用户画像：吉林考生，524 分，位次 19627，物化生，本科批，专业组模式；用户偏好中已有上海，专业偏好包括金融学类、经济与贸易类、外国语言文学类，策略为稳妥型。
- 用户连续表达：
  - “上海的有哪些”
  - “上海已经在优先看了吧”
  - “什么意思”
  - “更优先”
- 需要确认的问题不是单条回复措辞，而是当前框架在“查询已有候选/方案状态”和“把已有地域偏好进一步强化为可执行方案调整”之间是否闭环。

### 现象

1. 用户问“上海的有哪些”时，实际走了 `explore_topic`，回复给出了泛化的上海院校建议，没有基于当前候选池或当前方案回答。
   - 回复中出现了不在当前候选池内的院校，例如上海对外经贸大学、上海师范大学、上海海事大学。
   - 当前上海候选池实际为 `total=69`、`totalUnitCount=12`，院校基础集合包括：上海立信会计金融学院、上海外国语大学、上海应用技术大学、上海电机学院、上海商学院、上海工程技术大学、上海第二工业大学。
   - 当前方案中已有 4 个上海专业组：上海外国语大学第005组、上海立信会计金融学院第004组、上海立信会计金融学院第002组、上海立信会计金融学院第003组。

2. 用户继续问“上海已经在优先看了吧”时，没有调用查询工具，回复被 `unbacked_plan_confirmation_reply_guard` 改写为“这轮还没有生成可确认的调整预览，所以不会改动当前方案...”。
   - 这句话和用户当前问题不匹配。用户是在确认当前状态，不是在确认执行某个缺少 preview 的调整。
   - 后续用户问“什么意思”后，系统才通过 `query_plan` 正确回答当前方案中有 4 个上海条目。

3. 用户说“更优先”后，系统生成了 `preview_plan_action`，结构化结果为 `actionFamily=regenerate_order`，并带上 `filters.province=["上海"]`。
   - 用户确认后 pending apply 成功，workspace version 从 3 更新到 4。
   - 但实际方案变化很弱：候选池不变，50 个专业组集合不变，上海专业组数量仍为 4，且上海立信会计金融学院第003组从第 44 位移动到第 46 位，反而更靠后。
   - 当前看 `regenerate_order + province=上海` 更像保存/沿用候选视图筛选条件并重排既有方案，不等价于“增加上海覆盖”“替换为更多上海候选”或“把上海专业组显著前移”。

### 初步判断

- 这不是单纯部署问题。路由已经进入 4.0 新链路，但工具选择和动作语义没有覆盖这类真实诉求。
- “上海的有哪些”在已有候选池和方案存在时，应优先被识别为候选/方案范围查询，而不是泛知识探索。
- “上海已经在优先看了吧”属于状态确认，应查询当前方案或候选状态；当前 guard 对“确认类表达”的兜底过宽，误把状态确认拦成了执行确认防护。
- “更优先”被解析为 `regenerate_order` 后缺少可验证目标。用户真实意图更接近“强化地域偏好”，可能需要结构化为增加、替换、前移上海候选，或生成明确的调整目标与影响范围。

### 后续待确认

- 是否需要把“有哪些/有多少/现在有几个”类表达，在已有方案上下文中统一路由到 `query_plan` 或候选查询工具。
- 是否需要调整 `unbacked_plan_confirmation_reply_guard` 的触发条件，避免对状态确认、反问、追问解释类表达误触发。
- 是否需要重新定义 `regenerate_order` 的适用边界：它只能排序已有方案，还是允许基于偏好重新选取候选并改写方案。
- 对“更优先/更想去/多放一些/尽量安排”这类偏好增强表达，是否需要单独的结构化动作，例如 `boost_preference`、`add_or_replace_by_region`，并要求 preview 中展示新增、移除、前移数量。

## 2026-07-13 会话 11802969：方案不足后的“有没有可以补充进来的”回复不可读

### 上下文

- 用户先表达“不想学金融了”，系统生成并应用 `intent_change`，新增硬约束 `mustExcludeMajors=["金融学类"]`。
- 应用后当前工作方案从 50 个专业组变为 45 个专业组，目标仍为 50 个，冲稳保为 `冲=13`、`稳=14`、`保=18`。
- 用户随后问：“现在不够了 有没有可以补充进来的”。
- 这句话承接的是刚才移除金融后数量不足的问题，用户期望看到是否能补、能补哪些、补多少，或者直接进入补齐预览。

### 现象

1. 本轮回复先重复了上一段上海查询结果：
   - “当前正式方案有50个志愿，按‘省份=上海’命中4个志愿...”
   - 该内容和“现在不够了，有没有可以补充进来的”无关，造成用户看不懂当前回答在回应什么。

2. 本轮实际路由为 `zhiyuan_agent_direct`，工具调用记录只有 `review_plan`。
   - 回复后半段是审查摘要：“当前正式方案有45个志愿，风险1项，提醒5项...已整理6个处理方向...”
   - 它提到了“补足志愿数量”，但没有说明当前少 5 个，也没有列出可补入的专业组，更没有给出可确认的补齐卡片。

3. 后端 `fix-proposals` 其实已经生成了可执行的补齐建议：
   - `strategy=fill_missing_count`
   - `status=ready`
   - `proposalId=fp_a366aa8aa087f97e`
   - dry-run 结果：`45 -> 50`，新增 5 个专业组、24 条专业明细。
   - 建议补入的专业组包括：
     - 延边大学第058组
     - 吉林财经大学第015组
     - 吉林财经大学第014组
     - 延边大学第054组
     - 长春理工大学第009组
   - 但该建议存在 warning：吉林财经大学第015组含金融学、保险学，可能不符合刚采纳的“排除金融学类”约束。

### 初步判断

- 这里有两个问题叠加。
- 回复串入上海结果，是 direct tool return 渲染时把历史 `query_plan` 只读结果作为本轮 `review_plan` 的前置上下文组合输出；本轮日志里 `toolNameCounts` 只有 `review_plan=1`，所以这不是用户当前意图触发的上海查询。
- “有没有可以补充进来的”被处理成只读审查/处理方向，语义不算完全错，但回复没有消费后端 ready 的 `fill_missing_count` 结构化建议，导致没有形成用户可理解、可执行的补齐回答。
- 当前框架已具备后端补齐建议能力，但 4.0 对话层缺少“补齐数量缺口”这类 ready fix proposal 的展示和确认承接。

### 后续待确认

- direct tool return 渲染时是否必须只组合“本轮工具返回”，不能扫描完整历史工具返回。
- 对“现在不够了/少了/不满 50/能不能补/有没有可以补进来”的语义，是否应优先映射到数量缺口处理：
  - 只问可行性时，应展示当前缺口和可补候选明细。
  - 要求补入或上下文已明确需要处理时，应生成可确认的补齐预览。
- `fill_missing_count` ready proposal 展示时，需要把 warning 一并讲清楚：哪些补入项可能违反刚确认的排除条件，是否需要改用其他候选或放宽约束。

## 2026-07-13 生产回捞上下文小规模模拟：数量补齐、费用约束、地域优先和指定加入

### 上下文

- 样本来源：`assets/zhiyuan-production-dialogue-context-5000-20260709-090527.json`。
- 该资产来自 2026-07-09 回捞，扫描 5000 条会话，选中 200 条有意义对话上下文。
- 本轮先抽取 6 个高价值生产场景做本地 4.0 agent 小规模模拟：
  - `6332`：学费超 8000、补足 45、民办排除。
  - `6264`：补齐 50 且不要民办。
  - `4158`：过度排除后要求先补齐 45 个冲稳保志愿。
  - `5542`：指定浙江师范大学汉语言文学（师范）加入方案并放第一。
  - `6099`：按推荐系数排序，同时湖南院校更靠前，但不是只保留湖南。
- 回放方式：把生产 `planningState` 导入本地高号 session，通过本地 `18090/18091` WebSocket 发送单轮话术。该方式没有完整恢复 pydantic-ai 历史消息和志愿文件，因此确认执行失败、历史承接缺失不直接作为最终结论；优先记录首轮路由、首轮回复和卡片语义问题。

### 现象

1. `6332 / 剔除学费超8000的`
   - 历史生产回复曾返回“这轮信息还不够完整，不会改动方案”，但用户表达已经足够明确，应识别为“学费上限 8000/年”。
   - 当前 4.0 回放首轮已有进步：生成 `intent_change`，summary 为“学费预算：每年不超过 8000 元”。
   - 但确认后回复为“已采纳这次报考要求，但当前方案暂时没有重新调整成功，请稍后重新生成方案”。这说明它只把学费作为后续报考条件采纳，没有稳定承接“当前方案里剔除超预算并补位/重排”的动作闭环。

2. `6332 / 现在不够45个，补足45个`
   - 历史生产回复曾说“没有定位到要加入方案的具体候选志愿”，把结构性数量缺口误当成需要用户点选具体候选。
   - 当前 4.0 回放首轮生成了 `plan_generation / generate_plan` 卡片：“生成新的正式方案”。
   - 这个动作过泛。用户要的是在现有方案上补足到 45 个，应优先走 `fill_missing_count` 或数量补齐类 fix proposal，而不是泛化成重新生成方案。

3. `6264 / 再帮我补齐50个，不要民办的`
   - 当前 4.0 回放只抽取了“院校要求：不要：民办”的 `intent_change`。
   - 同一句里的“补齐50个”没有进入首轮可执行动作或组合预览。
   - 这是复合诉求拆解问题：一个句子同时包含硬约束和方案补齐动作，当前只保留了约束，丢失了数量补齐目标。

4. `6099 / 整体按推荐系数重新排序，尽量将湖南省院校排在相对前面的位置，不是只保留湖南`
   - 当前 4.0 回放生成 `plan_mutation / sort_ordered_plan`，summary 为“按推荐系数（综合分）重新排序当前方案”。
   - 回复没有体现“湖南省院校相对前置”的软目标，也没有说明“不是只保留湖南”已经被理解为非排他约束。
   - 这和会话 `11802969` 的“上海更优先”类似：当前 `sort/regenerate_order` 对地域偏好增强缺少可验证语义目标，容易只做普通排序。

5. `5542 / 把浙江师范大学的汉语言文学（师范）加入方案，放在第一个`
   - 当前 4.0 回放回复为候选里未唯一匹配，要求用户确认专业、批次、加入方式。
   - 用户已经给出学校、专业和目标位置，仍无法形成加入预览。
   - 需要确认这是候选池确实无该项，还是实体解析/候选检索能力不足。如果候选池无该项，回复也应明确“当前可选候选里没有，所以不能直接加入”，而不是追问批次和加入方式。

6. `6332 / 为什么后面的志愿没有26年的招生计划`
   - 历史生产回复解释为“2026 年招生计划还没有正式发布，目前展示的是 2025 年及之前数据”。
   - 这与当前约定冲突：智能填报模式下应使用 2026 年，模拟填报下使用 2025 年。
   - 年份展示逻辑和对话解释需要对齐模式，不应泛化回答“2026 未发布”。

### 初步判断

- 当前 4.0 agent 对单一硬约束的识别已有改善，例如“学费超 8000”能结构化为 tuition budget。
- 更严重的问题集中在复合动作和可执行闭环：
  - “补齐数量 + 不要民办/费用限制”没有形成一个能同时表达约束和补齐目标的预览。
  - “地域更优先/相对靠前，但不是只保留”缺少 `boost preference` 类动作语义，只退化为普通排序。
  - “指定学校专业加入并放到某位置”在候选定位失败时缺少清晰边界和替代候选建议。
- 生产上下文里还有明显的模式解释问题：招生计划年份不能脱离 `prepareType` 回答。
- 本轮确认执行阶段有回放环境噪音：部分 pending 确认后 `pendingStatusAfterConfirm=None`，可能和本地回放卡片 `message_id`、历史消息未完整恢复有关。文档中暂不把这些确认失败当作最终业务缺陷，只记录首轮语义和回复质量问题。

### 后续待确认

- 是否为“补齐到 N 个/不够 N 个/剩下太少”建立明确的一等 action family，而不是依赖 `generate_plan` 或用户点选具体候选。
- 复合诉求是否需要在 preview 层支持“先采纳约束，再按约束补齐当前方案”的组合卡片，避免只采纳条件不调整方案。
- 地域/院校/专业“更优先、往前放、相对靠前、不要只保留”是否需要可验证指标，例如前移数量、目标区域新增/前移专业组数、排序权重说明。
- 指定加入失败时，回复应区分：
  - 候选池确实没有，不能加入。
  - 候选池有多个近似项，需要用户选择。
  - 候选池有唯一项，但当前解析没命中，应修复解析或检索。
- 年份解释统一改为基于 `prepareType` 和实际 `examYear/dataFreshnessState.examYear`，不能用泛知识回答。

## 2026-07-13 生产回捞上下文 40 条首轮扩大回放

### 上下文

- 回放对象：`assets/zhiyuan-production-dialogue-context-5000-20260709-090527.json` 中自动抽取的 40 个高价值生产上下文。
- 回放方式：临时 first-turn-only 脚本 `/tmp/zhiyuan_context_first_turn_replay.py`，只导入生产 `planningState/userScoreDetail/userProfile`，只发送首轮用户话术，不做确认执行。
- 输出文件：
  - `/tmp/zhiyuan-production-context-first-turn-40-20260713.json`
  - `/tmp/zhiyuan-production-context-first-turn-40-20260713.md`
- 自动标签结果：40 条中 `issue=26`、`ok=14`。其中有少量误报，例如“如果不够600分要不要复读”被关键词误识别为“补齐数量”；也有少量漏报，需要人工复核。

### 主要现象

1. 明确方案动作没有形成 pending。
   - `4158`：“请调整，对于地域，请将广东省内优先级别放到最低”
     - 回复：“没有识别到明确的报考要求”
     - 问题：用户是明确的地域降权/优先级调整，不应被当成无要求。
   - `6332`：“移除学费超8000的院校”
     - 回复：“还没有唯一定位到要调整的方案项：学费不少于8000元/年。请说明学校、专业或第几个志愿。”
     - 问题：费用阈值是结构化过滤条件，不需要用户点选具体志愿。
   - `4768`：“删除有单科成绩限制的院校专业”
     - 回复：“还没有唯一定位到要调整的方案项：admission_limit。”
     - 问题：暴露内部 code，且没有走限报/单科限制的结构化移除或审查项处理。
   - `4732`：“排除厦门大学的马来西亚分校”
     - 回复被兜底为“这轮还没有生成可确认的调整预览...”
     - 问题：这是明确排除学校/校区，不应触发 unbacked preview guard。

2. 复合诉求只抽取一部分。
   - `6264`：“再帮我补齐50个，不要民办的”
     - 只生成“院校要求：不要：民办”的 `intent_change`，丢失“补齐50个”。
   - `4485`：“学费不超过三万的都可以考虑，把好考公的专业放在前面，重新调整一下志愿方案”
     - 只生成“学费预算：每年不超过30000元”，丢失“好考公专业前置”和“重新调整方案”。
   - `5591`：“地域放宽...专业放宽...接受民办本科”
     - 只生成地域要求，丢失专业放宽和接受民办作为取舍。
   - `4098`：“学校地域在福建，排除烹饪专业，学费在1.3万左右，以学校录取概率高排序完整40个志愿”
     - 回复“这轮处理没有完成，请稍后重试”
     - 问题：多条件完整方案生成没有结构化承接。

3. “补齐数量”仍不稳定。
   - `6093`：“补全45个专业组，要求不限于我所说的那几个，同属于一个大类就行，最好是湖南省的大学”
     - 生成 `plan_generation/generate_plan`，summary 只有“生成新的正式方案”。
     - 问题：缺少“补全45”“同大类”“湖南优先”的可验证目标。
   - `7239`：“编入二本王牌专业补足45个专业”
     - 只走 `review_plan`，没有 pending。
     - 问题：明确“编入/补足”被误路由成只读审查。
   - `4659`：用户粘贴了“本省保底志愿数量不足...处理前预览...补入1组...”
     - 回复让用户再选择“希望怎么处理”，没有形成预览。
     - 问题：已有结构化处理方向时，应能生成或恢复对应补齐预览。

4. 地域/排序软目标容易退化。
   - `6099` 小样本已见：“湖南院校相对前面，不是只保留湖南”退化为普通推荐系数排序。
   - `6750`：“不是只保留江苏和浙江，其他我勾选的城市也要有，只是江苏和浙江优先”
     - 生成“地域要求：要：江苏、浙江、长三角”。
     - 问题：把软优先近似成地域正向要求，没有保留“其他勾选城市也要有/不是 only_keep”的语义。
   - `2378`：“不用排除民办但是优先考虑公办”
     - 生成“院校要求：要：公办”。
     - 问题：把软优先公办变成硬要求，可能错误压缩候选。

5. 专业层级 only_keep/exclude 有语义冲突。
   - `3367`：“能源动力类专业中只保留新能源科学与工程专业”
     - 生成“专业要求：要：新能源科学与工程；不要：能源动力类、新能源科学与工程”。
     - 问题：同一实体同时出现在正向和负向，说明“类中只保留子专业”的层级语义没有正确表达。
   - `2752`：“严格只保留临床医学...用这个策略”
     - 生成泛化 `regenerate_order`，没有形成明确 only_keep 临床医学的约束/方案预览。

6. 指定候选加入/替换的定位能力不足。
   - `6014`：“加入山西大学{除考古学} 山西财经大学 山西师范大学 山西大同大学的冲稳保”
     - 回复要求补充专业方向。
     - 问题：用户指定学校集合和排除项，至少应查询候选中这些学校的冲稳保机会，而不是只追问。
   - `5686`：“把录取率极低1%的冲换成更实际的机会，添加江西农业大学、江西中医药大学、景德镇陶瓷大学”
     - 回复要求说明要移出的具体志愿。
     - 问题：用户已经给出旧项选择器“录取率极低1%的冲”和新增学校方向，应能生成替换预览或候选不足说明。

7. 回复质量和内部边界问题。
   - `2483`：用户问专业组里 28 个专业为什么只选 6 个，是否考虑调剂问题。
     - 回复先说“暂时没有拿到可逐条扫描的方案明细”，又接“继续看审查结果”，没有回答专业组内选专业/调剂风险机制。
   - `4169`：“江苏科技大学与俄罗斯高校合办的光电信息科学与工程、能源与动力工程，排除”
     - 回复“这轮处理没有完成，请稍后重试。”
     - 问题：明确中外合作/具体学校/具体专业排除失败，且没有可操作解释。

### 初步判断

- 当前最严重的不是单一实体识别，而是“复杂真实话术 -> 结构化动作”的覆盖不足。
- 主要缺口集中在：
  - 复合诉求拆分与合并预览。
  - 数量补齐作为一等动作。
  - 软偏好和硬约束的区分。
  - 专业层级 only_keep 的语义表达。
  - 审查项/特殊限制/费用阈值作为结构化过滤条件的定位。
  - 指定候选加入/替换时的候选检索与失败边界。
- 自动抽样也暴露了回放选择器问题：部分生产消息可能是用户粘贴的历史回复或长上下文，需要后续筛掉纯 assistant-style 文本，避免误判。

### 后续待确认

- 继续扩大前，需要把回放样本选择器改成更严格的用户真实诉求抽取，过滤欢迎语、长助手回复、纯咨询类非方案动作。
- 下一批建议按类别定向抽样，而不是纯关键词：
  - 10 条数量补齐。
  - 10 条费用/民办/中外合作/限报。
  - 10 条地域软优先与“不是只保留”。
  - 10 条指定学校/专业加入或替换。
  - 10 条专业层级 only_keep/exclude。

## 2026-07-13 生产回捞上下文第二批 50 条定向首轮回放

### 上下文

- 回放对象仍为 `assets/zhiyuan-production-dialogue-context-5000-20260709-090527.json`。
- 本轮在临时脚本 `/tmp/zhiyuan_context_first_turn_replay.py` 增加严格抽样：
  - 排除上一批 40 条已跑过的 `sourceSessionId`。
  - 过滤欢迎语、明显助手回复、采纳卡片文案、过长粘贴文本。
  - 按问题类型均衡抽样，每类最多 10 条。
- 输出文件：
  - `/tmp/zhiyuan-production-context-first-turn-targeted-50-20260713.json`
  - `/tmp/zhiyuan-production-context-first-turn-targeted-50-20260713.md`
- 自动标签结果：50 条中 `issue=20`、`ok=30`。
- 人工复核发现自动 `ok` 有明显漏报：只要生成了 pending card，脚本容易判为 ok，但很多卡片只承接了部分意图，或把动作降级成普通 intent。

### 主要现象

1. “数量补齐”依然不是稳定的一等动作。
   - `4958`：“补足志愿数量 排除少数民族类”
     - 只生成“专业要求：不要：民族学类”，丢失“补足志愿数量”。
   - `7355`：“补齐剩下的 10 个志愿，让方案更完整”
     - 生成 `generate_plan`，没有表达“现有方案补 10 个”的目标。
   - `4838`：“补齐二本好就业好升学的专业院校”
     - 走只读 `review_plan`，未生成补齐预览。
   - `4762`：“可以加一些河北和山东的院校，帮我补足48个专业组”
     - 只生成地域 intent，丢失补足 48 个。
   - `7457`：“我叫你给我增加保底志愿啊 为什么审核过后还是有这个问题啊”
     - 仍只读审查，没有承接“增加保底志愿”的修复动作。

2. 结构化过滤条件有时仍被当成“需要唯一定位方案项”。
   - `4230`：“去掉民办学校”
     - 回复“还没有唯一定位到要调整的方案项：院校性质=民办”。
     - 民办是全局结构化过滤条件，不应要求用户指出具体学校或第几个志愿。
   - 第一批已出现同类问题：学费超 8000、单科成绩限制、录取率阈值、校区/分校排除。
   - 说明问题不是单个实体词表，而是框架仍把一部分“按属性批量过滤当前方案”的请求降级成单项定位。

3. 多条件方案生成/重排容易只保留一个条件。
   - `4489`：“重新生成48个专业组志愿，只保留法学、会计学、汉语言文学、财务管理、审计学，排除英语和文物与博物馆学，学费2万以内，优先级法学>会计>汉语言>财务管理>审计学”
     - 直接回复“这轮处理没有完成”。
   - `4472`：“专项资格，不学汉语言文学，不当老师不考虑师范专业，不考虑民办和中外合办，重新生成志愿表”
     - 只抽取“不要汉语言文学、师范”，丢失专项资格、民办、中外合办和重新生成动作。
   - `5609`：“地域陕西/西安为主，公办一本，好就业工科，排除民办、偏远、基础学科”
     - 直接失败。
   - `7003`：外语是日语、接受高收费和中外合办、除西藏外地区都可、排除广播电视编导/学前教育/护理/小语种
     - 输出“要日语；不要日语”等冲突，且丢失高收费/中外合办接受、地域约束和多个排除项。

4. 地域软优先/排序目标仍会退化。
   - `6099`：“整体按推荐系数重新排序，尽量将湖南省院校排在相对前面的位置”
     - 只生成“按推荐系数重新排序”，丢失湖南前置。
   - `5776`：“把重庆院校放在前面，但整体依然按照冲稳保”
     - 只生成“地域要求：要重庆”，没有表达“重庆前置 + 仍保持冲稳保”。
   - `6899`：“公办本科移动到民办本科上面；公办大于民办，东三省公办大于外省公办”
     - 只生成普通“按推荐系数排序”，没有保存用户给出的排序规则。
   - `4041`：“把所有不是广东省的去掉，把广州的加进去”
     - 被解析为“不要广东省”，方向完全反了。

5. 指定加入/候选扩展仍多被降级为 intent。
   - `3675`：要求加入湖州学院、湖州师范大学、成都师范学院等，并限定软件工程/计算机科学与技术，优先计算机科学与技术。
     - 只生成院校 intent，丢失专业限定、加入动作和优先级。
   - `4578`：“把天津或河北加进方案，按具体专业或学校筛选后，生成加入方案的预览”
     - 只生成地域 intent，没有生成加入预览。
   - `7283`：“可以加入中外合作办学的学校”
     - 只生成“要中外合作”的报考条件，没有进入候选扩展/加入方案。
   - `6664`：“为什么找不到可加入方案的候选志愿”
     - 只读审查，没有回答候选加入失败原因。

6. 解释类问题的回复质量不稳定。
   - `6186`：“赣南师范大学建议放在第一个吗”
     - 回复大量通用原则，并说无法逐条扫描方案明细；但本地 state 已有正式方案，应尽量结合当前方案位置、档位和录取概率回答。
   - `6036`：要求查看当前方案中哪些志愿匹配“特色鲜明+生源多元+氛围沉稳”，并看候选中有没有尚未加入机会。
     - 回复混入泛化发展方向审查，没有列出具体当前方案项或候选项。
   - `2464`：“说下这个方案的科学性，以及优缺点和注意事项”
     - 只返回“审查无明显风险”，没有回答优缺点和注意事项。
   - `3554`：“我还想报核电技术与控制工程”
     - 回复变成专业科普，没有生成“加入意向专业/候选查询”的承接。

7. 专业语义仍有矛盾样本。
   - `3648`：“主从会计类，不要调剂”
     - 输出“要会计学；不要会计学、财务管理、审计学、资产评估、税收学”，同一专业同时正负向。
     - “不要调剂”没有被转成专业组内专业选择/服从调剂风险处理。
   - `3151`：“没排除物化专业”
     - 输出“要理学、工学”，可能把“物化专业/物化生相关专业”误读成正向理工要求，语义边界需要结合上下文确认。

### 初步判断

- 第二批严格抽样后，自动 issue 比例下降到 20/50，但人工看实际问题更多。原因是当前检测逻辑只要有 pending card 就容易判 ok，而真实缺陷经常是“有卡片但只抽取了一部分语义”。
- 与第一批结论一致：当前最严重问题不是单点词表缺失，而是结构化动作层覆盖不足。
- 更具体地说，4.0 框架现在能把不少单句硬约束落成 intent，但在以下场景中不能稳定闭环：
  - 同一句里同时包含“约束 + 方案动作”。
  - 用户要求按属性批量过滤当前方案。
  - 用户要求按软优先级重排，而不是硬筛选。
  - 用户要求补齐数量、增加保底、补候选。
  - 用户要求指定院校/专业加入，并带排序位置或专业优先级。
  - 用户要求解释当前方案质量，需要结合当前正式方案/候选明细回答。

## 2026-07-13 框架断点定位记录（仅记录，未改代码）

### 已确认的代码层现状

1. 4.0 direct agent 当前注册工具包括：
   - `read_state`
   - `answer_policy`
   - `compare_entities`
   - `explore_topic`
   - `preview_intent_change`
   - `preview_plan_action`
   - `query_plan`
   - `review_plan`
   - `confirm_pending`

2. 当前 direct 工具集中没有 `preview_fix_proposal` 或等价工具。
   - 旧 registry 中已经把 `fill_missing_count`、`add_safety_items`、`fill_probability_gap` 等策略映射到 `preview_fix_proposal`。
   - 但 4.0 direct 链路没有暴露这个 action family，所以模型遇到“补齐/增加保底/补一个安全点”时，只能在 `generate_plan`、`regenerate_order`、`review_plan` 或普通 intent 之间摇摆。
   - 这和生产回放中“数量补齐不稳定”的现象一致。

3. `preview_plan_action` 的 `PlanAction` 目前只有：
   - `add`
   - `remove`
   - `move`
   - `replace`
   - `sort`
   - `generate`
   - `regenerate_order`
   - `pin_lock`
   - 没有 `fill_missing_count` 或 `apply_fix_proposal`。

4. `review_plan(generate_fix_proposals=True)` 能调用后端 `generate_planning_fix_proposals`，并把 proposal summary 放进回复。
   - 但它只返回只读 message，不创建 pending confirmation。
   - 即使后端已经返回 ready 的 `fill_missing_count` proposal，也不会直接展示可确认卡片。
   - 这解释了会话 `11802969` 中“现在不够了，有没有可以补充进来的”只看到处理方向，却没看到具体可确认补齐项的问题。

5. direct `confirm_pending` 当前执行 plan pending 时，`_apply_plan_pending` 支持：
   - `generate_plan`
   - `regenerate_order`
   - `add_units`
   - `replace_units`
   - `remove_units` / `remove_ordered_unit`
   - `move_unit` / `move_ordered_unit`
   - `sort_ordered_plan`
   - 未接入 `apply_fix_proposal`。
   - 旧 service 路径里存在 `apply_planning_fix_proposal` 的执行逻辑，但 direct confirm 路径没有对应分支。

6. 属性过滤能力本身已有基础。
   - `preview_plan_action(action="remove", filters=...)` 和 `query_plan(filters=...)` 里有 plan item 匹配逻辑。
   - `school_nature`、`program_type`、`province`、`major`、`tuition_min/max` 以及 `ATTRIBUTE_REGISTRY` 都已被接入。
   - 因此“民办/中外合作/高收费/学费阈值/单科限制”不是完全不能处理，而是经常没有被路由成带 filters 的 `preview_plan_action`，或在模型漏 filters 后退化成澄清“请说明学校、专业或第几个志愿”。

7. direct tool return 渲染存在潜在历史串入风险。
   - `BaseAgent.run_with_message_deltas()` 在 direct tool return 分支里，会从 `agent_run.all_messages()` 提取 tool returns 再传给 renderer。
   - 如果历史消息中包含上一轮 `query_plan` / `review_plan` 结果，存在把历史只读工具结果拼到当前回复前面的风险。
   - 这与会话 `11802969` 中“补齐问题回复前串入上海查询结果”的现象吻合。

### 暂不改代码时的结论

- 当前问题不是单点字符串匹配缺失，而是 4.0 direct 工具边界没有完整承接旧框架已有的 proposal 能力。
- “数量补齐”最明显：后端已有 proposal 策略，但 direct agent 没有可调用、可确认、可执行的工具路径。
- “属性批量过滤”已有底层匹配能力，但要求模型一次性选对 action 和 filters；模型漏槽位时没有可靠结构化兜底。
- “复合诉求”仍依赖模型完整抽取 semantic requirements；`preview_intent_change` 注释明确说明工具不会从 `raw_user_text` 自动扫描补语义，所以模型漏掉“补齐50/不要民办/地域优先”等槽位后，工具层不会自动补回来。

## 2026-07-13 生产回捞上下文剩余 110 条首轮回放

### 上下文

- 回放对象仍为 `assets/zhiyuan-production-dialogue-context-5000-20260709-090527.json`。
- 本轮排除前两批已跑的 90 条，继续回放剩余 110 条。
- 回放方式：首轮语义回放，不做确认执行。
- 输出文件：
  - `/tmp/zhiyuan-production-context-first-turn-remaining-110-20260713.json`
  - `/tmp/zhiyuan-production-context-first-turn-remaining-110-20260713.md`
- 自动标签结果：`issue=35`、`ok=75`、`blocked=0`。
- 耗时统计：`p50=8929ms`、`p90=17521ms`、`max=32495ms`。

### 自动标签问题分布

- `action_prompt_no_pending`: 28
- `reply_not_actionable`: 5
- `action_prompt_intent_only`: 4

### 主要现象

1. 明确重做/调整方案没有形成可确认预览。
   - `4474`：“帮我重新做一份志愿方案，学校优先选河南省内和周边”
     - 回复：“没有识别到明确的报考要求”。
   - `3715`：“筛选广东及附近省份的优质公办大专，同时保留现有本科志愿，调整结构为冲本科 + 稳本科/大专 + 保大专，扩展人文社科类专业方向”
     - 回复：“这轮处理没有完成”。
   - `5546`：“专业优先级排序：最想学的在最前面，依次排序...”
     - 回复：“这轮处理没有完成”。
   - `5743`：“根据目前的方案，帮我按照专业优先的顺序进行调整方案，同时保底方案要有”
     - 回复先说没有逐条方案明细，又返回不支持的排序字段说明。

2. “保留/删除/替换”组合动作被错误定位或未形成动作。
   - `2200`：“保留青岛理工大学、大连交通大学、天津商业大学、山东科技大学、沈阳航空航天大学。其他全部删除”
     - 回复要求说明学校、专业或第几个志愿，并把保留对象表现成 `exclude_schools`。
   - `5147`：“许昌学院第111组和河南城建学院第103组删除，重新选两个有电气专业的”
     - 只生成“电气”专业意向卡，删除和重新选两个未形成方案动作。
   - `4470`：“把这里面学费高于2.2万的删除，用别的替换”
     - 回复说当前没有高于 2.2 万项目，随后转成口头询问是否需要预览，没有形成替换预览。
   - `6815`：“移除不是广东的，补广东的进来”
     - 回复要求唯一定位 `province_not=广东`。

3. 指定学校/专业组加入或移除定位不稳定。
   - `6461`：“把重庆文理学院和重庆第二师范学院加入方案”
     - 回复要求补充搭配专业。
   - `5761`：“去掉浙江传媒学院第203组、曲阜师范大学第204组、大连交通大学第208组中外合作办学组”
     - 回复要求说明学校、专业或第几个志愿。
   - `5911`：“去掉九江学院04组 03组”
     - 回复没有唯一定位，要求用户说明第几个志愿、专业组或是否移除所有九江学院。
   - `4825`：“把这个学校加入方案”
     - 回复要求说明学校名称和专业组。
   - `7017`：“确认加入”
     - 回复没有可确认预览。

4. 属性批量过滤仍有“要求唯一定位”的表现。
   - `6342`：“删除组内专业数量大于1的专业组”
     - 回复要求唯一定位 `major_count_min=2`。
   - `5137`：“去掉有新增专业的专业组院校”
     - 回复要求唯一定位 `专业标签=新增专业`。
   - `6807`：“把所有高校专项去掉”
     - 回复要求唯一定位 `enrollment_type=高校专项`。
   - `6784`：“删除前几个冲的志愿”
     - 回复要求唯一定位 `梯度=冲`。
   - `6642`：“我是汉族，去掉朝鲜族考生能报的专业”
     - 回复“这轮处理没有完成”。

5. 复合报考要求只抽取一部分或抽取冲突。
   - `5769`：位次、同意调剂、专业倾向、河南学校、色弱、不接受中外合办等多项信息一起表达。
     - 回复被改成“这轮还没有生成可确认的调整预览”。
   - `4947`：“把民办去掉，只要公办，重新给我一个方案”
     - 只生成“院校要求：要公办”，没有体现“去掉民办”和“重新给方案”。
   - `5245`：“帮我重新筛选一下，计算机类优先选择计算机科学与技术”
     - 卡片中同时出现“要计算机科学与技术”和“不要计算机类、计算机科学与技术”。
   - `7094`：长文本包含专业、地域、公办/民办、费用限制等要求。
     - 卡片只保留部分专业要求。
   - `7391`：“只要电气、电子、机械、自动化等强工科，有调剂风险的不要”
     - 卡片把“调剂风险”作为专业负向项。

6. 地域/院校层次/排序偏好的表达被弱化或泛化。
   - `5139`：“按照只去广东，这个范围调整方案”
     - 生成地域要求“要广东”，没有体现“只去”和“调整方案”。
   - `2255`：“院校层次优先，可接受外省的院校”
     - 生成“要双一流、211、985；地域要求：要外省”。
   - `6541`：“优先保证在能上的211内选择，随后考虑一本，专业优先考虑电气自动化、通信工程、电子科学等，其次计算机、软件，再次新能源、材料，避免土木”
     - 卡片只保留“院校要求：要211、一本”。
   - `6796`：“把方案里的专业按系统综合推荐度排序，前边几个医科类不变”
     - 生成普通推荐系数排序，未体现“前边几个医科类不变”。
   - `6646`：“冲的按职能排序，选3个排前三”
     - 生成普通推荐系数排序。

7. 解释/查询类回复缺少当前方案明细或出现泛化。
   - `5965`：“能出示一下冲稳保的专业吗”
     - 回复说暂时没有逐条扫描方案明细，只返回审查摘要。
   - `6073`：“还是想先看看当前方案里新能源相关的覆盖情况，再决定怎么调整？”
     - 回复说未检索到新能源覆盖，并追问怎么调整；未形成当前方案明细列表。
   - `5118`：“护理和康复治疗技术这两个专业，我应该把哪个放在希选”
     - 回复泛化比较两个专业，没有结合当前方案或用户上下文。
   - `5508`：“选末尾的985好还是选强劲的211专业好，一起加入考虑范围内”
     - 回复为院校层次和专业实力取舍科普，没有承接“一起加入考虑范围内”。

8. 用户承接前文的省略表达处理不稳定。
   - `4922`：“或者按地域、专业、稳妥程度做局部调整”
     - 回复“这轮还没有生成可确认的调整预览”。
   - `5615`：“那就第二个方案吧，3.3.4吧，3冲，3稳，4保”
     - 回复没有可确认预览。
   - `5829`：“是否坚持信息安全方向？我可以帮你放宽条件再查一次...”
     - 回复转成澄清坚持信息安全还是放宽到计算机类。
   - `5976`：“加入方案”
     - 回复要求说明加入什么内容，并列出可能方向。

9. 部分自动 ok 实际仍有明显失败话术。
   - `6564`：“我就一个目的上985，可以接受高收费一年10万，我想将来让孩子去澳大利亚上学”
     - 回复“这轮处理没有完成”。
   - `6923`：“南航给了一个一保一政策，是不是应该优先填到前边一点？”
     - 回复“这轮处理没有完成”。
   - `4663`：“意向院校湖南财经学院会计学财务管理，次选湖南警察学院法学”
     - 回复“这轮处理没有完成”。
   - `5488`：“我只有地方专项不接纳国家专项和高校专项”
     - 回复“没有识别到明确的报考要求”。

## 2026-07-13 生产回捞 200 条首轮回放统一问题汇总

### 回放范围

- 第一批 40 条：`/tmp/zhiyuan-production-context-first-turn-40-20260713.json`
- 第二批 50 条：`/tmp/zhiyuan-production-context-first-turn-targeted-50-20260713.json`
- 剩余批 110 条：`/tmp/zhiyuan-production-context-first-turn-remaining-110-20260713.json`
- 三批合计唯一样本：200 条。

### 自动统计

- `auto_issue=81`
- `auto_ok=119`
- `auto_blocked=0`
- 自动问题标签：
  - `action_prompt_no_pending`: 58
  - `action_prompt_intent_only`: 12
  - `fill_count_no_pending`: 8
  - `reply_not_actionable`: 7
  - `fill_count_over_generic_generate_plan`: 3
  - `fill_count_lost_to_intent_only`: 3
  - `priority_region_dropped`: 3
  - `constraint_plus_fill_dropped_fill_action`: 1
- 样本类别覆盖：
  - `region_priority`: 61
  - `review_explain`: 45
  - `add_specific`: 31
  - `tuition_private`: 28
  - `major_constraint`: 25
  - `fill_count`: 18

### 统一问题归类

1. 明确动作没有形成 pending。
   - 用户已经表达“调整、删除、移除、加入、补齐、重做、重新生成、排序”等动作。
   - 实际回复中多次出现“没有识别到明确报考要求”“这轮处理没有完成”“请说明学校、专业或第几个志愿”“这轮还没有生成可确认的调整预览”。

2. 有 pending 但只承接部分语义。
   - 常见表现是只生成 `intent_change`，没有同步承接当前方案动作。
   - 典型场景包括“不要民办 + 补齐数量”“只要公办 + 重新给方案”“指定删除旧项 + 重新选新项”“加入学校 + 限定专业 + 排序位置”。

3. 数量补齐类不稳定。
   - “补齐45/50/96”“补足剩下10个”“增加保底志愿”“现在不够了能否补”会被分流到多种结果：
     - 泛化 `generate_plan`
     - `regenerate_order`
     - 只读 `review_plan`
     - 只采纳约束 intent
     - 无 pending 回复

4. 属性批量过滤容易被当成单项定位。
   - 民办、中外合作、高收费、学费阈值、单科限制、新增专业、高校专项、组内专业数量、录取率阈值、民族限制等属性类请求，多次被回复为需要说明具体学校、专业或第几个志愿。

5. 地域和排序软目标容易丢失。
   - “湖南/上海/重庆/广东更靠前”“不是只保留”“仍按冲稳保”“公办在民办上面”“东三省公办优先于外省公办”等表达经常被弱化成普通排序、普通地域要求或单一 intent。

6. 专业层级和专业组语义有冲突样本。
   - “类中只保留子专业”出现正负同名。
   - “计算机类优先选择计算机科学与技术”出现要子专业同时不要父类和子专业。
   - “不要调剂/有调剂风险不要”被转成专业负向项。
   - “组内专业数量大于1”“同专业组有符合意向专业”被当成需要唯一定位。

7. 指定加入/替换候选能力不稳定。
   - 指定学校、专业、专业组、院校集合和替换方向时，经常回复需要更多学校/专业信息。
   - 有时只把学校或专业记录成报考意向，没有生成加入/替换方案预览。

8. 当前方案查询和解释质量不稳定。
   - 用户问当前方案有哪些、覆盖情况、科学性、优缺点、冲稳保专业、某校是否放第一时，回复中多次出现“暂时没有拿到可逐条扫描的方案明细”或通用科普。
   - 部分回复没有列出具体方案项、候选项或当前位置。

9. 上下文承接不稳定。
   - “那就第二个方案”“确认加入”“或者按地域/专业/稳妥程度局部调整”“现在不够了”这类承接前文的表达，容易被当成无 active pending 或缺少具体对象。
   - 部分回复和用户当前问题不对齐。

10. 自动评估存在漏报。
   - 自动规则只要看到 pending card 就容易标成 ok。
   - 实际人工看，部分 ok 样本仍存在“只承接一部分语义”“生成泛化排序”“回复处理失败”“没有回答用户问题”等问题。

## 2026-07-14 v2.65 问题关闭状态矩阵

本节以 v2.65 当前代码、`release-4.0.0-zhiyuan-agent-implementation-design.md` 和真实 final-action gate 为准，覆盖上面的 200 条首轮回放问题。前文保留问题发现时的原始记录，不再把当时的“当前框架现状”直接当作最新实现状态。

| 原问题类别 | 当前状态 | 已关闭范围 | 仍未关闭范围 |
|---|---|---|---|
| 1. 明确动作没有形成 pending | 大部分关闭 | 已支持明确加入、移出、替换、移动、排序、命名候选加入、总数量补齐和当前总数不变的显式覆盖；ready 时只创建一个结构化 pending，blocked/no-change 不出假确认卡 | 增加保底、补概率缺口、冲稳保档位数量等结构目标仍只读审查；当前不允许用 generate/regenerate 伪装这些目标 |
| 2. 有 pending 但只承接部分语义 | 部分关闭 | `fill_to_count + include/exclude/only_keep + 一条同档 priority` 已进入同一个 `PlanChangeSpec`、Proposal、pending 和 planning command，并在确认后统一校验 | “加入指定对象 + 指定位置”、没有数量目标的筛选与 priority 复合、多条/多级 priority 等仍未形成统一原子 Proposal |
| 3. 数量补齐类不稳定 | 总数目标已关闭，结构数量未关闭 | 显式补到 N、根据 planning state 补到上下文目标、补齐同时排除/只保留/include/priority，以及保持当前总数的显式覆盖数量已闭环 | “再增加 N 个”相对覆盖、至少 N 个保底、冲稳保配额、概率缺口和安全垫仍需独立 typed goal 与 postcondition |
| 4. 属性批量过滤被当成单项定位 | 部分关闭 | 公办/民办、中外合作、高收费、学费、院校层次、地域、专业门类/标签等已有 structured requirement/filter 和 final-action 回归；工具不再从 `raw_user_text` 私自恢复条件 | 组内专业数量、录取率阈值、复杂招生限制等尚未全部进入统一 selector schema；部分纯当前方案批量处理仍依赖模型完整输出 filters |
| 5. 地域和排序目标丢失 | 单条同档规则已关闭 | 一条 `rank_before/within_tier` priority 可单独执行，也可与数量及 requirements 复合；规则持久化并在 regenerate 后恢复，确认后校验同档逆序为 0 | 多条/多级优先、公办优先于民办再叠加地域优先、跨档移动、priority 自身增加覆盖仍 fail closed |
| 6. 专业层级和专业组语义冲突 | 部分关闭 | major/majorGroup 已按 volunteer model 分域计数，专业组按完整 unit 增删；专业门类、学科、标签和命名专业已有 final-action 覆盖 | 父类/子专业同时 only_keep/exclude 的冲突解释、调剂风险、组内专业数量与组内覆盖等仍需专门 typed selector/目标 |
| 7. 指定加入/替换候选不稳定 | 大部分关闭 | 命名院校+专业会查询真实候选，唯一命中生成 pending，多解澄清；替换方向支持费用、合作办学、院校层次、录取把握和地域等结构化维度 | 加入后同时放到指定位置尚未统一成一个原子 Proposal；多候选质量排序、候选不足时的替代建议仍需扩大生产样本验证 |
| 8. 当前方案查询和解释不稳定 | 部分关闭 | `query_plan` ground 到正式方案，`discover_options` 区分目录、当前可报、候选推荐和正式方案；“上海的有哪些”无上下文时先澄清，不再用模型常识补名单 | `compare_entities` 目前主要使用院校/专业资料并标记是否在当前方案，尚未完整结合候选池录取率、推荐分、可报状态和当前位置进行对比 |
| 9. 上下文承接不稳定 | 大部分关闭 | active pending 的确认、取消、追加和替换已统一到独立 pending/CAS；短文本确认、断连、租约接管和 operation 重放闭环；direct 直返只消费本轮 tool return | 没有结构化 pending 的自然省略表达仍依赖模型语义；相对数量和复杂多目标承接继续澄清而不是猜测 |
| 10. 自动评估漏报 | 机制已改，正式复跑未关闭 | runner 已支持工具次数、followup、routing、pending 状态、planning version、最终方案字段和 postcondition 等断言，不再只以“有卡片”判成功 | 200 条生产样本尚未基于 v2.65 重新全量回放；正式 `13 live + 19 clone-backed final-action` 发布门禁仍需在稳定完整拓扑执行并分层报告 |

### 当前总体结论

- pending、确认、幂等事务和断连恢复等执行地基已经关闭，不再是 4.0 的主要风险。
- v2.57-v2.65 已关闭读侧发现、总数补齐、projected requirements、coverage 和单条同档 priority 等第一批高频能力，原始 200 条问题不能再按 `81/200` 直接代表当前失败率。
- 当前主要风险已转为能力覆盖与发布证据：结构数量目标、复杂 selector、多级优先、候选/方案 grounding 对比，以及完整正式门禁尚未收口。
- 后续仍坚持一个 typed `PlanChangeSpec`、一个后端 Proposal、一个 pending 和一个可回放 planning command；不恢复 3.2 中文规则枚举，不从原话在工具层补造业务条件。

## 2026-07-14 v2.66 重复调用关闭与正式门禁进度

### 本轮关闭项

- “民办就算了”“山东别去了”“省外可以，但太偏的地方不想去”中，模型首轮已经给出结构化 `semantic_requirements`、但遗漏等价 `positive/negative` 时，不再返回 completion 错误要求模型二次调用。工具只把 `explicit/confirmable` 结构化项补进 typed payload，`reference` 不落为要求，也不从 `raw_user_text` 扫描恢复实体或条件。
- active pending 下“再把民办也算了吧，一起记上”此前首轮漏传 `pending_resolution`，会收到 `active_pending_requires_resolution` 后再调用一次。现在只在 active pending 场景动态把该字段标为 tool schema required；append/replace/hold 的选择仍由模型完成，没有增加中文话术分类器或工具层猜测。
- 被替代的 `intent_change_requires_attribute_completion` 返回协议和专用 completion 校验实现已删除；v179 对应回归资产的 `maxToolCallCount` 已从 2 收紧为 1。

### 验证证据

- Python unit：`1586 passed, 31 skipped`；正式 local quality gate：`441 passed`。
- clone-backed focused：v143 `2/2`、v216 `2/2`、v179 strict `10/10`。所有步骤工具调用数均为 1，确认后 pending、planning version、硬要求、ordered/review 刷新和 targeted replace 后端断言通过。
- v179 append 步骤从修复前约 `15.9s / 2 次模型请求 / 2 次 preview_intent_change` 收敛到约 `6.4-6.7s / 1 次模型请求 / 1 次 preview_intent_change`。
- metrics：`/private/tmp/zhiyuan_400_v266_v143_semantic_materialization.json`、`/private/tmp/zhiyuan_400_v266_v216_semantic_materialization.json`、`/private/tmp/zhiyuan_400_v266_v179_strict_single_call.json`。

### 正式门禁当前口径

- v2.65 完整拓扑上已执行 13 文件 live baseline：`230` step，`223` passed，`7` failed。
- 已执行 19 文件 clone-backed final-action gate：`151` step，`149` passed，`2` failed；全部后端状态断言通过，没有 final-action timeout、原子执行错误或跨 case 状态污染。
- 上述 9 个失败不能再统一归为执行链路缺陷：其中包含模型超时、断言漏报，以及尚未实现的 review-to-repair、专业组内安全补齐和上下文补齐数量 Proposal。v2.66 已关闭其中稳定的 intent 重复调用，但尚未重新执行完整 32 文件 gate，因此不把 focused 结果写成正式门禁全绿。

### 下一批实现顺序

1. 将“把这版调稳点，先看怎么动”从只读 `review_plan` 的处理方向推进到用户明确要求时可选择并冻结一个 review fix Proposal；只读询问仍不创建 pending。
2. 为“专业组里补一个安全专业，先看预览”建立 group-inner safety typed goal、候选选择和 postcondition，不用中文规则枚举拼 action。
3. 修复“从候选选 7 所补齐志愿数量”的上下文数量/对象语义，使其进入一个 `PlanChangeSpec`、一个 Proposal 和一个 pending；不能退回泛化 generate。
4. 强化 runner 对 timeout、fallback、缺 pending 和回复与后端目标不一致的失败判定，再重跑 13 live + 19 final-action 完整门禁。
5. 扩大候选/方案 grounding 的院校专业推荐与比较验证；“孩子可能涨分，要不要留冲的空间”保持政策/策略只读回答，不要求先有正式方案。

## 2026-07-14 v2.67 专业组内安全修复关闭

### 已关闭范围

- “专业组里面有没有录取率太悬的？能不能补一个安全一点的专业，先给我看预览”不再走只读 `review_plan`，也不再用不消费临时修复目标的 `regenerate_order` 生成假确认卡。模型一次调用 `preview_plan_change(repair_goal=...)`，工具精确选择 `group_inner_safety_guard + adjust_major_group_inner_safety` 的 ready Proposal。
- `repair_goal` 与数量、筛选和 priority 互斥；工具不会按后端返回顺序选择第一个 ready Proposal。相同 issue+strategy 无 ready、出现多个 ready、Proposal 来源/版本不一致时均不创建 pending。
- review stale 导致 Proposal 生成时 planning version 前进的问题已纳入契约：envelope、Proposal guard 和生成后 fresh workspace version 必须一致。该校验关闭了调用前状态摘要版本落后一拍导致的假失败，同时保持并发版本保护。
- 确认后不再只看 API code。后端要求 Proposal ID/source 一致且 `postValidationPassed=true`；失败事务回滚，成功回执展示实际调整的专业组数和补入专业数。
- 被替代的该场景 `preview_plan_action(regenerate_order, probability_gap)` prompt 路由和测试口径已移除；纯重排能力保留，但只能消费已确认要求和当前候选，不能承载临时 review repair 目标。

### 验证结果

- Python unit：`1590 passed, 31 skipped`；direct/mainline/hard-cut：`271 passed, 31 skipped`。
- Java：`575 tests, 0 failures/errors, 4 skipped`。
- 真实 clone-backed `2/2`：首轮一个 `preview_plan_change`、一个 pending card；确认后调整 3 个专业组、补入 3 个专业、复审通过，pending `applied`，ordered/review 刷新和全部后端 postcondition 断言通过。metrics：`/private/tmp/zhiyuan_400_v267_review_repair_exact_proposal.json`。
- 测试 session `9905814` 的后端 8 类数据、Agent history 和候选复制文件已清零；已 purge 封存的 `binlog.000293`，保留活动 `binlog.000294`。MySQL 目录约 `15G`，磁盘可用约 `70GiB`。

### 仍未关闭范围

- 泛化“把这版调稳点/稳一点”仍没有足够窄的 typed selector，不能盲选当前存在的 `sort_by_probability`，也不能把 `preview_only/blocked` Proposal 当可执行建议；当前继续只读列出处理方向。
- 增加保底、补概率缺口、冲稳保档位数量仍需各自的确定目标与 postcondition。
- “从候选中选择 7 所并补齐志愿数量”的候选对象与上下文数量组合尚未进入一个 Proposal。
- 完整 `13 live + 19 final-action` gate 尚未基于 v2.67 全量重跑；本节只关闭该 focused 纵切，不把局部 `2/2` 写成整体发布门禁全绿。

## 2026-07-15 v2.68 泛化调稳预览关闭

### 已关闭范围

- “把这版调稳点/别太冒险，先看怎么动”现在先获取结构化 review Proposal options，再由模型选择唯一直接匹配的 ready Proposal，并以 exact `review_issue_code + strategy` 第二次调用同一工具。第一次 options 不创建 pending，第二次 exact 选择成功后才创建一个确认卡。
- 这不是恢复 3.2 的 Proposal 规则枚举。Python 不扫描中文原话映射策略、不按列表顺序选第一项，也不把数量 Proposal 混进稳定性目标；未表达数量时，`fill_missing_count/count_validation` 明确排除。
- 首轮 options 后不再依赖 prompt 期待模型自觉继续。Agent 使用一次框架级 `ModelRetry` 携带完整结构化 options，强制完成选择或明确返回无唯一匹配边界；重试预算为 1，不会形成工具循环。
- exact Proposal 继续复用 v2.67 的唯一 ready、Proposal 来源和版本 guard、单 pending、planning command 幂等执行与复审 postcondition。确认成功必须满足 `postValidationPassed=true`，不能只因接口返回成功就宣称已调稳。

### 验证结果

- 完整 Python unit：`1593 passed, 31 skipped`；Agent/direct/mainline/hard-cut：`300 passed, 31 skipped`。
- 真实 focused preview `1/1`：工具调用恰好为两次 `preview_plan_change`，没有 `review_plan/query_plan/preview_plan_action`，生成唯一确认卡；metrics `/private/tmp/zhiyuan_400_v268_stability_forced_retry_preview.json`。
- 同 session 确认 `1/1`：pending `applied`，策略 `sort_by_probability`，调整 2 个专业组且不增删志愿，ordered/review 刷新返回，`postValidationPassed/satisfied=true`；metrics `/private/tmp/zhiyuan_400_v268_stability_forced_retry_confirm.json`。

### 仍未关闭范围

- 增加保底、补概率缺口、冲稳保档位数量仍需各自的 typed goal、确定性 dry-run 和专用 postcondition，不能统一塞进“调稳点”。
- “从候选中选择 7 所并补齐志愿数量”的对象选择与上下文数量组合仍未进入一个 Proposal。
- 完整 `13 live + 19 final-action` gate 尚未基于 v2.68 重跑；本节 focused `2/2` 只关闭调稳纵切，不代表整体发布门禁全绿。

## 2026-07-15 v2.69 上下文补齐 final-action 关闭

### 用户语义结论

- 连续话术“不要医学类的”之后“从候选中选择 7 所放入方案里，先补齐志愿数量”，主目标是把现有方案补到上下文规划目标；`7 所` 表示用户预计从候选中选取的数量或来源描述，不能在用户未说“最终共 7 所/补到 7 所”时覆盖最终目标。
- 实测 planning state 为当前 45 个专业组、目标 48。第二轮必须冻结 `target_count=48`，并把上一轮未确认的 `exclude major.level1=医学` 合并进同一个 Proposal；不能先确认硬要求再另建补齐 pending，也不能退回 `add_units` 而缺少候选 ID。
- 软偏好仍不引入本链路。用户明确说“不要医学类”按硬要求投影、过滤和最终校验。

### 首次真实失败

- 前两轮路由和 pending 已符合设计：一次 `preview_intent_change`，随后一次 `preview_plan_change`；目标冻结为 48、requirement 冻结为医学排除，旧 intent pending 被合并成一个 plan-change pending。
- Proposal 错误预演为“当前 45，移出 0，补入 3，最终 48”。确认时后端重建得到 47，postcondition 报错：`target=48 actual=47 persistedTarget=48 requirements=1/1`。事务和硬要求均正确回滚，说明确认地基有效，错误位于 dry-run 与执行事实不一致。
- 根因不是模型或“医学/医学类”文本。候选池专业 ID 为 `专业组ID_计划专业数据ID`，正式方案专业 ID 为 `专业组ID_专业ID`；Proposal 仅按 ID 查找导致正式方案专业拿不到候选池中的 `majorDiscipline/majorCategory`，而确认重建会按最新候选事实过滤，因此两边计数漂移。

### 修复与删除旧口径

- Proposal 和实际有效候选复用同一候选事实构建：身份归一、已有推荐覆盖层、专业分类补全。没有保留一套“预演原始 items”、另一套“执行 enriched items”的重复实现。
- 正式方案专业 ID 解析增加“专业组 ID + 完整专业名”的唯一回退，出现多解不选择第一项。专业组按过滤后的净存活数计数：混合组只删医学专业，全医学已选组计为损失；被清空的组可作为 projected eligible 候选重新补入。
- 旧的“专业组所有候选都必须满足硬要求才可选”口径被替换为先过滤组内不合格专业、再判断组是否仍有可选专业，避免一个被排除专业拖死整个组。
- active pending 合并仅接受 typed major/school/region 条件；职业、学费、未知字段和不兼容 only-keep 直接 blocked，并保留旧 pending。工具不扫描用户原话恢复字段。

### 最终验证

- Java 相关测试 `259 tests, 0 failures/errors, 3 skipped`；完整 Maven `577 tests, 0 failures/errors, 4 skipped`。Agent 聚焦 `303 passed, 31 skipped`，runner/quality `111 passed`。
- 真实三轮 final-action `3/3`。修复后第二轮预演为“当前 45，移出 1，补入 4，最终 48”；第三轮返回“已按预览调整方案，当前共 48 个专业组，数量和 1 条要求校验通过”。
- 后端断言全部通过：pending `applied`、`postcondition_report.satisfied=true`、`requirementCount=1`、`requiredCount=48`、ordered units 长度 48、最终方案不含医学；ordered/review 两个刷新入口均返回。
- metrics：`/private/tmp/zhiyuan_400_v269_context_fill_pending_merge_after_identity_projection_fix.json`。

### 清理与剩余项

- session `9907046` 的 planning/profile/score 已覆盖恢复为源 session 16；Agent SQLite 历史删除 2 行，3 个候选复制文件已删除。
- 当前本机 MySQL 管理账号仍无法认证，因此 applied pending 等历史测试 DB 行与 sealed binlog 暂未物理清理；没有手工删除 binlog。恢复有效凭据后应只用 MySQL `PURGE BINARY LOGS` 清理已封存文件，并再次确认活动 binlog。
- 本节只关闭该 focused final-action，不代表完整发布门禁全绿。下一步重跑 `13 live + 19 final-action`，再推进保底数量、冲稳保配额、概率缺口和候选/方案 grounding 对比。

## 2026-07-15 v2.70 首工具、reference、对比与测试假阳性收口

### 设计结论

- 不增加软偏好层。普通“倾向/重点关注/优先考虑/也可以考虑”继续按硬要求预览；只有用户明确说“仅供参考、先别记录、不要调整”时，才使用 typed `strength=reference` 做不落状态的只读确认。
- 每轮首个模型响应必须恰好调用一个工具。同批多工具在执行前整体拒绝并重试，未执行 ToolCall 不写入持久化历史；顺序发生的参数/schema 修正仍允许。
- “有哪些”按名单发现或当前方案/候选查询处理；两个到五个院校、专业或宽口径方向问“哪个更适合”统一对比处理。没有恢复 3.2 中文规则枚举，也没有在工具层扫描原话补造业务条件。
- only-keep 只保留点名的正向集合。“其他方向都不要”是集合补语，不是一个可落库的专业实体。

### 完整 live 基线分层

- v2.70 13 文件 live 基线共 `231 step`，`224 passed / 7 failed`，metrics 目录 `/private/tmp/zhiyuan_400_v270_after_reference_fix_full_gate`。
- 7 个失败中，5 个由 3 次真实 `TimeoutError` 及后续轮次连带造成：偏好预览确认 2 step、体制内方案场景 1 step、学费预算预览确认 2 step。
- 另外 2 个稳定问题是：“法学和财经哪个更适合我”误走 `explore_topic`；“只要电气和气象”已返回 canonical `大气科学类`，旧断言仍要求口语别名“气象”。
- 最大抽象集结果：dialogue-derived `88/88`、open-quality `23/23`、review/repair `10/10`、career `4/4`。因此没有证据表明整体自主路由框架需要退回规则表。

### 修复与聚焦复核

- 专业对比新增精确工具契约，live `1/1`，首工具为 `compare_entities`，总工具数 1，无 pending。
- “只要电气和气象”live `1/1`，pending 只含 `电气类、大气科学类`，不再出现“不要：其他方向”。体检表影响 live `1/1`，只调用一次 `answer_policy`。
- 三条超时链隔离复跑 `6/6`：偏好预览/确认 `2/2`，体制内方案审查/移动预览 `2/2`，学费预算预览/确认 `2/2`。学费确认后 pending applied、planning version 增长，最终方案全部 `tuitionPerYear <= 20000`，ordered/review 双刷新通过。原失败按超时及连带归类，不放宽断言。

### 新发现的测试与展示问题

- `400-prod-scenario-public-service-oriented-plan` 默认克隆 session 17，但该源正式方案数量为 0；旧断言只要回复出现“方案/第8/第12/预览”任一词就会通过，实际回复是“没有正式方案”。该结果不再计成功。
- 用例已切换到 session 16（45 个正式志愿），声明 `formal_plan_present`，固定首轮 `review_plan`、第二轮 `preview_plan_action`、工具数 1、单 pending，并禁止无方案回复。
- runner 现从克隆 planningState 生成小型 state profile，并在 WebSocket 前校验 fixture contract。正式方案为空时直接按环境失败，不允许进入对话后假通过。
- 移动 payload 原本正确保存目标第12位，但确认卡只显示源第8位。现统一显示“源第8位；目标位置：方案第12位”；G17 档内移动显示“保底第1位（方案第98位）”。

### 验证与当前结论

- Agent unit：`1608 passed, 31 skipped`；runner unit：`101 passed`；quality gate unit：`16 passed`；移动目标聚焦：`10 passed`。
- clone-backed 代表 final-action `9/9`：G17 `1/1`、v157 cancel/reissue `4/4`、v211 南方/北方 `2/2`、学费 requirement/action `2/2`。所有适用的 pending、planning version、硬要求、正式方案和 workspace refresh 后端断言通过。
- 本轮 9 个测试 session 的数据库状态和 Agent history 已复核清零，四组候选复制文件已删除；明确失效或被最终结果替代的 metrics 已清理。MySQL 活动日志确认是 `binlog.000337`，已通过 `PURGE BINARY LOGS TO 'binlog.000337'` 删除 `000296-000336`，未手工删除文件；当前只剩活动 binlog，磁盘可用空间从 15GiB 恢复到 57GiB。
- 当前可确认：已发现的两个稳定语义问题已修复，三条超时链无法稳定复现，且测试假阳性已封堵。当前仍不能宣布完整发布门禁全绿；需要清理测试状态后重新执行一次完整 `13 live + 19 clone-backed final-action`，并对模型超时、fixture/environment 和稳定业务失败分别报告。

## 2026-07-16 v2.71-v2.72 完整门禁分层与稳定问题关闭

本节是当前最新状态，覆盖上一节“尚未执行完整门禁”的阶段性结论。前面的失败发现过程继续保留，但不能再直接当作当前未修复问题清单。

### 13 文件 live gate

- 清洁初跑共 `231 step`，结果 `221 passed / 10 failed`，metrics 目录为 `/private/tmp/zhiyuan_400_v271_clean_full_gate`。
- 稳定业务缺陷只有一项：`only_keep` 语句“只想学临床医学，其他专业先不要”被模型展开成多个学科门类负向项，确认卡出现泛化“不要”内容。`only_keep` 本身已经通过正向集合表达补集，不应再持久化模型枚举出的泛化补集。
- 工具现在只基于结构化 `semantic_requirements` 清理未被用户语义片段点名的泛化补集，覆盖“其他/其它/其余/剩余/剩下”；明确点名的排除项仍保留。工具没有扫描 `raw_user_text` 发明条件，也没有恢复中文规则枚举。
- 修复后生产抽象 only-keep `2/2`、正式方案 requirement/action `2/2`；8 个 dialogue-derived 失败步骤在连接恢复后 `8/8`，open-quality 文案断言 `2/2`。初跑 10 个失败步骤均有隔离通过证据，但这仍按分层复验记录，不伪写成同一次 `231/231`。

### 19 文件 clone-backed final-action gate

- 初跑共 `151 step`，结果 `143 passed / 8 failed`，metrics 目录为 `/private/tmp/zhiyuan_400_v272_final_action_gate`。
- 3 个 environment failure 来自 G3/G22/G31 依赖可变源 session `130` 的 active pending。用例已改为从正式方案夹具开始，在同一 case 首轮真实创建 intent pending，第二轮再执行只读查询，并断言 pending 仍为 `active`。修订后 3 case 共 `6/6`，G31 最终单包 `2/2`。
- 1 个稳定语义失败是“管理学的不要了”偶发被收窄为 `工商管理类`。Agent 现在要求保留用户点名的专业分类层级：管理学/医学/工学等学科门类使用 `level1` 原名，专业类使用 `level2`，具体专业使用 `major`。工具仍只归一结构化参数，不从原话纠正模型。最终动作复验 `2/2`，后端 `mustExcludeMajors` 保存“管理学”，正式方案完成过滤。
- v158 的 2 个失败步骤由首轮模型 `TimeoutError` 及确认轮级联造成，隔离重跑 `2/2`；“山东 + 民办”同时落入一个 pending，确认后地域和院校性质硬要求、最终方案及双刷新断言全部通过。
- v173 的 2 个失败步骤由一次性 `TypeError` 及下一轮错位级联造成；相同夹具和代码单包复现 `2/2`，位置选择、pending 和确认移出均通过。当前没有可重复代码根因，因此不增加防御性业务分支。

### 当前结论与剩余工作

- 上述 19 包中没有仍可重复的 final-action 业务失败；pending、确认、Proposal apply、planning version、硬要求和正式方案 postcondition 未发现新缺口。
- Python unit 全量为 `1611 passed, 31 skipped`；Agent/direct/runner/quality/hard-cut 聚焦为 `396 passed, 31 skipped`。JSON 资产已验证可解析。
- 验收后已删除 990* 回归会话的 290 条 chat session、11494 条 message、1554 条 extra-data、119 条 pending、51 条 planning command、2148 条 behavior event 和 293 条 freshness schedule，复核 8 类表均为 0；Agent SQLite 删除 367 条 990* 历史并 `VACUUM`，654 个候选复制文件已删除。MySQL 仅通过 `PURGE BINARY LOGS` 清理封存日志，当前只保留活动 `binlog.000371`；磁盘可用空间由 18GiB 回升到 54GiB。
- 发布证据仍需区分“完整初跑”和“失败子集复验”。若要宣布一次性发布门禁全绿，还需在清洁 session 上重新跑一轮同版本 `13 live + 19 final-action`，不能把分层结果简单相加。
- 原 200 条人工问题中的剩余能力缺口仍是结构数量目标、复杂 selector、多级 priority，以及结合候选池可报状态/录取率/当前位置的院校专业比较；继续按 typed goal、确定 dry-run 和专用 postcondition 扩展，不恢复 3.2 中文执行规则罗列。

## 2026-07-16 v2.74 查询、审查与复合硬要求收口

本节覆盖 v2.72 之后对人工检查问题的继续处理。此前章节中的发现过程继续保留，但下列已关闭项不应再列入当前稳定缺陷；尚未完成的完整门禁仍单独列出，focused 结果不代替发布结论。

### 已关闭问题

- 院校/专业的目录发现、候选查询、正式方案查询和比较不再混成泛知识回答。`discover_options` 负责查目录或当前可选候选，`query_plan` 负责正式方案事实，`compare_entities` 负责命名对象比较；“上海的有哪些”缺少查询范围时先澄清，有候选或方案上下文时按对应数据源查询，不再凭模型常识补院校名单。
- 发现条件兼容 `level1/level2/level3/major_direction -> major`、`admission_stability -> tier`、`stable -> 稳/保`。候选精确查询为空时会继续检查专业是否存在于其他档位或父专业类，并给出真实示例与下一步；不会把“指定档位没有”误报为“这个专业不存在”。
- `review_plan` 直接返回可核验的当前方案结论：当前总数和目标数、冲稳保结构、问题数量和实际影响样本、学费阈值、专业/职业方向承接、可执行 Proposal 与 blocked 原因，以及只读边界。问题定位优先使用 issue code，不再用“保”等单字符扫描整段文本；高学费问题因此不会再因“保留”字样误判成保底问题。
- “一年学费最多两三万，方案里高收费多吗”中的明确上限按硬要求处理，归一为每年不超过 `30000` 元。链路先用 `query_plan` 回答当前方案影响，再用 `preview_intent_change` 生成一个 pending；影响展示区分 `26 个专业组 / 85 条专业志愿`，不再把专业明细条数说成专业组数。只有明确“仅供参考/不要记录/不要调整”才保持只读。
- “当前方案对财会和考公方向承接怎么样，先不要改”使用一次 `review_plan`。专业方向按真实专业字段匹配，职业方向使用共享的 canonical evidence；代表项按专业证据优先排序并按专业组去重，不再重复展示同组内无关专业，也不再让院校名称弱证据压过专业证据。
- Proposal 预览补充明确标题、受影响专业组数和专业明细数。带临时筛选/修复目标的 generate/regenerate 若后端不能消费该目标，会返回需要具体 Proposal 的澄清，不创建假确认卡。`respond_casual` 不能承接查询、审查或变更；缺少真实意图内容时明确要求补充，而不是输出泛化模板。

### 实测与自动验证

- 聚焦 Python：direct `248 passed, 31 skipped`；职业与意向 `80 passed`；runner/质量门禁 `121 passed`；`py_compile`、JSON 解析和 `git diff --check` 通过。
- 查询/审查/调稳探针 `3/3`；候选空结果增强 `1/1`；真实“保底够不够” `1/1`；候选不足诚实披露 `1/1`；预算审查与缺内容澄清 `2/2`；计算机候选查询 `2/2`；复合硬预算 `1/1`。
- 复合硬预算实测 exact tools 为 `query_plan -> preview_intent_change`，只生成一个 pending，影响为 `26 个专业组 / 85 条专业志愿`。职业承接实测为 `1/1`：财会命中 `1` 个专业组，体制内/考公命中 `10` 个专业组；重启 Agent 后的最终结果只展示财会真实命中组，并分别用小学教育和药学作为职业方向的强证据示例。
- 最终职业承接证据：`/private/tmp/zhiyuan_400_v274_career_fit_probe_restarted.json`。其他聚焦证据包括 `/private/tmp/zhiyuan_400_v274_open_problem_probes.json`、`/private/tmp/zhiyuan_400_v274_candidate_empty_analysis.json`、`/private/tmp/zhiyuan_400_v274_realistic_safety.json`、`/private/tmp/zhiyuan_400_v274_shortage_focus_recheck.json` 和 `/private/tmp/zhiyuan_400_v274_budget_hard_composite_final.json`。
- 一次使用 runner 默认旧端口 `18290` 的执行被沙箱阻断，属于 environment failure；另一次在 Agent 重启前运行只验证了旧进程。两者均不计入发布证据，最终记录只采用显式后端 `8080` 且加载当前代码的重启后结果。

### 当前未关闭项

- v2.74 尚未在同一清洁环境完整重跑 `13 live + 19 clone-backed final-action`。受影响的 open-quality、realistic-user、explore、review-repair 和 dialogue-derived 包需要先复跑，再执行 19 包最终动作门禁；不能把上述聚焦通过简单相加成发布全绿。
- 保底数量、冲稳保配额、概率缺口、组内复杂 selector、多条/多级 priority，以及结合候选池可报状态、录取率、推荐分和当前位置的院校专业比较仍是能力缺口。
- 普通偏好继续按硬要求判决；不新增软偏好执行通道。新增复合能力仍必须落入一个 typed `PlanChangeSpec`、一个确定 Proposal、一个 pending、一个可回放 planning command 和专用 postcondition，不恢复 3.2 中文执行规则枚举。
- 完整门禁结束后统一删除 990* 测试会话、pending/command、Agent SQLite 历史和候选复制文件；MySQL 只通过 `PURGE BINARY LOGS` 清理封存 binlog，禁止直接删除活动或未封存日志文件。

## 2026-07-16 v2.74 受影响包复验与失败分层

### 本轮补充关闭

- direct 单轮总超时由 `30s` 调整为 `60s`。真实稳定 Proposal 曾在 `36.18s` 正常完成，旧阈值会误杀；原 open-quality 的 4 个超时用例在新阈值下 `4/4`。阈值不继续提高到 90 秒：realistic-user 中有一次上游请求在 60 秒内完全没有首个 HTTP 响应，属于 provider hang，不应继续占用会话资源。
- 明确“仅供参考/不记录/不调整”的 reference 现在由 `preview_intent_change` 直接终止，不创建 pending，也不再经过第二次模型概括。链路从 `5 nodes / 2 LLM requests / 11.2s` 降为 `3 nodes / 1 request / 7.5s`。存在 active pending 时只读查询也不再错误追加“没有生成预览”，原 pending 保持 active。
- “候选和方案里有没有这些学校”在没有正式方案时固定查 `discover_options(mode="eligible")`，结果明确说明只来自候选范围且正式方案尚未生成。隔离回归 `4/4`，最终工具为 `discover_options`，不再先查空方案后猜候选。
- 费用审查现在分别统计“超过本轮学费阈值”和“中外合作项目”，并说明二者可能重叠。零命中夹具会分别返回 `0/0`；正式方案实测返回 `39` 个超预算专业组、`131` 条专业志愿，以及 `6` 个中外合作专业组、`14` 条专业志愿，不再只回答费用阈值而漏掉中外合作目标。
- dialogue-derived 中两个原宽松用例已收紧：`把太贵的那几个先去掉看看` 必须恰好调用一次 `preview_plan_action`、生成一个 `remove_units` pending；`能不能说人话` 在有正式方案且无可重述历史时必须调用一次 `review_plan`，禁止 `clarify_request/respond_casual`。收紧后隔离 `2/2`。

### 受影响包结果

- open-quality 原 4 个超时子集在 60 秒阈值下 `4/4`；explore 完整串行包 `22/22`；职业承接重启后 `1/1`；候选/正式方案混合查询 `4/4`；reference 直返 `1/1`。
- realistic-user 完整串行为 `8/9`。唯一失败是单次上游请求在 60 秒内没有首个 HTTP 响应，没有工具调用或后端副作用，归为 provider timeout residual risk，不增加业务兜底分支。
- review-repair 完整串行初跑 `9/10`，唯一失败是旧运行进程文案“暂时不能直接补或调”未覆盖断言词汇；同时发现并修复费用审查漏报中外合作目标。重启后两个受影响用例严格 `2/2`。这属于分层复验，不能写成同一次 `10/10`。
- dialogue-derived 完整串行初跑 `87/88`，唯一失败是 `能不能说人话` 一次 `UnexpectedModelBehavior`。隔离时运行错误未复现，但暴露 `clarify_request` 假通过；收紧契约和提示后两个相关用例严格 `2/2`。同样不把它改写成一次性 `88/88`。
- 最新 Python：direct `249 passed, 31 skipped`；history/Proposal/base `184 passed`；runner/quality/report `121 passed`。JSON、`py_compile` 和 `git diff --check` 通过。

有效 metrics：`/private/tmp/zhiyuan_400_v274_open_quality_failed4_after_60s.json`、`/private/tmp/zhiyuan_400_v274_explore_serial_60s.json`、`/private/tmp/zhiyuan_400_v274_quality_realistic_serial_60s.json`、`/private/tmp/zhiyuan_400_v274_review_repair_serial_60s.json`、`/private/tmp/zhiyuan_400_v274_dialogue_derived_serial_60s.json`、`/private/tmp/zhiyuan_400_v274_dialogue_two_strict_after_prompt_fix.json`、`/private/tmp/zhiyuan_400_v274_reference_direct_final.json` 和 `/private/tmp/zhiyuan_400_v274_mixed_candidate_plan_grounded.json`。

并发 4 的 `/private/tmp/zhiyuan_400_v274_affected_live` 只产出 `130/152` metrics，包含大量 clone/cleanup 资源竞争和 environment timeout，整组作废，不得计入发布通过率；验收清理时该目录已删除。

### 当前发布状态

- 受影响只读包已完成完整串行或失败子集复验，但仍不是一次清洁环境的全量门禁全绿。
- 下一步执行 19 包 clone-backed final-action gate，重点核对 pending CAS、Proposal apply、planning version、硬要求落库、正式方案 postcondition 和 workspace 双刷新。
- 门禁完成后再统一清理测试 session、数据库 pending/command、Agent SQLite 历史和候选副本；封存 binlog 只使用 MySQL `PURGE BINARY LOGS`。

## 2026-07-16 v2.74 19 包 final-action 门禁收口

### 完整初跑

- 在 Agent `8037`、后端 `8080`、rank `5001`、MySQL 凭据有效的完整拓扑上，使用 `dialog_quality_gate.py --mode final-action` 串行执行全部 19 个 clone-backed 文件。每个 case 均启用 chat-session/state/志愿文件克隆、per-case history/pending/planning-intent 清理和 180 秒响应上限。
- 完整初跑共 `152 step`，结果 `150 passed / 2 failed`；17 个文件全绿。两个失败都发生在 `stepIndex=0`，WebSocket 尚未发起，均为读取大型 `planningState` 后执行 planning-intent 清理的 `TimeoutError`；业务失败、provider/runtime 失败和断言契约失败均为 0。
- 全量 metrics 目录为 `/private/tmp/zhiyuan_400_v274_final_action_gate`。v173 action 扩展包 `11/11`，验证位置 unit 移出、定向低学费替换、移动、院校排名排序和审查承接替换；v179 `10/10`、v183 `13/13`，验证 active pending 追加/替换、no-pending 防护和“替换而非删除”。

### 夹具根因与复验

- runner 的 planning-intent 清理默认超时原为 5 秒，而 session 16 的 `planningState` 单次响应约 `18.4 MB`；空闲读取约 1 秒，但连续 final action 后会偶发超过 5 秒。clone helper 对同一状态已使用 30 秒，因此将该清理 helper 的专用默认上限对齐为 30 秒；没有修改 Agent、后端业务超时或 60 秒 direct/provider 边界。
- 增加单测锁定 planningState/userprofile 两次读取和写入均使用 30 秒夹具上限；runner 单测 `102 passed`，`py_compile` 与 `git diff --check` 通过。
- 原失败 `400-v156-deferred-region-no-plan-change` 隔离复跑 `2/2`：山东要求落库、candidate view 更新、planning version 增长，ordered items/units 保持不变且无 workspace refresh。metrics：`/private/tmp/zhiyuan_400_v274_v156_deferred_region_after_fixture_timeout_fix_valid.json`。
- 原失败 `400-v158-do-not-confirm-means-cancel-active-pending` 隔离复跑 `2/2`：pending 最终 `cancelled`，planning version、ordered items/units 和中外合作要求均未变化。metrics：`/private/tmp/zhiyuan_400_v274_v158_cancel_pending_after_fixture_timeout_fix_valid.json`。
- 证据继续按“完整初跑 `150/152` + 两个原 case 隔离 `4/4`”记录，不相加成一次虚假的全绿数字。当前没有可复现的 final-action 业务缺陷，pending、Proposal apply、planning version、要求落库、ordered-plan postcondition 和 workspace 刷新均已覆盖。

### 当前发布状态

- v2.74 的 19 包 final-action 验证已经完成，原“尚未执行最终动作门禁”不再是未关闭项。
- 整体仍不是一次性 `13 live + 19 final-action` 全绿：realistic-user、review-repair 和 dialogue-derived 仍按完整初跑与隔离复验分层记录，其中 realistic-user 保留一次无首响应 provider timeout 的运行风险。
- 本轮测试状态、候选副本、被替代 metrics 和封存 binlog 已完成清理；当前发布剩余项是保留上述 live 证据分层及 provider timeout 风险，不再包含 final-action 业务缺陷或环境清理待办。能力扩展继续聚焦保底数量、冲稳保配额、概率缺口和候选/方案 grounding 对比。

### 验收清理结果

- MySQL 中 `990*`/`880*` 测试命名空间共删除 pending command `51`、pending confirmation `107`、session extra data `678`、chat message `12604`、planning behavior event `188`、freshness schedule `239`、integration request `0` 和 chat session `171` 条；事务完成后八张表分别复查为 `0`。
- Agent SQLite `chat_session_history` 删除 `279` 行并执行 `VACUUM`，测试 session 复查为 `0`，主库文件由约 `2.5G` 降至 `1.3G`。另两个 stage/semantic 验证库原本即为 `0`，未做无关改写。
- 删除 `449` 个 `session_volunteer_990*`/`session_volunteer_880*` 候选复制文件，原占用约 `2.7G`，复查文件数为 `0`。v2.74 metrics 删除 `21` 份作废或已被后续结果替代的中间证据，保留本节及前两节引用的 `17` 份有效结果。
- MySQL `9.6.0` 使用 `SHOW BINARY LOG STATUS` 确认活动日志为 `binlog.000401`，随后仅执行 `PURGE BINARY LOGS TO 'binlog.000401'`；`binlog.000371` 至 `binlog.000400` 共 `30` 个封存日志已清理，活动 `binlog.000401` 保留。工作盘可用空间由清理前 `8.8GiB` 增至 `43GiB`。
- 清理后的最终聚焦验证为 direct `249 passed, 33 skipped`（全部 skip 均为真实 LLM opt-in）、history/Proposal/base `184 passed`、runner/quality/report `122 passed`；完整 Python 语法编译、examples JSON 结构化解析和 `git diff --check` 通过。测试后再次复查 MySQL、SQLite 和候选副本，仍全部为 `0`。

## 2026-07-16 v2.75 档位最低数量 Proposal 纵切

### 设计与实现

- “当前方案保底至少要有 20 个”不再停留在 `review_plan` 建议层。`PlanChangeSpec.requirements` 新增独立数据域 `domain="admission", key="tier"`，以 `kind="include" + values=["保"] + min_count=20` 表示硬档位覆盖目标；普通偏好仍按硬要求处理，没有新增 soft preference。
- 档位要求只允许 `include` 且必须包含用户明确给出的 `min_count`。`冲/稳/保`、`sprint/stable/protect` 和“保底”等别名在 Agent 与后端分别归一；未知档位、exclude/only_keep 档位以及“多放一些保底”缺少数字时 fail closed，不扫描原话猜数量、不创建 pending。
- 单独提出档位最低数量时冻结当前正式方案总数，`persistTargetCount=false`，通过等量替换满足最低数量，不覆盖 planning state 原总目标；与 `fill_to_count` 同时提出时，在一个 `PlanChangeSpec`、一个后端 Proposal、一个 pending 和一个 planning command 中同时满足总数与档位最低数。
- 后端复用通用 coverage solver，但档位匹配、canonical 校验和展示分域实现，不新增“保底专用中文规则”。目标持久化到 `hardPlanningObjectives.coverageRequirements`，后续 regenerate 继续强制执行；确认后 postcondition 按当前 volunteer model 以志愿或完整专业组计数，并同时校验最终方案命中数和目标持久化。

### 验证与门禁

- 新档位包真实 clone-backed `3/3`：源方案 45 个专业组、保档 19 组；预览等量移出/补入 1 组，确认后仍为 45 组、保档精确达到 20，pending `applied`、planning version 增长、目标持久化、postcondition 和 ordered/review 双刷新全部通过。模糊“保底再多放一些”只追问最低数量和等量替换边界，无 pending。
- 复跑共享 Proposal 包：fill-to-count `11/11`、coverage-preserve `3/3`、priority-rules `4/4`，与新档位包合计 `21/21`。有效 metrics 为 `/private/tmp/zhiyuan_400_v275_tier_minimum.json`、`/private/tmp/zhiyuan_400_v275_fill_to_count.json`、`/private/tmp/zhiyuan_400_v275_coverage_preserve.json` 和 `/private/tmp/zhiyuan_400_v275_priority_rules.json`。
- `dialog_quality_gate.py` 将上述四个已有/新增 Proposal 包补入 `FINAL_ACTION_CASE_FILES`，长期 final-action 入口由 19 包升级为 23 包。发布证据仍按“v2.74 原 19 包门禁 + v2.75 新纳入四包 `21/21`”分层记录，不能写成同一次 23 包全绿。
- 自动验证为 direct `252 passed, 33 skipped`、runner/quality/gate `122 passed`；完整 Maven `581 tests, 0 failures/errors, 4 skipped`，Python 编译、JSON 解析和 `git diff --check` 通过。

### 清理与剩余边界

- 本轮 12 个测试 session 已清理：MySQL 删除 pending command `8`、pending confirmation `8`、extra data `36`、message `67`、behavior event `0`、freshness schedule `12`、integration request `0`、chat session `12`，八表复查为 `0`；SQLite 删除 `12` 行并 `VACUUM`，候选副本删除 `36` 个，均复查为 `0`。
- 仅通过 MySQL `FLUSH BINARY LOGS` 和 `PURGE BINARY LOGS TO 'binlog.000404'` 清理 `binlog.000401` 至 `binlog.000403` 三个封存日志，保留活动 `binlog.000404`；当前工作盘可用空间约 `42GiB`。
- 当前关闭的是“显式档位最低数量”。冲稳保精确等于/最大值配额、比例目标、概率缺口和安全垫联合求解仍未开放；这些目标继续要求 typed schema、确定 dry-run 和专用 postcondition，不能退回泛化“调稳”或 generate/regenerate 假执行。

## 2026-07-16 v2.76 冲稳保精确配额 Proposal 纵切

### 设计与实现

- v2.75 的单档 `min_count` 继续只表示“至少 N 个”。本轮新增独立 `tier_quota_goal={type:"exact_counts", sprint_count, stable_count, protect_count}` 表示三档最终数量精确相等，不把它保存成三条 coverage 下限。
- 冲、稳、保三个非负整数必须全部由用户明确给出，且合计等于最终方案总数。无补齐目标时冻结当前正式方案总数；与 `fill_to_count` 同时出现时，合计必须等于显式或 planning state 解析出的目标。缺项、比例、相对表达和合计不一致都 fail closed，无 pending。
- 后端仅在 Proposal 求解阶段临时复用 coverage solver 做最小补入/等量替换；原始目标独立持久化到 `hardPlanningObjectives.tierQuotaGoal`。regenerate 会同时维护既有 coverage 与精确配额，并在执行后再次验证三档互斥且精确。
- 确认后专用 `tierQuotaResult` 返回期望和实际冲稳保数量、目标持久化状态与 satisfied。首版不与本轮普通 requirements、priority rules、repair goal 混合；最大值、区间、比例和概率缺口仍未开放。

### 验证与门禁

- 完整 Python unit `1630 passed, 33 skipped`；完整 Maven `593 tests, 0 failures/errors, 4 skipped`；examples JSON、Python 编译和 `git diff --check` 通过。
- 新 quota 包真实 clone-backed `3/3`。45 个专业组的 `冲9/稳17/保19` 预览只创建一个 pending，确认后 pending applied、version 增长、独立目标落库、实际三档计数和专用 postcondition 全部通过，并刷新 ordered/review；`9+17+18=44` 与总数 45 不一致时只澄清，无 pending。有效 metrics：`/private/tmp/zhiyuan_400_v276_tier_quota.json`。
- Java 测试额外覆盖配额不满足时的等量替换、锁定冲突、非 fill 注入、专业组多档异常及后续 regenerate。真实 no-op fixture 通过不代表只验证了保存字段。
- 长期 final-action 入口新增 quota 包后由 23 包变为 24 包。证据保持分层：v2.74 原 19 包、v2.75 四包 `21/21`、v2.76 quota `3/3`；尚未执行一次性 24 包全绿门禁。

### 清理与剩余边界

- 本轮两条测试 session 的 MySQL 八类状态、Agent SQLite 历史和 6 个候选副本均已清零；隔离 backend `18080`、Agent `8037` 已停止。最终 metrics 覆盖了两次未进入业务逻辑的环境失败结果，只保留有效 `3/3`。
- `SHOW BINARY LOGS` 仅返回活动 `binlog.000404`，没有封存日志可 purge，因此没有为清理而额外 `FLUSH` 产生新日志。
- 人工检查中的“明确冲稳保精确数量”已关闭；比例分配、单档最大值/区间、概率缺口和与其他新要求的联合配额仍是下一阶段能力缺口。

## 2026-07-16 v2.77 全量发布门禁与人工问题状态

### 已关闭问题

- v2.76 记录的“尚未执行一次性 24 包全绿门禁”已关闭。隔离 backend `18080`、Agent `8037`、rank `5001` 和 MySQL `sales_bot` 上，24 包 clone-backed final-action 一次性 `178/178`，`warnings=[]`、`failures=[]`，最慢 step `22.178s`；当前最终动作 P0 没有可复现业务缺陷。有效证据目录为 `/private/tmp/zhiyuan_400_v277_full_final_action_gate`。
- 当前方案里命名院校/专业的数量、是否有多个或“是不是放多了”，即使用户强调“先别改”，都应走 `query_plan`。本轮“青岛城市学院是不是放多了”完整初跑错走分析/发现工具，补强边界后 focused `1/1`，不再依赖状态摘要样例口头猜数。
- “候选里更稳一点的会计审计”属于推荐候选发现，当前契约是 `discover_options(mode=recommend)`；旧资产要求 `review_plan` 已 hard cut。这里没有恢复 3.2 的专业/院校推荐 Agent，也没有新增中文规则枚举，仍由统一 Agent 选择 typed 工具。
- 普通“倾向/重点关注/优先考虑”继续默认作为硬要求进入确认/Proposal 边界，只有用户明确“仅供参考/不记录/不调整”才是只读 reference；没有恢复 soft preference 执行通道。

### Live 门禁与剩余运行风险

- 13 包 live 完整初跑为 `227/231`，有效证据目录 `/private/tmp/zhiyuan_400_v277_full_live_gate`。四个红 step 中，上述 query 路由和会计候选旧资产已处理；另两个分别为一次 `UnexpectedModelBehavior`、一次本专科纠错首轮误选不支持 filter 的 `discover_options`，原 case 隔离复验分别正确通过。
- 四个原红 step focused 合计 `4/4`，有效 metrics 为 `/private/tmp/zhiyuan_400_v277_live_effect_after_query_prompt_fix.json`、`/private/tmp/zhiyuan_400_v277_live_accounting_asset_hardcut.json`、`/private/tmp/zhiyuan_400_v277_live_readonly_runtime_isolated.json`、`/private/tmp/zhiyuan_400_v277_live_junior_correction_isolated.json`。
- 发布结论必须保持为“完整初跑 `227/231` + 原红项隔离 `4/4`”，不能写成同一次 `231/231`。因此已关闭的是稳定路由缺陷和过期测试契约；仍需观察的是模型首轮路由/运行波动，但它没有阻塞一次性全绿的 final-action P0。

### 自动验证、清理与后续能力

- 修改后完整 Python 为 `1719 passed, 42 skipped`；44 个 examples JSON、Python 编译和 `git diff --check` 通过。完整 Maven 最近同轮 Java 基线为 `593 tests, 0 failures/errors, 4 skipped`，本轮只改 Agent prompt 和一个 JSON case 契约，没有新增 Java 改动。
- final-action 与 live 两轮测试状态均已清零。live 清理删除 MySQL command `8`、pending `37`、extra `259`、message `446`、behavior `8`、freshness `86`、integration `0`、session `86`，八表复查为 `0`；SQLite 删除 `185` 行并 `VACUUM`；runner helper 删除 `231` 个候选副本，复查为 `0`。仅通过 MySQL `PURGE BINARY LOGS TO 'binlog.000425'` 删除 10 个封存日志，最终只保留活动 `binlog.000425`，磁盘可用空间约 `51GiB -> 65GiB`。隔离 `8037/18080` 已停止。
- 当前查询边界是：正式方案事实走 `query_plan`，院校/专业目录、可报候选和推荐名单走 `discover_options`，地域适配判断走 `explore_topic`；裸问“上海的有哪些”且上下文缺少实体类型/数据范围时走 `clarify_request(discovery_scope)`。
- 下一阶段剩余 typed 能力按优先级为：冲稳保比例或单档最大值/区间、概率缺口与安全垫、精确配额和 requirements/priority 的联合求解、复杂 selector、多条或多级 priority。不得为覆盖这些表达回退到中文规则罗列；每项继续要求一个 `PlanChangeSpec`、一个 Proposal、一个 pending、一个 command，以及确定 dry-run、持久化和专用 postcondition，未支持组合整体 fail closed。
