# Release 3.0.2 Acceptance Checklist

本文档用于记录 `3.0.2` 稳定版本的验收过程。设计与实现细节见：

- `docs/release-3.0.2-stability-plan.md`
- `docs/release-3.0.2-implementation-design.md`

## 1. 验收状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 版本目标 | 待验收 | P0 已进入实现阶段，需要本地/准生产逐项验证 |
| 最新提交 | 待提交 | 当前工作区仍有 3.0.2 修复改动，提交后更新 commit / tag |
| 后端关键测试 | 已通过 | 2026-05-19 本地补跑 `PlanningStateServiceTest,PlanningExcelExportBuilderTest`，94 tests，0 failures，2 skipped |
| 前端类型检查 | 有既有阻塞 | `tsc --noEmit` 仍受历史类型问题阻塞，不作为本次新增改动失败信号 |
| 本地生成物 | 不提交 | `tsconfig.tsbuildinfo`、`data/tmp/session_volunteer_*.json` 保留本地 |

## 2. 验收环境

| 项目 | 值 |
| --- | --- |
| 验收时间 | 2026-05-18 22:15 CST 起，2026-05-19 继续 |
| 分支 | `develop` |
| 代码提交 | `94cf0d1` |
| 前端地址 | `http://127.0.0.1:3001` |
| 后端地址 | `http://127.0.0.1:8080` |
| Agent 地址 | `http://127.0.0.1:8000` |
| Rank 地址 | `http://127.0.0.1:5001` |

基础服务 smoke：

| 检查项 | 结果 | 记录 |
| --- | --- | --- |
| `/customerDetail` | 通过 | `HTTP 200` |
| `/customer` | 通过 | `HTTP 200` |
| `/sessionDetailV2?chatSessionId=17&userId=1&page=1&pageSize=10` | 通过 | `HTTP 200` |
| 后端 `/gaotu-assistant-bot/base-data/ethnicity-list` | 通过 | `HTTP 200` |
| Agent `/docs` | 通过 | `HTTP 200` |
| Rank 端口 | 通过 | `127.0.0.1:5001` listening |
| 外部初始化 `v1` 无授权调用 | 通过 | 返回 `code=800`、`msg=不合法请求`，说明接口受 `tk/pf` 授权保护；创建型 live 验收需有效授权上下文 |

验证时优先使用新建会话，避免历史会话脏数据影响判断。必须覆盖：

- 专业+大学模式
- 院校专业组模式

## 3. P0 验收清单

### 3.1 登录后默认进入会话列表

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| C 端账号密码登录 | 登录后进入 `/customer`，默认打开会话列表 | 待验证 |  |
| C 端手机号登录 | 登录后进入 `/customer`，默认打开会话列表 | 待验证 |  |
| C 端 token 登录 | 静默登录后进入 `/customer`，默认打开会话列表 | 待验证 |  |
| B 端用户登录 | 仍进入 `/session` 会话列表 | 待验证 |  |
| 外部深链路进入详情 | 不被默认会话列表跳转打断 | 待验证 |  |

