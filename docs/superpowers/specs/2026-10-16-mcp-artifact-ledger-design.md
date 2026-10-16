# 可信 MCP 产物账本

## 授权与范围

用户已确认 `../reviews/2026-10-16-artifact-lifecycle-discovery.md` 中复用现有 SQLite 的路线，并授权实施。
本 spec 固化该书面设计，不改变业务提案、自动预填或单 worker 部署约束。按已有协调约定在当前工作区实施，不自动提交。

## 信任与数据流

Gateway/MCP 使用既有 `CODEX_APP_SERVER_BINDING_REGISTRY_PATH` 文件中的独立表。
`SqliteArtifactStore` 只负责可信签发、按租户/会话批量读取以及过期清理；不依赖 Gateway 或 MCP 实现。
可信 MCP 在校验 binding、读取权威版本并完成工具执行后，调用 store.issue，提交成功后才对模型返回 artifacts。
Gateway 只从输出/事件中提取引用 ID；登记权限绝不来自模型文本或自带的身份字段。
所有真正用于验证的字段从 store 读取；本进程不保留可作为替代权威的 `_registered_artifacts` 字典。

## 不可变性与寿命

记录包含 tenant/session/type/stateVersion、工具名、可信入参摘要、工具结果摘要、审计 thread 和签发/到期时间。
产物 ID 对租户、会话、类型、版本、工具名及两份摘要做 SHA256；相同内容重试返回原记录，不改写 thread 或延长 TTL。
不同内容产生不同 ID；同 ID 内容不一致或记录损坏必须拒绝。JSON 禁止非有限数。
每条记录最多 16 KiB，TTL 默认 24 小时，时钟可注入；恰好到期即失效。
查询按 tenant/session/id 精确限制，不泄露外租户 ID 是否存在；未命中返回空，输出校验报告 artifact_not_found。
每次成功签发前最多清理 128 条已到期记录，使用 expires_at 索引；不删除未过期记录，也不触及 Java 冻结命令产物或绑定表。
ID 包含签发时间代际，避免已过期、已清理记录的旧引用因相同参数重查而重新有效。

## 故障与兼容

SQLite 读取/写入失败返回稳定 artifact_store_unavailable，不回落内存或相信事件；不向用户透出路径、SQL、密钥或原始异常。
生产 codex_readonly/write 装配必须配置此文件并在启动运行时前初始化。单测可显式注入 fake store，纯文本回合不依赖 artifact 查询。
validator 对 artifact 补齐 tenant/type/版本一致性检查；回合内权威重基区间及同会话恢复换 thread 的语义保留。
首次、schema 修复、产物修复和 evidence 重查都按最新输出的 ID 重新读取 store。
旧 `mcp_art_*` 无法仅凭历史事件自动迁入；由只读工具重新签发。旧 ID 的 artifact_not_found 进入已有的一次修复分支，不无限重试。
进程重启恢复要求本机受限权限持久卷保留，不承诺丢卷恢复、SQLite 跨主机共享或多实例串行。

## 验证

先复现模型自造产物和跨租户通过的反例，再实现。
临时 SQLite 覆盖跨实例重开、同内容重试、结果变化、到期重新签发、大小/参数/损坏校验、定量清理、失败不放行和绑定表共存。
真实 ReadonlyDomainTools + fake backend 验证先登记再返回；Gateway + fake harness 验证零工具跨回合/跨重启引用、修复轮和重基。
不连接共享 Redis/Java，不调用模型，不重启本地服务。会话回收在本阶段验收后另行实施。
