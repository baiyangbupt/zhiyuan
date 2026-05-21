# Release 3.0.2 Acceptance Checklist

本文档用于记录 `3.0.2` 稳定版本的验收过程。设计与实现细节见：

- `docs/release-3.0.2-stability-plan.md`
- `docs/release-3.0.2-implementation-design.md`

## 1. 验收状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 版本目标 | P0 人工验收通过，系统验证中 | 前端人工可验部分已完成，继续进行自动化、接口和 Agent 场景验证 |
| 代码复核 | 已完成 | 前置信息缓存、专业组内专业排序、专业+大学导出结构已按主链路确认 |
| 最新提交 | `b624345` | 当前基线为 rebase 后本地 `develop`，验收记录提交后再更新最终发布 commit / tag |
| 后端关键测试 | 已通过 | 2026-05-22 本地补跑 `PlanningStateServiceTest,PlanningBehaviorEventSharedServiceTest`，97 tests，0 failures，2 skipped；外部初始化 clean 定向测试 23 tests，0 failures |
| 后端全量测试 | 已通过 | 2026-05-21 沙箱外执行 `mvn test`，216 tests，0 failures，0 errors，2 skipped；移除旧 `behaviorEvents` DTO 字段后已复跑通过；沙箱内会因本机 MySQL 连接被拦截失败 |
| 前端类型检查 | 有既有阻塞 | `tsc --noEmit` 仍受历史类型问题阻塞，不作为本次新增改动失败信号 |
| 本地生成物 | 不提交 | `tsconfig.tsbuildinfo`、`data/tmp/session_volunteer_*.json` 保留本地 |

## 2. 验收环境

| 项目 | 值 |
| --- | --- |
| 验收时间 | 2026-05-18 22:15 CST 起，2026-05-20 继续 |
| 分支 | `develop` |
| 代码提交 | `b624345` |
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
| C 端账号密码登录 | 登录后进入 `/customer`，默认打开会话列表 | 前端人工通过 | 2026-05-20 人工验收 |
| C 端手机号登录 | 登录后进入 `/customer`，默认打开会话列表 | 前端人工通过 | 2026-05-20 人工验收 |
| C 端 token 登录 | 静默登录后进入 `/customer`，默认打开会话列表 | 前端人工通过 | 2026-05-20 人工验收 |
| B 端用户登录 | 仍进入 `/session` 会话列表 | 前端人工通过 | 2026-05-20 人工验收 |
| 外部深链路进入详情 | 不被默认会话列表跳转打断 | 前端人工通过 | 2026-05-20 人工验收 |

