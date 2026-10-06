import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const basePath = process.env.APP_ENV === 'dev' ? '' : '/assistant-pc';
const defaultProductionOrigin = 'https://www.gaotuzhiyuan.com';

const normalizeOrigin = (value, fallback = defaultProductionOrigin) => {
  const normalized = (value || '').trim().replace(/\/+$/, '');
  return normalized || fallback;
};

// 内网面在**代理层**就挡住 ✓（Task C2）：`/gaotu-assistant-bot/:path*` 那条通用规则
// 会把 `/inner/...` 一并透到后端 ✗——rewrite 是**按顺序**匹配的 ✓，所以这些守卫必须排在它前面 ✓。
// 目标指向一个不存在的路径 ✓：Next 于是回 404 ✓（rewrites 没有"直接返回 404"的写法 ✓）。
const INTERNAL_PATH_GUARDS = [
  '/gaotu-assistant-bot/inner/:path*',
  '/gaotu-assistant-bot/internal/:path*',
  '/gaotu-assistant-bot/admin/:path*',
  '/gaotu-assistant-bot/debug/:path*',
  '/internal/evidence/:path*',
].map((source) => ({ source, destination: '/__codex_internal_blocked__' }));

const configObj = {
  transpilePackages: ['antd', '@sentry/nextjs'],
  productionBrowserSourceMaps: true,
  reactStrictMode: false,
  basePath,
  // 隔离栈的 `next dev`（3201）与标准栈的 `next start`（3001）**长期共用同一个 `.next`** ✗——
  // dev 一启动就把生产构建的 server 文件清掉 ✓，运行中的 3001 随即 500 ✓
  // （2026-10-06 实证：公网 /assistant-pc/login 500）。拆目录根治：
  // dev 栈由 `scripts/start-codex-local.sh` 注入 `NEXT_DIST_DIR=.next-dev` ✓，
  // 生产/标准栈不设该变量、保持默认 `.next` ✓，两边可并行跑。
  distDir: process.env.NEXT_DIST_DIR || '.next',
  swcMinify: true,
  compiler: {
    reactRemoveProperties: process.env.NODE_ENV === 'production',
  },
  // 禁用构建时的 ESLint 检查
  eslint: {
    ignoreDuringBuilds: true,
  },
  // 添加 TypeScript 配置
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    minimumCacheTTL: 31536000,
    unoptimized: true,
    domains: [
      's2.loli.net',
      'hl-backend-prod.oss-cn-beijing.aliyuncs.com',
      'p.gsxcdn.com',
      'test-i.gsxcdn.com',
      'i.gsxcdn.com',
      'test-p.gsxcd.com',
      'test-hl-wish-file-bucket.oss-cn-beijing.aliyuncs.com',
      'hl-wish-file-bucket.oss-cn-beijing.aliyuncs.com',
      'gtoss.gsxcdn.com',
    ],
  },
  // 环境变量
  env: {
    BABEL_ENV: process.env.BABEL_ENV,
    APP_ENV: process.env.APP_ENV,
    BASE_URL: basePath,
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    NEXT_GTZY_C_PC_ORIGIN: process.env.NEXT_GTZY_C_PC_ORIGIN,
    DEFAULT_SOURCE: process.env.DEFAULT_SOURCE,
    NEXT_B_SAAS_ORIGIN: process.env.NEXT_B_SAAS_ORIGIN,
    NEXT_GTCAS_C_HOST: process.env.NEXT_GTCAS_C_HOST,
    NEXT_GTZY_C_MWEB_ORIGIN: process.env.NEXT_GTZY_C_MWEB_ORIGIN,
    NEXT_GTCAS_C_MWEB_ORIGIN: process.env.NEXT_GTCAS_C_MWEB_ORIGIN,
    NEXT_PUBLIC_ASSISTANT_API_BASE_URL: process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL,
    NEXT_PUBLIC_AGENT_API_BASE_URL: process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || '',
    NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE: process.env.NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE || '',
    NEXT_PUBLIC_OUTER_API_BASE_URL: process.env.NEXT_PUBLIC_OUTER_API_BASE_URL,
  },

  webpack(config, options) {
    const { isServer } = options;

    // 添加路径别名
    config.resolve.alias = {
      ...config.resolve.alias,
      '@': path.join(__dirname, 'src'),
    };

    if (!isServer) {
      const { cacheGroups } = config.optimization.splitChunks;
      if (cacheGroups) {
        cacheGroups.vendors = {
          test: /[\\/]node_modules[\\/](axios|classnames|js-base64|mobx|mobx-react-lite|jsencrypt|crypto-js|qs|svg-sprite-loader|md5|js-cookie)[\\/]/,
          name: 'vendors',
          chunks: 'all',
          priority: 1,
        };
        cacheGroups.antd = {
          test: /[\\/]node_modules[\\/]antd[\\/](es|lib)[\\/]/,
          name: 'antd',
          chunks: 'all',
          priority: 1,
        };
        cacheGroups.antdVendors = {
          test: /[\\/]node_modules[\\/](@?rc-.*|@ant-design|qrcode.react)[\\/]/,
          name: 'antdVendors',
          chunks: 'all',
          priority: 1,
        };
      }
    }
    // next-image-loader不处理*.local. 格式的图片，交给url处理，自动转base64
    const imageLoaderRule = config.module.rules.find(rule => rule.loader === 'next-image-loader');
    imageLoaderRule.exclude = /\.local\.(png|jpe?g|gif|)$/i;
    config.module.rules.push(
      {
        test: /\.local\.(png|jpe?g|gif)$/i,
        use: [
          {
            loader: 'url-loader',
            options: {
              limit: 100 * 1024,
            },
          },
        ],
      },
      {
        test: /.svg$/,
        loader: 'svg-sprite-loader',
        include: path.resolve(__dirname, './src/images/icons/svgs'),
        options: {
          symbolId: 'icon-[name]',
        },
      }
    );
    return config;
  },
