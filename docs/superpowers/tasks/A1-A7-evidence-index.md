# A1–A7 证据索引

> 交付于 A7（2026-09-21）。用途：A 线的验收判断要能一眼看出**每条结论是哪一层的
> 证据**，而不是只看到"全绿"。
> 计划对报告的要求（`plans/2026-09-20-codex-native-interaction.md` 第九节）：
> 报告必须区分 **fixture / 真实 Java+上游 / 真实 Codex / 真实浏览器** 四层证据。

## 一、四层证据的含义

| 层 | 含义 | 说不了什么 |
|---|---|---|
| fixture | 纯 Python 单测、替身对象 | 真实协议、真实模型、真实页面 |
| 真实 Codex | 真的 `codex-cli` 二进制（替身或真实模型） | 真实 Java、真实浏览器 |
| 真实 Java + 上游 | 真的 Spring 服务、真的 MySQL/Redis、真的招生上游 | 真实浏览器 |
| 真实浏览器 | 真人在真的域名上点 | — |

**"协议层 passed"不等于"产品功能可用"**（A1 报告第九节原话）。A 线今天的位置：
前两层有真证据，第三层只有 Java/Python 各自的单测与 mock，第四层一条都没有。

## 二、逐任务

| 任务 | 状态 | 报告 | 最强的一层证据 | 到不了的那一层 |
|---|---|---|---|---|
| A1 运行时能力矩阵 | DONE_WITH_CONCERNS | `A1-runtime-capability-matrix/REPORT.md` | **真实二进制** `.runtime/codex-capabilities.json`（`codex-cli 0.155.1`；`resume: passed`，`realModel: false`） | 真实模型的原生提问 |
| A2 冻结事件与状态 | DONE_WITH_CONCERNS | `A2-event-state-freeze/REPORT.md` | Python 层 + 协议层 | 真实 Java、页面 |
| A5 事件重放/幂等 | DONE_WITH_CONCERNS | `A5-event-store/REPORT.md` | **真实 Redis**（隔离库 9），13 条含 3 种 resync 成因与水位交接 | 多进程并发、Redis 故障切换 |
| A3 流式事件与可响应 WS | DONE_WITH_CONCERNS | `A3-live-events/REPORT.md` | 真 `CodexAppServerHarness` + 替身二进制；`TestClient` 同进程 | 真实网络栈、跨进程重连 |
| A4 原生问答桥 | DONE_WITH_CONCERNS | `A4-user-input-bridge/REPORT.md` | 真实二进制 + **真实模型**（直接驱动 harness，未经 WS） | 浏览器侧卡片 |
| A6 前端接线 | PARTIAL | `A6-frontend-wiring/REPORT.md` | 纯函数层有真测试（node:test）；组件改动**只有 tsc** | 渲染、键盘可达性、浏览器 |
| A7 Thread 恢复 | DONE_WITH_CONCERNS | `A7-thread-recovery/REPORT.md` | **真实二进制两进程重启**（沿用/重建对照）；真实 Redis 的跨层用例；**真实栈五种恢复形状**（真 Java 绑定 + compat WS：四种进程死亡 + 网关自身重启，见报告四之三，复跑 `scripts/probe_codex_recovery.py`）；**整套验收前后对照**（3 遍 × 16 case，同一台机器：45/0/3 → 46/1/1 → 三处修复全上后 **48/0/0**，重拉 3 → 0 → 0，见报告四之三） | 浏览器 |

## 三、复跑命令

```bash
# Python（打真实 Redis；缺 URL 时 A5/A7 的 Redis 用例显式 skip，不记为通过）
cd zhiyuan-agent
CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9 \
  .venv/bin/python -m pytest tests/unit tests/integration -q

# A7 进程级恢复（要本地栈在跑；会杀 codex、agent-restart 还会重启 agent 进程）
.venv/bin/python scripts/probe_codex_recovery.py --shape between-turns   # mid-turn | agent-restart

# Java（全量）
cd zhiyuan-server && mvn -o test
```

## 四、A 线整体的未闭合项（按"下一环谁做"分）

| 项 | 归谁 | 依据 |
|---|---|---|
| 浏览器上的真实问答与恢复 | C4 | A6/A7 报告的证据边界 |
| resync 快照接线、请求去重接线 | A5 报告第 2 条明确"仍未接" | A5 REPORT 七-2 |
| `expire_runtime` 无生产调用点 | 设计裁决 | A7 REPORT 五-3 |
| Snapshot 注入的硬上限与退化策略 | 设计裁决 | A7 REPORT 五-1 |
| `register()` 不撤销旧绑定 | 设计裁决 | A7 REPORT 五-4 |
| MessageList（1771 行、无测试）接线是否正确 | C4 | A6 REPORT 七 |
| 快照证据的三个 Java 字段（`sourceSystem`/`paramsDigest`/`expiresAt`）Python 收不收 | 设计裁决（已临时收下，见 A7 REPORT 四之三） | 不修则任何多轮会话从第二轮起不可用 |
