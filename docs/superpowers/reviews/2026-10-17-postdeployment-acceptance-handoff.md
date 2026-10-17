# 部署版本留档与只读冒烟交接

日期：2026-10-17；分支：`wip/2026-09-28-p2-write-loop-green`；本轮生产代码提交：`7d99822`。

## 执行状态

用户已批准推进部署版本留档及真实链路冒烟。本轮已完成候选降级修复的独立提交、提交前完整离线回归、运行实例核对及本机只读安全探针。**尚未完成真实模型和写入式端到端验收，不能据此宣称发布验收全部通过。**

没有推送、重启、重建运行中的 Web 目录、修改实际凭证、执行 Redis 清理或修改业务数据；没有复用旧用户会话触发确认/取消，也没有调用真实模型。服务凭证只从已批准读取的 Agent 进程环境取入探针内存，没有打印或写入报告。

## 独立提交与离线证据

`7d99822 fix(agent): clarify missing candidate context without inventing recovery` 仅包含：

- `zhiyuan-agent/app/engine/working_set.py`
- `zhiyuan-agent/tests/unit/test_working_set.py`
- `zhiyuan-agent/tests/unit/test_gateway_working_set_reconciliation.py`
- `docs/superpowers/reviews/2026-10-17-candidate-context-degradation-handoff.md`

在原 `4e30d41` 基线上，提交前重新运行完整离线 unit/integration 回归：**2996 passed、21 skipped、33 deselected、23 warnings，67.31 秒，退出码 0**。

日志：`/tmp/zhiyuan-candidate-context-precommit-20261017.log`。19 项需要专用测试 Redis，2 项需要显式配置固定 Codex 二进制；跳过不算通过。本轮运行进程核对发现 Agent 配置的 Codex 二进制文件实际存在，因此不能将测试 shell 未配置路径表述为本机完全没有可执行文件。没有把线上 Redis 或 Agent 凭证直接接入离线测试来消除跳过。

工作目录中的 `working_set.py` SHA256 与提交内容一致：`2b50b3639312314072813140333e90f506867beaa3f1e15e820f7bc4b9316aaf`。

整理交接时，另有工作线推进到 `0ff5e32`，并出现 MCP schema/技能及前端会话处理的未提交改动。这些文件没有被本轮修改或暂存；上述完整回归仅对应候选降级批次，不能作为后出现改动的验证结果。本验收记录单独提交。

## 本机运行实例

只读核对的实例如下，均未重启：

| 端口 | PID | 已核对信息 |
| --- | --- | --- |
| 18290 | 15304 | Java，启动于 2026-10-17 09:42:23 +08:00 |
| 18291 | 15591 | Agent，启动于 2026-10-17 09:42:45 +08:00；工作目录为当前 `zhiyuan-agent`；`GATEWAY_MODE=codex_write`、`MCP_MODE=readonly` |
| 3201 | 31139 | Web 开发实例；`NODE_ENV=development`、`APP_ENV=dev`、`NEXT_DIST_DIR=.next-dev`；入口为 `/login` |
| 3001 | 10117 | Web，`APP_ENV=production`，使用默认 `.next`；入口为 `/assistant-pc/login` |

候选上下文源文件修改时间为 2026-10-17 09:14:22 +08:00，早于 Agent 启动；这是部署源路径和时间关系的佐证，**不是进程实际加载字节或真实模型行为的直接证明**。本轮没有热注入调试代码或为核对版本重启进程。

## 只读探针结果

2026-10-17 18:17:45 +08:00 重跑：**12 passed、0 failed，退出码 0**。

| 检查 | 结果 |
| --- | --- |
| 18290 内部健康，无服务凭证 | 401 |
| 18290 内部健康，错误服务凭证 | 403 |
| 18290 内部健康，Agent 当前服务凭证 | 200，业务信封成功且状态 UP |
| 18291 `/health` | 200，状态 UP |
| 3201 `/login` | 200 |
| 3001 `/assistant-pc/login` | 200；响应 buildId 与磁盘 BUILD_ID 一致 |
| 3201 正确基础路径下的 inner/evidence 代表性路径 | 各 404 |
| 3001 正确基础路径下的 inner/evidence 代表性路径 | 各 404 |
| 18291 V3 WebSocket 无票据 | 403，未发送回合 |
| 18291 V3 WebSocket 假票据 | 403，未发送回合 |

临时驱动：`/tmp/zhiyuan_postdeploy_readonly_probe_20261017.py`。最终结构化证据：`/tmp/zhiyuan-postdeploy-readonly-20261017.json`；原始路径误配记录：`/tmp/zhiyuan-postdeploy-readonly-20261017-initial.json`。这些文件不是发布产物，不保证跨机器或清理 `/tmp` 后保留。

首轮为 11 passed、1 failed：探针错误地把 3201 当成带 `/assistant-pc` 的生产基础路径，登录页返回 404。依据实际进程 `APP_ENV=dev`、`next.config.mjs` 的明确基础路径规则及既有 `/login` 入口，修正探针路径后复跑通过；没有修改服务端逻辑，也没有将该错误路径下的 404 当作内网封堵证明。最终两组封堵检查均在对应实例的真实基础路径下执行。

这些结果仅覆盖本机直连及代表性路径；不证明公网代理、全部路由、合法票据的跨用户拒绝、跨重启恢复或业务写入正确。

## 发现的发布差异

3001 的匿名登录页实际返回 `buildId=LznUVyKZVJ9zg_ESdO1yk`，与当前默认 `.next/BUILD_ID` 一致。该文件修改时间为 **2026-10-06 11:28:57 +08:00**，对应 `required-server-files.json` 中仍为 **`typescript.ignoreBuildErrors=true`**；当前源码则为 false。

因此，**3001 实际仍在提供旧构建，不能用源码修复或历史隔离构建通过来证明此实例已发布最新前端门禁**。3201 是开发实例，其可访问也不是生产构建发布证明。本轮没有从上述信息推断所有前端改动均缺失或宣称实际存在某条 XSS 利用链；Markdown 消毒等具体改动是否进入其他对外产物仍需逐入口核对。

建议优先安排 Web 受控发布：使用隔离构建目录生成新生产产物并留存源码提交与 buildId 对照，在已授权切换窗口发布，然后验证实际入口的产物和浏览器行为。不要在运行中的 `.next` 内直接覆盖构建。

## 尚未执行的业务验收

下列项目均为 **not_run**，不是通过：

1. 合法测试身份尝试访问另一隔离测试用户的会话并被拒绝。
2. 合法票据连接、断线重连及 native thread 续接。
3. 真实模型跨轮候选指代。
4. 真实模型在候选工作集缺失时的诚实降级。
5. 隔离计划确认后只执行一次，重复请求不重复写。
6. 隔离计划取消后不执行，旧卡不能再次生效。

现有 MySQL/Redis 容器正在供既有栈使用。本轮未核定本次写入验收的可重置实例、测试凭证和会话归属；不能仅凭容器名字或旧 fixture 的 runId 就自动执行重置/写入脚本。需要提供或核准隔离验收目标和凭证文件路径，并记录本轮新建合成会话范围后，再执行上述项目。

只读夹具预检也已重跑：**缺少 94 条引用，退出码 2，未启动任何命令**。日志：`/tmp/zhiyuan-postdeploy-fixture-preflight-20261017-final.log`。不造空文件，不读取真实用户数据来凑绿灯。

保持单 Gateway worker，不启用会话自动回收；精确候选批次恢复及空 admissionFacts 语义仍按既有交接列为后续独立任务。
