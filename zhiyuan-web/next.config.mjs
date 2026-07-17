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

const configObj = {
  transpilePackages: ['antd', '@sentry/nextjs'],
  productionBrowserSourceMaps: true,
  reactStrictMode: false,
  basePath,
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
      const devDomainOuter = process.env.NEXT_PUBLIC_OUTER_API_BASE_URL || 'https://www.gaotuzhiyuan.com';

      console.log('🔧 开发环境启用API代理');
      return [
        {
          source: '/gaotu-assistant-bot/:path*',
          destination: `${devDomainInner}/gaotu-assistant-bot/:path*`,
        },
        {
          source: '/gaotu-assistant-agent/:path*',
          destination: `${devDomainInner}/gaotu-assistant-agent/:path*`,
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
