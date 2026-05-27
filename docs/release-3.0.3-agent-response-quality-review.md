# Release 3.0.3 Agent Response Quality Review

本文记录 `3.0.3` Agent 回复质量的文本级评审。重点不是只看“快不快”或“短不短”，而是看用户是否拿到了可理解、可决策、边界清楚的回复。

## 1. 评审输入

本轮基于真实 WebSocket 场景回归输出：

- case 文件：`zhiyuan-agent/examples/dialog_regression_303_effect_perf_cases.json`
- 完整回复输出：`/private/tmp/dialog-regression-303-current-text.json`
- 评估时间：2026-05-25

运行结果：

| 指标 | 结果 |
| --- | ---: |
| steps | 13 |
| failedSteps | 0 |
| median elapsed | 2.319s |
| p95 elapsed | 3.616s |
| max elapsed | 4.922s |

结论概览：

- Plan 类结构化快路径已经解决了早期“方案情况如下”但内容单薄、格式难懂的问题。
- 高副作用动作的 `preview -> confirm -> apply` 边界整体稳定，没有发现未确认直接改方案。
- 局部查询、移动、加入、排序的回复已经足够快，但部分回复还缺少影响面说明。
- Explore 和 Intent 仍是主要质量风险：回复有模板感、个别用户信息没有被充分利用、内部层级词有外露。
- 多模型只读/预览对照中回复高度一致，说明这批 case 主要在测结构化快路径稳定性，不能代表开放式生成质量已经充分优秀。

## 2. 评分口径

每条回复按 1 到 5 分人工评估：

| 维度 | 说明 |
| --- | --- |
| 正确性 | 是否答对用户问题，事实和边界是否准确 |
| 完整度 | 是否包含结论、依据、影响和下一步 |
| 自然度 | 是否像正常顾问表达，是否有模板感 |
| 可行动性 | 用户看完是否知道下一步怎么做 |
| 边界清晰度 | 是否区分只读、预览、确认和已执行 |

硬性问题：

- 内部术语外露。
- 把待确认说成已生效。
- 用户要求只分析，却触发工作台联动或 pending 执行。
- 用户已经给出的信息被忽略。

## 3. 逐 Case 评审

### 3.1 方案状态查看

用户输入：

```text
看看现在的方案，给我一个结构化一点的结论
```

实际回复：

```text
方案已经有了，目前有 94/96 个志愿。
- 梯度分布：冲66 / 稳28 / 保0。
- 审查提醒：风险 3 项，提醒 5 项。
- 数量缺口：当前志愿数量不足，还差 2 个。
- 需要关注：冲区占比过高且保区占比过低；本省保底志愿数量不足。
- 前排示例：青岛理工大学-建筑学(中外合作办学)(与韩国光云大学合作)(冲)第1位；青海民族大学-土地资源管理(中外合作办学)(与波兰波兹南生命科学大学合作，文实校区)(冲)第2位；哈尔滨理工大学-人力资源管理(冲)第3位。
- 当前偏好：偏好专业=经济与贸易类,金融学类,外国语言文学类等8项；排除专业=中医学类,医学技术类；偏好地域=内蒙古,北京,天津等9项
- 承接情况：当前方案里较贴近的有55个，明显冲突的有0个。
- 贴近偏好的例子：青岛理工大学-建筑学(中外合作办学)(与韩国光云大学合作)(冲)第1位（匹配偏好专业:建筑类）；喀什大学-建筑学(东城校区)(冲)第5位（匹配偏好专业:建筑类）
你可以继续看审查详情，或者告诉我想按地域、专业、稳妥程度怎么调。
```

评分：正确性 5，完整度 5，自然度 3，可行动性 4，边界清晰度 5。

判断：

- 相比早期只有“已填满、冲稳保、前几个志愿”的薄回复，本轮信息明显更完整。
- 关键结论能被用户理解：数量不足、保底不足、风险提醒、偏好承接都有说。
- “当前偏好：偏好专业=...”仍偏系统化，但已经没有 `@1`、`volunteerId` 等内部格式。

建议：

- 保留当前结构。
- 后续可把“当前偏好”改成更自然的表达，例如“你目前更看重经贸、金融、外语等方向，排除了中医、医学技术等方向”。

### 3.2 局部查询

用户输入：

```text
青岛城市学院相关专业是不是有多个，先帮我判断一下，不要直接改方案
```

实际回复：

```text
当前排序方案里共命中了 7 条符合“院校:青岛城市学院”的志愿。下面仅展示前 5 条示例：青岛城市学院-法语（冲，录取率1%）；青岛城市学院-国际经济与贸易（冲，录取率1%）；青岛城市学院-俄语（冲，录取率1%）；青岛城市学院-德语（冲，录取率1%）；青岛城市学院-商务英语（冲，录取率1%）
```

评分：正确性 5，完整度 4，自然度 4，可行动性 3，边界清晰度 5。

判断：

- 正确回答了“是不是有多个”，没有触发方案修改，也没有出现无联动卡片。
- 示例包含学校、专业、冲稳保和录取率，用户能理解。
- 缺少下一步引导，例如“如果要集中处理这个学校，可以告诉我保留哪几个或移动到哪个位置”。

建议：

- 查询类可以增加一句轻量下一步，但不能变成待确认动作。

### 3.3 按名称移动志愿预览

用户输入：

```text
把青岛城市学院的国际经济与贸易改到第3位
```

实际回复：

```text
已定位到 青岛城市学院-国际经济与贸易，当前在第36位，会移动到第3位。 需要你确认后才会执行。
```

评分：正确性 5，完整度 4，自然度 4，可行动性 5，边界清晰度 5。

判断：

- 定位对象、当前位置、目标位置、确认边界都清楚。
- 适合短回复，因为用户明确要求执行具体动作。

建议：

- 可微调空格和标点。
- 如果移动会导致审查状态过期，可以补一句“移动后需要重新审查”，但不要让预览回复过长。

### 3.4 按名称加入候选预览

用户输入：

```text
把河南农业大学的建筑类加进来
```

实际回复：

```text
已在候选里定位到 河南农业大学-建筑类，会加入当前方案。 需要你确认后才会执行。
```

评分：正确性 4，完整度 3，自然度 4，可行动性 4，边界清晰度 5。

判断：

- 确认边界清楚。
- 缺少“加入到哪里”“是否已经在方案里”“是否会导致数量超出目标”的影响说明。
- 如果候选存在多个同名或专业组变体，当前文案需要依赖执行层已经唯一定位。

建议：

- 加入类预览应补充唯一定位结果和数量影响，例如“当前方案 94/96，加入后 95/96”。
- 已存在场景继续保持 `no_change`，不要生成 pending。

### 3.5 专业组整体移动预览

用户输入：

```text
把第4个专业组移到第2位
```

实际回复：

```text
会整体移动第 4 个专业组：山东交通学院第201组(中外合作办学组)，组内共 3 个专业，目标是移动到第 2 个专业组位置。这里的“第几个”按专业组顺序计算，不是按单条志愿位置计算；执行后该组内专业会保持连续，组内专业顺序不变。 需要你确认后才会执行。
```

评分：正确性 5，完整度 5，自然度 4，可行动性 5，边界清晰度 5。

判断：

- 这是本轮质量最好的高副作用预览回复之一。
- 对专业组模式的关键歧义解释清楚：按组移动，不按单条志愿移动。
- 明确组内专业数量、组内顺序保持不变、确认后执行。

建议：

- 保持当前逻辑。
- 后续同类删除专业组也应对齐这个解释密度。

### 3.6 专业组整体移动确认

用户输入：

```text
确认
```

实际回复：

```text
已将该专业组移动到第 2 位，方案顺序已更新。
```

评分：正确性 5，完整度 4，自然度 5，可行动性 4，边界清晰度 5。

判断：

- 确认后执行语义清楚。
- 工作台刷新已经通过 followup 触发。
- 可补充“审查状态已变为待重新审查”，但这类信息也可以留在工作台状态里，不一定放在回复里。

建议：

- 保持短确认回复。
- 如果前端审查状态有明显变化，可在回复末尾追加简短提醒。

### 3.7 方案排序预览

用户输入：

```text
按院校层次排序
```

实际回复：

```text
会按院校层次重新排序当前方案，排序会实际改变方案顺序和导出顺序，并让审查状态进入待重新审查。 需要你确认后才会执行。
```

评分：正确性 5，完整度 4，自然度 4，可行动性 5，边界清晰度 5。

判断：

- 已说明排序会实际改变方案和导出顺序，符合“交互稍重一点，需要确认”的产品要求。
- 已说明审查状态会变为待重新审查。
- 还可以补充排序方向：院校层次按排名升序或层次优先，而不是由用户猜。

建议：

- 加一句“院校排名越靠前越优先”，保持一句话内完成。

### 3.8 职业方向承接分析

用户输入：

```text
当前方案对体制内稳定就业方向承接得怎么样，先不要改方案
```

实际回复：

```text
**分析结论**
- 我先帮你做了一个方向对比分析。

**当前判断**
我先帮你把“体制内/考公导向”和“稳定就业导向”放在一起看一眼：
  初步判断：
  - 这类问题更适合先看你本人更适合哪条路径，再看当前方案更偏向哪一边。
  - 你的当前选科是物理、历史、地理，这至少没有把这条方向直接挡住。
  需要补充留意：
  - 当前分数段更适合优先保证就业确定性，选学校和专业时先看就业承接，不把深造当第一目标。
  可以继续展开看的方向：
  - 候选里和“体制内/考公导向”更相关、但还没进方案的大约还有 46 个机会。
  - 候选里和“稳定就业导向”更相关、但还没进方案的大约还有 62 个机会。
  如果继续了解：
  - 如果你愿意，我可以接着单独展开其中一个方向，专门看它和你当前方案到底有多匹配。
  - 如果你现在主要卡在“自己更适合哪类路径”，后面也可以结合 MBTI 和霍兰德职业兴趣测评再细看。

**下一步**
- 如果你愿意，我可以接着单独展开其中一个方向，再看它和当前方案到底有多匹配。
```

评分：正确性 3，完整度 3，自然度 2，可行动性 3，边界清晰度 5。

判断：

