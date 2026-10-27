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
    assert.equal(destinations['/ws/chat'], 'http://127.0.0.1:18291/ws/chat');
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

test('production rewrites guard internal paths before the general Bot rule (P0, 2026-10-06)', async () => {
  // 生产分支此前**漏挂**守卫 ✗（公网 `/gaotu-assistant-bot/inner/...` 直通后端返回 200 ✓
  // 由 2026-10-05 复核实证）。生产守卫的形状是三个实测约束逼出来的 ✓：
  // 1. `basePath: false` ✓（浏览器请求根路径 ✗）；2. 该形态的目标必须是外部 http(s) URL ✓
  // （相对死路径直接构建失败 ✗，实测 `Error: Invalid rewrites found` ✓）；
  // 3. 死路径落在 Agent 上 ✓（Agent 对未映射路径回干净 404 ✓，后端统一回 500 ✗）。
  const previous = {
    APP_ENV: process.env.APP_ENV,
    NEXT_PUBLIC_ASSISTANT_API_BASE_URL: process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL,
    NEXT_PUBLIC_AGENT_API_BASE_URL: process.env.NEXT_PUBLIC_AGENT_API_BASE_URL,
    NEXT_PUBLIC_OUTER_API_BASE_URL: process.env.NEXT_PUBLIC_OUTER_API_BASE_URL,
  };
  process.env.APP_ENV = 'production';
  process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL = 'http://127.0.0.1:18090';
  process.env.NEXT_PUBLIC_AGENT_API_BASE_URL = 'http://127.0.0.1:18091';
  process.env.NEXT_PUBLIC_OUTER_API_BASE_URL = 'https://test-www.gaotuzhiyuan.com';

  try {
    const { default: config } = await import(`../../next.config.mjs?test=${Date.now()}`);
    const rewrites = await config.rewrites();

    assert.match(rewrites[0].source, /^\/gaotu-assistant-bot\/inner\//, '守卫必须排在第一条');
    for (const source of [
      '/gaotu-assistant-bot/inner/:path*',
      '/gaotu-assistant-bot/internal/:path*',
      '/gaotu-assistant-bot/admin/:path*',
      '/gaotu-assistant-bot/debug/:path*',
      '/internal/evidence/:path*',
    ]) {
      const guard = rewrites.find((rule) => rule.source === source);
      assert.ok(guard, `生产分支缺守卫 ${source}`);
      assert.equal(
        guard.destination,
        'http://127.0.0.1:18091/__codex_internal_blocked__',
        `${source} 应指向 Agent 死路径（干净 404），不得指向任何可达业务端点`
      );
      assert.equal(guard.basePath, false, `${source} 必须 basePath:false 才匹配根路径流量`);
    }

    const botIndex = rewrites.findIndex((rule) => rule.source === '/gaotu-assistant-bot/:path*');
    const lastGuardIndex = rewrites.findIndex(
      (rule) => rule.source === '/internal/evidence/:path*'
    );
    assert.ok(botIndex > lastGuardIndex, '守卫必须全部排在通用规则之前');

    const bot = rewrites[botIndex];
    assert.equal(bot.destination, 'http://127.0.0.1:18090/gaotu-assistant-bot/:path*', '通用规则仍在');
    assert.equal(bot.basePath, false);

    for (const rule of rewrites) {
      if (rule.basePath === false) {
        assert.match(
          rule.destination,
          /^https?:\/\//,
          `${rule.source}：basePath:false 的目标必须是外部 URL，否则 Next 13.5 构建失败`
        );
      }
    }

    const { readFileSync } = await import('node:fs');
    const middlewareSource = readFileSync(new URL('../middleware.ts', import.meta.url), 'utf8');
    for (const prefix of [
      '/gaotu-assistant-bot/inner',
      '/gaotu-assistant-bot/internal',
      '/gaotu-assistant-bot/admin',
      '/gaotu-assistant-bot/debug',
      '/internal/evidence',
    ]) {
      assert.ok(middlewareSource.includes(prefix), `middleware 守卫缺前缀 ${prefix}`);
    }
    assert.match(middlewareSource, /status: 404/, '守卫应以 404 拒绝');
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
