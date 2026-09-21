# Codex 原生接入方案审查记录

日期：2026-09-20。范围：设计、实施计划、当前源码与现有测试；没有执行本轮新增业务实现或部署。

## 结论与证据范围

采用 Codex App Server 作为对话 Runtime、沿用智愿业务后端与前端是可行方向。初稿把多个“源码有能力”“业务已有基础”“前端已接通”混为已完成，且接口与状态有不一致；本次已在主设计和 A/B/C 任务书中修正。

本次采用 Superpowers 的 writing-plans、dispatching-parallel-agents、verification-before-completion 方法，按当前源码做三位子 agent 的独立审查，再对新任务书做第二轮复核。审查结果是**文档已补齐已发现的关键落地点**；不表示代码实现、真实模型兼容、上游数据或公网浏览器已经验收。

此前若干子 agent 启动遇到模型渠道503，未形成审查结论；本轮重新分派的三个 agent 均已完成，以下只记录实际返回的发现。

| 审查者 | 独立范围 | 实际工作 |
|---|---|---|
| native_interaction_audit | Codex原生提问、elicitation、steer/interrupt、事件wire shape | 第一轮核源码，第二轮核新A计划与恢复语义 |
| business_contract_audit | 数据真实来源、Evidence、方案生成、审查、Pending/CAS | 第一轮核Java/Python断点，第二轮核B计划的预览/事务/持久化 |
| frontend_plan_audit | 现有页面接线、WS、鉴权、脚本、域名验收 | 两轮只读审查；运行已有Node与shell语法检查 |

主 agent逐项核回源码并修订文档，没有让审查agent改动生产文件。

## 第一轮发现与落点

| 发现 | 修订后的明确落点 |
|---|---|
| get_current_plan 是 working-plan，不是年度计划或ordered-plan | 主设计§3与B2拆工具和结果kind；修tenant=1硬编码 |
| 历史分数数组没有概率，资格检查是boolean | B1/B2保留信封、分类适配、删除自铸authoritative证据 |
| Java已有program接口enrollRatio，但学校率不等于专业组率 | B2按层级和单位映射；缺单位概率明确不足 |
| groupCode已发出但Java历史请求不消费 | B2真实支持才扩DTO，否则unsupported_scope |
| P1b/P1c断点仍存在 | B1接Snapshot证据、Java核验、tenant/session边界；不因工作区版本变动判招生事实失效 |
| 原生选项是带id双向请求，存在模式门槛 | A1能力探针、A4原request回包；结构化终态澄清为独立降级路径 |
| MCP progress协议存在但发送链未证明可用 | 依赖item/started与completed，不承诺百分比进度 |
| 原生delta可能是最终JSON | A2/A3只发布脱敏阶段，最终答案校验后展示 |
| compat WS不转发中间事件，收包阻塞 | A3单reader+回调、独立收包/worker/writer，两路共用 |
| 页面没有消费normalizer，WorkspacePanel未传events/Artifacts | A6页面级store、真实props接线、复用现有组件 |
| preview没有Pending，confirm只claim没有execute/complete | B6真实编译/冻结、claim→execute→complete→workspace |
| generateInitialPlan/generateOrderedPlan写入，review推进workspace版本 | B5纯计算预览，review精确定义“不改志愿内容” |
| 工具成功覆盖partial业务状态 | A2修P2，分别保存executionStatus与toolStatus |
| inner路径无登录拦截，已有session/detail无owner校验 | C1真实owner校验、ticket、公网facade；C2阻止inner外露 |
| launcher的WS回连访客localhost，dev路径与旧assistant-pc不一致 | C2显式local/public-test，dev根路径，同源WSS |

## 第二轮新增问题与修订

