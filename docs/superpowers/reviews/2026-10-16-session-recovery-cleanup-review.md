# 会话恢复与逐类清理审查

日期：2026-10-16；审查基线：`4a75c56`；分支：`wip/2026-09-28-p2-write-loop-green`。

## 范围与结论

用户同意先独立提交只读预检，再审查恢复与清理边界。前批 9 个文件已提交为 `4a75c56 feat(agent): add read-only session reclaim preflight`，未推送或部署；既有前端产物及前序调查文档不在提交内。

本轮后续为直接源码审查与离线证据探针，**没有继续修改生产代码，没有启用删除或自动回收**，不声称经过独立 reviewer。

结论：只读预检可作为诊断基础，但目前不应接入驱逐。恢复查询仍有两项需要优先修复的既有 P1 问题，工作集也尚无等价恢复契约。测试通过不能被解释为这些问题已经修好。

## 已确认问题

### P1：恢复查询仍可把失败或畸形响应解释成没有绑定

位置：

- `zhiyuan-agent/app/util/internal_client.py:360`：当前绑定查询未使用严格 HTTP 成功模式；通用 GET 对非 200 仍可透传 JSON。
- `zhiyuan-agent/app/server.py:374`：生产适配只判断 code 是否属于 `(None, 0)`，随后直接取 data；缺失 code/data、code=False 和失败标记未被严格区分。
- `zhiyuan-agent/app/gateway/thread_recovery.py:108`：组合查询把非 Mapping 的 data 当作可使用本地兜底的无绑定回答。
- `zhiyuan-agent/app/gateway/thread_recovery.py:334`：恢复层同样接受缺失或布尔 code，data=None 会进入无绑定分支。

证据：临时本机 HTTP fixture 返回 **503 + code=0/data=null**，调用真实 `get_current_codex_thread_binding`、组合查询及 ThreadRecovery，最终执行 create。code=False、缺失 code、success=False/error 与畸形标量 data 也可触发本地兜底并 resume。

影响：后端异常可被误认为“原上下文不存在”，没有本地命中时错误新建并丢失模型上下文；有本地命中时可能掩盖查询故障。不能把网络异常字典全部归入这一问题：现有客户端异常返回 data={} 的路径通常会被后续解析拒绝；上述特定误判已分别复现。

建议下一批：仅在 HTTP 200、实际整型 code=0、显式 data 且无失败标记时承认有绑定/无绑定；错误或畸形响应必须报恢复不可用，不兜底、不 create、不 resume。保留“可信成功 null → 本地恢复兜底”的现有正常路径，不全局改变其他 GET 调用。

### P1：不完整身份的绑定仍可进入 resume

位置：`zhiyuan-agent/app/gateway/thread_recovery.py:195`、`zhiyuan-agent/app/gateway/thread_recovery.py:218`。

CurrentBinding 将缺失 tenant/session 收敛为空字符串，belongs_to 只在字段非空时比较。因此带 threadId 但缺失两个身份字段的对象也会被判为属于请求会话。离线探针已观察到对 unscoped-thread 调用 resume。

Java 实际 DTO 含 tenantId/chatSessionId：`zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CodexThreadBindingContextRes.java:9`。不能把“正常应有字段”当作跳过客户端校验的理由。

影响：上游字段丢失或错误返回时，恢复隔离边界 fail open。证据来自构造的错误上游响应，不代表已经证明线上存在跨租户利用。

建议与上一项同批修复：非空绑定要求可用且类型正确的 threadId、必填并匹配的 tenant/session；错配或缺失不得 resume 或 create。需要同时保留后端与本地登记表的正常完整身份恢复测试。

## 回收前置阻塞，不是本批引入的回归

### 工作集不能只靠快照等价重建

`zhiyuan-agent/app/engine/working_set.py:70` 从权威快照恢复业务字段、证据和部分规划范围，但不恢复 candidate_entities、artifact_refs、candidate_source_turn_id、last_turn_id 等跨轮投影。普通回合在 `zhiyuan-agent/app/gateway/service.py:2274` 显式继承旧工作集中的这些内容，说明它们不是可随意丢弃的重复缓存。

探针验证同一快照重建后候选列表和来源 turn 锚点消失；没有实际调用模型来断言用户一定会收到哪句错误回答。回收前需明确这些数据的恢复来源，或产品允许的显式刷新降级，不能仅以 snapshot 可重读为由删除整个 working set。

### 清理 Python thread 映射不等于释放 native 资源

`zhiyuan-agent/app/harness/codex.py:62`、`zhiyuan-agent/app/harness/codex.py:85` 封装了 create/resume，但项目尚未提供经过验证的单 thread 卸载及恢复闭环。仅 pop `_threads` 无法证明子进程资源已释放；本轮未测量真实 native RSS，也不猜测当前固定二进制支持什么卸载协议。

未来若需异步 native 释放，还必须设计回收中的准入/代际 fencing：先预检、再 await 卸载、最后发现 stamp 已变，已经太迟，不能据此保证没有卸掉新进入的活动。当前只读 candidate 本来就不提供这种授权。

### 路由与撤销语义需独立裁决

- native 关闭连接默认保留路由：`zhiyuan-agent/app/server.py:642`、`zhiyuan-agent/app/server.py:1662`。compat 关闭路径会 detach，不能把两者混为一谈。预检阻止保留路由是既定安全行为，不应为了提高命中率强制删除。
- 后端 current 同时过滤 revoked/expired：`zhiyuan-server/src/main/java/com/ytell/zhiyuan/mapper/CodexThreadBindingMapper.java:24`；本地 latest_for_session 不区分这两类原因，重新注册会清除 revokedAt。撤销究竟表示旧凭据失效还是禁止恢复，需明确契约；不在缺少产品语义时直接将重新登记称为越权，也不擅改现有授权规则。