### 3.2 前置信息采集缓存与创建会话

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 完成高考信息后刷新 | 回到当前步骤，已确认字段保留 | 前端人工通过 | 2026-05-20 人工验收 |
| 完成个人信息两个子步骤后刷新 | 分数、位次、批次、身体情况均回填；总结区和继续入口恢复 | 前端人工通过 | 2026-05-20 人工验收 |
| 完成专业意向后刷新 | 已选专业、排除专业、学费区间和是否接受外校回填；总结区和继续入口恢复 | 前端人工通过 | 2026-05-20 人工验收 |
| 完成区域意向后刷新 | 已选省份回填；总结区和继续入口恢复 | 前端人工通过 | 2026-05-20 人工验收 |
| 切到新会话且没有有效缓存 | 不沿用上一个会话的确认态、总结态和已填值 | 前端人工通过 | 2026-05-20 人工验收 |
| `/customerDetail` 页面入口和弹窗创建入口分别进入 | 缓存恢复、无缓存重置、选科策略加载行为一致 | 前端人工通过 | 2026-05-20 人工验收 |
| 首次进入选科成绩子步骤 | 后端/用户信息里的默认选科正常选中；未点击确认前不出现右侧“确认提交”反馈气泡 | 前端人工通过 | 2026-05-20 人工验收 |
| 首次进入选科成绩子步骤且批次线接口返回数据 | 批次下拉自动选中默认批次线，文案包含批次线分数；异步加载后不被空默认值清掉 | 前端人工通过 | 2026-05-20 人工验收 |
| 选科成绩子步骤输入各科分数 | 总分自动计算；批次线已选中时成绩排名自动回填 | 前端人工通过 | 2026-05-20 人工验收 |
| 选科成绩子步骤切换批次 | 特殊省份专科批总分口径重新计算，成绩排名按新批次重新拉取 | 前端人工通过 | 2026-05-20 人工验收 |
| 选科成绩子步骤确认 | 页面自动滚到身体信息子步骤起始位置，用户能看到下一段内容已出现 | 前端人工通过 | 2026-05-20 人工验收 |
| 在个人信息页点击上一步 | 回到上一采集步骤，已确认字段回填 | 前端人工通过 | 2026-05-20 人工验收 |
| 身体情况填写视力 4.3/4.3 后提交 | 不再提示“请输入视力情况”，不回滚到分数区域 | 前端人工通过 | 2026-05-20 人工验收 |
| 不同选科/批次进入专业意向 | 负意向专业类按当前选科和批次重新获取，不固定为同一套列表 | 前端人工通过 | 2026-05-20 人工验收 |
| 志愿填报策略确认 | 底部只出现一个“了解完成，继续下一步”入口 | 前端人工通过 | 2026-05-20 人工验收 |
| 完成志愿策略后刷新 | 已选策略回填；总结区和继续入口恢复 | 前端人工通过 | 2026-05-20 人工验收 |
| 最终创建请求 | 请求体包含完整 `batch`，不再返回 `系统错误` | 前端人工通过 | 2026-05-20 人工验收 |
| 创建成功 | 进入新创建的会话详情页，不打开会话列表/移动端抽屉 | 前端人工通过 | 2026-05-20 人工验收 |
| 创建成功后再次新建 | 不恢复上一次已消费缓存 | 前端人工通过 | 2026-05-20 人工验收 |
| 批次异常缺失 | 前端展示“请选择批次后再创建会话”，后端不再 NPE | 自动测试已覆盖后端校验；前端人工通过 | `ChatSessionBizServiceTest#shouldRejectCreateSessionWhenBatchMissing`；2026-05-20 人工验收 |

### 3.3 外部初始化会话学员姓名展示

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 调旧路径初始化并传 `createSession.userName` | 响应和会话详情可追溯学员姓名 | 后端测试已覆盖；页面人工通过 | 2026-05-20 人工验收 |
| 调 `v1` 路径初始化并传 `createSession.userName` | 响应返回 `studentName`，行为与旧路径一致 | 后端测试已覆盖；页面人工通过 | 2026-05-20 人工验收 |
| 不传学员姓名 | 详情页不展示空姓名标签 | 前端人工通过 | 2026-05-20 人工验收 |
| 打开 `sessionUrl` | 详情页顶部展示“高翔的志愿规划工作台” | 前端人工通过 | 2026-05-20 人工验收 |
| 线上兼容无版本路径 | `/integration/session/initialize` 继续可用，不要求 3.0.1 调用方改为 `v1` | 后端测试已覆盖 | `IntegrationSessionControllerTest#shouldInitializeExternalSession` |
| 稳定版本路径 | `/integration/v1/session/initialize` 与无版本路径共用同一实现 | 后端测试已覆盖 | `IntegrationSessionControllerTest#shouldInitializeExternalSessionWithV1Path` |
| `strategy_type` 兼容 | 外部 snake_case 字段可映射到 `createSession.strategyType` | 后端测试已覆盖 | `IntegrationSessionControllerTest#shouldBindSnakeCaseStrategyTypeOnExternalSessionRequest` |
| 缺 `sex` | 创建前默认补 `female/女`，接口不因缺性别失败 | 后端测试已覆盖 | `ChatSessionBizServiceTest#shouldFillDefaultSexAndStrategyTypeWhenMissing` |
| 缺 `strategyType` | 创建前默认补 `cautious/稳妥型`，后续方案目标数仍按目标志愿数计算 | 后端测试已覆盖 | `ChatSessionBizServiceTest#shouldFillDefaultSexAndStrategyTypeWhenMissing` |
| 缺 `strategyType` 的 `requiredTierCounts` | 可信旧 targetMap 继续沿用；明显候选规模 map 不再回退，按 `need_count + cautious` 计算冲稳保 | 后端测试已覆盖 | `PlanningStateServiceTest#shouldFallbackToCautiousStrategyWhenStrategyTypeMissing` |
| 缺 `need_count` 的 `requiredTierCounts` | 不使用候选规模兜底，最终默认目标数为 45 | 后端测试已覆盖 | `PlanningStateServiceTest#shouldFallbackToDefaultPlanCountWhenNeedCountMissing` |

