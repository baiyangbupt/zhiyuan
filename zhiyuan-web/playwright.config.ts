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
    {
      name: 'contract',
      testMatch: '**/*.contract.spec.ts',
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
