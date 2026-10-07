# 数据侧请求：为演示合成会员开通 VOLUNTEER 取数策略（2026-10-08）

> 提出方：本机演示/验收环境维护侧。可直接转发数据侧。
> 相关记录：`docs/superpowers/reviews/2026-10-07-dialogue-engine-iteration-and-review.md` §六⑥。

## 一、现象

演示环境"新建会话（含从零采集的空会话）→ 更新成绩 → 确认"链路**稳定失败**：

- 卡片/预览可正常生成；
- 点确认后执行返回 **`84009 当前策略已失效，请刷新页面`**，卡片转"未生效"。
- 实例：会话 `10041975`（安徽 / 物理类 / 507 分），2026-10-08 07:31。

## 二、根因（已定位到"策略口径"层，非本地代码缺陷）

1. **上游省策略已切新一届**：直连实测（`/hl-wish/ci/selectSubjectPolicy/noToken/subjectPolicy`，
   2026-10-08）——
   - 浙江 `330000` → `prepareType=VOLUNTEER`、`year=2027`
   - 安徽 `340000` → `prepareType=VOLUNTEER`、`year=2027`
   - 江西 `360000` → `prepareType=VOLUNTEER`、`year=2027`

2. **本地按"策略优先"口径推导**：成绩更新请求未携带 prepareType 时，实时读省策略推导
   （`ScoreCatalogService.provinceDefaultsOrNull` → `GaotuClient.getSubjectPolicy`）。
   后端日志：`scoreUpdate: prepareType missing, filled province prepareType=VOLUNTEER province=340000`。

3. **确认执行按该策略取数被拒**：
   `ProgramPageReq(memberId=900002, prepareType=VOLUNTEER, score=507, areaId=340000, ...)`
   → 上游 `code:84009, msg:当前策略已失效，请刷新页面`。

4. **A/B 排除"年份不对"假设**（2026-10-08 07:46 实测）：以 `prepareType=VOLUNTEER` +
   **策略年 `examYear=2027`** 调外部初始化（创建时即触发全量拉数）——
   `ProgramPageReq(year=2027, memberId=900002, prepareType=VOLUNTEER, score=641, areaId=330000, ...)`
   → **仍 84009**，会话事务整体回滚（连会话都建不出来）。
   即：**900002 在 2026 与 2027 两个年份都没有 VOLUNTEER 取数策略**——断因是**账号策略缺失**，
   不是年份口径或"没有跟随上游策略"的问题（本地已按省策略实时推导 prepareType，属策略优先口径）。
   对照：同账号 **PREDICT 全量取数正常**（真拉取，同参数面）。

## 三、结论

演示用**合成会员（900002 等）目前只有 PREDICT（模拟填报）取数策略**；上游切 VOLUNTEER 后，

- 凡"策略优先"推出的 **VOLUNTEER 链路**（新建/空会话的补录确认；后续新会话的取数）都会断在 84009；
- 已存量的**旧会话**（自带 PREDICT）不受影响，演示可继续用它们。

（此前演示通道文档即已备注："待数据侧补齐 VOLUNTEER 策略后此差异消失"——本次即该差异的实锤。）

## 四、请求（二选一）

**A. 推荐**：为合成会员**开通/发布 VOLUNTEER 取数策略**（按 2027 届口径）——
至少 `900002`；如方便，`900001`/`900005` 一并。
使"从零采集 → 成绩确认 → 落库"全链可在新季策略下走通。

**B. 备选**：如短期无法开通，请**明示演示验收的指定口径**（例如"指定用携带 PREDICT 的存量会话"），
我方同步调整演示脚本与验收用例。

**C. 等价替代**（给存量会员开策略不方便时）：**新开一个带 VOLUNTEER 取数策略的测试会员**，
附可用登录手机号（或直接告知 memberId）——本环境登录时按手机号从上游用户系统换回 memberId
（`UserBizService` 登录链 ✓），换回后即可全链验证，效果与 A 等价。

## 五、证据附列

- 后端日志（2026-10-08 07:31:10 / 07:31:14）：`filled province prepareType=VOLUNTEER` 与
  `ProgramPageReq(... prepareType=VOLUNTEER ...)`、`84009` 原文；
- 网关日志：`execute stage response: status=failed code=84009`；
- 上游策略直连实测输出：三省均 `VOLUNTEER` + `year=2027`（2026-10-08 抓取）。
