---
status: PARTIAL
task: C4（浏览器自动化与真实交互验收矩阵）
source: docs/superpowers/plans/2026-09-20-codex-browser-validation.md（Task C4 段）
date: 2026-09-26
---

# C4 报告：骨架与第一个绿灯（做到第 1 个复选框）

> 评审入口：`docs/superpowers/tasks/2026-09-26-评审入口（C线三份与B6补充）.md` §4 ✓

> 本目录是为了让它**有可回收的落点** ✓（C4 此前既无任务目录也无报告 ✗，与 C2 同）。
> 实现会话写 ✓；**改动未提交** ✗。

## 一、这一轮做到哪

| C4 复选框 | 状态 |
|---|---|
| ① 安装浏览器测试依赖 + `test:e2e` + 装 Chromium | **做了一半** ✓✗：依赖与浏览器**都在容器里** ✓（见第二节的偏差 ✗）；`package.json` 的 `test:e2e` 脚本**还没加** ✗ |
| ② 假 Codex app-server + 18293 控制口 + `start-codex-contract.sh` | **四件里做完三件半** ✓：控制服务 ✓、带闸门替身 ✓、wrapper ✓、启动器 ✓（**唯一没做的**是把它们接起来跑一轮真栈 ✗ ✓）|
| ③ `playwright.config.ts`（缺 origin/session 必须失败 ✓） | **完成** ✓✓ |
| ④ 流式闸门用例（不依赖固定延时 ✓） | **未做** ✗（依赖 ② ✓）|
| ⑤ F01–F16 逐条断言 | **只做了 F14 的可自动化部分** ✓✗（`access.contract.spec.ts` ✓）|
| ⑥ 指标时间戳（受理回显 ≤1s 等） | **未做** ✗ |
| `npx tsc --noEmit` ✓ | **完成** ✓✓（结果见第三节 ✓）|

**新增文件** ✓：`zhiyuan-web/playwright.config.ts` ✓、
`zhiyuan-web/tests/e2e/access.contract.spec.ts` ✓、
`zhiyuan-web/tests/e2e/browser-smoke.mjs` ✓（只读冒烟 ✓）、
`scripts/run-codex-e2e-in-container.sh` ✓。

## 二、**必须偏离任务书的一处** ✗✓：e2e 在容器里跑

任务书写的是 `cd zhiyuan-web && npx playwright test --project=contract` ✓——**本机做不到** ✗：
宿主是 CentOS 7 / **glibc 2.17** ✗，Playwright 的 chromium 要 **GLIBC 2.18/2.25** ✗✗，
**这是地板问题** ✓（缺的 3 个库补上也过不去 ✓）。同理 Node 22 也跑不起来 ✗（要 2.27/2.28 ✗）。
探明过程与实测读数在 `docs/validation/codex-native-environment.md` §4.1 ✓。

因此多了 `scripts/run-codex-e2e-in-container.sh` ✓：`--network host` ✓（容器直连宿主回环 ✓）、
仓库**只读**挂载 ✓、**不给任何默认 origin** ✗（缺就拒 ✓）、浏览器缓存复用 ✓
（否则每次 `--rm` 都要重下 ~150MB ✗）。**宿主零改动** ✓，`docker rmi` 即可回退 ✓。

## 三、原始读数 ✓

**绿灯** ✓（容器内 ✓）：

```text
$ ZHIYUAN_E2E_ORIGIN=http://127.0.0.1:3001 \\
  ZHIYUAN_E2E_SESSION_URL=/assistant-pc/sessionDetailV2 \\
  bash scripts/run-codex-e2e-in-container.sh --project contract
Running 2 tests using 1 worker
  ✓  1 [contract] › tests/e2e/access.contract.spec.ts:9:5 › 会话页面能打开，且全程不碰内网路径 (458ms)
  ✓  2 [contract] › tests/e2e/access.contract.spec.ts:35:5 › 会话路由是**相对路径**，不是硬编码的域名 (2ms)
  2 passed (1.1s)
```

