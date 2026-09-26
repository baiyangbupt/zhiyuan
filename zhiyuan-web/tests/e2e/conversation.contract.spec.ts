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
  turnId,
  runtimeGate,
  verifyFakeRuntime,
}) => {
  void verifyFakeRuntime; // 自动 fixture ✓：跑之前已校验 runtimeKind=fake ✓

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

  const turn = page.locator(`[data-turn-id="${turnId}"]`);

  // ① 进度先到 ✓（UI 把替身的工具进度映成"历年录取"这类字样 ✓）
  await expect(turn.getByTestId('turn-progress')).toContainText('历年录取', { timeout: 20_000 });
  // ② 停止仍可操作 ✓
  await expect(turn.getByTestId('turn-stop')).toBeEnabled();
  // ③ **终态还没来** ✓✓——这条之所以可信，是因为替身没放行就真的不发 ✓（不是等得不够久 ✓）
  await expect(turn.getByTestId('assistant-final')).toHaveCount(0);

  // ④ 放行后终态才到 ✓
  await runtimeGate.releaseFinal(turnId);
  await expect(turn.getByTestId('assistant-final')).toHaveCount(1, { timeout: 20_000 });
});
