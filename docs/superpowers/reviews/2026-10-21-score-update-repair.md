# 成绩更新与本地演示模式修复（2026-10-21）

## 本次故障与配置复发原因

- 会话 `10042000` 在湖南 / 物理类 / 2027 年 / 478 分的成绩确认中，上游
  `VOLUNTEER` 全量数据查询返回 `84009`。分页初始化重试与全量接口均失败。
- 数据库只读核对：没有 `userScoreDetail` 行，没有成功的执行命令记录；待确认行
  为 `score_update / expired / 84009`。本次成绩写入没有生效，不是保存后仅提示失败。
- `76c8662`（2026-10-09）的模式兜底代码仍是当前 HEAD 的祖先，没有被代码回退。
  它的生产默认值一直是空，即关闭；当时通过本地临时启动参数开启 `PREDICT`。
- 10 月 13 日的既有验收记录仍注明该启动参数；当前日志可追溯到的 10 月 19 日启动
  已为 `effective=off`。本次运行进程同样没有该启动参数，私有配置原来也没有对应值。
  因而能确认是启动配置没有持久继承，不能据此归因到某个代码回滚或某次具体操作。

## 修复范围

1. 已有成绩的单科修正按科目编码合并，不删除未修改科目。完整选科变更仍采用完整新成绩单，
   不把新旧选科并成额外科目；重复科目拒绝。单科实际变化但没有新总分时先返回可解释的
   `110`，不擅自对可能包含赋分、加分的成绩求和，也不悄悄沿用旧总分。变更选科后同步
   重建继承的 `subjectList` 与优势学科字段；单科修正也刷新继承的优势学科分数。
2. 总分、年份、省份、科类或批次变化，且本轮没有明确提供新位次时，清除继承位次再查询。
   用户明确给的新位次仍优先；查询无数据时保持缺失，不保留旧位次，也不编造位次。
3. 成绩 prepare 保存合并归一后的有效成绩快照，包含预览时确定的取数模式，避免确认阶段
   因缺省模式再次推导而与预览口径不同。仍使用既有 pending、版本守门、claim 与幂等命令链。
4. 执行失败与实际过期的展示分离：内部失败落 `expired` 的存储协议保持兼容，但
   `resolvedAction=fail` 的冷加载展示投影为 `failed`。`84009` 不再被结果解析、续接指令或
   卡片提示当作确认超时；保留原始业务码和上游消息供排查。
5. 本地配置生成器默认持久写入 `demo.prepare-type-fallback: "PREDICT"`，支持显式改为
   `VOLUNTEER` 或空字符串关闭；生产资源配置不变，请求显式模式和会话既有模式仍不覆盖。
   当前私有配置也已写入该值，不依赖某个 `/tmp` 启动脚本继续携带参数。
6. 卡片与文字确认仍共用执行链；新增“两个入口 × 成功/84009”回归，验证命令、冻结载荷、
   operationId 与 claim token 的一致性。

## 验证

先写回归再修复：Java 首轮 8 个断言失败，Python 首轮 6 个用例失败，前端新增用例失败，
分别复现了数据合并、位次继承、模式未冻结、失败归类和配置缺失问题。
补丁审查另发现“不完整存量成绩的上下文修改预览/执行不一致”和“换科后残留旧选科字段”，
随后新增 3 个红例确认并修复；不完整旧档案在 prepare 阶段就要求补齐，不留必失败的确认卡。

定向回归命令：

```bash
cd zhiyuan-server
mvn -q '-Dtest=ChatSessionBizServiceTest,ChatSessionBizServiceScore*Test,ScoreCatalogServiceProvinceDefaultsTest,PendingPlanningCommandBizServiceTest,PendingConfirmationBizServiceTest,ConversationSnapshotServiceTest' test

cd ../zhiyuan-agent
.venv/bin/python -m pytest tests/unit/test_conversation_actions.py tests/unit/test_gateway_action_continuation.py tests/unit/test_codex_local_infra_script.py tests/unit/test_gateway_turn_conversation_action.py tests/unit/test_gateway_score_update.py tests/unit/test_codex_local_stack_scripts.py tests/unit/test_ws_conversation_action.py tests/unit/test_pending_confirmation_client.py -q

cd ../zhiyuan-web
node --test src/pageComponents/sessionDetailV2/ConversationEvents/*.test.mjs
```

- Java：166 tests，0 failures，0 errors，0 skipped。
- Python：158 passed。
- Web：68 passed。
- 配置生成测试使用临时目录与替身 Docker，未操作真实容器。
- 私有配置仅输出模式和权限核验：`PREDICT`，`0600`；未输出凭据。

