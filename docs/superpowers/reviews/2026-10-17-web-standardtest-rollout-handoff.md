# 3001 Web 生产构建与单实例发布交接

日期：2026-10-17。用户已授权重新构建并切换本地 3001 Web，不整体重启系统。

## 结果

- Web 源码快照：`11a8abb4af43b30930c41890a5bc1dd29197f537`，包含 Markdown 消毒、严格类型门禁、工具进度合并及终态成绩卡修复。
- 发布期间另有工作线推进至 `dfb0006`；与快照相比没有 Web 文件变化。本轮没有提交或部署该 Gateway 改动，也没有重启 Agent。
- 新 buildId：`82HqWQHXcNoPnX78GbRH5`；旧 buildId：`LznUVyKZVJ9zg_ESdO1yk`。
- 2026-10-17 19:51:08 +08:00，3001 已切换到新产物；19:52:57 +08:00 再次验证通过。
- 新运行容器：`zhiyuan-web-standardtest-20261017`，Node `22.22.3`，只读根文件系统，2 CPU / 2 GiB，重启策略 `unless-stopped`。监听 3001 的进程从 10117 变为 22430；容器主进程为 22412。
- `typescript.ignoreBuildErrors=false`，没有跳过类型检查；保留既有构建时 lint 豁免，不宣称 lint 通过。生产静态目录没有残留 `.map` 文件。

## 产物与配置

独立发布目录：`.runtime/web-releases/20261017-1830-be9e206`。目录名是准备批次标识，实际源码修订以 `release-manifest.json` 的 `revision=11a8abb…` 为准。

- `workspace/` 由已提交 Web 源码归档生成，排除原 `.env*`、增量缓存和运行中构建；随后只生成本批需要的 `.env.prod`。
- 构建配置沿用 3001 旧产物的公开配置，不迁移到另一套后端：Java 仍为 `127.0.0.1:18090`，Agent 仍为 `127.0.0.1:18091`，outer 仍为 `https://test-www.gaotuzhiyuan.com`。
- 3201 继续作为原开发实例，18290/18291 继续原演示栈；本批没有把 3001 误接到 18290/18291。
- 构建和浏览器验收使用已有镜像 `zhiyuan-e2e-playwright:1.55.0`，显式只读挂载宿主已有 Node `22.22.3` 和项目 `node_modules`，未下载或修改依赖。
- 原 `zhiyuan-web/.next` 保留原样，**不再是当前 3001 的运行产物**。今后核对 3001 版本应检查实际页面 buildId 和本发布目录，不应再仅凭原目录 BUILD_ID 判断旧代码仍在运行。
- 容器从独立快照的 `/workspace` 运行；日志由 Docker 保存，缓存和临时文件使用专用 tmpfs，不覆盖原 `.next` 或 3201 的 `.next-dev`。

## 验证证据

所有证据位于发布目录下 `evidence/`：

1. `build-and-tests-node22.log`：Node `22.22.3`，类型检查退出 0；**190 tests、190 passed、0 failed、0 skipped**；完整 `build:prod` 退出 0，9/9 静态页、构建追踪及 source-map 后处理完成。
2. `browser-report.json`、`browser-smoke.log`：断网容器内实际生产产物 **9 checks passed**。覆盖登录页水合、助手/用户 Markdown 消毒、流式终态、确认卡只发一个带身份/版本的动作、迟到状态不复活旧卡、旧版历史、移动端取消及布局、代表性内网路径封堵、无页面异常/坏静态资源/未配置接口。
3. `stage-http.json`：临时 `127.0.0.1:3181` 上 **26 passed、0 failed**。
4. `live-http-cutover.json`：切换后 3001 上 **26 passed、0 failed**。
5. `live-http-final.json`：切换后再次核对 **26 passed、0 failed**。包括实际返回的新 buildId、登录页所有发现的 JS/CSS 资源、根路径与 `/assistant-pc` 路径的代表性 inner/admin/debug/evidence 封堵，以及原 Agent 代理健康检查。
6. `listeners-before-cutover.txt`、`listeners-after-cutover.txt`：本轮切换前后，18090=22566、18091=27507、18290=15304、18291=17262、3201=31139，排序服务 PID 也不变；只替换 3001，并关闭本轮临时 3181。
7. `cutover-result.json`、`live-container.log`、`stage-container.log`：发布结果及运行日志。

首轮误用了镜像自带 Node `20.20.2`，类型检查通过，但测试 runner 在 `codexLocalRewrite.test.mjs` 报 `Unable to deserialize cloned data due to invalid or unsupported version`，188 passed、1 failed；因此没有继续构建或切换。随后显式挂载项目要求的 Node 22 并完整重跑，通过 190 项；没有删除用例、修改业务代码或放宽门禁。原失败日志保留为 `build-and-tests.log`。

构建仍有既有 sharp 可选依赖、旧 caniuse 数据及 customerDetail CSS end 兼容告警；未在本批修改依赖或样式。磁盘剩余约 4.3 GiB（89% 已用），未执行清理。

## 运维入口与回滚

当前实例已由 Docker 管理。不要使用会启动开发模式的通用 `scripts/start.sh web` 来替代本实例，也不要直接覆盖当前发布目录重新构建。

查看当前日志和重启同一产物：

```bash
docker logs --tail 100 zhiyuan-web-standardtest-20261017
docker restart zhiyuan-web-standardtest-20261017
```

复验当前发布：

```bash
zhiyuan-agent/.venv/bin/python \
  .runtime/web-releases/20261017-1830-be9e206/release-control.py probe
```

需要明确回滚时，从仓库根执行：

```bash
zhiyuan-agent/.venv/bin/python \
  .runtime/web-releases/20261017-1830-be9e206/release-control.py rollback
```

回滚控制器会停止本批 3001 容器，使用受限权限保存的原启动信息和原构建恢复旧实例，并检查旧 buildId。`rollback-private.json` 权限 0600，含完整启动环境，**不得打印、提交或复制到公开报告**。本轮未触发实际回滚，也未为演练制造停机；切换代码具备失败自动恢复路径，不将其表述为已做完整回滚演练。

运行所需的发布目录、原构建、只读依赖目录、Node 22 目录和 Docker 镜像须保留；不自动删除任何一项。

## 边界

- 本轮只读 HTTP 和合成接口/WS 浏览器测试不证明真实模型、合法跨用户拒绝、线程重连、确认幂等或数据库写入正确。
- 没有真实登录、调用付费模型、操作已有用户会话、修改业务数据库/Redis、变更凭证或 Nginx。
- 未复验公网入口，不把本机 3001 的结果扩大为公网代理全链路通过。
- 94 条缺失夹具引用及此前列明的隔离写入验收仍未解决；不得为凑绿灯伪造夹具。
- 保留其他工作线的未提交文件；本轮没有新增业务代码变更。
