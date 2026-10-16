import type {
  ISubjectItem,
  ISubjectTypeAndExamObject,
  ISexAndProvinceAndBatchObject,
} from './updateBaseInfo';

export interface IUserScoreInfo {
  examYear?: number;
  province?: ISexAndProvinceAndBatchObject | null;
  sex?: ISexAndProvinceAndBatchObject | null;
  subjectList?: ISubjectItem[];
  subjectType?: ISubjectTypeAndExamObject;
}

export interface IUpdateUserInfo {
  userName: string;
  avatarUrl?: string;
  userScoreOb?: IUserScoreInfo;
}

export interface IUserInfo {
  id?: string | number;
  userName?: string;
  avatarUrl?: string;
  userLevel?: string;
  expiredDate?: string | number | null;
  userScoreOb?: IUserScoreInfo;
}

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
