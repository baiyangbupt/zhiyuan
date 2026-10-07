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
    // **「数据缺失」不是故障** ✓✓（2026-10-07 用户实测：刷新/改分时弹"系统错误"）：
    // 84001 = 未查询到一分一段数据（该省/该口径无表），-1 = 上游系统错误——
    // 两者调用方都按"算不出位次"处理 ✓（`ScoreSupplement` 的 `.then(code===0&&data)`
    // 与 `.catch` 兜底 ✓、`PersonalInfoCollect` 同理 ✓），
    // 只有全局 toast 不该弹 ✓——位次是**可选项**，缺数据留给用户手填 ✓。
    special: [84001, -1],
  } as any);
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
