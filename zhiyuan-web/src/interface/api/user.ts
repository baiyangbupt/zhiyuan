export interface ILoginParams {
  userName: string;
  password: string;
}
export interface ILoginByTokenParams {
  token: string;
  channel: string;
}
export interface ILoginMobileParams {
  mobile: string;
  verifyCode: string;
}
export interface ISendCodeParams {
  mobile: string;
}

export interface ILoginRes {
  loginToken: string;
  botId: number;
  tenantId: number;
  hasAddInfo: boolean;
  isCustomer: boolean;
}