- 边界正确：只分析，没有改方案，没有触发工作台联动。
- 核心问题是用户问“当前方案承接得怎么样”，回复没有直接给出“好/一般/弱”的结论，也没有列当前方案内承接该方向的具体数量或示例。
- “我先帮你做了一个方向对比分析”“如果你愿意...”重复，模板感较强。
- 提到了候选中未进方案的机会，但当前方案内部承接证据不足。

建议：

- 这是需要优先修的 Explore 质量问题。
- 回复应改为“结论先行 + 方案内证据 + 候选补充机会 + 不改方案边界”。
- 示例目标形态：

```text
当前方案对体制内/稳定就业方向的承接偏弱到中等。方案里有 X 个更贴近这类方向的志愿，主要集中在 A/B/C；但当前冲区占比高、保底不足，稳定就业导向下需要优先补稳保和可考公口径更清楚的专业。候选里还有体制内相关约 46 个、稳定就业相关约 62 个机会。这里只做分析，不会改你的方案。
```

### 3.9 只读分析后用户说确认

用户输入：

```text
确认
```

实际回复：

```text
我这边没有上一轮待确认的方案动作。你可以直接说想生成方案、审查方案或怎么调整，我会先说明影响，确认后再执行。
```

评分：正确性 4，完整度 4，自然度 4，可行动性 4，边界清晰度 5。

判断：

- 从 pending 安全角度是正确的：上一轮是只读分析，不应把“确认”误执行为方案调整。
- 但结合上一轮回复中“如果你愿意，我可以接着展开”这句话，用户说“确认”也可能是在确认继续展开，而不是确认方案动作。

建议：

- 可保持不执行动作，但文案更贴近上下文，例如“上一轮只是分析，没有待执行的方案动作。如果你想继续展开，可以说‘展开体制内方向’或‘展开稳定就业方向’。”

### 3.10 专业对比

用户输入：

```text
法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好
```

实际回复：

```text
这轮先按通用维度看 法学 vs 财政学。当前没有拿到可用的个性化量化评分，所以不直接说系统分数谁更高。

- 当前会话还没有完整分数、选科、省份和性别信息。
- 法学（法学类）：就业路径主要看法律职业、公检法、司法行政、纪检监察、合规风控、公共事务等方向；门槛是法考、案例训练、文字表达和逻辑论证要求较高；稳定性上，考公相关岗位覆盖较多，但早期路径受法考、实习和平台影响明显；试错成本上，专业壁垒清楚，上限不低；如果兴趣不强，前期试错成本偏高。
- 财政学（财政学类）：就业路径主要看财政、税务、审计、预算管理、银行、国企财务和政府财会类岗位；门槛是需要财税基础、政策理解和数据处理能力，证书压力相对分散；稳定性上，岗位口径清楚，考公考编、国企和企业财务都能承接；试错成本上，路径更可预期，对普通家庭降低试错成本更友好。
- 选择建议：稳就业、可预期路径和降低试错成本优先时，先重点看财政学；强兴趣、长期壁垒和上限优先时，可以重点看法学。最终还要结合具体学校层次、城市、录取概率和是否愿意投入对应训练。
- 下一步可以把目标地区和可接受学校层次加进来，再看它们在当前方案和候选里的实际院校质量、录取概率和城市机会。
```

评分：正确性 4，完整度 5，自然度 4，可行动性 5，边界清晰度 5。

判断：

- 回复不再单薄，给出了就业路径、门槛、稳定性、试错成本和选择建议。
- 只分析、不记偏好的边界正确。
- 问题在于用户输入已经说“普通家庭女生”，回复却说“没有完整...性别信息”。这里应该区分“会话画像缺失”和“本轮用户已经提供的信息”。

建议：

- 修正表述为“本轮先按你提到的普通家庭女生来做通用判断；因为还缺分数、选科、省份，所以不做系统量化评分。”
- 这类修复属于回复组织，不应改变意向状态。

### 3.11 Intent 预览

用户输入：

```text
我倾向法学和财政学，但护理不要
```

实际回复：

```text
这个想法我先整理成待确认内容。如果你愿意，我可以继续帮你看看现在这份方案和它有多匹配。
- 待确认偏好专业（level3）：法学
- 待确认偏好专业（level3）：财政学
- 待确认排除专业（level3）：护理学
```

评分：正确性 4，完整度 3，自然度 2，可行动性 4，边界清晰度 5。

判断：

- 确认前没有写入，边界正确。
- `level3` 是明显内部术语，用户不应看到。
- “如果你愿意，我可以继续帮你看看...”放在待确认项前面，会弱化“请确认”的动作指引。

建议：

- 必修：去掉 `level3`，改成用户语言。
- 建议目标文案：

```text
我先把这条偏好整理成待确认内容，确认后才会作为后续筛选和方案调整参考：
- 偏好方向：法学、财政学
- 排除方向：护理学
如果确认，请回复“确认这个偏好”；如果要改，可以直接说想保留或删除哪一项。
```

### 3.12 Intent 确认

用户输入：

```text
确认这个偏好
```

实际回复：

```text
我已经按你的要求把候选结果收紧了，你现在可以直接去看筛选后的结果。要是你愿意，我也可以继续帮你看看这份方案里还有没有不符合这条要求的地方。
```

评分：正确性 3，完整度 3，自然度 4，可行动性 4，边界清晰度 4。

判断：

- 已确认偏好的语义基本正确。
- “把候选结果收紧了”可能说得过满：如果后端只是记录偏好并刷新候选展示条件，这句话会让用户理解为候选池已经被永久缩小。
- 回复没有复述已确认的偏好和排除项，用户难以核对刚刚生效的内容。

建议：

- 改成“已记录为后续筛选和方案调整参考”，并复述本次确认项。
- 如果会触发候选刷新，再说“候选展示会按这条偏好更新”。

### 3.13 无 pending 确认保护

用户输入：

```text
确认
```

实际回复：

```text
我这边没有上一轮待确认的方案动作。你可以直接说想生成方案、审查方案或怎么调整，我会先说明影响，确认后再执行。
```

评分：正确性 5，完整度 5，自然度 4，可行动性 5，边界清晰度 5。

判断：

- 安全边界正确。
- 没有误执行历史 pending。
- 文案可接受。

建议：

- 保持。
- 如果上一轮是 Explore 的“可继续展开”，可以用上下文感知版本替代这条通用 guard。

### 3.14 新会话 Explore / 专业对比 / Intent 预览

用户输入：

```text
我是山东450分，物理历史地理，想先看看适合什么方向
网络与新媒体和跨境电商哪个更适合我
那把网络与新媒体作为优先方向，跨境电商也可以考虑
```

实际回复特征：

```text
结合你的情况，我先做个初步判断：
...
```

评分：正确性 4，完整度 5，自然度 4，可行动性 5，边界清晰度 5。

判断：

- 首轮 Explore 仍然是最慢一轮，约 `46.9s`，但回复已经从“薄判断”变成完整的方向分析，不再只是单句结论。
- 第二轮专业对比能承接上一轮的山东、450 分、物理历史地理，不再误说“缺少分数、选科和省份”。
- 这轮新增的专业画像补强后，`网络与新媒体 vs 跨境电子商务` 不再落到“当前没有沉淀专门画像”的泛化答法，而是能给出新闻传播学类与电子商务类的路径、门槛、稳定性和试错成本。
- 第三轮 Intent 预览会把“跨境电商”归一为“跨境电子商务”，并正常输出待确认方向，语义边界仍然正确。

建议：

- Explore 开放问法继续优化首响和总耗时，重点不是再短，而是把用户已经给出的分数、选科和方向约束更稳地承接进去。
- 专业对比画像可以继续扩，但不建议写死单组固定模板，应继续沿用 category profile 机制。

## 4. 主要问题清单

### P1 需要优先修

1. Intent 预览暴露 `level3`。
   - 影响：用户看不懂，属于内部术语外露。
   - 建议：所有专业层级统一渲染为“专业方向/专业类/专业”，不要暴露目录层级名。

2. Explore 职业方向承接没有直接回答“当前方案承接得怎么样”。
   - 影响：用户问方案承接，回复偏成泛方向分析。
   - 建议：补“方案内承接数量、示例、短板、候选补充机会”。

3. 专业对比忽略本轮用户提供的“女生”信息。
   - 影响：用户会觉得系统没有理解问题。
   - 建议：把本轮显式事实纳入回复，即使会话画像缺失也不应说该信息不存在。

4. Intent 确认“候选结果收紧”语义偏强。
   - 影响：可能把“记录偏好/刷新展示”误解成候选池被永久改变。
   - 建议：改为“已记录为参考，候选展示会按偏好更新”。

### P2 可排期优化

1. 方案状态里的偏好摘要偏系统化。
2. 加入候选预览缺少方案数量影响。
3. 排序预览缺少排序方向说明。
4. 局部查询缺少下一步引导。
5. 只读分析后用户说“确认”时，guard 文案可以更贴合上一轮上下文。
6. 预览 / 举例类回复只给个例不够，要再补学校层次、冲稳保、专业热度、数量缺口等关键分布，给用户更完整的结构判断。

## 5. 对模型对照的解释

四模型只读/预览 benchmark 中，多数回复文本完全一致或高度一致。这不是模型质量无差异，而是说明：

- 这些 case 多数走结构化 fast route。
- 回复主要由本地 renderer 或工具结果生成。
- 当前多模型对照主要验证 fast route 稳定性和性能，不足以评价开放式 Explore/Intent 的表达质量。

后续模型质量对照需要补充这些开放场景：

- 用户给出家庭、城市、分数、性格约束后做职业路径分析。
- 多个专业方向取舍，不只两个标准专业名。
- 用户先表达软偏好，再追加硬排除，再追问对当前方案影响。
- 用户用简称、模糊表达或非标准专业名称提问。
- 用户要求“不要改方案，只解释为什么”。

## 6. 下一步落地建议

本轮先完成文本评审，不直接改逻辑。建议下一步按以下顺序进入设计和实现：

1. 修 Intent renderer：去掉 `level3`，确认前后文案改成用户语言。
2. 修 Explore career renderer：结论先行，补方案内承接证据。
3. 修 major compare renderer：使用本轮用户显式事实，避免误报“性别信息缺失”。
4. 给 Plan add/sort/query 补轻量影响说明，保持短回复但不丢关键事实。
5. 补充对应 case 断言：禁止 `level3`，要求职业承接出现“当前方案/承接数量或示例”，要求专业对比不出现“缺少性别信息”。

