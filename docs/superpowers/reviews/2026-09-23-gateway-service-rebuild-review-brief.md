# 复核交办书：重建版 `app/gateway/service.py`（2026-09-23）

> 这份是**交办书**（给评审会话读的），不是评审结论。评审结论请另写一份，见文末"产出要求"。
> 交办方 = 本地执行会话（DeepSeek）；2026-09-23 的事故与重建由它完成。
>
> **复查提示（2026-09-23 晚）**：本交办书发出后已完成一轮复核（结论「有条件不通过」），
> 三项已在当晚报修并各补回归测试；**文件指纹随之从 `a7f406d9…` 变为 `cd873230408d61c0ee7af960fb17c9fe`**。
> 复核记录 `2026-09-23-gateway-service-rebuild-review.md`；修复与复跑记录见事故报告第十节。

## 一句话任务

独立复核：**重建版 `zhiyuan-agent/app/gateway/service.py` 是否忠实于三份任务报告所定义的行为**，
并逐条判定交办方主动交出的 5 个可疑点（第六节）。

## 背景（五行）

2026-09-23，死代码普查的一次"按文件名回滚"把 legacy `app/service.py`（387549 字节）覆盖到了
同名的 `app/gateway/service.py`（网关）上，毁掉其上三方**未提交**改动（P1b-3 Python 半、P1c-2、P2d）。
无 golden copy（取证见下）；执行方以 `/tmp/service.py.keep`（9-21 19:58 快照）为底，按**任务报告 + 无损测试**
重建了那三处。全量套件与真栈验收均已复跑通过。**注意：原文件已丢，"逐字节等于原版"无法证明**——
复核的目标是"行为与报告一致 + 无报告外的新行为"。

完整事故记录（取证、恢复方式、真栈复验、复核指南、残留不确定性）：
`docs/superpowers/reviews/2026-09-23-gateway-service-restore-incident.md`。
**复核清单与全部命令在该文档第九节**，本交办书不重复。

## 复核对象与指纹

| 项 | 值 |
|---|---|
| 文件 | `zhiyuan-agent/app/gateway/service.py` |
| md5 | `a7f406d97a49e9f73c22cbdec30db06c`（如与工作区不符，说明有人改过，先查清再评审） |
| 相对 HEAD | `git diff HEAD -- zhiyuan-agent/app/gateway/service.py` → +483/−119 |
| 重建版快照 | `/tmp/gateway-service-recovered.py`（与工作区一致） |
| 底稿 | `/tmp/service.py.keep`（9-21 19:58，52462 字节，md5 `898bcae71d80`） |

## 三处改动的规格来源（判定"有没有出处"就靠它）

| 处 | 报告 | 该看哪节 |
|---|---|---|
| P1b-3（证据以 snapshot 为准） | `tasks/P1b-3-snapshot-evidence/REPORT.md` | 第一节第 2 条（"删掉那一行"的原文理由） |
| P1c-2（四态核验接入 + 重查一次） | `tasks/P1c-2-verify-in-gateway/REPORT.md` | 第二节交付表 + 第三节两条 fail-closed 的写法 + 第七节（分流表那一行作废） |
| P2d（schema 补 3 处 enum） | `tasks/P2d-contract-schema-alignment/REPORT.md` | 第二节交付表 |

定义行为的无损测试（当时为新行为写的，未被事故波及）：
`tests/unit/test_gateway_evidence_flow.py`（8 条）、
`tests/integration/test_shadow_gateway.py::test_evidence_follows_the_snapshot_not_the_process_memory`、
`tests/unit/test_gateway_contracts.py::test_the_model_facing_schema_exposes_every_contract_enum`。

## 已完成的验证（复核是"复现"，不是"首次验证"）

- 全量（带 `CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9`）：`1 failed / 1939 passed / 35 skipped`，
  与台账 P2e 记的基线精确一致（那 1 failed = `test_dialog_quality_gate` 缺夹具，旧账）；
- 真栈 A/B（原版进程 vs 重建版，同题同答 658 分/位次 7462，核验端点 200）；
- 真栈断依赖（核验端点 500 → 整轮硬失败、18 字、无事实性回答）；
- 真栈重查：`重查一次 → 仍失效 → 整轮作废` 复现（backend 恰好 2 次 verify 调用）；
  **"重查后成功"未撞到**（概率性，单测覆盖该组合）；
- 16 案例验收回归 `16/16，0 业务失败 0 环境失败`。

## 必须逐条判定的 5 个可疑点（交办方主动交出）

1. `_recheck_turn` 的 `start_turn` 回退分支——真栈与单测覆盖的都是 `start_turn_and_collect` 路径；
2. 重查轮没传 `emit`（进度事件）——若原版传了，UI 上重查轮会多一段进度；
3. 可空 `admissionMode` 的 enum 形态（enum 列字面量、不含 `null`）是判断，不是报告规定；
4. 交办方新加的日志文案（`evidence settlement failed the turn …`）未必与原版一致；
5. `_extract_output` / `_validate_round` 是交办方抽的内部函数（原版更紧凑，行号 `:1121` → `:1180`）。

## 边界（做评审时请守）

- **不要 commit**（本项目实现方不提交；工作区是唯一副本，改动前先备份）。
- **不要删代码**、不要动死代码清单里的任何候选（那份清单已明确"不是删除授权"）。
- 本地栈在跑：agent `:18091`、Java backend `:18090`、rank `:18092`、事件存储 Redis `:16379`。
  重启 agent 用 `/tmp/restart_agent.py`（会轮转 `/tmp/agent-18091.log`）；
  **不要用 `pkill -f` 杀一次性工具**（模式会匹配到你自己的 shell，实测两次把执行峰会话杀了）。
- 一次性验收工具在 `/tmp`：`fact_turn.py`（提问）、`verify_breaker.py`（断依赖代理）、
  `flip_version.py`（翻转版本行逼出重查，`finally` 还原，注意别 kill 太早）。
- 复核**不能**解决的两件事已在交办书背景里写明（逐字节等价、结构是否与原版相同）。

## 产出要求

写完一份评审记录，建议放 `docs/superpowers/reviews/2026-09-23-gateway-service-rebuild-review.md`：
逐条给判定（`通过 / 有问题 / 无法判定`）+ **证据原文**（命令与输出，别只写结论），
并把"未验/无法验"的项单独列出。判定"有问题"的项，请给出**最小复现**。