**红证据** ✓（任务书要求"首次必须因缺 origin/session 失败，不能默认打生产" ✓）：

```text
$ env -u ZHIYUAN_E2E_ORIGIN -u ZHIYUAN_E2E_SESSION_URL npx --no-install playwright test --project contract
退出码=1
Error: ZHIYUAN_E2E_ORIGIN required（页面 origin ✓，例如 http://127.0.0.1:3201）
```

**类型检查** ✓（C4 清单要求 ✓，同时补上 C2 报告自标未验的第 4 条 ✓）：

```text
$ npx --no-install tsc --noEmit --incremental false
退出码=2  错误总数: 24  ← **全是既有错误** ✓
  18  src/pages/userCenter/index.tsx
   4  src/pageComponents/session/subjectScores/index.tsx
   1  src/service/request/index.ts
   1  src/service/index.ts
```

**我碰过的文件一个都不在榜上** ✓✓（`MessageList/index.tsx` ✓、`conversationSocket.mjs` ✓、
`playwright.config.ts` ✓）——**24 是基线** ✓，此后谁跑都能一眼看出是不是自己弄坏的 ✓。

**依赖改动** ✓：`package.json` 只多一行 `"@playwright/test": "^1.55.0"` ✓（devDependencies ✓）。
lockfile 里 npm 顺手把 `webpack-sources` 从 `3.3.4` 升到 `3.5.3` ✗——**与本任务无关** ✗，
已按原值**精准还原** ✓（版本/resolved/integrity 三行 ✓）；唯一保留的删除行是根包
`0.1.0 → 3.0.0` ✓，那是 lockfile 与 `package.json` 对齐的**校正** ✓。JSON 已校验可解析 ✓。

## 四、自标未验 ✗

1. **`test:e2e` 脚本没加** ✗——因为本机的 `npm` 会连带改写 lockfile ✗；加脚本属于
   `package.json` 的小改 ✓，但我想跟依赖那次一起、在容器里做 ✓（下一轮 ✓）。
2. **假 Codex 闸门（②）整块未做** ✗——C4 的主体（流式不依赖固定延时 ✓、F01–F16 ✓）都在它上面 ✓。
3. **F14 只覆盖了"页面不碰内网路径"这一半** ✗；无票/错 Origin/过期票/跨用户那些 ✗ 要登录态 ✓（未做 ✓）。
4. **指标时间戳（⑥）未做** ✗。
5. 本轮踩到的三条环境坑（cwd 漂移 ✗、管道吞退出码 ✗、bash 4.2 空数组 ✗）已记入记忆
   `zhiyuan-env-traps` ✓——其中第二条**两次**让我把失败读成了成功 ✗✓。

---

## 五、续作（2026-09-26 晚，实现会话）：② 的四件

| 件 | 状态 | 证据 |
|---|---|---|
| `browser_runtime_control.py` ✓（18293 控制口 ✓） | 完成 ✓ | `test_browser_runtime_control.py` **5 passed** ✓：identity 说 fake 且**参数改不动它** ✓、**只许绑 loopback** ✓、放行一次性 ✓、**reset 只清指定 run** ✓✓、动作留痕 ✓ |
| `browser_app_server.py` ✓（带闸门替身 ✓） | 完成 ✓ | `test_browser_app_server.py` **4 passed** ✓：**放行前没有终态** ✓✓、中断发**真中断** ✓、超时**大声失败不补终态** ✓、注入的 turnId 被回显 ✓ |
| `browser_codex_wrapper.sh` ✓ | 完成 ✓ | 三条守卫当场验过 ✓ + 正常路真回了 `thread/start` 的 JSON-RPC ✓ |
| `scripts/start-codex-contract.sh` ✓ | 完成 ✓ | 干跑 ✓：identity=fake ✓ → 隔离栈按预期拒 ✓ → **控制服务被收干净**（18293 释放 ✓）；**被占就拒且不接管** ✓✓（占位进程仍持有端口 ✓）|