## 7. 修复设计

本轮开始落地 P1 修复，范围如下：

| 问题 | 修复入口 | 设计 |
| --- | --- | --- |
| Intent preview 暴露 `level3` | `ChatService._normalize_pending_intent_reply` / `_normalize_user_facing_terms` / `intent_state_tool._LABEL_MAP` | 在用户可见回复里清理目录层级字段，把“待确认偏好专业（level3）”改成“待确认偏好专业/专业类/具体专业”等用户语言，保留具体专业名和确认边界 |
| Intent confirm “候选结果收紧”语义偏强 | `intent_response_tool.render_intent_state_update` | 确认后表达为“已记录为后续筛选和方案调整参考”，候选数量只作为展示更新说明，不暗示候选池被永久改变 |
| 职业方向承接没有直接回答方案承接 | `explore_direction_tool.preview_direction_comparison_from_request` | 多方向比较先给“当前方案承接强弱”结论，再列方案内承接数量、示例和候选机会；只读场景仍不改方案、不写 pending |
| 专业对比忽略本轮用户事实 | `major_compare_reply_renderer.render_missing_weight_major_compare_reply` | 会话画像缺失时仍读取本轮用户话术里的“普通家庭/女生”等约束，避免说“缺少性别信息” |
| 方案审查未进入 3.0.3 quality 主 case | `dialog_regression_303_effect_perf_cases.json` | 增加“帮我审查一下当前方案”审查 case，校验审查回复、review 工作台刷新和内部字段屏蔽 |
| 方案审查回复一整段长句 | `analysis_handlers._build_review_summary` | 审查结果改为“审查结论 + 风险提醒 + 主要问题 + 典型涉及 + 下一步建议”的短要点，不改变审查执行和 review 刷新 |
| 职业方向承接回复重复 | `explore_direction_tool.preview_direction_comparison_from_request` | 多方向比较的顶部结论只出现一次，“当前判断”展开分方向承接、示例和候选机会，“下一步”不重复塞在判断段内 |
| 待确认意向后追问影响又回完整 Agent | `ChatService.pending_intent_impact_fast_route` / `intent_relation_tool` | 已有 `planEditCache` 待确认内容时，用户问“这个偏好会影响当前方案吗”直接做只读影响分析；不确认、不发工作台联动、不改方案 |
| Intent 影响说明泛化句太重 | `intent_relation_tool.enrich_plan_relation_analysis_from_state` | 已拿到真实当前方案或候选命中时，去掉“我先帮你看看 / 顺手看看”这类泛化句，优先呈现贴近、冲突和候选机会 |
| 结构化影响文本被重复套标题 | `intent_response_tool.render_intent_analysis_text` | `impact_text` 已经是 Markdown 标题块时直接嵌入，不再额外包一层“当前判断” |
| 只读分析后用户说“确认”文案生硬 | `ChatService._build_no_pending_confirmation_guard_reply` | 无 pending 时仍不执行任何动作；若上一轮是职业方向分析、专业对比或局部查询，则按上一轮只读上下文提示下一步，而不是统一回复“没有上一轮待确认的方案动作” |
| Intent 确认后用户难以核对生效内容 | `intent_response_tool.render_intent_state_update` | 确认成功后从 `merged` 中提取专业、院校、地域和发展方向的正/负向条目，补充“本次确认内容”，让用户能核对刚刚生效的偏好/要求 |
| 专业对比缺少结构化输出 | `major_compare_reply_renderer.render_missing_weight_major_compare_reply` | 无量化权重时保持通用比较，但改成“会话参考 / 专业A / 专业B / 选择建议 / 下一步”的分段结构，提升可扫读性，不改 compare 路由和判断逻辑 |
| 专业对比仍有系统化术语 | `major_compare_reply_renderer.render_missing_weight_major_compare_reply` | 把“个性化量化评分 / 系统分数 / 系统评分”改成“还没有完整结合分数、省份、选科和方案位置，先做方向判断”，更接近用户语言 |
| 预览 / 举例回复信息密度不够 | `plan_query_tool` / `planning_workflow_tool` / `explore_direction_tool` 相关预览 renderer | 预览类回复除了对象和代表样本，还要补学校层次、冲稳保、专业热度、数量缺口等关键分布，避免只给个例没有整体结构 |
| 院校层次摘要仍可能像内部字段 | `plan_query_tool._format_tier_summary` | 分布摘要不再把 `schoolRank` 数字直接塞进“学校层次”，改为“院校排名约区间 + 公办/民办/双一流等标签 + 专业热度/计划数” |
| 批量评估工具无法识别薄回复 | `dialog_case_evaluation_report.py` | case 级评分补充 `qualityViolations`、`distributionCoverage` 和 `verdict`，把内部术语外露、确认边界冲突、预览缺少关键分布纳入自动标记 |
| 本地/降级场景 Intent 确认可能丢 pending | `ChatService._load_pending_intent_confirmation` / `_extract_pending_intent_confirmation_from_history` | 后端 `planEditCache` 仍为主路径；读不到时从 Agent 历史中的 Intent preview 工具调用恢复待确认 payload，避免下一句“确认这个偏好”误走无 pending guard |
| Intent 确认回复过度承诺候选刷新 | `intent_response_tool.render_intent_state_update` | 无候选数量事实时不再说“候选展示会按这条要求更新、现在可以去看候选结果”，改成“后续查看候选和方案时会按这条要求作为参考” |
| Intent preview item 文案像已生效 | `intent_state_tool._build_select_items` / `dialog_case_evaluation_report.py` | 待确认卡片条目统一使用“确认后，将把...”条件式表达；评估工具新增 `pending_intent_effective_wording` 门禁，防止待确认内容再用已生效语气 |
| 审查后续调整预览耗时过长 | `plan_fast_router.resolve_plan_fast_route` / `ChatService.plan_fast_route` | 用户在审查后明确说“针对最严重的问题，先给调整预览，不要执行”时，不再进入完整 Agent 自由反复读方案；高置信识别为 `analyze_adjustment` 或补齐类 `preview_compensation`，直接走既有 `plan_next_action -> execute_plan_action`，只读分析不挂 pending，可执行补齐仍按原确认协议处理 |

不在本轮做：

- 不改变方案排序、移动、加入、删除的执行语义。
- 不绕过 `preview -> confirm -> apply`。
- 不为开放式 Explore 引入新的模板短路；只修已有 renderer 的事实组织和用户语言。
- 不把用户尚未确认的 Intent preview 直接应用到筛选、候选或方案。

## 8. 实施记录

已完成：

