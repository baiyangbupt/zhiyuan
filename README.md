# 智愿 AI 志愿填报系统

AI 驱动的高考志愿填报辅助系统。学生通过多轮对话与 AI Agent 交互，系统收集个人信息（成绩、选科、意向院校/专业/城市等）后自动生成个性化志愿方案。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户 (Web / 小程序)                        │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    ▼                         ▼
        ┌───────────────────┐    ┌───────────────────────┐
        │   zhiyuan-web     │    │    zhiyuan-agent      │
        │   前端 (Next.js)   │    │  AI Agent (FastAPI)   │
        │   Port: 3000      │    │  Port: 8000           │
        └────────┬──────────┘    └──────────┬────────────┘
                 │                          │
                 │    ┌─────────────────────┤
                 │    │                     │
                 ▼    ▼                     ▼
        ┌───────────────────┐    ┌───────────────────────┐
        │  zhiyuan-server   │    │    zhiyuan-rank       │
        │ 业务后端 (Spring)  │    │  排序服务 (Flask)     │
        │  Port: 8080       │    │  Port: 5001           │
        └────────┬──────────┘    └───────────────────────┘
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
     [MySQL]  [Redis]  [Gaotu API]
```

## 模块说明

| 模块 | 目录 | 技术栈 | 说明 |
|------|------|--------|------|
| 前端 | `zhiyuan-web/` | Next.js 13, React 18, Ant Design 5 | PC 端用户界面，WebSocket 聊天 + 工作区面板 |
| 后端 | `zhiyuan-server/` | Spring Boot 2.3, MyBatis-Plus, MySQL | 业务数据管理、志愿方案状态机、数据查询 API |
| Agent | `zhiyuan-agent/` | FastAPI, Pydantic AI, WebSocket | AI 对话引擎，意向提取，方案编排 |
| 排序 | `zhiyuan-rank/` | Flask, Pandas, NumPy | 志愿排序算法，专业推荐，权重计算 |

## 快速开始

### 前置条件

- Node.js >= 22
- Java 8
- Python >= 3.10
- MySQL 8.0
- Redis 7

### 方式一：Docker Compose (推荐联调)

```bash
# 启动基础设施 + 前端 + Agent + Rank
docker-compose up -d mysql redis zhiyuan-rank zhiyuan-agent zhiyuan-web

# 后端在宿主机运行 (需要本地 MySQL/Redis)
cd zhiyuan-server
mvn spring-boot:run
```

### 方式二：各模块独立启动

```bash
# 1. 启动基础设施
# MySQL: 创建 gaotu_zhiyuan 数据库
# Redis: 默认端口 6379

# 2. 后端
cd zhiyuan-server
mvn spring-boot:run -Dspring-boot.run.profiles=local

# 3. 排序服务
cd zhiyuan-rank
pip install -r requirements.txt
python app.py  # 端口 5001

# 4. Agent
cd zhiyuan-agent
pip install -e .
cp .env.example .env  # 填入 LLM API Key
uvicorn app.server:app --port 8000 --reload

