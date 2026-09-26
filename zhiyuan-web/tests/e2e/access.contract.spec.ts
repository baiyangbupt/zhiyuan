import { expect, test } from '@playwright/test';

// C4 的第一个绿灯 ✓：**不需要假 Codex 闸门** ✓ 的那一类（F14 的可自动化部分 ✓）。
// 口径来自 C2 ✓：内网面（`/inner/`、`/internal/`、`/admin/`、`/debug/`）**任何一层都不许漏** ✓——
// 代理层（Nginx ✓）、Next rewrite（✓ 已前置守卫 ✓）、页面实际请求（**这条** ✓）三处一起才算数 ✓。

const sessionUrl = () => process.env.ZHIYUAN_E2E_SESSION_URL as string;

test('会话页面能打开，且全程不碰内网路径', async ({ page }) => {
  const requests: string[] = [];
  const consoleErrors: string[] = [];
  const failed: string[] = [];

  page.on('request', (request) => requests.push(request.url()));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 200));
  });
  page.on('requestfailed', (request) => {
    failed.push(`${request.method()} ${request.url().slice(0, 120)}`);
  });

  const response = await page.goto(sessionUrl(), { waitUntil: 'domcontentloaded', timeout: 30_000 });

  expect(response?.status(), '会话路由必须是 200 ✓（注意 basePath ✗：`/` 在 production 轮廓下本来就 404）').toBe(200);
  await expect(page.locator('body')).toBeVisible();

  const innerHits = requests.filter((url) =>
    /\/gaotu-assistant-bot\/(inner|internal|admin|debug)\//.test(url)
  );
  expect(innerHits, '内网路径不该被页面请求到 ✓（漏了就是事故 ✗）').toEqual([]);
  expect(failed, '不该有失败请求').toEqual([]);
  expect(consoleErrors, '页面不该有 console error').toEqual([]);
});

test('会话路由是**相对路径**，不是硬编码的域名', async () => {
  // 任务书要求 origin 与 session 路由分开给 ✓（`ZHIYUAN_E2E_ORIGIN` + `ZHIYUAN_E2E_SESSION_URL` ✓）。
  // 会话路由若自带域名 ✗，那这条用例在任何 origin 下都会打到同一个地方 ✗——那正是"跨环境复用凭据"的雏形 ✓。
  const url = sessionUrl();
  expect(url.startsWith('/'), `ZHIYUAN_E2E_SESSION_URL 应当是相对路径 ✓（现在：${url}）`).toBe(true);
  expect(url.startsWith('http'), '不要写死域名 ✓').toBe(false);
});
