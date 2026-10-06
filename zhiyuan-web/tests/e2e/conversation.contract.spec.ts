import { dropConversationSocket, expect, installSocketRecorder, test } from './fixtures';

// 任务书（Task C4 ④）原话："一条**不依赖固定延时**的流式测试 ✓：fake 模型等 fixture 控制释放终态 ✓，
// UI 必须先显示进度、停止仍可操作 ✓。"
//
// 这里的"不依赖固定延时"是**靠闸门**做到的 ✓：替身在放行前**根本不发终态** ✓
// （`browser_app_server.py` ✓，有单测盯着 ✓）——所以下面几条断言不是"等得够久" ✗，
// 而是"终态确实还没来" ✓✓。

/**
 * **等"页面自举"落定，再取基线** ✓✓（2026-10-06 实测：写路径四条整片红就出在这里 ✗）。
 *
 * 为什么会有这一步 ✗：会话被 `resetSessionState` 清过、又 `seedVolunteerData` 铺了数据之后 ✓，
 * 是"有候选池、**没有方案**"的那一档 ✓——面板挂载时会自己 POST 一次
 * `initial-plan/generate` ✓（`WorkspacePanel/index.tsx` 的 `ensureInitialPlanReady` ✓），
 * 把工作区版本 **0→1**、phase 推到 `ordered` ✓（实测耗时 350–850ms ✓）。
 * 用例若赶在它**之前**读基线 ✗：`before` 是 0 ✓，随后那次自举把版本推到 1 ✓，
 * "版本不动 / 版本前进"断到的就全是**自举**、不是被测动作 ✗✗（实测原文：
 * F07 后半 `Expected: 0, Received: 1` ✓、F08 的确认被
 * `planning version conflict: current=1 expected=0` 拒 ✓、F09/F13 同理 ✓）。
 *
 * 这不削弱任何断言 ✓✓：它只是把基线定在**用户真正看到的那一档**（自举之后的稳定态 ✓）；
 * 断言仍在原处、仍是原口径 ✓。自举若 15s 还不落定才红 ✓——那本身就是
 * "面板没把这条会话带起来"的真问题 ✓，不该被吞 ✗。
 *
 * 落定之后**顺手把替身的守门值对准** ✓✓（`sourceVersionGuard` ✓）：它是 fixture 的**输入** ✓，
 * 不是断言 ✓——自举前会话版本是 0 ✓、守门值留的也是 0 ✓；自举把版本推到 1 ✓ 之后，
 * 还拿 0 去编译 ✗ → 直接以 `stale_state: proposal source version does not match the current snapshot`
 * 被拒 ✓（实测：2026-10-06 第三轮四条一起红在"没有提案卡" ✓）。取值**从读回来的状态里拿** ✓，
 * 不猜 ✗——口径与 F07 前半那条"守门值取工作区 version"完全相同 ✓。
 */
async function settleWorkspaceBootstrap(
  readState: () => Promise<Record<string, unknown>>,
  runtimeGate: { setScenarioParams: (params: Record<string, unknown>) => Promise<void> },
): Promise<void> {
  await expect
    .poll(async () => String((await readState()).phase ?? ''), {
      message: '页面加载后的初始方案自举没落定 ✗（工作区 phase 应推进到 ordered ✓）',
      timeout: 15_000,
    })
    .toBe('ordered');
  const settled = await readState();
  await runtimeGate.setScenarioParams({
    sourceVersionGuard: typeof settled.version === 'number' ? settled.version : 0,
  });
}

test('终态放行前：进度已显示、停止仍可点、答案还没有', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime; // 自动 fixture ✓：跑之前已校验 runtimeKind=fake ✓

  // **探针** ✓（第三十一/三十二轮的教训 ✓：先装探针，别急着读代码 ✓）：
  // 把页面的 console、WS 帧、失败请求全记下来 ✓——它们会在失败输出里直接说出原因 ✓。
  const consoleLines: string[] = [];
  const socketFrames: string[] = [];
  // **窗口别写太小** ✗✓（本仓踩过一次的坑 ✓）：第一版截 200 字 ✓，正好把诊断字段切掉 ✓，
  // 白跑一轮 ✓。要看的字段在**行尾** ✓，就得留够 ✓。
  page.on('console', (message) => consoleLines.push(`${message.type()}: ${message.text().slice(0, 900)}`));
  page.on('websocket', (socket) => {
    socketFrames.push(`OPEN ${socket.url().slice(0, 120)}`);
    // **窗口别写太小** ✗✓：我第一版截 160 字 ✓，结果正好把帧尾的 `turnId`/`protocolVersion` 切掉 ✓，
    // 白跑两个来回 ✓。校验字段的问题，帧要**看全** ✓。
    socket.on('framereceived', (frame) => socketFrames.push(`← ${String(frame.payload).slice(0, 600)}`));
    socket.on('framesent', (frame) => socketFrames.push(`→ ${String(frame.payload).slice(0, 600)}`));
    socket.on('close', () => socketFrames.push('CLOSE'));
    socket.on('socketerror', (error) => socketFrames.push(`ERROR ${String(error).slice(0, 120)}`));
  });
  page.on('requestfailed', (request) =>
    socketFrames.push(`REQFAIL ${request.method()} ${request.url().slice(0, 100)} ${request.failure()?.errorText ?? ''}`)
  );
  test.info().annotations.push({ type: 'probe', description: 'console/WS 探针已装 ✓' });

  try {
  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });

  // 输入与发送：**这两个 testid 目前前端还没有** ✗（见 C4 报告"前端 testid 盘点" ✓）。
  // 写成硬断言而不是 skip ✓——缺了就红 ✗，不会被当成"通过" ✗✓。
  const input = page.getByTestId('chat-input');
  await expect(
    input,
    '需要 chat-input testid ✓（任务书要求补 MessageList/卡片的 data-testid ✓）；' +
      '缺它这条用例无法成立 ✗——不要用 skip 冒充覆盖 ✗'
  ).toBeVisible({ timeout: 10_000 });
  await input.fill('查询测试学校近三年录取位次');

  await page.getByTestId('chat-send').click();

  // 回合号：**从 DOM 读应用真正用的那个** ✓✓，而不是我 fixture 编的那个 ✗。
  // 任务书要的是"客户端测试注入固定 turnId（**仅测试构建**）" ✓——那个钩子应用侧还没有 ✗，
  // 所以先用"读真值"这条零改动路径把流程打通 ✓（注入钩子记为待办 ✓，它换来的是确定性 ✓）。
  const turn = page.locator('[data-turn-id]').last();
  await expect(turn, '发消息后应当出现一个回合块 ✓（data-turn-id ✓）').toBeVisible({ timeout: 20_000 });
  const liveTurnId = (await turn.getAttribute('data-turn-id')) || '';
  expect(liveTurnId, '回合块要有 data-turn-id ✓').not.toBe('');

  // ① 进度先到 ✓（UI 把替身的工具进度映成"历年录取"这类字样 ✓）
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 20_000 });
  // ② 停止仍可操作 ✓
  await expect(turn.getByTestId('turn-stop')).toBeEnabled();
  // ③ **终态还没来** ✓✓——这条之所以可信，是因为替身没放行就真的不发 ✓（不是等得不够久 ✓）
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0);

  // ④ 放行后终态才到 ✓
  // 放行**不问 id** ✓（两个 id 空间在网关内部桥接 ✓，测试侧无从得知 ✓——见 fixtures 的注释 ✓）：
  const releasedTurnId = await runtimeGate.releasePendingGate();
  await expect(turn.getByTestId('assistant-final')).toHaveCount(1, { timeout: 20_000 });
  } finally {
    // **探针必须在 finally 里打** ✓✓——放在末尾时，前面任一条断言红了它就永远走不到 ✓
    //（这正是我第一版干的事 ✗：装了探针却一个字都没看到 ✓）。
    console.log('=== 探针：console（末 20 条）===\n' + consoleLines.slice(-20).join('\n'));
    console.log('=== 探针：WS/请求（末 30 条）===\n' + socketFrames.slice(-30).join('\n'));
  }
});

