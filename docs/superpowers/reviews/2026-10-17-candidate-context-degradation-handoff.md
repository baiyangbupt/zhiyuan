# 候选上下文缺失降级修复交接

日期：2026-10-17；基线：`fa50178`；分支：`wip/2026-09-28-p2-write-loop-green`。

## 批次范围

用户已批准候选恢复审查中的方案 A：修正现有工作集上下文的缺失分支，不新增候选持久化或精确批次恢复。本记录对应新的实现批次，不修改先前调查记录的历史结论。

唯一生产改动在 `zhiyuan-agent/app/engine/working_set.py` 的 `ConversationWorkingSet.as_context_text()`：

- 有候选时保留原有名称、ID 和优先解析指代的提示。
- 空候选改为描述“当前工作集未保留候选对象”，不再同时无条件要求“不要说看不到候选”。
- 明确应用工作集为空不代表线程历史从未出现候选，先从可用历史中的明确对象和可靠来源解析，禁止编造对象或 ID。
- 只有本轮请求依赖候选且仍无法解析时，才澄清缺失条件或使用已获准的只读查询；提示重查是当前条件下的新结果，不是恢复原来的同一批。
- 历史查询的缺失参数要求及结构化 JSON 投影保持不变。

未改候选合并、24 个对象的滚动上限、来源轮次、阶段/招生模式失效规则、工具准入、写确认或证据规则；未增加接口、存储、依赖或关键词意图分类器。没有新增启动/重连自动查询或自动清理，也没有删除任何恢复数据。

## 永久回归

在修改生产逻辑前，先补充 `tests/unit/test_working_set.py` 与 `tests/unit/test_gateway_working_set_reconciliation.py`：

- 空工作集不再注入互相矛盾的提示，并包含历史来源、条件澄清/只读重查和新旧批次边界。
- 空/非空两个分支均保留已确认查询范围、缺失参数要求及结构化候选来源投影。
- 两轮候选仍合并为滚动实体集合；空 `data.items` 或 `data.candidates` 仍保留已有对象及其来源轮次。
- 实际 `GatewayService.handle_turn()` 冷回合注入缺失分支；暖回合仍有候选时保留既有提示。
- 阶段或招生模式变化失效后，下一轮实际模型输入切换为缺失分支。

新增 9 个用例，并增强既有的暖回合和范围变化断言。Gateway 测试只替换外部 Codex/消息存储等依赖，实际运行工作集投影、快照协调和模型输入构造；没有通过替换被测渲染逻辑制造通过。

这些用例验证的是确定性的模型输入和状态边界，**没有调用真实模型，不能证明真实回答一定遵守提示**，也没有验证精确上一批恢复。

## 失败优先与定向验证

生产修改前：**6 failed、26 passed，0.50 秒，退出码 1**。失败均是预期的上下文断言，包括空工作集三项及 Gateway 冷回合、阶段变化、招生模式变化；不是导入或环境失败。

日志：`/tmp/zhiyuan-candidate-context-red.log`。

最小修复后：**57 passed，4.49 秒，退出码 0**。

日志：`/tmp/zhiyuan-candidate-context-green.log`。在 `zhiyuan-agent` 目录执行：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
tests/unit/test_working_set.py \
tests/unit/test_gateway_working_set_reconciliation.py \
tests/unit/test_gateway_internal_state_tags.py \
tests/unit/test_execution_plan.py \
tests/unit/test_snapshot_projection.py -q -rs
```

## 完整回归与源码复核

完整离线回归沿用网络护栏：只允许连接本次测试进程创建的 loopback listener，阻止现有业务端口和外部地址。部分 fixture 需要监听端口，按既有沙箱权限限制申请提权执行，不移除护栏。每项测试限时 20 秒，整批限时 300 秒。

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
timeout --signal=TERM --kill-after=10s 300s \
.venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
tests/unit tests/integration -m 'not e2e' -q -rs -x \
-o faulthandler_timeout=30
```

结果日志：`/tmp/zhiyuan-candidate-context-full.log`。

完整回归结果：**2996 passed、21 skipped、33 deselected、23 warnings，65.80 秒，退出码 0**，比基线增加 9 项通过。19 项因未配置专用测试 Redis 跳过，2 项因缺少固定 Codex App Server 二进制跳过，跳过不算通过。23 项告警与前批数量相同，来自既有 Pydantic usage 弃用及同步函数 asyncio 标记，未在本批修改。

用户批准版本留档后，在当前 `4e30d41` 基线上重新执行同一完整离线命令：**2996 passed、21 skipped、33 deselected、23 warnings，67.31 秒，退出码 0**。提交前日志：`/tmp/zhiyuan-candidate-context-precommit-20261017.log`。跟踪差异及新交接文档的空白检查无诊断。

本轮为直接源码复核，不是独立 reviewer 审查；未发现本批范围内新增的阻断问题。生产差异只有上下文渲染分支，不含 Java、Gateway 执行流程或前端修改。已有前端构建产物及未跟踪调查文件不属于本批。

## 验收边界与后续

1. 精确恢复上一批候选仍需单独设计批次归属、查询与数据版本、工具来源、实际展示锚点以及并发覆盖规则；滚动实体集合和单个来源轮次不能替代它。
2. 空 `admissionFacts` 的“未提供/权威空集”语义没有在本批解决；保留前一批兼容策略。
3. 保持单 Gateway worker，不因本批通过就启用自动回收或宣称跨 worker 恢复完备。
4. 接下来优先补发布验收缺口：私有对话 fixture、固定 Codex 二进制、真实模型/写入端到端，以及凭证、代理、回滚联调。本批离线测试不替代这些验收。

用户已授权将本批独立提交留档，范围仅为 `app/engine/working_set.py`、两个相邻单元测试文件和本交接文档四个文件；不包含其他未提交内容，不推送或重启服务。用户随后报告已部署；实际运行版本与后续冒烟的证据另行记录，不把离线测试当作部署验收。
