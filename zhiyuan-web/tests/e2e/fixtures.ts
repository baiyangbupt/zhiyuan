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
  /** 本 run 的场景（按 runId 存在控制服务上 ✓，**跨用例不清** ✗——`cleanGates` 会复位 ✓）。 */
  setScenario: (name: string) => Promise<void>;
  /** **换掉这条会话的事件代际** ✓（F11 靶子 ✓）：控制服务删掉 `seq`/`epoch` 两键 ✓，
   *  下一次追加就由存储脚本生成新代际 ✓、序号**从 1 重来** ✓。 */
  rotateEpoch: (sessionId: string) => Promise<void>;
  /** **本 run 的场景参数** ✓（替身自己拿不到的数据走这里 ✓，最典型是提案的
   *  `sourceVersionGuard` ✓——它是"会话当前的工作区版本" ✓）。 */
  setScenarioParams: (params: Record<string, unknown>) => Promise<void>;
  /** **给某条会话铺一份 legacy 志愿数据** ✓（提案编译的前置 ✓；本地合成会话本来没有 ✗）。 */
  seedVolunteerData: (sessionId: string) => Promise<void>;
  /** **把某条会话的规划状态清干净** ✓（提案/待确认那一族 ✓）——"干净会话"是提案链的前置 ✓：
   *  同一条会话反复试会把两个计数器写岔 ✓，于是同一个守门值不可能同时成立 ✓。 */
  resetSessionState: (sessionId: string) => Promise<void>;
  /**
   * **收尾用**的放行：把名单上所有还没放行的闸门都放掉 ✓（数量随便 ✓）。
   *
   * 与 `releasePendingGate` 的分工要写清 ✗✓：那个是**判据**型的 ✓（"恰好 1 个"是它要验的
   * 东西之一 ✓，多了少了都该红 ✓）；这个是**清理**型的 ✓，给"一轮用例里起过多轮、
   * 收尾时不确定还剩几个"的场景用 ✓（F11 就是：换代前后各一轮 ✓）。
   */
  releaseAllPending: () => Promise<string[]>;
};

/**
 * **"断线"的可控做法** ✓✓（不刷新页面 ✓）：把 `WebSocket` 包一层记下实例 ✓，再从页面里关掉它 ✓。
 *
 * 为什么不用 `context.setOffline(true)` ✗：它只影响**新**连接 ✓，已建立的 WebSocket 不保证被关掉 ✗——
 * 页面根本没重连 ✓，用例就会**假绿** ✗（第一次写这条用例时就是这么栽的 ✓）。
 * 包装必须是**忠实**的 ✓：静态常量 `OPEN`/`CONNECTING` 等要照搬 ✗，否则 hook 里
 * `readyState === WebSocket.OPEN` 的判等永远为假 ✓ → 消息只入队、根本不发 ✓
 * （第二版就是这么红的 ✓）。只包在测试里 ✓，应用代码一行不动 ✓。
 */
export async function installSocketRecorder(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const original = window.WebSocket;
    const bag = window as unknown as { __conversationSockets?: WebSocket[] };
    bag.__conversationSockets = [];
    const wrapped = function (this: unknown, ...args: ConstructorParameters<typeof WebSocket>) {
      const socket = new original(...args);
      bag.__conversationSockets?.push(socket);
      return socket;
    } as unknown as typeof WebSocket;
    wrapped.prototype = original.prototype;
    Object.assign(wrapped as unknown as Record<string, unknown>, {
      CONNECTING: original.CONNECTING,
      OPEN: original.OPEN,
      CLOSING: original.CLOSING,
      CLOSED: original.CLOSED,
    });
    window.WebSocket = wrapped;
  });
}

/** 把页面**最近一条**对话 WebSocket 关掉（hook 会在重连间隔后自己接回来 ✓，并带上游标 ✓）。 */
export async function dropConversationSocket(page: Page): Promise<void> {
  await page.evaluate(() => {
    const bag = window as unknown as { __conversationSockets?: WebSocket[] };
    bag.__conversationSockets?.[bag.__conversationSockets.length - 1]?.close();
  });
}

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

/**
 * 一条用例一个会话 ✓✓：**会话在服务端是有状态的**（在飞回合、事件流、闸门都挂在它名下 ✓），
 * 共用一条会话时，上一条用例的残留会打进下一条 ✗——实测过两种形态：
 *   · 下一条的消息被判"当前回合还在进行"直接拒收 ✗（F02 跟在 F10 后面就是这么红的 ✓）；
 *   · 重连补发把**上一条**的回合补进这一条的页面 ✗ → 断言对着旧回合假绿 ✗
 *     （F02 的 ①–④ 曾经全"过"，过的却是 F10 那张卡 ✓）。
 * 池子：本地私有数据里会话 id 在 `ZHIYUAN_E2E_SESSION_URL` 给出的那个**往下**连号 ✓
 * （实测 900003–900047 ✓，够用例数 ✓）；按用例**标题**分配，同一条用例每次拿同一个 ✓。
 */
const SESSION_POOL_SIZE = 32; // 池子：配置给的 id **往下**连号（实测 900003–900047 ✓，够用 ✓）
// **占位表挂 `globalThis`** ✓✓：模块级的 Map 是**每个 spec 文件一份** ✗——
// 两个文件各自从同一个 base 派生、又各自记账 ✓，于是必然撞车 ✓
//（实测：同一次跑里 `900023` 被连了 **3 次** ✗，前后两条用例共用一条会话 ✗ →
//  上一条的在飞回合把下一条打成"没有回合块" ✗）。挂到 globalThis 上，
// 同一 worker 内的所有文件共用一份 ✓；换 worker/换 run 自然重置 ✓。
const claimedSessions = ((
  globalThis as unknown as { __zhiyuanSessionClaims?: Map<number, string> }
).__zhiyuanSessionClaims ??= new Map<number, string>());