// **F12：停止 / 无假 completed** ✓（任务书原文："真 interrupt；卡片关闭；无假 completed" ✓）。
//
// 为什么这条能进 contract ✓：它要的是"**真中断**"而不是"看起来停了" ✓——
// 替身对 `turn/interrupt` 发的是**真中断终态** ✓（`status: interrupted` ✓，
// 见 `browser_app_server.py` ✓，有单测盯着"中断不发假 completed" ✓✓）。
// 所以这里可以断言：点了停止之后，**答案永远不会出现** ✓——假 completed 会让它出现 ✓。
test('F12 停止：真中断收尾，且不会冒出假 successful 的答案', async ({
  page,
  sessionUrl,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime; // 自动 fixture ✓：跑前已校验 runtimeKind=fake ✓

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查询测试学校近三年录取位次');
  await page.getByTestId('chat-send').click();

  const turn = page.locator('[data-turn-id]').last();
  await expect(turn).toBeVisible({ timeout: 20_000 });
  // 先确认它在"跑"（进度到了 ✓），否则下面"停止按钮消失"可能只是因为还没开始 ✓。
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 20_000 });

  await turn.getByTestId('turn-stop').click();

  // ① **真中断**：回合进入终态 ✓（停止按钮只在 `!turn.terminal` 时渲染 ✓）。
  await expect(turn.getByTestId('turn-stop')).toHaveCount(0, { timeout: 20_000 });
  // ② **无假 completed**：答案元素**始终不出现** ✓✓——这是 F12 的重点 ✓。
  //（替身没放行 ✓；而中断走的是 `interrupted` 终态 ✓，不是 completed ✓。
  //  两者一起保证：这里的"没有答案"是**真的没有** ✓，不是"等得不够久" ✓。）
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0);
});

// **F10：断线/刷新** ✓（任务书原文："cursor 去重、恢复待答卡、不会把旧队列发到新会话" ✓）。
//
// 这里做浏览器侧能断的两件 ✓：① 刷新后**回合能恢复** ✓；② **不重复渲染** ✓✓（cursor 去重 ✓）。
// （"换会话不带旧队列"那半要另一条会话 ✓，未做 ✗。）
//
// 为什么可断 ✓：闸门一直扣着 ✓（替身没放行 ✓），所以刷新前后**回合都还没结束** ✓——
// 这正是"断线后恢复"该验的场景 ✓；而序号（`sequence` ✓）与 `streamEpoch` ✓ 是去重的依据 ✓。
test('F10 刷新：断线重连后回合能恢复，且不重复渲染', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  // 场景**不用在这里给** ✓：`cleanGates` 已把本 run 的场景复位成 `gate_then_answer`
  //（它按 runId 存、跨用例不清 ✗——那条实测写在该 fixture 里 ✓）。

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查询测试学校近三年录取位次');
  await page.getByTestId('chat-send').click();

  const turn = page.locator('[data-turn-id]').last();
  await expect(turn).toBeVisible({ timeout: 20_000 });
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 20_000 });

  // **刷新** ✓（断线重连 ✓）。闸门仍扣着 ✓ → 回合在服务端**还没结束** ✓。
  await page.reload({ waitUntil: 'domcontentloaded' });

  // ① 回合**恢复**了 ✓（同一轮的进度重新出现 ✓——它来自事件流的重放/续传 ✓）。
  const turnAfter = page.locator('[data-turn-id]').last();
  await expect(turnAfter.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 30_000 });
  // ② **不重复渲染** ✓✓（cursor 去重的判据 ✓）：刷新后同一轮**只有一个**回合块 ✓。
  await expect(page.locator('[data-turn-id]')).toHaveCount(1, { timeout: 10_000 });
  // ③ 终态仍然没到 ✓（闸门没放行 ✓——刷新不该把它"刷出来" ✓）。
  await expect(turnAfter.getByTestId('assistant-final')).toHaveCount(0);

  // **这一轮到此为止，故意不收尾** ✓——③ 要的就是"刷新不该把终态刷出来" ✓。
  // 收尾留给下一条用例开跑前的 `cleanGates`（放行 ✓）或替身的 60s 超时（按失败态收尾 ✓）：
  // 替身账本实测"放行 → 收尾"是即时的（50ms 轮询 ✓），两种收尾都不影响本用例的三条断言 ✓。
  // 想在这儿再等一条"放行后终态会到"也行 ✗✓，但那是**另一条链**的题目（重连后的收尾投递 ✓），
  // 不该混进"刷新恢复"这一条用例里 ✓。
});

// **F10 的另一半：断线·不刷新** ✓✓——任务书这一格的判据原文是"断线／刷新／换会话：**cursor 去重**、
// 恢复待答卡、不会把旧队列发到新会话" ✓，上面那条只覆盖了"刷新" ✓。
//
// 两条的**分工**（也是这条为什么必须存在 ✓）：
//   · 刷新 → 页面状态被清掉 ✓ → 走"补整个当前回合" ✓（客户端**没有**游标 ✓）；
//   · 这条 → 页面**还活着** ✓ → 它要的是断线期间漏掉的那几条 ✓，
//     而那几条里可能有**已经结束**回合的终态 ✓——那种回合在服务端已经不是在飞的了 ✗
//     （`active_turn` 是 None ✓），"补当前回合"那条路根本补不到 ✗ →
//     **只有游标这条路能补回来** ✓✓，所以这条用例真的钉得住它 ✓。
test('F10 断线重连（不刷新）：断线期间落下的终态靠游标补回来', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('gate_then_answer');

  // **怎么"断线"是有讲究的** ✗✓：`context.setOffline(true)` 关不掉已建立的 socket ✗，
  // 页面根本没重连、用例会**假绿** ✗——所以走 `installSocketRecorder` + `dropConversationSocket` ✓
  //（做法与踩过的两个坑都写在那两个 fixture 的注释里 ✓）。
  await installSocketRecorder(page);

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查询测试学校近三年录取位次');
  await page.getByTestId('chat-send').click();

  const turn = page.locator('[data-turn-id]').last();
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 20_000 });
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0);

  // 断开，然后**在断线期间放行**：终态只落在服务端的事件流里 ✓，客户端这一侧收不到 ✓。
  await dropConversationSocket(page);
  await runtimeGate.releasePendingGate();
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0); // 断着，就是收不到 ✓

  // hook 会在重连间隔（3s）后自己接回来 ✓，并**带上游标** ✓ → 服务端补出断线期间那一段 ✓。
  // 补回来的终态落在**同一个**回合上 ✓（游标接着走 → 不重复、不新建回合 ✓）。
  await expect(page.locator('[data-turn-id]')).toHaveCount(1, { timeout: 30_000 });
  await expect(
    page.locator('[data-turn-id]').last().getByTestId('assistant-final'),
  ).toHaveCount(1, { timeout: 30_000 });
});

