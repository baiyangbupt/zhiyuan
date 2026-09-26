// C4 的第一块砖：只读冒烟 ✓——证明浏览器驱动能真的驱动**这个**应用 ✓。
// 不登录 ✓、不写任何数据 ✓（登录会建会话行 ✓，那是后续步骤 ✓）。
import { chromium } from 'playwright';

const targets = [
  ['前端本地栈', 'http://127.0.0.1:3001/assistant-pc/sessionDetailV2'],
  ['共享后端健康', 'http://127.0.0.1:18090/gaotu-assistant-bot/inner/ops/health'],
];

const browser = await chromium.launch({ headless: true });
console.log('浏览器版本:', browser.version());
const page = await browser.newPage();

const consoleErrors = [];
const failedRequests = [];
page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 120));
});
page.on('requestfailed', (req) => {
  failedRequests.push(`${req.method()} ${req.url().slice(0, 90)} :: ${req.failure()?.errorText ?? ''}`);
});

for (const [label, url] of targets) {
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const bodyText = (await page.locator('body').innerText().catch(() => '')) || '';
    console.log(
      `${label.padEnd(12)} HTTP ${response?.status() ?? '?'} | title=${JSON.stringify(
        (await page.title()).slice(0, 30)
      )} | 可见文本前 70 字=${JSON.stringify(bodyText.replace(/\s+/g, ' ').slice(0, 70))}`
    );
  } catch (error) {
    console.log(`${label.padEnd(12)} ✗ ${error.constructor.name}: ${String(error.message).slice(0, 100)}`);
  }
}

console.log('控制台 error 条数:', consoleErrors.length, consoleErrors.slice(0, 3));
console.log('失败请求条数:', failedRequests.length, failedRequests.slice(0, 3));
await browser.close();