### 3.2 前置信息采集缓存与创建会话

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 完成高考信息后刷新 | 回到当前步骤，已确认字段保留 | 待验证 |  |
| 完成个人信息两个子步骤后刷新 | 分数、位次、批次、身体情况均回填；总结区和继续入口恢复 | 待验证 |  |
| 完成专业意向后刷新 | 已选专业、排除专业、学费区间和是否接受外校回填；总结区和继续入口恢复 | 待验证 |  |
| 完成区域意向后刷新 | 已选省份回填；总结区和继续入口恢复 | 待验证 |  |
| 切到新会话且没有有效缓存 | 不沿用上一个会话的确认态、总结态和已填值 | 待验证 |  |
| `/customerDetail` 页面入口和弹窗创建入口分别进入 | 缓存恢复、无缓存重置、选科策略加载行为一致 | 待验证 |  |
| 首次进入选科成绩子步骤 | 后端/用户信息里的默认选科正常选中；未点击确认前不出现右侧“确认提交”反馈气泡 | 待验证 |  |
| 首次进入选科成绩子步骤且批次线接口返回数据 | 批次下拉自动选中默认批次线，文案包含批次线分数；异步加载后不被空默认值清掉 | 待验证 |  |
| 选科成绩子步骤输入各科分数 | 总分自动计算；批次线已选中时成绩排名自动回填 | 待验证 |  |
| 选科成绩子步骤切换批次 | 特殊省份专科批总分口径重新计算，成绩排名按新批次重新拉取 | 待验证 |  |
| 选科成绩子步骤确认 | 页面自动滚到身体信息子步骤起始位置，用户能看到下一段内容已出现 | 待验证 |  |
| 在个人信息页点击上一步 | 回到上一采集步骤，已确认字段回填 | 待验证 |  |
| 身体情况填写视力 4.3/4.3 后提交 | 不再提示“请输入视力情况”，不回滚到分数区域 | 待验证 |  |
| 不同选科/批次进入专业意向 | 负意向专业类按当前选科和批次重新获取，不固定为同一套列表 | 待验证 |  |
| 志愿填报策略确认 | 底部只出现一个“了解完成，继续下一步”入口 | 待验证 |  |
| 完成志愿策略后刷新 | 已选策略回填；总结区和继续入口恢复 | 待验证 |  |
| 最终创建请求 | 请求体包含完整 `batch`，不再返回 `系统错误` | 待验证 |  |
| 创建成功 | 默认回到会话列表，不直接进入新创建的会话详情 | 待验证 |  |
| 创建成功后再次新建 | 不恢复上一次已消费缓存 | 待验证 |  |
| 批次异常缺失 | 前端展示“请选择批次后再创建会话”，后端不再 NPE | 自动测试已覆盖后端校验；前端待验证 | `ChatSessionBizServiceTest#shouldRejectCreateSessionWhenBatchMissing` |

### 3.3 外部初始化会话学员姓名展示

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 调旧路径初始化并传 `createSession.userName` | 响应和会话详情可追溯学员姓名 | 后端测试已覆盖；页面待验证 |  |
| 调 `v1` 路径初始化并传 `createSession.userName` | 响应返回 `studentName`，行为与旧路径一致 | 后端测试已覆盖；页面待验证 |  |
| 不传学员姓名 | 详情页不展示空姓名标签 | 待验证 |  |
| 打开 `sessionUrl` | 详情页顶部在“模拟填报/智能填报”前展示姓名 | 待验证 |  |

### 3.4 候选筛选已选条件快捷移除

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 添加一个正向地域筛选 | 已选条件条展示该条件 | 待验证 |  |
| 添加一个排除地域筛选 | 已选条件条展示排除条件，视觉上可区分 | 待验证 |  |
| 删除排除条件 | 正向筛选保留，候选列表按剩余条件刷新 | 待验证 |  |
| 删除正向条件 | 排除条件保留，候选列表按剩余条件刷新 | 待验证 |  |
| 父级筛选分组已选后折叠 | 选择“院校地域 > 上海”后仍可折叠“院校地域” | 待验证 |  |

### 3.5 院校名与三级专业筛选

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 院校名称正向筛选 | 候选列表只保留匹配院校 | 待验证 |  |
| 院校名称排除筛选 | 候选列表排除匹配院校 | 待验证 |  |
| 专业门类展开到专业大类 | 层级展示稳定，不出现意向专业类等旧标签 | 待验证 |  |
| 专业大类展开到三级专业 | 可选择具体专业名 | 待验证 |  |
| 三级专业正向筛选 | 候选列表只保留匹配专业 | 待验证 |  |
| 三级专业排除筛选 | 候选列表排除匹配专业 | 待验证 |  |
| 未归类专业 | 统一在“其他专业”尾部展示 | 待验证 |  |
| 专业+大学模式 | 筛选项和结果均稳定 | 待验证 |  |
| 院校专业组模式 | 筛选项和结果均稳定 | 待验证 |  |