### 3.4 候选筛选已选条件快捷移除

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 添加一个正向地域筛选 | 已选条件条展示该条件 | 前端人工通过 | 2026-05-20 人工验收 |
| 添加一个排除地域筛选 | 已选条件条展示排除条件，视觉上可区分 | 前端人工通过 | 2026-05-20 人工验收 |
| 删除排除条件 | 正向筛选保留，候选列表按剩余条件刷新 | 前端人工通过 | 2026-05-20 人工验收 |
| 删除正向条件 | 排除条件保留，候选列表按剩余条件刷新 | 前端人工通过 | 2026-05-20 人工验收 |
| 父级筛选分组已选后折叠 | 选择“院校地域 > 上海”后仍可折叠“院校地域” | 前端人工通过 | 2026-05-20 人工验收 |

### 3.5 院校名与三级专业筛选

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 院校名称正向筛选 | 候选列表只保留匹配院校 | 前端人工通过 | 2026-05-20 人工验收 |
| 院校名称排除筛选 | 候选列表排除匹配院校 | 前端人工通过 | 2026-05-20 人工验收 |
| 专业门类展开到专业大类 | 层级展示稳定，不出现意向专业类等旧标签 | 前端人工通过 | 2026-05-20 人工验收 |
| 专业大类展开到三级专业 | 可选择具体专业名 | 前端人工通过 | 2026-05-20 人工验收 |
| 三级专业正向筛选 | 候选列表只保留匹配专业 | 前端人工通过 | 2026-05-20 人工验收 |
| 三级专业排除筛选 | 候选列表排除匹配专业 | 前端人工通过 | 2026-05-20 人工验收 |
| 未归类专业 | 统一在“其他专业”尾部展示 | 前端人工通过 | 2026-05-20 人工验收 |
| 专业+大学模式 | 筛选项和结果均稳定 | 前端人工通过 | 2026-05-20 人工验收 |
| 院校专业组模式 | 筛选项和结果均稳定 | 前端人工通过 | 2026-05-20 人工验收 |

### 3.6 候选空态口径

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 用户筛选导致结果为空 | 候选列表只提示“当前筛选结果为空” | 前端人工通过 | 2026-05-20 人工验收 |
| 系统候选池本身为空 | 展示系统候选状态和具体风险原因，不提示用户放宽筛选 | 前端人工通过 | 2026-05-20 人工验收 |
| 用户筛选后再清空条件 | 恢复候选列表或系统候选空态 | 前端人工通过 | 2026-05-20 人工验收 |

### 3.7 专业组内专业顺序

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 新建院校专业组模式会话 | 生成方案后，每个专业组内已选专业按专业录取率从低到高展示 | 自动测试已覆盖；前端人工通过；代码复核通过 | `PlanningStateServiceTest#shouldDisplaySelectedMajorGroupMajorsByAdmissionRatioAsc`；2026-05-20 人工验收 |
| 院校专业组模式方案页 | 专业组标题展示组级录取率；页面优先读取 `orderedPlanState.units`，刷新后不丢失组级录取率和组内专业顺序 | 前端人工通过；代码复核通过 | 2026-05-20 人工验收 |
| 包含托底专业的专业组 | 托底专业仍保留，但不会强制排在录取率更低的专业前面 | 自动测试已覆盖；前端人工通过 | `shouldPreferSafetyMajorWhenBuildingPlanningUnit` 仍通过；2026-05-20 人工验收 |
| 组内存在录取率缺失专业 | 缺失录取率的专业排在有录取率专业之后，不丢失 | 自动测试覆盖；前端人工通过 | 2026-05-20 人工验收 |
| 手动移动专业组整体顺序 | 只改变专业组位置，不打散组内专业顺序 | 自动测试已覆盖；前端人工通过 | `shouldSortMajorGroupPlanByFinalScoreWithoutBreakingGroupMajors`；2026-05-20 人工验收 |
| 专业组模式导出 | Excel 中组内专业顺序与页面一致 | 自动测试已覆盖；文件人工通过 | `PlanningExcelExportBuilderTest#shouldBuildMajorGroupExportRowsFromOrderedUnits`；2026-05-20 人工验收 |