- Intent preview 回复清理 `level1/level2/level3`，用户侧统一展示为“待确认偏好专业 / 待确认排除专业”等用户语言。
- Intent confirm 回复保留“确认后已记下”的语义，但不再说“候选结果收紧”，改成“作为后续筛选和方案调整参考”。
- 职业方向多方向承接分析补上结论先行：先说当前方案整体承接强弱、方案内相关志愿数量和示例，再说候选机会。
- 专业对比缺少量化评分时，能使用本轮用户输入里的“普通家庭 / 女生”等约束，不再误报“缺少性别信息”。
- 方案局部查询与候选查询补充轻量下一步引导：命中结果后会补一句“下一步如果要处理这些志愿/机会，可以怎么继续”，但不改变只读边界，也不自动进入待确认动作。
- `add_units` 预览补充当前方案数量影响：能读取到当前排序方案总数时，会在确认前说明“当前方案已有 X/Y，确认后预计增加 N 个”，让用户知道这次加入对方案数量的实际影响。
- `sort_ordered_plan` 预览补充排序方向说明：录取率默认“录取率低的排在前面”，院校层次默认“排名靠前的排在前面”，推荐系数默认“推荐系数高的排在前面”；仍然只生成预览，确认后才改顺序。
- 方案操作预览继续补足影响面：普通志愿移动会说明方案顺序和导出顺序变化，候选加入会说明方案数量和导出内容变化，移出会说明数量减少；这些预览都会明确审查状态会进入待重新审查。
- 只有 `plan_next_action` 形成排序 pending、还没有走 `execute_plan_action` 时，也会补齐排序方向和待重新审查说明，避免用户只看到“会按院校层次排序”但不知道具体怎么排。
- 无 pending 的“确认”保护补充上下文文案：职业方向只读后会提示可继续展开具体方向，专业对比只读后会提示可记成偏好或看对方案影响，局部查询后会提示可移动/删除/加入/排序；全部保持不执行、不联动。
- 无 pending 的“确认”保护继续补强：除工具调用记录外，也会从上一轮 assistant 文本识别职业方向分析、专业对比和局部查询，避免快路径或降级场景只保存文本时退回泛化提示。
- Intent 确认回复补充“本次确认内容”：专业、院校、地域和发展方向的偏好/排除项会被复述给用户，避免只说“已记录为参考”但用户无法核对。
- Intent 确认回复继续结构化：确认后改成“记录结果 / 本次确认内容 / 后续使用 / 候选结果 / 下一步”的短要点，保留用户可核对内容，同时避免“候选展示会按要求更新”这种过度确定表达。
- 专业对比 fallback 改成结构化分段输出：保留通用比较逻辑，但把会话参考、两个专业画像、选择建议和下一步拆开，减少一整段平铺文字带来的“太薄”感。
- 专业对比 fallback 文案去系统化：不再出现“个性化量化评分 / 系统分数 / 系统评分”，改成“还没有完整结合分数、省份、选科和方案位置，先给方向判断”。
- 新会话补充验证 `880403`：`山东450分、物理历史地理 -> 网络与新媒体 vs 跨境电商 -> 偏好确认` 三步通过；专业对比和 Intent 预览都能正确承接上下文并输出更具体的专业类画像。
- `dialog_regression_303_effect_perf_cases.json` 补充方案审查 quality case，并收紧 Intent / Explore / 专业对比断言。
- 方案审查执行结果改为结构化要点，避免“风险、提醒、典型涉及”被压成一整段长句。
- 职业方向多方向承接回复去掉重复结论和重复下一步提示，保留当前方案承接、分方向数量、方案示例、候选机会和测评建议。
- 待确认意向后追问“这个偏好会影响当前方案吗”时，直接基于待确认内容和当前方案/候选事实生成影响说明，不再进入完整 Agent；回复明确“尚未确认、确认前不生效、不改方案”。
- Intent preview 卡片文案去掉“候选结果收紧”“专家推荐”等用户容易误解或不自然的表达。
- Intent 影响分析去掉已有真实命中情况下的泛化开场句，避免回复显得像固定模板。
- Intent 专业意向的源头标签也改成用户语言：内部仍保留 `level1/level2/level3` 结构用于存储、编码和候选过滤，但用户可见内容只展示“专业门类 / 专业类 / 具体专业 / 偏好专业 / 排除专业”，避免后续绕过 ChatService 清洗时再次露出层级字段。
- Intent pending 增加 Agent 历史兜底：后端 `planEditCache` 写入/读取失败时，从历史中最近一次 `preview_current_*_intent_confirmation` 工具调用恢复待确认 payload，保证“确认这个偏好/要求”仍能承接上一轮。
- Intent 历史兜底不会复活已处理 pending：历史中如果已经出现 `update_volunteer_intent_state` 确认/拒绝结果，会清掉更早的 preview pending，避免用户后续再次“确认”重复应用旧意向。
- Intent 确认回复收紧：没有实际候选数量事实时，只说明“后续查看候选和方案时会按这条要求作为参考”，不再暗示候选已经刷新。
- Intent preview 卡片条目继续收紧：专业、院校、地域和发展方向的待确认条目统一改成“确认后，将把...”条件式表达，避免在“确认前不会生效”的说明之外，单个条目仍让用户误以为已经记下。
- case 级质量评分工具补强：`dialog_case_evaluation_report.py` 不再只按字数和延迟粗略打分，会输出 `qualityViolations`、`distributionCoverage` 和 `verdict`；预览类回复如果只给个例、没有覆盖至少两类关键分布，会标记为 `thin_preview_distribution`。
- case 级质量评分工具新增待确认意向语气门禁：待确认上下文里如果出现没有“确认后”条件的“把 X 记成/作为/后续都会按要求”等已生效表达，会标记为 `pending_intent_effective_wording`。
- 方案/候选查询的分布摘要继续用户化：院校部分优先展示双一流、公办/民办等标签和“院校排名约 X-Y”的范围，专业部分优先展示专业热度、计划数、招生计划等信息，避免把裸 `schoolRank` 数字说成“学校层次”。
- 职业方向只读回复结构收口：不再把“当前判断”里再嵌“初步判断 / 需要补充留意 / 可以继续展开”，改为“方案承接 / 需要留意 / 候选机会 / 下一步”的平铺结构；只改展示层，不改方向识别、候选/方案计算和只读边界。
- 专业对比画像补强后，`network vs ecommerce` 这类场景不再只返回“当前没有沉淀专门画像”，而是可以落到“内容策划 vs 电商运营”的具体比较。
- 主对话运行时不再暴露 `load_skill` 等技能管理工具，只保留技能边界摘要；这是减少开放式 Explore 额外工具轮次的性能修复，不改变用户侧回复结构，也不新增模板化短路。
- 职业方向只读回复补充“本次边界”：明确这轮只是方向分析，不会自动修改偏好、当前方案或方案顺序；如果后续要按方向调整方案，仍会先给预览、确认后再执行。
- 方案调整确认后的完成回复补充下一步：移动、删除、加入、替换和排序在执行成功后，如果后端结果没有说明审查/导出影响，会补充“方案/导出已同步更新、审查状态已进入待重新审查、可到方案区查看并必要时审查”，减少用户只看到“已更新”但不知道后续如何处理的情况。
- 剩余 `needs_review` 文案继续收口：排序预览改为“动作 / 排序方式 / 执行影响 / 确认”的要点结构；无 pending 的职业方向确认保护补充“继续分析 / 调整方案 / 查看方案 / 不确定下一步”四类出口；已有偏好提示合并同类项并明确不会重复写入或改方案；专业对比只读回复补充“本次边界”，避免用户误解为已经记成偏好。
- 开放式质量 case 继续扩展：`dialog_regression_303_open_quality_cases.json` 从 3 个 case 扩到 7 个 case，新增局部查询后确认保护、推荐系数排序预览、非“法学/财政学”的专业对比、考公/稳定就业/读研三方向承接。目标是验证回复质量不是只对主 effect/perf 固定样例有效，同时继续要求只读不联动、预览不执行、不暴露内部术语。
- 真实 open-quality 扩展回归暴露三方向职业问法性能退化：`当前方案对考公、稳定就业和读研三个方向分别有什么支撑和短板` 因为缺少“支撑/短板”只读语义识别，回落完整 Agent，耗时约 `17.2s`。已把“支撑/短板”纳入 `career_direction_fast_route` 强只读分析触发词，仍保留“记偏好 / 改方案 / 确认”等高副作用拦截。
- 待确认意向文案进一步收口：用户可见回复统一从“确认前不会正式生效 / 我再正式生效”改为“确认前不会写入后续参考 / 我再写入后续参考”。这次只调整待确认预览、待确认影响追问和旧回复清洗，不改变确认后写入、候选刷新或方案调整执行链路。
- 无 pending 的查询确认保护继续补充边界提示：只读查询后用户回复“确认”时，回复会明确“不会执行移动、删除、加入或排序，也不会改动当前方案”，然后给出可继续的方案/候选处理入口，避免保护回复过短或让用户误以为确认会生效。
- 审查后续调整预览慢链路收敛：真实探针中 `帮我审查一下当前方案 -> 最严重的问题是什么 -> 针对最严重的问题，先给我调整预览，不要直接执行` 第三步曾进入完整 Agent，约 `99.9s`、`11` 次工具调用，包含重复 `plan_next_action / execute_plan_action / query_volunteer_plan`。本轮只对明确带“审查/风险/最严重/问题 + 调整预览/怎么调/不要执行”的高置信请求启用 Plan fast route；普通“最严重的问题是什么，优先解决哪个”仍不被抢路由，交给原只读问答链路。

验证：

