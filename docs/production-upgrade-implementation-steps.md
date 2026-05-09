# 生产服务器升级实施步骤

本文档记录在当前生产服务器上推进老版本到 V2 升级的实际执行步骤。当前线上尚未部署新版本，生产流量仍在老版本服务上；本次实施先做只读核查、真实样本迁移验证和单会话回滚演练，验证通过后再进入部署。

## 1. 当前前提

当前新版本代码位于：

```text
/root/dev/zhiyuan
```

当前线上实际运行仍是老版本：

- 前端容器：`gaotu-volunteer-assistant-prod`
- Agent 容器：`gaotu-zy-agent-plus-prod`
- Rank 容器：`gaokao-volunteer-rank-prod`
- 后端进程：`/root/work/gaotu-assistant-server/gaotu-assistant-server.jar`

因此当前不会有线上用户触发新版本 `planningState` 懒迁移。正式切流前，必须先完成真实样本验证。

## 2. 实施原则

1. 先验证，后部署。
2. 先只读核查，后复制样本。
3. 不直接修改老方案 JSON。
4. 不直接删除生产 `planningState`，除非明确指定单个会话并完成 dry-run。
5. 不全量重算历史方案。
6. 不立即下线旧页面和旧 `/volunteer/*` 接口。
7. 每一步保留可回滚路径。

## 3. 阶段 A：只读确认生产运行态

目标：确认当前生产服务、配置、数据目录和日志目录。

### A1. 查看运行服务

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
ps -ef | grep -E 'gaotu-assistant-server|gaotu-ai-server|java|uvicorn|gunicorn|next' | grep -v grep
```

预期：

- 能看到老版前端、Agent、Rank 容器。
- 能看到老版 Java 后端进程。

### A2. 查看老后端配置

```bash
sed -n '1,240p' /root/work/gaotu-assistant-server/application-online.yml
```

重点确认：

- `spring.datasource`
- `spring.redis`
- `gaotu.zhiyuan.temp-data-path`
- OSS 配置
- 后端端口
- Rank 服务地址

注意：该步骤只读，不修改配置。

### A3. 查看方案数据目录

根据 `gaotu.zhiyuan.temp-data-path`，执行：

```bash
find <temp-data-path> -maxdepth 2 -type f -name 'session_volunteer_*.json' \
  -printf '%p %s\n' | sort | tail -100
```

目标：

- 确认老方案 JSON 是否在本机。
- 确认是否同时存在 `_temp.json`、`_temp_summary.json`、最终提交 JSON。
- 初步观察文件大小，识别大文件样本。

## 4. 阶段 B：抽样真实老方案 JSON

目标：把真实生产方案 JSON 复制到隔离目录，供新版本迁移测试使用。

样本目录：

```text
/tmp/zhiyuan-migration-samples
```

创建目录：

```bash
mkdir -p /tmp/zhiyuan-migration-samples
```

抽样建议：

- 已提交方案：`session_volunteer_{id}.json`
- 临时方案：`session_volunteer_{id}_temp.json`
- 大文件方案
- 空方案或很小文件
- 专业组模式
- 专业优先模式
- 缺少 `is_preferred` 或 `selectZy` 的旧格式
- 有 `_temp_summary.json` 的会话，但测试目录优先放完整方案 JSON

复制样例：

```bash
cp <temp-data-path>/session_volunteer_1002.json /tmp/zhiyuan-migration-samples/
cp <temp-data-path>/session_volunteer_1003_temp.json /tmp/zhiyuan-migration-samples/
```

注意：

- 只复制，不移动。
- 不删除生产目录里的任何文件。

## 5. 阶段 C：运行真实样本迁移测试

目标：验证新版本后端可以解析真实老 JSON，并转成 V2 `planningState` 结构。

执行：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest#shouldImportExternalLegacyCompleteDataSamples \
  -Dlegacy.sample.dir=/tmp/zhiyuan-migration-samples test
```

通过标准：

