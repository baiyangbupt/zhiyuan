import request from '@/service/index';
import {
  ILoginByTokenParams,
  ILoginMobileParams,
  ILoginParams,
  ILoginRes,
  ISendCodeParams,
} from '@/interface/api/user';
import { ICheckRightsRes, OperateCheckPoint } from '@/interface/api/assistant';

// 用户登录-用户名密码
export const loginApi = (data: ILoginParams) =>
  request<ILoginParams, ILoginRes>({
    url: `/gaotu-assistant-bot/chat/user/login/by-pwd`,
    method: 'post',
    data,
  });
// 用户登录-手机号验证码
export const loginMobileApi = (data: ILoginMobileParams) =>
  request<ILoginMobileParams, ILoginRes>({
    url: `/gaotu-assistant-bot/chat/user/login/by-mobile`,
    method: 'post',
    data,
  });
// 发送验证码
export const sendCodeApi = (data: ISendCodeParams) =>
  request<ISendCodeParams, any>({
    url: `/gaotu-assistant-bot/chat/user/login/send-code?mobile=${data.mobile}`,
    method: 'post',
    // data,
  });
// 获取用户信息
export const getUserInfoApi = () =>
  request<ISendCodeParams, any>({
    url: `/gaotu-assistant-bot/chat/user/info`,
    method: 'get',
  });
// 更新用户信息
export const updateUserInfoApi = (data: any) =>
  request<ISendCodeParams, any>({
    url: `/gaotu-assistant-bot/chat/user/update-info`,
    method: 'post',
    data,
  });
// 获取oss签名
export const getOssSignApi = () =>
  request<ISendCodeParams, any>({
    url: `/gaotu-assistant-bot/base-data/get-oss-sign?dir=user`,
    method: 'get',
  });
// 根据channel&token登录
export const getLoginByTokenApi = ({ channel, token }: { channel: string; token: string }) =>
  request<ILoginByTokenParams, any>({
    url: `/gaotu-assistant-bot/chat/user/login/by-token`,
    method: 'post',
    data: {
      channel,
      token,
    },
  });

export const checkUserRightsApi = (data: { checkPoint: OperateCheckPoint; prepareType?: string }) =>
  request<{ checkPoint: OperateCheckPoint; prepareType?: string }, ICheckRightsRes>({
    url: `/gaotu-assistant-bot/chat/user/check-rights?checkPoint=${data.checkPoint}${
      data.prepareType ? `&prepareType=${data.prepareType}` : ''
    }`,
    method: 'get',
  });
