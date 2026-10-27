# 工作集恢复契约审查

日期：2026-10-16；审查基线：`2122cef`；分支：`wip/2026-09-28-p2-write-loop-green`。

## 本轮边界

前批 thread-binding 恢复修复已独立提交为 `2122cef`。本轮仅对工作集进行源码审查和离线现状复现，不修改生产行为，不增加持久化，不启用自动清理。

没有委派独立 reviewer；结论来自直接源码复核及假模型、临时 SQLite 下的探针。没有访问真实模型、现有业务服务、共享 Redis/数据库，也没有重启服务、修改 Java、推送或部署。

## 已确认的问题

### 1. 旧录取事实会覆盖快照明确给出的新事实

- 位置：`zhiyuan-agent/app/gateway/service.py:2273`、`zhiyuan-agent/app/gateway/service.py:2283`。
- 新工作集先由 `ConversationWorkingSet.from_snapshot()` 正确构造，再被旧工作集的整个 `admission_facts` 列表无条件覆盖。
- 离线复现：同一录取单元，旧事实为 30/冲/old-data，新快照为 80/保/fresh-data。回合结果的嵌套 snapshot 保留 80，但工作集顶层和实际传给假模型的工作集文本仍包含旧事实 30。
- 这是已复现的模型输入自相矛盾，不是已证明模型最终给出错误建议，更不是已验证的越权写入。
- 当前 Java `ConversationSnapshotService` 尚未填充 `admissionFacts`。因此这里证明的是现有 Gateway 在收到非空新事实时的合并缺陷，不能宣称真实 Java 链路已产生这类非空更新。

### 2. 快照中已不存在的提案会从旧内存复活

- 位置：`zhiyuan-agent/app/gateway/service.py:2290`、`zhiyuan-agent/app/engine/execution_plan.py:69`。
- 新快照的 `activeProposal` 为 null 时，Gateway 会回填旧工作集的提案；执行骨架随后因为该旧提案选择 `confirmation`。
- 离线复现：旧版本有 pending-old，新版本成功返回 `activeProposal=null`；新回合工作集仍带 pending-old，实际传给假模型的执行计划为 confirmation。
- Java `ConversationSnapshotService.java:142` 在当前 pending 不存在或非 active 时保持该字段为空，说明这里的 null 有明确的“当前无活跃提案”来源，不应解释成加载失败。
- 已确认影响模型上下文和确定性执行骨架；本轮没有证明失效提案能够绕过后端校验并执行写入。

## 恢复能力与契约缺口

### Gateway 重建后，候选及来源轮次没有由快照恢复

`zhiyuan-agent/app/engine/working_set.py:70` 只从快照重建业务投影；快照模型 `zhiyuan-agent/app/gateway/contracts.py:534` 不含候选明细、工件引用或候选来源轮次。

离线对照使用同一成功快照：预置候选的旧 Gateway 在正常回合后仍有候选 school-1 和来源 candidate-origin；新建 Gateway 的工作集候选为空，来源轮次为 null。探针重建的是 Gateway 对象，不是真实 native resume 或真实进程重启实验，也未证明原 thread 中的模型历史完全丢失。

结论是不能仅凭“threadId 恢复成功”就承诺应用工作集恢复等价。重启、回收或切换 worker 后，“上一批学校”等指代所需的应用投影必须有明确恢复源或显式降级。

### 空录取事实列表尚不能等同于撤销全部历史事实

Java DTO 的 `admissionFacts` 默认为空列表，`ConversationSnapshotService` 当前没有对应填充逻辑。Python 的 `build_snapshot()` 也把缺失和空列表归一化为空。

探针确认空快照事实下旧工作集事实会保留，但这里只记录现状，不把所有保留一概判为缺陷。后续需要明确“未提供”“权威空集”“查询后失效”的区分，以及历史事实的来源、适用范围和版本；不能在没有新契约时把所有旧事实直接清空，也不能将其无条件宣传为当前有效事实。

## 字段来源与恢复边界