- `python3 -m json.tool zhiyuan-agent/examples/dialog_regression_303_effect_perf_cases.json`
- `python3 -m py_compile zhiyuan-agent/app/service.py zhiyuan-agent/app/tools/intent_response_tool.py zhiyuan-agent/app/resolver/major_compare_reply_renderer.py zhiyuan-agent/app/tools/explore_direction_tool.py`
- `PYTHONPATH=. pytest --noconftest tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_dialog_regression_runner.py -q`：`171 passed`
- `PYTHONPATH=. pytest --noconftest tests/unit/test_plan_fast_router.py tests/unit/test_plan_execution_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_major_intent_fast_router.py tests/unit/test_plan_query_fast_router.py -q`：`137 passed`
- `dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` 真实 WebSocket 复跑：`14/14` steps 通过，输出 `/private/tmp/dialog-regression-303-after-p1-quality-rerun.json`，中位耗时约 `2212ms`，最大耗时约 `4350ms`
- 合并单测回归：`PYTHONPATH=. pytest --noconftest tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_scenario_stability.py tests/unit/test_dialog_regression_runner.py tests/unit/test_plan_fast_router.py tests/unit/test_plan_execution_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_major_intent_fast_router.py tests/unit/test_plan_query_fast_router.py -q`：`310 passed`
- 审查结构化与职业方向去重后复跑：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` 真实 WebSocket `14/14` steps 通过，输出 `/private/tmp/dialog-regression-303-after-review-and-career-polish.json`，中位耗时约 `2240ms`，最大耗时约 `4140ms`
- 最新合并单测回归覆盖 ChatService、Explore、mainline、方案执行/查询和快路由：`336 passed`
- 方案查询/加入预览/排序预览补强后聚焦回归：`tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py -q`：`142 passed`
- 无 pending 确认上下文文案补强后，`tests/unit/test_chat_service_history_persistence.py -q`：`118 passed`；合并 agent 单测：`344 passed`；`dialog_regression_303_effect_perf_cases.json` JSON 校验通过。
- Intent 确认内容复述补强后，Intent 聚焦回归：`224 passed`；合并 agent + Intent 单测：`450 passed`。
- 专业对比结构化 fallback 补强后，`tests/unit/test_major_compare_reply_renderer.py tests/unit/test_chat_service_history_persistence.py -q`：`123 passed`。
- 技能注入聚焦单测：`tests/unit/test_base_agent.py tests/unit/test_chat_agent_init_profile.py tests/unit/test_chat_agent_tools.py -q`：`40 passed`
- `dialog_regression_303_open_quality_cases.json --clear-history --keep-response-text` 真实 WebSocket 复跑：`4/4` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_backend_start.json`，中位耗时约 `3107ms`，最大耗时约 `4987ms`；待确认意向影响追问约 `2899ms`，无 followup 工作台卡片。
- 聚焦单测覆盖 pending intent 影响追问、Intent preview 边界、结构化 impact 标题去重和泛化句清理。
- 职业方向结构收口后复跑：`dialog_regression_303_open_quality_cases.json --clear-history --keep-response-text` 真实 WebSocket `4/4` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_career_format_restart.json`，中位耗时约 `3140ms`，最大耗时约 `3794ms`。
- 最新 `dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` 真实 WebSocket `14/14` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_career_format_restart.json`，中位耗时约 `2317ms`，最大耗时约 `4704ms`。
- 技能工具收紧后，`dialog_regression_303_effect_perf_cases.json` 真实 WebSocket `14/14` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_skill_toolset_scope.json`，中位耗时约 `2284ms`，最大耗时约 `4930ms`；职业方向承接场景约 `2204ms`，tool trace 仅有 `analyze_current_career_direction`，没有 `load_skill`。
- 技能工具收紧后，`dialog_regression_303_open_quality_cases.json` 真实 WebSocket `4/4` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_skill_toolset_scope.json`，中位耗时约 `3046ms`，最大耗时约 `3506ms`。
- Intent 专业标签源头用户化并对齐 ChatService 清洗 guard 后，聚焦 + 合并回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py -q`：`338 passed`。
- case 级质量评分补强后，`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py -q`：`8 passed`。
- 使用历史带回复文本的 effect/perf 输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_career_format_restart.json` 生成离线质量报告：`14` 个 case，`qualityViolations` 为空，`strong=4 / needs_review=10`；同时修正评估规则，避免把 Intent 预览/确认误判为必须覆盖方案分布的预览类回复。
- 方案/候选摘要用户化后，`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_plan_query_tool.py -q`：`25 passed`。
- 专业对比文案去系统化后，真实 WebSocket `session=990306`：`法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好` 通过，耗时约 `2097ms`；回复包含会话约束、法学/财政学路径、选择建议和下一步，不再出现系统评分术语。
- Intent pending 历史兜底后，真实 WebSocket `session=990309`：`我倾向法学和财政学，但护理不要 -> 确认这个偏好` 两步通过，中位耗时约 `2035ms`；第二步走 `update_volunteer_intent_state`，回复包含“本次确认内容：偏好专业：法学、财政学；排除专业：护理学”，不再误走无 pending guard。
- Intent preview 条件式文案和评估门禁补强后，聚焦回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_ws_compat.py tests/unit/test_planning_intent_scenarios_sync.py -q`：`248 passed`；补充条目级条件语气和评估门禁聚焦回归：`107 passed`。
- 方案操作预览影响面补强后，聚焦回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py -q`：`213 passed`。
- 无 pending 确认文本兜底补强后，ChatService 聚焦回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py -q`：`125 passed`。
- Intent 确认结构化回复补强后，聚焦回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_chat_service_history_persistence.py -q`：`222 passed`。
- 使用历史带回复文本的 effect/perf 输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_career_format_restart.json` 重新生成离线质量报告：`14` 个 case，`qualityViolations` 为空，`strong=4 / needs_review=10`；新增 `pending_intent_effective_wording` 门禁未误伤已有结果。
- 上一轮宽回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_mainline_dialog_scenarios.py tests/integration/test_dialog_style_coverage.py tests/regression/test_pending_protocol.py tests/regression/test_execution_preview.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_major_compare_reply_renderer.py tests/unit/test_chat_agent_progress_hints.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_intent_state_tool.py -q`：`722 passed`。
- 局部查询/职业方向样本展示继续补强：查询摘要去掉“专业热度专业热度”重复前缀，示例解释改为“专业信息：热度/计划数”；职业方向“代表样本”只保留真实院校/专业样本，不再重复数量判断和泛化提醒。
- 评估工具修正确认保护误判：用户只回复“确认”且系统返回“上一轮只是只读分析、没有待执行动作”时，不再按预览类回复强制要求分布覆盖，避免把正确的 no-pending guard 标成 `thin_preview_distribution`。
- 真实 WebSocket effect/perf 复跑：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` `14/14` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_query_career_polish.json`，中位耗时约 `2555ms`，最大耗时约 `4692ms`；离线质量评分 `qualityViolations=0`，`strong=6 / needs_review=8`。
- Intent 确认边界在干净会话单独验证：`session=990411` 跑通“我倾向法学和财政学，但护理不要 -> 确认这个偏好”，预览条目使用“确认后，将把...”条件式表达，确认回复复述“偏好专业：法学、财政学；排除专业：护理学”。固定回归会话 `880203` 本地后端已有画像时会进入 existing-only 兼容分支，不能用来判断新会话的待确认文案。
- Intent existing-only 文案修复：固定会话已存在相同偏好/要求时，首轮回复改为“当前已经在后续参考中，不需要重复确认”，并列出“已在参考的偏好/排除项”，不再说成新的“待确认”内容。
- 最新真实 WebSocket effect/perf 复跑：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` `14/14` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_intent_existing_polish.json`，中位耗时约 `2320ms`，最大耗时约 `4247ms`；离线质量评分 `qualityViolations=0`，`strong=5 / needs_review=9`。
- 最新宽回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_mainline_dialog_scenarios.py tests/integration/test_dialog_style_coverage.py tests/regression/test_pending_protocol.py tests/regression/test_execution_preview.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_major_compare_reply_renderer.py tests/unit/test_chat_agent_progress_hints.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_intent_state_tool.py -q`：`726 passed`。
- 只读边界与确认完成提示补强后，聚焦回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py -q`：`228 passed`。
- 只读边界与确认完成提示补强后，宽回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_mainline_dialog_scenarios.py tests/integration/test_dialog_style_coverage.py tests/regression/test_pending_protocol.py tests/regression/test_execution_preview.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_major_compare_reply_renderer.py tests/unit/test_chat_agent_progress_hints.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_intent_state_tool.py -q`：`726 passed`。
- 最新真实 WebSocket effect/perf 复跑：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` `14/14` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_readonly_apply_hint.json`，中位耗时约 `2263ms`，最大耗时约 `4576ms`；离线质量评分输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_readonly_apply_hint_quality.json`，`qualityViolations=0`，`strong=6 / needs_review=8`。
- 回复结构和可行动性补强后，焦点回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_intent_state_tool.py tests/unit/test_major_compare_reply_renderer.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_regression_runner.py tests/unit/test_dialog_case_evaluation_report.py -q`：`350 passed`。
- 排序预览结构化和只读边界补强后，宽回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_mainline_dialog_scenarios.py tests/integration/test_dialog_style_coverage.py tests/regression/test_pending_protocol.py tests/regression/test_execution_preview.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_planning_workflow_tool.py tests/unit/test_plan_query_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_major_compare_reply_renderer.py tests/unit/test_chat_agent_progress_hints.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_intent_state_tool.py -q`：`726 passed`。
- 最新真实 WebSocket effect/perf 复跑：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style` `14/14` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_final_reply_polish_v2.json`，中位耗时约 `2297ms`，最大耗时约 `4425ms`；离线质量评分输出 `/private/tmp/zhiyuan_agent_303_effect_perf_after_final_reply_polish_v2_quality.json`，`qualityViolations=0`，`strong=14 / needs_review=0`。
- `dialog_regression_303_open_quality_cases.json` JSON 校验通过；新增目录级单测约束 open-quality case 必须覆盖 pending impact、局部查询、排序预览、非固定专业对比、多方向职业承接和 no-pending guard。
- 职业方向快路由补强前，扩展 open-quality 真实 WebSocket `8/9` 步通过，失败点为三方向职业 case 的 thinking 断言，实际回复内容正确但走完整 Agent，耗时约 `17.2s`；该问题已补聚焦单测覆盖。
- 待确认意向文案统一与职业方向快路由补强后，聚焦单测：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_career_direction_fast_router.py tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_mainline_dialog_scenarios.py::test_release_303_open_quality_cases_cover_richer_real_user_shapes tests/unit/test_chat_service_history_persistence.py::test_chat_service_major_intent_fast_route_bypasses_main_agent_and_persists_preview tests/unit/test_chat_service_history_persistence.py::test_chat_service_pending_intent_impact_question_bypasses_main_agent tests/unit/test_chat_service_history_persistence.py::test_intent_timeout_fallback_uses_pending_cache_without_applying tests/unit/test_chat_service_history_persistence.py::test_normalize_pending_intent_reply_avoids_premature_recorded_wording tests/unit/test_chat_service_history_persistence.py::test_normalize_pending_intent_reply_rewrites_existing_only_recorded_wording tests/unit/test_intent_state_tool.py::test_build_preview_title_uses_pending_boundary_without_candidate_tightening tests/unit/test_ws_compat.py::test_ws_compat_timeout_uses_pending_intent_fallback_after_plan_miss -q`：`24 passed`。
- 最新 open-quality 真实 WebSocket 复跑：`dialog_regression_303_open_quality_cases.json --clear-history --keep-response-text --assert-plan-style` `9/9` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_pending_wording_text.json`，中位耗时约 `2429ms`，最大耗时约 `3966ms`；离线质量评分输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_pending_wording_text_quality.json`，`qualityViolations=0`，`strong=8 / needs_review=1`。唯一 `needs_review` 是 no-pending guard 的“确认”保护回复，功能正确但内容较短，后续继续优化。
- no-pending 查询确认保护补强后，聚焦单测：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_chat_service_history_persistence.py::test_chat_service_no_pending_confirm_infers_context_from_text_only_history tests/unit/test_dialog_case_evaluation_report.py -q`：`14 passed`。
- no-pending 查询确认保护补强后，最新 open-quality 真实 WebSocket 复跑：`dialog_regression_303_open_quality_cases.json --clear-history --keep-response-text --assert-plan-style` `9/9` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_no_pending_guard_text.json`，中位耗时约 `2477ms`，最大耗时约 `3981ms`；离线质量评分输出 `/private/tmp/zhiyuan_agent_303_open_quality_after_no_pending_guard_text_quality.json`，`qualityViolations=0`，`strong=9 / needs_review=0`。
- 审查后续调整预览快路径聚焦回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_plan_fast_router.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_chat_service_history_persistence.py::test_chat_service_plan_fast_route_bypasses_main_agent_and_persists_preview tests/unit/test_chat_service_history_persistence.py::test_chat_service_plan_fast_route_preserves_named_ref_for_preview tests/unit/test_chat_service_history_persistence.py::test_chat_service_plan_fast_route_handles_review_followup_adjustment_preview_without_main_agent -q`：`50 passed`。
- 审查后续调整预览宽回归：`PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_plan_fast_router.py tests/unit/test_plan_orchestration_tool.py tests/unit/test_plan_execution_tool.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_dialog_case_evaluation_report.py -q`：`276 passed`；`PYTHONPYCACHEPREFIX=/private/tmp/zhiyuan_pycache ./.venv/bin/python -m py_compile app/resolver/plan_fast_router.py app/service.py` 通过。
- 真实 WebSocket 探针已尝试复跑 `session=17` 三步慢例，但当前本地 `INTERNAL_SERVICE_URL=http://localhost:8080` 未启动，Agent 读取到的是空方案状态，不能作为有效方案链路性能判断；代码层面通过 ChatService 单测确认该请求会走 `plan_fast_route`，`llmRequests=0`、`toolCallCount=2`，且不会进入主 Agent 或重复 `query_volunteer_plan`。
- 评估框架完善后，使用 `--markdown-detail` 对最新历史真实输出重新生成详细回复质量报告：
  - `effect_perf`：`/private/tmp/zhiyuan_agent_303_effect_perf_detail_eval.json`、`/private/tmp/zhiyuan_agent_303_effect_perf_detail_eval.md`，结果 `strong=14 / needs_review=0 / fail=0`，`qualityViolations=0`。
  - `open_quality`：`/private/tmp/zhiyuan_agent_303_open_quality_detail_eval.json`、`/private/tmp/zhiyuan_agent_303_open_quality_detail_eval.md`，结果 `strong=9 / needs_review=0 / fail=0`，`qualityViolations=0`。
  - 剩余 warning 主要是历史 runner 输出未记录 `routingPath`，不影响回复质量结论；评估工具已用 toolName/actionFamily 兜底识别真实业务动作，避免把正确只读确认保护误判为质量待复核。
