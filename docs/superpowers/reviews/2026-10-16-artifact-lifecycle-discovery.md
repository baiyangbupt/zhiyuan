# 产物账本与会话回收：续轮调查（2026-10-16）

## 状态与范围

用户要求继续修复并评估是否提交。本轮重新核对当前工作区，基线仍为 `7b6a0a4`。
这里只记录调查结果与待确认方案；没有实现第三批修复，没有提交、部署、重启服务或读写共享数据库。
第一、二批交付与验证仍以同日的 architecture-hardening / release-readiness handoff 为准，本轮没有重跑那些全量测试。

推进次序需要调整为：先补产物签发可信性和持久账本，再实施会话回收。
仅把当前内存字典原样持久化，会把不可信来源也永久保存，并不能补齐安全边界。

## 已确认的代码路径

- `GatewayService._evidence_inputs` 从整个 turn 的 `artifacts` / `events` 递归收集记录。`_collect_records` 会解析 JSON 字符串，也会进入 `agentMessage.text`，没有在此处证明记录来自真实工具执行。
- `register_scoped_artifacts` 只检查记录自带的 tenant/session/stateVersion 是否齐全、是否匹配，不独立查询签发来源。完整字段是格式与归属声明，不是不可伪造的签发证明。
- `validate_turn_output` 的 artifact 分支核对 session 与版本，但没有像 evidence 分支一样比较 tenant。`strict_scope=True` 也没有补上该比较。
- MCP 真正的签发点是 `ReadonlyDomainTools._attach_artifacts`。当前产物 ID 依赖租户、会话、工具、工作区版本与可信入参，不包含结果内容摘要。
- Java 已有 `ConversationArtifactService` 与不可变产物表，但公开的内部 controller 只有读取和分页，现有 `put` 自动生成 `art_<uuid>`，没有接收 `mcp_art_*` 签发登记的接口。
- Gateway 与 stdio MCP 已共用 `ThreadBindingRegistry` 的 SQLite 文件，并通过 `CODEX_APP_SERVER_BINDING_REGISTRY_PATH` 传递位置。这是可复用的单机持久化边界，不代表共享多 worker 调度已经成立。

## 本轮纯内存复现

使用当前项目 `.venv/bin/python`，设置 `PYTHONDONTWRITEBYTECODE=1`，只构造假的 snapshot、Gateway 对象与事件，没有启动运行时或调用后端。

第一条探针把自造 `mcp_art_offline_fabricated` 放进 `agentMessage.text` 的 JSON：

1. snapshot 为 `sessionId=offline-session`、版本 42。
2. 自造记录包含 `tenantId=offline-tenant`、同一 session、版本和类型。
3. 经 `_evidence_inputs`，记录进入会话登记表。
4. 再以 recommendation 的 artifactRefs 引用它，`validate_turn_output(..., strict_scope=True)` 接受。

第二条探针直接向 validator 提供同 session、同版本但 `tenantId=other-tenant` 的产物账本条目，当前 tenant 为 `offline-tenant`，仍被接受。

实际输出：

```text
model_only_record_registered= True
model_only_record_accepted= True
foreign_tenant_same_session_accepted= True
```

这是组件级可复现的可信来源缺口和租户校验遗漏，不是生产环境攻击演练；不能据此宣称真实接口已经发生数据泄漏。
涉及的 `output_validation.py` 在当前工作区没有相对 HEAD 的修改，不能把这些问题归因于前两批补丁。

## 待确认的架构选择

### 建议：复用本机 SQLite，先完成单 worker 的可信签发账本

- 在既有共享文件中使用独立产物表和独立 store 接口，不修改绑定记录的含义，也不把 handle 或密钥存入产物记录。
- 仅由可信 MCP 工具成功产生 candidate/comparison 结果后登记；先原子提交签发记录，再把引用返回给模型。登记失败不得仍返回可引用的成功产物。
- Gateway 按输出引用的 artifactId 和当前 tenant/session 查询真实签发记录；模型正文及递归事件中的记录只用于定位候选 ID，不再成为签发证明或持久化来源。
- 校验至少覆盖 tenant、session、artifactType、权威 stateVersion 和有效期；thread 只保留审计作用，不能因正常恢复更换 thread 就拒绝同会话合法产物。
- 保存结果摘要与可信入参摘要，使 ID 与内容身份相符。同 ID 的不一致内容必须报冲突，不能继续“最后一次覆盖”。不能仅复制当前依赖入参的确定性 ID 规则后假设结果永远相同。
- store 损坏、读取失败、未登记、过期及跨作用域都拒绝；不能因存储不可用退回相信模型事件。生产模式缺少 store 应在装配边界显式失败，测试替身需要显式注入可信 store。
- 只保留验证所需的紧凑记录，不宣称实现完整候选内容恢复或新增通用产物读取产品接口。Java 的冻结方案、pending 命令产物不迁入此表。
- 旧版本进程内记录不能从历史 assistant 文本“补录”。升级后无法核验的旧引用应要求工具重新签发，不能靠补齐字段放行。
- 需要在正式 spec 中固定有效期、每条记录上限、按索引分批清理和错误码。到期是明确失效，不静默延长；SQLite 文件必须放在受限权限且跨重启保留的本机持久卷，丢卷不承诺恢复。

