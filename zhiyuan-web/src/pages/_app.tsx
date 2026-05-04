import type { AppProps } from 'next/app';
import Head from 'next/head';
import { ConfigProvider, App } from 'antd';
import zhCN from 'antd/lib/locale/zh_CN';
import { useEffect } from 'react';
import '@/styles/globals.scss';
import '@/images/icons/index';
import AppComponent from '@/components/appComponent';
// import { prohibitCopy } from '@/utils/tool';

export default function RootApp({ Component, pageProps }: AppProps) {
  // useEffect(() => {
  //   prohibitCopy();
  // }, []);

  return (
    // <ConfigProvider theme={{hashed: false, token: {colorPrimary: '#2266ff'}}} locale={zhCN}>
    <ConfigProvider theme={{ hashed: false, token: { colorPrimary: '#FF443D' } }} locale={zhCN}>
      <App component={false} message={{ maxCount: 1 }}>
        <AppComponent>
          <Head>
            <title>高途AI志愿填报</title>
            <meta
              name="viewport"
              content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"
            />
          </Head>
          <Component {...pageProps} />
        </AppComponent>
      </App>
    </ConfigProvider>
  );
}