- 本地 `rank + server + agent + web` 服务链路恢复后，使用最新运行服务重新跑真实 WebSocket case：
  - `effect_perf`：`dialog_regression_303_effect_perf_cases.json --clear-history --keep-response-text --assert-plan-style`，`14/14` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_effect_perf_latest_live.json`；详细评分输出 `/private/tmp/zhiyuan_agent_303_effect_perf_latest_live_eval.json`、`/private/tmp/zhiyuan_agent_303_effect_perf_latest_live_eval.md`，结果 `strong=14 / needs_review=0 / fail=0`，`qualityViolations=0`。延迟：中位 `2340ms`，p95 `3975ms`，最大 `4547ms`，首响中位 `178ms`，终响中位 `338ms`。
  - `open_quality`：`dialog_regression_303_open_quality_cases.json --clear-history --keep-response-text --assert-plan-style`，`9/9` steps 通过，输出 `/private/tmp/zhiyuan_agent_303_open_quality_latest_live.json`；详细评分输出 `/private/tmp/zhiyuan_agent_303_open_quality_latest_live_eval.json`、`/private/tmp/zhiyuan_agent_303_open_quality_latest_live_eval.md`，结果 `strong=9 / needs_review=0 / fail=0`，`qualityViolations=0`。延迟：中位 `2379ms`，p95 `3661ms`，最大 `3745ms`，首响中位 `232ms`，终响中位 `376ms`。
  - 这次最新 live 输出中仍存在 `missing_route_observability` warning：`effect_perf=13`、`open_quality=7`。当前不影响用户侧质量结论，因为工具调用和 actionFamily 可以识别真实业务动作；后续建议让 runner/服务端统一输出 `routingPath`，减少评估报告的兜底推断。
- 评估工具补强 `expectedKeyPoints / forbiddenPatterns` 自动检查后，使用严格版规则重新评估同一批最新 live 输出：
  - `effect_perf`：`/private/tmp/zhiyuan_agent_303_effect_perf_latest_live_eval_strict.json`，结果仍为 `strong=14 / needs_review=0 / fail=0`，`qualityViolations=0`。
  - `open_quality`：`/private/tmp/zhiyuan_agent_303_open_quality_latest_live_eval_strict.json`，结果仍为 `strong=9 / needs_review=0 / fail=0`，`qualityViolations=0`。
  - 新规则不会改变 Agent 回复逻辑，只让 case 评估更严格：case 专属禁用表达命中会失败；期望业务点缺失会进入 `needs_review`，避免“回复结构完整但漏掉关键业务说明”被直接放过。
- runner 可观测性补强：后续真实 WebSocket 回归会从历史中的 fast-route `model_name` 或 `fast-/direct-` tool call id 推断 `turnObservability.routingPath`。这会降低 `missing_route_observability` warning，并避免完整 Agent 调用同名工具时被误标为快路径。
- 主 case 集补齐 `expectedKeyPoints / forbiddenPatterns` 后，使用最新 live 输出复评：
  - `effect_perf`：`/private/tmp/zhiyuan_agent_303_effect_perf_latest_live_eval_keypoints.json`，结果 `strong=14 / needs_review=0 / fail=0`，`qualityViolations=0`。
  - `open_quality`：`/private/tmp/zhiyuan_agent_303_open_quality_latest_live_eval_keypoints.json`，结果 `strong=9 / needs_review=0 / fail=0`，`qualityViolations=0`。
  - 这轮把“数量/冲稳保/审查/偏好承接”“导出顺序/待重新审查/确认边界”“当前方案承接/候选机会/代表样本”“专业对比边界/就业路径/选择建议”等场景级质量要求写入 case 定义，后续回复变薄或漏关键点会被自动标记。
- 新增真实用户口语化输入 case 集：`zhiyuan-agent/examples/dialog_regression_303_realistic_user_cases.json`。
  - 覆盖短句、懒输入、口语、省略、简称和弱指令，例如“这方案咋样”“保底够不够啊”“青城那个是不是放多了”“按好学校排下看看”“法和财哪个更适合女孩子，家里一般”“新媒体和跨电呢 数学不太行”“会计审计可以 土木别要”“嗯可以”。
  - 这组 case 的质量目标是：用户输入可以很短，但系统回复不能变薄；必须主动补结论、依据、代表性数据、风险边界和可继续交互的下一步。
  - 目录级单测已覆盖该 case 集必须包含 `realistic_user_input`、`lazy_short_prompt`、`school_abbreviation`、`major_abbreviation`、`career_short_prompt`、`short_intent`、`vague_confirm`、`preview_confirm_boundary` 和 `no_pending_guard` 等标签。
- 真实用户口语化 case 首轮 live 复跑已执行，输出 `/private/tmp/zhiyuan_agent_303_realistic_user_live.json`，详细报告输出 `/private/tmp/zhiyuan_agent_303_realistic_user_live_eval.md`。
  - 结果：`9` 个 step 中 `8` 个拿到回复，`1` 个超时失败；中位耗时约 `16832ms`，p95 约 `38698ms`。
  - 质量可接受样例：`这方案咋样` 能覆盖数量、冲稳保、审查、偏好匹配、前排示例和下一步；`新媒体和跨电呢 数学不太行` 能识别专业简称并给出学习压力、就业路径和建议。
  - 暴露问题：`法和财哪个更适合女孩子，家里一般` 未进入专业对比快路由，落到完整 Agent 后 `124469ms` 超时；`按好学校排下看看` 的排序预览尾部重复了“排序方式/执行影响”；`嗯可以` 没有进入无 pending 确认保护，回复没有明确“当前没有待确认/待执行事项”；`青城那个是不是放多了` 有院校简称歧义，实际误偏向青海民族大学而非预期的青岛城市学院。
  - 修复设计：不新增普通业务字符串模板回复；只把高置信口语简称纳入既有快路由解析，把真实确认口语纳入既有无 pending 保护，把排序预览的结构化补充收敛为单一来源。院校简称仅补充已在 case 中明确验证的高置信映射，仍保持只读查询、不生成卡片、不执行方案动作。
  - 修复后重启 Agent 复跑：`/private/tmp/zhiyuan_agent_303_realistic_user_live_after_restart.json`，`9/9` steps 通过；中位耗时约 `3453ms`，最大 `38766ms`。`青城` 命中青岛城市学院并走 `plan_query_fast_route`；`法和财` 命中 `major_compare_fast_route`，约 `2435ms`；`嗯可以` 命中 `plan_confirmation_guard_no_pending`，约 `2177ms`。
  - 排序字段专项复验：`/private/tmp/zhiyuan_agent_303_good_school_sort_after_field_fix.json`，`按好学校排下看看` 约 `2445ms`，走 `plan_fast_route`，回复为“按院校层次重新排序”，不再误判为录取率排序，也不再重复“排序方式/执行影响”。
  - 最终收口复跑：`/private/tmp/zhiyuan_agent_303_realistic_user_live_final4.json`，详细评分报告 `/private/tmp/zhiyuan_agent_303_realistic_user_live_final4_eval.md`。结果 `9/9` steps 通过，`failedSteps=0`，`qualityViolations=0`；评分 `strong=7 / needs_review=2 / fail=0`。延迟：runner 统计中位 `2257ms`、p95/max `28006ms`；详细评分器插值 p95 为 `18232ms`，max 仍为 `28006ms`。
  - 最终收口的关键链路：`保底够不够啊` 走 `plan_fast_route -> query_state`，约 `2373ms`，不再误走补齐预览；`法和财哪个更适合女孩子，家里一般` 走 `major_compare_fast_route`，约 `2301ms`；`新媒体和跨电呢 数学不太行` 走 `major_compare_fast_route`，约 `2188ms`；`会计审计可以 土木别要` 走 `major_intent_fast_route`，约 `2079ms`；`青城那个是不是放多了` 能映射到青岛城市学院；`嗯可以` 走无 pending 确认保护。
  - 剩余 `needs_review` 解释：`这方案咋样` 内容质量通过，覆盖数量、冲稳保、审查风险、前排样本和下一步，但本轮仍有 `28006ms` 慢请求，后续如果继续压性能，应优先看方案状态类回复是否能减少一次模型往返或引入结构化 facts 兜底；`保底够不够啊` 路由和内容正确，但 case 的 `expectedKeyPoints` 对“主要问题 / 建议 / 下一步”字面要求偏严格，当前回复用“需要关注 / 可以继续...”表达，没有构成质量硬失败。

## 11. 当前回复质量结论与后续关注点

### 11.1 已满足 3.0.3 发布质量门槛

基于最新详细评估，3.0.3 当前主 case 集达到：

- 硬失败为 0：没有内部术语外露、待确认/已生效边界冲突、空回复或超时硬失败。
- 主链路覆盖为 strong：方案状态、审查、局部查询、移动、加入、排序、专业组操作、意向预览/确认、无 pending 确认保护均通过。
- 开放质量覆盖为 strong：职业方向、多方向承接、专业对比、待确认意向影响追问、只读查询后确认保护均通过。
- 真实口语化输入覆盖已补齐：短句、懒输入、简称、弱确认和混合软硬意向均有 live 结果；最终收口 `9/9` 通过，未出现质量硬失败。
- 延迟整体可接受：最新本地服务 live 复跑中 effect/perf 中位约 `2340ms`，open-quality 中位约 `2379ms`，口语化 case 中位约 `2257ms`。仍需继续关注“方案概况自由组织回复”偶发慢请求。

### 11.2 后续仍建议关注

当前不是硬失败，但后续继续优化时应关注：

- 职业方向多方向回复有时较长，专业组或专业名称带招生说明时会显得压迫；后续可考虑对代表样本做更短的显示摘要。
- 局部查询的“专业热度/计划数”信息已经覆盖关键分布，但表达仍偏数据化；后续可进一步转成更像顾问的解释。
- 多模型对照仍需要更开放的 case，否则结构化 renderer 会让不同模型回复高度一致，难以真实比较模型表达质量。
- 新 runner 输出应尽量补齐 `routingPath`，减少详细报告里的 route warning。

## 12. 开放真实场景与多模型对比扩展

本轮继续扩展开放式质量评估，重点不是再增加标准问法，而是加入更接近真实用户的表达：

- `dialog_regression_303_open_quality_cases.json` 已从标准开放问法继续扩展，新增家长视角、风险焦虑、专业压力、候选机会和只读后确认保护场景，例如“这版是不是太冲了，能不能给我说人话”“家里就想让孩子以后稳一点进体制”“法学会不会太卷”“会计审计这类还行，土木建筑那种别碰”“候选里还有没有更稳一点的会计审计”。
- 新增 `model_provider_303_open_quality_realistic_cases.json`，用于多模型 Agent 横向对比。该文件只选取代表性开放口语 case，并要求保留完整回复、质量期望点、禁用表达、no-followup 和耗时预算。
- `model_provider_benchmark.py` 的 Agent 场景断言已补充 `expectedKeyPoints / forbiddenPatterns / assertThinkingContains / assertNoFollowups / maxElapsedSeconds / warnElapsedSeconds`，避免多模型对比只看延迟而忽略回复质量。
- 本轮继续把多模型开放 case 从 10 个扩展到 25 个，新增“这方案咋样，能不能说重点”“青城那个是不是放多了，先看看别改”“新媒体和跨电呢，数学不太行，哪个别踩坑”“按好学校排下看看，先给我看会怎么动”“嗯可以”“会计和审计哪个更稳，考公也能用点的”“以后想考公但也怕太卷，这方案有支撑吗，先看看”“就按别太冒险的思路把这版调稳点，先给我看看会怎么动”“北京天津想去，但别最后没学上，这个取舍咋看”“医学护理这些别碰，财会还能接受，先看看影响”等真实短句、简称、家长表达、弱确认和方案调整边界场景。
- `model_provider_benchmark.py` 新增 `expectedKeyPointGroups` 和 `minTextLengthWarn` 评估口径。前者用于同义表达验收，后者只做薄回复 warning，不作为硬失败，避免把质量评估退化成固定模板或字数门槛。

当前设计口径：

- 多模型对比继续使用 SiliconFlow 示例配置中的 `Pro/moonshotai/Kimi-K2.6`、`Pro/MiniMaxAI/MiniMax-M2.5`、`deepseek-ai/DeepSeek-V4-Flash`、`Pro/zai-org/GLM-5.1`。
- 质量优先于延迟：如果某个模型或链路虽然慢一些，但能更完整地解释取舍、覆盖关键分布、给出确认边界和可执行下一步，应优先进入人工复核，而不是被低延迟模型直接替代。
- 多模型开放 case 不要求全部命中 fast route；如果某个模型在开放表达上更会组织理由、但耗时略高，需要结合完整回复人工复核。
- 如果某个模型漏掉确认边界、误发工作台联动、外露内部字段或把待确认说成已生效，即使延迟更低也不能作为优选。
- `fast route` 的目标是减少确定性链路的无效等待，不是绕过语义理解。对于地域安全取舍、专业风险权衡、软硬意向混合表达等开放问题，若本地结构化事实不足以支撑高质量回复，应保留完整 Agent 或澄清链路，并通过进度提示改善等待体验。

推荐输出：

- `/private/tmp/model-provider-303-open-realistic-benchmark.json`
- `/private/tmp/model-provider-303-open-realistic-benchmark-eval.md`

上一轮 10 case 四模型实测结果：

| provider | model | steps | errors | assertion failures | latency warnings | final median | final p95/max | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| siliconflow-kimi-k26 | `Pro/moonshotai/Kimi-K2.6` | 10 | 0 | 0 | 1 | 0.482s | 78.263s | 质量门禁通过，但三专业开放对比慢请求明显 |
| siliconflow-minimax-m25 | `Pro/MiniMaxAI/MiniMax-M2.5` | 10 | 0 | 0 | 0 | 0.248s | 20.038s | 重跑同义关键点组后通过，综合速度最好 |
| siliconflow-deepseek-v4-flash | `deepseek-ai/DeepSeek-V4-Flash` | 10 | 0 | 0 | 0 | 0.257s | 21.615s | 质量门禁通过，开放 LLM 场景耗时中等 |
| siliconflow-glm-51 | `Pro/zai-org/GLM-5.1` | 10 | 0 | 0 | 0 | 0.261s | 25.354s | 质量门禁通过，开放 LLM 场景耗时略高于 DeepSeek |

输出文件：

- `/private/tmp/model-provider-303-open-realistic-expanded-boundary-final.json`
- `/private/tmp/model-provider-303-open-realistic-minimax-after-keypoint-groups.json`

结果解读：

- 预算 / 高收费 / 中外合作只读风险分析已经稳定走低延迟路径，四个模型均能覆盖预算风险和“不改方案”的边界。
- 开放式专业对比仍是主要耗时来源。Kimi 在“三专业松散对比”里出现 `78.263s` 慢请求，质量通过但不适合作为默认性能优先模型。
- MiniMax 首轮失败来自断言过硬：回复用了“踩坑点 / 求稳排序 / 总结”等自然表达，没有逐字出现旧期望词。改为 `expectedKeyPointGroups` 后通过，说明评估应检查语义覆盖而不是固定模板。
- 25 case 首轮四模型矩阵已经执行，输出 `/private/tmp/model-provider-303-open-realistic-25case-4model.json`。这轮暴露了两个真实问题：
  - `医学护理这些别碰，财会还能接受，先看看影响` 被 `plan_query_fast_route` 抢走，回复退化成“当前方案里还没有可查询的志愿”，没有进入待确认意向预览。
  - `就按别太冒险的思路把这版调稳点，先给我看看会怎么动` 在部分模型下回落 full-agent，MiniMax 出现 `execute_plan_action` 参数校验失败，DeepSeek 出现超时，Kimi 虽有回复但耗时约 `66.385s`。

修复措施：

- `plan_query_fast_router` 增加无范围意向影响问法保护：没有明确“方案里 / 候选里 / 有没有 / 查一下”等查找范围，且包含“别碰 / 能接受 / 影响 / 排除”等意向语义时，不再抢路由，交给 `major_intent_fast_route`。
- `major_intent_fast_router` 补充真实口语归一化：`医学 / 学医 / 医药` 展开为临床医学类、口腔医学类、中医学类、护理学类、医学技术类；`财会` 展开为会计学、审计学；`别碰 / 还行 / 能接受` 纳入高置信软硬意向识别。
- `plan_fast_router` 补充“调稳 / 稳点 / 别太冒险 + 先看看会怎么动”高置信调整分析路径，直接进入 `analyze_adjustment`，避免完整 Agent 自由构造工具参数。
- `ChatService` 对 `adjustment_analysis` 的快路径回复追加用户侧边界：当前只是分析怎么调稳，不直接改方案；后续具体移动、删除、补入或排序才会影响方案顺序和导出顺序，并让审查状态进入待重新审查，确认后才执行。

修复后聚焦复验：

- 输出：`/private/tmp/model-provider-303-open-realistic-fix-probe-4model-v2.json`
- 覆盖：`这方案咋样，能不能说重点`、`就按别太冒险的思路把这版调稳点，先给我看看会怎么动`、`医学护理这些别碰，财会还能接受，先看看影响`
- 四模型结果：`steps=3`，`errors=0`，`assertion_failures=0`，`latency_warnings=0`，`quality_warnings=0`，`quality_gate_pass_rate=1.0`
- 修复后最慢 final：
  - Kimi：`1.016s`
  - MiniMax：`0.573s`
  - DeepSeek：`0.484s`
  - GLM：`0.423s`

仍需后续优化：

- `北京天津想去，但别最后没学上，这个取舍咋看` 回复质量可接受，能覆盖京津诉求、保底风险和取舍建议，但仍可能进入 full-agent 地域兴趣分析链路，首轮四模型里 Kimi 约 `45.046s`、DeepSeek 约 `27.352s`、GLM 约 `21.971s`。后续应单独设计“地域偏好 vs 录取安全”的本地结构化分析能力，而不是把它粗暴降级成普通方案概览。
- 当前 `plan_fast_route / plan_query_fast_route / major_intent_fast_route / major_compare_fast_route / career_direction_fast_route` 仍是多个独立 fast router。它们可以解决一批高置信 case，但底层仍依赖局部表达特征和路由顺序，容易出现“字符串补丁越加越多、换一种说法又错”的问题。根本方案不是继续堆关键词，而是引入统一语义路由仲裁：
  - 先把用户输入解析为统一的意图候选，包含场景范围、动作类型、对象实体、只读/修改边界、副作用等级和置信度。
  - 现有 fast router 改为产生 `route candidate`，不再直接抢最终路由。
  - 仲裁层按“质量可满足程度 > 语义置信度 > 副作用安全 > 延迟成本”排序；不确定时进入完整 Agent 或澄清。
  - 建立 route confusion matrix，把“意向影响被方案查询抢走”“调稳预览回落自由工具调用”“地域安全取舍被普通概览薄化”等 case 固化为回归。

### 12. 统一 fast route 仲裁落地

本轮已把“逐个 fast router 顺序抢路由”改为“候选生成 + 统一仲裁”：

- 新增 `app/resolver/fast_route_arbitrator.py`。
- `plan_fast_route / plan_query_fast_route / major_intent_fast_route / major_compare_fast_route / career_direction_fast_route` 仍负责识别各自高置信候选，但不再由 ChatService 顺序命中后立即执行。
- ChatService 先收集所有 fast-route candidate，再通过 `arbitrate_fast_route_candidates` 选择最终路径。
- 选中路径后继续复用原来的执行链、历史保存、workspace followup 和 conversation_turn_event，不重写工具调用逻辑。
- `routeDecision.arbitration` 会记录候选列表、分数、质量门槛和 blockers，方便排查“为什么走这条 / 为什么没有走快路径”。
- 如果所有候选都被质量门槛挡住，会记录 `fast_route_arbitration_fallback_event`，然后进入完整 Agent。

第一版仲裁规则：

- 质量优先：快路径只有在能支撑该场景足够好的回复时才接管。
- 明确范围查询优先于意向写入：例如“孩子不想学医也不想护理，方案里有没有这种坑，先看看”同时命中方案查询和专业意向时，选择 `plan_query_fast_route`，因为用户问的是“方案里有没有”。
- 无明确查询范围的意向影响继续走待确认意向预览：例如“医学护理这些别碰，财会还能接受，先看看影响”走 `major_intent_fast_route`。
- 方案状态、明确排序/移动/删除/加入、显式审查等仍可走 `plan_fast_route`，但高副作用动作只生成预览和确认边界。
- 地域偏好与录取安全取舍暂不降级成普通方案概览：例如“孩子就想去北京天津，但分数不算高，这样是不是太冒险，先别改”会被 `region_safety_tradeoff_needs_full_analysis` 挡住，进入完整 Agent，避免用薄概览回答复杂取舍。

新增回归：

- `tests/unit/test_fast_route_arbitrator.py` 覆盖候选仲裁、质量门槛、地域安全取舍降级、方案状态和高副作用预览。
- `test_release_303_fast_router_priority_matrix_prevents_cross_layer_intercepts` 改为验证统一仲裁结果，不再保护旧的顺序抢路由。
- `test_chat_service_arbitration_quality_gate_falls_back_to_full_agent_for_region_safety_tradeoff` 验证质量门槛阻止薄快路径后会进入完整 Agent，且不会调用方案工具或局部查询工具。

这不是完全消除所有规则判断，底层各 fast router 仍有局部识别逻辑；但系统层面已经从“谁先匹配谁执行”收口到“全部候选统一评估”。后续继续优化的方向是把 candidate 的实体、范围、只读/修改边界和质量评分做得更结构化，逐步减少 router 内部的表达补丁。

### 13. LLM 意图路由是否启用的决策门槛

当前不直接把 LLM Intent Router 放入主链路。原因是新增一次 LLM 意图判断会带来额外延迟、成本和模型漂移风险；只有当现有“本地候选 + 仲裁”在真实场景效果上不达标时，才进入 LLM Intent Router shadow。

先按以下效果门槛判断：

| 维度 | 观察项 | 进入 LLM Intent Router shadow 的触发条件 |
| --- | --- | --- |
| 路由正确性 | 高置信、冲突、开放取舍三类 case 的最终路由 | 真实口语 case 中出现 2 个以上错误路由，且不是单个业务工具 bug |
| 回复质量 | `strong / needs_review / fail`、关键点覆盖、是否薄回复 | 出现 `fail`，或 `needs_review` 集中在语义理解不足导致的信息缺失 |
| 安全边界 | 只读不联动、待确认不执行、高副作用预览 | 任一高副作用误执行或误刷新工作台 |
| 延迟 | 首响、最终回复、超时率 | 完整 Agent 回落过多导致 p95 明显不可接受，且本地结构化能力无法覆盖 |
| 可维护性 | 新增 case 是否只能继续堆字符串补丁 | 同类语义连续出现多种表达变体，需要跨多个 router 补规则 |

如果不触发上述条件，本期继续保持本地候选仲裁，优先补 case、补质量评分和补结构化事实能力。

如果触发，LLM Intent Router 也先只做 shadow：

1. 输入当前用户文本、最近对话摘要、当前 pending 状态和方案概览。
2. 输出结构化 `IntentFrame`，包含 `scene / action / entities / readonly / sideEffect / confidence / reason / missingInfo`。
3. 不直接执行工具，只和本地仲裁结果一起写入观测日志。
4. 连续跑真实口语和多模型 case，对比 LLM 候选是否真正减少误路由、是否带来新的误判。
5. 只有 shadow 结果稳定优于本地仲裁，才考虑把低置信/冲突/质量门槛挡住的场景交给 LLM Intent Router。

### 13.1 最新效果复核结论

基于最新本地 `8107` Agent 复跑，本期暂不启用 LLM Intent Router 主链路，也暂不进入 shadow：

- 复跑命令：`dialog_regression_303_open_quality_cases.json --clear-history --keep-response-text --assert-plan-style`
- 输出：`/private/tmp/zhiyuan_agent_303_open_quality_after_keypoint_backend_8107.json`
- 详细评分：`/private/tmp/zhiyuan_agent_303_open_quality_after_keypoint_backend_8107_eval_v2.md`
- 结果：`23/23` steps 通过，`failedSteps=0`。
- 延迟：中位 `2283ms`，p95 `3794ms`，最大 `3969ms`。
- 评分：`strong=23 / needs_review=0 / fail=0`，没有 `route_mismatch`、`action_family_mismatch`、`unexpected_action` 或 `thin_preview_distribution` 硬失败。

这轮验证必须以 Agent、Server、Rank 三个本地依赖同时可用为前提。此前在 `INTERNAL_SERVICE_URL=http://localhost:8080` 后端未启动时，方案状态、候选查询、审查和调整预览会退化为空方案事实，虽然路由链路仍可能返回响应，但不能作为 3.0.3 方案类效果/性能结论。