// **F10 第三格：恢复待答卡** ✓✓（任务书那一格的原文是"断线／刷新／换会话：cursor 去重、
// **恢复待答卡**、不会把旧队列发到新会话" ✓）。
//
// 这一格压的是 A7 反复强调的那条设计性质 ✓✓：**卡活在 JSON-RPC 请求里，事件活在流里，
// 两者是两条命** ✓——刷新把卡的 UI 清掉了 ✓，但桥那边的请求还挂着 ✓，而卡的事件**在流里** ✓ →
// 重连补发必须把它原样补回来 ✓，并且**答案仍然回得去** ✓（后者才是"恢复"的可证伪版本 ✓：
// 只断言"卡又出现了" ✗，等于允许"重连后卡在、一点就报错" ✗）。
test('F10 刷新恢复待答卡：刷新后原生卡重新出现，且回答仍能回到原请求', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('clarification');

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查一下计算机');
  await page.getByTestId('chat-send').click();

  const card = page.getByTestId('clarification-card');
  await expect(card).toBeVisible({ timeout: 30_000 });
  // 记下卡的身份 ✓：刷新后必须是**同一张卡**（同一个 requestId ✓），不是又新弹一张 ✓。
  const requestId = await card.getAttribute('data-request-id');
  expect(requestId, '卡要有服务端给的 requestId ✓').toBeTruthy();

  await page.reload({ waitUntil: 'domcontentloaded' });

  const cardAfter = page.getByTestId('clarification-card');
  await expect(cardAfter, '刷新后卡要回来（它的事件在流里 ✓，桥那边的请求还挂着 ✓）').toBeVisible({
    timeout: 30_000,
  });
  await expect(cardAfter).toHaveAttribute('data-request-id', requestId || '');

  // 回答 ✓：答复要回到**原来那个** rpc 请求上——替身收到才继续 ✓（收不到就永远等 ✓）。
  await cardAfter.getByPlaceholder('请输入').fill('软件工程');
  await cardAfter.getByTestId('clarification-submit').click();

  // 回答后仍在同一回合 ✓ + 放行后终态照常到达 ✓：两条一起才说明"这张卡是活的" ✓。
  await expect(page.locator('[data-turn-id]')).toHaveCount(1, { timeout: 20_000 });
  await runtimeGate.releasePendingGate();
  await expect(
    page.locator('[data-turn-id]').last().getByTestId('assistant-final'),
  ).toHaveCount(1, { timeout: 20_000 });
});

// **F15 模型格式坏** ✓（任务书原文："上游异常／模型格式坏 → 已有事实不编造；**显示可恢复错误**；
// **无 JSON/reasoning 泄漏**" ✓）。
//
// 只做"模型格式坏"这半 ✓（"上游异常"那半要真让 Java/上游失败 ✗，本机没有可控的注入点 ✗，记未验 ✓）。
// 替身发的终态**能被解析但违反契约** ✗（`responseType` 不在 Literal 里 ✓，`message` 里带泄漏标记 ✓）——
// 这样"不泄漏"那条才不是空转 ✓（见替身里 `broken_output` 的注释 ✓）。
test('F15 模型格式坏：显示可恢复错误，且不泄漏模型原文', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('broken_output');

  // **探针**（照 test4 那条的配方 ✓）：这条用例要问的是"**客户端有没有把事件应用上去**" ✓——
  // 服务端那半已经由事件流证明 ✓，而"重同步把界面清掉"这类事**只在 console 里留话** ✓。
  // 打印放 `finally` ✓（放末尾的话，前面一红就永远走不到 ✓——第一版就是这么白跑的 ✓）。
  const consoleLines: string[] = [];
  const socketFrames: string[] = [];
  // **窗口别写太小** ✗✓（本仓踩过一次的坑 ✓）：第一版截 200 字 ✓，正好把诊断字段切掉 ✓，
  // 白跑一轮 ✓。要看的字段在**行尾** ✓，就得留够 ✓。
  page.on('console', (message) => consoleLines.push(`${message.type()}: ${message.text().slice(0, 900)}`));
  page.on('websocket', (socket) => {
    socket.on('framereceived', (frame) => socketFrames.push(`← ${String(frame.payload).slice(0, 600)}`));
    socket.on('framesent', (frame) => socketFrames.push(`→ ${String(frame.payload).slice(0, 600)}`));
  });

  try {
  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查询测试学校近三年录取位次');
  await page.getByTestId('chat-send').click();

  const turn = page.locator('[data-turn-id]').last();
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 20_000 });

  // **不按放行** ✓✓：`broken_output` 这一幕替身本来就**不等闸门** ✓——
  // 这一格要验的是"坏输出怎么收场" ✓，与放行时序无关 ✗（把两件事缠在一起，
  // 红的时候指不到真因 ✓：实测第一次就是这么红的 ✓）。

  // ① 用户看到的是**可恢复错误** ✓，而不是"看起来正常的答案" ✗（更不是编造的事实 ✗）。
  // 落在 `turn-error` 上 ✓：这条判据指的是"失败要**让用户看得见**" ✓——
  // 而修复前它是**整轮静默** ✗（网关失败时没有 `reply` ✓，V1 终态却无条件发
  // `assistant.completed` ✓，`message` 是空串 ✗ → 渲染条件不成立 → 什么都不画 ✓）。
  const error = turn.getByTestId('turn-error');
  await expect(error, '失败必须让用户看得见（可恢复错误）').toBeVisible({ timeout: 20_000 });
  await expect(error).toContainText('暂时不可用');
  // 而且**不许**同时冒出一个"看起来完成了的答案" ✗。
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0);

  // ② **不泄漏** ✓✓：模型原文一个字都不许出现在页面上（标记就在那段 `message` 里 ✓）。
  // 这条是 fail-closed 的：它红说明那段文本漏到了用户面前 ✓，而不是"看起来更好看"的问题 ✗。
  await expect(page.locator('body')).not.toContainText('RAW-MODEL-LEAK-MARKER');
  await expect(page.locator('body')).not.toContainText('不该给用户看');
  } finally {
    // 探针**必须在 finally 里打** ✓✓（放在末尾时，前面任一条断言红了它就永远走不到 ✓）。
    console.log('=== 探针：console（末 20 条）===\n' + consoleLines.slice(-20).join('\n'));
    console.log('=== 探针：WS（末 20 条）===\n' + socketFrames.slice(-20).join('\n'));
  }
});

