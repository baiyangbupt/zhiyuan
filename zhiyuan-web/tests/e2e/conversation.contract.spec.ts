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
