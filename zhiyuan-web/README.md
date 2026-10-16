# zhiyuan-web

智愿 AI 志愿填报系统前端，基于 Next.js 13 (Pages Router)。

## 技术栈

- Next.js 13 + React 18 + TypeScript
- Ant Design 5
- SCSS Modules
- Axios + WebSocket

## 开发

需要 Node.js >= 22.14.0。

```bash
npm install
npm run dev          # 开发服务器 (端口 3001)
npm run typecheck    # 严格类型检查，不写增量缓存
npm run test:unit    # 无网络工具及消息组件单元测试
npm run build:dev    # 开发环境构建
npm run build:prod   # 生产环境构建
```

Next 构建会阻止 TypeScript 错误，不再忽略类型失败。ESLint 仍沿用已有的构建豁免，尚未恢复完整 lint 门禁，不能用类型检查通过替代 lint 通过。

## 页面路由

| 路由 | 说明 |
|------|------|
| `/login` | 登录（手机号/密码/Token 静默登录） |
| `/customer` | C 端首页，自动跳转最新会话 |
| `/customerDetail` | 5 步信息采集���导 |
| `/session` | B 端会话管理列表 |
| `/sessionDetailV2` | 会话详情：聊天 + 工作区面板 |
| `/userCenter` | 个人中心 |

## 环境配置

通过 `env-cmd` 加载对应 `.env.*` 文件：

| 文件 | 用途 |
|------|------|
| `.env.dev` | 本地开发 (指向 localhost) |
| `.env.test` | 测试环境 |
| `.env.beta` | 灰度环境 |
| `.env.prod` | 生产环境 |

关键变量：
- `NEXT_PUBLIC_API_BASE_URL` — 后端 API 地址
- `NEXT_PUBLIC_AGENT_WS_BASE` — Agent WebSocket 地址

## Docker 部署

```bash
./build-docker-fast.sh <env> <version>   # 构建并推送
./run-docker.sh <env> <version>          # 拉取并运行 (端口 28688)
```
