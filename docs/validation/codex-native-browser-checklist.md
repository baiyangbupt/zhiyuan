# 人工浏览器基线清单（Task C3）

> 这是给**人**在浏览器里执行的清单 ✓（本机当前无浏览器驱动 ✗，见环境基线第四节 ✓）。
> 每一步都写**要记什么** ✓：记不下证据的步骤等于没做 ✓。
> **禁止记录**原始 token / ticket / cookie ✗（记路径与状态码就够 ✓）。

## A. 本地回环（`CODEX_LOCAL_ACCESS_MODE=local` ✓）

前置 ✓：隔离栈已起（`bash scripts/codex-local-infra.sh start` ✓ →
`preflight` ✓ → `start-codex-local.sh` ✓），`seed-codex-acceptance.py --apply` 已建合成数据 ✓。

1. 打开 `http://127.0.0.1:3201/` 与**实际的 sessionDetailV2 路由** ✓。
   **记**：页面路径 ✓、HTTP 状态 ✓（注意 `basePath` ✓——本地栈若是 `production` 轮廓，
   应用在 `/assistant-pc/...` ✓，`/` 本来就会 404 ✓，那不是故障 ✗）。
2. 用**合成账户**登录 ✓（两个 tenant 各试一次 ✓，确认**非 tenant1** 的用例也能走 ✓）。
   **记**：登录后落到哪个路由 ✓、是否出现租户串号 ✗。
3. 完成**一条历史查询** ✓。
   **记**：页面路径 ✓、Network 里每个请求的**路径与目标**（host:port ✓）、
   WebSocket handshake 的 URL ✓ 与**是否 101** ✓、第一条进度事件 ✓、最终消息 ✓、
   workspace API 的路径与状态码 ✓。
   **别记**：原始 token / ticket / cookie 值 ✗。
4. 打开 `docs/validation/codex-native-environment.md` ✓，把这轮的版本/端口/开关**对着核一遍** ✓
   （有出入就更新它 ✓）。

## B. 公开测试域（`CODEX_LOCAL_ACCESS_MODE=public-test` ✓）

前置 ✓：本地那轮通过 ✓、用该 run 的 stop 脚本停掉 ✓（**保留隔离数据** ✓）✓、
DNS/TLS 已确认可用 ✓（环境基线第三节当前标了阻塞 ✗）。
以 `CODEX_LOCAL_PUBLIC_ORIGIN=https://test-wwww.gaotuzhiyuan.com` +
`CODEX_LOCAL_OUTER_API_BASE_URL=<受控测试源>` 重启 ✓。

5. **只用 HTTPS origin** 重新登录/取票 ✓（不再用 loopback 页面 ✓）。
   **记**：页面 URL ✓、票的来源路径 ✓、WS 是否 101 ✓。
6. **不得跨 Origin 复用票据** ✗：把上一轮 loopback 的票拿去公网域用 ✓，
   **记**：被拒的表现（状态码/关闭码 ✓）✓。
7. **DNS/TLS** ✓：`getent hosts test-wwww.gaotuzhiyuan.com` ✓、
   `curl --fail --head https://test-wwww.gaotuzhiyuan.com/` ✓、
   证书 SAN 与实际域名一致 ✓。
   **记**：三条的原始输出 ✓。**HTTP 成功不证明 WS 升级成功** ✗——必须在浏览器里再取一次票看到 101 ✓。
8. 从**另一台设备/网络**打开该 HTTPS 域名 ✓。
   **记**：Network 里**有没有** `localhost`、`ws://`、旧 test-www、production API、inner endpoint ✗
   （有任何一个就是失败 ✓）；公开的 `/inner/...` 返回拒绝 ✓；静态资源/HMR 在 dev 下可用 ✓。
   若确需匿名字典路径 ✓，逐个 exact 放行后**重跑本步** ✓。

## C. 收尾 ✓

9. 用 `scripts/smoke-codex-public.sh --origin https://<host> --base-path /` ✓ 复核一遍 ✓
   （无票据时它会如实写 `authenticated=not_run` ✓，别当成通过 ✗）。
10. 把 A/B 两轮的记录写进基线报告 ✓：四服务版本与端口 ✓、代理路径 ✓、
    数据实例标识（**无凭证** ✓）、浏览器版本 ✓、功能开关 ✓、**实际验证了哪几项** ✓。
    没做成的写**具体阻塞项** ✗，不要用"本地 curl 通过"代替公网通过 ✗。
