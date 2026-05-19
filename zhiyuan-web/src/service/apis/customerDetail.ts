import {
  ICollectflowParams,
  IPosRangeParams,
  IUnAcceptableMajorsParams,
} from '@/interface/api/customerDetail';
import request from '@/service/index';
export const getCollectFlowApi = (data: ICollectflowParams) =>
  request<ICollectflowParams, any>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/collect-flow`,
    method: 'get',
  });
// 根据用户成绩+填报批次获取位次
export const getPositionRangeApi = (data: IPosRangeParams) =>
  request<IPosRangeParams, any>({
    url: `/gaotu-assistant-bot/base-data/score/position-range`,
    method: 'post',
    data,
  });
// 获取民族列表
export const getEthnicityListApi = () =>
  request<ICollectflowParams, any>({
    url: `/gaotu-assistant-bot/base-data/ethnicity-list`,
    method: 'get',
  });
// 获取意向专业列表
export const getMajorEducationApi = (educationLevel: string = 'BACHELOR') =>
  request<ICollectflowParams, any>({
    url: `/gaotu-assistant-bot/base-data/major-level2-data?educationLevel=${educationLevel}`,
    method: 'get',
  });
// 获取不能接受的专业列表
export const getUnacceptableMajorsListApi = (data: IUnAcceptableMajorsParams) =>
  request<IUnAcceptableMajorsParams, any>({
    url: `/gaotu-assistant-bot/base-data/unacceptable-majors`,
    method: 'post',
    data,
  });
// 获取按大区分组的省份列表
export const getRegionProvinceApi = () =>
  request<ICollectflowParams, any>({
    url: `/gaotu-assistant-bot/base-data/region-province`,
    method: 'get',
  });
// 根据选科成绩信息获取用户推荐专业
export const getMajorRecommendApi = (tenantId: string | number, data: any) =>
  request<ICollectflowParams, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/major-recommend`,
    method: 'post',
    data,
  });
