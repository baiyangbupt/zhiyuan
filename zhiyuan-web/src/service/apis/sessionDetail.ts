import {
  IRecommendSchoolRes,
  IMajorRes,
  IBaikeRes,
  IBaikeDetailRes,
  IVersionRes,
  ISessionStatusRes,
  IUserProfileRes,
  IMessageListRes,
  IMessageListParams,
  IZhiYuanRes,
  ISaveOrUpdateParams,
  ISaveOrUpdateRes,
  ISessionParams,
  IEndSessionParams,
  IUserInfoParams,
  IStartSessionRes,
  IEntityPropertyAnalyzeRes,
  IEntityPropertyAnalyzeParams,
  IEntityRecognitionRes,
  IEntityRecognitionParams,
  ProfileKVDto,
  UserIntentEmotionSaveReq,
} from '@/interface/api/sessionDetail';
import {
  PlanningCandidateFilterOptionsRes,
  PlanningCandidatePoolQueryReq,
  PlanningCandidatePoolQueryRes,
  PlanningCandidateViewState,
  PlanningFixProposalApplyReq,
  PlanningFixProposalApplyRes,
  PlanningFixProposalState,
  PlanningReviewWorkflowRunRes,
  PlanningDataFreshnessCheckReq,
  PlanningDataFreshnessCheckRes,
  OrderedPlanActionRes,
  PlanningStateRes,
  PlanningWorkspaceStateRes,
} from '@/interface/api/volunteer';
import request from '@/service/index';
import {
  BatchReqParams,
  BatchResParams,
  IGetSubjectPolicyRes,
  IProvince,
  ISubject,
} from '@/interface/api/updateBaseInfo';
import {
  IBasicProfileParams,
  IBasicProfileRes,
  ICreateSessionParams,
  ISessionListParams,
  ISessionListRes,
  ISessionListResItem,
  ISubjectRes,
} from '@/interface/api/assistant';
import {
  IUpdateScoreDetailParams,
  IUpdateScoreDetailRes,
} from '@/interface/api/sessionDetail';

// 获取推荐院校
export const getRecommendSchoolApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, IRecommendSchoolRes>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/recommend/school?chatSessionId=${data.chatSessionId} `,
    method: 'get',
  });

// 获取推荐专业
export const getRecommendMajorApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, IMajorRes[]>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/recommend/major?chatSessionId=${data.chatSessionId} `,
    method: 'get',
  });

// 获取推荐百科
export const getRecommendBaikeApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, IBaikeRes[]>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/recommend/baike?chatSessionId=${data.chatSessionId} `,
    method: 'get',
  });

// 获取百科详情
export const getBaikeDetailApi = (data: IUserInfoParams, name: string) =>
  request<IUserInfoParams, IBaikeDetailRes[]>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/recommend/baike-detail?baikeName=${name}`,
    method: 'get',
  });

// 获取推荐专业/院校/百科/动态画像最新版本
export const getLastVersionApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, IVersionRes>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/recommend/data-last-version?chatSessionId=${data.chatSessionId} `,
    method: 'get',
  });

// 会话状态监测
export const checkSessionStatusApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, ISessionStatusRes>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/check-session-status?chatSessionId=${
      data.chatSessionId
    }&meetingId=${data.meetingId}&meetingType=${data.meetingType || 'AliTingWu'} `,
    method: 'get',
  });

export const getAnalyzeApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, any>({
    url: `/gaotu-assistant-agent/web/chat/${data.tenantId}/analyze?chatSessionId=${data.chatSessionId}`,
    method: 'post',
  });

// 生成志愿
export const produceZhiYuanApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, IZhiYuanRes>({
    url: `/gaotu-assistant-agent/web/chat/${data.tenantId}/bot/${data.botId}/produce-zhiyuan?chatSessionId=${data.chatSessionId}`,
    method: 'post',
  });