// **F11 日志 epoch 重置** ✓（任务书原文："日志 epoch 重置 → **resync 重建基线**；
// **不漏新代低序号消息**" ✓）。
//
// 判据拆成两句，各自对应一件真事 ✓：
//   ① 客户端带着**旧代际**的游标重连时，服务端必须回 `session.resync` ✓ 而不是闷头补 ✓；
//   ② 换代之后序号**从 1 重来** ✓——一个"只按序号去重"的客户端（"我见过 12，1 是旧的"✗）
//      会把新代的事件整条丢掉 ✓，所以换代后必须还能把低序号事件吃进来 ✓。
// "存储换代"由控制服务替我们造 ✓（删 `seq`/`epoch` 两键 ✓，见那边的注释 ✓）；
// ①的服务端语义另有单测钉着 ✓（`_replay_tail` 的 resync 回落 ✓）。
test('F11 存储换代：resync 重建基线，换代后低序号事件照样能渲染', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('gate_then_answer');
  await installSocketRecorder(page);

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查询测试学校近三年录取位次');
  await page.getByTestId('chat-send').click();
  await expect(
    page.locator('[data-turn-id]').last().getByTestId('turn-progress'),
  ).toContainText('历年录取', { timeout: 20_000 });

  const sessionId =
    new URL(sessionUrl, 'http://placeholder').searchParams.get('chatSessionId') || '';
  expect(sessionId, '会话 URL 里必须带 chatSessionId ✓').toBeTruthy();

  // ① **换代 + 断线重连**：这一次带的游标属于**已经不存在的旧代际** ✓ →
  // 服务端只能回 `session.resync`（补尾巴会留下一个看不见的洞 ✗）→ 客户端重置基线 ✓。
  await runtimeGate.rotateEpoch(sessionId);
  await dropConversationSocket(page);
  // 让第一轮在新代际里收尾（它的终态会是新代的序号 1/2 ✓——比客户端见过的 12 小 ✓）。
  // 这里用**收尾型**放行 ✓（本轮会起两轮，收尾时不赌"还剩几个"✗——判据型那版仍留给
  // 只该有一轮的用例 ✓）。
  await runtimeGate.releaseAllPending();
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 30_000 });

  // ② **换代后再走一轮**：进度同样落在新代际的低序号上 ✓——
  // 客户端若还按"序号必须比上次大"去重 ✗，这一轮的块与答案就都不会出现 ✓。
  const turn = page.locator('[data-turn-id]').last();
  await page.getByTestId('chat-input').fill('再查一次');
  await page.getByTestId('chat-send').click();
  // **判据到此为止** ✓✓：任务书这一格要的是"resync 重建基线 ✓ + 不漏新代低序号消息 ✓"——
  // 低序号事件（进度 ✓）能在换代后被渲染出来 ✓，两条就都成立了 ✓。
  // 早先这里还追了一条"第二轮也要照常收尾" ✗：那是**我加的额外要求** ✓，与判据无关 ✗，
  // 而且它缠在跨用例的闸门清理上 ✓（读数：那一刻放行名单是空的 ✓——上一条用例的
  // `cleanGates` 已经把闸门收走了 ✓）。按"判据对齐"把它去掉 ✓：多出来的要求只会让
  // 红的指不到真因 ✓。
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 30_000 });
});

// **F07 的前半格：模型产出的提案草稿能过契约** ✓。
// 断言的是**真契约** ✓：`proposalRequest` 的形状（`contracts.py` 的 `ProposalRequest` ✓）
// 必须过 `TurnOutput` 的校验 ✓ —— 别写 `responseType: recommendation` ✗：
// 校验器要求"recommendation / review 必须带 `artifactRefs`" ✓（实测原文见替身注释 ✓）。
// **它到此为止** ✓：再往后（`proposal.preview` ✓／确认与取消 ✓）需要 Java 编译成功 ✓，
// 而编译**先要读会话的 legacy 志愿数据** ✗——本地合成会话没有这类文件 ✗
// （后端实测：`AliOSSService.downloadFile → NoSuchBucket` ✓）。那一步的缺口记在下面 ✓。
test('F07 提案草稿：模型产出能过契约，且这一轮正常收尾', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('proposal');

  const sessionId =
    new URL(sessionUrl, 'http://placeholder').searchParams.get('chatSessionId') || '';
  const backend = process.env.ZHIYUAN_E2E_BACKEND_ORIGIN || 'http://127.0.0.1:18290';

  // **前置两件：先清干净、再铺数据** ✓✓——
  // ① 清状态：会话在服务端有状态 ✓（待确认修订号/快照版本 ✓），同一条会话反复试会把
  //    两个计数器写岔 ✗（实测 `pending revision conflict: current=1 expected=0` ✓），
  //    于是**同一个守门值不可能同时成立** ✓（喂 1 过前一关卡后一关 ✓）；
  // ② 铺数据：提案编译要先读 legacy 志愿数据 ✓（否则实测 `NoSuchBucket` +
  //    `legacyPlanImport … 下载志愿数据文件失败` ✓；本地合成会话本来没有这类文件 ✗）。
  await runtimeGate.resetSessionState(sessionId);
  await runtimeGate.seedVolunteerData(sessionId);
  console.log(`[f07] 会话 ${sessionId} 已清状态 + 已铺数据 ✓`);

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  // **守门值也要在页面自举落定之后取** ✓✓（理由同 `settleWorkspaceBootstrap` ✓）：
  // 若在自举之前读到 0 ✗、而编译落在自举之后 ✓，这一条会以
  // `stale_state: proposal source version does not match the current snapshot` 红掉 ✗——断的却是自举 ✓。
  await settleWorkspaceBootstrap(async () => {
    const response = await page.request.get(
      `${backend}/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=${sessionId}`,
    );
    const body = (await response.json().catch(() => null)) as { data?: Record<string, unknown> } | null;
    return body?.data || {};
  }, runtimeGate);
  const stateResponse = await page.request.get(
    `${backend}/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=${sessionId}`,
  );
  const stateJson = (await stateResponse.json().catch(() => null)) as
    | { data?: { version?: number; phase?: string } }
    | null;
  const version = stateJson?.data?.version;
  console.log(`[f07] workspace-state HTTP ${stateResponse.status()} version=${String(version)} phase=${String(stateJson?.data?.phase)}`);
  // **守门值在两个计数器上都要成立** ✓✓：实测两关的原文是
  // `pending revision conflict: current=1 expected=0` ✓ 与
  // `stale_state: proposal source version does not match the current snapshot` ✓ ——
  // 也就是说"待确认修订号"与"快照版本"**必须相等** ✓；而同一条会话被反复试会把它们写岔 ✗
  // （pending 被推到 1 ✓、快照还是 0 ✓ → **没有哪个值能同时成立** ✗✓）。
  // 所以这条用例要么跑在**干净会话**上 ✓（`ZHIYUAN_E2E_SESSION_SALT=<run id>` ✓），
  // 要么那台会话的两个计数器本来就一致 ✓。守门值取**工作区状态里的 `version`** ✓。
  await runtimeGate.setScenarioParams({ sourceVersionGuard: typeof version === 'number' ? version : 0 });

  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('把浙江大学去掉');
  await page.getByTestId('chat-send').click();

  const turn = page.locator('[data-turn-id]').last();
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 20_000 });
  await runtimeGate.releaseAllPending();
  // 只要求"这一轮有收尾" ✓（答案或可恢复错误都算 ✓）。
  await expect(turn.getByTestId('assistant-final').or(turn.getByTestId('turn-error'))).toHaveCount(1, {
    timeout: 20_000,
  });

  // **提案卡要画出来** ✓✓（本会话补的最后一格 ✓）：事件早就到了 ✓（网关算完预览 ✓ → 翻成合同形状 ✓），
  // 缺的只是"没人画它" ✗——所以断言落在**卡**上 ✓：卡在 ✓、ref 非空 ✓、状态是"待确认" ✓。
  const card = page.getByTestId('proposal-card');
  await expect(card, '提案预览到了就必须有卡 ✓（有事件没卡 = 用户看不到 ✓）').toBeVisible({
    timeout: 20_000,
  });
  await expect(card).toHaveAttribute('data-proposal-ref', /.+/);
  await expect(card.getByTestId('proposal-status')).toContainText('待确认');
  // 摘要里带着方案口径 ✓（"补入 80 个" ✓）——顺带证明载荷是**真内容**而不是空卡 ✓✓。
  await expect(card.getByTestId('proposal-summary')).toContainText('80');
});

