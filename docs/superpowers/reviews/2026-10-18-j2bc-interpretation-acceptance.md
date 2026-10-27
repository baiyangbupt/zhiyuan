# J2b/J2c 录取解读真栈验收（2026-10-18）

## 一、链路

```
模型 → planning.interpret_admission(planVersion)
  → agent MCP（身份来自受信 binding；模型塞的 tenant/session 被丢弃）
  → Java inner POST /session/plan/admission-interpretation
  → loadPlanningStateReadOnly + 候选池回填
  → PlanAdmissionInterpretationService（结构/条件情景，无概率）
  → 有界 interpretation.preview 事件 + 正文
```

## 二、部署

- Java 18290 新 jar：`PlanAdmissionInterpretationFacade` + controller endpoint。
- Agent 18291：MCP tool 注册（CAPABILITIES/kind/description/input schema/
  output kind=`interpretation`）、`interpret_admission` internal client、
  工具标签、tool contract。
- 插件：新增 `plan-admission-interpretation` 技能、routing 一行、cachebuster
  重装（`1.0.0+codex.20261018065153`）。
- 提示词：apply 后续接调一次解读；禁止概率/“最可能”；禁止转述
  `admissionRatio`/`schoolEnrollRatio` 百分比；解读卡由系统自动渲染。

## 三、真栈读数

克隆会话 900051/900052（10041984 状态，测试后已删除）：

- `tool.progress`：`planning.interpret_admission`，标签“正在解读当前方案”，
  started → completed。
- `interpretation.preview`：`status=completed`、`planVersion=5`、
  3 个情景（base/upside/downside），payload **无 path/evidenceRefs**；
  drivers 过滤后只剩 `档位=稳/冲/保`，不再带“录取率=56”。
- 正文：base=第 14 个潍坊学院、upside=广东金融学院、downside=南京邮电大学
  通达学院；明确“不是录取概率”；没有“没有卡片/没有可引用记录”的错误声明。
- 版本守卫：`planVersion` 不符返回 `stale_interpretation`（单测覆盖）；
  缺 planVersion 工具入口即 `needs_clarification`，不打后端。

## 四、验收中发现并修复

1. 首次真栈回答转述了 `drivers` 里的“录取率=56”（工具证据值，容易被读成概率）。
   修法：适配层过滤含“录取率/ratio/%”的 driver；技能与提示词同步禁止转述
   ratio 百分比。
2. 模型一度声称“没有可引用的解读卡片”。修法：技能明确“卡片由系统自动渲染，
   正文不要声称有没有卡”。

## 五、测试

- Python 全量：2840 passed / 33 skipped。
- Java：`PlanAdmissionInterpretationFacadeTest`、
  `PlanningStateControllerInterpretationTest`、J2a 服务测试全绿。
- Web：typecheck 通过；新增 `interpretationCardText`、reducer、
  whitelist 测试；全量 node 单测除既有的 `codexLocalRewrite` IPC 抖动外通过。

## 六、未完成

- `volunteerId -> CandidateItemDTO` 进程内 LRU（当前每次只读加载；量小可接受，
  J5.2 前补）。
- J3 回执扩展（origin/actionType/scope/receipt）。
- 非 V1 legacy 通道的解读映射（当前只保证 V1 事件；老 UI 不展示解读卡）。
- J5.2 切换后，解读输入从 `ReviewState.checks` 改读 `PlanEvaluation.findings`。