// 获取用户画像-静态
export const getUserBasicProfileApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, IUserProfileRes[]>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/user-basic-profile?chatSessionId=${data.chatSessionId}`,
    method: 'post',
  });

// 获取用户画像-动态
export const getUserDynasticProfileApi = (data: IUserInfoParams) =>
  request<IUserInfoParams, IUserProfileRes[]>({
    url: `/gaotu-assistant-agent/web/chat/${data.tenantId}/user-dynastic-profile?chatSessionId=${data.chatSessionId} `,
    method: 'post',
  });

// 获取实体属性 推理总结 的接口
export const getEntityPropertyAnalyzeApi = (tenantId: string, data: IEntityPropertyAnalyzeParams) =>
  request<IEntityPropertyAnalyzeParams, IEntityPropertyAnalyzeRes>({
    url: `/gaotu-assistant-agent/web/chat/${tenantId}/entity-property-analyze?message_ner_id=${data.message_ner_id}`,
    method: 'post',
    data,
  });
// 实体识别接口
export const getEntityRecognitionApi = (tenantId: string, data: IEntityRecognitionParams) =>
  request<IEntityRecognitionParams, IEntityRecognitionRes>({
    url: `/gaotu-assistant-agent/web/chat/${tenantId}/entity-recognition?message_id=${data.message_id}`,
    method: 'post',
    data,
  });

// 分页获取消息列表
export const getMessageListApi = (tenantId: string, data: IMessageListParams) =>
  request<IMessageListParams, IMessageListRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/message/page`,
    method: 'post',
    data,
    special: [800],
  });

// 保存消息
export const saveOrUpdateMessageApi = (tenantId: string, data: ISaveOrUpdateParams) =>
  request<ISaveOrUpdateParams, ISaveOrUpdateRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/message/save`,
    method: 'post',
    data,
  });

// 开始沟通
export const startChatSessionApi = (data: ISessionParams) =>
  request<ISessionParams, IStartSessionRes>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/session/start?chatSessionId=${data.chatSessionId}`,
    method: 'post',
    data,
  });

// 结束沟通
export const endChatSessionApi = (data: IEndSessionParams) =>
  request<IEndSessionParams, boolean>({
    url: `/gaotu-assistant-bot/chat/${data.tenantId}/session/stop?chatSessionId=${data.chatSessionId}&meetingId=${data.meetingId}`,
    method: 'post',
    data,
  });

export const getYearList = () =>
  request<null, { examYearList: string[] }>({
    url: '/hl-wish/ci/memberWhitelist/noToken/commonInfo',
    method: 'get',
  });

export const getSubjectPolicy = (areaId: string) =>
  request<{ areaId: string }, IGetSubjectPolicyRes>({
    url: '/hl-wish/ci/selectSubjectPolicy/noToken/subjectPolicy',
    method: 'get',
    data: {
      areaId,
    },
  });

export const getProvinceLists = () =>
  request<null, IProvince[]>({
    url: '/hl-wish/ci/volunteerPolicy/noToken/provinceList',
    method: 'get',
  });

export const getBatchList = (data: BatchReqParams) =>
  request<BatchReqParams, BatchResParams>({
    url: '/hl-wish/ci/h5/batchData/anno/batchListByPolicy',
    method: 'get',
    data,
  });

// 创建会话
export const createSession = (tenantId: string, data: ICreateSessionParams) =>
  request<ICreateSessionParams, ISessionListResItem>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/session/create`,
    method: 'post',
    data,
  });

//调用推荐专业接口
export const callMajorRecommendation = (tenantId: string, chatSessionId: string) =>
  request<any, any>({
    url: `/gaotu-assistant-agent/web/chat/${tenantId}/major-recommendation?chatSessionId=${chatSessionId}`,
    method: 'post',
  });

// 分页获取会话列表
export const getSessionList = (tenantId: string, data: ISessionListParams) =>
  request<ISessionListParams, ISessionListRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/session/page`,
    method: 'post',
    data,
  });

// 保存志愿信息
export const saveVolunteerInfo = (data: ISubject) =>
  request<ISubject, ISubjectRes>({
    url: '/hl-wish/ci/h5/ai/volunteer/noToken/saveMemberFormByMobile',
    method: 'post',
    data,
  });

// 绑定腾讯会议
export const bindTencentMeeting = (
  tenantId: string,
  chatSessionId: string,
  tencentMeetingCode: string
) =>
  request<{}, { code: number; msg: string; data: number }>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/session/bind-tencent-meeting?chatSessionId=${chatSessionId}&tencentMeetingCode=${tencentMeetingCode}`,
    method: 'post',
  });

// 获取用户信息-基本信息
export const getSessionUserInfoApi = (tenantId: string, chatSessionId: string) =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/user-basic-profile?chatSessionId=${chatSessionId} `,
    method: 'post',
  });
