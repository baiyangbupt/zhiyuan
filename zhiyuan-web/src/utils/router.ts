/**
 * 路由工具函数
 * 统一处理 basePath 的路由跳转
 */

import { getUa, getValueFromUrlBykey } from '@/utils/tool';

// 是否为浏览器环境
const isClient = typeof window !== 'undefined';

// 获取当前环境的 basePath
const getBasePath = (): string => {
    return process.env.APP_ENV === 'dev' ? '' : '/assistant-pc';
};

/**
 * 构建完整的路径（包含 basePath）
 * @param path 相对路径，如 '/session'
 * @returns 完整路径
 */
export const buildPath = (path: string): string => {
    const basePath = getBasePath();
    // 确保路径以 / 开头
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${basePath}${normalizedPath}`;
};

/**
 * 获取 storage 中的 source（小程序端标识）
 */
const getStoredSource = (): string | null => {
    if (!isClient) return null;
    if (getValueFromUrlBykey('source') === 'minip' || getUa().isWechatMP) {
        return 'minip';
    }
    return null;
};

/**
 * 页面跳转（使用 window.location.href）
 * @param path 相对路径，如 '/session'
 * @param query 查询参数对象
 */
export const navigateTo = (path: string, query?: Record<string, string | number>): void => {
    if (!isClient) {
        console.warn('navigateTo called on server side, skipping navigation');
        return;
    }

    const mergedQuery = { ...query };
    const storedSource = getStoredSource();
    if (storedSource === 'minip') {
        mergedQuery.source = 'minip';
    }

    let fullPath = buildPath(path);

    if (Object.keys(mergedQuery).length > 0) {
        const searchParams = new URLSearchParams();
        Object.entries(mergedQuery).forEach(([key, value]) => {
            searchParams.append(key, String(value));
        });
        const queryString = searchParams.toString();
        if (queryString) {
            fullPath += `?${queryString}`;
        }
    }

    window.location.href = fullPath;
};

/**
 * 页面跳转（替换当前历史记录，不产生回退入口）
 * 适用于中转页（如静默登录）跳转后不希望被回退到的场景
 */
export const replaceTo = (path: string, query?: Record<string, string | number>): void => {
    if (!isClient) {
        console.warn('replaceTo called on server side, skipping navigation');
        return;
    }

    const mergedQuery = { ...query };
    const storedSource = getStoredSource();
    if (storedSource === 'minip') {
        mergedQuery.source = 'minip';
    }

    let fullPath = buildPath(path);

    if (Object.keys(mergedQuery).length > 0) {
        const searchParams = new URLSearchParams();
        Object.entries(mergedQuery).forEach(([key, value]) => {
            searchParams.append(key, String(value));
        });
        const queryString = searchParams.toString();
        if (queryString) {
            fullPath += `?${queryString}`;
        }
    }

    window.location.replace(fullPath);
};

/**
 * 页面跳转（新窗口打开）
 * @param path 相对路径，如 '/session'
 * @param query 查询参数对象
 */
export const openInNewTab = (path: string, query?: Record<string, string | number>): void => {
    if (!isClient) {
        console.warn('openInNewTab called on server side, skipping navigation');
        return;
    }
    
    let fullPath = buildPath(path);
    
    if (query) {
        const searchParams = new URLSearchParams();
        Object.entries(query).forEach(([key, value]) => {
            searchParams.append(key, String(value));
        });
        const queryString = searchParams.toString();
        if (queryString) {
            fullPath += `?${queryString}`;
        }
    }
    
    window.open(fullPath, '_blank');
};

/**
 * 获取当前页面的完整路径（包含 basePath）
 * @param path 相对路径
 * @returns 完整的 URL
 */
export const getFullUrl = (path: string): string => {
    if (!isClient) {
        return buildPath(path);
    }
    
    const fullPath = buildPath(path);
    return `${window.location.origin}${fullPath}`;
};

/**
 * 检查当前路径是否匹配指定路径
 * @param path 要检查的路径
 * @returns 是否匹配
 */
export const isCurrentPath = (path: string): boolean => {
    if (!isClient) {
        return false;
    }
    
    const basePath = getBasePath();
    const currentPath = window.location.pathname;
    const targetPath = `${basePath}${path.startsWith('/') ? path : `/${path}`}`;
    return currentPath === targetPath;
}; 

/**
 * 更新页面路径参数
 * @param url 路径
 * @returns 更新后的 URL
 */
export const updateUrlParameter = (paramsObject: Record<string, string>): string => {
    if (!isClient) {
        console.warn('updateUrlParameter called on server side, returning empty string');
        return '';
    }
    
    const url: string = window.location.href;
    const search = new URL(url).search;
    const params = new URLSearchParams(search);

    // 遍历参数对象，逐个设置查询参数
    Object.entries(paramsObject).forEach(([key, value]) => {
        params.set(key, value);
    });

    const baseUrl = url.split('?')[0];
    const newUrl = `${baseUrl}?${params.toString()}`;
    window.history.replaceState({ ...window.history.state, ...paramsObject }, '', newUrl);
    return newUrl
};
