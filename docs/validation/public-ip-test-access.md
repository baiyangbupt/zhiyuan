# 临时公网 IP 测试入口

显式选择 `public-ip-test` 可通过 HTTP IPv4 地址测试浏览器；原 `public-test` 仍要求 HTTPS origin。

```bash
export CODEX_LOCAL_ACCESS_MODE=public-ip-test
export CODEX_LOCAL_PUBLIC_ORIGIN=http://101.42.252.196:3201
export CODEX_LOCAL_OUTER_API_BASE_URL=https://test-api.example.com
bash scripts/start-codex-local.sh --print-access-env
```

`CODEX_LOCAL_OUTER_API_BASE_URL` 必须换成受控测试 API 源，并显式提供；不得指向入口自身。
预检只输出解析值，不启动服务。访问模式变化后，需要按既有启动流程重新启动或构建 Web，使
`NEXT_PUBLIC_CODEX_ACCESS_MODE` 生效。

该模式清空 WS override，浏览器始终连接当前页面同源的 `ws://101.42.252.196:3201`，
忽略历史遗留的 WS 地址。Agent 的 Origin 白名单仅包含完整的指定 origin，端口也必须一致。
Origin 必须是规范的 `http://IPv4:port`；拒绝回环、零地址、多播、保留地址、越界端口、
前导零，以及凭据、路径、查询参数和 fragment。

监听限制保持原样：Next 继续监听回环；公网入口由独立代理转发 Web、业务 API 门面和
`/ws/chat`。此模式不会放开 Java、Agent、Rank 或内部 API 的直接访问。

代理访问日志不记录查询串；Agent 对 `uvicorn.access` 和 `uvicorn.error` 也在写日志前
移除完整 URL 查询串，保留请求路径，避免 WebSocket 票据进入接受或拒绝连接的日志。
本地真实请求已验证 HTTP 和 WS 脱敏；这一改动不回写历史日志。

本机 Chromium 已通过受限转发代理完成登录、确认、刷新和业务连接重连验证，保留上述公网
Origin。该路径使用私网转发，不能作为独立外网可达的证据；云安全组与公网入站仍须单独验收。
