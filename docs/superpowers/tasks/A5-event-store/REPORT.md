---
task: A5
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-20 23:05 +0800
source: docs/superpowers/plans/2026-09-20-codex-native-interaction.md
---

# A5 报告：事件重放、请求幂等与断线恢复

## 一、结论

事件存储独立可用、可单测；WS 接线按计划留给 A3/A6/A7。
所有原子性结论都来自**真实 Redis**，没有一条是内存 mock 得出的。

| 能力 | 接口 | 验证方式 |
|---|---|---|
| 原子追加 + 编号 | `append(key, event) -> UiEvent` | 200 并发，编号稠密唯一 |
| 按 cursor 重放 | `replay(key, epoch, after) -> list \| None` | 5 种 resync 成因各一条 |
| high-water | `watermark(key) -> int` | 切换窗口插入事件的不丢不重 |
| 请求幂等 | `admit(key, request_id, digest)` | accepted / duplicate / conflict |
| 结果关联 | `finish_request` / `request_result` | 换实例后仍在 |

## 二、发现并修复：连接池默认值是一道静默悬崖

200 并发追加的用例第一次跑就撞上：

```
redis.exceptions.MaxConnectionsError: Too many connections
```

根因不是测试写得太狠，是 redis-py 的 `from_url` 默认 `max_connections = 100`。
一个 Gateway worker 同时服务的会话数可以超过它，而池满时是**硬失败不是排队**——
结果是正在进行的回合丢事件。已把池显式定容（构造参数 `max_connections`，默认 256），
并在注释里写明"256 是起步值不是上限"。

顺带修掉一个浪费：200 个协程首次并发时都会看到脚本没装载，各发一次 `SCRIPT LOAD`。
加锁收敛成一次。

## 三、resync 的五种成因，各有一条测试

"返回 None"必须让客户端理解成"重建基线"，而不是"再等等"。所以每一种都要能被区分出来：

| 成因 | 测试 |
|---|---|
| 代际（epoch）不同 | `test_replay_requires_resync_when_generation_changed` |
| 计数/代际键丢失 | 同上路径（`stored_epoch is None` 且 cursor 非 0） |
| cursor 超前 | `test_replay_requires_resync_when_cursor_is_ahead` |
| 保留窗口已滑走（有洞） | `test_replay_requires_resync_when_window_was_trimmed` |
| 跨租户同 sessionId | `test_two_tenants_sharing_a_session_id_do_not_mix` |

最后一条单列的理由：`(tenantId, chatSessionId)` 是业务隔离边界，不是 threadId
（台账 2026-09-13 已裁决）。同 sessionId 的两个租户各有一条独立时间线，
拿 A 的代际读 B 必须被拒，而不是返回 B 的数据。

## 四、缺配置时显式 skip，不记为通过

```
$ pytest tests/integration/test_conversation_replay.py -q -rs
SKIPPED [13] CODEX_TEST_REDIS_URL is required; skipping is not a pass
```

skip 理由写在用例里，不是仓库配置里——这样它出现在任何人的输出里都是同一句话。
计划要求"缺配置显式 skip 并阻止公网 gate，不记为通过"，本节即为该约束的实现。

## 五、验收命令与原始结果

```
cd zhiyuan-agent
# 无隔离 Redis（默认）：14 条 skip
CODEX_APP_SERVER_BIN=<bin> .venv/bin/python -m pytest tests/ -q
# 2 failed, 1773 passed, 56 skipped

# 带隔离 Redis（16379 的 /9 库）
CODEX_TEST_REDIS_URL=redis://127.0.0.1:16379/9 \
  CODEX_APP_SERVER_BIN=<bin> .venv/bin/python -m pytest tests/ -q
# 2 failed, 1787 passed, 42 skipped

# 稳定性：连跑三次
CODEX_TEST_REDIS_URL=... pytest tests/integration/test_conversation_replay.py -q
# 13/14 passed ×3（第 14 条为后补的水位用例，补后 14 passed）
```

两条 failed 与台账基线逐字同名，无新增。

## 六、改动清单

| 路径 | 变更 |
|---|---|
| `app/gateway/event_store.py` | 新增 |
| `app/config.py` | 新增 `ConversationEventStoreConfig`（含 workers=1 校验） |
| `pyproject.toml` | 新增依赖 `redis>=5.0`（此前无任何异步 Redis 依赖） |
| `docker-compose.codex-local.yml` | 隔离 Redis 开 AOF（`--appendonly yes --appendfsync everysec`） |
| `tests/integration/test_conversation_replay.py` | 新增，14 条，全部打真实 Redis |

## 七、未完成 / 留给下一环

1. **AOF 改动只对新建容器生效。** 已运行的 `zhiyuan-codex-local-redis-1` 仍是旧
   启动参数；要生效需重新 create 容器。本任务**没有重启它**（现有栈可能正被使用），
   所以"重启后事件仍在"只由换客户端实例的用例证明，没有真的重启过 Redis。
2. ~~存储未接任何入口。~~ **已接（2026-09-21 补做）**：`ConnectionChannel` 在
   配置了 `CODEX_EVENT_STORE_REDIS_URL` 时**先入流拿编号再发**；未配置则退回旧信封。
   真实 Redis 上验过发送与重放的编号一致。仍未接：resync 快照、请求去重的接线。
3. **"worker 起不来时明确 terminal failure""重启遗留 running 进入 recovery"**
   只有原语（`admit`/`finish_request`/`request_result`），没有编排——属 A3。
4. **首期单 worker 是硬约束**，已写成配置校验（`workers != 1` 直接拒绝）。
   未来多实例需要租约/fencing，未实现前不把本存储描述成集群调度器。
5. `MAXLEN ~` 用的是近似裁剪，实际保留条数可能略多于 2000；
   `replay` 按 sequence 判洞，不依赖精确条数。

## 八、证据边界

真实 Redis 上验的是存储语义；**没有**验证多进程并发（单 worker 是前提）、
没有验证 Redis 故障切换、没有验证真实断线重连（需 C 线的浏览器环境）。