| 字段 | 现有来源 | 建议边界 / 未决项 |
| --- | --- | --- |
| snapshotVersion、scoreContext、confirmedConstraints、preferences、mode/stage、capabilities | 每轮成功读取的业务快照 | 由快照重建；读取失败不伪造空快照 |
| evidenceRefs | 快照和当前回合输出 | 跨轮以新快照为准；不从旧内存复活已不在快照中的证据 |
| activeProposal | 快照，及当前回合输出投影 | 下一轮以成功快照为准；null 不回填旧提案 |
| admissionFacts | 快照、工具结果和回合输出 | 明确非空新事实不应被旧列表覆盖；空列表和历史事实有效性需另定契约 |
| candidateEntities、candidateSourceTurnId | 工具/回合 payload，保存在进程内工作集 | 目前只有同进程连续性；恢复源缺失时不能编造候选或声称已恢复 |
| candidate scope | 快照版本、阶段及招生模式 | 现有阶段/模式变化会清候选；该规则不等于已经覆盖所有候选失效条件 |
| artifactRefs | 回合输出和进程内工作集 | 恢复引用不等于恢复授权；仍须按 tenant/session、有效期及版本核验签发记录 |
| lastResponseType、lastTurnId | 回合输出 | 仅为连续性锚点，不能替代当前 pending、请求幂等或写入授权状态 |

相关投影逻辑位于 `zhiyuan-agent/app/engine/working_set.py:83`、`zhiyuan-agent/app/engine/working_set.py:96`，模型输入边界位于 `zhiyuan-agent/app/gateway/service.py:2477`。

## 不能直接当作工作集恢复源的现有存储

- `SqliteArtifactStore.issue()`（`zhiyuan-agent/app/gateway/artifact_store.py:119`）保存身份、版本、paramsDigest/payloadDigest 和签发信息，不保存候选原文或查询参数原文。真实临时 SQLite 的签发/读回探针确认，签发记录里没有 candidates、payload、arguments；不能从摘要反向还原候选。
- `get_many()` 还需要已知 artifactId，并按 tenant/session 和有效期过滤。签发台账是授权核验来源，不应未经评审扩展成第二业务数据库。
- Redis UI 事件存储默认有 24 小时 TTL、2000 条上限和单事件 16 KiB 限制（`zhiyuan-agent/app/gateway/event_store.py:95`）；没有完整应用工作集恢复契约，不能把有限 UI 历史当作必然完整的恢复日志。
- thread-binding SQLite 是恢复 thread 的锚点，不包含完整工作集。不得因工作集调整或本地清理删除其最后恢复键，更不得删除可能共用的 SQLite 文件。

## 离线证据

- 当前行为复现和相邻回归：**35 passed，4.53 秒，退出码 0**，其中 5 项为临时审查探针，30 项为既有测试。
- 探针通过表示成功复现现状，**不表示上述问题已经修复**。
- 探针：`/tmp/test_zhiyuan_working_set_recovery_audit.py`；日志：`/tmp/zhiyuan-working-set-contract-audit.log`；均为临时调查产物，不是提交的永久回归。
- 五项分别覆盖：非空新事实被旧事实覆盖、空事实保留旧事实、旧提案进入确认骨架、Gateway 对象重建丢失候选/来源锚点，以及签发台账仅保存摘要。

从 `zhiyuan-agent` 执行的调查命令：

```bash
PYTHONPATH=.:tests/unit PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python /tmp/zhiyuan_hardening_pytest.py \
/tmp/test_zhiyuan_working_set_recovery_audit.py \
tests/unit/test_working_set.py \
tests/unit/test_snapshot_projection.py \
tests/unit/test_gateway_internal_state_tags.py -q -rs
```

前批提交前完整回归为 2971 passed、21 skipped、33 deselected、23 warnings，65.70 秒，退出码 0，日志 `/tmp/zhiyuan-binding-recovery-precommit.log`。这是前批验证记录，不是本轮新增修复的验证结果。

## 建议下一批：先修现有合并边界

本轮结论支持先做范围明确的小修，而不是直接引入工作集持久化：

1. 成功快照的 activeProposal 为 null 时，不再从旧工作集回填；非空提案继续使用新快照投影。
2. 成功快照明确提供非空 admissionFacts 时，保留新事实列表，不让旧内存整个覆盖；空列表暂保留现有行为，并明确这只是兼容过渡，不代表旧事实已获有效性背书。
3. 先写永久失败回归，检查实际模型输入、执行骨架及正常候选跨轮连续性，再改 Gateway 的合并逻辑。保留已有证据失效、阶段/模式候选失效、提案正常生成及确认回归。

更大的工作集恢复契约另行评审：比较“缺恢复源则显式重查/澄清”和“增加独立、有来源/版本约束的恢复投影”两种方案，再决定是否需要新持久化。前者部署与数据复杂度较低但连续性有限；后者连续性更强，但需要处理归属、并发写、失效、保留期和迁移，不能顺手加入本批。

该建议尚未实施。本审查文档留在工作区，不混入 `2122cef`，也不据此启用 TTL/LRU、扫描、路由卸载或其它自动回收。
