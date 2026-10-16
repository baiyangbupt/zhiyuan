import { IUserInfoParams } from '@/interface/api/assistant';
import { IDialogueResData } from '@/interface/api/sessionDetail';
import { ConversationEvidence } from '@/interface/api/conversation';
import request from '@/service/index';
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

export type PlanningWorkspaceTargetView = 'candidate' | 'ordered';
export type PlanningWorkspaceRefreshTarget = PlanningWorkspaceTargetView | 'review' | 'draft' | 'workingPlan';

export interface PlanningWorkspaceIntent {
  nonce: number;
  targetTab?: 'volunteer';
  targetView?: PlanningWorkspaceTargetView;
  refreshTargets?: PlanningWorkspaceRefreshTarget[];
  volunteerIds?: string[];
  refresh?: boolean;
  preserveView?: boolean;
  silent?: boolean;
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

/** Read-only Evidence lookup used by the Codex conversation drawer. */
export const getConversationEvidenceApi = (
  tenantId: string,
  chatSessionId: string,
  evidenceId: string,
) =>
  request<{ chatSessionId: string; evidenceId: string }, ConversationEvidence>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/planning/session/evidence?chatSessionId=${chatSessionId}&evidenceId=${encodeURIComponent(evidenceId)}`,
    method: 'get',
  });
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

export interface PlanningCompensationAction {
  type?: string;
  level?: string;
  summary?: string;
  detail?: string;
  sourceCheckCode?: string;
  unitIds?: string[];
  volunteerIds?: string[];
}

export interface PlanningCompensationPreview {
  status?: string;
  sourceVersion?: number;
  totalActions?: number;
  actions?: PlanningCompensationAction[];
}

export interface PlanningReplacementPair {
  fromUnitId?: string;
  fromVolunteerId?: string;
  toUnitId?: string;
  toVolunteerId?: string;
  reasonCodes?: string[];
}

export interface PlanningFixProposalAction {
  actionType?: string;
  level?: string;
  sourceCheckCode?: string;
  summary?: string;
  detail?: string;
  unitIds?: string[];
  volunteerIds?: string[];
  removeUnitIds?: string[];
  removeVolunteerIds?: string[];
  candidateUnitIds?: string[];
  candidateVolunteerIds?: string[];
  replacementPairs?: PlanningReplacementPair[];
  totalUnitCount?: number;
  totalVolunteerCount?: number;
  totalReplacementPairCount?: number;
}

export interface PlanningCandidateShortage {
  strategy?: string;
  sourceCheckCode?: string;
  scope?: string;
  reasonCode?: string;
  targetTier?: string;
  requiredCount?: number;
  currentCount?: number;
  shortageCount?: number;
  availableCount?: number;
  message?: string;
}

export interface PlanningFixProposalDryRunResult {
  status?: string;
  message?: string;
  beforeUnitTotal?: number;
  afterUnitTotal?: number;
  beforeVolunteerTotal?: number;
  afterVolunteerTotal?: number;
  beforeUnitTierCounts?: Record<string, number>;
  afterUnitTierCounts?: Record<string, number>;
  beforeVolunteerTierCounts?: Record<string, number>;
  afterVolunteerTierCounts?: Record<string, number>;
  beforeUnitIds?: string[];
  afterUnitIds?: string[];
  beforeVolunteerIds?: string[];
  afterVolunteerIds?: string[];
  beforeAverageFinalScore?: number;
  afterAverageFinalScore?: number;
  beforeAverageHotIndex?: number;
  afterAverageHotIndex?: number;
  beforeAverageSchoolRank?: number;
  afterAverageSchoolRank?: number;
  affectedUnitCount?: number;
  affectedVolunteerCount?: number;
  addUnitCount?: number;
  addVolunteerCount?: number;
  removeUnitCount?: number;
  removeVolunteerCount?: number;
  warnings?: string[];
}

export interface PlanningFixProposal {
  proposalId?: string;
  sourceVersion?: number;
  sourceReviewVersion?: number;
  sourceVersionGuard?: number;
  status?: string;
  strategy?: string;
  title?: string;
  summary?: string;
  impact?: string;
  blockingReason?: string;
  blockingReasonCodes?: string[];
  candidateShortages?: PlanningCandidateShortage[];
  requiresConfirmation?: boolean;
  sourceCheckCodes?: string[];
  affectedUnitIds?: string[];
  affectedVolunteerIds?: string[];
  actions?: PlanningFixProposalAction[];
  dryRunResult?: PlanningFixProposalDryRunResult;
}

export interface PlanningFixProposalState {
  status?: string;
  sourceVersion?: number;
  sourceReviewVersion?: number;
  sourceVersionGuard?: number;
  total?: number;
  proposals?: PlanningFixProposal[];
}

export interface PlanningFixProposalApplyReq {
  proposalId: string;
  sourceVersionGuard: number;
  regenerateOrderedPlan?: boolean;
  rerunReview?: boolean;
}

export interface PlanningRepairReport {
  status?: string;
  proposalId?: string;
  strategy?: string;
  proposalTitle?: string;
  proposalSummary?: string;
  proposalImpact?: string;
  sourceVersion?: number;
  resultVersion?: number;
  sourceReviewVersion?: number;
  resultReviewVersion?: number;
  dryRunStatus?: string;
  dryRunMessage?: string;
  sourceCheckCodes?: string[];
  appliedActionCount?: number;
  affectedUnitCount?: number;
  affectedVolunteerCount?: number;
  addedUnitCount?: number;
  addedVolunteerCount?: number;
  removedUnitCount?: number;
  removedVolunteerCount?: number;
  beforeRiskCount?: number;
  afterRiskCount?: number;
  beforeWarnCount?: number;
  afterWarnCount?: number;
  postValidationPassed?: boolean;
  actionDetails?: Array<{
    actionType?: string;
    sourceCheckCode?: string;
    summary?: string;
    detail?: string;
    unitIds?: string[];
    volunteerIds?: string[];
    removeUnitIds?: string[];
    removeVolunteerIds?: string[];
    candidateUnitIds?: string[];
    candidateVolunteerIds?: string[];
    replacementPairs?: PlanningReplacementPair[];
    totalUnitCount?: number;
    totalVolunteerCount?: number;
    totalReplacementPairCount?: number;
  }>;
  messages?: string[];
  warnings?: string[];
}

export interface PlanningFixProposalApplyRes {
  status?: string;
  message?: string;
  proposal?: PlanningFixProposal;
  repairReport?: PlanningRepairReport;
  state?: PlanningStateRes;
}

export interface PlanningReviewWorkflowRunRes {
  status?: string;
  sessionId?: number;
  sourceVersion?: number;
  reviewState?: PlanningStateRes['reviewState'];
  fixProposalState?: PlanningFixProposalState;
  workflowStatus?: PlanningStateRes['workflowStatus'];
  workspaceState?: PlanningWorkspaceStateRes;
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

export interface PlanningInitialPlanStrategyReport {
  targetProfile?: {
    targetCount?: number;
    targetTierCounts?: Record<string, number>;
    sourceProvinceName?: string;
    volunteerModel?: string;
    requiredMajorCount?: number;
  };
  objectiveWeights?: Array<{
    code?: string;
    label?: string;
    relativeWeight?: number;
    priority?: number;
    description?: string;
  }>;
  selectedCount?: number;
  appliedRepairs?: Array<{
    ruleCode?: string;
    actionType?: string;
    reasonCode?: string;
    fromVolunteerId?: string;
    fromLabel?: string;
    toVolunteerId?: string;
    toLabel?: string;
    detail?: string;
    tradeoffSummary?: string;
  }>;
  actions?: PlanningFixProposalAction[];
  tradeoffs?: Array<{
    ruleCode?: string;
    actionType?: string;
    reasonCode?: string;
    fromVolunteerId?: string;
    fromLabel?: string;
    toVolunteerId?: string;
    toLabel?: string;
    finalScoreDelta?: number;
    admissionRatioDelta?: number;
    hotIndexDelta?: number;
    schoolRankDelta?: number;
    preferredDowngraded?: boolean;
    preferredUpgraded?: boolean;
    gains?: string[];
    costs?: string[];
    summary?: string;
  }>;
  unresolvedRisks?: Array<{
    ruleCode?: string;
    detail?: string;
  }>;
  candidateShortages?: PlanningCandidateShortage[];
  userAttentionMessages?: string[];
}

export interface PlanningReviewCheck {
  code?: string;
  /** 审查 2.0 四级分级：block/action/notice/info；旧数据可能缺省，回退用 level。 */
  severity?: string;
  level?: string;
  passed?: boolean;
  reasonCode?: string;
  summary?: string;
  detail?: string;
  suggestedAction?: string;
  affectedVolunteerIds?: string[];
  suggestedCompensations?: PlanningCompensationAction[];
}

export interface PlanningWorkingPlanItem {
  volunteerId?: string;
  tier?: string;
  schoolName?: string;
  majorName?: string;
  locked?: boolean;
  source?: string;
}

export type PlanningDraftItem = PlanningWorkingPlanItem;

export interface PlanningCandidateItem {
  volunteerId?: string;
  tier?: string;
  subTier?: string;
  planSchoolDataId?: string;
  schoolId?: string;
  schoolUnitCode?: string;
  schoolName?: string;
  displaySchoolName?: string;
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
  viewSummary?: {
    poolEntryTotal?: number;
    poolUnitTotal?: number;
    viewEntryTotal?: number;
    viewUnitTotal?: number;
    loadedEntryCount?: number;
    loadedUnitCount?: number;
  };
}

export interface PlanningCandidateFilterOptionsRes {
  provinceNames?: string[];
  cityNames?: string[];
  schoolKeywords?: string[];
  schoolTags?: string[];
  majorTags?: string[];
  majorKeywords?: string[];
  groups?: Array<{
    groupCode?: string;
    groupName?: string;
    filterField?: string;
    values?: string[];
  }>;
  regionTree?: Array<{
    provinceName?: string;
    cityNames?: string[];
  }>;
  majorTree?: Array<{
    disciplineName?: string;
    categories?: Array<{
      categoryName?: string;
      majorNames?: string[];
    }>;
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

export interface PlanningWorkingPlanUnit {
  unitId?: string;
  tier?: string;
  schoolName?: string;
  source?: string;
  locked?: boolean;
  majorItems?: PlanningUnitMajorItem[];
}

export type PlanningDraftUnit = PlanningWorkingPlanUnit;

export interface PlanningWorkingPlanState {
  items?: PlanningWorkingPlanItem[];
  units?: PlanningWorkingPlanUnit[];
  bannedVolunteerIds?: string[];
  summary?: {
    unitTotal?: number;
    targetUnitCount?: number;
    total?: number;
    targetCount?: number;
    unitTierCounts?: Record<string, number>;
    tierCounts?: Record<string, number>;
  };
}

export interface PlanningOrderedUnit {
  unitId?: string;
  planSchoolDataId?: string;
  schoolId?: string;
  schoolUnitCode?: string;
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
  requiredMajorCount?: number;
  selectedMajorCount?: number;
  totalMajorCount?: number;
  allMajors?: PlanningUnitMajorItem[];
  majorItems?: PlanningUnitMajorItem[];
}

export type PlanningOrderedSortField = 'admissionRatio' | 'schoolRank' | 'finalScore';

export interface PlanningOrderedSortReq {
  sortField: PlanningOrderedSortField;
}

export interface PlanningDataFreshnessState {
  source?: string;
  fetchTime?: string;
  lastCheckedAt?: string;
  examYear?: string;
  prepareType?: string;
  province?: string;
  batch?: string;
  subjectType?: string;
  score?: number;
  requestHash?: string;
  dataHash?: string;
  dataVersion?: string;
  sourceDataHash?: string;
  latestSourceDataHash?: string;
  nextCheckAt?: string;
  checkIntervalMinutes?: number;
  checkSource?: string;
  lastCheckSource?: string;
  lastCheckStatus?: string;
  failCount?: number;
  lastError?: string;
  lastFailedAt?: string;
  latestDataHash?: string;
  latestDataVersion?: string;
  statusCode?: string;
  changeLevel?: 'none' | 'minor' | 'medium' | 'major' | string;
  shouldNotify?: boolean;
  requiresCandidateRefresh?: boolean;
  requiresReview?: boolean;
  summary?: string;
  detail?: string;
  changedCount?: number;
  addedCount?: number;
  removedCount?: number;
  updatedCount?: number;
  invalidCount?: number;
  affectedVolunteerIds?: string[];
  affectedUnitIds?: string[];
  affectedReviewCodes?: string[];
}

export interface PlanningDataFreshnessCheckReq {
  source?: string;
  requestHash?: string;
  dataHash?: string;
  dataVersion?: string;
  sourceDataHash?: string;
  changeLevel?: string;
  summary?: string;
  detail?: string;
  changedCount?: number;
  addedCount?: number;
  removedCount?: number;
  updatedCount?: number;
  invalidCount?: number;
  affectedVolunteerIds?: string[];
  affectedUnitIds?: string[];
  markStale?: boolean;
  fetchLatest?: boolean;
  syncSourceData?: boolean;
  applyLatestSnapshotToWorkspace?: boolean;
}

export interface PlanningDataFreshnessCheckRes {
  version?: number;
  staleFlags?: PlanningStateRes['staleFlags'];
  dataFreshnessState?: PlanningDataFreshnessState;
  workspaceState?: PlanningWorkspaceStateRes;
}

export interface PlanningDataFreshnessScheduleState {
  chatSessionId?: number;
  tenantId?: number;
  prepareType?: string;
  provinceCode?: string;
  provinceName?: string;
  examYear?: number;
  sessionStatus?: string;
  createTime?: string;
  lastAccessedAt?: string;
  lastCheckedAt?: string;
  nextCheckAt?: string;
  checkIntervalMinutes?: number;
  lastCheckSource?: string;
  lastCheckStatus?: string;
  sourceDataHash?: string;
  latestSourceDataHash?: string;
  failCount?: number;
  lastError?: string;
  lastFailedAt?: string;
  enabled?: boolean;
}

export interface PlanningStateRes {
  sessionId?: number;
  version?: number;
  phase?: string;
  studentSummary?: {
    sex?: string;
    score?: number;
    rank?: number;
    batchName?: string;
    batchScore?: number;
    provinceName?: string;
    subjects?: string[];
    strengthSubjects?: string[];
  };
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
    /** 4.0 权威意向字段：priorityRules / coverageRequirements / tierQuotaGoal（横幅派生标签读它）。 */
    hardPlanningObjectives?: Record<string, unknown>;
    /** legacy 只读（4.0 起）：仅为兼容旧会话保留字段与读取，勿在写链新增（口径见队列 21）。 */
    softPreferences?: Record<string, unknown>;
    derivedPreferences?: Record<string, unknown>;
  };
  operationLogs?: Array<Record<string, unknown>>;
  dataFreshnessState?: PlanningDataFreshnessState;
  staleFlags?: {
    candidatePool?: boolean;
    recommendationOverlay?: boolean;
    initialRecommendation?: boolean;
    orderedPlan?: boolean;
    planAdjustment?: boolean;
    review?: boolean;
    reasonCode?: string;
    message?: string;
    affectedReviewCodes?: string[];
  };
  planGenerationState?: PlanningPlanGenerationState;
  initialRecommendationState?: {
    generatedAt?: string;
    sourceVersion?: number;
    candidateViewVersion?: number;
    profileVersion?: number;
    strategyReport?: PlanningInitialPlanStrategyReport;
    summary?: {
      total?: number;
      expertPreferredCount?: number;
      tierCounts?: Record<string, number>;
      localProtectCount?: number;
      gapFixCount?: number;
      unresolvedGapCount?: number;
      unitCompletionCount?: number;
      appliedRepairCount?: number;
      unresolvedRuleCodes?: string[];
    };
  };
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
    sourceSummary?: {
      externalEntryTotal?: number;
      externalUnitTotal?: number;
      externalEntryTierCounts?: Record<string, number>;
      externalUnitTierCounts?: Record<string, number>;
      normalizedEntryTotal?: number;
      normalizedUnitTotal?: number;
      normalizedEntryTierCounts?: Record<string, number>;
      normalizedUnitTierCounts?: Record<string, number>;
    };
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
  workingPlanState?: PlanningWorkingPlanState;
  draftPlanState?: PlanningWorkingPlanState;
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
      /** 审查 2.0 四级计数（只统计未通过的检查）。 */
      blockCount?: number;
      actionCount?: number;
      noticeCount?: number;
      infoCount?: number;
    };
    checks?: PlanningReviewCheck[];
    compensationPreview?: PlanningCompensationPreview;
  };
  workflowStatus?: {
    candidateStatus?: string;
    candidateMessage?: string;
    planStatus?: string;
    planMessage?: string;
    legacySubmitted?: boolean;
    legacyMessage?: string;
    reviewStatus?: string;
    reviewMessage?: string;
    reviewReasonCode?: string;
    reviewReasonMessage?: string;
    affectedReviewCodes?: string[];
    exportStatus?: string;
    exportMessage?: string;
    lastExportedAt?: string;
  };
}

export type OrderedPlanActionRes = Pick<
  PlanningStateRes,
  | 'sessionId'
  | 'version'
  | 'phase'
  | 'staleFlags'
  | 'workingPlanState'
  | 'draftPlanState'
  | 'orderedPlanState'
>;

export type PlanningWorkspaceStateRes = Pick<
  PlanningStateRes,
  | 'sessionId'
  | 'version'
  | 'phase'
  | 'studentSummary'
  | 'profileState'
  | 'constraintState'
  | 'staleFlags'
  | 'planGenerationState'
  | 'initialRecommendationState'
  | 'dataFreshnessState'
  | 'candidatePoolState'
  | 'candidateViewState'
  | 'workingPlanState'
  | 'draftPlanState'
  | 'orderedPlanState'
  | 'reviewState'
  | 'operationLogs'
  | 'workflowStatus'
>;
