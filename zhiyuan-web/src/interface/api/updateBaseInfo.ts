
export interface IGetSubjectPolicyRes{
    limitTimes:number;
    prepareType:{
        code:string;
        desc:string;
    };
    policy:ISubjectType;
    subjectTypeList:{ // 文科理科选择列表
        code:string;
        desc:string;
    }[];
    firstNum:number; // 首选科目的数量限制
    secondNum:number; // 次选科目的数量限制
    subjectList:{ // 科目选择列表
        isFirst:0|1; // 是否是首选
        subject:string; // 科目value
        subjectName:string; // 科目名称
        subjectType?:string;
    }[];
    year?: string;
}

// 每一个选项的数据结构
export interface ISelectDataItem{
    name:string;
    value:string;
}

export enum ISelectTypeEnum{
    Single, // 单选
    Mutiple, // 多选
}

export interface ICommonSelectProps{
    bigItem?:boolean; // true代表展示大的item
    selectType:ISelectTypeEnum; // 单选 or 多选
    limitNum?:number; // 多选可选的个数
    data: ISelectDataItem[];
    selectedDataIndex:string[];
    onChooseItem:(item:ISelectDataItem)=>void;
}

export type IMemberSubject = {
    id: string;
    createTime: string;
    createdBy: string;
    memberScoreId: string;
    subject: Item;
    isFirst: boolean;
}

export type GetMemberInfoSaas = {
    userId: string;
    programId: string;
}
export interface ISubject{
    isFirst?:0|1;
    subjectType?:string;
}

export interface ISelectConfig{
    name?:string; // 标题
    config:ICommonSelectProps;
}

export type ISubjectItem = ISubject & ISelectDataItem

// 科目类型
export enum ISubjectType{
    ArtsOrSciences ='01', // 文科或者理科
    FirstAndSecond = '02', // 首选1门，次选2门
    ThreeOutOfSix= '03', // 六选三
}
export type BatchReqParams = {
    areaId: string;
    prepareType: string;
    subject: string;
}

export type BatchList = {
    id: string;
    batch: string;
    batchTitle: string;
    score: string;
    level: {key: MajorLevel};
}

export type BatchResParams = {
    batchList: BatchList[];
    area: {key: string};
    type: ISexAndProvinceAndBatchObject;
}

export interface IProvince {
    code: string;
    label: string;
    isUse?: boolean;
}

export interface ISubjectList {
    isFirst: number;
    subject: string;
    subjectType?: string;
    subjectName: string;
}

export interface ISexAndProvinceAndBatchObject {
    code:string;
    name:string;
}

export interface ISubjectTypeAndExamObject {
    code: string;
    desc: string;
}