### 3.6 候选空态口径

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 用户筛选导致结果为空 | 候选列表只提示“当前筛选结果为空” | 待验证 |  |
| 系统候选池本身为空 | 展示系统候选状态和具体风险原因，不提示用户放宽筛选 | 待验证 |  |
| 用户筛选后再清空条件 | 恢复候选列表或系统候选空态 | 待验证 |  |

### 3.7 专业组内专业顺序

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 新建院校专业组模式会话 | 生成方案后，每个专业组内已选专业按专业录取率从低到高展示 | 自动测试已覆盖；页面待验证 | `PlanningStateServiceTest#shouldDisplaySelectedMajorGroupMajorsByAdmissionRatioAsc` |
| 院校专业组模式方案页 | 专业组标题展示组级录取率；页面优先读取 `orderedPlanState.units`，刷新后不丢失组级录取率和组内专业顺序 | 待验证 |  |
| 包含托底专业的专业组 | 托底专业仍保留，但不会强制排在录取率更低的专业前面 | 自动测试已覆盖原托底保留；页面待验证 | `shouldPreferSafetyMajorWhenBuildingPlanningUnit` 仍通过 |
| 组内存在录取率缺失专业 | 缺失录取率的专业排在有录取率专业之后，不丢失 | 待补边界验证 |  |
| 手动移动专业组整体顺序 | 只改变专业组位置，不打散组内专业顺序 | 自动测试已覆盖；页面待验证 | `shouldSortMajorGroupPlanByFinalScoreWithoutBreakingGroupMajors` 补充断言 |
| 专业组模式导出 | Excel 中组内专业顺序与页面一致 | 自动测试已覆盖；文件待人工验证 | `PlanningExcelExportBuilderTest#shouldBuildMajorGroupExportRowsFromOrderedUnits` |

### 3.8 专业+大学模式导出结构

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 专业+大学模式同校多个专业 | 导出文件中每个“学校 + 专业”是独立志愿行，不按学校合并成一个嵌套单元 | 自动测试已覆盖；文件待人工验证 | `PlanningExcelExportBuilderTest#shouldBuildMajorSchoolExportRowsPerOrderedMajor` |
| 专业+大学模式导出序号 | 序号从 1 连续递增，顺序与页面排序区一致 | 自动测试已覆盖；文件待人工验证 | 同上 |
| 手动移动或排序后导出 | 导出顺序跟随调整后的当前方案顺序 | 后端排序映射已覆盖；页面待验证 | 导出按 `orderedPlanState.items.position` 映射 |
| 院校专业组模式导出回归 | 仍按一个专业组一个导出单元，组内专业明细保留 | 自动测试已覆盖 | `shouldBuildMajorGroupExportRowsFromOrderedUnits`、旧 ID 兼容测试仍通过 |

### 3.9 Agent 长历史污染和上下文成本

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 长历史会话普通查询 | “看看方案”等只读查询不被旧偏好、旧 preview 或旧工具结果污染 | 单测已覆盖 runtime 裁剪；场景待验证 | 见 implementation design 8 |
| 长历史会话高副作用动作 | 排序、移动、删除、加入方案仍先 preview，确认后 apply | 自动回归已通过；真实 WebSocket 待验证 | `tests/regression/test_execution_preview.py`、`test_execution_apply.py` |
| 长历史会话确认动作 | 存在 pending 时可直接执行；不存在 pending 时返回 no-pending guard | 自动回归已通过 | `tests/regression/test_pending_protocol.py`、`test_chat_service_history_persistence.py` |
| Token 成本 | 主 agent 输入 token 相比完整历史显著下降，完整历史仍保留用于审计 | 单测已验证 runtime chars 下降；真实日志待观测 |  |

## 4. P1 验收清单

P1 不阻塞 3.0.2 P0 准入，但需要确认是否纳入本版本最终发布范围。

