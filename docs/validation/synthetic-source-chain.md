# 本地合成招生源链路验收

此验收仅验证隔离 Java、Rank、MySQL 对合成源的处理与持久化。招生计划 ID、分数、概率和学校展示名均为合成数据；结果不能说明真实招生数据或推荐质量。脚本不发送 Agent 消息，不生成确认操作，不提交志愿。

从仓库根目录运行。默认只打印预览，不连接网络、Docker 或数据库，也不写文件：

```bash
zhiyuan-agent/.venv/bin/python scripts/validation/probe_synthetic_source_chain.py
```

确认当前隔离栈健康后，显式传入该次运行的后端日志并执行一次：

```bash
zhiyuan-agent/.venv/bin/python scripts/validation/probe_synthetic_source_chain.py --apply \
  --backend-log /root/zhiyuan/.runtime/codex-local-<run-id>/logs/backend.log
```

入口先验证隔离 MySQL 容器映射 `127.0.0.1:13306`、Java `127.0.0.1:18290` 与 Rank `127.0.0.1:18292` 的当前进程，核对 Java 私有配置中的 JDBC、源文件目录、高途无效地址、`ali.oss.enabled: false`，并要求当前 PID 的启动日志出现 OSS 禁用记录。它使用 `codex-test` 私有凭据走真实登录，创建一个 `SYNTHETIC-chain-*` 草稿会话，仅向该新会话写入合成成绩与空画像。ORIGINAL 文件只允许新建，不覆盖已有文件。

脚本随后通过真实 API 生成候选和初始方案，再独立从 API 与隔离库回读，要求 **12 个合成候选、10 个选中项、10 个排序项**，以及 `PREDICT` 后台新鲜度巡检关闭。证据写入被 Git 忽略的 `.runtime/validation/zhiyuan-SYNTHETIC-chain-*/`；`manifest.json`、`summary.json`、`cleanup.json` 和各步回读可复核。构建器可单独预览，但 `--apply --output-dir` 只接受 `.runtime/validation/` 内的新目录。

日志观察只统计实际远程 bridge 的启动记录。`OSS download skipped because OSS is disabled` 表示调用被本地开关跳过，记录次数但不当作远程请求。日志窗口无相关记录仅说明这次工作负载在可见日志中未出现远程 bridge 活动；它不是抓包证据，也不覆盖其他工作负载。

清理时先核对 `cleanup.json` 中的 session ID、owner、tenant 和合成 marker，再逐项检查该会话在 `assistant_chat_session`、`assistant_chat_session_extra_data`、消息、规划新鲜度、行为事件和 pending 表中的实际行。源文件与证据目录的路径也在清单中。不得按前缀批量删除或影响共享的 `codex-test` 账户及其他会话。