# 5. 前端
cd zhiyuan-web
npm install
npm run dev  # 端口 3001
```

## 服务间通信

| 调用方 | 被调方 | 协议 | 路径前缀 |
|--------|--------|------|----------|
| 前端 → 后端 | HTTP | `/gaotu-assistant-bot/*` |
| 前端 → Agent | WebSocket | `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do` |
| Agent → 后端 | HTTP | `/gaotu-assistant-bot/inner/*` |
| Agent → Rank | HTTP | `/gaokao-volunteer-rank/*` |
| 后端 → Rank | HTTP | `/gaokao-volunteer-rank/*` |
| 后端 → Gaotu平台 | HTTP | 外部 API |

## 环境配置

### 后端 (zhiyuan-server)

Profile 文件：`src/main/resources/application-{profile}.yml`

| Profile | 用途 | 数据库 |
|---------|------|--------|
| `local` | 本地开发 | localhost:3306/sales_bot |
| `test` | 测试环境 | 10.0.8.8:33306/gaotu_zhiyuan |
| `online` | 生产环境 | (配置不入仓) |

### Agent (zhiyuan-agent)

环境变量（`.env` 文件）：

| 变量 | 说明 | 示例 |
|------|------|------|
| `LLM_PROVIDER` | LLM 提供商 | openai / anthropic |
| `LLM_MODEL_NAME` | 模型名 | gpt-4o |
| `LLM_API_KEY` | API Key | sk-xxx |
| `INTERNAL_SERVICE_URL` | 后端地址 | http://localhost:8080 |
| `RANK_SERVICE_URL` | 排序服务地址 | http://localhost:5001 |

## 本地开发脚本

`scripts/` 目录提供了一套本地开发管理脚本：

```bash
# 首次使用：一键初始化环境（安装依赖、编译、初始化数据库）
bash scripts/setup.sh

# 启动全部服务（含 MySQL/Redis）
bash scripts/start-all.sh

# 查看所有服务运行状态
bash scripts/status.sh

# 停止全部服务
bash scripts/stop-all.sh

# 单个服务管理
bash scripts/start.sh <web|server|agent|rank>
bash scripts/stop.sh <web|server|agent|rank>

# 查看日志
bash scripts/logs.sh <web|server|agent|rank>          # 最后 50 行
bash scripts/logs.sh <web|server|agent|rank> --follow  # 实时跟踪
```

服务启动后日志输出到 `logs/` 目录，PID 文件保存在 `.pids/` 目录。

## 部署

各模块均支持 Docker 部署，统一使用 Aliyun Container Registry：

```bash
# 构建并推送 (env: dev/test/prod)
cd zhiyuan-web && ./build-docker-fast.sh prod 1.0.0
cd zhiyuan-agent && ./build-docker.sh prod 1.0.0
cd zhiyuan-rank && ./build-docker-fast.sh prod 1.0.0

# 后端为 JAR 部署
cd zhiyuan-server && mvn package -DskipTests
# 产出: target/zhiyuan-server.jar
```

当前服务器 `zhiyuan.ytell.cn` 的实际部署记录、问题处理和运维命令见：

- [zhiyuan.ytell.cn 部署记录与问题处理](docs/zhiyuan-yttell-deployment-notes.md)

## 目录结构

```
zhiyuan/
├── docker-compose.yml          # 全栈本地联调
├── .gitignore
├── README.md
├── scripts/                    # 本地开发脚本
│   ├── setup.sh                # 一键环境初始化
│   ├── start-all.sh            # 启动全部服务
│   ├── stop-all.sh             # 停止全部服务
│   ├── status.sh               # 查看服务状态
│   ├── start.sh                # 启动单个服务
│   ├── stop.sh                 # 停止单个服务
│   └── logs.sh                 # 查看服务日志
├── zhiyuan-web/                # 前端
│   ├── src/pages/              # Next.js 路由
│   ├── src/pageComponents/     # 页面组件
│   ├── src/hooks/              # WebSocket、Auth 等 Hook
│   ├── src/service/            # API 调用层
│   ├── Dockerfile
│   └── package.json
├── zhiyuan-server/             # 后端
│   ├── src/main/java/com/ytell/zhiyuan/
│   │   ├── web/controller/     # REST API
│   │   ├── service/            # 业务逻辑
│   │   ├── manager/            # 外部服务集成
│   │   └── model/              # 数据模型
│   ├── script/                 # 部署脚本
│   └── pom.xml
├── zhiyuan-agent/              # AI Agent
│   ├── app/
│   │   ├── agent/              # Agent 核心 (Pydantic AI)
│   │   ├── tools/              # 意向提取工具
│   │   ├── plan/               # 方案规划 handlers
│   │   ├── data/               # 数据层
│   │   └── server.py           # WebSocket 服务
│   ├── skills/                 # 技能定义
│   └── pyproject.toml
└── zhiyuan-rank/               # 排序服务
    ├── app.py                  # Flask 路由
    ├── services/               # 推荐算法
    └── requirements.txt
```
