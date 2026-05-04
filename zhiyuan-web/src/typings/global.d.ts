declare module 'habo';

declare module 'qrcodejs2';

declare module 'file-saver';

declare module 'md5';

declare module 'react-dnd';

declare const twemoji: {
    parse: (content: string) => string;
};
declare interface Window {
    WVJBCallbacks?: [(params: unknown) => void];
    WVJBInterface: {
        [key: string]: (params: unknown) => void;
    };
    WebViewJavascriptBridge: {
        [key: string]: (params: unknown) => void;
    };
    loadingFlag: boolean;
    twemoji: twemoji;
    MathJax: any;
    __wxjs_environment: string;
}

declare type Item = {
    key: string;
    data: string;
}

declare type MajorLevel = '01' | '02';

declare type DegreeLevel = 'academic' | 'professional';
declare interface CSSProperties extends CSS.Properties<string | number>, Partial<Record<string, string>> {
}

type AnyObject = {
    [key: string]: any;
}
