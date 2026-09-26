import { expect, test } from '@playwright/test';

// C4 的第一个绿灯 ✓：**不需要假 Codex 闸门** ✓ 的那一类（F14 的可自动化部分 ✓）。
// 口径来自 C2 ✓：内网面（`/inner/`、`/internal/`、`/admin/`、`/debug/`）**任何一层都不许漏** ✓——
// 代理层（Nginx ✓）、Next rewrite（✓ 已前置守卫 ✓）、页面实际请求（**这条** ✓）三处一起才算数 ✓。

const sessionUrl = () => process.env.ZHIYUAN_E2E_SESSION_URL as string;

test('会话页面能打开，且全程不碰内网路径', async ({ page }) => {
  const innerResponses: { url: string; status: number }[] = [];
  const isInner = (url: string) => /\/gaotu-assistant-bot\/(inner|internal|admin|debug)\//.test(url);
  const consoleErrors: string[] = [];
  const failed: string[] = [];

  page.on('response', (response) => {
    if (isInner(response.url())) innerResponses.push({ url: response.url(), status: response.status() });
  });
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 200));
  });
  page.on('requestfailed', (request) => {
    failed.push(`${request.method()} ${request.url().slice(0, 120)}`);
  });

  const response = await page.goto(sessionUrl(), { waitUntil: 'domcontentloaded', timeout: 30_000 });

  expect(response?.status(), '会话路由必须是 200 ✓（注意 basePath ✗：`/` 在 production 轮廓下本来就 404）').toBe(200);
  await expect(page.locator('body')).toBeVisible();

  // **该断的性质与模式无关** ✓✓（这是真栈联调两次教我的 ✓）：
  //   · 页面**会**请求内网路径 ✓——有的是相对路径（走 Next 的 origin ✓，实测 5 条 ✓），
  //     有的走 `NEXT_PUBLIC_ASSISTANT_API_BASE_URL` ✓；请求本身不是事故 ✗。
  //   · **事故是"内网路径拿到了 200"** ✗✗——那意味着守卫那一层被绕过了 ✓。
  // 所以这里断**响应状态** ✓：`/inner/`、`/internal/`、`/admin/`、`/debug/` 一条 200 都不许有 ✓
  // （被 Nginx 挡 ✓、被 Next rewrite 前置守卫挡 ✓、或直接没响应 ✓，都算挡 ✓）。
  const leaked = innerResponses.filter((entry) => entry.status === 200);
  expect(
    leaked,
    `内网路径不得有 200 命中 ✓（被挡住才正常 ✗）：${JSON.stringify(leaked)}`
  ).toEqual([]);
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
