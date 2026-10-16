# 发布就绪收口交接（2026-10-16）

## 范围与边界

沿用基线 `7b6a0a4` 和第一批架构加固工作区，本批完成用户确认的脚本鉴权迁移与类型/测试门禁修复。没有提交、创建分支、部署、重启服务、修改实际密钥、执行真实资产采集或对话回放，也没有写共享数据库。

原有 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/` 保留；前端检查关闭增量输出，Node 22 容器使用项目只读挂载、无网络和临时 npm 缓存。

## 修复内容

1. 三个资产采集、能力验证、本地回放脚本共用 `scripts/internal_http.py`。内部路径带服务凭证，公共取票仍只用登录凭证；禁止调用者覆盖服务头、重定向和非 2xx。SSH 只在参数中出现固定 `curl -q --config -`，URL、JSON、凭证经 stdin 配置发送，兼容 curl 7.29。缺省/空白/控制字符凭证在输出目录、资产读写和回放之前本地拒绝。离线能力验证模式不要求凭证。
2. 敏感响应错误统一为不含正文/底层 stderr 的异常，抹去敏感异常上下文，解析 JSON 后检查转义凭证回显，避免写入采集产物。复审另复现并修复两项兼容问题：curl 7.29 不接受浮点 `max-time`，改为校验后向上取整；HTTP 错误转成 RuntimeError 后，回放 setup/first/confirm 阶段全部捕获，双案例失败仍生成完整 blocked 报告。
3. 24 条 TypeScript 诊断清零：补成绩表单 props、分离仅含 form 的引用契约；个人中心使用真实用户/科目类型，移除未使用的重复 payload 构造及未消费的策略数组写入；Header 处理异步空用户；补缺失的 SaaS 存储读取，登录凭证在源头收紧为字符串。未给既有公共 API 全面改型，以免扩散到其他旧页面。
4. `npm run typecheck` 不写增量缓存；`npm run test:unit` 覆盖工具和消息组件。Next 的 `ignoreBuildErrors` 改为 false；ESLint 构建豁免仍保留，不能宣称完整 lint 门禁已恢复。
5. npm/yarn 的 webpack-sources 统一为本机已安装且已有缓存的 `3.6.0`，满足 webpack `^3.5.1`。缓存 tarball SHA512 验证一致，npm 虚拟图 822 节点、0 无效边；没有借机同步两份锁里其他既有版本差异。
6. 修复三条流式事件断言：进度必须在终态闸门打开之前到达，但不要求早于 assistant delta；原生连接显式验证 `turn.started` 后接业务进度/澄清卡。身份、内容、敏感参数和答案回传断言保留。
7. 私有志愿夹具不再混入纯单元断言；样例的数值来源契约仍检查。质量 gate 自动在任何执行命令前预检显式克隆文件，缺失/无效退出 2，即使 `--no-stop-on-failure` 也不能绕过。支持独立 `--check-fixtures` 和与 runner 一致的目录参数/环境变量；不造假数据，不把预检当成真实动作验证。

## 验证证据

- RED：脚本首次 45 failed / 2 passed；入口前置检查 3 failed；敏感异常和转义回显 3 failed；复审兼容用例 9 failed / 52 passed。最终脚本与夹具定向合计 94 passed。日志 `/tmp/zhiyuan-readiness-{scripts-red,entrypoints-red,sensitive-red,review-red,targeted-final}.log`。
- TypeScript 原样重现 24 条错误；修复后在 Node 22.22.3 执行 `npm run typecheck` 退出 0。新工具/门禁用例先红后绿，Node 22 `npm run test:unit`：187 passed，0 failed/skipped。日志 `/tmp/zhiyuan-readiness-web-node22.log`。
- 流式集成先原样复现 3 failed / 13 passed；修改后连同原生/兼容、鉴权、组合、影子、证据、请求上下文和 8 条真实 curl/urllib 临时回环传输验证进行扩展回归：69 passed、1 skipped、3 warnings，8.02 秒。最终输出见 `/tmp/zhiyuan-readiness-integration-final.log`。
- 全量离线 Python 单元：2461 passed、33 deselected、20 warnings，56.56 秒。使用仅放行测试自身监听端口、每例 20 秒超时的包装器；不再排除缺夹具单测，只有标记为 e2e 的 33 条未选中。最终输出见 `/tmp/zhiyuan-readiness-unit-final.log`。
- `git diff --check`、三份运维脚本 Bash 语法检查通过；缓存包 integrity 及 npm 虚拟图检查通过，日志 `/tmp/zhiyuan-readiness-lock-validation.log`。
- 本批未修改 Java 代码，不把第一批 Java/Redis 验证记录冒充本轮新跑结果。

## 独立复审

- 前端只读复审未发现本轮引入的可复现高/中风险；另外做了三种选科及非 C 端保存 payload 的内存前后对照，确认与 Java `value/name/isFirst/subjectType` 契约及旧行为一致。
- 脚本只读复审发现上述 curl 超时和回放异常报告两项中风险，已先补红灯回归再修复。复审者独立只读复跑 8 条超时/双案例异常测试通过，确认两项关闭，限定范围未发现剩余可复现高/中风险。

## 仍然需要完成

- `--check-fixtures --mode final-action` 在当前工作区明确退出 2，报告 94 条缺失引用。需要授权的脱敏夹具，且数据目录与隔离 Java 后端一致。详见 `zhiyuan-agent/docs/dialog-fixture-preflight.md`。预检只保证显式来源 JSON 可读，不证明业务状态正确。
- 固定 Codex App Server 二进制未安装对应测试仍跳过；原 Pydantic 废弃警告保留。
- 尚未运行完整 Next 生产构建、浏览器整站登录/保存、真实模型或写入式 E2E，不宣称具备完整上线验收证据。
- 仍需单独发布授权窗口：协调 Java/Agent/MCP/运维同一服务凭证、最终后端地址及 Redis；先迁移调用方，再启用严格鉴权服务端；验收跨用户拒绝、断线恢复与动作确认。
- 会话生命周期、持久 artifact 账本和分布式归属/串行调度仍属下一批架构工作；完成前保持单 worker。
