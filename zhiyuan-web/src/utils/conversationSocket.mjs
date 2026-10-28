/**
 * 会话 WebSocket 的 base 派生（Task C2）。
 *
 * 口径：**有显式 override 就用它**（本地栈把 override 指到 loopback ✓）；
 * 否则按 `window.location` **派生同源** ✓——公开测试模式下 override 是空的 ✓，
 * 浏览器于是连自己访问的那个域名（`wss://test-wwww.gaotuzhiyuan.com` ✓），
 * 而不是它自己的 `127.0.0.1` ✗。
 *
 * 为什么单独一个模块：真正拼 URL 的调用点不止 hook 一处 ✗——
 * 只改 hook、别处仍回退到 `NEXT_PUBLIC_AGENT_WS_BASE`，公开模式就会漏 ✗。
 * 放这里是为了让"所有调用点走同一条判据" ✓（并有单测盯着 ✓）。
 *
 * @param {{protocol: string, host: string}} location 浏览器侧位置（测试里传字面量 ✓）
 * @param {string | undefined | null} override 显式 WS base；空串/undefined 都算"没有" ✓
 * @returns {string} 形如 `wss://host` 或 `ws://host`（无尾斜杠 ✓）
 */
export const PUBLIC_TEST_ACCESS_MODE = 'public-test';
export const PUBLIC_IP_TEST_ACCESS_MODE = 'public-ip-test';

export function socketBase(location, override, mode) {
  // 公开测试模式：**忽略一切显式 base**（含历史遗留的 `NEXT_PUBLIC_AGENT_WS_BASE` ✗）,
  // 一律按 `window.location` 派生同源 ✓——任务书的验收就是这一条：
  // "旧 `WS_BASE` 非空、override 为空、public-test 模式，仍必须得到当前域名 wss" ✓。
  // 其他模式保持既有优先级 ✓（显式 override 优先 ✓，其次由调用点决定要不要给遗留值 ✓）。
  if (mode === PUBLIC_TEST_ACCESS_MODE || mode === PUBLIC_IP_TEST_ACCESS_MODE) {
    return `${location?.protocol === 'https:' ? 'wss:' : 'ws:'}//${location?.host ?? ''}`;
  }
  const explicit = typeof override === 'string' ? override.trim() : '';
  if (explicit) {
    return explicit.replace(/\/$/, '');
  }
  const protocol = location?.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${location?.host ?? ''}`;
}

export default socketBase;
