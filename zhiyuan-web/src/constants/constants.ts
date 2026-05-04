import {Base64} from 'js-base64';

export const TIMEOUT = 10000;
export const SUCCESS_CODE = 0;
export const isClient = typeof window !== 'undefined';
export const maxLimitSize = 10 * 1024 * 1024;
export const warnTime = 600;
export const isProd = process.env.APP_ENV === 'production';
export const isTest = process.env.APP_ENV === 'test';
export const unAuthentication = 350701;
export const redirectCode = 302;
export const unSignCode = 700;
export const thirtyDaysToSeconds = 2592000000;
export const imgTypeList = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp'];
export const judgePicReg = /^data:image|.(jpe?g|png|webp)((\?|&)[\w\W]+)?$/;

export const tenant = `${Base64.encode('0002')}`;
export const tenantCode = '0002';

export const navBarGroup: {
    [key: string]: {
        group: string;
        needLogin: boolean;
        needAllInfo?: boolean;
        needVip?: boolean;
        isProjectPath: boolean;
    };
} = {
    // '/': {
    //     group: 'sy',
    //     needLogin: false,
    //     isProjectPath: true,
    // },
    '/session': {
        group: 'session',
        needLogin: false,
        isProjectPath: true,
    },
    '/sessionDetailV2': {
        group: 'session',
        needLogin: false,
        isProjectPath: true,
    },
};

export const showAllDataPro = [
    '370000',
    '330000',
];


export const noLoginPath = ['/session', '/sessionDetailV2'];

export const EXPERT_DETAIL = '/expertDetail';
