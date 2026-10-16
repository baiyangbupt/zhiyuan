# Thread-binding 恢复契约修复交接

日期：2026-10-16；基线：`4a75c56`；分支：`wip/2026-09-28-p2-write-loop-green`。

## 范围与设计

落实 `2026-10-16-session-recovery-cleanup-review.md` 中两项已获用户同意的 P1：查询异常误判为无绑定，以及缺失身份的绑定进入 resume。仅修复现有 Python 恢复链路；不修改 Java、不引入新依赖、不做会话删除或自动驱逐。

- HTTP 层：仅当前绑定查询启用已有的 `require_success=True`，非 200 不信任成功响应体；通用 GET 默认行为和 pending 严格读取保持不变。
- 生产适配层：必须收到完整业务 envelope；只接受实际整型 `code=0`、显式 `data`，且没有失败标记。HTTP 200 的 JSON null、裸绑定、缺字段、布尔/浮点 code、失败标记、标量 data 均不能证明不存在绑定。
- 组合层与恢复层：共享 `normalize_current_binding_payload`，不再各自宽松判断。显式注入的本地查询仍可返回完整裸绑定或 None；这不是远端 HTTP 响应的许可。
- 拒绝嵌套 envelope：否则生产适配先解一层、组合层再解一层，仍可能把畸形绑定当作可信 null 而回退。
- 绑定身份：threadId 必须为非空、无首尾空白的字符串；tenantId/chatSessionId 必须完整，接受正 Java Long 整数及其规范十进制字符串，拒绝布尔、浮点、容器、空白、前导零和溢出。
- 归属判断：两个身份同时匹配请求才可 resume；缺失或错配不得 resume，也不得 create 来掩盖错误。

## 必须保留的行为

- 后端有完整绑定时优先使用后端，不用本地旧绑定覆盖。
- 可信成功 null 才能进入本地恢复兜底；本地完整登记记录即使授权 TTL 已过仍可用于找回原 thread。
- 真正无绑定仍可 create；本地最小栈未配置 lookup 的语义不变。
- 已知无 rollout、active writer、runtime exit 的原有恢复策略不变；未知查询/恢复故障不降级为新建。
- 本地登记表的授权重登记、过期/撤销策略、工具授权不在本批调整范围。

## 执行与验证

- [x] 复核原调用链、现有测试及后端 DTO；沿用当前工作区，不创建分支或委派。
- [x] 先写永久失败回归，再改生产代码。
- [x] 收紧 HTTP 成功条件、统一 envelope 校验、验证必填身份。
- [x] 源码复核时补充嵌套 envelope 的真实生产链路失败回归，再修复。
- [x] 定向单测：111 passed，0.42s；`/tmp/zhiyuan-binding-contract-green.log`。
- [x] 定向集成/准入回归：169 passed、2 skipped，5.04s；`/tmp/zhiyuan-binding-integration-green.log`。
- [x] 完整离线 unit/integration（排除 e2e）：2971 passed、21 skipped、33 deselected、23 warnings，65.75s，退出码 0；`/tmp/zhiyuan-binding-recovery-full.log`。
- [x] 提交前重新执行完整离线回归：2971 passed、21 skipped、33 deselected、23 warnings，65.70s，退出码 0；`/tmp/zhiyuan-binding-recovery-precommit.log`。
- [x] 已跟踪差异及本批新增文件空白检查无输出；用户已同意将本批独立提交。

完整回归命令（在 `zhiyuan-agent` 下）：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
timeout --signal=TERM --kill-after=10s 300s \
.venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
tests/unit tests/integration -m 'not e2e' -q -rs \
-o faulthandler_timeout=30
```

19 项因未配置测试 Redis 跳过，2 项因未安装固定 Codex 二进制跳过；没有把这些跳过算成通过。23 项告警与基线数量一致，为既有 Pydantic usage 弃用及同步函数 asyncio 标记告警，未在本批修复。

红灯证据：

- 初版契约回归：40 failed、26 passed，失败是预期未抛异常/错误归属；不是导入或语法错误。
- 初版真实 HTTP + 实际 lifespan 组合：17 failed、6 passed，证明生产路径会误回退或恢复无身份绑定。
- 严格 GET 参数与组合层异常传播：2 failed。
- 复核新增嵌套响应回归：1 failed、23 passed，捕获重复解包导致的误回退。

集成覆盖临时 HTTP 服务、真实 `get_current_codex_thread_binding`、真实 lifespan 中的回调、组合查询和临时 SQLite 登记表。原有真实 harness + 假 stdio 子进程恢复用例一并通过。跳过的 Redis/固定 Codex 二进制测试不算通过。

测试通过离线保护 runner 执行，只允许连接当次测试创建的 loopback listener；不访问现有业务服务、共享 Redis/数据库或真实模型。沙箱不允许创建 listener 时，使用审批后的同一离线命令运行。

## 本批文件与后续

生产改动：`zhiyuan-agent/app/gateway/thread_recovery.py`、`zhiyuan-agent/app/util/internal_client.py`、`zhiyuan-agent/app/server.py`。

永久测试：新增 `tests/unit/test_thread_recovery_contract.py`、`tests/integration/test_thread_recovery_transport.py`；更新 `tests/unit/test_thread_recovery.py`、`tests/unit/test_codex_binding_client.py`。

本轮为直接源码复核，不声称独立 reviewer 审查。本批按用户确认独立提交，不推送或部署；前端既有构建产物和前序调查文档保持原样，不混入本批提交。

下一批先明确 working set 跨轮候选、artifact/source-turn 锚点的恢复来源或显式降级契约；当前仍不能因为 snapshot 可读就启用自动回收。
