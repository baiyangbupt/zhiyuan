# 本地研发测试账户与数据边界

隔离栈使用本地用户名账户 `codex-test`，不要求高途内部账号。密码由测试脚本生成，保存在
被 Git 忽略且权限为 `0600` 的 `.local/codex-local/browser-test-credentials.json`。
不要把这个文件提交到仓库。准备命令如下；不带 `--apply` 只预览目标。

```bash
python3 scripts/prepare-codex-test-account.py
python3 scripts/prepare-codex-test-account.py --apply
python3 scripts/prepare-codex-test-account.py --name codex-test-qa --apply
```

脚本只接受 `zhiyuan-codex-local-mysql-1` 映射到 `127.0.0.1:13306` 的
`zhiyuan_codex_local` 数据库，并核对 Java 配置。已有同名但不属于本次 fixture 的账户会拒绝
覆盖。新密码使用 PBKDF2-SHA256、随机盐和 600000 次迭代。重复运行保留账户 ID 和密码，
因此已有会话归属不变。不要对生产数据库执行此准备流程。

用户名登录走本地凭据表；高途 token 登录是另一条会调用高途服务的路径。测试账户仍通过
真实登录令牌、当前用户、租户与会话归属校验，并使用一次性票据建立 WebSocket，未绕过鉴权。
`ytell` 渠道和本地 `SUPER_VIP` 测试权限避免依赖高途用户权益。

| 数据 | 来源与测试边界 |
| --- | --- |
| 学校、专业、地区目录 | Java 包内 CSV/JSON/XLSX，已真实查询到非空数据 |
| 会话、消息、画像、成绩、规划状态 | 隔离 MySQL；按用户、租户与会话校验访问 |
| WS 事件、票据与重放 | 隔离 Redis；身份取自服务端签发票据 |
| 招生候选源、成绩补录所需的招生数据 | 高途接口，或已存在的本地 ORIGINAL 文件/OSS |
| 前端省份政策和批次接口 | 配置的 outer API；默认隔离环境没有接通真实高途源 |

可登录和可创建空会话不代表已经有真实招生数据。隔离配置禁用了高途和 OSS；没有受控数据源时，
成绩补录、源数据刷新和实时招生事实不能记为通过。合成 ORIGINAL 数据只能验证指定测试会话的
数据处理流程，不能证明真实招生数据或推荐质量。

可复用的合成源 API/SQL 验收入口见 [synthetic-source-chain.md](synthetic-source-chain.md)。

实际合成会话验证已生成 12 个候选、10 个选中项和 10 个排序项，API 与 SQL 独立回读一致。
会话 3 还通过真实 Gateway 的排序预览、确认写入和重复确认测试：预览不写方案，确认后
规划版本从 5 到 7，10 个志愿保持唯一，重复确认和整栈重启后再确认都没有第二次业务写入。
随后真实浏览器点击确认将版本从 7 推进到 9；刷新后已生效卡片和实际变更数量可恢复，强制断开业务 WebSocket 后新连接可继续收到心跳和业务响应，重复确认没有第二次写入。浏览器使用本机受限代理保留公网 Origin，不代表独立外网可达。
这些数据均为合成样例，不能用于真实填报。
但有成绩且尚无规划状态的冷加载会先尝试 OSS FINAL/TEMP，失败后才读取本地 ORIGINAL。
本地配置必须显式设置 `ali.oss.enabled: false`；这时 OSS 客户端不初始化，上述下载尝试
立即返回失败，不发远程请求，仍保留本地 ORIGINAL 回退。

旧 OSS 对象 key 为 `session_volunteer/{sessionId}{suffix}.json`，不含环境或租户前缀。
隔离库的会话 ID 可能与其他环境重复。本地生成配置保持 `ali.oss.enabled: false`；
当前私有 `.local/codex-local/application-codex-local.yml` 已补上该项并重启 Java；其他旧环境
也须更新后重启。若另行启用 OSS，启动预检要求显式声明 `ali.oss.enabled: true`、
`ali.oss.namespace: codex-local`（可附加环境后缀）和 bucket。开启 namespace 后所有远程对象 key 前置
`codex-local/`，不会回退读取旧的无前缀 key。生产未配置 namespace 时沿用原有 key；
不要将本地测试指向生产 bucket。

多人使用同一个 `codex-test` 就会共享该账户的会话，这是共享身份的结果。用 `--name codex-test-<姓名或用途>`
创建独立账户；后缀使用小写英文字母、数字或连字符。各账户使用不同随机密码和私有凭据文件，
例如 `.local/codex-local/test-account-codex-test-qa.json`，重复准备不改变身份和密码。
跨用户隔离测试须使用不同账户；跨租户测试还须使用不同租户。验收应包括本人读写成功、他人和跨租户请求被拒绝、
被拒绝后数据库内容不变，以及未带 sessionId 的消息分页不能扩大为全库查询。

管理员建号接口和此脚本的首次建号都使用 InnoDB `REPEATABLE_READ` 事务，先按用户名执行
索引锁定查询，再在同一事务创建用户与凭据。真实 8 路同名请求复验结果为 1 个成功、7 个业务
`409`，只留下 1 个用户和 1 条凭据，无孤儿行；临时并发测试账户已清理。数据库尚无用户名唯一约束，
绕过这一事务协议的直接写入仍可能制造重复账户，不能把此修复理解为全库唯一性保证。

最新 Java 已支持从同租户、同会话、同 pending 与 operation 的成功命令回执重建已生效卡片，
包括实际新增、删除和调整顺序的数量；不会从预览推测执行结果。实时回执过大时只推送有界摘要，
详细数据通过受鉴权的 REST 接口回读。

公网临时测试入口见 [public-ip-test-access.md](public-ip-test-access.md)。服务器代理已准备，
云安全组入站 TCP 3201 和外部网络访问仍须单独确认。HTTP 临时入口使用合成测试账户。