### 3.8 专业+大学模式导出结构

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 专业+大学模式同校多个专业 | 导出文件中每个“学校 + 专业”是独立志愿行，不按学校合并成一个嵌套单元 | 自动测试已覆盖；文件人工通过；代码复核通过 | `PlanningExcelExportBuilderTest#shouldBuildMajorSchoolExportRowsPerOrderedMajor`；2026-05-20 人工验收 |
| 专业+大学模式导出序号 | 序号从 1 连续递增，顺序与页面排序区一致 | 自动测试已覆盖；文件人工通过 | 同上；2026-05-20 人工验收 |
| 手动移动或排序后导出 | 导出顺序跟随调整后的当前方案顺序 | 后端排序映射已覆盖；前端人工通过 | 导出按 `orderedPlanState.items.position` 映射；2026-05-20 人工验收 |
| 院校专业组模式导出回归 | 仍按一个专业组一个导出单元，组内专业明细保留 | 自动测试已覆盖；文件人工通过；代码复核通过 | `shouldBuildMajorGroupExportRowsFromOrderedUnits`、旧 ID 兼容测试仍通过；2026-05-20 人工验收 |

### 3.9 Agent 长历史污染和上下文成本

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 长历史会话普通查询 | “看看方案”等只读查询不被旧偏好、旧 preview 或旧工具结果污染 | 单测已覆盖 runtime 裁剪；场景待验证 | 见 implementation design 8 |
| 长历史会话高副作用动作 | 排序、移动、删除、加入方案仍先 preview，确认后 apply | 自动回归已通过；真实 WebSocket 待验证 | `tests/regression/test_execution_preview.py`、`test_execution_apply.py` |
| 长历史会话确认动作 | 存在 pending 时可直接执行；不存在 pending 时返回 no-pending guard | 自动回归已通过 | `tests/regression/test_pending_protocol.py`、`test_chat_service_history_persistence.py` |
| Token 成本 | 主 agent 输入 token 相比完整历史显著下降，完整历史仍保留用于审计 | 单测已验证 runtime chars 下降；真实日志待观测 |  |

### 3.10 行为事件新表与导出态迁移