- 测试通过。
- 没有 JSON 解析异常。
- 没有 NPE。
- 迁移后候选数、优报数、排序数合理。

如果失败：

1. 记录失败文件名。
2. 不修改生产数据。
3. 在新版本迁移解析逻辑中修复兼容。
4. 再重新跑测试。

## 6. 阶段 D：真实会话人工对账

目标：确认新老页面结果一致。

建议先选至少 20 个真实 `chatSessionId`：

- 10 个已提交方案。
- 10 个未提交或只有临时方案。

对账口径：

- 老页面优报总数 = V2 `orderedPlanState.items` 总数。
- 老页面冲/稳/保优报数 = V2 ordered 冲/稳/保数量。
- 老页面候补项在 V2 candidate 中仍可查询。
- 已提交方案顺序保持一致。
- 导出 Excel 主要字段一致。
- 有 `planEditCache` 的会话只提示，不自动改方案。

建议记录表：

| chatSessionId | 老状态 | 老优报数 | V2 ordered 数 | 冲/稳/保是否一致 | 顺序是否一致 | 导出是否一致 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |

## 7. 阶段 E：单会话回滚演练

目标：确认某个会话的 V2 状态可以删除并重新懒迁移。

先 dry-run：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
python3 scripts/reset_planning_state.py --session-id 1002
```

确认 SQL 只命中：

```text
data_key = 'planningState'
data_version = 0
chat_session_id = 1002
```

再执行：

```bash
python3 scripts/reset_planning_state.py --session-id 1002 --execute
```

验证：

- 删除后进入 V2，会重新触发懒迁移。
- 回到 legacy 页面仍能查看老方案。
- 老方案 JSON 未被修改。

## 8. 阶段 F：补齐上线前 P0

当前文档中明确的 P0 遗留：

1. 真实老方案样本测试。
2. 真实会话新旧对账。
3. 单会话回滚演练。
4. 前端 V2 对 `legacy_submitted` 展示明确提示。

其中第 4 项建议改造：

- 读取 `orderedPlanState.generationMode`。
- 当值为 `legacy_submitted` 时，在工作台顶部展示：

```text
历史已提交方案，建议只读查看；如需调整，请先复制或重新生成方案。
```

并避免给用户强烈暗示“可随意编辑已提交历史方案”。

## 9. 阶段 G：部署准备

真实样本和对账通过后，再进入部署准备。

后端：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
mvn package -DskipTests
```

前端：

```bash
cd /root/dev/zhiyuan/zhiyuan-web
npm run build:dev
```

Agent：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
# 根据生产环境镜像策略构建或更新
```

Rank：

- 如果本次没有算法或数据改造，可暂不升级。
- 如果 V2 依赖新 rank 字段，需单独验证再升级。

## 10. 阶段 H：正式部署和灰度

部署前必须明确：

- 是替换现有 `/root/work/gaotu-assistant-server` 老后端，还是新建 `/root/work/zhiyuan-server`。
- Nginx 路由是否切到新端口。
- 新前端是否覆盖老前端容器。
- Agent WebSocket 路由是否切到新 Agent。
- 回滚命令是什么。

推荐灰度：

1. 后端先上线兼容版本，旧接口保留。
2. 内部账号访问 `/sessionDetailV2`。
3. 少量真实会话进入 V2。
4. 观察迁移日志：

```bash
cd /root/dev/zhiyuan/zhiyuan-server
python3 scripts/analyze_legacy_migration_logs.py /path/to/server.log
```

5. 无异常后扩大入口。

## 11. 回滚要点

前端回滚：

- 把入口切回老页面。
- 保留 `/sessionDetailLegacy`。

后端回滚：

- 切回老 JAR 或老容器。
- 新增 `planningState` dataKey 对老版本无影响。

单会话回滚：

```bash
python3 scripts/reset_planning_state.py --session-id <id> --execute
```

生产数据保护：

- 不删除老 JSON。
- 不删除旧 `/volunteer/*` 接口。
- 不批量删除 `planningState`。

