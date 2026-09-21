---
task: B0
status: DONE
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-21 05:30 +0800
source: docs/superpowers/plans/2026-09-20-codex-domain-and-plan-transactions.md
---

# B0 报告：Artifact 与 prepare 幂等存储

## 一、结论

两张表、两个服务、一个内部端点落地，25 条新测试通过，全量 Java
**732 tests / 0 failures / 6 skipped / BUILD SUCCESS**。

计划要求的"隔离 MySQL 上验跨用户不可读、重启后可读"**已补齐**：
`ConversationArtifactPersistenceIntegrationTest` 7 条，跑在真实隔离库上，
并且缺配置时显式 skip 而不记为通过。

## 二、交付

| 路径 | 变更 |
|---|---|
| `db/migration/V16__conversation_artifact.sql` | 新增（V16 未被占用，与任务书一致） |
| `db/migration/V17__conversation_proposal_request.sql` | 新增 |
| `model/entity/biz/ConversationArtifactEntity.java` | 新增 |
| `model/entity/biz/ConversationProposalRequestEntity.java` | 新增 |
| `mapper/ConversationArtifactMapper.java`、`ConversationProposalRequestMapper.java` | 新增 |
| `model/dto/planning/ArtifactDTO.java`、`ArtifactPageDTO.java`、`PrepareResultDTO.java` | 新增 |
| `service/biz/ConversationArtifactService.java` | 新增 |
| `service/biz/ConversationProposalRequestService.java` | 新增 |
| `web/controller/inner/ConversationArtifactController.java` | 新增 |
| `test/.../ConversationArtifactServiceTest.java` | 新增，10 条 |
| `test/.../ConversationProposalRequestServiceTest.java` | 新增，8 条 |
| `test/.../ConversationArtifactPersistenceIntegrationTest.java` | 新增，7 条（真库，环境变量门控） |

## 三、写下的几条语义约束

**产物不可原地修改。** 内容与摘要一起写入、读取时复核。上游数据变了就生成新产物，
而不是改旧的那份——否则同一个 artifactId 在不同时刻代表不同内容，引用它的所有
结论都要重新判断。

**摘要只取决于内容本身。** FastJSON 默认按字段插入顺序输出，同一份数据换个构造
路径就会得到不同字节、不同摘要，而那会被下游当成"内容变了"。所以走
`MapSortField + SortField` 的稳定序列化；有一条测试专门验"两种构造顺序同一个摘要"。

**超限不截断。** 超过 2MiB 直接报 413：截断后的 JSON 既不是原产物也解析不了。

**不存在与不属于自己回同一个错误。** 区分开来等于确认了一次越权探测——
对方能据此判断 id 存在与否。

**prepare 记录不可覆盖。** Pending 是每会话一行的**状态**，每次 prepare 都会把它冲掉；
于是"重试同一个 requestId"在它上面看起来和新的一次 prepare 一模一样，两者都会
重新编译预览、生成新的 operationId——而用户只是没收到回包。

**先占位再干活。** 唯一键是并发防线：两个并发请求只有一个能插进去，另一个拿到
`DuplicateKeyException` 后走"重放已有记录"。反过来先干活再插入的话，两边都会跑一遍。

**`superseded` 是终态，不复活。** 重试一个已被取代的 requestId 必须拿到"已被取代"，
而不是把它重新执行一遍——用户看到的旧卡已经失效了。

## 四、实现中修掉的两个自己的错

1. **`ArtifactPageDTO` 漏 `import java.util.Map`**（编译期就炸了）。
2. **分页测试的算术是空的**：fixture 只有 25 条数据却断言"取到 50 条"，实际拿到 25。
   即使上限没生效结果也一样——那条测试测不出任何东西。改成 60 条数据，才真的
   观察到上限（第一页 50 + 游标，第二页 10 + 无游标）。

## 五、真库层：把"为什么落库"验掉

mock/假表证明分支走对了，证明不了 SQL 的 where 真的过滤掉跨租户，也证明不了
数据真的在库里。7 条真库用例覆盖的正是这些：

