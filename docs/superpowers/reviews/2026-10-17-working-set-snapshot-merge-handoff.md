# 工作集快照合并修复交接

日期：2026-10-17；基线：`2122cef`；分支：`wip/2026-09-28-p2-write-loop-green`。

## 已批准范围

落实前轮工作集审查中的两处合并修复，限制在现有 Python Gateway 内。不修改快照接口、Java 服务、持久化格式、native thread 恢复或授权校验；不启用清理、TTL/LRU、路由卸载或扫描。

前轮审查记录为 `docs/superpowers/reviews/2026-10-16-working-set-recovery-contract-review.md`，仍作为独立调查产物留在工作区，不将其误当成本批实现文件。

## 改动

- 每轮工作集仍先由成功读取的快照构造。快照 `admissionFacts` 非空时保留该列表，不再被旧工作集整个覆盖；这是列表替换，不是把旧事实拼到新事实后面。
- 快照 `admissionFacts` 为空时暂保留旧事实回填行为，兼容当前 Java 尚未填充该字段的现状。这不是对旧事实有效性的背书，也不解决缺失/权威空集的区分。
- 删除从旧工作集回填 `activeProposal` 的逻辑。成功快照为空时本轮没有活跃提案；快照有新提案时继续使用新投影，执行计划据此决定确认或澄清。
- 候选跨轮保留、来源轮次、阶段/招生模式变化时失效、证据以新快照为准及工件核验保持原有规则。

唯一生产文件：`zhiyuan-agent/app/gateway/service.py`。新增永久回归：`zhiyuan-agent/tests/unit/test_gateway_working_set_reconciliation.py`。

## 失败优先与定向验证

新增 16 项用例通过实际 `GatewayService.handle_turn()` 连续处理两轮，外部 Codex 和消息存储使用替身，不替换被测的快照构造、工作集合并或执行骨架逻辑。断言同时检查真实生成的模型输入与回合结果，不只检查私有字典。

- 同版本、相邻版本及跳版本：旧工作集为空或含旧事实，都不能覆盖非空新事实；新事实列表中也不能夹带旧列表独有项。
- 同样三种版本关系：快照提案为 null，不把旧提案带回模型输入。
- 提案消失且当前缺少成绩信息时，实际执行骨架应为 clarification，而非旧提案触发的 confirmation。
- 新快照有活跃提案时仍进入 confirmation，保留新的引用和来源版本。
- 快照事实字段缺失或显式空列表时保留兼容行为。
- 刷新事实不丢失候选及其来源轮次；阶段或招生模式变化仍清除旧候选。

红灯：**10 failed、6 passed，0.47 秒，退出码 1**，日志 `/tmp/zhiyuan-working-set-merge-red.log`。失败均为预期的事实列表不符、旧提案残留或确认骨架错误，不是导入/环境错误。6 项通过是原有兼容行为的对照。

最小修复后，新增及相邻工作集/执行骨架/快照/模型上下文回归：**48 passed，4.45 秒，退出码 0**，日志 `/tmp/zhiyuan-working-set-merge-green.log`。

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
tests/unit/test_gateway_working_set_reconciliation.py \
tests/unit/test_working_set.py \
tests/unit/test_execution_plan.py \
tests/unit/test_snapshot_projection.py \
tests/unit/test_gateway_internal_state_tags.py -q -rs
```

命令均在 `zhiyuan-agent` 目录执行。

## 完整回归与复核

- [x] 生产差异直接复核：仅对非空新事实优先及提案不回填做最小改动，无新依赖或第二份业务状态。
- [x] 先观察永久回归的预期失败，再修改生产逻辑。
- [x] 新增及相邻定向回归通过。
- [x] 完整 unit/integration 离线回归：2987 passed、21 skipped、33 deselected、23 warnings，65.49 秒，退出码 0。
- [x] 独立提交前重新执行完整离线回归：2987 passed、21 skipped、33 deselected、23 warnings，65.69 秒，退出码 0；日志 `/tmp/zhiyuan-working-set-merge-precommit.log`。
- [x] 已跟踪差异及本批新增测试/交接文档的空白检查无输出；仅有一个 Python 生产文件发生改动。

完整回归首次在沙箱内被测试 HTTP server 的 socket 创建权限阻断：160 passed、1 setup error；不是业务断言失败。随后通过权限审批重跑同一隔离命令，仍仅允许连接当次测试创建的 loopback listener，不访问现有业务服务、共享 Redis/数据库或真实模型。

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
timeout --signal=TERM --kill-after=10s 300s \
.venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
tests/unit tests/integration -m 'not e2e' -q -rs -x \
-o faulthandler_timeout=30
```

结果日志：`/tmp/zhiyuan-working-set-merge-full.log`。19 项因未配置专用测试 Redis 跳过，2 项因缺少固定 Codex 二进制跳过，不把跳过算成通过。23 项告警与前批数量一致，为既有 Pydantic usage 弃用及同步函数 asyncio 标记告警，未在本批调整。

本轮是直接源码复核，不是独立 reviewer 审查。未发现本批范围内新增的阻断问题，不据此承诺下述恢复契约已经完备。

## 仍未解决的契约问题

1. Java 快照的空 `admissionFacts` 目前无法区分“未提供”和“权威空集”；历史事实的来源、范围、版本和失效仍需单独设计。
2. Gateway 重建或切换 worker 后，候选及来源轮次尚无完整应用层恢复源。threadId 恢复不等于工作集恢复；本批没有增加这项能力。
3. 工件签发台账只有摘要，不能还原候选原文；有限 UI 事件流也不能被当作必然完整的恢复日志。

建议先将本批小修独立审阅/提交，再讨论“恢复缺口时显式重查/澄清”和“增加有来源/版本约束的独立恢复投影”的取舍。不要因为这两处合并修复通过，就启用会话自动回收。

用户已确认将本批独立提交。提交范围仅为 `zhiyuan-agent/app/gateway/service.py`、新增永久回归及本交接文档三个文件；不推送或部署，不包含前端构建产物及既有未跟踪调查文档。
