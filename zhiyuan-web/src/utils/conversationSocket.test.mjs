import assert from 'node:assert/strict';
import test from 'node:test';

import { PUBLIC_TEST_ACCESS_MODE, socketBase } from './conversationSocket.mjs';

// C2 的口径（任务书 `plans/2026-09-20-codex-browser-validation.md` Task C2 ✓）：
// **公开模式靠 `window.location` 派生同源 wss** ✓，本地模式用显式 override ✓。
// 只改 hook 不够 ✗——真正拼 URL 的调用点也要走这里 ✓。

test('public-test derives same-origin wss from window.location', () => {
  assert.equal(
    socketBase({ protocol: 'https:', host: 'test-wwww.gaotuzhiyuan.com' }, ''),
    'wss://test-wwww.gaotuzhiyuan.com'
  );
});

test('public-test ignores a stale loopback override when it is empty', () => {
  // 公开模式下 `NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE` 必须为空 ✗——
  // 空串不能被当成"有 override"而回退到 loopback ✗（那会让用户浏览器连自己的 127.0.0.1 ✗）。
  assert.equal(
    socketBase({ protocol: 'https:', host: 'test-wwww.gaotuzhiyuan.com' }, undefined),
    'wss://test-wwww.gaotuzhiyuan.com'
  );
});

test('local keeps the explicit override and trims the trailing slash', () => {
  assert.equal(
    socketBase({ protocol: 'http:', host: '127.0.0.1:3201' }, 'ws://127.0.0.1:18291/'),
    'ws://127.0.0.1:18291'
  );
});

test('http page without override derives ws, not wss', () => {
  assert.equal(
    socketBase({ protocol: 'http:', host: '127.0.0.1:3201' }, ''),
    'ws://127.0.0.1:3201'
  );
});

test('public-test ignores a stale non-empty legacy base (任务书验收原文)', () => {
  // 场景：`.env` 里 `NEXT_PUBLIC_AGENT_WS_BASE` 非空 ✗、override 为空 ✓、模式 public-test ✓。
  // 期望：**当前域名的 wss** ✓——不能让那个遗留值把浏览器指到别处 ✗。
  assert.equal(
    socketBase(
      { protocol: 'https:', host: 'test-wwww.gaotuzhiyuan.com' },
      '',
      PUBLIC_TEST_ACCESS_MODE
    ),
    'wss://test-wwww.gaotuzhiyuan.com'
  );
  assert.equal(
    socketBase(
      { protocol: 'https:', host: 'test-wwww.gaotuzhiyuan.com' },
      'wss://www.gaotuzhiyuan.com',
      PUBLIC_TEST_ACCESS_MODE
    ),
    'wss://test-wwww.gaotuzhiyuan.com'
  );
});

test('public-ip-test always uses the page origin despite stale overrides', () => {
  for (const override of ['', undefined, 'ws://127.0.0.1:18291', 'wss://old.example']) {
    assert.equal(
      socketBase({ protocol: 'http:', host: '101.42.252.196:3201' }, override, 'public-ip-test'),
      'ws://101.42.252.196:3201'
    );
  }
  assert.equal(
    socketBase({ protocol: 'https:', host: '101.42.252.196:3201' }, 'ws://old.example', 'public-ip-test'),
    'wss://101.42.252.196:3201'
  );
});
