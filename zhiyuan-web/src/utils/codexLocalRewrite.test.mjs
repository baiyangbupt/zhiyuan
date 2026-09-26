import assert from 'node:assert/strict';
import test from 'node:test';

test('development rewrites route the Agent and Java services independently', async () => {
  const previous = {
    APP_ENV: process.env.APP_ENV,
    NEXT_PUBLIC_ASSISTANT_API_BASE_URL: process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL,
    NEXT_PUBLIC_AGENT_API_BASE_URL: process.env.NEXT_PUBLIC_AGENT_API_BASE_URL,
  };
  process.env.APP_ENV = 'dev';
  process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL = 'http://127.0.0.1:18290';
  process.env.NEXT_PUBLIC_AGENT_API_BASE_URL = 'http://127.0.0.1:18291';

  try {
    const { default: config } = await import(`../../next.config.mjs?test=${Date.now()}`);
    const rewrites = await config.rewrites();
    const destinations = Object.fromEntries(rewrites.map(({ source, destination }) => [source, destination]));

    assert.equal(
      destinations['/gaotu-assistant-bot/:path*'],
      'http://127.0.0.1:18290/gaotu-assistant-bot/:path*'
    );
    assert.equal(
      destinations['/gaotu-assistant-agent/:path*'],
      'http://127.0.0.1:18291/gaotu-assistant-agent/:path*'
    );
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = value;
      }
    }
  }
});

test('internal paths are blocked before the general Bot rewrite (Task C2)', async () => {
  // `/gaotu-assistant-bot/:path*` 那条通用规则会把 `/inner/...` 一并透到后端 ✗；
  // rewrite 是**按顺序**匹配的 ✓，所以内网守卫必须排在它前面 ✓。
  const previous = {
    APP_ENV: process.env.APP_ENV,
    NEXT_PUBLIC_ASSISTANT_API_BASE_URL: process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL,
    NEXT_PUBLIC_AGENT_API_BASE_URL: process.env.NEXT_PUBLIC_AGENT_API_BASE_URL,
  };
  process.env.APP_ENV = 'dev';
  process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL = 'http://127.0.0.1:18290';
  process.env.NEXT_PUBLIC_AGENT_API_BASE_URL = 'http://127.0.0.1:18291';

  try {
    const { default: config } = await import(`../../next.config.mjs?test=${Date.now()}`);
    const rewrites = await config.rewrites();
    const destinations = Object.fromEntries(
      rewrites.map(({ source, destination }) => [source, destination])
    );

    assert.equal(
      destinations['/gaotu-assistant-bot/inner/:path*'],
      '/__codex_internal_blocked__',
      '内网路径不得指向后端'
    );
    assert.match(rewrites[0].source, /^\/gaotu-assistant-bot\/inner\//, '守卫必须排在第一条');
    assert.equal(
      destinations['/gaotu-assistant-bot/:path*'],
      'http://127.0.0.1:18290/gaotu-assistant-bot/:path*',
      '通用规则仍在（没被守卫顶掉）'
    );
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = value;
      }
    }
  }
});
