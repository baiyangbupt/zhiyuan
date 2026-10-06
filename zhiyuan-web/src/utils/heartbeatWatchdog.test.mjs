import test from 'node:test';
import assert from 'node:assert/strict';

import { createHeartbeatWatchdog, HEARTBEAT_TIMEOUT_MS } from './heartbeatWatchdog.mjs';

test('刚建立的连接有一个完整超时窗口的宽限，不算死', () => {
  const watchdog = createHeartbeatWatchdog();
  watchdog.reset(1_000);
  assert.equal(watchdog.isSilent(1_000 + HEARTBEAT_TIMEOUT_MS - 1), false);
});

// **这条就是事故的回归用例**：原实现的判据是"距上次 ping 的时长"，而每发一次 ping
// 就把锚点重写成 now —— 它永远到不了 30s。ping 不能刷新静默窗口，只有 pong 能。
test('只发 ping（没有一个 pong 回来）也要在超时后判死', () => {
  const watchdog = createHeartbeatWatchdog();
  watchdog.reset(0);
  // 模拟心跳 tick：每 5s 发一次 ping（ping 只是出站流量，不是一个事件输入）。
  for (let t = 5_000; t < HEARTBEAT_TIMEOUT_MS; t += 5_000) {
    assert.equal(watchdog.isSilent(t), false, `t=${t} 还没到超时，不该判死`);
  }
  assert.equal(
    watchdog.isSilent(HEARTBEAT_TIMEOUT_MS),
    true,
    '整 30s 没有 pong 必须判死（否则假死连接永远不重连）',
  );
});

test('收到 pong 会把静默窗口清零', () => {
  const watchdog = createHeartbeatWatchdog();
  watchdog.reset(0);
  assert.equal(watchdog.isSilent(29_000), false);
  watchdog.touchPong(29_000);
  assert.equal(watchdog.silenceFor(29_001), 1);
  assert.equal(watchdog.isSilent(29_000 + HEARTBEAT_TIMEOUT_MS - 1), false);
  assert.equal(watchdog.isSilent(29_000 + HEARTBEAT_TIMEOUT_MS), true);
});

test('stop 之后不再判死（连接已断，那条路由 onclose 负责）', () => {
  const watchdog = createHeartbeatWatchdog();
  watchdog.reset(0);
  watchdog.stop();
  assert.equal(watchdog.isSilent(HEARTBEAT_TIMEOUT_MS * 10), false);
  assert.equal(watchdog.silenceFor(HEARTBEAT_TIMEOUT_MS * 10), 0);
});

test('从没 reset 过（还没连接）不判死', () => {
  const watchdog = createHeartbeatWatchdog();
  assert.equal(watchdog.isSilent(Date.now() + HEARTBEAT_TIMEOUT_MS * 10), false);
});

test('reset 可以重开一局：重连后的锚点是新连接，不是上一局的时间戳', () => {
  const watchdog = createHeartbeatWatchdog();
  watchdog.reset(0);
  assert.equal(watchdog.isSilent(HEARTBEAT_TIMEOUT_MS), true);
  watchdog.reset(100_000);
  assert.equal(watchdog.isSilent(100_000 + HEARTBEAT_TIMEOUT_MS - 1), false);
});