**测试当场抓出一个真缺陷** ✓✓：第一版替身是**单线程**的 ✗——`turn/start` 一进等待就把 stdin 阻塞 ✗，
`turn/interrupt` 永远读不到 ✗（F12"真中断"根本不可测 ✗）。已改成"等待放后台线程 ✓ + 终态只发一次 ✓ +
stdout 加锁 ✓"。

**前端 testid 盘点与补法** ✓（任务书要求"补 MessageList/卡片元素 data-testid" ✓）：

| testid | 状态 |
|---|---|
| `data-turn-id` ✓、`turn-progress` ✓、`turn-progress-step` ✓、`turn-stop` ✓ | 原本就有 ✓ |
| `chat-input` ✓、`chat-send` ✓ | **已补** ✓（`MessageList/index.tsx` 的 `Input` + `suffix` 里那个「发送」`Button` ✓；`tsc` 复核仍 24 = 基线 ✓✓）|
| `assistant-final` ✗ | **未补** ✗——`turn` 块里没有终态答案元素 ✓（它来自**消息列表**的渲染 ✓，在 2000+ 行文件的 JSX 深处 ✓）；定位到"消息列表渲染处"为止 ✓，未再往下翻 ✓ |

**一个搜索教训** ✓：先前按中文文案（"输入你的问题"）找输入框**找不到** ✗，
换成搜**属性名** `placeholder` 一击命中 ✓✓（文案会改 ✓、属性名不会 ✓——这也是为什么 e2e 要用 testid ✓）。

**下一步（下一步的第一件事）** ✗：补那 3 个 testid ✓ → 写 `tests/e2e/fixtures.ts` ✓
（**测试前校验 `runtimeKind=fake`** ✓，任务书点名 ✓）→ 写 `conversation.contract.spec.ts` ✓
（任务书给的那条流式断言 ✓：进度先到 ✓、终态未到 ✓、停止仍可点 ✓、放行后终态才到 ✓）→
起合同栈跑一轮 ✓（这是 ② 唯一没做的那半 ✓）。

### 5.1 续：流式用例与 fixtures（2026-09-26 深夜）

| 产物 | 要点 |
|---|---|
| `tests/e2e/fixtures.ts` ✓ | **跑任何 contract 用例前先问控制服务要 `identity`** ✓，不是 `runtimeKind=fake` 就让项目**直接失败** ✓（任务书："项目名本身不能决定 Runtime" ✓）；闸门封装成 `runtimeGate.releaseFinal(turnId)` ✓（**显式传参** ✓——我第一版用 `globalThis` 偷传 ✓✗，已改 ✗）；认证态没给就**失败** ✗（不静默跳过用匿名页冒充"已登录" ✗） |
| `tests/e2e/conversation.contract.spec.ts` ✓ | 任务书 ④ 那条流式断言 ✓：进度先到 ✓ → 停止仍可点 ✓ → **终态还没来** ✓✓ → 放行后终态才到 ✓。**"没有终态"之所以可信，是因为替身没放行就真的不发** ✓（不是"等得不够久" ✓✓）。缺 `chat-input`/`chat-send` 时**硬红** ✗——不写 skip ✓（任务书明令"不能 skip 后声称覆盖" ✗） |

**类型检查** ✓✓：`npx --no-install tsc --noEmit` 仍是 **24 个错误、同样那 4 个既有文件** ✓——
**新增的三个 e2e 文件零错误** ✓（`fixtures.ts` ✓、`conversation.contract.spec.ts` ✓、`playwright.config.ts` ✓）。

**下一步** ✗（② 唯一剩下的）：补 3 个 testid（`chat-input` ✗、`chat-send` ✗、`assistant-final` ✗——
输入区不在 `MessageList` ✓、也不在 `WorkspacePanel` 的那些位置 ✓，需再定位一次 ✓）→ 起合同栈跑一轮 ✓。
