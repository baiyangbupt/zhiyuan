import Cookies from 'js-cookie';
import { EXPERT_DETAIL } from '@/constants/constants';

// 是否为浏览器环境
export const isClient = typeof window !== 'undefined';

export const objToUrl = (object: { [key: string]: any }) => {
  const list = [];
  for (const i in object) {
    if (Object.prototype.hasOwnProperty.call(object, i)) {
      list.push(`${encodeURIComponent(i)}=${encodeURIComponent(object[i])}`);
    }
  }
  return list.join('&');
};

/**
 * @description: 获取url上的参数转为键值对
 * @param serverUrl: 服务端渲染时手动传入url
 */
export const getSearchParams = (serverUrl = '') => {
  if (!isClient && !serverUrl) {
    return {};
  }
  const searchString = serverUrl ? serverUrl.split('?')[1] : location.search.substring(1);
  const searchArray = searchString?.split('&').filter(item => item) || [];
  const searchJson: { [key: string]: string } = searchArray.reduce(
    (prev: { [key: string]: string }, cur: string) => {
      const [key, value] = cur.split('=');
      return {
        ...prev,
        [key]: value,
      };
    },
    {}
  );
  return searchJson;
};

export const getSid = () => {
  if (!isClient) {
    return '';
  }
  return Cookies.get('gtgz-sid') || Cookies.get('sid') || '';
};

export enum EStorageKey {
  ZJ_TICKET = 'zj_ticket',
  LAMP_WEB_TOKEN = 'output/lamp-web_TOKEN',
  ZY_SAAS_PC = 'b_saasInfo_pc',
  TOKEN = 'token',
  BOT_ID = 'botId',
  TENANT_ID = 'tenantId',
  HASADDINFO = 'hasAddInfo',
  ISCUSTOMER = 'isCustomer',
  CHANNEL = 'channel',
  SOURCE = 'source',
}

export type KeyType = EStorageKey | string;

export const getYuzhiToken = () => {
  if (!isClient) {
    return '';
  }
  const token = getStorage(EStorageKey.TOKEN);
  return typeof token === 'string' ? token : '';
};

export const getSaasInfo = () => {
  const stored = getStorage(EStorageKey.ZY_SAAS_PC);
  if (!stored || typeof stored !== 'object' || Array.isArray(stored)) {
    return { uToken: '', institutionId: '' };
  }
  const uToken = 'uToken' in stored && typeof stored.uToken === 'string' ? stored.uToken : '';
  const institutionId = 'institutionId' in stored ? stored.institutionId : null;
  return {
    uToken,
    institutionId:
      typeof institutionId === 'string' ||
      (typeof institutionId === 'number' && Number.isFinite(institutionId))
        ? String(institutionId)
        : '',
  };
};

// 统一前缀：所有 localStorage key 一律加上该前缀
const YTELL_PREFIX = 'ytell_';
function getPrefixedKey(rawKey: string): string {
  return rawKey.startsWith(YTELL_PREFIX) ? rawKey : `${YTELL_PREFIX}${rawKey}`;
}

export const getStorage = (key: KeyType): unknown => {
  if (!isClient) {
    return '';
  }

  function getValue(key: string) {
    const prefixedKey = getPrefixedKey(key);
    // 读取时优先取带前缀的值
    const value = localStorage.getItem(prefixedKey);
    try {
      return JSON.parse(value as string);
    } catch {
      return value;
    }
  }
  return getValue(key);
};

export const clearStorage = (key: KeyType[]): boolean => {
  if (!isClient) {
    return false;
  }
  function clearValue(key: KeyType) {
    const prefixedKey = getPrefixedKey(String(key));
    localStorage.removeItem(prefixedKey);
  }
  for (const keyItem of key) {
    clearValue(keyItem);
  }
  return true;
};

export const setStorage = (data: { key: KeyType; value: unknown }[]): boolean => {
  if (!isClient) {
    return false;
  }
  function setValue(dataItem: { key: KeyType; value: unknown }) {
    const keyStr = String(dataItem.key);
    const prefixedKey = getPrefixedKey(keyStr);
    localStorage.setItem(prefixedKey, JSON.stringify(dataItem.value));
  }
  for (const dataItem of data) {
    setValue(dataItem);
  }
  return true;
};

export const getToken = () => `Bearer ${getStorage(EStorageKey.LAMP_WEB_TOKEN) || ''}`;

export const getTicket = () => `Bearer ${getStorage(EStorageKey.ZJ_TICKET) || ''}`;

export function getValueFromUrlBykey(key: string) {
  if (!isClient) {
    return '';
  }
  const url = new URL(window.location.href);
  // 取url参数上的第一个匹配的key
  const param = url.searchParams.get(key);
  return param ? param : null;
}