优势：复用已经存在的 Gateway/MCP 共享边界，不增加 Java 发布耦合或新的 Redis 可用性前提，适合当前明确的单 worker 约束。
代价：持久性限于保留该本机卷的重启，不能当作多实例共享权威或容灾完成。

### 备选

- Java 数据库统一账本：更适合后续共享权威，但需要受保护的签发写入契约、不可变 ID/内容冲突处理和协调上线；不是直接调用现有 `put` 就完成。
- Redis 签发账本：便于共享，但必须另外明确持久化、淘汰和保留策略，不能把事件流现有 TTL 自动当成产物寿命，也不能在配置缺失时回落内存。

## 会话回收的依赖与边界

此项在可信持久账本落地后单独设计、实施和验证，不与第一项混成一次大改。

- `SessionRuntime` 的 `_active`、`_tasks`、admission gate 已有完成回收逻辑；不能把所有映射一概视为同一类缓存。
- `_detached` 目前是全局任务集合，不足以回答“某个会话是否还有不带 requestId 的动作在收尾”。需要显式的按会话持有者计数。
- Gateway 的锁要同时覆盖持锁者和等待者，在取锁之前取得生命周期持有权；不能靠 `lock.locked()` 或检查私有等待队列后删锁。
- 连接、已入队请求、快照/绑定恢复、动作执行、原生待答问题与自动续接都属于持有者；从读取用户水位到续接完成必须连续持有，避免回收后水位重置形成 ABA 问题。
- 原生问答既有 pending 记录，也有已答去重记录和 RPC 反向索引。回收需要分别说明活跃阻挡与完成后保留期，不能把“不在可答卡片快照里”当作“没有状态”。
- 有待确认业务提案、或者无法证明没有提案时保守保留；不能修改、取消真实提案来制造空闲。Java 状态和本机授权/绑定记录也不能当作临时缓存删除。
- 回收只释放可从权威存储重建的内存状态；重新进入会话要沿用现有 ThreadRecovery，不能因内存表缺项就静默新建 thread。
- 容量压力只能回收满足安全条件的空闲会话；活跃会话过多不能强制驱逐后宣称“全进程内存已严格有界”。
- 首期继续单 worker；本轮不实现分布式归属、fencing 或跨进程串行。

## 后续验收与提交判断

正式设计批准后，先用回归测试钉住上述两个反例，再覆盖真实 MCP 签发、两个 store 实例跨重开读取、内容冲突、错租户/错会话/类型/版本/过期、存储故障和修复回合。测试必须使用临时数据库与 fake backend，不接共享服务。

生命周期阶段另测锁等待者、无 requestId 的 detached 动作、续接水位、待答卡片、待确认提案和回收后原 thread 恢复。

当前不执行 `git add` 或 `git commit`。前两批已有离线验证记录，可按独立职责拆分提交，但提交不等于上线批准；不应把尚未实现的第三批描述为完成。
鉴于新发现的产物可信性问题，建议先补其最小可信闭环，再评估相关 Agent 改动的提交。互不依赖的前端/运维修复可以另行评估，不必等多实例改造。
必须排除用户原有 `zhiyuan-web/tsconfig.tsbuildinfo`、`.next-dev-p2/`、`.next-dev-r5/`、日志和运行数据库；对共享文件只按确认过的变更范围暂存，不能整库 `git add .`。

本轮检查清单：

- [x] 核对当前基线、工作区与前两批交付记录。
- [x] 追踪真实签发、事件收集、校验、恢复与运行时持有者。
- [x] 纯内存复现两个产物可信性反例并记录限制。
- [x] 对比持久化路线并明确回收依赖。
- [ ] 用户确认架构路线，形成正式 spec 与实现计划。
- [ ] 实现、离线验证、复审后重新评估分批提交。

## 后续状态

用户随后批准 SQLite 路线，可信签发账本已实施并完成离线验证与限定范围复审，详见 `2026-10-16-mcp-artifact-ledger-handoff.md`。
本文件保留调查时点的方案比较与检查清单；会话生命周期回收仍待下一阶段，尚未提交或部署。
