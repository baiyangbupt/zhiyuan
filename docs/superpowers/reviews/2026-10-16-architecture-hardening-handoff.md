# 高考志愿系统架构加固交接（2026-10-16）

> 本文保留第一批完成时的证据；同日第二批已补齐三个脚本鉴权、清零 24 个类型错误、修复 webpack-sources 锁边及流式测试，并将私有数据要求移入不可绕过的执行前置预检。最新状态见 `2026-10-16-release-readiness-handoff.md`；部署及深层架构风险仍未宣称完成。

## 交付范围

本批针对已经复现的问题修复，不替换现有规划架构，不改变已批准的自动预填方案行为。基线为 `7b6a0a4`；保留并行工作和原有 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/`。

所有改动仅在工作区：未提交、未发布、未重启已有服务、未修改线上或共享测试数据库、未修改实际密钥配置。上线前必须完成下文配置协调。

| 问题 | 本批处理 |
| --- | --- |
| WebSocket 握手成功后仍信任报文身份 | 原生、兼容、旧入口以及中断、转述、澄清控制消息统一绑定票据身份；检查 camelCase 和 snake_case 别名。跨租户/会话/用户或缺少可信身份以 4403 拒绝；缺失报文字段只从票据补齐。 |
| Markdown 可执行 HTML | 两处消息 HTML 渲染使用同一 `sanitize-html` 白名单；保留普通文字、表格、代码、安全链接，移除脚本、事件属性和危险协议。 |
| 未知录取率和小数间隙落入最安全档 | 空值、非有限值、越界值进入“未知”，在排序/自动选取前排除；九档/三档范围连续，真实 0% 仍属于“冲”，不是“保”。 |
| 请求忙碌后重试被错误去重、重复请求静默消失 | 运行时接入 Redis；按会话串行准入，忙碌拒绝不占号；按内容/动作摘要判重，重复回包明确原回合与恢复状态。 |
| 后台回合被后续报文覆盖 | 固定后台任务的内容、回合和事件发射上下文；兼容入口进度也固定原回合号。 |
| 动作收据早于真正执行结束 | 动作仍独立于可中断推理回合，但收据跟随真实执行/终态结果；返回的失败、中断以及被路由捕获的异常不会再写成完成。 |
| 内部、管理、调试、证据接口依赖网络隔离 | 独立服务凭证拦截器，真实 HTTP 401/403；Agent/MCP/运维探针传递同一凭证，拒绝缺省凭证、覆盖凭证和携带凭证跟随重定向。 |
| 默认后端指向生产、回合缓存无上限 | 缺省后端改为本机 8090；完成回合的结果与摘要共用有界 FIFO 条目，默认 1024 条/3600 秒。 |

## 请求恢复契约

- `clientRequestId` 是请求标识，`turnId` 是界面回合标识，二者不再混作内容摘要。生产入口显式计算规范 JSON 的 SHA-256 摘要。
- 活动回合期间的不同请求返回 busy，不写请求占位；相同请求/内容返回 duplicate，相同请求/不同内容返回 conflict。准入锁在最后一个持有者/等待者退出后回收。
- 收据保存 `running`、`completed`、`failed` 或 `interrupted` 及原始回合号。独立动作执行期间保持 running，不占推理回合位，也不被普通 `cancel_all()` 误取消。
- 进程重启后没有本地工作任务的 running 收据，以及占位成功但没有收据的请求，返回 `recovery_required`，不擅自再次执行。应重放事件或重建权威状态，并查询 Java 操作结果。
- 收据是执行状态/原回合引用，不是完整回答副本，更不是数据库事务提交证明。Java 操作幂等与权威规划状态仍负责最终业务结果。
- Redis 完成收据和请求占位的保留期原子续期；不产生没有请求占位的孤立收据。默认窗口为 24 小时；窗口外不承诺去重。
- 必须显式配置 `CODEX_EVENT_STORE_REDIS_URL` 才有跨进程重启的准入/重放保证。未配置时保留旧部署兼容行为，但不可声称具备持久幂等。
- 仍限定一个 Gateway worker。Redis 请求占位不等于分布式会话锁；多 worker、多实例和长时间跨窗口执行需要独立的 ownership/fencing 设计。

## 验证证据

先增加失败用例再修复；原始身份越权、危险 HTML、概率边界、忙碌占号、收据提前完成和旧 curl 探针问题均有 RED/GREEN 证据。内部鉴权和探针的完整命令、日志及边界见 `2026-10-16-internal-auth-rollout.md`。

- Python 单元回归：2382 passed、34 deselected、20 warnings，56.42 秒；使用禁止外部连接、仅放行测试自身临时监听端口的离线包装器，不运行 `e2e`，单条超时 20 秒。34 个未选中项包含 33 个 `e2e` 和下述缺少数据夹具的基线检查，不计作通过。日志：`/tmp/zhiyuan-hardening-unit-verified.log`。
- 网关鉴权/组合/影子模式/证据/请求上下文集成：45 passed、1 skipped；skip 为未安装固定 Codex App Server 二进制，不计作通过。
- 真实 Redis：18 passed；现有 Redis 镜像的临时容器使用 `--network none`、Unix socket、不持久化，测试结束关闭，不连接共享 Redis。
- Java：76 passed、0 failures/errors/skips；离线 Maven，11 个相关测试类，包含 33 个真实拦截器链的 standalone MockMvc 鉴权用例，不启动 Spring Boot 或数据库。
- Web：Node 22.22.3 下 `node --test src/utils/*.test.mjs`，118 passed；浏览器目标 webpack 打包/调用通过；无网络 Chromium 实际插入清洗后 HTML，未执行恶意载荷，表格和安全链接保留。
- TypeScript：`tsc --noEmit --incremental false --pretty false` 仍有 24 个错误；对临时解压的基线执行同一命令，诊断逐字相同，没有本次新增错误。未改动用户已有增量缓存。
- npm lockfile 虚拟依赖检查：本批 sanitizer 新依赖有效。唯一无效边 `webpack -> webpack-sources` 在基线同样存在（要求 `^3.5.1`，原锁为 `3.3.4`），保留并单独记录，没有借本次安装升级无关依赖。
- 未执行整站 Next 生产构建或真实业务 E2E，避免写运行中的构建目录或接触付费模型/共享业务数据；浏览器验证是隔离的消息渲染检查，不代表整站验收。

可复验的常规命令（各自目录执行；需要允许测试自建本机端口）：

```bash
# zhiyuan-agent；独立离线环境，显式限制网络，不连接已运行的业务服务
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/unit -m 'not e2e' -q -p no:cacheprovider --deselect=tests/unit/test_dialog_quality_gate.py::test_final_action_explicit_clone_sources_have_volunteer_fixture
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_gateway_access.py tests/integration/test_gateway_composition.py tests/integration/test_shadow_gateway.py tests/integration/test_evidence_roundtrip.py tests/integration/test_request_context_integration.py -q -p no:cacheprovider
# 在临时隔离 Redis 上设置 CODEX_TEST_REDIS_URL，再执行 test_conversation_replay.py

# zhiyuan-server
mvn -o -q -Dtest=InternalServiceAuthMvcTest,LoginInterceptorTest,OpsHealthControllerTest,CatalogControllerTest,CodexConversationControllerTest,PlanningFacadeControllerTest,IntegrationSessionControllerTest,UserAdminControllerTest,VolunteerIntervalServiceTest,VolunteerUnknownExclusionTest,RankRequestMappingTest test

# zhiyuan-web；使用项目要求的 Node 22，而不是本机缺省 Node 20
node --test src/utils/*.test.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false --pretty false
```

### 仍然失败的基线检查

下列问题在临时解压的 `7b6a0a4` 上分别重现，未掩盖为通过、未修改无关业务逻辑：

1. `test_final_action_explicit_clone_sources_have_volunteer_fixture`：现有对话回归样例引用的本地 `session_volunteer_*.json` 数据文件缺失，检查返回 94 条引用缺失。
2. `test_gateway_live_events.py` 三条首帧断言：一条要求 tool progress 早于现有 assistant delta；两条 native 场景要求业务进度/澄清卡恰为第一帧，但现有实现先发送 `turn.started`。其余 13 条在离线检查中通过。
3. 前述 TypeScript 24 个基线错误和 lockfile 原有 webpack 依赖边。

测试中原来使用与报文不同身份的“无条件放行”替身已调整为每例显式签发匹配身份，没有放松生产身份校验。

## 上线前必须协调

1. 通过密钥管理给 Java、Agent、Codex/MCP 子进程和可信探针配置相同非空 `INTERNAL_SERVICE_TOKEN`；Java 也支持 `internal.service.token`。禁止放进浏览器、Git、命令参数或共享日志。
2. 显式指定可信的最终 `INTERNAL_SERVICE_URL`，禁止依赖缺省地址来选择共享环境。客户端先发新头可兼容旧服务端；新服务端一旦启用就拒绝旧客户端。空凭证是 fail-closed 故障，不是回退开关。
3. 盘点所有直连内部 API 的调用方。三个生产资产/回放类一次性脚本本批未迁移，鉴权启用后会收到 401；准确路径与迁移纪律见内部鉴权交接文档。不得为这些脚本重新开放匿名内部接口。
4. 认证探针兼容本机 curl 7.29/Bash 4.2：凭证经转义后的 stdin 配置发送，禁止重定向、关闭 TLS 校验或把受认证响应落盘。内部健康地址必须直接返回 2xx。
5. 在独立授权窗口部署并验收跨用户拒绝、真实页面渲染、断线重放和动作确认；本批没有代为上线。

## 明确保留的架构风险

- 会话级锁、线程绑定、快照、待确认状态等仍是进程内结构，生命周期回收和多实例调度未完成。回合缓存有界不等于整个进程内存已全面有界。
- MCP artifact 签发/验证的持久账本迁移未完成，重启独立验证能力仍有限；不擅自删除审批相关记录来“解决”内存问题。
- 地理名称到规范地域 ID 的迁移、大服务拆分、完整类型与 lint 门禁恢复另行实施。Next 仍忽略构建时类型/lint 错误，本批未用开关掩盖这些既有债务。
- 自动预填方案行为未变更；读写分离和产品状态契约应单独确认，不能把行为变更夹进安全加固。