export function getUa(): {
  isWechatMP: boolean;
  isAndroid: boolean;
  isIOS: boolean;
  isXApp: {
    isGaotuApp: boolean;
    isGongkaoApp: boolean;
    isTutuApp: boolean;
    isJingpinApp: boolean;
  };
} {
  let ua = '';
  if (isClient) {
    ua = window.navigator.userAgent.toLocaleLowerCase();
  }
  const isAndroid = /android/i.test(ua);
  const isIOS = /(iPhone|iPad|iPod|iOS)/i.test(ua);

  const isWechatMP: boolean =
    ua.includes('miniprogram') || window.__wxjs_environment === 'miniprogram';
  const getIsXApp = (appName: string) =>
    ua.includes('gaotuapp-') && new RegExp(`/${appName}(/noah)?$`).test(ua);
  const isXApp = {
    isGaotuApp: getIsXApp('gaotu'),
    isGongkaoApp: getIsXApp('gongkao'),
    isTutuApp: getIsXApp('tutu'),
    isJingpinApp: getIsXApp('jingpin'),
  };

  return {
    isWechatMP,
    isAndroid,
    isIOS,
    isXApp,
  };
}

// 是否是app
export function isApp(): boolean {
  let ua = '';
  if (isClient) {
    ua = window.navigator.userAgent;
  }
  return ua.includes('gaotuapp');
}

export const formatPhoneNumber = (value: string) => {
  const match = value.match(/^(\d{3})(\d{0,4})(\d{0,4})$/);
  if (match) {
    return match.slice(1).filter(Boolean).join(' '); // 以空格分隔
  }
  return value;
};

export const encryptPhoneNumber = (value: string) =>
  value.replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2');

export const getUserId = (): number | null => {
  if (isClient) {
    return Number(Cookies.get('gtgz-userId')) || Number(Cookies.get('userId')) || null;
  }
  return null;
};

export const gtgzCEnv = () => {
  if (isClient) {
    return location.host !== process.env.NEXT_GTCAS_C_HOST;
  }
  return true;
};

// 计算平铺之后的数组长度
export const getTotalRecordCount = (records: any[]) =>
  records.reduce((total, record) => {
    let count = 1; // 当前节点本身
    if (record.children && record.children.length > 0) {
      count += getTotalRecordCount(record.children);
    }
    return total + count;
  }, 0);

//
export const getKeys = (data: any) => {
  const keys: string[] = [];
  data.forEach((item: any) => {
    keys.push(item.preEnrollSchoolId + (item.preEnrollMajorId || ''));
    if (item.children) {
      keys.push(...getKeys(item.children));
    }
  });
  return keys;
};

// 禁止浏览器复制
export function prohibitCopy() {
  // 禁止右键菜单
  document.oncontextmenu = function () {
    return false;
  };
  // 禁止文字选择
  document.onselectstart = function () {
    return false;
  };
  // 禁止复制
  document.oncopy = function () {
    return false;
  };
  // ios
  document.oncontextmenu = function (e) {
    e.preventDefault();
  };
  document.onselectstart = function (e) {
    e.preventDefault();
  };
  // 安卓
  document.addEventListener('contextmenu', e => {
    e.preventDefault();
  });
  document.ontouchend = function () {
    // throw new Error('NO ERRPR:禁止长按弹出');
  };
  // 禁止剪切
  document.oncut = function () {
    return false;
  };
  // 禁用 Ctrl+S
  // todo
  // 禁止页面被嵌入进其他iframe中
  // todo
}

/**
 * @param targetUrl string 目标url
 * @param deleteKeys string[] 需要删除的key list
 * @param query Record<PropertyKey, PropertyKey> 需要添加的key 和 value
 * @param replaceUrl string 替换的url
 */
interface IHandleHistoryReplaceStateConfig {
  deleteKeys?: string[];
  query?: Record<PropertyKey, PropertyKey>;
}

export function getLocationOrigin(urlObj: URL) {
  const { protocol, hostname, port } = urlObj;
  return `${protocol}//${hostname}${port ? `:${port}` : ''}`;
}

export function getURL(urlObj: URL) {
  const { href } = urlObj;
  const origin = getLocationOrigin(urlObj);
  return href.substring(origin.length);
}

/**
 * @description replace history使用
 * @param config
 * @type IHandleHistoryReplaceStateConfig
 */
export function handleHistoryReplaceState(config: IHandleHistoryReplaceStateConfig) {
  const { deleteKeys = [], query = {} } = config ?? {};
  const urlObj = new URL(location.href);
  for (const key of deleteKeys) {
    urlObj.searchParams.delete(key);
  }
  Object.keys(query).forEach((key: keyof typeof query) => {
    urlObj.searchParams.set(key as string, query[key] as string);
  });
  // 初次加载next/router会赋值state，当浏览器的返回按钮点击时，若state未空值，next/router不会进行刷新操作
  const asPath = getURL(urlObj);
  const { state } = history;
  const { options, __N, key } = state || {};
  history.replaceState(
    {
      url: asPath,
      as: asPath,
      options,
      __N,
      key,
    },
    '',
    asPath
  );
}

export const returnSaas = () => {
  const searchParams = getSearchParams();
  top?.location.replace(
    `${process.env.NEXT_B_SAAS_ORIGIN}${EXPERT_DETAIL}?memberId=${
      searchParams.memberId || ''
    }&expertId=${searchParams.expertId || ''}`
  );
};

export const jumpOldPage = (pathParams: string, usePCHost = false) => {
  const getJumpOrigin = () => {
    if (usePCHost || process.env.APP_ENV === 'dev' || !isClient) {
      return process.env.NEXT_GTZY_C_PC_ORIGIN;
    }
    return `https://${location.host}`;
  };
  window.open(`${getJumpOrigin()}/oldPage?pathParams=${encodeURIComponent(pathParams)}`);
};
