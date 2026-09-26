import { expect, test as setup } from '@playwright/test';

import { existsSync } from 'node:fs';

// 登录态前置（Task C4："fixture 以 C3 的测试账户登录" ✓）。
//
// 为什么单独一个 setup 工程 ✓：登录一次 ✓、存 `storageState` ✓、所有 contract 用例复用 ✓——
// 每个用例各登一次既慢 ✓ 又会把"验证码一次性"这条规则踩碎 ✗（`verifyCode` 成功即 delete ✓）。
//
// **验证码必须在宿主注入** ✓（`scripts/inject-codex-e2e-sms-code.sh` ✓）：
// 短信发不出去 ✗（占位 AccessKey ✓），Redis 在宿主 ✓、容器够不着 ✗；
// 且值必须是 **JSON 串** ✓（写成裸数字会被读成 Integer ✓ → 前端只看到"系统错误" ✗）。
//
// 这里**不做 skip** ✗：注入没做、账号没配，就让 setup 红 ✓（skip 会把它变成"看起来通过" ✗）。

const STORAGE_STATE = process.env.ZHIYUAN_E2E_AUTH_STATE;
const MOBILE = process.env.ZHIYUAN_E2E_MOBILE;
const CODE = process.env.ZHIYUAN_E2E_SMS_CODE;

setup('登录并保存 storageState', async ({ page }) => {
  if (!STORAGE_STATE) throw new Error('缺少 ZHIYUAN_E2E_AUTH_STATE（state 存哪儿 ✓）');
  if (!MOBILE || !CODE) {
    throw new Error(
      '缺少 ZHIYUAN_E2E_MOBILE / ZHIYUAN_E2E_SMS_CODE ✗——先在**宿主**注入验证码：\n' +
        '  bash scripts/inject-codex-e2e-sms-code.sh <mobile> <code>\n' +
        '（短信发不出去 ✓，验证码只能手工塞 ✓；值必须是 JSON 串 ✓，见该脚本注释 ✓）'
    );
  }

  // 入口用**会话路由**（配置给的 ✓），不要用 `/` ✗：实测 `/` 在隔离栈上是 Next 的 **404** ✓
  // （截图实证 ✓——隔离栈没有根页面 ✓）。而会话路由在未登录时会**重定向到登录页** ✓，
  // 这一点由 `access.contract.spec.ts` 的截图证据在案 ✓✓——所以它才是环境无关的入口 ✓。
  const entry = process.env.ZHIYUAN_E2E_SESSION_URL;
  if (!entry) throw new Error('缺少 ZHIYUAN_E2E_SESSION_URL（登录入口靠它 ✓）');
  await page.goto(entry, { waitUntil: 'domcontentloaded' });

  // 选择器用 placeholder 与按钮文案 ✓（**不是 testid** ✗——登录页我们没加 ✓；
  // 若它哪天改文案，这条会红 ✓ 而不是静默走错页 ✓）。
  await page.getByPlaceholder('请输入手机号').fill(MOBILE);
  await page.getByPlaceholder('请输入验证码').fill(CODE);

  // 协议勾选：按钮在未勾选时是禁用的 ✓（截图实证 ✓）→ 点了才可能提交 ✓。
  const agreement = page.getByRole('checkbox').first();
  if (await agreement.isVisible().catch(() => false)) {
    await agreement.check({ force: true }).catch(() => undefined);
  }

  await page.getByRole('button', { name: /开启高途志愿/ }).click();

  // 成功的判据不是"点了按钮" ✗，而是**离开登录页** ✓（登录页那几个 placeholder 消失 ✓）。
  await expect(page.getByPlaceholder('请输入手机号')).toHaveCount(0, { timeout: 30_000 });

  await page.context().storageState({ path: STORAGE_STATE });
  if (!existsSync(STORAGE_STATE)) throw new Error('storageState 没有落盘 ✗');
});
