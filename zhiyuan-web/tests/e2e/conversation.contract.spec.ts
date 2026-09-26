import { expect, test } from './fixtures';

// 任务书（Task C4 ④）原话："一条**不依赖固定延时**的流式测试 ✓：fake 模型等 fixture 控制释放终态 ✓，
// UI 必须先显示进度、停止仍可操作 ✓。"
//
// 这里的"不依赖固定延时"是**靠闸门**做到的 ✓：替身在放行前**根本不发终态** ✓
// （`browser_app_server.py` ✓，有单测盯着 ✓）——所以下面几条断言不是"等得够久" ✗，
// 而是"终态确实还没来" ✓✓。

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
  page.on('console', (message) => consoleLines.push(`${message.type()}: ${message.text().slice(0, 200)}`));
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
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime;

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
