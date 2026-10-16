# 原生问答生命周期修复交接

日期：2026-10-16。实现基线：`bedc026`；分支：`wip/2026-09-28-p2-write-loop-green`。

## 范围与结论

本批完成会话安全回收调查中第 1 批：原生问答记录/索引清理、有界回答回执、运行时代际隔离，以及退出、重启、resolved 通知和超时中断的实际接线。计划见 `docs/superpowers/plans/2026-10-16-user-input-lifecycle.md`。

这是问答生命周期的前置修复，**不是会话驱逐实现，也不代表全部架构风险已经消除**。没有修改 Java 业务事务、Gateway 会话回收策略、在线配置或 `CODEX_DETACH_ON_CLOSE`。没有部署、重启现有服务、调用真实模型或写入共享数据库。

## 实现边界

### Broker

- timeout、取消、emitter 失败/取消、native resolved 和 runtime 退出均释放 pending 与 RPC 反向索引；旧等待者的 finally 通过记录身份校验，不能误删后来复用 RPC ID 的请求。
- 成功回答后立即释放 Broker 持有的完整问题记录，仅保留 session key、generation、答案摘要与过期时间；默认全 Broker 最多 **1024** 条、**600 秒**。FIFO 淘汰和 TTL 在访问时惰性清理，不创建后台清理任务。
- 去重窗口内相同答案为 `accepted`、不同答案为 `conflict`、跨会话答案拒绝；过期、容量淘汰或运行时退出后不再保证旧回答可重放，返回 `unknown_request`。
- RPC 索引使用 `(generation, ID 类型, ID)`，区分整数 `1` 与字符串 `"1"`；活动 ID 冲突直接拒绝。snapshot 排除已完成/取消或过期的请求。
- 配置可信 scope resolver 时，缺少绑定直接拒绝，不回落到模型携带的 tenant/session 元数据。记录分别保留原生 thread/turn ID 和业务 UI turn ID。

### 传输与组合层

- AppServerClient 每次成功启动生成新 generation；stdout reader 和原生请求任务捕获所属代际。旧 reader 不向新进程的等待者分发结果，旧 handler 的迟到 result/error 不写入新进程。
- 启动、退出和通知通过同步回调接入 Broker；退出同时唤醒请求/通知等待者、取消并等待所属原生请求任务收尾。
- 临时 notification observer 只旁观，不从现有 collector 或 backlog 取走通知；作用域退出、取消和进程退出均收尾。
- 超时按可信绑定使用原生 thread/turn 发送 interrupt，等待同一原生回合的 terminal 后，才返回 `clarification_expired`。terminal 仍由原 collector 接收，没有合成新的 `turn/start`。
- 终态识别保留既有字段兼容性：`turn.id`、`turnId` 和 `turn_id`。不能仅凭相同 thread、缺失 turn ID 的通知认定本回合已经结束。

## 验证证据

### 测试先行

- 首轮 Broker 新回归：22 failed、1 passed；失败来自索引/记录保留、代际未隔离和缺失配置接口。
- 首轮 transport 新回归：11 failed；首轮组合层接线回归：2 failed、1 passed。
- 最终复审补充字段兼容用例，修改实现前为 1 failed、2 passed，失败为 snake_case 终态无法唤醒 observer；补齐后通过。
- 后续补充了 emitter 取消、过期回调失败、旧 reader、完整超时 stdio 链路等边界用例。并非所有补充用例都单独执行了红灯，不能把补充覆盖等同于每项均独立完成红绿验证。

### 最终聚焦回归

在 `zhiyuan-agent` 目录运行：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
  tests/unit/test_user_input_runtime_lifecycle.py \
  tests/unit/test_user_input_lifecycle.py \
  tests/integration/test_gateway_composition.py -q -rs
```

结果：**55 passed、1 skipped，0.77 秒**。日志：`/tmp/zhiyuan-user-input-final-chain.log`。跳过项需要未安装的固定 Codex App Server 二进制，不计为通过。

### 扩大离线回归

原沙箱运行在测试 fixture 创建 socket 时出现 `PermissionError: [Errno 1] Operation not permitted`，后续停滞；已仅终止本轮 pytest 进程。诊断用的 fixture 文件在授权沙箱外重跑为 **7 passed**，并未为此修改业务代码或测试预期。

随后在授权沙箱外运行：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  timeout --signal=TERM --kill-after=10s 300s \
  .venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
  tests/unit tests/integration -m 'not e2e' -q -rs \
  -o faulthandler_timeout=30
```

结果：**2678 passed、21 skipped、33 deselected、23 warnings，64.40 秒，exit 0**。日志：`/tmp/zhiyuan-user-input-regression-escalated.log`。

- 21 个 skip：19 个需要 `CODEX_TEST_REDIS_URL`，2 个需要固定 Codex App Server 二进制；没有连接共享 Redis 来补跑。
- 33 个 e2e 被显式排除；本批不宣称完成真实模型/真实二进制协议验收。
- 23 个 warning 位于本批未修改的 `base_agent.py` 调用路径和 `test_domain_mcp_tools.py`：22 个 Pydantic AI usage 弃用告警、1 个 asyncio 标记告警；未越界修改。
- `/tmp/zhiyuan_hardening_pytest.py` 是本机临时验证入口，不随提交分发：仅允许本进程自建 fixture 的回环监听端口，阻止访问既有服务和外部地址，并为单项设置 20 秒告警。整体运行另设 5 分钟截止。
- `git diff --check` 通过。没有配置/引入新的格式化工具。

## 尚未覆盖的保证

- 回执是单 worker 进程内的短期幂等窗口，不是持久化 exactly-once 台账，也不是跨 worker ownership/fencing。
- 缺失原生 ID、可信绑定不可用、interrupt 失败或 terminal 超时会报错，不猜测其他回合、不自动重启共享 runtime。无法据本批离线测试保证这些故障下真实模型的后续行为；需要固定二进制验收后再作保证。
- 生命周期回调是内部同步、非阻塞接线；取消收尾依赖 handler 配合取消。本批没有为任意第三方回调异常或故意吞掉取消的 handler 增加隔离机制。
- Gateway 会话字典、关闭连接登记以及后台动作/续接的引用生命周期仍属后续阶段。下一批应先补 owner/lease 登记和释放测试，再考虑只驱逐经新鲜权威查询确认空闲的会话；不能直接启用 TTL 删除。

## 提交建议与工作区

本批适合单独提交，建议消息：`fix(agent): bound native input lifecycle and fence runtime generations`。本轮尚未执行 git add、commit 或 push。

建议明确限定为 9 个文件：

- `zhiyuan-agent/app/gateway/user_input.py`
- `zhiyuan-agent/app/gateway/composition.py`
- `zhiyuan-agent/app/harness/client.py`
- `zhiyuan-agent/app/harness/codex.py`
- `zhiyuan-agent/tests/unit/test_user_input_lifecycle.py`
- `zhiyuan-agent/tests/unit/test_user_input_runtime_lifecycle.py`
- `zhiyuan-agent/tests/integration/test_gateway_composition.py`
- `docs/superpowers/plans/2026-10-16-user-input-lifecycle.md`
- `docs/superpowers/reviews/2026-10-16-user-input-lifecycle-handoff.md`

保留且不混入本批：用户已有的 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/`，以及此前未提交的 Web 验收和会话回收调查文档。未做独立代理代码审查；本轮为本地差异复审加离线回归。