| 用例 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| 新表写入添加/删除/移动/排序/导出事件 | 成功动作都能在新表查到对应事件 | 已实现 | 已补单测 |
| 无效方案动作不落事件 | 重复加入、删除不存在志愿等没有实际改变方案的请求不写行为事件，也不递增方案版本 | 已实现 | 已补单测 |
| 行为事件载荷 | 方案动作事件包含动作对象、前后位置和必要志愿展示字段；专业组整体动作和方案排序也能补齐候选池里的录取率、院校排名、推荐分等字段；候选筛选事件不记录 | 已实现 | `eventPayloadJson` 承载详情，`snapshotDigest` 仅短摘要；已补单测 |
| 专业+大学模式行为事件 | `plan_add / plan_remove / plan_item_move / plan_sort_apply / plan_export` 均写入 `mode=major`，主要对象为 `volunteerIds`，`eventPayloadJson.items` 包含学校、专业、录取率、院校排名和排序位置 | 已实现 | `PlanningStateServiceTest#shouldGenerateMoveAndPinOrderedPlan`、`shouldSortMajorPlanByAdmissionRatioAndKeepPinnedPosition`、`shouldPersistExportBehaviorEventAndKeepExportStatusReady` |
| 院校专业组模式行为事件 | `plan_add / plan_remove / plan_unit_move / plan_unit_remove / plan_sort_apply / plan_export` 均写入 `mode=majorGroup`；组级动作同时记录 `unitIds` 和组内 `volunteerIds`，payload 保留组内专业明细 | 已实现 | `PlanningStateServiceTest#shouldMoveAndRemoveMajorGroupOrderedUnits`、`shouldSortMajorGroupPlanByFinalScoreWithoutBreakingGroupMajors` |
| 旧 JSON 事件退出主链路 | `planningState.behaviorEvents` 不再作为业务读写来源，新动作不再写入旧 JSON，工作台响应不再返回事件列表 | 已实现 | 已补单测；`PlanningStateDTO` 已移除旧字段，老 JSON 残留字段会被忽略 |
| `exportStatus` 从新表读取 | 导出、已导出后调整、未导出三种状态与旧口径一致 | 已实现 | 已补单测 |
| 新表未命中 | 不再读取旧 `planningState.behaviorEvents`，导出态按未导出处理 | 已实现 | 已补单测 |
| 删除旧 JSON DTO 字段 | 服务端状态 DTO 不再保留旧事件列表字段 | 已实现 | 已补单测 |

验证记录：

- 2026-05-21：`mvn -Dtest=PlanningStateServiceTest,PlanningBehaviorEventSharedServiceTest test` 通过，95 tests，0 failures，2 skipped。
- 2026-05-21：`mvn test` 在沙箱外通过，216 tests，0 failures，0 errors，2 skipped；移除旧 `PlanningStateDTO.behaviorEvents` 字段后再次复跑通过；沙箱内同命令仅因本机 MySQL 连接被 sandbox 拦截失败。

## 4. P1 验收清单

P1 不阻塞 3.0.2 P0 准入，但需要确认是否纳入本版本最终发布范围。

| 项目 | 预期 | 状态 | 记录 |
| --- | --- | --- | --- |
| Agent 对话触发筛选 | 对话写入的筛选状态在前端可见、可撤销 | 待排期 |  |
| Agent 对话触发方案编辑 | 移动、删除、加入方案覆盖专业+大学和专业组模式 | 自动场景目录已补，真实 WebSocket 待验证 | 见 5.1.2、5.1.3 |
| 学校/专业简称匹配 | 简称能匹配到合理候选，不误操作相似项 | 待排期 |  |
| 筛选行为事件 | 本期不记录，保留为后续可选优化项 | 不纳入本版 |  |
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

.venv/bin/python -m pytest \
  tests/unit/models/test_conversation_phase.py \
  tests/unit/test_chat_service_history_persistence.py \
  tests/unit/test_dialog_regression_runner.py \
  tests/unit/test_instructions.py \
  tests/unit/test_intent_state_tool.py \
  tests/unit/test_plan_execution_tool.py -q
```

结果：

- 时间：2026-05-19
- 结果：通过
- 汇总：442 passed
- 2026-05-20 补充聚焦回归：346 passed

覆盖点：

- 长历史传给主 agent 前按 `HISTORY_RUNTIME_MAX_MESSAGES` 裁剪。
- 存在待确认方案动作时，runtime history 会保留产生 pending 的工具调用/工具返回/预览回复，避免非确认追问丢上下文。
- 超长 tool return 会压缩为短摘要，不继续把大 JSON 注入模型。
- SQLite 仍保留完整历史，并在本轮结束后追加新消息。
- `RequestContext.chat_history` 使用短文本历史和当前用户输入。
- 方案 pending、preview 和 apply 回归继续通过，高副作用动作仍遵循 preview -> confirm -> apply。
- 3.0.2 对话场景样例目录校验通过，覆盖查询、排序、专业组移动、学校/专业简称删除、调整后查询。
- 3.0.2 Explore/Intent 场景样例目录校验通过，覆盖专业/职业/地域/院校探索、软硬意向、意向修订、未确认意向下查询方案和候选风险解释。
- 执行层补充“学校简称 + 专业简称”删除方案志愿的歧义回归；当前 session 17 真实方案里“河南农大建筑”无法唯一定位，已作为“简称不足以唯一删除”的负例保留，同类歧义简称仍要求用户补充更完整的学校+专业全称或直接点选真实条目。

### 5.1.3 Agent 真实 WebSocket 场景样例

```bash
cd zhiyuan-agent
.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_agent_cases.json \
  --assert-plan-style \
  --response-timeout 180 \
  --clear-history

