# J5.5a：命令与只读预览验收

日期：2026-10-19。基线：`487e6ec`。范围：本地代码与自动测试，未部署、未重启、未提交。

后续进度：本文保留 a 阶段的历史验收边界。2026-10-19 的 b 前置批次已修复下文
Golden 上下文问题与专业组合作办学漏报，并在纯读预览增加不可确认的冻结排序与
原 probe 预检；以 `2026-10-19-j55b-frozen-preview-preflight-acceptance.md` 为当前进度。

## 交付边界

- `PlanCommandDTO` 替换无类型 `suggestedCommand` 与旧 `CompiledActionDTO`。
  统一 compiler 输出绝对数量、安全下限、覆盖集合、原 tier bounds、显式目标、
  evaluationVersion 与 canonical commandDigest。
- mapper 在最终 finding 状态确定后逐 probe 编译；unknown/needs_input/policy/
  pass 不产命令。缺显式组内专业配对、gap/edge、无显式配额的 ratio 不编造命令。
- 安全阈值仅为 effective target，原范围保留范围，未写长期用户目标。
- 新增 `POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/fix-proposals/preview`
  （`chatSessionId` 参数）：返回 `status=preview_only`、`sourceVersion`、最新
  `review.findings`、空 `proposals`。不生成假 proposalId/previewDigest/pending。
- 只读 loader 支持候选池拆分行；计算不保存 overlay/review，也不推进方案版本。
  缺状态/候选或 overlay 陈旧/缺失时返回 HTTP 409、body.code=40905、
  msg=`review_fix_stale`；通过专用异常映射避免全局异常处理误吞为 HTTP 200。
- 原 generate/runReview/prepare/apply/Python 工具路由未切换。
  无新 typed command 的旧 check 仅在 legacy 候选解析层恢复原策略 override，
  不为兼容旧卡片伪造新命令，不改全局 compensation 优先级。

## 验证证据

1. TDD：`ReviewCommandCompilationTest` 最初 7 项行为断言全部 RED，落实后通过；
   现另覆盖 unsupported gap/ratio。
2. `PlanCommandCompilerTest` 覆盖来源不完整拒绝、集合与顺序 digest 差异、深拷贝隔离。
   独立审查额外发现五项 P2，新增测试均复现 RED 后修复：当前数超目标时按权威
   target 而非当前数编译、缺绝对数量拒绝、不完整显式引用整体拒绝、未知策略拒绝、
   约束集合换序/重复不改变 digest。未将边界输入缺口夸大成已证实的执行漏洞。
   另补空方案的 admissionMode→volunteer 粒度回归，确保不因缺当前条目丢失 level。
3. `PlanningStateControllerReviewPreviewTest` 7 项通过，使用真实 controller/service/
   GlobalExceptionHandler，仅替换持久化与外部服务。覆盖重复预览、版本/存储不变、
   无 overlay/pending 写、stale 拒绝、缺状态不懒导入、拆分池只读回填。
4. 定向回归初次发现 ratio/gap 两项旧卡片状态由 preview_only 变 blocked；
   已在 legacy fallback 层修复。`PlanningStateServiceTest` 231 项零失败，3 项原有跳过。
5. 最终 `cd zhiyuan-server && mvn -o test`：1293 项，0 failure、0 error、10 skipped。
   未提供环境变量的可选快照测试包含在跳过项中，不能算作快照已验收。
   日志：`/tmp/j55a-full-test-final.log`。
6. 显式启用 `ReviewCommandGoldenTest`，读取十个会话的本地只读快照：
   900018/900028/900038/900040/900045/900016/900047/10041981/10041983/10041984。
   8 份有 review 的快照通过命令确定性/来源一致/输入不变断言；900016、900047
   当前快照无 review，显式报告跳过。日志：`/tmp/j55a-command-golden-final.log`。

## 已有 Golden 阻塞（未掩盖）

启用旧 `EvaluationGoldenShadowTest` 时，900018 的 safety_guard 对照失败
（旧 check 为 fail，当前 mapper 为 pass）。已将 HEAD 用 `git archive` 解出到
`/tmp/j55a-head-baseline.hMrMTJ`，未带本轮修改复跑，复现同一失败；基线的
`PlanningStateServiceTest` 同时零失败。日志：`/tmp/j55a-head-baseline.log`。

该测试自建 context 未填 J5.4 safetyFloorMode/safetyMinLocalProtect 等派生输入，
仍要求逐项等同历史 checks；不是本轮命令编译新增的判据变化。本轮未改断言、
未覆盖历史报告、未宣称“旧 Golden 10/10 绿”。b/c 切流前需更新完整评价输入的
对照夹具，并区分历史 check 差异与新 probe 的预期变化。

## 下一阶段门禁

- b：完整冻结后态物化（包括顺序/专业级动作）、最小原 probe evaluator 与预览
  preflight、prepare/pending/网关一次确认闭环、独立审查版本/计划内容 guard。
- apply：evaluationVersion 绑定来源而非整池失效；选择/动作相关硬事实变化才拒绝。
- c：Search effective patch 与明确授权 durable change 分离；普通 FILL 合规存量
  硬保留，REVIEW_FIX 只在授权范围换项；solver ready 但原 probe 未通过时禁止确认。
- 所有 a 命令仍 `executable=false`；当前不具备新确认卡或自动执行能力。
