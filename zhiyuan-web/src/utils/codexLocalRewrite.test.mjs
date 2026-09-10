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