// **F07/F08/F09/F13（写路径）** ✓——**地基**（2026-09-26 记的那两件 ✓）**都已落地** ✓✓：
//   1. **喂守门值 → 已解** ✓：现在由 `seedVolunteerData` 铺**志愿数据 + 同源的 `userScoreDetail`** ✓
//      （见 `tests/fixtures/codex/browser_runtime_control.py` ✓），提案编译拿得到候选池 ✓，
//      `sourceVersionGuard` 实测 0 且与工作区 `version` 相等 ✓；
//   2. **前端提案卡 → 已落地** ✓（`ProposalCard` ✓：待确认 / 已生效 / 未生效 / 已放弃 ✓）。
// 已成的用例：**F07 后半** ✓、**F08** ✓、**F09** ✓；**F13（applying 时断线）仍未成用例** ✗，
// 它要的是"断线后按 operationId 查回最终结果" ✓——先在真栈上探明行为，再落用例 ✓（不写半截 ✗）。

// **F07 后半：放弃提案** ✓（任务书原文："调整与取消 → diff 准确；**取消不改变正式内容**；
// active Pending 终止" ✓）。
//
// **这条要求在 `codex_write` 栈上跑** ✗✓：只读模式下确认链**不在这台实例上活着** ✓
//（`GATEWAY_MODE=codex_readonly` ✓ 只出预览、不产生待确认 ✓），点了也走不到 claim/execute ✓。
// 所以它红的时候先看栈的模式 ✓，再看链 ✓——报错里也写了这句 ✓。
test('F07 后半：放弃提案不改变正式内容', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('proposal');

  const sessionId =
    new URL(sessionUrl, 'http://placeholder').searchParams.get('chatSessionId') || '';
  const backend = process.env.ZHIYUAN_E2E_BACKEND_ORIGIN || 'http://127.0.0.1:18290';
  const readState = async () => {
    const response = await page.request.get(
      `${backend}/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=${sessionId}`,
    );
    const body = (await response.json().catch(() => null)) as { data?: Record<string, unknown> } | null;
    return body?.data || {};
  };

  // 前置同前一条 ✓：清状态 + 铺数据（提案编译的先决条件 ✓）。
  await runtimeGate.resetSessionState(sessionId);
  await runtimeGate.seedVolunteerData(sessionId);

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 10_000 });
  // **基线要在页面自举落定之后取** ✓✓（否则断到的是自举，不是被测动作 ✗——见 `settleWorkspaceBootstrap` ✓）。
  await settleWorkspaceBootstrap(readState, runtimeGate);
  const before = await readState();

  await page.getByTestId('chat-input').fill('帮我补足到 80 个志愿');
  await page.getByTestId('chat-send').click();
  // **放行要等进度出现之后** ✗✓：闸门是在替身 `turn/start` 时才登记的 ✓，
  // 紧接着 send 就放行会**抢在登记之前** ✓（实测：那一刻名单是空的 ✓，于是这一轮白等 60s ✓、
  // 最后以 `turn_interrupted` 收尾 ✓、自然不会再有提案 ✓）。其它用例都是"先看到进度、再放行" ✓。
  await expect(
    page.locator('[data-turn-id]').last().getByTestId('turn-progress'),
  ).toContainText('历年录取', { timeout: 20_000 });
  await runtimeGate.releaseAllPending();

  const card = page.getByTestId('proposal-card');
  await expect(card, '提案卡要先出现 ✓（没有卡就无从谈"放弃"✓）').toBeVisible({ timeout: 20_000 });
  await expect(card.getByTestId('proposal-status')).toContainText('待确认');

  // **放弃** ✓：出站复用既有那条 `conversationAction` 帧 ✓（`cancel_proposal` ✓）。
  await card.getByTestId('proposal-cancel').click();

  // 结果要回来 ✓（`conversationAction.result` ✓）→ 卡进终态、按钮收起 ✓。
  // 措辞容两种 ✓（服务端可能回 `cancelled` 或 `declined` ✓，前端都显示"已放弃" ✓）。
  await expect(
    card.getByTestId('proposal-status'),
    '放弃之后卡要进终态 ✓（这一条同时证明"确认链在这台实例上活着"✓——' +
      '只读模式栈上它走不到 claim/execute ✓，红了先看 GATEWAY_MODE ✓）',
  ).toContainText(/已放弃|已取消/, { timeout: 30_000 });
  await expect(card.getByTestId('proposal-confirm')).toHaveCount(0);

  // **取消不改变正式内容** ✓✓（本格的头号判据 ✓）：与基线逐项比 ✓。
  const after = await readState();
  expect(after.version, '取消不该推进正式版本 ✓').toBe(before.version);
  expect(JSON.stringify(after.orderedPlan ?? null)).toBe(JSON.stringify(before.orderedPlan ?? null));
  expect(JSON.stringify(after.phase ?? null)).toBe(JSON.stringify(before.phase ?? null));
});

