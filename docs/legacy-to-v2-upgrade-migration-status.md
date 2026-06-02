# 老版本到 V2 升级迁移实施状态

本文档记录老版本到 `sessionDetailV2` 平滑升级迁移的当前实施状态、已验证范围和剩余遗留事项。完整方案见 `docs/legacy-to-v2-upgrade-migration-plan.md`。

更新时间：2026-05-09

## 1. 当前结论

迁移主链路已经具备进入真实样本验证和小流量灰度前检查的基础：

- 后端已支持 `planningState` 缺失时从老方案懒迁移。
- 前端已支持 `/sessionDetailV2` 主工作台和 `/sessionDetailLegacy` 灰度兜底页。
- 已补充迁移日志分析脚本和单会话 `planningState` 重置脚本。
- 已有单测覆盖提交方案、临时方案、无优报标记补选、`planEditCache` 提示和已跟踪老完整数据样本。

当前不建议直接全量切换。下一步应先用生产导出的真实老方案样本做迁移验证，再在环境中按会话逐步灰度。

## 2. 已完成事项

### 2.1 后端迁移能力

- `PlanningStateService` 在读取 V2 状态时，若缺少 `planningState`，会尝试导入老方案。
- 老方案读取顺序为已提交方案优先，失败后回退临时方案。
- 导入成功后写入 `assistant_chat_session_extra_data(data_key=planningState, data_version=0)`，后续访问直接读 V2 状态。
- 已提交老方案导入后标记 `orderedPlanState.generationMode=legacy_submitted`，并对排序项设置锁定/固定语义。
- 临时老方案导入后标记 `orderedPlanState.generationMode=legacy_import`。
- 老版完整数据格式 `detailList/majorVOList` 已转换到 V2 可消费的推荐结构。
- `planEditCache` 不自动合并进最终方案，仅写入 `legacy_plan_edit_cache_pending` 操作日志提示。

### 2.2 工具与观测

- 新增 `zhiyuan-server/scripts/analyze_legacy_migration_logs.py`，用于汇总迁移日志中的成功、失败、跳过、来源和导入规模。
- 新增 `zhiyuan-server/scripts/reset_planning_state.py`，用于单会话 dry-run 或删除 V2 `planningState`，便于修复后重新触发懒迁移。

### 2.3 前端兜底与移动端

- 新增 `/sessionDetailLegacy`，迁移期可只读回看老版志愿方案。
- `/sessionDetailLegacy` 复用老版志愿表展示和旧推荐/导出接口，不写入 `planningState`。
- `/sessionDetailV2` 移动端默认保留对话主视图，通过底部 `志愿方案 / 会话列表` 打开新工作区和会话列表抽屉。
- `/sessionDetailLegacy` 移动端保留 `志愿方案 / 会话列表` 快捷入口，去掉老版 `用户信息` 入口。
- V2 工作区移动端已完成候选专业卡片化、方案组头部错位修复和底部快捷入口收敛。
- V2 工作区已识别 `orderedPlanState.generationMode=legacy_submitted` 并展示“历史已提交方案，建议只读查看”提示，降低用户误编辑历史提交方案的风险。

## 3. 已验证事项

本地已运行迁移相关单测：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldImportSubmittedLegacyPlanWhenPlanningStateMissing,PlanningStateServiceTest#shouldFallbackToTempLegacyPlanWhenSubmittedPlanUnavailable,PlanningStateServiceTest#shouldSelectLegacyPlanByTierTargetsWhenPreferredFlagMissing,PlanningStateServiceTest#shouldPreservePlanEditCacheAsPendingNotice,PlanningStateServiceTest#shouldImportTrackedLegacyCompleteDataFiles test
```

验证覆盖：

- 缺少 `planningState` 时导入已提交老方案。
- 已提交方案缺失时回退临时推荐方案。
- 老数据缺少 `is_preferred` 时按冲稳保目标数量补选。
- 无后缀原始全量数据不再按已提交方案导入；`selectSchool/selectZy` 不再映射为 V2 优选。
- 存在 `planEditCache` 时只提示，不改写正式方案。
- 已跟踪的 26、29、35 三份老完整数据样本可迁移。

前端已验证：

```bash
cd zhiyuan-web
npm run build:dev
```

构建通过。当前仅存在既有 `customerDetail/style.module.scss` autoprefixer warning。

生产外部样本已验证：

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldImportExternalLegacyCompleteDataSamples \
  -Dlegacy.sample.dir=/tmp/zhiyuan-migration-samples-run/zhiyuan-migration-samples test
```

