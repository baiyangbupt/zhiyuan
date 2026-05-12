import { IUserInfoParams } from '@/interface/api/assistant';
import { IDialogueResData } from '@/interface/api/sessionDetail';
export interface DialogueProps {
  routerParams: IUserInfoParams;
  version: number;
  setScrollEleIndex: (index: number) => void;
  entityCardList: IDialogueResData;
  fetchFlag: number;
  sessionStatus: string;
  fetchSessionDetail: () => void;
  workspaceIntent?: PlanningWorkspaceIntent | null;
  onWorkspaceIntentConsumed?: () => void;
}

export interface PlanningWorkspaceIntent {
  nonce: number;
  targetTab?: 'volunteer';
  targetView?: 'candidate' | 'ordered';
  volunteerIds?: string[];
  refresh?: boolean;
  candidateFilters?: {
    tiers?: string[];
    provinceNames?: string[];
    negativeProvinceNames?: string[];
    cityNames?: string[];
    negativeCityNames?: string[];
    schoolKeywords?: string[];
    negativeSchoolKeywords?: string[];
    majorKeywords?: string[];
    negativeMajorKeywords?: string[];
    schoolTags?: string[];
    negativeSchoolTags?: string[];
    majorTags?: string[];
    negativeMajorTags?: string[];
  };
}
// 定义筛选类型
export type FilterType = 'sprints' | 'safes' | 'protects';

export interface CollapseHeaderProps {
  index: number;
  tabActive: string;
  schoolName: string;
  schoolRank: string | null;
  basicTagList: string[] | [];
  rankTagList: string[] | [];
  enrollRatio: string;
  baoyanRatio: string;
  majors: Array<{
    duration: string;
    enroll_ratio: string;
    history_score_list: Array<{
      // 修改为数组类型
      year: number;
      score: number;
      pos: number | null;
      planNum: number | null;
      enrollNum: number | null;
    }>;
    level: string;
    majorUnitCode: string;
    major_name: string;
    must_subject: string[];
    planMoney: string;
    planNum: number;
    planTagList: string[];
    rankTagList: string[];
    popTagList: string[];
  }>;
  advantages: string[];
  masterCount: number;
  doctoralCount: number;
  recommendationRate: string;
  admissionRate: string;
  historyScoreList: Array<{
    // 修改为数组类型
    year: number;
    score: number;
    pos: number | null;
    planNum: number | null;
    enrollNum: number | null;
  }>;
  popTagList?: string[];
}
export interface CollapseContentProps {
  isMobile?: boolean;
  tabActive: string;
  majors: Array<{
    major_name: string;
    majorUnitCode: string;
    enroll_ratio: string;
    level: string;
    must_subject: string[];
    rankTagList: string[];
    planTagList: string[];
    history_score_list: HistoryScore[];
  }>;
  volunteerModel?: string;
  volunteerCount?: {
    majorCount?: number;
  };
} // 定义数据类型
export interface DataType {
  key: string;
  major_name: string;
  planTagList: string[];
  enroll_ratio: string;
  rankTagList: string[];
  history_score_list: HistoryScore[];
  type: string;
}

export interface HistoryScore {
  year: number;
  score: number;
  pos: number | null;
  planNum: number | null;
  enrollNum: number | null;
}

export interface PlanningPendingAction {
  type?: string;
  level?: string;
  summary?: string;
  detail?: string;
  sourceCheckCode?: string;
  volunteerIds?: string[];
}

export interface PlanningCompensationAction {
  type?: string;
  level?: string;
  summary?: string;
  detail?: string;
  sourceCheckCode?: string;
  volunteerIds?: string[];
}

export interface PlanningCompensationPreview {
  status?: string;
  sourceVersion?: number;
  totalActions?: number;
  actions?: PlanningCompensationAction[];
}

export interface PlanningPlanGenerationState {
  mode?: string;
  sourceVersion?: number;
  generatedAt?: string;
  usedOverlayVersion?: number;
  allowAutoComplete?: boolean;
  respectedPinnedCount?: number;
  preservedManualOrderCount?: number;
}

export interface PlanningReviewCheck {
  code?: string;
  level?: string;
  passed?: boolean;
  summary?: string;
  detail?: string;
  suggestedAction?: string;
  affectedVolunteerIds?: string[];
  suggestedCompensations?: PlanningCompensationAction[];
}

export interface PlanningDraftItem {
  volunteerId?: string;
  tier?: string;
  schoolName?: string;
  majorName?: string;
  locked?: boolean;
  source?: string;
}