| 问题 | 修订 |
|---|---|
| Redis日志重建仅sequence不能识别代际 | streamEpoch+sequence；resync先于普通去重处理 |
| resync漏掉仍活动的原生待答卡 | Broker.snapshot+SessionRuntime活动状态纳入恢复快照 |
| 提问超时回RPC error可能被解释为空答案继续 | 先interrupt并等待终态，resolved后取消handler且不迟到回包 |
| 协议缺少明确steer入站操作 | turnSteer类型、active/mismatch/completed测试 |
| choice/form答案形状未区分 | inputKind判别、typed content、accept/decline/cancel分别测试 |
| A3依赖A5却排在A5前 | 执行顺序改A1→A2→A5→A3→A4→A6→A7 |
| B5 selection之后直接ordering会读旧/空排序 | 新纯计算类：目标投影→working选择→ordered实体构建→排序→审查→冻结 |
| applied重试仍execute会被现Java owner guard拒绝 | operation状态查询成为必做；成功读结果，仅缺complete时补complete |
| Java complete可无成功command就标applied | complete服务核operation/摘要/后置条件，异常尝试都拒绝 |
| generated/profile新命令缺类型和摘要分支 | typed payload、明确偏好白名单、digest/validate/execute/postcondition全接线 |
| Java Artifact并不存在 | 新B0表、服务、ownership、分页、digest、有效期、重启用例 |
| Pending单行覆盖不支持prepare幂等 | 新B0不可覆盖request记录，superseded不复活，applying不得替换 |
| Java/Compose当前不一定只监听loopback | C2显式server.address与MySQL/Redis端口绑定 |
| 旧异常处理HTTP200与C1预期401/403冲突 | 新访问异常与新路径HTTP状态映射，保留旧业务码兼容 |
| MessageList还会回退旧WS_BASE | C2同时改实际URL构造处，public-test强制同源 |
| public模式只允许HTTPS却测试本地Origin | C3分local/public-test两次启动，重新取各Origin票据 |
| fake Runtime/闸门只有文件没有启动链 | C4独立contract launcher、wrapper、18293控制服务与identity检查 |
| E2E复用有历史会话导致全页消息计数错 | 每例独立session/初始版本，按turnId定位，失败保留现场 |

## 本轮实际执行的检查

代码基线：Codex源码 `5c5308f`，智愿源码 `4a23d50`；PATH二进制 `codex-cli 0.155.1`。执行 `codex app-server --help` 验证该二进制暴露stdio和schema生成命令；未据此判定所有交互能力通过。

主 agent重新执行：

```bash
cd /root/dev/zhiyuan/zhiyuan-web
node --test src/utils/conversationEvents.test.mjs \
  src/utils/codexLocalRewrite.test.mjs \
  src/pageComponents/sessionDetailV2/MessageList/fetchQueue.test.mjs
```

结果：Node报告3个测试文件通过，0失败、0跳过。它们是当前已有基线测试，不覆盖本计划将新增的浏览器/流式实现。

```bash
cd /root/dev/zhiyuan
bash -n scripts/start-codex-local.sh scripts/preflight-codex-local.sh \
  scripts/stop-codex-local.sh scripts/smoke-standardtest-web-proxy.sh
```

结果：exit 0。只证明现有脚本语法，没有启动服务、验证数据隔离或公网端口。

另外对最终文档检查：Markdown本地链接、引用现有文件、JSON示例解析、Python片段语法、任务ID/依赖及合同字段一致性。实际文档检查通过：5份文档、18处本地链接、9个JSON示例、12个Python片段、3个JavaScript片段、3个Bash片段、36个现有文件路径；20个任务、142个未执行步骤。语法检查不证明示例已接入应用，不将其当已部署代码。

## 尚需实施阶段实际验证

- Codex二进制+provider的原生问答/MCP metadata/有效工具清单；本地源码支持不代表运行组合支持。
- program概率单位和专业组身份、年度招生计划与章程的真实数据源；B3明确API/官方导入方式，没源则保持能力关闭。
- Java Artifact、prepare幂等表、完整预览纯计算和写事务；当前源码尚未包含这些新增实现。
- DNS/TLS/WSS、测试域名代理归属、Cookie/ticket、远程设备浏览器、跨用户访问拒绝；本轮未部署或宣称通过。
- 新增Python/Java/Playwright用例都属于待实施任务，本轮未运行不存在的测试。
- 官方文档 `https://developers.openai.com/codex/app-server/` 本轮获取返回HTTP403；本地源码是原生能力判断依据，没有伪称官方页面已验证。

## 交付入口

- [主设计](../../release-4.0.0-codex-native-zhiyuan-integration-and-frontend-validation-plan.md)
- [A：交互与前端](../plans/2026-09-20-codex-native-interaction.md)
- [B：领域与事务](../plans/2026-09-20-codex-domain-and-plan-transactions.md)
- [C：浏览器与域名验证](../plans/2026-09-20-codex-browser-validation.md)