// 获取用户信息-意向信息
export const getSessionUserDynasticInfoApi = (tenantId: string, chatSessionId: string) =>
  request<{}, ProfileKVDto[]>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/user-dynastic-profile?chatSessionId=${chatSessionId} `,
    method: 'post',
  });

// 保存用户意向情绪
export const saveUserIntentEmotionApi = (tenantId: string, data: UserIntentEmotionSaveReq) =>
  request<UserIntentEmotionSaveReq, boolean>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/user-dynastic-profile/save`,
    method: 'post',
    data,
  });
// 获取志愿列表
export const getVolunteerRecommendListApi = (tenantId: string, chatSessionId: string) =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/volunteer/recommend-list?chatSessionId=${chatSessionId} `,
    method: 'get',
  });
// 导出志愿
export const getVolunteerExportApi = (tenantId: string, chatSessionId: string) =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/volunteer/export?chatSessionId=${chatSessionId} `,
    method: 'post',
    responseType: 'blob',
  });
// 提交志愿列表
export const getVolunteerSubmitApi = (tenantId: string, chatSessionId: string) =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/volunteer/submit?chatSessionId=${chatSessionId} `,
    method: 'post',
  });
// 获取会话详情
export const getSessionDetailApi = (tenantId: string, chatSessionId: string) =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/session/detail?chatSessionId=${chatSessionId}`,
    method: 'get',
  });

export const getPlanningWorkspaceStateApi = (tenantId: string, chatSessionId: string) =>
  request<{}, PlanningWorkspaceStateRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/workspace-state?chatSessionId=${chatSessionId}`,
    method: 'get',
  });

export const checkPlanningDataFreshnessApi = (
  tenantId: string,
  chatSessionId: string,
  data: PlanningDataFreshnessCheckReq = {}
) =>
  request<PlanningDataFreshnessCheckReq, PlanningDataFreshnessCheckRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/data-freshness/check?chatSessionId=${chatSessionId}`,
    method: 'post',
    data,
    special: [84009],
  });

export const runPlanningReviewWorkflowApi = (tenantId: string, chatSessionId: string) =>
  request<{}, PlanningReviewWorkflowRunRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/review-workflow/run?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {},
  });

export const generatePlanningFixProposalsApi = (tenantId: string, chatSessionId: string) =>
  request<{}, PlanningFixProposalState>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/fix-proposals/generate?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {},
  });

export const applyPlanningFixProposalApi = (
  tenantId: string,
  chatSessionId: string,
  data: PlanningFixProposalApplyReq
) =>
  request<PlanningFixProposalApplyReq, PlanningFixProposalApplyRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/fix-proposals/apply?chatSessionId=${chatSessionId}`,
    method: 'post',
    data,
  });

export const generatePlanningCandidatePoolApi = (
  tenantId: string,
  chatSessionId: string,
  forceRegenerate: boolean = true,
  refreshSourceData: boolean = false
) =>
  request<{ forceRegenerate: boolean; refreshSourceData: boolean }, PlanningStateRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/candidate-pool/generate?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      forceRegenerate,
      refreshSourceData,
    },
  });

export const generatePlanningInitialPlanApi = (
  tenantId: string,
  chatSessionId: string,
  forceRegenerate: boolean = false,
  regroupByTier: boolean = true,
  overwriteExistingDraft: boolean = false,
  // 可选：把指定业务码从**全局 toast** 里豁免（2026-10-07）——工作台的"自举初始方案"
  // 是后台尽力而为的动作 ✓：失败时方案区本来就显示"还没有方案"占位 ✓，
  // 再弹一个全局"系统错误"只会吓用户（实测：自举与懒导入竞态时偶发 -1）✗。
  special?: number[]
) =>
  request<
    { forceRegenerate: boolean; regroupByTier: boolean; overwriteExistingDraft: boolean },
    PlanningStateRes
  >({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/initial-plan/generate?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      forceRegenerate,
      regroupByTier,
      overwriteExistingDraft,
    },
    ...(special ? { special } : {}),
  } as any);

export const exportPlanningOrderedPlanApi = (tenantId: string, chatSessionId: string) =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/ordered-plan/export?chatSessionId=${chatSessionId}`,
    method: 'post',
    responseType: 'blob',
  });