.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_explore_intent_cases.json \
  --assert-plan-style \
  --response-timeout 180 \
  --session-offset 200000

.venv/bin/python examples/dialog_regression_runner.py \
  --cases examples/dialog_regression_302_readonly_real_session_cases.json \
  --assert-plan-style \
  --response-timeout 180 \
  --clear-history
```

状态：

- 时间：2026-05-19 首轮，2026-05-20 复跑
- 结果：302 Plan 操作真实 WebSocket 回归通过；Explore/Intent 重模型效果继续作为观察项
- 样例文件：`zhiyuan-agent/examples/dialog_regression_302_agent_cases.json`、`zhiyuan-agent/examples/dialog_regression_302_explore_intent_cases.json`、`zhiyuan-agent/examples/dialog_regression_302_readonly_real_session_cases.json`

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
- `302-remove-by-school-major-abbrev / session=17` 复跑后确认：当前 session 17 的真实排序方案里并不存在“河南农大建筑”这个可唯一定位目标，后端 ordered-plan 中只有若干“建筑”相关志愿，无法把这个简称稳定解析成一个明确的真实 volunteerId。该用例应继续保留为“简称不足以唯一删除”的负例，不应当视为删除成功回归；如果需要删除，必须提供更完整的学校+专业全称或在列表里直接点选真实条目。
- `302-query-after-mutation / session=17` 通过，回复不暴露内部结构字段。
- 2026-05-20 Explore/Intent offset 回归：`session=305735` 到 `305746` 这组干净映射样本整体可跑通，首条泛方向分析与地域/院校/专业探索均能返回正常自然语言回复；原始失败点已确认属于样例前置条件问题而非链路回退：
  - `302-soft-hard-intent-mix-with-plan-impact / session=305737` 的“确认”是在偏好已经生效后的重复确认，当前应返回 no-pending guard 或无待确认动作，而不是继续要求“偏好/排除/要求”。
  - `302-school-region-explore-to-intent / session=305739` 的“天津商业大学和河北经贸大学可以重点关注”原样本过于接近生成方案动作，当前干净会话里会先返回缺少成绩信息的保护提示；已改为“先记为重点关注学校”类语义，避免把样本写成必然触发生成的请求。

复跑定位记录：

- 本机曾同时存在两个 Agent 监听 8000，其中旧进程绑定 `127.0.0.1:8000`，导致首轮 WebSocket 验证一度命中旧代码；已停止旧进程并按当前工作区重新启动 Agent。
- 当前代码日志确认 runtime history 生效：`session=16 full_len=352 runtime_len=24 full_chars=264677 runtime_chars=15001 dropped_tool_returns=2`。
- 重新复跑 `session=16 / 把第3个专业组移到第5位` 时，硅基流动连续返回 `503 System is too busy now`，因此真实业务效果暂不能继续判断。
- compat WebSocket 异常响应已修复为带 `end=true`；同一请求现在约 7s 返回 `{"type":"error","end":true}`，不再表现为 runner 等待 180s 超时。
- 302 Explore/Intent 固定 session 已确认存在历史状态污染风险；后续真实回归优先使用 `--session-offset` 映射到干净数字会话，输出中的 `base=<原始 sessionId>` 用于对照原 case。
- 2026-05-20 offset smoke：使用 `--session-offset 300000` 后，runner 输出 `session=305735 base=5735`，证明映射生效；但首条专业比较和职业比较均触发 180s 服务端超时兜底，说明当前硅基模型链路仍会阻塞整组回归。
- 2026-05-20 pending confirm smoke：`session=305736` 在 preview 后留下 `career_intents` pending，发送“确认”约 15s 返回“已经按你的确认记下来了”，随后 `planEditCache` 查询为空，确认 `conversation_phase.pending -> update_volunteer_intent_state(confirm)` 链路可消费并清空 pending。
- 2026-05-20 302 复跑补充：`session=17 / 把河南农大建筑去掉` 说明当前 ordered-plan 中不存在可唯一定位的真实目标；后续“确认”无论命中 no-pending guard，还是进入 apply 后返回“没有定位到真实编号”，都不应刷新 ordered 工作台。该 case 已改为负例保留。
- 2026-05-20 验证口径调整：`--session-offset` 只隔离 Agent 聊天历史，不会复制原 session 的成绩、候选池和排序方案。方案查询、排序、移动、删除等依赖真实方案数据的样例应使用原 `16/17` 并通过 runner 清理本地 Agent 历史；Explore/Intent 的纯确认边界和模型效果观察再使用 offset。
- 2026-05-20 Plan 操作按新口径复跑通过：命令增加 `--clear-history`，先清理 Agent 本地 SQLite 历史，再使用真实 `session=16/17` 后端方案数据。结果：
  - `302-status-major-readable / session=17` 通过，约 56s，回复包含 94/96、冲稳保和风险摘要。
  - `302-sort-school-rank-major / session=17` 通过，预览约 34s，确认约 2.4s，确认后发送 `ordered refresh=true`。
  - `302-move-unit-major-group / session=16` 通过，预览约 63s，确认约 5.5s，专业组整体移动后发送 `ordered refresh=true`。
  - `302-remove-by-school-major-abbrev-negative / session=17` 通过，预览仍会按用户原话提示待确认，但确认 apply 重新解析真实 ID 后返回“没有定位到真实编号”，`followupMessages=0`，不刷新工作台。
  - `302-query-after-mutation / session=17` 通过，说明未执行删除、方案数量不变，且不暴露内部结构字段。
- 2026-05-20 Explore/Intent 只读 smoke：使用 `session=17 --clear-history` 验证真实方案数据下的只读解释链路。
  - “当前方案对体制内稳定就业方向承接得怎么样”通过，约 104s，能读取真实方案、考生分数和候选信息，未发送工作台卡片。
  - “如果分数刚好压线，可选机会少是什么原因”通过，约 41s，能结合山东 450 分、物史地、当前冲稳保结构解释原因，未发送工作台卡片。
  - 结论：只读 Explore/Intent 能在真实方案数据上工作，但泛方向分析仍有明显大模型耗时，作为后续性能优化观察项，不阻塞本次 Plan/pending 收口。

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
| 创建新会话 | 专业+大学和专业组模式均能生成方案 | 前端人工通过 | 2026-05-20 人工验收 |
| 外部初始化接口 | 旧路径和 `v1` 路径均可用 | 后端测试通过；页面人工通过 | 带学员姓名链路已验收；继续保留授权接口 smoke |
| 专业组内专业顺序 | 已选专业按录取率正排，页面和导出一致 | 自动测试已通过；前端人工通过 | 见 5.1.1；2026-05-20 人工验收 |
| 专业+大学导出结构 | 一条志愿一行，不按学校聚合 | 自动测试已通过；文件人工通过 | 见 5.1.1；2026-05-20 人工验收 |
| 创建成功跳转 | 新建会话完成后进入 `/sessionDetailV2`，不打开会话列表/抽屉 | 前端人工通过 | `/customerDetail` 与嵌入式抽屉均已人工验收 |
| 专业意向确认气泡 | 不出现 `[object Object]`、`false`，展示意向/排除/中外合作/学费可读摘要 | 前端人工通过 | 2026-05-20 人工验收 |
| Agent 长历史治理 | 降低主 agent 完整历史输入，避免旧 preview/tool return 污染当前轮 | 首轮实现已完成，需继续场景验证 | 见 5.1.2 |
| 文档与 changelog | 3.0.2 文档和前后端 changelog 已更新 | 已完成 |  |
| tag / 构建包 | P0 验收通过后再打 `prod-3.0.2` | 未开始 |  |

补充验证：

- 2026-05-22：`mvn clean -Dtest=ChatSessionBizServiceTest,IntegrationSessionServiceTest,IntegrationSessionControllerTest,PlanningStateServiceTest#shouldFallbackToCautiousStrategyWhenStrategyTypeMissing,PlanningStateServiceTest#shouldFallbackToDefaultPlanCountWhenNeedCountMissing,PlanningStateServiceTest#shouldPreferStoredStrategyTypeWhenBuildingRequiredTierCounts test` 通过，23 tests，0 failures。
- 2026-05-22：`mvn -Dtest=PlanningStateServiceTest,PlanningBehaviorEventSharedServiceTest test` 通过，97 tests，0 failures，2 skipped。
- 2026-05-22：`./.venv/bin/python -m pytest tests/unit/models/test_conversation_phase.py tests/unit/test_chat_service_history_persistence.py tests/unit/test_plan_execution_tool.py -q` 通过，227 passed。