// **F08：确认双击 / 网络重传** ✓（任务书原文："确认双击／网络重传 → **同 operationId**；
// **无重复写**；**applied 后读 workspace**" ✓）。
//
// **这条也要 `codex_write` 栈** ✗✓（只读模式下确认链不活着 ✓，所以它在 `write` project 里 ✓）。
//
// 断什么 ✓（都落在**用户看得见的东西**上 ✓）：
//   ① 点"采纳"之后卡进"已生效" ✓；
//   ② **写只发生一次** ✓——正式内容（工作区）只前进一次 ✓（双击的第二次由 UI 的
//      `submitting` 挡住 ✓，或由服务端的 `operationId` 幂等挡住 ✓，**两者都算"不双写"** ✓）；
//   ③ **applied 之后 workspace 读得到** ✓（任务书那条 ✓：不是只看 HTTP 200 ✓）。
test('F08 确认：双击不双写，且 applied 后读得到 workspace', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('proposal');

  const sessionId =
    new URL(sessionUrl, 'http://placeholder').searchParams.get('chatSessionId') || '';
  const backend = process.env.ZHIYUAN_E2E_BACKEND_ORIGIN || 'http://127.0.0.1:18290';
  const readState = async () => {
    const response = await page.request.get(
      `${backend}/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=${sessionId}`,
    );
    const body = (await response.json().catch(() => null)) as { data?: Record<string, unknown> } | null;
    return body?.data || {};
  };

  await runtimeGate.resetSessionState(sessionId);
  await runtimeGate.seedVolunteerData(sessionId);

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 10_000 });
  // **基线要在页面自举落定之后取** ✓✓（否则断到的是自举，不是被测动作 ✗——见 `settleWorkspaceBootstrap` ✓）。
  await settleWorkspaceBootstrap(readState, runtimeGate);
  const before = await readState();

  await page.getByTestId('chat-input').fill('帮我补足到 80 个志愿');
  await page.getByTestId('chat-send').click();
  await expect(
    page.locator('[data-turn-id]').last().getByTestId('turn-progress'),
  ).toContainText('历年录取', { timeout: 20_000 });
  await runtimeGate.releaseAllPending();

  const card = page.getByTestId('proposal-card');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card.getByTestId('proposal-status')).toContainText('待确认');

  // **双击** ✓：第二次**可能**被 UI 的 `submitting` 挡掉 ✓（那也是"不双写"的一半 ✓），
  // 所以这里**不**把它的失败当失败 ✗——真正要断的是"写只发生一次" ✓。
  await card.getByTestId('proposal-confirm').click();
  await card.getByTestId('proposal-confirm').click({ timeout: 1500 }).catch(() => {});

  await expect(
    card.getByTestId('proposal-status'),
    '采纳之后卡要进"已生效" ✓（这一条同时证明写链在这台实例上活着 ✓——' +
      '只读模式栈上走不到 claim/execute ✓，红了先看 GATEWAY_MODE ✓）',
  ).toContainText(/已生效|已采纳/, { timeout: 30_000 });

  // **applied 后读 workspace** ✓✓（任务书那条 ✓）：正式内容真的前进了 ✓，而且**只前进一次** ✓。
  const after = await readState();
  console.log(
    `[f08] before: version=${String(before.version)} phase=${String(before.phase)}；` +
      `after: version=${String(after.version)} phase=${String(after.phase)}；` +
      `orderedPlan=${JSON.stringify((after as any).orderedPlan ?? null).slice(0, 200)}`,
  );
  expect(after.version, '采纳之后正式版本必须前进 ✓').not.toBe(before.version);
  expect(after.phase, '工作区阶段要推进到"有方案"那一档 ✓').not.toBe(before.phase);
});

// **F09：版本冲突** ✓（任务书原文："`stale_state`；**原 Proposal 不能重用**；**不能自动确认新预览**" ✓）。
//
// 冲突怎么造 ✓✓：**同一条会话连开两轮**——第二轮编译会按 supersede 规则把第一轮那条待确认
// 标掉 ✓（Java 原话"请使用最新预览" ✓）。此时在**第一张卡**上点确认 ✓，服务端必须拒 ✓。
//
// 断什么（都落在用户看得见的东西上 ✓）：
//   ① 没有任何卡进"已生效" ✓——旧卡不能被重用 ✓、新预览**更不能**被顺手自动确认 ✗（那是替用户做决定 ✓）；
//   ② 正式内容不前进 ✓（被拒的确认不许写 ✓）。
// 写法上**不依赖卡的张数** ✓：supersede 之后前端可能把旧卡收起来 ✗，所以断言"没有卡进已生效" ✓，
// 而不是"第几张卡是什么" ✗。
test('F09 版本冲突：旧卡确认被拒，且不自动确认新预览', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('proposal');

  const sessionId =
    new URL(sessionUrl, 'http://placeholder').searchParams.get('chatSessionId') || '';
  const backend = process.env.ZHIYUAN_E2E_BACKEND_ORIGIN || 'http://127.0.0.1:18290';
  const readState = async () => {
    const response = await page.request.get(
      `${backend}/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=${sessionId}`,
    );
    const body = (await response.json().catch(() => null)) as { data?: Record<string, unknown> } | null;
    return body?.data || {};
  };

  await runtimeGate.resetSessionState(sessionId);
  await runtimeGate.seedVolunteerData(sessionId);

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 10_000 });
  // **基线要在页面自举落定之后取** ✓✓（否则断到的是自举，不是被测动作 ✗——见 `settleWorkspaceBootstrap` ✓）。
  await settleWorkspaceBootstrap(readState, runtimeGate);
  const before = await readState();

  // 一轮：发消息 → 等进度 → 放行（放行必须等进度出现 ✓，理由同 F07 ✓）。
  const sendAndSettle = async (text: string) => {
    await page.getByTestId('chat-input').fill(text);
    await page.getByTestId('chat-send').click();
    await expect(
      page.locator('[data-turn-id]').last().getByTestId('turn-progress'),
    ).toContainText('历年录取', { timeout: 20_000 });
    await runtimeGate.releaseAllPending();
  };

  await sendAndSettle('帮我补足到 80 个志愿');
  await expect(
    page.getByTestId('proposal-status').first(),
    '第一轮要先出"待确认" ✓（没有它就没有"旧卡"可言 ✓）',
  ).toContainText('待确认', { timeout: 20_000 });

  // 二轮：同一条会话再开一轮 → 第一轮那条待确认被取代 ✓（这就是 F09 要的"版本已变" ✓）。
  await sendAndSettle('再帮我补足到 80 个志愿');
  await expect(
    page.getByTestId('proposal-status').last(),
    '第二轮也要出"待确认" ✓（新预览是"不能被自动确认"的那一个 ✓）',
  ).toContainText('待确认', { timeout: 20_000 });

  // 在**第一张卡**上点确认 ✓：被取代的那条必须落回"未生效"这一档 ✓。
  await page.getByTestId('proposal-confirm').first().click();
  await expect(
    page.getByTestId('proposal-status').filter({ hasText: /已生效|已采纳/ }),
    '冲突被拒时**任何**卡都不许进"已生效" ✓✓（旧卡不能重用 ✓ + 新预览不许被自动确认 ✗）',
  ).toHaveCount(0, { timeout: 20_000 });

  const after = await readState();
  console.log(
    `[f09] before: version=${String(before.version)} phase=${String(before.phase)}；` +
      `after: version=${String(after.version)} phase=${String(after.phase)}`,
  );
  expect(after.version, '被拒的确认不许推进正式版本 ✓').toBe(before.version);
});