| 用例 | 为什么只有真库能验 |
|---|---|
| 迁移建出了两张表 | 编译通过 ≠ 建得起来（字符集、索引长度、约束名） |
| 换一条**独立 JDBC 连接**读得到产物 | 证明数据在库里而不是 ORM 会话缓存里——服务本身无状态，所以"重启后还在"由此成立 |
| 跨租户 / 跨会话读不到 | mock 里 `where` 根本不会被执行 |
| 直接把 `expires_at` 改到过去 → 410 | 验证读取路径真的看了这一列 |
| 直接把 `payload_json` 改掉 → 摘要不符 | 验证签名是真的在比对，不是形式 |
| 绕过服务直接插同 key → 唯一键拒绝 | 唯一键若没建出来，并发防线就只剩应用代码，而那正是它防不住的东西 |
| 真表上重发 prepare → 返回原记录 | 幂等靠的是表上的唯一约束，不是内存里的 Map |

运行方式写在该类头部注释里；`CONVERSATION_TEST_DB_URL` 未设置时**整类 skip**：

```
$ mvn -o -Dtest=ConversationArtifactPersistenceIntegrationTest test   # 无配置
Tests run: 1, Failures: 0, Errors: 0, Skipped: 1
```

skip 不是通过——这一点在这条命令的输出里是可见的。

## 五之二、仍未做

1. **`prepareOnce` 没有被任何生产代码调用**——它是 B6 `/proposal/prepare` 的底座，
   本任务只建机器不接线。
2. 产物与 Artifact 引用的**有效期分档**（candidate/comparison 24 小时、
   pending 引用的 plan preview 至少 30 天）只体现在"必须传 expiresAt"，
   没有按 kind 给默认值——那属于 B5/B6 的调用方。
3. 真库测试是**单连接**下的行为；并发插入下 `DuplicateKeyException`
   分支是否按预期走，只有并发用例能证明（现在证明的是"唯一键存在"）。

## 六、验收命令与原始结果

```
cd zhiyuan-server
mvn -o -Dtest=ConversationArtifactServiceTest test
# Tests run: 10, Failures: 0, Errors: 0, Skipped: 0

mvn -o -Dtest=ConversationProposalRequestServiceTest test
# Tests run: 8, Failures: 0, Errors: 0, Skipped: 0

mvn -o test
# Tests run: 732, Failures: 0, Errors: 0, Skipped: 6 — BUILD SUCCESS
# （Skipped 里含门控的真库测试类：缺配置时不通过）

CONVERSATION_TEST_DB_URL=... CONVERSATION_TEST_DB_USER=root CONVERSATION_TEST_DB_PASSWORD=... \
  mvn -o -Dtest=ConversationArtifactPersistenceIntegrationTest test
# Tests run: 7, Failures: 0, Errors: 0, Skipped: 0 — 跑在 127.0.0.1:13306 的隔离库上
```

计划点名的两例都在：`prepareBThenRetryASeversAInsteadOfReRunningIt`（并额外断言
`prepareWork` **没有被重新执行**）、`prepareIsRejectedWhileAPendingIsApplying`。

### 非空性

- "重试不重新编译"用 `AtomicInteger runs` 记编译次数并断言 `== 1`；如果服务真的
  又跑了一遍，计数会变成 2。
- "取代后重试不执行"那条把 `prepareWork` 写成直接 `throw new AssertionError`——
  一旦被执行，测试立刻挂，而不是悄悄通过。
- "被取代"这条依赖 `supersedeSiblings` 真的改了状态；单元测试里的假表实现了它，
  真实 SQL 版本由第五节的真库用例另行验证。

## 七、证据边界

- 逻辑层：mock mapper + 内存假表；真库层：隔离 MySQL（`zhiyuan_codex_local` @ 13306）。
- **没有并发测试**：唯一键的**存在**被证明了，并发插入下服务是否按预期走
  `DuplicateKeyException` 分支没有被证明。
- 真库测试跑在**本机隔离实例**上，不是生产等价环境；没有验证主从、连接池打满等场景。
- 仍然：`prepareOnce` 无生产调用方，端到端（HTTP → 服务 → 表）未验。