## 部署前边界（修复阶段记录）

本轮不替换正在使用的 jar，不重启任何服务，不改现有业务记录，不提交代码。
配置文件已修改不等于运行时已加载；本轮结束前运行的 18290 仍是原进程，启动日志有效值
仍为 `off`。需要部署新后端并重启后端/Agent，浏览器才能验证完整修复。应限定在
`18290 / 18291 / 3201` 这组本地环境，不整体重启另一套环境。

运行验收时须重新生成成绩预览；失败终态不能靠再次确认旧卡绕过。存量显式指定
`VOLUNTEER` 的会话也不会被本地缺省兜底静默改写，需另行明确模式或等待上游数据就绪。

## 部署验收（用户确认后执行）

用户随后授权定向部署。2026-10-21 已完成本地替换，未修改上述历史业务记录，也未提交代码。

| 服务 | 部署前 PID | 部署后 PID | 处理 |
| --- | --- | --- | --- |
| 后端 `18290` | `19518` | `27208` | 隔离构建后以新 jar 启动 |
| Agent `18291` | `4515` | `27332` | 使用原启动参数和完整环境重启 |
| Web `3201` | `31139` | `31139` | `next dev` 热更新，未重启 |
| Rank `18292` | `2035 / 4258` | `2035 / 4258` | 未重启 |
| 另一套 `18090 / 18091 / 3001` | `22566 / 27507 / 22430` | 相同 | 未重启 |

- 从当前工作区复制后端源码到私有 rollout 目录，重新执行 166 项后端回归并构建新包；
  未覆盖原 `target/zhiyuan-server.jar`，旧包另存为 `backend-rollback.jar`。
- 启动后逐项比对进程：后端仅替换 jar 路径，其他参数与完整环境保持原样；Agent 参数与
  完整环境保持原样。原有 `review.fix.command.enabled=true`、
  `review.fix.search.enabled=true`、`review.fix.search.strategies=all` 均保留。
- 新后端日志确认 `demo.prepare-type-fallback effective=PREDICT`。对 `18290` 的内部健康检查
  携带既有内部凭据返回 200；没有关闭认证或对外暴露内部接口。
- `18290 / 18291 / 18292 / 3201` 的健康探针全部通过；另一套
  `18090 / 18091 / 3001` 也均通过。`3201/sessionDetailV2` 返回 200，实际返回的页面 JS
  已包含新版 `84009` 提示，不仅是磁盘源码发生变化；前端访问内部健康路径仍为 404。
- 本次再次运行 Agent 回归 `158 passed`、前端回归 `68 passed`；`git diff --check` 通过。
  已同步 `/tmp/18290-staged.pid` 与 `/tmp/agent-18291.pid`，避免后续沿用旧 PID。

部署目录为 `.local/codex-local/rollouts/score-update-20261021T032454Z/`，目录权限为 `0700`。
其中新运行包是 `build/target/zhiyuan-server.jar`，当前日志是 `backend-new.log` 与
`agent-new.log`，不是部署前的 `/tmp/18290-staged.log` 与 `/tmp/agent-18291.log`。
`deployment-success.json` 与 `runtime-verification.json` 保存本次运行证据；原启动信息文件
含私有环境，仅保留在该私有目录并设为 `0600`，不要复制进版本库。该目录包含正在运行的
jar，不应作为普通构建缓存清理。

### 尚需浏览器复验

未替用户执行真实成绩确认或自动改业务数据；服务可用与回归通过不等于真实上游端到端
业务已经验收。请在 `3201` 刷新会话，重新发送原成绩并生成新的确认卡：

1. 核对预览内容后，可点击卡片确认，也可针对当前待确认事项发送“确认更新成绩”；
   两个入口使用同一执行链，旧失败卡不应再次执行。
2. 确认后检查成绩横幅与方案上下文；刷新页面，确认已保存、失败和真实过期状态不混淆。
3. 单科分数实际修改时同时给出新总分；未给新位次时应重新查位次，不能默默沿用旧位次。
   未给新总分则应要求补充，不应猜测总分或直接执行。
4. 若仍出现 `84009`，记录会话 ID 和操作时间，先核对该会话是否已显式保存
   `VOLUNTEER`；不能据此认定全局 `PREDICT` 配置又回退，也不要反复确认旧卡。

另发现磁盘已使用约 99%，部署后可用空间约 530 MiB。未擅自清理其他环境或历史构建；
后续大规模构建前需要单独处理空间问题，并保留当前运行包和回退包。