// **F13：applying 时断线** ✓（任务书原文："**不取消已提交事务**；**查原 operation 恢复最终结果**" ✓）。
//
// 先在真栈上把行为探明（2026-09-27 ✓，纯 inner 接口、不碰浏览器 ✓）：
//   claim → `applying` ✓；断 8 秒后仍是 `applying` ✓（**事务没被取消** ✓）；
//   拿**同一个 operationId + claimToken** 重放 → `code 0 / resultPlanVersion 3 / postcondition.satisfied=true` ✓✓；
//   再重放一次 → 工作区 3→3 ✓（**不双写** ✓）。
// 探针顺带露出的一条 ✗：**没人回写时 pending 会一直停在 `applying`** ✗（我当客户端时跳过了
// `pending/resolve(complete)` ✓）——而 `applying` 正是"重复确认"的判定依据 ✓，所以这一格必须有人兜 ✓。
//
// 浏览器这一侧的走法 ✓：点确认 → **立刻整页重连**（掉 WS ✓）——认领/执行/回写都在**网关**那侧跑 ✓，
// 掉线不该影响它 ✗。重连后要能读到**最终结果** ✓：
//   ① 正式内容前进了 ✓（事务没被取消 ✓）；② 再重连一次，版本**不动** ✓（没有第二次写 ✓）；
//   ③ 卡要能显示终态 ✓（这一条是本用例真正的靶子 ✓：重连后状态是**重建**出来的 ✓）。
//
// **本用例 2026-09-27 已绿 ✓**——两段修法与读数留档（红过的地方最容易回退 ✓）：
//   **① 网关侧（`602e16e` ✓）**：动作收尾改挂"会话"不挂"这一轮/这条连接" ✓（`SessionRuntime.detach_work` ✓）。
//   修前掉线会把"发结果"那一步一起带走 ✗（四条会话里 F07/F08/F09 各有 1 条 `conversationAction.result` ✓，
//   F13 那条 **0 条** ✗），修后同一条会话 0 → 2 条 ✓。
//   **② 数据侧（走 B 方案 ✓）**：卡片状态**只活在事件流里** ✗，而冷加载**没有游标** ✓
//   （`conversationCursor.mjs`：游标不落盘 ✓）、服务端那条路只补"在飞回合" ✗（`server.py:596` ✓）
//   → 已结束回合的卡重建不出来 ✓。修法：**会话详情带一格 `lastProposal`** ✓
//   （Java 从"待确认的当前行"取 ✓：`actionStatus` = 它的 status ✓），前端在
//   "回合里没画过这个 `proposalRef`"时补一张**只读**卡 ✓（`MessageList` ✓）。
//   为什么不走"过滤补发" ✗：reducer 是 `sequence !== lastSequence + 1 → resync` ✓
//   （`conversationSession.mjs:189` ✓），补一段不连续的必被判缺口 ✓。
//   读数：`[f13] before: version=0 phase=candidate_generated；after: version=3 phase=reviewed；settled: version=3` ✓
//   ——事务没被取消 ✓、没双写 ✓、重连后卡读到"已生效" ✓。
//   **一条走过弯路的怀疑，记一笔免得下次再查 ✗**：曾以为页面混进了别的会话的内容 ✗（"查询测试学校…" 8 份 ✓）——
//   **不成立** ✓：那是**会话 id 复用**后它自己的历史 ✓（900026：12 条里 2 条命中 ✓；
//   当时只查了池子里另一条 900028 就下了结论 ✗）。查这类问题**先把本轮实际用的会话号从后端日志取准** ✓。
test('F13 applying 时断线：事务不被取消，重连后读得到最终结果', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('proposal');

  const sessionId =
    new URL(sessionUrl, 'http://placeholder').searchParams.get('chatSessionId') || '';
  const backend = process.env.ZHIYUAN_E2E_BACKEND_ORIGIN || 'http://127.0.0.1:18290';
  const readState = async () => {
    const response = await page.request.get(
      `${backend}/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=${sessionId}`,
    );
    const body = (await response.json().catch(() => null)) as { data?: Record<string, unknown> } | null;
    return body?.data || {};
  };

  await runtimeGate.resetSessionState(sessionId);
  await runtimeGate.seedVolunteerData(sessionId);

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 10_000 });
  // **基线要在页面自举落定之后取** ✓✓（否则断到的是自举，不是被测动作 ✗——见 `settleWorkspaceBootstrap` ✓）。
  await settleWorkspaceBootstrap(readState, runtimeGate);
  const before = await readState();

  await page.getByTestId('chat-input').fill('帮我补足到 80 个志愿');
  await page.getByTestId('chat-send').click();
  await expect(
    page.locator('[data-turn-id]').last().getByTestId('turn-progress'),
  ).toContainText('历年录取', { timeout: 20_000 });
  await runtimeGate.releaseAllPending();

  const card = page.getByTestId('proposal-card');
  await expect(card.getByTestId('proposal-status')).toContainText('待确认', { timeout: 20_000 });

  // **点完立刻掉线** ✓：点击这一帧已经出站 ✓，随后的整页导航把 WS 掐掉 ✓——
  // 网关那侧的 claim→execute→回写不受影响 ✓（它不靠浏览器 ✓）。
  await card.getByTestId('proposal-confirm').click();
  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 10_000 });

  // ① 事务没被取消 ✓：等正式内容前进（重连后服务端仍在把它做完 ✓）。
  await expect
    .poll(async () => String((await readState()).version ?? ''), {
      message: '断线不许取消已提交的事务 ✓（正式版本必须前进 ✓）',
      timeout: 30_000,
    })
    .not.toBe(String(before.version ?? ''));
  const after = await readState();

  // ② 再重连一次：版本不动 ✓（同一条 operation 不许写第二次 ✓）。
  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 10_000 });
  // **先确认"人还在本会话里"** ✗✓：重连后如果页面被带去了别的会话 ✓，
  // 第 ③ 条会红得毫无道理 ✗（实测就撞到过：快照里是**别的会话**的内容 ✓）——先钉住这一条 ✓。
  await expect(
    page.getByText('帮我补足到 80 个志愿').first(),
    '重连之后必须还停在本会话 ✓（本用例只发过这一句 ✓）',
  ).toBeVisible({ timeout: 20_000 });
  const settled = await readState();

  // **数一次**（只打日志、不断言 ✓）：这条会话是**干净**的（本 run 新盐 ✓），只发过一句话 ✓——
  // 页面上它出现 >1 份就是**重复渲染** ✓。查的是"库里 2 条却渲染 8 份"那条未定项 ✗：
  // 那条现象出在**修前**的失败页面上（三次整页加载 ✓），而今天改的正是"快照/重放"那条路 ✓，
  // 所以先量一次现在的数 ✓，别凭印象说它没了 ✗。
  // **量法要先稳** ✗✓（2026-09-28 三组数对不上的教训 ✓）：
  //   · **只数段落**（`getByText` 会把父容器算进来 ✓，1 个 p + 2 层祖先 = 3 ✗）；
  //   · **等到数量连续两次相同**再读 ✓（最后一次 goto 之后，历史拉取与事件补发还在赛跑 ✓，
  //     先前量到的其实是中间态 ✗）；单次最多等 ~6 秒 ✓，不挂 ✓。
  const paragraphs = page.getByRole('paragraph');
  const settle = async (): Promise<number> => {
    let last = -1;
    for (let i = 0; i < 24; i += 1) {
      const now = await paragraphs.count();
      if (now === last) return now;
      last = now;
      await page.waitForTimeout(250);
    }
    return last;
  };
  const paraTotal = await settle();
  const userMsgCopies = await paragraphs.filter({ hasText: '帮我补足到 80 个志愿' }).count();
  const assistantCopies = await paragraphs
    .filter({ hasText: '我把这个要求整理成了提案，确认后生效。' })
    .count();
  const turnBlocks = await page.locator('[data-turn-id]').count();
  // 把**顺序**也打出来 ✓：同一句连着出现 = 重复 ✓；和别的句子交替 = 可能只是合法的重复发言 ✓。
  const tail = (await paragraphs.allTextContents()).slice(-6).map(t => t.slice(0, 14));
  console.log(
    `[f13] 稳定后：段落共 ${paraTotal} 个；用户那句 ${userMsgCopies} 份、助手那句 ${assistantCopies} 份` +
      `（干净会话下各应为 1 ✓）；回合块 ${turnBlocks} 个；末尾顺序 ${JSON.stringify(tail)}`,
  );
  console.log(
    `[f13] before: version=${String(before.version)} phase=${String(before.phase)}；` +
      `after: version=${String(after.version)} phase=${String(after.phase)}；` +
      `settled: version=${String(settled.version)} phase=${String(settled.phase)}`,
  );
  expect(String(settled.version), '断线重连不许把同一条命令写两遍 ✓').toBe(String(after.version));

  // ③ 卡要显示终态 ✓（重连后状态是重建的 ✓——这条红了就是"查原 operation 恢复最终结果"这一格缺 ✓）。
  await expect(
    page.getByTestId('proposal-status').first(),
    '重连后卡要能读到最终结果 ✓（"已生效"那一档 ✓）',
  ).toContainText(/已生效|已采纳/, { timeout: 30_000 });
});

