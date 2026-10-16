# 会话引用登记：代码审查与实现交接

日期：2026-10-16。基线：`796d691`。分支：`wip/2026-09-28-p2-write-loop-green`。

## 结论

用户授权代码 review 后直接推进。核对真实边界后，采用共享单 worker 协调器方案；本批实现与离线回归完成，随后用户同意独立提交，提交状态以 git log 为准，未推送、未部署。审查由当前执行者直接完成，不声称经过独立 reviewer。

本批是安全回收的第 2 批前置修复，**没有启用内存回收**。不修改 Java 事务、pending 消费、线上配置或 `CODEX_DETACH_ON_CLOSE`，不调用真实模型、不重启业务服务、不写共享数据库。

## 审查发现与处置

| 风险 | 处置 |
| --- | --- |
| `_channels` 只保存最新连接，不能覆盖仍存活的旧连接 | lease 归真实 channel；每条连接独立计数，重复绑定幂等，sender 关闭后释放；路由选择仍保持原行为 |
| native replay 位于 try/finally 外，异常和取消绕过收尾 | replay、sender.start、receive loop 进入同一 try/finally；可信票据会话在首次等待前登记 |
| 排队者、未启动就取消的 Task 和无 requestId 的动作无法用 active turn 代表 | admission 在锁等待前登记；turn/action 在调度前登记并由 Task done callback 释放；调度失败关闭协程并释放 |
| Broker 回答返回早于 RPC write/drain | reader 在创建 handler Task 前获取 native_request lease，直到结果/错误写回或取消收尾完成才释放 |
| closed/ended reader 仍可能读取缓冲请求并登记引用 | reader 在 factory 前复核接受代际，关闭/结束/旧代际不登记；handler 执行和写回原有代际守卫保留 |
| sender 创建失败遗留未等待协程，关闭 channel 可能再次启动 | 创建失败关闭协程；closed channel 禁止重新启动；重复 close 共享完成通知 |
| Gateway、SessionRuntime 与协议边界若各自计数会出现保护空窗 | composition 创建单一 registry，server 显式注入；真实 Runtime 构造及后绑定错配均拒绝 |

## 实现契约

- `session_lifecycle.py`：固定 owner 类别、唯一 session-entry generation、活动 revision、按类别计数、最后释放的 monotonic idle 起点、不可变只读快照及幂等 lease；不保存 Task/channel/问题内容，不提供清空或驱逐入口。
- Runtime：排队 admission、turn、detached action、publish、请求状态读取及 interrupt/steer 异步调用均受保护。保留 DeferredRequest、请求去重与状态收尾，后台动作在 App Server 重启后继续持有。
- Gateway：公共快照、动作、回合、续接及控制入口覆盖锁等待和 loader；不移动水位递增、once-key 或业务锁。动作已生效后刷新失败仍返回真实终局。
- 连接：按可信票据提前登记，不使用客户端自报会话授权；不同租户/会话不可在 channel 上切换。connection 释放独立于是否摘除路由，保留默认开关语义。
- 原生协议：通用 Client 只依赖可关闭 lease 协议；composition 经 Harness 注入 factory。native 及 MCP form 均使用 Broker 的可信 thread 解析；无绑定返回 RPC 错误，未知方法仍返回原有 null 结果。

## 验证证据

### 失败测试与复查

- 协调器初次执行因模块缺失失败；Runtime 首轮 9 项失败，Gateway 首轮 10 项失败，连接接线首轮 6 项失败，均指向未实现的 ownership/关闭边界。
- fake-stdio 的回答写回与进程退出引用测试在实现前失败；原有不可信 scope 拒绝测试已能通过，作为保留行为回归，不计为新红绿证明。
- 最终复查：closed/ended reader 的 2 个测试先失败，修正 reader 验证边界后通过；sender 创建失败/关闭后重新启动的 2 个测试先失败，修正后通过。
- 后补的刷新失败保持终局、实际 server 动作从水位到终态/续接连续持有、resolved/expiry/form-decline 和未知 RPC 测试用于补充覆盖；未将每个后补用例都单独执行红灯，不声称所有用例均独立完成红绿验证。

### 聚焦回归

从 `zhiyuan-agent` 运行：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  /tmp/zhiyuan_hardening_pytest.py \
  tests/unit/test_session_lifecycle.py \
  tests/unit/test_session_runtime_ownership.py \
  tests/unit/test_gateway_session_ownership.py \
  tests/unit/test_ws_session_ownership.py \
  tests/unit/test_native_request_ownership.py \
  tests/integration/test_gateway_composition.py -q -rs
```

结果：**68 passed、1 skipped，5.06 秒**。跳过项为未安装的固定 Codex 二进制。

### 最终离线全量

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  timeout --signal=TERM --kill-after=10s 300s \
  .venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
  tests/unit tests/integration -m 'not e2e' -q -rs \
  -o faulthandler_timeout=30
```

授权沙箱外运行，包装器只允许 fixture 自建的回环监听端口，20 秒单测试上限及 300 秒命令上限；没有放通现有业务端点。结果：**2731 passed、21 skipped、33 deselected、23 warnings，65.04 秒**，退出码 0。日志：`/tmp/zhiyuan-session-ownership-final-regression.log`。

19 项跳过需要 `CODEX_TEST_REDIS_URL`，2 项需要固定 Codex 二进制；不计为通过。23 条 warning 为既有 Pydantic usage 弃用和同步测试被 asyncio 标记，不在本批扩修。

先前沙箱内全量在 fixture/socket/TestClient 路径出现错误并停滞，不能作为验收；未因此降低断言或改动业务逻辑。授权离线首轮为 2718 passed，最终补充边界后重新执行得出上述 2731 项结果。

已检查本批 tracked diff 与全部新增文件的空白错误；没有新增格式化工具或依赖。

用户同意推进后，在相同隔离条件下再次执行提交前全量复验：**2731 passed、21 skipped、33 deselected、23 warnings，64.95 秒**，退出码 0；日志 `/tmp/zhiyuan-session-ownership-precommit.log`。

## 剩余风险与下一批

1. 会话字典、旧关闭路由及协调器空闲元数据仍会积累；本批不解决容量增长，零 owner 不等于允许删除。
2. `get_authoritative_snapshot` 的失败缓存回落不是新鲜 pending 权威。下一批必须先建立新鲜三态 pending 预检、活动 revision 二次校验与删除前无 await 的原子边界。
3. 后续 TTL/容量策略、closed route 处置、持久 binding 恢复 thread 需单独设计验收；不提前增加自动删除开关。
4. 当前保护只适用于单事件循环/单 worker，不提供分布式锁或故障接管；专用 Redis、真实二进制与线上端到端仍未验证。

## 变更隔离

本批 app 改动位于 agent 的 lifecycle/runtime/service/user_input/composition/client/codex/server；测试及本批 spec/plan/handoff 随实现一起交付。原有 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/` 和两个既有未提交调查文档保持原样，不混入本批。用户授权后按明确文件清单独立提交，不推送或合并其他分支。
