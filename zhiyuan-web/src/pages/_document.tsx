import React from 'react';
import {createCache, extractStyle, StyleProvider, legacyLogicalPropertiesTransformer} from '@ant-design/cssinjs';
import Document, {Head, Html, Main, NextScript} from 'next/document';
import type {DocumentContext} from 'next/document';

const MyDocument = () => (
    <Html lang="en" translate="no">
        <Head />
        <body>
            <Main />
            <NextScript />
        </body>
    </Html>
);

MyDocument.getInitialProps = async (ctx: DocumentContext) => {
    const cache = createCache();
    const originalRenderPage = ctx.renderPage;
    ctx.renderPage = () =>
        originalRenderPage({
            enhanceApp: App => props => (
                <StyleProvider cache={cache} transformers={[legacyLogicalPropertiesTransformer]}>
                    <App {...props} />
                </StyleProvider>
            ),
        });

    const initialProps = await Document.getInitialProps(ctx);
    const style = extractStyle(cache, true);
    return {
        ...initialProps,
        styles: (
            <>
                {initialProps.styles}
                <style dangerouslySetInnerHTML={{__html: style}} />
            </>
        ),
    };
};

export default MyDocument;