## 逐类清理清单

下表是未来设计约束，不是删除白名单。

| 状态 | 当前来源/保留方式 | 恢复或清理约束 |
| --- | --- | --- |
| Gateway `_snapshots` | 每会话内存；权威 loader 可重读 | 相对可重建，但读失败须保持明确错误/既定退化语义；不是 pending absent 的证据 |
| Gateway `_working_sets` | 每会话内存；含跨轮候选、工件与锚点 | 尚未等价恢复，暂不可随 session 一起删除 |
| Gateway `_threads` | 每会话映射；后端 current + 本地 registry 恢复 | 先修严格查询与身份校验；保留最近恢复锚点，不把丢历史的新建当作正常回收 |
| Gateway `_session_locks` | 每会话 asyncio.Lock | 引用归零及无等待者后才有设计讨论空间；不得使等待者继续用旧锁、新请求用新锁 |
| Gateway `_user_turn_seq` | 每会话用户回合水位 | 与续接让路/旧请求语义绑定；不能无恢复或代际方案地 reset 成 0 |
| Gateway `_turn_cache` | 已有 max=1024、TTL=3600s | 维护既有 turnId/内容冲突与结果重放窗口；不能借 session 回收提前缩短 |
| Gateway `_continued_actions` | 全局有界台账，上限 2048 | 不是普通会话缓存；不得以字符串前缀顺手删除并重新放行重复续接 |
| Runtime `_active/_tasks/_pending_requests/_detached` | 对应真实任务，已有收尾释放 | 不主动取消/删除来制造空闲；依靠真实生命周期收尾 |
| Runtime `_admission_gates` | 最后一个使用者离开即移除 | 已有释放规则，不再叠加 TTL 或替换活动 gate |
| Runtime `_channels` | 最新投递路由，native 关闭后可保留 | owner=0 不代表 route 可删；先解决 replay/终态投递/重连恢复契约 |
| Lifecycle `_entries` | 唯一 entry generation/revision/idle | 最后阶段才考虑清理；必须与其它状态一致，不能让旧 lease/ticket 影响新代际 |
| Server `binding_handles` | `server.py:272` 的闭包字典，按 thread 缓存 handle/expiry | 仍未有容量/过期删除；新清理接口必须纳入此隐藏保留点，且不能记录明文凭据 |
| Broker pending/RPC/answered | 活跃请求有 deadline；回答收据已有 max=1024、TTL=600s | 已结算与活跃资源分别处理；不能删除待回答 native/MCP 请求或缩短回答幂等窗口 |
| Redis stream/epoch/请求摘要和结果 | 已有 TTL/max-events | 不是 worker 本地缓存；禁止随本地清理删共享键，保护游标与跨进程请求去重 |
| 本地 ThreadBindingRegistry | SQLite 持久恢复键，latest 不按授权 TTL 过滤 | 不按 expires_at 直接删最后恢复键；旧历史保留策略另议，避免重启后失忆 |
| SqliteArtifactStore | 持久工件签发台账，已有过期失效与分批清理 | 不随会话删除来破坏工件核验；可能与 registry 共用文件，严禁删除整个 SQLite 文件 |

清单依据主要见 `zhiyuan-agent/app/gateway/service.py:1225`、`zhiyuan-agent/app/gateway/session_runtime.py:270`、`zhiyuan-agent/app/server.py:272`、`zhiyuan-agent/app/gateway/event_store.py:95`、`zhiyuan-agent/app/mcp_server/context.py:89`。

## 证据与验证

- 提交前离线全量：**2865 passed、21 skipped、33 deselected、23 warnings，65.24 秒，退出码 0**；日志 `/tmp/zhiyuan-session-reclaim-precommit.log`。
- 恢复路径离线审查：**74 passed、1 skipped，0.89 秒，退出码 0**；其中 8 项是审查探针，包含 7 项现状/问题证据和 1 项显式业务失败正确阻止的对照，其余 66 项为既有回归。skip 为缺少专用 Redis。
- 探针通过代表成功复现当前行为，**不代表缺陷已修复**。探针文件 `/tmp/test_zhiyuan_session_recovery_review.py`，结果日志 `/tmp/zhiyuan-session-recovery-review.log`。
- 仅 fixture-owned loopback HTTP、临时 SQLite 和 fake native 子进程；没有访问共享 Redis/数据库、现有业务服务或真实模型。Java 仅做源码审查，没有执行真实撤销/重新登记实验。

审查命令从 `zhiyuan-agent` 执行：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  /tmp/zhiyuan_hardening_pytest.py \
  /tmp/test_zhiyuan_session_recovery_review.py \
  tests/unit/test_thread_recovery.py \
  tests/integration/test_gateway_thread_recovery.py \
  tests/unit/test_gateway_turn_cache_bounds.py \
  tests/unit/test_working_set.py -q -rs
```

## 建议推进顺序

1. 独立小批修复绑定恢复的严格传输、失败/无记录区分及完整身份校验，先写失败测试，再保留正常 local fallback/resume 回归。
2. 明确工作集的可恢复数据、必须保留锚点和显式降级；补回收后重连、上一批候选指代、确认/重复请求/续接的恢复验收。
3. 单独评审 native 保留路由、撤销与卸载语义，再设计原子清理与准入 fencing。跨 worker 的空闲判定与协调仍不在当前单 worker registry 能力内。
4. 最后才讨论容量阈值、TTL/LRU、扫描和启用策略；目前不要接入自动驱逐。

本审查文档先留工作区，不与已完成的前批提交混在一起。
