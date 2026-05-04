export interface ICollectflowParams {
  tenantId: string;
}
export interface IUnAcceptableMajorsParams {
  subjectType: string;
  educationLevel: string;
  subjectList: ISubjectList[]; //高考科目;
}

export interface ISubjectList {
  isFirst: number;
  subject: string;
  subjectType?: string;
  subjectName: string;
}

export interface ICollectflowRes {
  majorStepId: string;
  majorStepName: string;
  order: number;
  subSteps: ISubSteps[];
}
export interface ISubSteps {
  formConfig: IFormConfig;
  actions: IActions[];
  contentSegments: ISegments[];
  order: number;
  subStepId: string;
  subStepName: string;
  subStepType: string;
  summarySegments: ISegments[];
}
export interface IFormConfig {
  description: string;
  title: string;
  fields: IFields[];
}

export interface IRegionItem {
  regionId: string;
  regionName: string;
  provinces: IOptions[];
}
export interface IFields {
  helpConfig: IHelpConfig;
  fieldName: string;
  fieldType: string;
  placeholder: string;
  defaultValue: string;
  options: IOptions;
  required: boolean;
  fieldId: string;
  validation: IValidation;
  editable?: boolean;
  majors?: IOptions[];
  regions?: IRegionItem[];
}
export interface IHelpConfig {
  helpText: string;
  showFieldHelp: boolean;
  style: string;
  rich?: any;
  position?: string;
}
export interface IOptions {
  name: string;
  code: string;
  children?: IOptions[];
}
export interface IValidation {
  required: string;
}
export interface IActions {
  actionType: string;
  label: string;
  nextSubStepId: number | string;
}
export interface ISegments {
  segmentId: string;
  materialUrl: string;
  order: number;
  content: IContent;
  type: string;
  expand: boolean;
}

export interface IContent {
  duration: number;
  message: string;
  title: string;
}
export interface IScoreSubject {
  score: number;
  subject: string;
  subjectName: string;
}

export interface IPosRangeParams {
  areaId: string; //省份
  subject: string; //选科类型
  dataLevel: string; //批次等级
  year: string; //考试年份
  score: string; //总成绩
}