## 7. 问题记录

| 时间 | 问题 | 影响 | 状态 | 处理 |
| --- | --- | --- | --- | --- |
| 2026-05-18 | 最终创建请求缺少 `batch` 时返回“系统错误” | 阻塞新建会话 | 已修复，前端人工复验通过 | 前端最终提交前补齐批次，后端保存前校验核心字段 |
| 2026-05-19 | 个人信息采集缓存恢复误把空派生字段当成已确认，导致选科默认值被空数组覆盖，并提前展示“确认提交”反馈 | 影响新建会话选科成绩子步骤 | 已修复，前端人工复验通过 | 只在存在真实个人信息缓存时恢复确认态；无真实缓存时保留表单默认选科 |
| 2026-05-19 | 批次线加载后会被后续表单初始化用空 `defaultValue` 覆盖 | 影响新建会话默认批次线展示和后续创建 payload | 已修复，前端人工复验通过 | 表单初始化值改为优先使用已缓存批次、当前有效批次或批次线列表第一项 |
| 2026-05-19 | 断点续填恢复和异步批次线加载没有重放总分/排名派生计算 | 影响总分、成绩排名自动填充 | 已修复，前端人工复验通过 | 初始化、批次线加载和用户输入统一走分数派生刷新；3+1+2 选科提交兼容拆分字段 |
| 2026-05-19 | 生产 `2268` 院校专业组模式中，方案内专业组的已选专业没有按老版本录取率正排口径展示 | 影响专业组内风险可读性和用户信任 | 已修复，前端人工复验通过 | 选择策略不变，展示/草稿/排序区/导出统一按专业录取率正排 |
| 2026-05-19 | 生产 `2268` 专业+大学模式导出出现类似专业组的嵌套专业结构 | 影响导出文件志愿边界和用户理解 | 已修复，导出文件人工复验通过 | 专业模式导出改为一条排序志愿一行，专业组模式保持原结构 |
| 2026-05-19 | Agent 真实 WebSocket 复跑时硅基流动返回 `503 System is too busy now`，compat 异常响应缺少 `end=true`，测试端表现为等待到超时 | 影响模型接口异常时的前端收口和自动验证判定 | 已修复，待复验 | compat WebSocket 异常响应补 `end=true`；真实效果仍需在模型服务可用时复跑 |
| 2026-05-19 | 创建会话成功后误进入会话列表或移动端抽屉 | 用户无法直接看到刚生成的方案 | 已修复，前端人工复验通过 | 创建成功统一跳转新会话详情；个人信息补全回列表作为独立入口保留 |
| 2026-05-19 | 专业意向采集确认气泡出现 `[object Object]`、`false` | 影响采集流程可理解性 | 已修复，前端人工复验通过 | 专业意向确认气泡改为字段级格式化摘要 |
| 2026-05-19 | 本地新建 `121` 被反馈专业组内专业应按老版本正排口径展示 | 需确认是默认方案排序口径还是前端展示问题 | 已修复，前端人工复验通过 | 后端组内 `orderedPlanState.units.majorItems` 改为录取率正排 |
