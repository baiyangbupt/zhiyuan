import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createHeartbeatWatchdog,
  HEARTBEAT_TIMEOUT_MS,
  shouldRearmWatchdog,
  shouldSkipSilenceCheck,
} from './heartbeatWatchdog.mjs';

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

// ── M4：后台标签页的节流不许变成"误杀好好连接"的理由 ──────────────────────────

test('隐藏期跳过判死：那时 ping 与 pong 都没有机会跑，静默不是证据', () => {
  assert.equal(shouldSkipSilenceCheck('hidden'), true);
});

test('前台照常判死（隐藏期跳过不能把探针整个关掉）', () => {
  assert.equal(shouldSkipSilenceCheck('visible'), false);
  // 老环境/SSR 拿不到 visibilityState → 退回原行为（判死不停）。
  assert.equal(shouldSkipSilenceCheck(undefined), false);
  assert.equal(shouldSkipSilenceCheck(''), false);
});

test('回到前台要复位窗口；隐藏/未知状态不动', () => {
  assert.equal(shouldRearmWatchdog('visible'), true);
  assert.equal(shouldRearmWatchdog('hidden'), false);
  assert.equal(shouldRearmWatchdog(undefined), false);
});

test('台面复刻：标签隐藏 10 分钟 → 回到前台先复位 → 不会被隐藏期的时长误杀', () => {
  const watchdog = createHeartbeatWatchdog();
  watchdog.reset(0);
  // 隐藏 10 分钟：按节流后的节奏巡检，但判死被跳过（隐藏期）。
  const hiddenAt = 10 * 60_000;
  assert.equal(shouldSkipSilenceCheck('hidden'), true);
  assert.equal(watchdog.isSilent(hiddenAt), true, '静默窗口本身照走（跳过判死是调用方的决定）');
  // 回到前台：事件先复位锚点 → 立刻判死应为假，且再等满一个完整窗口才判死。
  assert.equal(shouldRearmWatchdog('visible'), true);
  watchdog.reset(hiddenAt);
  assert.equal(watchdog.isSilent(hiddenAt + HEARTBEAT_TIMEOUT_MS - 1), false);
  assert.equal(watchdog.isSilent(hiddenAt + HEARTBEAT_TIMEOUT_MS), true);
});
