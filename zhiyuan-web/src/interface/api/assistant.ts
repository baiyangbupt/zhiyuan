export enum EMessageType {
  QUESTION = 'question',
  ANSWER = 'answer',
  PRODUCEZHIYUAN = 'producezhiyuan',
}

export interface ISaveOrUpdateParams {
  id: string;
  chatSessionId: string;
  messageFrom: string;
  meetingId: string;
  contentType: string;
  content: string;
}

export interface ISaveOrUpdateRes {
  id: string;
  getProfileFlag: boolean;
}

export interface ISessionParams {
  tenantId: string;
  chatSessionId: string;
}
export interface IEndSessionParams extends ISessionParams {
  meetingId: string;
}

export interface IUserInfoParams {
  tenantId: string;
  chatSessionId: string;
  meetingId?: string;
  botId?: string;
}

export interface IStartSessionRes {
  wssUrl: string;
  meetingId: string;
}

export interface IUserInfoRes {
  name: string;
  value: string[];
}

export interface ISessionListParams {
  botId: string;
  statusList: string[];
  orderBy: any[];
  searchWord: string;
  page: number;
  pageSize: number;
}

export enum ESessionStatus {
  WAIT = 'WAIT',
  GOING = 'GOING',
  FINISHED = 'FINISHED',
  CLOSE = 'CLOSE',
}

export interface IPrepareType {
  code: string; // VOLUNTEER、PREDICT
  desc: string; // 智能填报、模拟填报
}

export interface ISessionListResItem {
  userId: string | number;
  userName: string | number;
  id: string;
  infoSummary: string;
  sessionStatus: ESessionStatus;
  startTime: string;
  endTime: string;
  createTime: string;
  updateTime: string;
  prepareType?: IPrepareType;
}
export interface ISessionListRes {
  current: number;
  records: ISessionListResItem[];
}

export interface ISexAndProvinceAndBatchObject {
  code: string;
  name: string;
}

export interface ISubjectTypeAndExamObject {
  code: string;
  desc: string;
}

export interface ISubjectList {
  isFirst: number;
  subject: string;
  subjectType?: string;
  subjectName: string;
}

export interface ITuitionRange {
  min: number;
  max: number;
}

export interface ICreateSessionParams {
  botId: string;
  // memberId: string;
  // formId: string;
  // mobile: string;
  userName: string; //用户姓名
  userId: string; //用户id
  sex: ISexAndProvinceAndBatchObject; //性别
  examYear: string; //高考年份
  province: ISexAndProvinceAndBatchObject; //高考省份
  specialPlan: boolean; //是否有专项计划
  colorBlindness: boolean; //是否色盲色弱
  subjectList: ISubjectList[]; //高考科目
  subjectScoreList: ISubjectScoreList[]; //各科成绩
  bonusPolicy: boolean; //是否有加分政策
  bonusScore: number; //加分
  totalScore: number; //总分
  batch: ISexAndProvinceAndBatchObject; //批次
  targetType: string; // 填报思路
  subjectType: ISubjectTypeAndExamObject;
  minority: boolean; // 是否少数民族
  examType: ISubjectTypeAndExamObject;
  tuitionRange?: ITuitionRange; // 学费区间
}

export interface IMessageListParams {
  chatSessionId: string;
  orderBy: any[];
  page: number;
  pageSize: number;
}

export interface IMessageListResItem {
  id: string;
  chatSessionId: string;
  messageFrom: string;
  contentType: string;
  content: string;
  displayTime: string;
}
export interface IMessageListRes {
  current: number;
  total: number;
  records: IMessageListResItem[];
}

export interface IMemberSubjectList {
  subjectCode: {
    key: string;
    data: string;
  };
  score: number;
}
export interface ISubjectScoreList {
  subjectName: string;
  subject: string;
  score: number;
}

export type OperateCheckPoint = 'CreateSession' | 'ModifyScore' | 'DoChat';

export interface ICheckRightsRes {
  canOperate: boolean;
  reason?: string;
}

export interface ISubject {
  mobile: string;
  memberName: string;
  sex: string;
  examYear: string;
  area: string;
  specialPlan: string;
  colorBlindness: boolean;
  subject: string;
  grades: string;
  bonusPolicy: string;
  score: number;
  batch: string;
  areaId: string;
  type: string;
  subjectType: string;
  memberSubjectList: IMemberSubjectList[];
  subjectScoreList: ISubjectScoreList[];
}

export interface ISubjectRes {
  formId: string;
  memberId: string;
}

export interface IBasicProfileParams {
  chatSessionId: string;
}
export interface userResObj {
  name: string;
  value: (string | number)[];
}
export interface IBasicProfileRes {
  name: string;
  value: (string | number)[];
}