export interface PlanningCandidateItem {
  volunteerId?: string;
  tier?: string;
  subTier?: string;
  planSchoolDataId?: string;
  schoolId?: string;
  schoolName?: string;
  provinceName?: string;
  cityName?: string;
  schoolBatch?: string;
  schoolLevel?: string;
  schoolNature?: string;
  schoolCategory?: string;
  schoolRank?: number;
  schoolEnrollRatio?: number;
  baoyanRatio?: number;
  upgradeRatio?: number;
  masterCount?: number;
  doctorCount?: number;
  preferred?: boolean;
  majorId?: string;
  majorName?: string;
  majorCode?: string;
  majorLevel?: string;
  majorDiscipline?: string;
  majorCategory?: string;
  majorTier?: string;
  planNum?: number;
  duration?: string;
  tuitionPerYear?: number;
  baseScore?: number;
  intentScore?: number;
  finalScore?: number;
  admissionRatio?: number;
  rankInTier?: number;
  hotIndex?: number;
  salaryAvg?: number;
  mustSubjects?: string[];
  reasonCodes?: string[];
  riskFlags?: string[];
  schoolRankTags?: string[];
  schoolBasicTags?: string[];
  schoolPopupTags?: string[];
  majorRankTags?: string[];
  majorPlanTags?: string[];
  schoolHistoryScores?: HistoryScore[];
  majorHistoryScores?: HistoryScore[];
}

export interface PlanningCandidatePoolQueryReq {
  filters?: {
    tiers?: string[];
    provinceNames?: string[];
    negativeProvinceNames?: string[];
    cityNames?: string[];
    negativeCityNames?: string[];
    schoolKeywords?: string[];
    negativeSchoolKeywords?: string[];
    majorKeywords?: string[];
    negativeMajorKeywords?: string[];
    schoolTags?: string[];
    negativeSchoolTags?: string[];
    majorTags?: string[];
    negativeMajorTags?: string[];
  };
  sort?: {
    field?: string;
    order?: 'asc' | 'desc';
  };
  page?: number;
  pageSize?: number;
}

export interface PlanningCandidatePoolQueryRes {
  items?: PlanningCandidateItem[];
  page?: number;
  pageSize?: number;
  total?: number;
  totalUnitCount?: number;
  loadedEntryCount?: number;
  loadedUnitCount?: number;
}

export interface PlanningCandidateFilterOptionsRes {
  provinceNames?: string[];
  cityNames?: string[];
  schoolTags?: string[];
  majorTags?: string[];
  majorKeywords?: string[];
  groups?: Array<{
    groupCode?: string;
    groupName?: string;
    filterField?: string;
    values?: string[];
  }>;
}

export interface PlanningCandidateViewState {
  filters?: {
    tiers?: string[];
    provinceNames?: string[];
    negativeProvinceNames?: string[];
    cityNames?: string[];
    negativeCityNames?: string[];
    schoolKeywords?: string[];
    negativeSchoolKeywords?: string[];
    majorKeywords?: string[];
    negativeMajorKeywords?: string[];
    schoolTags?: string[];
    negativeSchoolTags?: string[];
    majorTags?: string[];
    negativeMajorTags?: string[];
  };
  sort?: {
    field?: string;
    order?: 'asc' | 'desc';
  };
  expertPreferredOnly?: boolean;
}

export interface PlanningOrderedItem {
  position?: number;
  volunteerId?: string;
  tier?: string;
  schoolName?: string;
  majorName?: string;
  locked?: boolean;
  pinned?: boolean;
  pinnedPosition?: number;
  orderedBy?: string;
  orderReason?: string;
  source?: string;
}

export interface PlanningUnitMajorItem {
  volunteerId?: string;
  majorName?: string;
  tier?: string;
  selected?: boolean;
  majorId?: string;
  majorCode?: string;
  majorCategoryId?: string;
  majorSubCategoryId?: string;
  admissionRatio?: number;
  finalScore?: number;
  intentScore?: number;
  preferred?: boolean;
  safetyMajor?: boolean;
  tuitionPerYear?: number;
  rankInTier?: number;
}

export interface PlanningDraftUnit {
  unitId?: string;
  tier?: string;
  schoolName?: string;
  source?: string;
  locked?: boolean;
  majorItems?: PlanningUnitMajorItem[];
}

