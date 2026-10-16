# 可信 MCP 产物账本交接（2026-10-16）

## 范围

用户批准复用现有 SQLite 的签发账本方案。本批在 `7b6a0a4` 上已有的前两批未提交修改旁继续实施，保留用户原有构建缓存和运行目录。
没有创建分支、暂存或提交，没有部署、改实际密钥、重启服务、接入共享 Redis/Java 或写真实业务数据库。
会话生命周期回收与多实例归属仍未实现，不把本批前置条件当作完整内存治理。

## 本批实现

1. `app/gateway/artifact_store.py` 提供独立 SQLite 账本，复用既有绑定文件但使用独立表和索引。签发事务先提交再返回；同内容在有效期内复用原记录，结果摘要或有效期代际变化生成新 ID，旧 ID 不会因过期清理后的重签而复活。
2. 记录默认有效 24 小时，单条 16 KiB、查询最多 128 个 ID；签发事务按索引最多清理 128 条到期记录。JSON、身份、时间和内容身份有校验；读取损坏或存储失败拒收，不回落内存。不是后台自动清盘或严格磁盘容量上限。
3. 真实 stdio `serve`、SDK 和 Gateway composition 共用 store。readonly/write 缺少文件配置时在 Codex 启动前失败。MCP 只有成功的 candidate/comparison 结果才能登记；登记失败不返回成功产品或引用，缓存命中也要重查是否仍有效。
4. Gateway 删除进程内 `_registered_artifacts` 权威；只按最新结构化输出引用的 ID 查询当前 tenant/session 的真实签发记录。模型正文和事件递归收集不再有产物登记权限。初轮、所有契约修复、priority 修复及 evidence 重查都按最新输出重读；非产物修复保留原证据账本。
5. validator 补 tenant、artifactType 与记录/引用版本一致性检查；同会话换 thread 仍允许，回合内版本重基仍必须经 Java 权威上限读数。缺失引用进入已有的一次只读工具修复分支，存储不可用不靠模型补章放行。
6. 旧测试中的可信工具结果改为显式 store fixture：候选 fixture 在模拟工具执行时登记，不把任意事件视为可信。另有真实 store + 真实工具适配器 + fake backend 的接线测试和 Gateway 跨实例重开、零工具引用验证。

## 本轮验证证据

- RED：安全反例 6 failed；新 store 测试因模块不存在收集失败；MCP 签发 4 failed；生产装配探针 3 failed / 13 passed / 1 skipped。日志 `/tmp/zhiyuan-artifact-{security,store,mcp,composition}-red.log`。
- 初次扩展回归发现 27 个旧 fixture 仍依赖无 store 签发、缺失 tenant/type 或内存登记。没有放宽生产路径；调整显式可信 fixture 后定向回归 195 passed、1 skipped、1 个既有 warning。日志 `/tmp/zhiyuan-artifact-focused-second.log`。
- 新增 Gateway 用例覆盖跨重建、完整模型自报章、跨作用域、存储故障以及修复轮更换引用，随最终定向/全量回归通过；无模型、无真实后端调用。
- 全量离线 Python 单元（全部复审修复后重跑）：**2507 passed、33 deselected、20 warnings，58.16 秒**。仅 deselect e2e 标记；包装器只放行测试自建监听端口，每例超时 20 秒。日志 `/tmp/zhiyuan-artifact-unit-final.log`。
- 扩展集成先无 Redis 跑到 97 passed / 20 skipped，再通过无网络、无持久化的临时 Redis 容器与 `/tmp` Unix socket 补齐；全部复审修复后重跑：**116 passed、1 skipped、3 warnings，9.34 秒**。唯一 skip 是缺固定 Codex App Server 二进制。临时容器随命令结束停止，不连接共享 Redis。日志 `/tmp/zhiyuan-artifact-integration-redis-final.log`。
- 本批没有修改 Java 或 Web 代码，不把前两批 Java/前端验收记录当作本轮新跑结果。

## 复审

SQLite/MCP 独立只读复审发现一项 P2：深层损坏 JSON 的 RecursionError 和追加列后的行解包异常可逃逸错误边界，中断 MCP 调用；不是越权放行。
已先补 4 条红灯回归（4 failed / 19 passed），再前置 checksum、归一化递归错误并显式指定 SELECT/INSERT 列；store/MCP 定向 28 passed。
复审者独立重跑 28 passed，并重放缓存及新 runner 反例确认稳定拒收、加列兼容，确认该 P2 关闭。日志 `/tmp/zhiyuan-artifact-review-{red,green}.log`。
Gateway/validator 复审确认第二项 P2：只读取首轮 ID 集合会导致非产物类契约修复改引已签发 B 时误拒；不换 ID 时也会沿用旧条目、漏过修复期间的到期/存储故障检查。
已补 7 条回归先红（5 failed / 13 passed），抽离 `_artifact_inputs`，将“允许修复工具调用”与“每次重读产物”解耦，并覆盖 priority 修复；定向 100 passed / 1 skipped。日志 `/tmp/zhiyuan-artifact-repair-{red,green}.log`。
复审者独立重跑 authority/evidence_flow 37 passed，并验证 proposal/admission/priority 六组未签/外租户完整自报章拒收，确认第二项 P2 关闭。两项限定范围复审收口，未留下已确认高/中风险问题；不等同于完整上线审计。

## 升级与未完成事项

- 必须保留同一受限权限本机持久卷，Gateway/MCP 使用同一路径和可访问 UID；文件不可处于模型可写目录。checksum 是损坏检测，不是对抗控制该数据库的攻击者的签名。
- 旧进程内产物不能从历史 assistant 文本自动迁入；升级后找不到的旧 ID 需要只读工具重新签发。Java 的冻结方案和 pending 命令产物没有迁移。
- 本机卷丢失、跨主机共享、分布式 fencing/串行、待确认卡生命周期与安全会话回收均不在本批承诺内，继续单 worker。
- 同日 readiness handoff 中缺少的 94 条私有脱敏夹具、完整模型写入式 E2E、整站浏览器/完整生产构建及协调鉴权上线窗口仍需另行解决。

## 提交判断

当前尚未执行 `git add` / `git commit`。本批与前两批部分修改共享 `service.py`、`composition.py` 及 cache 测试，不能只提交新 store 文件造成生产装配断链。
复审已收口，适合按依赖完整的逻辑批次提交已验证修复，不需要等多实例改造，但提交不表示批准部署。
建议将前端修复作为独立逻辑批次，内部鉴权与调用方迁移保持配套，Agent 幂等/缓存/产物账本及对应测试一起审查；文档随所属修复提交。
共享文件须逐项/逐 hunk 确认，绝不 `git add .`。排除 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/`、日志、SQLite 文件与 sidecar。