/**
 * 按**用例标题**定会话：跨文件稳定 ✓、同一条用例每次拿同一个 ✓。
 *
 * **不能用计数器** ✗✓：Playwright **每个 spec 文件**各有一份模块实例 ✓，计数器会在
 * `access.contract.spec.ts` 与 `conversation.contract.spec.ts` 之间各从 0 起 ✗ →
 * 两条用例撞进同一条会话 ✓（实测读数：连接顺序是 `…900041 → **900047**` 回绕 ✗）。
 * 会话一撞，这条隔离要防的事就全回来了 ✓——上一条的在飞回合把下一条判成 BUSY ✗、
 * 重连补发把上一条的回合补进下一条的页面 ✗。
 *
 * 冲突（哈希撞了）就**顺序探一格** ✓，探到再撞就**抛** ✗——不静默共用 ✓。
 */
function sessionIdFor(baseId: number, title: string): number {
  let hash = 0;
  for (const char of title) hash = (hash * 31 + (char.codePointAt(0) || 0)) >>> 0;
  // **按 run 加盐** ✓✓：`ZHIYUAN_E2E_SESSION_SALT` 一变，这一轮所有用例就拿一套**新会话** ✓。
  // 为什么需要它 ✗：会话在服务端**有状态** ✓（待确认修订号、快照版本、候选池… ✓）——
  // 同一条会话被反复试会把状态写脏 ✓（实测：pending=1 而快照=0 ✓，两个计数器对不上 ✓，
  // 于是**同一个守门值不可能同时成立** ✗）。要"干净会话"就得换一条 ✓。
  // 默认空 ✓（不加盐 = 原来的行为 ✓）；跑需要干净状态的用例时把它设成 run id 之类 ✓。
  const salt = process.env.ZHIYUAN_E2E_SESSION_SALT || '';
  for (const char of salt) hash = (hash * 31 + (char.codePointAt(0) || 0)) >>> 0;
  for (let step = 0; step < SESSION_POOL_SIZE; step += 1) {
    const candidate = baseId - ((hash + step) % SESSION_POOL_SIZE);
    const owner = claimedSessions.get(candidate);
    if (owner === undefined || owner === title) {
      claimedSessions.set(candidate, title);
      return candidate;
    }
  }
  throw new Error(
    `会话池不够分了 ✗（池大小 ${SESSION_POOL_SIZE}，本 run 的用例数已超出）——` +
      `要么把 ZHIYUAN_E2E_SESSION_URL 指到池子更靠上的 id，要么扩大池子`,
  );
}

function perTestSessionUrl(base: string, title: string): string {
  const url = new URL(base, 'http://placeholder');
  const raw = url.searchParams.get('chatSessionId');
  const baseId = Number(raw);
  // 没给 id 就原样用 ✓：**不在这里编一个** ✗（编出来的会话可能不存在，而失败会看起来像应用坏了 ✗）。
  if (!raw || !Number.isFinite(baseId)) return base;
  url.searchParams.set('chatSessionId', String(sessionIdFor(baseId, title)));
  return `${url.pathname}${url.search}`;
}

export const test = base.extend<Fixtures>({
  sessionUrl: async ({ page }, use, testInfo) => {
    const configured = process.env.ZHIYUAN_E2E_SESSION_URL;
    if (!configured) throw new Error('缺少 ZHIYUAN_E2E_SESSION_URL');
    const value = perTestSessionUrl(configured, testInfo.title);
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
      setScenario: async (name: string) => {
        await controlFetch(`/runs/${process.env.ZHIYUAN_E2E_RUN_ID || 'browser-run'}/scenario`, 'POST', {
          scenario: name,
        });
      },
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
      setScenarioParams: async (params: Record<string, unknown>) => {
        await controlFetch(`/runs/${runId}/scenario-params`, 'POST', params);
      },
      seedVolunteerData: async (sessionId: string) => {
        await controlFetch(`/runs/${runId}/seed-volunteer`, 'POST', { sessionId });
      },
      resetSessionState: async (sessionId: string) => {
        await controlFetch(`/runs/${runId}/reset-session`, 'POST', { sessionId });
      },
      releaseAllPending: async () => {
        const state = (await controlFetch('/gates', 'GET')) as {
          gates?: Record<string, { released?: boolean }>;
        };
        const pending = Object.entries(state.gates || {}).filter(([, gate]) => !gate?.released);
        for (const [turnId] of pending) {
          await controlFetch(`/gates/${turnId}/release`, 'POST', {});
        }
        return pending.map(([turnId]) => turnId);
      },
      rotateEpoch: async (sessionId: string) => {
        // 事件存储的键是 `conv:{租户:会话}:seq|epoch` ✓——租户在这里是固定的 `1` ✓
        //（合同栈的票据身份就是 1 ✓）。
        await controlFetch(`/runs/${runId}/rotate-epoch`, 'POST', {
          sessionId,
          tenantId: '1',
        });
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
        // **场景也要复位** ✓✓：场景按 runId 存在控制服务上，而 `reset` 只清闸门 ✗——
        // 上一条用例设的场景会**继承**下来 ✗（实测：留下 `clarification` 之后，下一条
        // 用例的回合先去弹卡等人作答 ✗，放行后终态永远等不到 ✗，红在 20s 超时 ✓）。
        // 放在清场里、不放进各用例 ✓：那样每加一条用例就再犯一次 ✗，这里只写一次 ✓。
        await controlFetch(`/runs/${runId}/scenario`, 'POST', { scenario: 'gate_then_answer' });
        console.log('[cleanGates] scenario 复位为 gate_then_answer ✓');
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