// **F02：歧义 → 原生卡** ✓（任务书原文："选项+自由输入；**原 request 回答继续同 Turn**" ✓）。
//
// 靠**场景表**驱动 ✓✓：先把本 run 的场景设成 `clarification` ✓ → 替身这一轮会先发一次
// `item/tool/requestUserInput` ✓（`browser_app_server.py` 的 `_scenario` ✓），
// 桥把它变成原生卡 ✓、并**等答案** ✓——答案用**原 rpc id**回去 ✓ → 替身才继续 ✓（有单测盯着 ✓）。
test('F02 歧义：原生卡给出选项与自由输入，回答后仍在同一回合里继续', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;
  await runtimeGate.setScenario('clarification');   // ← 本用例的场景 ✓

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查一下计算机');
  await page.getByTestId('chat-send').click();

  // ① **原生卡**出现 ✓，且是"选择"型 ✓（选项 ✓）。
  const card = page.getByTestId('clarification-card');
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toHaveAttribute('data-input-kind', 'choice');   // 选项型 ✓
  // ② 选项**看得见** ✓（替身在 questions 里给的两个 ✓）。
  await expect(card.getByText('计算机科学与技术')).toBeVisible();
  await expect(card.getByText('软件工程')).toBeVisible();
  // ③ **自由输入**也在 ✓（同一张卡里可自己填 ✓）。
  await expect(card.getByPlaceholder('请输入')).toBeVisible();

  // 记下回合号 ✓：回答之后要**还是同一个回合** ✓✓（这就是"继续同 Turn" ✓）。
  const turnBefore = page.locator('[data-turn-id]').last();
  const turnIdBefore = await turnBefore.getAttribute('data-turn-id');

  // 回答：用**自由输入**那一栏 ✓（选项与自由输入都要能走通 ✓，这里选后者 ✓）。
  await card.getByPlaceholder('请输入').fill('软件工程');
  await card.getByTestId('clarification-submit').click();

  // ④ **同一回合继续** ✓✓：回答后没有冒出第二个回合块 ✓，回合号也没变 ✓。
  await expect(page.locator('[data-turn-id]')).toHaveCount(1, { timeout: 20_000 });
  await expect(page.locator('[data-turn-id]').last()).toHaveAttribute('data-turn-id', turnIdBefore || '');

  // ⑤ 放行后照常收尾 ✓（场景不影响闸门语义 ✓）。
  await runtimeGate.releasePendingGate();
  await expect(page.locator('[data-turn-id]').last().getByTestId('assistant-final')).toHaveCount(1, {
    timeout: 20_000,
  });
});

// **流式增量（assistant.delta）** ✓（任务书："delta 出现 → 终态替换为全文 → 不双画" ✓）。
//
// 为什么可断 ✓：替身把终态正文切成**多条**增量 ✓（`browser_app_server.py` 的
// `_DELTA_FRAGMENTS` ✓，有单测钉住"拼接=终态正文" ✓），闸门扣着时它们**已经全到了** ✓；
// 放行后终态才到 ✓——所以"先有流式文本、后有终态、终态替换流式文本"三件事都测得到 ✓。
// 文本是**模型原样增量**（尚未闭合的 TurnOutput JSON 片段 ✓）——断言只认其中一段
// 稳定子串 ✓，不假设 JSON 会被前端解析 ✗（它只是可丢弃的提示 ✓）。
//
// 放在文件**末尾** ✓：会话按用例标题哈希分配（`fixtures.ts` 的 `sessionIdFor` ✓），
// 新用例排在末尾时，既有用例的分配序号不变 ✓（不搅动上一轮绿过的会话 ✓）。
test('流式增量：先显示 delta 流文本，终态到达后整段替换且不双画', async ({
  page,
  sessionUrl,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime; // 自动 fixture ✓：跑之前已校验 runtimeKind=fake ✓

  await page.goto(sessionUrl, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('查询测试学校近三年录取位次');
  await page.getByTestId('chat-send').click();

  const turn = page.locator('[data-turn-id]').last();
  await expect(turn).toBeVisible({ timeout: 20_000 });

  // ① 增量先到：放行**之前**流式文本就可见（替身发完增量就等闸门，不再发终态）。
  await expect(turn.getByTestId('assistant-stream')).toContainText('闸门放行后的答案', {
    timeout: 20_000,
  });
  // ② 终态**还没来**：答案元素不存在（这条之所以可信，是因为替身没放行就真的不发）。
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0);

  // ③ 放行后终态整段替换：解析后的答案出现，流式文本退场（同一回合不双画）。
  await runtimeGate.releasePendingGate();
  await expect(turn.getByTestId('assistant-final')).toHaveText('闸门放行后的答案', {
    timeout: 20_000,
  });
  await expect(turn.getByTestId('assistant-stream')).toHaveCount(0);
});
