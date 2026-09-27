import { defineConfig } from '@playwright/test';

// 配置**必须**因为缺关键项而失败 ✓（Task C4 原话："首次必须因缺 origin/session/auth fixture 失败；
// 不能默认打生产" ✗）——所以这里没有默认值 ✓，缺一个就抛 ✓。
if (!process.env.ZHIYUAN_E2E_ORIGIN) {
  throw new Error('ZHIYUAN_E2E_ORIGIN required（页面 origin ✓，例如 http://127.0.0.1:3201）');
}
if (!process.env.ZHIYUAN_E2E_SESSION_URL) {
  throw new Error(
    'ZHIYUAN_E2E_SESSION_URL required（C3 确认过的会话路由 ✓，例如 /assistant-pc/sessionDetailV2）'
  );
}

// 项目名**不代表运行时** ✗（任务书原话："项目名本身不能决定 Runtime" ✓）：
// 真正的判据是栈自己的身份证据 ✓——contract 栈要 `/identity` 返回 `runtimeKind=fake` ✓，
// real 栈要拿到真实二进制的版本证据 ✓；由用例侧断言 ✓，不靠这个名字 ✓。
export default defineConfig({
  testDir: './tests/e2e',
  // 串行 ✓：合同栈闸门与真实栈都不能并发打同一个会话 ✓。
  workers: 1,
  retries: 0,
  // 本机（CentOS 7 / glibc 2.17 ✗）宿主跑不了浏览器 ✗ → 由
  // `scripts/run-codex-e2e-in-container.sh` 在容器里执行 ✓（配方见
  // `docs/validation/codex-native-environment.md` §4.1 ✓）。
  use: {
    baseURL: process.env.ZHIYUAN_E2E_ORIGIN,
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  projects: [
    // 登录态前置 ✓：登录一次、存 storageState ✓（验证码必须**先在宿主注入** ✓，
    // 见 `scripts/inject-codex-e2e-sms-code.sh` ✓）。
    // 注意 ✗：**不依赖 `dependencies`**——那会把 setup 的失败降级成 dependents 的 `skipped` ✗✗，
    // 正是任务书禁止的"skip 后声称覆盖" ✓。runner 改为**显式先跑 setup、失败即中止** ✓✓。
    { name: 'setup', testMatch: '**/*.setup.ts' },
    // 合同栈：真实浏览器 + Gateway + Java 隔离库 ✓，Codex 侧是**可控闸门**的假实现 ✓。
    //
    // **写路径那几条排除在外** ✓✓（`grepInvert` ✓）：它们要求栈跑在 `codex_write` 上 ✗
    //（只读模式下确认链不在这台实例上活着 ✓，点了也走不到 claim/execute ✓）——
    // 混在一起的话，"栈起成了只读"会被读成"功能坏了" ✗，而"写路径还没做完"会被读成"合同栈红" ✗✗。
    // 排除的判据是**用例标题**里的 `F07 后半` ✓（与用例里的注释同一处口径 ✓）。
    {
      name: 'contract',
      testMatch: '**/*.contract.spec.ts',
      grepInvert: /F07 后半|F08|F09|F13/,
      use: { storageState: process.env.ZHIYUAN_E2E_AUTH_STATE || undefined },
    },
    // **需要 `codex_write` 栈的用例** ✓（当前只有 F07 后半那条 ✓——起栈时要
    // `CODEX_LOCAL_GATEWAY_MODE=codex_write` ✓，见 `scripts/start-codex-local.sh` ✓）
    // **新增写路径用例时，两处 grep 都要加** ✗✓（`contract` 的 `grepInvert` 与这里的 `grep` ✓）——
    // 漏一处的话它要么跑在只读栈上（红得没道理 ✓），要么被过滤掉**一条都不跑** ✗✓
    //（实测：`--project write --grep F08` 交集为空 ✓，输出里只有 setup ✓，看起来像"用例没写对" ✗）。
    {
      name: 'write',
      testMatch: '**/*.contract.spec.ts',
      grep: /F07 后半|F08|F09|F13/,
      use: { storageState: process.env.ZHIYUAN_E2E_AUTH_STATE || undefined },
    },
    // 真实栈：同一套栈，但换真实 Codex 与真实（或经批准的隔离）上游 ✓。
    {
      name: 'real',
      testMatch: '**/*.real.spec.ts',
      use: { storageState: process.env.ZHIYUAN_E2E_AUTH_STATE || undefined },
    },
  ],
});