验证结果：

- `Tests run: 1, Failures: 0, Errors: 0, Skipped: 0`
- 样本目录共 20 个 JSON 文件。
- 覆盖 9 个会话：`400 / 953 / 960 / 965 / 968 / 989 / 990 / 1378 / 1496`。
- 文件类型覆盖普通方案、`_final`、`_temp`。
- 测试日志显示样本均可解析并导入为 V2 `planningState`；部分同一会话存在多个文件，按文件维度重复验证属于预期。

生产外部样本离线对账已验证：

```bash
python3 zhiyuan-server/scripts/analyze_legacy_plan_samples.py /tmp/zhiyuan-migration-samples
```

验证结果：

- 共扫描 20 个 JSON 文件，覆盖 9 个会话：`400 / 953 / 960 / 965 / 968 / 989 / 990 / 1378 / 1496`。
- `files_ok=20`，`files_failed=0`。
- 汇总识别学校/专业组记录 `23309` 条，候选/专业记录 `58896` 条。
- 未发现学校 ID、学校名称、计划学校 ID、专业身份字段缺失。
- 部分 `_final`、`_temp` 文件缺少显式优选标记，合计 `missing_pref_flag=9663`；这与老数据格式差异一致，需要继续依赖迁移逻辑中的冲/稳/保目标数量补选策略。
- `1378`、`1496` 的 `_final/_temp` 样本为小体积空方案，解析结果为空且无异常，可作为空方案边界样本。

说明：该离线对账只读取复制到 `/tmp/zhiyuan-migration-samples` 的 JSON 样本，不访问线上接口、不连接数据库、不写入 `planningState`，不会影响线上用户。

## 4. 剩余遗留事项

## 4.1 2026-05-09 回归补充记录

本轮针对 planning 补偿/替换建议修复后的影响范围补充了后端、agent 和 examples 回归。

后端：

```bash
cd zhiyuan-server
mvn -q -Dtest='!InitialPlanEvaluationP0ReportTest' test
```

结果：通过。排除项 `InitialPlanEvaluationP0ReportTest` 依赖本地 MySQL `127.0.0.1:3306/sales_bot`，当前本地环境不可连接，属于环境型 P0 报告测试，不是业务断言失败。

