export interface IMatches {
  tag: string;
  values: string[];
}

export interface IMajors {
  major_name: string;
  enroll_ratio?: string;
  score: number;
  level?: string;
  matches: IMatches[];
  recommend_school: IRecommendSchoolRes2;
}

export interface ISchoolInfo {
  school_name: string;
  enroll_ratio?: string;
  school_enroll_ratio?: string;
  level?: string;
  score?: number;
  matches?: IMatches[];
  majors?: IMajors[];
}

export interface IRecommendSchoolRes {
  sprints: ISchoolInfo[];
  safes: ISchoolInfo[];
  protects: ISchoolInfo[];
}

export interface IRecommendSchoolRes2 {
  sprint: ISchoolInfo[];
  safe: ISchoolInfo[];
  protect: ISchoolInfo[];
}

export interface IMajorRes {
  major_level_2_name: string;
  child_majors: IMajors[];
}

export interface IBaikeRes {
  id: number;
  name: string;
}

export interface IBaikeDetailRes {
  tag: string;
  value: string;
}

export interface IVersionRes {
  school: number;
  major: number;
  baike: number;
  profile: number;
}

export type SessionStatus = 'FINISHED' | 'WAIT' | 'GOING' | 'CLOSE';
export interface ISessionStatusRes {
  sessionStatus: SessionStatus;
}

export interface IUserProfileRes {
  name: string;
  value: (string | number)[];
}
export interface IUserProfileDynasticRes {
  name: string;
  pvalue: string[];
  nvalue: string[];
}

// 情绪值枚举
export type EmotionValue = 'Strong' | 'Neutral' | 'Weak';
// 极性枚举
export type Polarity = 'POSITIVE' | 'NEGATIVE';

// 用户意向详情
export interface UserIntentValueDetail {
  dimension: string; // 维度编码，如 cityProvince、college、majorLevel2 等
  polarity: Polarity; // POSITIVE / NEGATIVE
  label: string; // 显示名称
  code?: string; // 编码（可选）
  emotion: EmotionValue; // 情绪值（Strong/Neutral/Weak）
  emotionDesc: string; // 情绪描述（强烈/一般/轻微）
}

// 动态画像分组数据
export interface ProfileKVDto {
  name: string; // 分组名称，如"地域-省份""院校""本科专业"
  pDetails: UserIntentValueDetail[]; // 正向字段
  nDetails: UserIntentValueDetail[]; // 负向字段
}

// 保存用户意向情绪的请求项
export interface UserIntentEmotionSaveItem {
  dimension: string; // 维度编码，大小写不敏感
  polarity: Polarity; // POSITIVE/NEGATIVE
  label?: string; // 显示名称（至少 label 或 code 一个非空）
  code?: string; // 编码（优先用于匹配）
  emotion?: EmotionValue; // Strong、Neutral、Weak（deleted=true 时可不填）
  deleted?: boolean; // 删除单条
  deleteAll?: boolean; // 清空该维度+正负向下所有意向
}

// 保存用户意向情绪的请求
export interface UserIntentEmotionSaveReq {
  chatSessionId: number; // 会话 ID
  intents: UserIntentEmotionSaveItem[]; // 意向列表
}
export interface NerItem {
  id: number;
  tagName: string;
  startPos: number;
  endPos: number;
  tagAnalyze: any;
}
export interface IMessage {
  id: number; // 消息id
  chatSessionId?: number; // 会话id
  messageFrom: string; // 发言人
  feedback?: number; // 反馈字段//0：无反馈；1：正反馈；-1：负反馈。
  messageFromUserName?: string; // 发言人姓名（用于腾讯会议SSE）
  contentType?: 'TEXT' | 'CARD'; // TODO: contentType有哪些类型
  content: string;
  displayTime?: string;
  meetingId?: string;
  nerList: NerItem[];
  contentSegments?: TextSegment[];
}

export interface TextSegment {
  type: 'text' | 'keyword';
  content: string;
  nerItem?: NerItem; // 只有keyword类型才有
}

export interface IWsMessage {
  speakerId: string;
  content: string;
}

export interface IEntityPropertyAnalyzeRes {
  data: string;
}

export interface BaikeField {
  baike_tags: BaikeTag[];
}

export interface BaikeTag {
  tagName: string;
  tagId: string;
  category: string;
  startPos: number;
  endPos: number;
  id: number;
}

export interface NerItem {
  tagName: string;
  id: number;
  category: string;
  startPos: number;
  endPos: number;
  tagAnalyze: any;
}

export interface IEntityRecognitionRes {
  sentence: string;
  entities: BaikeField;
}

export interface IMessageListRes {
  current: number;
  total: number;
  records: IMessage[];
}

export interface IOrderBy {
  isAsc: boolean;
  orderBy: string;
}

export interface IEntityRecognitionParams {
  message_id: number;
}

export interface IEntityPropertyAnalyzeParams {
  message_ner_id: number;
}
export interface IMessageListParams {
  chatSessionId: number;
  orderBy?: IOrderBy[];
  page: number;
  pageSize: number;
}

export interface IZhiYuanRes {
  content: string;
  contentType: string;
}

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
  userId?: string;
  userName?: string;
  botId?: string;
  meetingType?: 'AliTingWu' | 'Tencent';
}

export interface IStartSessionRes {
  wssUrl: string;
  meetingId: string;
}

export interface IUserInfoRes {
  name: string;
  value: string[];
}

export interface IDialogueRes {
  id: number;
  keyword: string;
  content: string;
  term: string[];
}
export interface IDialogueResData {
  [id: number]: IDialogueRes[]; // 数字键（年份）映射到对话数组
}

export type UserLevel = 'SUPER_VIP' | 'VIP' | 'ORIGIN';

export interface IUserInfoRes {
  userName: string;
  avatarUrl: string;
  userScoreOb: IUserScoreOb;
  userLevel?: UserLevel;
  expiredDate?: string | number;
}

export interface IUserScoreOb {
  examYear: number;
  province: IProvinceAndSex;
  sex: IProvinceAndSex;
  subjectList: ISubjectList[];
  subjectType: ISubjectTypeAndExamObject;
}

export interface ISubjectList {
  isFirst: number;
  subject: string;
  subjectType?: string;
  subjectName: string;
}
export interface IProvinceAndSex {
  code: string;
  name: string;
}
export interface ISubjectTypeAndExamObject {
  code: string;
  desc: string;
}

/** 空会话「补充成绩」：单科成绩条目（subject 编码与建会话 subjectScoreList 一致）。 */
export interface IScoreDetailSubjectScore {
  subject: string;
  subjectName: string;
  score: number;
}

/** 空会话「补充成绩」请求体：CreateSessionReq 的增量子集（全部必填项见后端校验）。 */
export interface IUpdateScoreDetailParams {
  province: IProvinceAndSex;
  batch: { code: string; name: string; level: string; score?: number };
  subjectType: ISubjectTypeAndExamObject;
  subjectScoreList: IScoreDetailSubjectScore[];
  totalScore: number;
  totalScorePos?: number;
  examYear?: number;
}

/** 空会话「补充成绩」响应：requiresWorkspaceReload 为 true 时前端应重拉 workspace-state。 */
export interface IUpdateScoreDetailRes {
  success: boolean;
  chatSessionId: number;
  planningVersion: number;
  staleFlags?: Record<string, unknown>;
  requiresWorkspaceReload?: boolean;
  volunteerSourceDataSynced?: boolean;
  volunteerSourceDataFetchedAt?: string;
}
