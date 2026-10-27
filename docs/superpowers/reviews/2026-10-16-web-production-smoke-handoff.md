# Web 隔离生产构建与浏览器烟测交接

## 范围与结论

- 验收修订：`bedc026`，包含本轮之前的五批本地提交；未推送、未部署。
- 完整 `npm run build:prod` 退出码为 0，包括严格类型检查、生产编译、9/9 静态页面生成、构建追踪及 `source-map.js` 后处理；`.next/static` 未留下 `.map` 文件。
- 在上述实际生产产物上启动 `next start`，Chromium 烟测最终 **9 checks passed，退出码 0**。最终报告的 pageErrors、consoleErrors、staticFailures、unknownApiRequests、blockedExternalRequests 均为空。
- 本轮未修改业务代码、依赖或生产配置，仅新增此验收记录。生产构建与烟测通过不等于真实登录、模型调用、方案写入或整站业务验收通过。

## 隔离约束

- 通过 `git archive HEAD` 将已提交 Web 源码、静态资源、Next/TypeScript 配置、包清单及后处理脚本复制至 `/tmp/zhiyuan-web-acceptance.BE85F5/work`。不复制任何真实 `.env*`、现有 `.next*`、增量缓存或登录态。
- 临时 `.env.prod` 仅含合成值：`APP_ENV=production`，API/外部站点指向容器内 `127.0.0.1:9`，WebSocket override 同样指向容器内关闭端口。不传入服务凭证、真实用户 token、数据库或模型配置。
- 使用已有镜像 `zhiyuan-e2e-playwright:1.55.0`、Node `22.22.3`、已安装只读 `node_modules`；不下载依赖、不重新安装。Next 版本为 `13.5.11`。
- 两阶段均使用 `--network none --read-only`，不映射宿主端口；构建只写临时快照，烟测阶段快照只读，浏览器产物只写临时 evidence 目录。
- 构建限制 2 CPU / 3 GiB，`CIRCLE_NODE_TOTAL=2`、`RAYON_NUM_THREADS=2`；烟测限制 2 CPU / 2 GiB。保留严格类型检查与原构建配置，不为验收放宽门禁。
- 临时 Next 服务只监听容器内 `127.0.0.1:3177`，脚本结束时关闭；未操作现有前端、18290/18291 服务或共享 Redis。

## 浏览器覆盖

1. 生产 `/assistant-pc/login` 返回 200，页面水合、标题及登录内容可见；未提交登录表单。
2. V2 历史助手消息和用户消息都经过真实 Markdown 渲染：恶意 script/img/svg、事件处理器及 javascript 链接被剔除，普通加粗、表格和安全链接保留，执行探针保持 false。
3. WebSocket 流式 JSON 碎片只显示可读 message 文本，终态用一份权威答案替换；终态中的 HTML 按文本呈现，不创建可执行图片。
4. 成绩更新预览展示省份、选科、年份、学科、总分和位次；点击后进入确认中、按钮锁定，仅发出一条包含 tenant/bot/session、proposalRef 及 expectedSourceVersion 的确认帧。模拟 applied 后移除按钮，迟到 applying 已确认经过前端事件处理且不回退已生效状态。
5. 模拟 stale_state 后显示重新确认指引，旧卡不再出现确认或取消按钮。
6. 生产旧版会话路由仍可渲染经过过滤的历史消息。
7. 390×844 移动端显示历史与确认卡，取消动作进入等待态，再按模拟结果显示已放弃；根文档未出现横向溢出。
8. 直连本次 Next 服务的三个带 `/assistant-pc` 前缀的内部路径返回 404。仅证明该 middleware 路径，不代表外部 Nginx、根路径转发或后端鉴权已联合验收。
9. 上述页面无运行时异常、console error、失败 JS/CSS 资源或未配置的接口请求。

HTTP 接口和 WebSocket 事件均为显式合成夹具，未知业务接口返回失败并纳入最终断言，不使用通配成功响应。页面自动请求的空档案 initial-plan 接口也由夹具返回业务 404；没有真正生成方案。确认/取消事件由测试脚本模拟，不证明 Java 命令执行、数据库事务或模型输出正确。

## 证据与复验入口

临时验收目录为 `/tmp/zhiyuan-web-acceptance.BE85F5`，非发布产物，不保证跨机器或清理 `/tmp` 后保留。

- 生产构建完整日志：`evidence/production-build.log`。
- 最终浏览器日志：`evidence/browser-smoke.log`；结构化报告：`evidence/browser-report.json`；服务日志：`evidence/next-start.log`。
- 临时浏览器驱动：`browser-smoke.cjs`，由 Node 加载实际项目 Playwright，在同一断网容器内启动和关闭生产服务。
- 截图：`evidence/login.png`、`evidence/v2-history.png`、`evidence/v2-confirmed.png`、`evidence/legacy-history.png`、`evidence/v2-mobile.png`。已检查桌面历史、桌面确认结果和移动端截图。
- 初轮测试脚手架失败记录另存为 `browser-report-initial.json`、`browser-report-instrumentation.json`、`browser-report-mobile-selector.json`：分别校正生产环境剔除 data-testid、Playwright 模拟 WebSocket 的观测方式，以及 Ant Design 双汉字按钮空格/旧版列表夹具。未通过修改业务代码或关闭编译优化来取得绿灯。

本次实际执行入口，分别在断网容器内的临时快照目录运行：

```bash
export PATH=/opt/node/bin:$PATH
npm --cache /tmp/npm-cache run build:prod
timeout 180s node_modules/.bin/env-cmd -f .env.prod node /runner/browser-smoke.cjs
```

复验必须沿用隔离快照、合成环境文件、只读依赖和浏览器缓存挂载；`/runner/browser-smoke.cjs` 映射自上述临时驱动，`/evidence` 映射至上述临时 evidence 目录。不要把这些命令直接改为当前运行目录的构建或既有真实栈 E2E。

## 非阻断告警与剩余门槛

- 构建保留现有 ESLint 豁免，未宣称 lint 通过；可选 sharp 提示、旧 caniuse 数据、customerDetail 的 CSS `end` 兼容提示，以及对应 webpack warning 序列化提示仍在，未顺手升级依赖或修改无关样式。
- 产物统计：共享 First Load JS 约 528 kB，V2 约 765 kB。记录为后续体积优化观察项，本轮没有网络时延或真实性能基准，不据此判断性能达标。
- 缺少的 94 条私有夹具引用、固定 Codex 二进制、真实模型/写入式业务 E2E，以及内部服务鉴权和代理的协调升级/回滚验收仍未解决。
- 本轮未重跑 Python/Java 回归，不将前一轮测试计数冒充本轮结果。安全会话回收、多 worker 所有权/fencing 等后续架构工作也没有在本轮展开。
- 原有 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/` 保持未提交，不清理、不覆盖。