agent planning regression：

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest tests/regression -q
```

结果：`706 passed`。覆盖 LLM 规划 `action_family`、`preview_compensation` 满额转 `analyze_adjustment`、预览/确认保护、query/apply 结果判定等核心路径。结论：本次后端修复没有改 planning 接口结构，不会破坏 agent 调用 planning 能力；影响集中在返回内容更合理，例如满额时不再继续给新增补齐动作，分析结果中可出现更完整的替换建议。

examples websocket 回归：

```bash
cd zhiyuan-agent
INTERNAL_SERVICE_URL=https://zhiyuan.ytell.cn .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
.venv/bin/python examples/dialog_regression_runner.py --cases examples/dialog_regression_plan_cases.json --assert-plan-style --open-timeout 5 --response-timeout 90
```

结果：通过，未触发 plan style 违规。远端样本 `sessionId=35/26` 当前均为 `profile_ready` 且没有正式方案，因此本次 examples 覆盖的是“有用户信息但无方案”的降级回复与 thinking 文案可读性，尚未覆盖“已有方案 -> 审查/调整/补齐/替换”的真实端到端链路。

补充观察：

- `tests/unit/test_plan_execution_tool.py` 仍有一批旧单测直接 patch `plan_execution_tool`，但执行逻辑已拆到 `app.handlers.*`。这属于 agent 测试基线漂移，后续需要按 handler 拆分后的结构更新 patch 点和断言。
- 远端 examples 中包含大量“确认 / 生成 / 替换 / 移动 / 锁定”等可能写生产数据的场景，本轮未直接全量执行。
- 下一步真实端到端建议准备专用测试会话或预发环境，覆盖已有方案下的 `review_plan`、`analyze_adjustment`、`preview_compensation`、替换预览和确认执行。

### P0：上线前必须完成

1. 对真实会话做 V2 与老页面结果对比。

   外部 JSON 样本迁移测试已经通过，但仍需要用浏览器/接口对同一个 `chatSessionId` 做老页面与 V2 页面人工对照。

   注意：当前线上尚未部署新版本，离线 JSON 对账不会影响线上；但一旦通过 V2 后端页面或 API 读取真实会话，缺少 `planningState` 的会话可能触发懒迁移写入。因此页面/API 对账必须在新版本服务部署后，按指定会话、小范围、低峰期执行，并保留单会话回滚脚本。

   2026-05-10 已用生产旁路 `8093` 对 `chatSessionId=2045`、`1747` 做最新逻辑验证。当前确认无后缀 `session_volunteer_{id}.json` 是建会话阶段保存的高途原始全量数据，不是 assistant 后端提交后的最终推荐结果；其中 `selectSchool/selectZy` 也不是 V2 优选口径。当前读取顺序为 `_final.json` -> `_temp.json` -> 无后缀 `.json` 兜底；只有 `_final.json` 会导入为 `legacy_submitted` 并 locked/pinned，`_temp.json` 导入为 `legacy_import`，无后缀原始数据只用于最后兜底参考。`2045` 无 `_final`，命中 `_temp` 后生成 ordered `冲=28 / 稳=28 / 保=40`；`1747` 命中 `_final` 后生成 ordered `冲=28 / 稳=28 / 保=40` 且全部 locked/pinned。

   必查口径：

   - 老页面优报总数 = V2 ordered 总数。
   - 老页面冲/稳/保优报数 = V2 ordered 冲/稳/保数。
   - 老页面候补项保留在 V2 candidate 中。
   - 已提交方案顺序保持一致。
   - 导出 Excel 主要字段一致。

2. 持续补充生产样本覆盖。

   ```bash
   cd zhiyuan-server
   mvn -q -Dtest=PlanningStateServiceTest#shouldImportExternalLegacyCompleteDataSamples,PlanningStateServiceTest#shouldPreferFinalOverTempAndOriginalForExternalLegacySessionSamples \
     -Dlegacy.sample.dir=/tmp/zhiyuan-migration-samples test
   ```

   2026-05-10 追加按同一会话三件套验证：从生产机 `/apps/volunnter-tmpdata` 下载 `612/1012/617/739` 四组样本，每组均包含无后缀、`_temp.json`、`_final.json`。其中 `612/1012` 覆盖专业+大学模式，`617/739` 覆盖院校专业组模式；测试确认存在三类文件时优先采用 `_final.json` 导入为 `legacy_submitted`，不会继续读取 `_temp.json` 或无后缀原始文件。

   当前已验证一批生产样本。后续建议继续补空方案、大文件、字段缺失、专业组为空、`selectZy/is_preferred` 缺失等边界样本。

3. 在环境中验证单会话回滚。

   ```bash
   cd zhiyuan-server
   python3 scripts/reset_planning_state.py --session-id 1002
   python3 scripts/reset_planning_state.py --session-id 1002 --execute
   ```

   删除后重新进入 V2 应能重新触发懒迁移；回旧页仍能查看老方案。2026-05-10 已用生产旁路对 `chatSessionId=358` 完成演练：备份并删除 `planningState id=8565` 后，经 `8093` 重新访问生成 `id=8568`，结果仍为 `_final` 来源的 `legacy_submitted`，ordered `冲=19 / 稳=14 / 保=15` 且全部 locked/pinned。

### P1：灰度阶段必须观察

1. 汇总迁移日志。

   ```bash
   cd zhiyuan-server
   python3 scripts/analyze_legacy_migration_logs.py /path/to/server.log
   ```

   重点看：

   - 迁移失败率。
   - `submitted/temp/regenerated/none` 来源分布。
   - 候选数、优报数、排序数异常值。
   - `top_unavailable_reasons`。

2. 监控接口性能和响应体大小。

   - `workspace-state`
   - `candidate-pool/query`
   - `ordered-plan/move`
   - `ordered-plan/export`
   - 老 `volunteer/recommend-list`

3. 按会话类型做人工验收。

   - 已提交老方案。
   - 已生成未提交方案。
   - 有 `planEditCache` 的会话。
   - 专业优先模式。
   - 院校专业组模式。
   - 超大方案 JSON。

### P2：后续优化

1. 评估是否对活跃历史会话做离线预迁移。
2. 拆分大体积 `planningState` 存储，避免长期单 JSON 过大。
3. 灰度稳定 1-2 周后，再评估隐藏 legacy 入口。
4. 旧 `/volunteer/*` 接口继续保留一段时间，不建议随 V2 切换立即删除。

## 5. 建议下一步执行顺序

1. 选 20 个以上真实 `chatSessionId` 做老页面和 V2 页面人工对照。
2. 补充空方案、大文件、字段缺失、专业组为空等边界样本。
3. 在测试环境执行单会话重置和重新懒迁移验证。
4. 修复人工对照或边界样本中暴露的解析、展示问题。
5. 小流量灰度，并使用日志脚本每日汇总迁移结果。

## 6. 当前不建议做的事

- 不建议全量批量重算历史方案。
- 不建议上线时删除老方案 JSON。
- 不建议立即下线老 `/volunteer/*` 接口。
- 不建议把 `planEditCache` 自动应用到当前最终方案。
- 不建议未完成人工页面对照和灰度观察前把所有会话默认切到 V2。

## 7. 2026-06-01 生产发现：历史专业组方案迁移后组内专业丢失

### 7.1 问题现象

生产会话 `chatSessionId=941` 从老版本历史方案懒迁移到 V2 工作台后，院校专业组在前端排序区每组只展示 1 个专业。页面本身可以正常加载，问题集中在专业组内专业明细不完整。

已确认的只读证据：

- 当前接口 `workspace-state?chatSessionId=941` 返回 `200`，`volunteerModel=majorGroup`。
- 当前 V2 状态：`orderedPlanState.units=40`，`orderedPlanState.items=40`。
- 当前 V2 状态中每个 `orderedPlanState.units[].majorItems` 都只有 1 个专业。
- 老方案文件 `/apps/volunnter-tmpdata/session_volunteer_941_temp.json` 中，同一个专业组原本包含多个 `majors`：
  - `山东政法学院(03组)` / `planSchoolDataId=53020261003178` 有 2 个专业：`计算机科学与技术(校本部)`、`网络空间安全(校本部)`。
  - `sprints` 中多专业组 `356` 个，`safes` 中多专业组 `96` 个，`protects` 中多专业组 `350` 个。
- 因此老 JSON 原始数据并未丢失；丢失发生在老 JSON 转 V2 `planningState` 的兼容迁移阶段。

### 7.2 当前判断

该问题不是前端单独展示问题。前端专业组模式优先读取：

```text
orderedPlanState.units[].majorItems
```

当前后端返回的 `majorItems` 已经只剩 1 个专业，前端只能展示 1 个。

该问题也不是老方案 JSON 损坏。`session_volunteer_941_temp.json` 中同组多专业仍完整存在。

当前根因判断为：历史方案兼容迁移逻辑对院校专业组内多个专业的身份建模不完整，导致同组多个专业在迁移选择和去重阶段被压缩成一个专业。

关键链路：

```text
buildPlanningStateFromLegacyPlan
  -> buildLegacyCandidatePoolState
  -> flattenCandidates
  -> selectLegacyPreferredCandidates
  -> buildLegacyDraftPlanState
  -> buildLegacyOrderedPlanState
  -> buildOrderedUnitsFromOrderedItems
```

当前 `flattenCandidates` 中专业组下专业的 `volunteerId` 使用：

```java
safeId(school.getPlanSchoolDataId(), major.getPlanMajorDataId(), major.getMajorId())
```

在部分老文件结构中，专业组内多个专业无法形成稳定的专业级唯一身份，后续 `selectLegacyPreferredCandidates` 又按 `volunteerId` 去重，最终每个专业组只保留一个专业进入 `draft/ordered`。

### 7.3 影响范围

已知影响：

- 只影响老版本历史方案懒迁移到 V2 工作台的院校专业组模式会话。
- 专业+大学模式不属于同一问题。
- 新建 3.0.x 会话的专业组生成链路已有独立单测和人工验收，不应直接受该历史迁移问题影响。
- 已经错误生成并落库 `planningState` 的历史会话，仅修代码不会自动恢复，需要重建或修复该会话的 V2 状态。

需要进一步扫描确认：

1. 已落库 `planningState` 且 `volunteerModel=majorGroup` 的历史会话中，`orderedPlanState.units[].majorItems` 是否大量为 1。
2. 对应老文件中同一 `planSchoolDataId` 下 `majors` 是否大于 1。
3. 这些会话的 `planningState.create_time/update_time`，用于判断是在 3.0.1 阶段已生成，还是 3.0.2 投产后首次懒迁移生成。

### 7.4 处理方案

建议按“先修迁移逻辑，再修已迁移数据”的顺序处理。

#### 方案 A：修后端迁移逻辑

目标：老专业组下每个专业在 V2 candidate/draft/ordered 中具备专业级唯一身份，同时专业组仍以 `planSchoolDataId` 作为 unit 聚合键。

建议调整：

1. 在 `flattenCandidates` 中区分专业组模式和专业+大学模式。
2. 专业组模式下：
   - `candidate.volunteerId` 使用专业级唯一 ID，例如 `planSchoolDataId + "_" + planMajorDataId`，必要时追加 `majorId/majorUnitCode` 作为兜底。
   - `candidate.planSchoolDataId` 保持为专业组 ID。
   - `resolveInitialRecommendationUnitId(candidate)` 仍返回 `planSchoolDataId`，用于聚合成一个专业组。
3. `selectLegacyPreferredCandidates` 对专业组模式不要按专业明细数量直接等同目标志愿数；应按专业组选中目标 unit 后，将该 unit 下应展示的组内专业带入 `draftUnit.majorItems` 和 `orderedUnit.majorItems`。
4. `buildLegacyDraftPlanState/buildLegacyOrderedPlanState` 对专业组模式应保证：
   - `orderedPlanState.units` 按老优选专业组顺序排列。
   - 每个 `unit.majorItems` 保留老文件中该专业组内的多个专业。
   - `orderedPlanState.summary.total/unitTotal` 仍按专业组数量统计。
   - `orderedPlanState.items` 的语义需要明确：可以保留为组代表项，或扩展为专业明细项，但前端和导出必须一致。

#### 方案 B：补测试样本

必须新增生产样本回归，至少覆盖 `sessionId=941`：

- 输入：`session_volunteer_941_temp.json`。
- 验证：
  - 迁移后 `volunteerModel=majorGroup`。
  - `orderedPlanState.units` 数量符合老优选专业组数量。
  - 至少一个 unit 的 `majorItems.size() > 1`。
  - `planSchoolDataId=53020261003178` 的 unit 包含 `计算机科学与技术(校本部)` 和 `网络空间安全(校本部)`。
  - 组内专业按录取率升序展示。
  - 导出与页面组内专业一致。

#### 方案 C：修复已迁移会话

代码修复上线后，对已经错误落库的历史会话不能只依赖懒迁移，需要主动处理：

1. 单会话修复：
   - 先备份 `chat_session_data` 中 `chatSessionId=941, data_key=planningState` 的当前值。
   - 删除或重置该会话 `planningState`。
   - 重新访问 V2 触发懒迁移。
   - 对比老文件和新 V2 页面。
2. 批量修复：
   - 先只读扫描疑似受影响会话，不直接批量删除。
   - 生成候选清单：历史来源、专业组模式、`units.majorItems` 全部或大部分为 1、老文件存在多专业组。
   - 分批执行重建，每批后抽样人工验收。

### 7.5 风险与回滚

风险：

- 改变历史迁移结果会影响老会话 V2 工作台展示、导出和 Agent 方案编辑上下文。
- 若 `orderedPlanState.items` 从“组代表项”改为“专业明细项”，可能影响排序、删除、导出、行为事件统计，需谨慎评估。

建议优先采用低风险口径：

- `orderedPlanState.units` 作为专业组展示和导出的权威来源。
- `items` 可继续保留组代表项，避免影响现有按 unit 计数逻辑。
- 修复重点放在 `units.majorItems` 补全和 `candidatePoolState.items` 专业级身份唯一。

回滚：

- 代码回滚后，已重建的 `planningState` 可通过备份恢复。
- 对单会话修复必须先备份原 `planningState`。
- 批量修复必须保留修复前快照和执行清单。

### 7.6 当前建议下一步

1. 先实现后端迁移逻辑修复和 `941` 样本单测。
2. 在本地用 `941` 老文件验证页面、导出、Agent 上下文。
3. 上线修复版本。
4. 仅对 `941` 做单会话 `planningState` 重建验证。
5. 扫描生产疑似受影响会话，形成清单后再分批修复。


### 7.6 2026-06-01 Hotfix 修复结果

本轮已按“历史迁移结构必须和 3.0.2 新建专业组结构一致”的原则修复后端迁移逻辑。

修复结论：

- 旧版本专业组历史方案迁移后，不再只把优选专业组作为 1 条代表 item 保存。
- 专业组候选项 `volunteerId` 增加专业级兜底身份：`planSchoolDataId + planMajorDataId/majorId/majorUnitCode/majorName`。
- 对老数据中 `planMajorDataId` 为空的情况，使用 `majorId` 兜底，解决 `sessionId=941` 中 `53020261003178` 组内两个专业被压成同一 ID 的问题。
- 迁移选择仍按老版本优选专业组或冲稳保目标数选择专业组；选中专业组后，再展开该组内完整专业明细进入 `draftPlanState.items` 和 `orderedPlanState.items`。
- `orderedPlanState.units` 仍按专业组聚合，用于页面专业组展示、整组排序/移动/删除、导出和审查结构化快照。
- 因此历史迁移后的结构与新建专业组保持一致：`ordered.items = 方案内专业明细`，`ordered.units = 专业组聚合视图`。

已覆盖的一致性范围：

- 页面展示：`orderedPlanState.units[].majorItems` 保留组内多专业。
- 组内动作：`orderedPlanState.items[].volunteerId` 为专业级唯一 ID，可支持组内专业移动/删除。
- 整组动作：`unitId=planSchoolDataId` 保持稳定，可支持整组移动/删除。
- 排序：专业组排序后 `units.majorItems` 不丢失。
- 删除：删除组内单个专业后，`ordered.items` 与 `ordered.units.majorItems` 同步减少。
- 审查/调整：`analyzePlanAdjustment(target=ordered)` 能基于迁移后的结构执行。
- 导出：导出构建逻辑优先使用 `ordered.units`，迁移后的组内专业明细可被导出使用。

本地验证命令：

```bash
cd zhiyuan-server
mvn -Dtest=PlanningStateServiceTest#shouldPreserveLegacyMajorGroupMajorsForExternalSession941   -Dlegacy.sample.dir=/tmp/legacy-941 test
mvn -Dtest=PlanningStateServiceTest -Dlegacy.sample.dir=/tmp/legacy-941 test
```

验证结果：

- `shouldPreserveLegacyMajorGroupMajorsForExternalSession941` 通过。
- `PlanningStateServiceTest` 整类通过：`Tests run: 97, Failures: 0, Errors: 0, Skipped: 1`。
- 真实样本 `session_volunteer_941_temp.json` 迁移后：`candidate=6216`，`ordered.items=160`，`ordered.units=40`。
- `planSchoolDataId=53020261003178` 的组内专业恢复为 2 个：`53020261003178_574`、`53020261003178_584`。

上线后处理要求：

1. 先部署后端 hotfix。
2. 对已错误落库的 `sessionId=941` 备份并重置 `planningState`，重新触发懒迁移。
3. 验证 `workspace-state?chatSessionId=941`：`ordered.items` 应大于 `ordered.units`，且目标组内专业为 2 个。
4. 前端验证：页面能展示两个专业，组内专业动作和整组动作均可正常触发。
5. 后续再只读扫描其他已落库历史专业组会话，确认是否需要分批重建。

### 7.7 2026-06-01 生产 hotfix 启动与 941 重建验证

生产执行结果：

- 已备份原生产 jar：`/root/work/zhiyuan-server-3.0.2/zhiyuan-server.jar.bak-20260601-legacy-major-group-hotfix`。
- 已替换后端 jar：`/root/work/zhiyuan-server-3.0.2/zhiyuan-server.jar`。
- 已重启服务：`zhiyuan-server-3.0.2-prod.service`。
- 新服务进程：`PID=19956`。
- 启动时间：`2026-06-01 20:34:58 CST`。
- 本机健康检查：`http://127.0.0.1:8090/v2/api-docs` 返回 `200`，耗时约 `0.029s`。
- 启动后日志未发现新的 ERROR/Exception；旧进程退出时出现过 Druid shutdown 阶段异常，不影响新进程启动。

`sessionId=941` 单会话重建结果：

- 已删除旧缓存行：`assistant_chat_session_extra_data.data_key=planningState`，删除前 `data_value` 长度约 `15575799`。
- 重新请求 `workspace-state?chatSessionId=941` 触发新代码懒迁移，接口返回 `200`，耗时约 `2.214s`，返回体约 `626672` 字节。
- 重建后 `orderedPlanState.items=160`，`orderedPlanState.units=40`，`items` 内 `volunteerId` 唯一数为 `160`。
- 目标专业组 `unitId=53020261003178`、学校 `山东政法学院(03组)` 下已恢复 2 个专业：
  - `53020261003178_574`：`计算机科学与技术(校本部)`
  - `53020261003178_584`：`网络空间安全(校本部)`

当前结论：

- 后端 hotfix 已在生产新服务生效。
- `941` 已从旧错误缓存重建为 3.0.2 专业组统一结构。
- 前端仍需人工打开 `sessionId=941` 验证页面展示、组内专业移动/删除、整组排序/导出/审查。
- 暂不建议批量重建其他历史会话；下一步应先只读扫描疑似受影响会话，形成清单后分批处理。

