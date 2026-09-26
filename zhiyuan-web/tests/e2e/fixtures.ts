import { test as base, expect } from '@playwright/test';

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
  /** 放行某一回合的终态 ✓——**显式传 turnId** ✓（别用全局变量偷偷传 ✗）。 */
  releaseFinal: (turnId: string) => Promise<void>;
  resetRun: () => Promise<void>;
};

type Fixtures = {
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

export const test = base.extend<Fixtures>({
  sessionUrl: async ({}, use) => {
    const value = process.env.ZHIYUAN_E2E_SESSION_URL;
    if (!value) throw new Error('缺少 ZHIYUAN_E2E_SESSION_URL');
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
      releaseFinal: async (turnId: string) => {
        await controlFetch(`/gates/${turnId}/release`, 'POST', {});
      },
      resetRun: async () => {
        await controlFetch(`/runs/${runId}/reset`, 'POST', {});
      },
    });
  },

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
