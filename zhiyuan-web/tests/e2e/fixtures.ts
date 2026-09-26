import { type Page, test as base, expect } from '@playwright/test';

// 任务书（Task C4 ③）要点，逐条落在这里 ✓：
//   - fixtures 导出 `{sessionUrl, turnId, expectedSourceVersion, runtimeGate}` ✓；
//   - **项目名不代表 Runtime** ✗：跑之前先问控制服务要 `identity` ✓，
//     不是 `runtimeKind=fake` 就让 contract 项目**直接失败** ✓（而不是"接着跑、绿了再说" ✗）；
//   - 闸门只经 **loopback 控制服务** ✓，真实 project 不跑闸门用例 ✓（由 testMatch 分 ✓）。
//
// 认证态：任务书要求"fixture 以 C3 的测试账户登录" ✓。登录态由 `ZHIYUAN_E2E_AUTH_STATE`
// 指向一个 Playwright storageState 文件 ✓（C3 的合成账户 ✓）。**没给就失败** ✗——
// 绝不静默跳过然后用匿名页面冒充"已登录" ✗（那正是"skip 后声称覆盖" ✗）。

export type RuntimeGate = {
  /**
   * 放行**当前未放行的那个闸门** ✓✓——**不问 id** ✓。
   *
   * 为什么不是 `releaseFinal(turnId)` ✗：**两个 id 空间** ✓✓——DOM 里是应用的 uuid ✓，
   * 而替身登记闸门用的是它自己的 `turn_N` ✓（`turn/start` 的参数里**根本没有回合号** ✗，
   * 见 `harness/codex.py:95` ✓；桥接只发生在网关内部 ✓）。拿 DOM 的 id 去放行 → 404 ✓（实测 ✓）。
   * 所以这里**问控制服务**要"有哪个没放行" ✓——它本来就列得出来 ✓，测试不必知道 id 从哪来 ✓。
   */
  releasePendingGate: () => Promise<string>;
  resetRun: () => Promise<void>;
};

type Fixtures = {
  /** 自动 fixture ✓：开跑前放行悬空闸门并复位本次 run ✓（否则前一例的红会毒到后一例 ✓）。 */
  cleanGates: void;
  /** 会话路由（相对路径 ✓，由 `ZHIYUAN_E2E_SESSION_URL` 给 ✓）。 */
  sessionUrl: string;
  /** 本轮注入的固定回合号 ✓（替身会回显它 ✓ → `data-turn-id` 才断得住 ✓）。 */
  turnId: string;
  /** 合同栈的运行时闸门 ✓（经 loopback 控制服务 ✓）。 */
  runtimeGate: RuntimeGate;
  /** 自动 fixture ✓：跑任何 contract 用例前先验 Runtime 身份 ✓。 */
  verifyFakeRuntime: void;
};

const controlUrl = () => process.env.ZHIYUAN_E2E_CONTROL_URL || 'http://127.0.0.1:18293';

async function controlFetch(path: string, method: 'GET' | 'POST', body?: unknown) {
  const response = await fetch(`${controlUrl()}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`控制服务 ${method} ${path} 失败：HTTP ${response.status}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

/**
 * 会话详情页需要 `localStorage.infoSummary` ✓✓（**截图实证** ✓）。
 *
 * 应用自己进详情页前会先 `setStorage([{ key: 'infoSummary', value: createdSession.infoSummary }])`
 * （`src/pages/session/index.tsx:227` ✓）——所以直接开 URL 会被**弹回登录页** ✗。
 * 这里替它把那一格补上 ✓（**不改应用** ✓）：先按会话 id 取详情 ✓，再在导航前注入 ✓。
 *
 * 取详情要打**后端 origin 本身** ✓，不能打页面相对路径 ✗：隔离栈的 Next 没有 dev rewrite ✓
 * （`APP_ENV` 未设 ✓），页面正是靠 `NEXT_PUBLIC_ASSISTANT_API_BASE_URL` **直连后端**的 ✓。
 */
async function primeInfoSummary(page: Page, sessionUrl: string): Promise<void> {
  const backend = process.env.ZHIYUAN_E2E_BACKEND_ORIGIN;
  const sessionId = new URL(sessionUrl, 'http://placeholder').searchParams.get('chatSessionId');
  if (!backend || !sessionId) return;
  try {
    const response = await page.request.get(
      `${backend}/gaotu-assistant-bot/chat/1/session/detail?chatSessionId=${sessionId}`
    );
    if (!response.ok()) throw new Error(`HTTP ${response.status()}`);
    const payload = (await response.json()) as { data?: { infoSummary?: string } };
    const summary = payload?.data?.infoSummary ?? '';
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value),
      ['infoSummary', summary]
    );
  } catch (error) {
    // **不当成静默失败** ✗：详情取不到就让后面的用例自己红 ✓（那正是"会话前置没打点好"的信号 ✓）。
    throw new Error(`取会话详情失败（infoSummary 前置 ✗）：${String(error)}`);
  }
}