| 项目 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| Agent 对话触发筛选 | 对话写入的筛选状态在前端可见、可撤销 | 待排期 |  |
| Agent 对话触发方案编辑 | 移动、删除、加入方案覆盖专业+大学和专业组模式 | 自动场景目录已补，真实 WebSocket 待验证 | 见 5.1.2、5.1.3 |
| 学校/专业简称匹配 | 简称能匹配到合理候选，不误操作相似项 | 待排期 |  |
| 筛选行为事件 | 添加/排除/移除/清空筛选记录行为事件 | 待排期 |  |
| 长历史治理 | 长历史不污染当前方案编辑和筛选意图 | 首轮实现已完成，待真实场景验证 | P0 先完成低风险 runtime 裁剪和 pending 轮保留 |
| Explore/Intent 前置层场景 | 专业/职业/地域/院校探索、软硬意向、意向修订和未确认意向查询方案 | 自动场景目录已补，真实 WebSocket 待验证 | 先增强样例，后续根据真实结果串联调优 |

## 5. 自动化验证记录

### 5.1 后端关键测试

```bash
cd zhiyuan-server
mvn -Dtest=ChatSessionBizServiceTest,IntegrationSessionServiceTest,PlanningStateServiceTest,IntegrationSessionControllerTest,PlanningExcelExportBuilderTest test
```

结果：

- 时间：2026-05-19
- 结果：通过
- 汇总：111 tests，0 failures，0 errors，2 skipped

覆盖点：

- 创建会话缺批次时返回业务错误，不再空指针。
- 外部初始化旧路径和 `v1` 路径。
- 外部初始化响应 `studentName`。
- 候选筛选项、候选身份归一和规划状态相关单测。
- 专业组内专业录取率正排和专业+大学导出结构回归。

### 5.1.1 专业组顺序与导出结构专项回归

```bash
cd zhiyuan-server
mvn -Dtest=PlanningExcelExportBuilderTest,PlanningStateServiceTest test
```

结果：

- 时间：2026-05-19
- 结果：通过
- 汇总：94 tests，0 failures，0 errors，2 skipped

覆盖点：

- 专业组内 `selectedMajors / draftUnit.majorItems / orderedUnit.majorItems` 按专业录取率正排。
- 专业组移动/排序后仍按专业组整体操作，组内专业顺序不被排序区位置调整打散。
- 专业组导出继续保持一个专业组一行，并按专业录取率正排组内专业。
- 专业+大学模式同校多专业导出为多条独立志愿行，每行只包含一个专业。
- 专业+大学、院校专业组两种模式的旧 ID 兼容导出测试仍通过。

### 5.1.2 Agent 长历史治理专项回归

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_mainline_dialog_scenarios.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_plan_execution_tool.py tests/regression/test_pending_protocol.py tests/regression/test_execution_preview.py tests/regression/test_execution_apply.py -q
```

结果：

- 时间：2026-05-19
- 结果：通过
- 汇总：442 passed

覆盖点：

- 长历史传给主 agent 前按 `HISTORY_RUNTIME_MAX_MESSAGES` 裁剪。
- 存在待确认方案动作时，runtime history 会保留产生 pending 的工具调用/工具返回/预览回复，避免非确认追问丢上下文。
- 超长 tool return 会压缩为短摘要，不继续把大 JSON 注入模型。
- SQLite 仍保留完整历史，并在本轮结束后追加新消息。
- `RequestContext.chat_history` 使用短文本历史和当前用户输入。
- 方案 pending、preview 和 apply 回归继续通过，高副作用动作仍遵循 preview -> confirm -> apply。
- 3.0.2 对话场景样例目录校验通过，覆盖查询、排序、专业组移动、学校/专业简称删除、调整后查询。
- 3.0.2 Explore/Intent 场景样例目录校验通过，覆盖专业/职业/地域/院校探索、软硬意向、意向修订、未确认意向下查询方案和候选风险解释。
- 执行层补充“广西师大统计”这类学校简称 + 专业简称删除方案志愿的回归；同类歧义简称仍要求用户补充信息。

### 5.1.3 Agent 真实 WebSocket 场景样例

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_agent_cases.json \
  --assert-plan-style \
  --response-timeout 180

.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_explore_intent_cases.json \
  --assert-plan-style \
  --response-timeout 180
```