这轮验证没有触发上面的 LLM Intent Router shadow 条件：

- 路由正确性：主要链路均命中预期路径，包括 `plan_fast_route`、`plan_query_fast_route`、`major_intent_fast_route`、`major_compare_fast_route`、`career_direction_fast_route` 和 `pending_intent_impact_fast_route`。
- 安全边界：只读查询不改方案，意向预览不写入，高副作用方案调整保持预览/确认边界。
- 回复质量：没有 fail，也没有 `needs_review`；专业对比、职业方向、意向影响、方案查询、候选空结果和无 pending 确认保护均达到当前自动质量门槛。
- 性能：p95 约 `3.7s`，当前没有因 full-agent 回落过多导致的不可接受延迟。

`候选里还有没有更稳一点的会计审计` 这一 case 曾被评为 fail。复核后确认根因不是路由错判：

- 该轮走 `plan_query_fast_route`，路径正确。
- 后端直查 `session=17` 候选池时，组合查询 `会计学+审计学`、单独查询 `会计学`、单独查询 `审计学` 均返回 `total=0`。
- 当前回复已改为明确说明“按这几个具体专业分别查过，当前候选池没有返回可用结果”，并给出“放宽到专业类 / 看当前方案相近志愿 / 按更稳思路做调整建议”的下一步。
- 评估口径也改为支持“有命中则看分布、无命中则看空结果解释和替代路径”，避免把真实数据为空误判为路由或回复硬失败。

