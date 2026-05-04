import { AxiosResponse } from 'axios';
import { getSid, getToken, getTicket, getYuzhiToken } from '@/utils/tool';
import { isClient, tenant } from '@/constants/constants';
import { message } from '@/store/message';
import getSign from '@/utils/encryptData';
import Request from './request';
import type { RequestConfig } from './request/types';
import { navigateTo } from '@/utils/router';

const noTipsErrorCodeArr = [50001, 40009, 40004, 40005, 40001, 40010, 401, 34, 40013];
const redirectCode = 700;

export interface YWZResponse<T> {
  code: number;
  data: T;
  extra?: any;
  isSuccess: boolean;
  msg: string;
}

// 重写返回类型
interface YWZRequestConfig<T, R> extends RequestConfig<YWZResponse<R>> {
  data?: T;
  special?: number[];
}

const baseURL = isClient ? '' : process.env.NEXT_PUBLIC_API_BASE_URL;
const commonPath = ['/addVolunteer', '/myVolunteer'];

const request = new Request({
  baseURL,
  timeout: 180000,
  headers: {
    'Content-Type': 'application/json;charse=UTF-8',
  },
  withCredentials: true,
  interceptors: {
    // 请求拦截器
    requestInterceptors(config) {
      const sign = getSign(config);
      // 客户端token取自local，服务端token请config.header中自带
      if (isClient) {
        // 服务端无window对象
        const { pathname, origin, search } = window.location;
        // 专家页面和戴鹏页面区分 域名区分
        // 专家
        if (origin.includes('zj-gtzy') || origin.includes('3002')) {
          config.headers['gtgz-sid'] = getSid();
          if (!config.headers.token) {
            config.headers.token = commonPath.includes(pathname) ? getTicket() : getToken();
          }
        }
        // C端
        else if (window === window.top || pathname.includes('advanceBatch')) {
          config.headers['gtgz-sid'] = getSid();
        } else if (search.includes('parentIframe=saas')) {
          const saasInfo = getSaasInfo();
          config.headers.uToken = saasInfo.uToken || '';
          config.headers.institutionId = saasInfo.institutionId || '';
        } else if (!config.headers.token) {
          config.headers.token = commonPath.includes(pathname) ? getTicket() : getToken();
        }
        config.headers.token = getYuzhiToken();
      }
      config.headers.sign = sign;
      config.headers.platform = 'pc_gtzy';
      config.headers['X-Cas-Redirect-Switch'] = 'disable';
      if (!config.headers.tenant && !config.url?.includes('/h5/')) {
        config.headers.tenant = tenant;
      }
      if (!config.headers.Authorization) {
        config.headers.Authorization = 'Basic bGFtcF93ZWI6bGFtcF93ZWJfc2VjcmV0';
      }
      if (!isClient) {
        console.log('请求开始', config);
      }
      return config;
    },
    // 响应拦截器
    responseInterceptors(response: any): AxiosResponse<any, any> {
      if (!isClient) {
        console.log('响应开始', response);
      }
      if (response.data.code === redirectCode && process.env.APP_ENV !== 'dev') {
        // 跳转 CAS
        window.location.href = `${window.location.origin}/gateway-api/ac/getAuth`;
        return response;
      }
      if (response.config.responseType === 'blob') {
        return response;
      }
      if (
        (response.config.special || []).includes(response.data.code) ||
        response.data.code === 0 ||
        response.data.isSuccess ||
        !isClient
      ) {
        return response;
      }
      if (!noTipsErrorCodeArr.includes(response.data.code)) {
        message.error(response.data.msg || response.data.message);
      }
      if (response.data.code === 403) {
        navigateTo('/login');
        return response;
      }
      return response;
    },
    // 响应失败回调
    responseInterceptorsCatch(err: any) {
      if (!isClient) {
        console.log('响应失败', err);
      }
      if (!isClient) {
        return err.response;
      }
      let messageStr = '连接到服务器失败';
      if (err && err.response) {
        switch (err.response.status) {
          case 400:
            messageStr = '错误请求';
            break;
          case 401:
            messageStr = '未授权，请重新登录';
            break;
          case 403:
            messageStr = '没有访问权限，拒绝访问';
            navigateTo('/login');
            break;
          case 404:
            messageStr = '请求错误,未找到该资源';
            break;
          case 405:
            messageStr = '请求方法未允许';
            break;
          case 408:
            messageStr = '请求超时';
            break;
          case 500:
            messageStr = err.response.msg || '服务器异常';
            break;
          case 501:
            messageStr = '网络未实现';
            break;
          case 502:
            messageStr = '网络错误';
            break;
          case 503:
            messageStr = '服务不可用';
            break;
          case 504:
            messageStr = '网络超时';
            break;
          default:
            messageStr = `连接错误${err.response.msg}`;
        }
        message.error(messageStr);
        return err.response;
      }
      if (err.code === 'ERR_NETWORK') {
        message.error('网络错误');
      }
      return Promise.reject(err);
    },
  },
});

/**
 * @description: 函数的描述
 * @generic D 请求参数
 * @generic T 响应结构
 * @param {YWZRequestConfig} config 不管是GET还是POST请求都使用data
 * @returns {Promise}
 */
const ywzRequest = <D = any, T = any>(config: YWZRequestConfig<D, T>) => {
  const { method = 'GET' } = config;
  if (method === 'get' || method === 'GET') {
    config.params = config.data;
  }
  return request.request<YWZResponse<T>>(config);
};
// // 取消请求
export const cancelRequest = (url: string | string[]) => request.cancelRequest(url);
// 取消全部请求
export const cancelAllRequest = () => request.cancelAllRequest();

export default ywzRequest;