export const queryPlanningCandidatePoolApi = (
  tenantId: string,
  chatSessionId: string,
  data: PlanningCandidatePoolQueryReq
) =>
  request<PlanningCandidatePoolQueryReq, PlanningCandidatePoolQueryRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/candidate-pool/query?chatSessionId=${chatSessionId}`,
    method: 'post',
    data,
  });

export const getPlanningCandidateFilterOptionsApi = (tenantId: string, chatSessionId: string) =>
  request<{}, PlanningCandidateFilterOptionsRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/candidate-pool/filter-options?chatSessionId=${chatSessionId}`,
    method: 'get',
  });

export const updatePlanningCandidateViewStateApi = (
  tenantId: string,
  chatSessionId: string,
  data: PlanningCandidateViewState
) =>
  request<PlanningCandidateViewState, PlanningStateRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/candidate-view-state?chatSessionId=${chatSessionId}`,
    method: 'patch',
    data,
  });

export const selectPlanningWorkingPlanItemsApi = (
  tenantId: string,
  chatSessionId: string,
  volunteerIds: string[],
  source: string = 'manual_workspace'
) =>
  request<{ volunteerIds: string[]; source: string }, PlanningStateRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/working-plan/select?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      volunteerIds,
      source,
    },
  });

export const removePlanningWorkingPlanItemsApi = (
  tenantId: string,
  chatSessionId: string,
  volunteerIds: string[]
) =>
  request<{ volunteerIds: string[] }, PlanningStateRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/working-plan/remove?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      volunteerIds,
    },
  });

export const movePlanningOrderedItemApi = (
  tenantId: string,
  chatSessionId: string,
  volunteerId: string,
  targetPosition: number
) =>
  request<{ volunteerId: string; targetPosition: number }, OrderedPlanActionRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/ordered-plan/move?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      volunteerId,
      targetPosition,
    },
  });

export const movePlanningOrderedUnitApi = (
  tenantId: string,
  chatSessionId: string,
  unitId: string,
  targetPosition: number
) =>
  request<{ unitId: string; targetPosition: number }, OrderedPlanActionRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/ordered-plan/unit/move?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      unitId,
      targetPosition,
    },
  });

export const removePlanningOrderedUnitApi = (
  tenantId: string,
  chatSessionId: string,
  unitIds: string[]
) =>
  request<{ unitIds: string[] }, OrderedPlanActionRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/ordered-plan/unit/remove?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      unitIds,
    },
  });

export const sortPlanningOrderedPlanApi = (
  tenantId: string,
  chatSessionId: string,
  sortField: 'admissionRatio' | 'schoolRank' | 'finalScore'
) =>
  request<{ sortField: string }, OrderedPlanActionRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/ordered-plan/sort?chatSessionId=${chatSessionId}`,
    method: 'post',
    data: {
      sortField,
    },
  });

// 消息反馈接口
export const getFeedbackApi = (tenantId: string, data: { feedback: number; messageId: number }) =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/message/feedback`,
    method: 'post',
    data,
  });
// 获取限制设置
export const getLimitSettingsApi = () =>
  request<{}, any>({
    url: `/gaotu-assistant-bot/chat/user/limit-settings`,
    method: 'get',
  });

// 更新会话学费区间（需后端提供对应接口）
export const updateSessionTuitionRangeApi = (
  tenantId: string,
  chatSessionId: string,
  data: { min: number; max: number }
) =>
  request<typeof data, any>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/session/update-tuition-range?chatSessionId=${chatSessionId}`,
    method: 'post',
    data,
  });

/**
 * 空会话「补充成绩」（产品裁决=同会话补录）。
 *
 * - 成功：data.requiresWorkspaceReload=true → 调用方应重拉 workspace-state；
 * - 110 校验类：HTTP 200 + code=110，由调用方在表单内提示；
 * - 84009 / -1：上游策略失效等 → toast 透出 msg 并提示刷新后重试；
 * - 非本人：真实 HTTP 403，走既有全局处理。
 *
 * `special` 抑制全局错误 toast，由调用方按上述分支自行呈现（避免重复提示）。
 */
export const updateSessionScoreDetailApi = (
  tenantId: string,
  chatSessionId: string,
  data: IUpdateScoreDetailParams
) =>
  request<IUpdateScoreDetailParams, IUpdateScoreDetailRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/session/update-score-detail?chatSessionId=${chatSessionId}`,
    method: 'post',
    data,
    special: [110, 84009, -1],
  });