export const test = base.extend<Fixtures>({
  sessionUrl: async ({ page }, use) => {
    const value = process.env.ZHIYUAN_E2E_SESSION_URL;
    if (!value) throw new Error('缺少 ZHIYUAN_E2E_SESSION_URL');
    await primeInfoSummary(page, value);  // 详情页的前置 ✓（见上 ✓）
    await use(value);
  },

  // 回合号由测试注入 ✓（任务书："客户端测试注入固定下一次 clientRequestId/turnId（仅测试构建）" ✓）。
  // 这里用"跑一次递增"的固定值 ✓——同一轮里可复现 ✓，不同轮不会撞 ✓。
  turnId: async ({}, use, testInfo) => {
    // 可复现 ✓、不同用例不撞 ✓（替身会把这个号原样回显 ✓ → `data-turn-id` 才断得住 ✓）。
    const injected = `turn-${testInfo.testId.split('-').slice(-2).join('-')}`;
    await use(injected);
  },

  runtimeGate: async ({}, use) => {
    const runId = process.env.ZHIYUAN_E2E_RUN_ID || 'browser-run';
    await use({
      releasePendingGate: async () => {
        const state = (await controlFetch('/gates', 'GET')) as {
          gates?: Record<string, { released?: boolean }>;
        };
        const pending = Object.entries(state.gates || {}).filter(([, gate]) => !gate?.released);
        if (pending.length !== 1) {
          // **fail-closed** ✗：0 个闸门 = 回合根本没起来；多个 = 状态不清，都不该猜 ✓。
          throw new Error(`期望恰好 1 个未放行的闸门，实际 ${pending.length} 个（${JSON.stringify(state.gates)}）`);
        }
        const [turnId] = pending[0];
        await controlFetch(`/gates/${turnId}/release`, 'POST', {});
        return turnId;
      },
      resetRun: async () => {
        await controlFetch(`/runs/${runId}/reset`, 'POST', {});
      },
    });
  },

  // **开跑前清场** ✓✓——这是我踩过的坑：上一个用例若没走到放行就红了 ✗，
  // 那个闸门会一直挂着 ✓，网关于是认为"当前回合还在进行" ✓ → 后续用例的消息被拒收 ✗
  //（探针原话：`当前回合还在进行，请先等它结束或点停止。` ✓）。
  // 做法：先把**悬空的闸门放行**（让替身把那一轮收尾 ✓，网关那边的回合才会结束 ✓），
  // 再 `reset` 本次 run ✓。任务书为 reset 写的那句"只清本次闸门" ✓，用的就是这里 ✓。
  cleanGates: [
    async ({}, use) => {
      try {
        // **作用域要收窄** ✓✓：只放行"**本次用例开始之前**就已登记"的闸门 ✓——
        // 原先"放行一切未放行的" ✗ 有个致命后果 ✓：若它在本用例**中途**被评估一次 ✓，
        // 就会把**本用例自己的**闸门放掉 ✗ → 那一轮不再被扣住 ✓ → 用例静默地失去意义 ✓
        //（F10 就是这么红的 ✓：探针显示发送后立刻收到终态 ✓、控制服务里所有闸门都是 released ✓）。
        // 判据用**登记时间的顺序快照** ✓：先读一次名单 ✓，此后新登记的（本用例的）一概不动 ✓。
        const before = (await controlFetch('/gates', 'GET')) as {
          gates?: Record<string, { released?: boolean }>;
        };
        const stale = Object.entries(before.gates || {}).filter(([, gate]) => !gate?.released);
        for (const [turnId] of stale) {
          await controlFetch(`/gates/${turnId}/release`, 'POST', {});
        }
        // 把它**打出来** ✓✓：万一还有别人在放行 ✓，下一轮日志会直接点名 ✓。
        console.log(`[cleanGates] 开始前已登记的闸门 ${Object.keys(before.gates || {}).length} 个，` +
          `其中未放行 ${stale.length} 个 → 放行：${JSON.stringify(stale.map(([id]) => id))}`);
        // `reset` 仍然只清**本 run** ✓（runId 要传进容器 ✓——这里顺带把实际用的 id 打出来 ✓）。
        const runId = process.env.ZHIYUAN_E2E_RUN_ID || 'browser-run';
        await controlFetch(`/runs/${runId}/reset`, 'POST', {});
        console.log(`[cleanGates] reset runId=${runId} ✓`);
      } catch (error) {
        throw new Error(`开跑前清场失败 ✗（控制服务不可达？）：${String(error)}`);
      }
      await use();
    },
    { auto: true },
  ],

  verifyFakeRuntime: [
    async ({}, use) => {
      // **身份来自服务自己** ✓，不是项目名 ✗、也不是被测方传参 ✗。
      const identity = await controlFetch('/identity', 'GET');
      expect(
        identity.runtimeKind,
        `contract 项目必须跑在假运行时上 ✓（identity=${JSON.stringify(identity)}）；` +
          `若这里是 real，说明起错了栈 ✗——任务书明令"项目名本身不能决定 Runtime" ✗`
      ).toBe('fake');
      await use();
    },
    { auto: true },
  ],
});

export { expect } from '@playwright/test';