export interface PlanningOrderedUnit {
  unitId?: string;
  tier?: string;
  schoolName?: string;
  source?: string;
  locked?: boolean;
  pinned?: boolean;
  pinnedPosition?: number;
  orderedBy?: string;
  orderReason?: string;
  position?: number;
  provinceName?: string;
  cityName?: string;
  admissionRatio?: number;
  finalScore?: number;
  schoolEnrollRatio?: number;
  majorItems?: PlanningUnitMajorItem[];
}

export interface PlanningStateRes {
  sessionId?: number;
  version?: number;
  phase?: string;
  profileState?: {
    explicitProfile?: {
      positiveMajors?: string[];
      negativeMajors?: string[];
      positiveSchools?: string[];
      negativeSchools?: string[];
      positiveRegions?: string[];
      negativeRegions?: string[];
      strengthSubjects?: string[];
    };
    latentProfile?: Record<string, unknown>;
    physicalConstraints?: Record<string, unknown>;
  };
  constraintState?: {
    hardConstraints?: Record<string, unknown>;
    softPreferences?: Record<string, unknown>;
    derivedPreferences?: Record<string, unknown>;
  };
  operationLogs?: Array<Record<string, unknown>>;
  staleFlags?: {
    candidatePool?: boolean;
    orderedPlan?: boolean;
    review?: boolean;
  };
  planGenerationState?: PlanningPlanGenerationState;
  candidatePoolState?: {
    generatedAt?: string;
    sourceVersion?: number;
    statusCode?: string;
    statusMessage?: string;
    riskHints?: string[];
    requiredCount?: number;
    requiredTierCounts?: Record<string, number>;
    requiredUnitCount?: number;
    requiredMajorCount?: number;
    userScore?: number;
    batchScore?: number;
    sourceProvinceName?: string;
    volunteerModel?: string;
    items?: PlanningCandidateItem[];
    summary?: {
      entryTotal?: number;
      unitTotal?: number;
      total?: number;
      entryTierCounts?: Record<string, number>;
      unitTierCounts?: Record<string, number>;
      tierCounts?: Record<string, number>;
    };
  };
  candidateViewState?: PlanningCandidateViewState;
  draftPlanState?: {
    items?: PlanningDraftItem[];
    units?: PlanningDraftUnit[];
    bannedVolunteerIds?: string[];
    summary?: {
      unitTotal?: number;
      targetUnitCount?: number;
      total?: number;
      targetCount?: number;
      unitTierCounts?: Record<string, number>;
      tierCounts?: Record<string, number>;
    };
  };
  orderedPlanState?: {
    items?: PlanningOrderedItem[];
    units?: PlanningOrderedUnit[];
    generationMode?: string;
    autoCompleted?: boolean;
    gradientAdjusted?: boolean;
    preservedPinnedCount?: number;
    preservedManualOrderCount?: number;
    summary?: {
      unitTotal?: number;
      targetUnitCount?: number;
      total?: number;
      targetCount?: number;
      unitTierCounts?: Record<string, number>;
      tierCounts?: Record<string, number>;
      sequenceOk?: boolean;
      gradientOk?: boolean;
      safetyOk?: boolean;
    };
  };
  reviewState?: {
    status?: string;
    reviewedAt?: string;
    sourceVersion?: number;
    summary?: {
      totalRuleCount?: number;
      passedRuleCount?: number;
      warnRuleCount?: number;
      riskRuleCount?: number;
      total?: number;
      passedCount?: number;
      warnCount?: number;
      riskCount?: number;
    };
    checks?: PlanningReviewCheck[];
    compensationPreview?: PlanningCompensationPreview;
  };
  pendingActions?: PlanningPendingAction[];
  workflowStatus?: {
    candidateStatus?: string;
    candidateMessage?: string;
    planStatus?: string;
    planMessage?: string;
    legacySubmitted?: boolean;
    legacyMessage?: string;
    reviewStatus?: string;
    reviewMessage?: string;
    exportStatus?: string;
    exportMessage?: string;
    lastExportedAt?: string;
  };
  behaviorEvents?: Array<Record<string, unknown>>;
}

export type OrderedPlanActionRes = Pick<
  PlanningStateRes,
  'sessionId' | 'version' | 'phase' | 'staleFlags' | 'orderedPlanState'
>;

export type PlanningWorkspaceStateRes = Pick<
  PlanningStateRes,
  | 'sessionId'
  | 'version'
  | 'phase'
  | 'staleFlags'
  | 'planGenerationState'
  | 'candidatePoolState'
  | 'candidateViewState'
  | 'draftPlanState'
  | 'orderedPlanState'
  | 'reviewState'
  | 'pendingActions'
  | 'operationLogs'
  | 'workflowStatus'
  | 'behaviorEvents'
>;
