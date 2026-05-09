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
   mvn -q -Dtest=PlanningStateServiceTest#shouldImportExternalLegacyCompleteDataSamples \
     -Dlegacy.sample.dir=/tmp/zhiyuan-migration-samples test
   ```

   当前已验证一批生产样本。后续建议继续补空方案、大文件、字段缺失、专业组为空、`selectZy/is_preferred` 缺失等边界样本。

3. 在环境中验证单会话回滚。

   ```bash
   cd zhiyuan-server
   python3 scripts/reset_planning_state.py --session-id 1002
   python3 scripts/reset_planning_state.py --session-id 1002 --execute
   ```

   删除后重新进入 V2 应能重新触发懒迁移；回旧页仍能查看老方案。

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