因此，本期继续沿用“本地候选 + 统一仲裁”的主路径。LLM Intent Router 的下一步只保留为预案：当后续真实场景重新出现跨 router 误判、开放取舍被薄回复接管、或同类表达需要持续堆规则时，再按 shadow 方案接入观测。

重启后复验：

- 输出：`/private/tmp/zhiyuan_agent_303_open_quality_restart_live.json`
- 详细评分：`/private/tmp/zhiyuan_agent_303_open_quality_restart_live_eval.md`
- 结果：`23/23` steps 通过，`failedSteps=0`。
- 延迟：runner 中位 `2242ms`，p95 `3661ms`，最大 `3819ms`；详细评分器中位 `2242ms`，p95 `3654ms`，最大 `3819ms`。
- 评分：`strong=23 / needs_review=0 / fail=0`，`quality violations={}`，`evaluation warnings={}`。
- 本次复验确认重启后本地 `8107` Agent、`8080` Server、`5001` Rank 链路仍能读取真实方案/候选事实；未出现后端未启动时的空方案退化。

### 13.2 代表样本展示清洗后的复核

针对用户侧回复里代表样本过长的问题，本轮新增了纯展示层清洗：

- 方案、候选和职业方向代表样本只保留可识别的“院校/专业/冲稳保/位置”等核心信息。
- 去掉 `办学地点`、合作方、前三年就读、外语成绩、学费说明等长招生备注。
- 不改变后端方案、候选池、审查、排序、录取率和专业组结构，只影响对话文本中的样例展示。

典型变化：

| 场景 | 清洗前 | 清洗后 |
| --- | --- | --- |
| 方案前排示例 | `青岛理工大学-建筑学(中外合作办学)(与韩国光云大学合作)(冲)@1` | `青岛理工大学-建筑学(冲)第1位` |
| 意向影响方案命中 | `广州理工学院第102组-会计学(办学地点:...)(保)` | `广州理工学院第102组-会计学（保）` |
| 职业方向承接样本 | `河北师范大学第201组(中外合作办学组)-翻译(合作方:...前三年... )` | `河北师范大学第201组-翻译` |

复验结果：

- 真实 WebSocket 输出：`/private/tmp/zhiyuan_agent_303_open_quality_after_display_clean_live.json`
- 详细评分：`/private/tmp/zhiyuan_agent_303_open_quality_after_display_clean_live_eval.md`
- 结果：`23/23` steps 通过，`failedSteps=0`。
- 延迟：中位 `2256ms`，p95 `3713ms`，最大 `3885ms`。
- 评分：`strong=23 / needs_review=0 / fail=0`，`quality violations={}`。
- 关键词抽检：`办学地点 / 合作方 / 韩国光云 / 波兰波兹南` 在最新输出和评分报告中未命中。
- 剩余 `missing_route_observability=1` 属于观测字段缺失，不影响用户侧回复质量和动作正确性。

对应验证：

- `PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_display_text.py tests/unit/test_intent_state_tool.py::test_enrich_plan_relation_analysis_trims_long_admission_notes_in_examples tests/unit/test_plan_execution_tool.py::test_execute_plan_action_query_state_trims_long_sample_notes tests/unit/test_explore_direction_scenarios_sync.py::test_candidate_brief_trims_long_admission_notes_for_inline_examples -q`：`5 passed`
- `PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_display_text.py tests/unit/test_explore_direction_scenarios_sync.py tests/unit/test_intent_state_tool.py tests/unit/test_plan_execution_tool.py -q`：`211 passed`
- `PYTHONPATH=. ./.venv/bin/python -m pytest tests/unit/test_major_compare_reply_renderer.py tests/unit/test_dialog_case_evaluation_report.py tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_plan_query_tool.py tests/unit/test_fast_route_arbitrator.py -q`：`91 passed`
