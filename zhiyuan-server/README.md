# zhiyuan-server

智愿 AI 志愿填报系统业务后端，基于 Spring Boot。

## 技术栈

- Java 8 + Spring Boot 2.3
- MyBatis-Plus + MySQL
- Redis (缓存 + 分布式锁)
- OkHttp (服务间调用)
- Flyway (数据库迁移)

## 开发

```bash
# 前置：MySQL 创建 sales_bot 数据库，启动 Redis
mvn spring-boot:run -Dspring-boot.run.profiles=local   # 端口 8080
```

## 包结构

```
com.ytell.zhiyuan/
├── web/controller/         # REST API (public + inner + admin)
├── service/                # 业务逻辑 (biz, shared, volunteer)
├── manager/                # 外部服务集成 (gaotu, rank, ali, cache, lock)
���── mapper/                 # MyBatis-Plus Mapper
├── model/                  # 数据模型 (entity, dto, vo, enums)
└── common/                 # 通用配置、工具、异常
```

## API 层级

| 前缀 | 用途 | 调用方 |
|------|------|--------|
| `/gaotu-assistant-bot/chat/{tenantId}/` | 用户 API | 前端 |
| `/gaotu-assistant-bot/base-data/` | 基础数据 | 前端 |
| `/gaotu-assistant-bot/inner/` | 工具 API | Agent |
| `/gaotu-assistant-bot/admin/` | 管理 API | 内部 |

## 环境配置

| Profile | 端口 | 数据库 |
|---------|------|--------|
| `local` | 8080 | localhost:3306/sales_bot |
| `test` | 8090 | 10.0.8.8:33306/gaotu_zhiyuan |
| `online` | 8090 | (生产 RDS，配置不入仓) |

## 部署

```bash
mvn package -DskipTests
# 产出: target/zhiyuan-server.jar

# 生产启动
cd script && sh start.sh
```