async rewrites() {
    // 开发环境API代理
    if (process.env.APP_ENV === 'dev') {
      const devDomainInner = process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL || 'http://localhost:8080';
      const devDomainAgent = process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || devDomainInner;
      const devDomainOuter = process.env.NEXT_PUBLIC_OUTER_API_BASE_URL || 'https://www.gaotuzhiyuan.com';

      console.log('🔧 开发环境启用API代理');
      return [
        ...INTERNAL_PATH_GUARDS,
        {
          source: '/gaotu-assistant-bot/:path*',
          destination: `${devDomainInner}/gaotu-assistant-bot/:path*`,
        },
        {
          source: '/gaotu-assistant-agent/:path*',
          destination: `${devDomainAgent}/gaotu-assistant-agent/:path*`,
        },

        {
          source: '/hl-wish/:path*',
          destination: `${devDomainOuter}/hl-wish/:path*`,
        },
        {
          source: '/v1/:path*',
          destination: `${devDomainOuter}/v1/:path*`,
        },
        {
          source: '/hl-saas/:path*',
          destination: `${devDomainOuter}/hl-saas/:path*`,
        },
      ];
    }
       // 测试环境
       if (process.env.APP_ENV === 'test') {
        console.log('🔧 测试环境启用API代理');
        return [
          ...INTERNAL_PATH_GUARDS,
          {
            source: '/gaotu-assistant-bot/:path*',
            destination: 'https://gaotu-test.ytell.cn/gaotu-assistant-bot/:path*',
          },
          {
            source: '/gaotu-assistant-agent/:path*',
            destination: 'https://gaotu-test.ytell.cn/gaotu-assistant-agent/:path*',
          },

          {
            source: '/hl-wish/:path*',
            destination: 'https://gaotu-test.ytell.cn/hl-wish/:path*',
          },
          {
            source: '/v1/:path*',
            destination: 'https://gaotu-test.ytell.cn/v1/:path*',
          },
          {
            source: '/hl-saas/:path*',
            destination: 'https://gaotu-test.ytell.cn/hl-saas/:path*',
          },
        ];
      }
    if (process.env.APP_ENV === 'production') {
      const assistantApiBase = normalizeOrigin(
        process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL
      );
      const agentApiBase = normalizeOrigin(
        process.env.NEXT_PUBLIC_AGENT_API_BASE_URL ||
          process.env.NEXT_PUBLIC_ASSISTANT_API_BASE_URL ||
          process.env.NEXT_PUBLIC_API_BASE_URL
      );
      const outerApiBase = normalizeOrigin(
        process.env.NEXT_PUBLIC_OUTER_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL
      );
      console.log('🔧 线上环境启用API代理');
      return [
        // 内网面守卫（2026-10-06，P0）✓。三个实测约束决定了这个形状：
        // 1. 必须 `basePath: false` ✓——浏览器请求根路径（不带 /assistant-pc ✗），
        //    否则守卫匹配不到真实流量；
        // 2. `basePath: false` 的目标**必须是外部 http(s) URL** ✓（Next 13.5 校验 ✗，
        //    相对死路径会让构建直接失败：`Error: Invalid rewrites found`）；
        // 3. 所以死路径落在上游上：**Agent 的未映射路径** ✓——实测回干净的 404 JSON ✓
        //    （后端对未映射路径统一回 500 ✗，Agent 才符合"404 拒绝"的验收口径 ✓）。
        // 目标里没有可达的业务端点 ✓：请求到此为止，不触碰任何 inner 数据面 ✓。
        // basePath 形态（/assistant-pc/...）由 `src/middleware.ts` 兜住 ✓（两机制互补）。
        ...INTERNAL_PATH_GUARDS.map((guard) => ({
          source: guard.source,
          destination: `${agentApiBase}/__codex_internal_blocked__`,
          basePath: false,
        })),
        {
          source: '/gaotu-assistant-bot/:path*',
          destination: `${assistantApiBase}/gaotu-assistant-bot/:path*`,
          basePath: false,
        },
        {
          source: '/gaotu-assistant-agent/:path*',
          destination: `${agentApiBase}/gaotu-assistant-agent/:path*`,
          basePath: false,
        },
        {
          source: '/hl-wish/:path*',
          destination: `${outerApiBase}/hl-wish/:path*`,
          basePath: false,
        },
        {
          source: '/v1/:path*',
          destination: `${outerApiBase}/v1/:path*`,
          basePath: false,
        },
        {
          source: '/hl-saas/:path*',
          destination: `${outerApiBase}/hl-saas/:path*`,
          basePath: false,
        },
      ];
    }
    return [];
  },
  // 核心修复：JSX 运行时错误
  experimental: {
    forceSwcTransforms: false,
    esmExternals: false,
    proxyTimeout: 180000,
  },
};

export default configObj;