状态：

- 时间：2026-05-19
- 结果：首轮真实 WebSocket 验证未完全通过，需要继续收口后复跑
- 样例文件：`zhiyuan-agent/examples/dialog_regression_302_agent_cases.json`、`zhiyuan-agent/examples/dialog_regression_302_explore_intent_cases.json`

覆盖点：

- 专业+大学模式方案现状查询和按院校层次排序。
- 院校专业组模式专业组整体移动。
- 按学校简称 + 专业简称删除方案志愿。
- 高副作用动作确认后刷新方案区。
- Explore/Intent 前置层不误触发方案变更，Intent 仍先 preview 后确认。
- 用户未确认意向时查询方案，不应自动确认或重复弹确认。

首轮真实运行记录：

- `302-status-major-readable / session=17` 通过，回复包含冲稳保和风险摘要，耗时约 61s。
- `302-sort-school-rank-major / session=17` 通过，预览约 42s，确认约 2.8s，确认后发送 `ordered` 刷新。
- `302-move-unit-major-group / session=16` 未通过，`把第3个专业组移到第5位` 触发 180s 超时兜底，未形成 pending；随后“确认”命中 no-pending guard。该项属于真实运行链路问题，需要继续定位。
- `302-remove-by-school-major-abbrev / session=17` 首轮样例无效：原样例“广西师大统计”不在当前 session 17 方案中，系统返回 no-change 是正确行为。样例已调整为 session 17 当前方案中真实存在的“河南农大建筑”，待复跑。
- `302-query-after-mutation / session=17` 通过，回复不暴露内部结构字段。

复跑定位记录：

- 本机曾同时存在两个 Agent 监听 8000，其中旧进程绑定 `127.0.0.1:8000`，导致首轮 WebSocket 验证一度命中旧代码；已停止旧进程并按当前工作区重新启动 Agent。
- 当前代码日志确认 runtime history 生效：`session=16 full_len=352 runtime_len=24 full_chars=264677 runtime_chars=15001 dropped_tool_returns=2`。
- 重新复跑 `session=16 / 把第3个专业组移到第5位` 时，硅基流动连续返回 `503 System is too busy now`，因此真实业务效果暂不能继续判断。
- compat WebSocket 异常响应已修复为带 `end=true`；同一请求现在约 7s 返回 `{"type":"error","end":true}`，不再表现为 runner 等待 180s 超时。

### 5.2 前端验证

```bash
cd zhiyuan-web
npm exec tsc -- --noEmit
```

结果：

- 状态：未通过
- 原因：项目存在既有 TypeScript 类型债，当前错误集中在 `IOptions` 类型、隐式 `any`、`userCenter` props 等历史问题。
- 处理口径：不作为 3.0.2 当前新增改动失败信号；发布前仍需至少完成本地页面 smoke 和关键链路人工验收。

## 6. 发布前检查

