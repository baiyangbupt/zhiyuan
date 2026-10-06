import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * 内网面在生产层的守卫（2026-10-06，P0）。
 *
 * 为什么是 middleware 而不是 rewrites：production 的 rewrite 要匹配浏览器实际请求的
 * **根路径**（`/gaotu-assistant-bot/inner/...`，浏览器不带 basePath ✗）就必须 `basePath: false` ✓；
 * 而 Next 13.5 校验要求 `basePath: false` 的 rewrite 目标以 http(s) 开头 ✗——
 * 死路径（`/__codex_internal_blocked__`）技巧会让构建直接失败 ✓（实测 `Error: Invalid rewrites found`）。
 * dev/test 分支没有这个问题（它们 basePath 为空或守卫本就不覆盖真实流量 ✗），保持原样 ✓。
 *
 * 注意口径：**公网 test-www 的 `/gaotu-assistant-bot/` 在代理层直通 Java、不经过 Next** ✗，
 * 这道守卫只覆盖「直连 3001」与「代理把 bot 前缀交给 Next」的部署形态 ✓；
 * P0 的第一道永远是代理层的 `location` 404 ✓（见 `ops/nginx/test-www.locations.conf`）。
 *
 * 返回 404 而不是 403 ✓：不向匿名者泄露路径存在性 ✓。
 */

const GUARDED_PREFIXES = [
  '/gaotu-assistant-bot/inner',
  '/gaotu-assistant-bot/internal',
  '/gaotu-assistant-bot/admin',
  '/gaotu-assistant-bot/debug',
  '/internal/evidence',
];

function isGuardedPath(pathname: string): boolean {
  // middleware 在不同 Next 版本里看到 pathname **是否带 basePath 不一样** ✓，
  // 这里把两种形态都归一后再比对 ✓，不押注单一行为。
  const stripped = pathname.startsWith('/assistant-pc/')
    ? pathname.slice('/assistant-pc'.length)
    : pathname;
  return GUARDED_PREFIXES.some(
    (prefix) => stripped === prefix || stripped.startsWith(`${prefix}/`)
  );
}

export function middleware(request: NextRequest) {
  if (isGuardedPath(request.nextUrl.pathname)) {
    return new NextResponse('Not Found', { status: 404 });
  }
  return NextResponse.next();
}

export const config = {
  // 只挂这些前缀 ✓（不给所有请求加开销 ✗）；
  // basePath 两种形态都列上 ✓，命中与否由 `isGuardedPath` 决定 ✓。
  matcher: [
    '/gaotu-assistant-bot/inner/:path*',
    '/gaotu-assistant-bot/internal/:path*',
    '/gaotu-assistant-bot/admin/:path*',
    '/gaotu-assistant-bot/debug/:path*',
    '/internal/evidence/:path*',
    '/assistant-pc/gaotu-assistant-bot/inner/:path*',
    '/assistant-pc/gaotu-assistant-bot/internal/:path*',
    '/assistant-pc/gaotu-assistant-bot/admin/:path*',
    '/assistant-pc/gaotu-assistant-bot/debug/:path*',
    '/assistant-pc/internal/evidence/:path*',
  ],
};