| 项目 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 工作区清理 | 不提交 `tsconfig.tsbuildinfo`、`data/tmp/session_volunteer_*.json` | 待处理 | 当前仍有本地生成物 |
| 后端关键测试 | 通过 | 已通过 | 见 5.1 |
| 前端本地 smoke | `/customerDetail`、`/customer`、`/sessionDetailV2` 可访问 | 已通过 | 三个页面均返回 `HTTP 200` |
| 创建新会话 | 专业+大学和专业组模式均能生成方案 | 待验证 |  |
| 外部初始化接口 | 旧路径和 `v1` 路径均可用 | 部分通过 | `v1` 无授权调用返回 `不合法请求`；带授权创建型调用待验证 |
| 专业组内专业顺序 | 已选专业按录取率正排，页面和导出一致 | 自动测试已通过，页面待验证 | 见 5.1.1 |
| 专业+大学导出结构 | 一条志愿一行，不按学校聚合 | 自动测试已通过，文件待人工验证 | 见 5.1.1 |
| 创建成功跳转 | 新建会话完成后进入 `/sessionDetailV2`，不打开会话列表/抽屉 | 待验证 | `/customerDetail` 与嵌入式抽屉都需覆盖 |
| 专业意向确认气泡 | 不出现 `[object Object]`、`false`，展示意向/排除/中外合作/学费可读摘要 | 待验证 | 明确专业意向步骤 |
| Agent 长历史治理 | 降低主 agent 完整历史输入，避免旧 preview/tool return 污染当前轮 | 首轮实现已完成，需继续场景验证 | 见 5.1.2 |
| 文档与 changelog | 3.0.2 文档和前后端 changelog 已更新 | 已完成 |  |
| tag / 构建包 | P0 验收通过后再打 `prod-3.0.2` | 未开始 |  |

## 7. 问题记录

| 时间 | 问题 | 影响 | 状态 | 处理 |
| --- | --- | --- | --- | --- |
| 2026-05-18 | 最终创建请求缺少 `batch` 时返回“系统错误” | 阻塞新建会话 | 已修复，待页面复验 | 前端最终提交前补齐批次，后端保存前校验核心字段 |
| 2026-05-19 | 个人信息采集缓存恢复误把空派生字段当成已确认，导致选科默认值被空数组覆盖，并提前展示“确认提交”反馈 | 影响新建会话选科成绩子步骤 | 已修复，待页面复验 | 只在存在真实个人信息缓存时恢复确认态；无真实缓存时保留表单默认选科 |
| 2026-05-19 | 批次线加载后会被后续表单初始化用空 `defaultValue` 覆盖 | 影响新建会话默认批次线展示和后续创建 payload | 已修复，待页面复验 | 表单初始化值改为优先使用已缓存批次、当前有效批次或批次线列表第一项 |
| 2026-05-19 | 断点续填恢复和异步批次线加载没有重放总分/排名派生计算 | 影响总分、成绩排名自动填充 | 已修复，待页面复验 | 初始化、批次线加载和用户输入统一走分数派生刷新；3+1+2 选科提交兼容拆分字段 |
| 2026-05-19 | 生产 `2268` 院校专业组模式中，方案内专业组的已选专业没有按老版本录取率正排口径展示 | 影响专业组内风险可读性和用户信任 | 已修复，页面待复验 | 选择策略不变，展示/草稿/排序区/导出统一按专业录取率正排 |
| 2026-05-19 | 生产 `2268` 专业+大学模式导出出现类似专业组的嵌套专业结构 | 影响导出文件志愿边界和用户理解 | 已修复，导出文件待人工复验 | 专业模式导出改为一条排序志愿一行，专业组模式保持原结构 |
| 2026-05-19 | Agent 真实 WebSocket 复跑时硅基流动返回 `503 System is too busy now`，compat 异常响应缺少 `end=true`，测试端表现为等待到超时 | 影响模型接口异常时的前端收口和自动验证判定 | 已修复，待复验 | compat WebSocket 异常响应补 `end=true`；真实效果仍需在模型服务可用时复跑 |
| 2026-05-19 | 创建会话成功后误进入会话列表或移动端抽屉 | 用户无法直接看到刚生成的方案 | 已修复，待页面复验 | 创建成功统一跳转新会话详情；个人信息补全回列表作为独立入口保留 |
| 2026-05-19 | 专业意向采集确认气泡出现 `[object Object]`、`false` | 影响采集流程可理解性 | 已修复，待页面复验 | 专业意向确认气泡改为字段级格式化摘要 |
| 2026-05-19 | 本地新建 `121` 被反馈专业组内专业应按老版本正排口径展示 | 需确认是默认方案排序口径还是前端展示问题 | 已修复，页面待复验 | 后端组内 `orderedPlanState.units.majorItems` 改为录取率正排；验证前需重启后端 |
