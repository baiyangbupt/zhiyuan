import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Collapse, Dropdown, Empty, InputNumber, Modal, Spin, Tag, Tooltip, message } from 'antd';
import {
  PlusOutlined,
  VerticalAlignTopOutlined,
  VerticalAlignBottomOutlined,
  DeleteOutlined,
  FilterOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  SwapOutlined,
  SortAscendingOutlined,
  DownOutlined,
  ShrinkOutlined,
  ExclamationCircleOutlined,
  DownloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  exportPlanningOrderedPlanApi,
  getPlanningCandidateFilterOptionsApi,
  generatePlanningCandidatePoolApi,
  generatePlanningInitialPlanApi,
  getPlanningWorkspaceStateApi,
  movePlanningOrderedItemApi,
  movePlanningOrderedUnitApi,
  queryPlanningCandidatePoolApi,
  removePlanningDraftItemsApi,
  removePlanningOrderedUnitApi,
  runPlanningReviewApi,
  selectPlanningDraftItemsApi,
  sortPlanningOrderedPlanApi,
  updatePlanningCandidateViewStateApi,
} from '@/service/apis/sessionDetail';
import { IUserInfoParams } from '@/interface/api/sessionDetail';
import {
  PlanningCandidateFilterOptionsRes,
  PlanningCandidateItem,
  PlanningCandidatePoolQueryRes,
  PlanningCandidateViewState,
  PlanningDraftItem,
  PlanningDraftUnit,
  PlanningOrderedItem,
  PlanningOrderedUnit,
  PlanningOrderedSortField,
  PlanningReviewCheck,
  PlanningStateRes,
  PlanningWorkspaceIntent,
} from '@/interface/api/volunteer';
import style from './style.module.scss';
import { MAJOR_CATEGORY_TO_DISCIPLINES } from './majorCategoryMap';

const { Panel } = Collapse;

type WorkspaceView = 'candidate' | 'ordered';
type CandidateSortField =
  | 'finalScore'
  | 'admissionRatio'
  | 'tuitionPerYear'
  | 'rankInTier'
  | 'schoolRank'
  | 'hotIndex'
  | 'salaryAvg';
type CandidateSortOrder = 'asc' | 'desc';
type CandidateTier = '' | '冲' | '稳' | '保';
type CandidateFilterOptionGroup = NonNullable<PlanningCandidateFilterOptionsRes['groups']>[number];
type FilterTokenField =
  | 'provinceNames'
  | 'cityNames'
  | 'schoolKeywords'
  | 'schoolTags'
  | 'majorTags'
  | 'majorKeywords'
  | 'expertPreferredOnly';
type FilterTokenPolarity = 'positive' | 'negative';
type ActiveFilterChipField =
  | 'provinceNames'
  | 'cityNames'
  | 'schoolKeyword'
  | 'majorKeyword'
  | 'schoolTags'
  | 'majorTags'
  | 'expertPreferredOnly';
type ActiveFilterChipPolarity = 'positive' | 'negative';

interface CandidateGroup {
  key: string;
  tier: string;
  schoolName: string;
  provinceName?: string;
  cityName?: string;
  items: PlanningCandidateItem[];
  maxScore: number;
  topItem: PlanningCandidateItem;
  schoolEnrollRatio?: number | null;
  preferred: boolean;
}

interface OrderedGroup {
  key: string;
  tier: string;
  schoolName: string;
  provinceName?: string;
  cityName?: string;
  schoolBatch?: string;
  schoolNature?: string;
  schoolCategory?: string;
  schoolLevel?: string;
  schoolEnrollRatio?: number;
  schoolBasicTags: string[];
  schoolRankTags: string[];
  schoolPopupTags: string[];
  topScore?: number;
  topItem: PlanningCandidateItem | null;
  orderedItems: Array<{
    orderedItem: PlanningOrderedItem;
    candidateItem: PlanningCandidateItem | null;
  }>;
}

interface DraftGroup {
  key: string;
  tier: string;
  schoolName: string;
  source?: string;
  items: Array<{
    draftItem: PlanningDraftItem;
    candidateItem: PlanningCandidateItem | null;
  }>;
}

interface SchoolHistoryModalState {
  schoolName: string;
  basicTags: string[];
  rankTags: string[];
  popupTags: string[];
  scores: NonNullable<PlanningCandidateItem['schoolHistoryScores']>;
}

interface OrderedMoveModalState {
  item: PlanningOrderedItem;
  currentPosition: number;
}

interface OrderedUnitMoveModalState {
  group: OrderedGroup;
  currentPosition: number;
}

interface ActiveFilterChip {
  key: string;
  label: string;
  field: ActiveFilterChipField;
  polarity: ActiveFilterChipPolarity;
  value: string;
}

interface FilterPanelOption {
  label: string;
  title: string;
  field: FilterTokenField;
  value: string;
}

interface FilterPanelGroup {
  label: string;
  option?: FilterPanelOption;
  options?: FilterPanelOption[];
  children?: FilterPanelGroup[];
}

interface WorkspacePanelProps {
  routerParams: IUserInfoParams;
  fetchFlag: number;
  examYear?: number | string | null;
  workspaceIntent?: PlanningWorkspaceIntent | null;
  onWorkspaceIntentConsumed?: () => void;
}

const getWorkspaceViewStorageKey = (chatSessionId?: string) =>
  `session_detail_v2_active_view_${chatSessionId || 'default'}`;

const EMPTY_CANDIDATE_FILTER_OPTIONS: PlanningCandidateFilterOptionsRes = {
  provinceNames: [],
  cityNames: [],
  schoolKeywords: [],
  schoolTags: [],
  majorTags: [],
  groups: [],
};

const createDefaultFilters = () => ({
  tier: '' as CandidateTier,
  provinceNames: [] as string[],
  negativeProvinceNames: [] as string[],
  cityNames: [] as string[],
  negativeCityNames: [] as string[],
  schoolKeywords: [] as string[],
  negativeSchoolKeywords: [] as string[],
  majorKeywords: [] as string[],
  negativeMajorKeywords: [] as string[],
  schoolTags: [] as string[],
  negativeSchoolTags: [] as string[],
  majorTags: [] as string[],
  negativeMajorTags: [] as string[],
  expertPreferredOnly: false,
  sortField: 'finalScore' as CandidateSortField,
  sortOrder: 'desc' as CandidateSortOrder,
});

const TIER_OPTIONS = [
  { label: '全部', value: '' },
  { label: '冲', value: '冲' },
  { label: '稳', value: '稳' },
  { label: '保', value: '保' },
] as const;

const SORT_FIELD_OPTIONS = [
  { label: '推荐系数', value: 'finalScore' },
  { label: '录取率', value: 'admissionRatio' },
  { label: '院校层次', value: 'schoolRank' },
  { label: '区间位次', value: 'rankInTier' },
  { label: '专业热度', value: 'hotIndex' },
  { label: '薪酬指数', value: 'salaryAvg' },
  { label: '学费', value: 'tuitionPerYear' },
];

const ORDERED_SORT_OPTIONS: Array<{
  label: string;
  value: PlanningOrderedSortField;
  description: string;
}> = [
  { label: '录取率', value: 'admissionRatio', description: '低录取率排在前面，优先处理风险较高的志愿' },
  { label: '院校层次', value: 'schoolRank', description: '院校排名靠前的排在前面' },
  { label: '推荐系数', value: 'finalScore', description: '推荐系数高的排在前面' },
];

const SALARY_AVG_TOOLTIP =
  '平均薪酬指数，反映该专业毕业生薪酬表现的相对水平，不等同于实际工资。';

const REVIEW_LEVEL_COLOR: Record<string, string> = {
  risk: 'error',
  warn: 'warning',
  info: 'processing',
};
const FILTER_TOKEN_SEPARATOR = '::';

const FILTER_FIELD_META: Record<
  FilterTokenField,
  { label: string; positivePrefix: string; negativePrefix: string; positiveColor: string; negativeColor: string }
> = {
  provinceNames: {
    label: '院校省份',
    positivePrefix: '去',
    negativePrefix: '不去',
    positiveColor: 'blue',
    negativeColor: 'red',
  },
  cityNames: {
    label: '院校城市',
    positivePrefix: '去',
    negativePrefix: '不去',
    positiveColor: 'geekblue',
    negativeColor: 'red',
  },
  schoolKeywords: {
    label: '院校名称',
    positivePrefix: '',
    negativePrefix: '不看',
    positiveColor: 'blue',
    negativeColor: 'red',
  },
  schoolTags: {
    label: '院校属性',
    positivePrefix: '',
    negativePrefix: '不看',
    positiveColor: 'gold',
    negativeColor: 'volcano',
  },
  majorTags: {
    label: '专业属性',
    positivePrefix: '',
    negativePrefix: '不看',
    positiveColor: 'green',
    negativeColor: 'magenta',
  },
  majorKeywords: {
    label: '专业大类',
    positivePrefix: '',
    negativePrefix: '不看',
    positiveColor: 'green',
    negativeColor: 'magenta',
  },
  expertPreferredOnly: {
    label: '推荐标签',
    positivePrefix: '',
    negativePrefix: '',
    positiveColor: 'cyan',
    negativeColor: 'purple',
  },
};

const buildFilterTokenValue = (
  field: FilterTokenField,
  polarity: FilterTokenPolarity,
  value: string
) => `${field}${FILTER_TOKEN_SEPARATOR}${polarity}${FILTER_TOKEN_SEPARATOR}${value}`;

const parseFilterTokenValue = (
  token: string
): { field: FilterTokenField; polarity: FilterTokenPolarity; value: string } | null => {
  const [field, polarity, ...rest] = token.split(FILTER_TOKEN_SEPARATOR);
  const normalizedField = field as FilterTokenField;
  const normalizedPolarity = polarity as FilterTokenPolarity;
  if (!rest.length) {
    return null;
  }
  if (!['provinceNames', 'cityNames', 'schoolKeywords', 'schoolTags', 'majorTags', 'majorKeywords', 'expertPreferredOnly'].includes(normalizedField)) {
    return null;
  }
  if (!['positive', 'negative'].includes(normalizedPolarity)) {
    return null;
  }
  return {
    field: normalizedField,
    polarity: normalizedPolarity,
    value: rest.join(FILTER_TOKEN_SEPARATOR),
  };
};

const uniqueStrings = (values: Array<string | null | undefined>) =>
  Array.from(new Set(values.map(item => (item || '').trim()).filter(Boolean)));

const getVolunteerLegacyPrefix = (volunteerId?: string) => {
  const parts = (volunteerId || '').trim().split('_').filter(Boolean);
  return parts.length >= 3 ? `${parts[0]}_${parts[1]}` : '';
};

const buildCandidateIdentityKeys = (
  item?: Pick<PlanningCandidateItem, 'volunteerId' | 'schoolName' | 'majorName'>
    | Pick<PlanningDraftItem, 'volunteerId' | 'schoolName' | 'majorName'>
    | Pick<PlanningOrderedItem, 'volunteerId' | 'schoolName' | 'majorName'>
) => {
  if (!item) {
    return [];
  }
  return uniqueStrings([
    item.volunteerId,
    getVolunteerLegacyPrefix(item.volunteerId),
    item.schoolName && item.majorName ? `${item.schoolName.trim()}\n${item.majorName.trim()}` : '',
  ]);
};

const hasFilterPanelOptions = (group: FilterPanelGroup): boolean =>
  Boolean(group.option || group.options?.length || group.children?.some(hasFilterPanelOptions));

const MAJOR_FILTER_GROUP_CODES = new Set([
  'major.discipline',
  'major.category',
  'major.tag',
  'admission.type',
  'constraint.limit',
]);

const isMajorFilterGroup = (group: CandidateFilterOptionGroup) => {
  const groupCode = group.groupCode || '';
  const filterField = group.filterField || '';
  return (
    MAJOR_FILTER_GROUP_CODES.has(groupCode) ||
    groupCode.startsWith('major.') ||
    filterField === 'majorTags' ||
    filterField === 'majorKeywords'
  );
};

const MACRO_REGION_TAGS = new Set([
  '华东',
  '华北',
  '华南',
  '华中',
  '西南',
  '西北',
  '东北',
  '华东地区',
  '华北地区',
  '华南地区',
  '华中地区',
  '西南地区',
  '西北地区',
  '东北地区',
  '京津冀',
  '长三角',
  '珠三角',
]);

const GEO_TAG_PREFIXES = ['位于', '地处', '坐落于', '坐落', '所在', '来自'];
const GEO_TAG_SUFFIXES = [
  '省',
  '市',
  '自治区',
  '特别行政区',
  '自治州',
  '地区',
  '盟',
  '新区',
  '自治县',
  '县',
  '院校',
  '高校',
];

const normalizeGeoTag = (value: string) => {
  let normalized = (value || '').trim();
  if (!normalized) {
    return '';
  }
  GEO_TAG_PREFIXES.forEach(prefix => {
    if (normalized.startsWith(prefix)) {
      normalized = normalized.slice(prefix.length).trim();
    }
  });
  GEO_TAG_SUFFIXES.forEach(suffix => {
    if (normalized.endsWith(suffix)) {
      normalized = normalized.slice(0, -suffix.length).trim();
    }
  });
  return normalized;
};

const FIXED_PSEUDO_SCHOOL_TAGS = new Set(['意向省份', '意向城市', '意向地区']);

const isGeoLikeSchoolTag = (value: string, provinceNames: string[] = [], cityNames: string[] = []) => {
  const normalized = (value || '').trim();
  const normalizedGeoTag = normalizeGeoTag(normalized);
  const normalizedProvinceNames = provinceNames
    .map(name => normalizeGeoTag(name || ''))
    .filter(Boolean);
  const normalizedCityNames = cityNames
    .map(name => normalizeGeoTag(name || ''))
    .filter(Boolean);
  if (!normalized) {
    return false;
  }
  if (FIXED_PSEUDO_SCHOOL_TAGS.has(normalized)) {
    return true;
  }
  if (MACRO_REGION_TAGS.has(normalized) || MACRO_REGION_TAGS.has(normalizedGeoTag)) {
    return true;
  }
  if ([...provinceNames, ...cityNames].some(name => (name || '').trim() === normalized)) {
    return true;
  }
  if ([...normalizedProvinceNames, ...normalizedCityNames].includes(normalizedGeoTag)) {
    return true;
  }
  if (
    [...normalizedProvinceNames, ...normalizedCityNames].some(
      geoName =>
        normalized.includes(geoName) ||
        normalizedGeoTag.includes(geoName) ||
        geoName.includes(normalizedGeoTag)
    )
  ) {
    return true;
  }
  return /(省|市|自治区|特别行政区|自治州|地区|盟|新区|自治县|县|院校|高校)$/.test(normalized);
};

const WorkspacePanel: React.FC<WorkspacePanelProps> = ({
  routerParams,
  fetchFlag,
  examYear,
  workspaceIntent,
  onWorkspaceIntentConsumed,
}) => {
  const initialActiveView = (() => {
    if (typeof window === 'undefined') {
      return 'ordered' as WorkspaceView;
    }
    const storedView = window.sessionStorage.getItem(
      getWorkspaceViewStorageKey(routerParams.chatSessionId)
    );
    if (storedView === 'candidate' || storedView === 'ordered') {
      return storedView;
    }
    return 'ordered' as WorkspaceView;
  })();
  const [planningState, setPlanningState] = useState<PlanningStateRes | null>(null);
  const [planningLoading, setPlanningLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<
    'candidate' | 'draft' | 'ordered' | 'review' | null
  >(null);
  const [orderedActionVolunteerId, setOrderedActionVolunteerId] = useState<string | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [activeView, setActiveView] = useState<WorkspaceView>(initialActiveView);
  const [draftExpanded, setDraftExpanded] = useState(false);
  const [candidatePoolResult, setCandidatePoolResult] = useState<PlanningCandidatePoolQueryRes>({
    items: [],
    page: 1,
    pageSize: 24,
    total: 0,
    totalUnitCount: 0,
    loadedEntryCount: 0,
    loadedUnitCount: 0,
  });
  const planYear = Number(examYear) || new Date().getFullYear();
  const planYearTitle = `${planYear}招生计划`;
  const [candidatePoolLoading, setCandidatePoolLoading] = useState(false);
  const [candidateCacheVersion, setCandidateCacheVersion] = useState(0);
  const [showBackTop, setShowBackTop] = useState(false);
  const [overviewCollapsed, setOverviewCollapsed] = useState(false);
  const [sortModalOpen, setSortModalOpen] = useState(false);
  const [selectedOrderedSortField, setSelectedOrderedSortField] =
    useState<PlanningOrderedSortField>('admissionRatio');
  const [orderedMoveModal, setOrderedMoveModal] = useState<OrderedMoveModalState | null>(null);
  const [orderedMoveTargetPosition, setOrderedMoveTargetPosition] = useState<number>(1);
  const [orderedUnitMoveModal, setOrderedUnitMoveModal] = useState<OrderedUnitMoveModalState | null>(null);
  const [orderedUnitMoveTargetPosition, setOrderedUnitMoveTargetPosition] = useState<number>(1);
  const candidateQueryInFlightPagesRef = useRef<Set<string>>(new Set());
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const [filterSearchKeyword, setFilterSearchKeyword] = useState('');
  const [expandedFilterGroupKeys, setExpandedFilterGroupKeys] = useState<string[]>([]);
  const [collapsedOrderedGroupKeys, setCollapsedOrderedGroupKeys] = useState<string[]>([]);
  const [candidateFilterOptions, setCandidateFilterOptions] = useState<PlanningCandidateFilterOptionsRes>({
    ...EMPTY_CANDIDATE_FILTER_OPTIONS,
  });
  const [expandedSchoolMetaKeys, setExpandedSchoolMetaKeys] = useState<string[]>([]);
  const [filters, setFilters] = useState(createDefaultFilters);
  const [focusVolunteerIds, setFocusVolunteerIds] = useState<string[]>([]);
  const [schoolHistoryModal, setSchoolHistoryModal] = useState<SchoolHistoryModalState | null>(null);
  const candidateItemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const orderedItemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const draftItemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const draftBasketRef = useRef<HTMLDivElement | null>(null);
  const workspaceBodyRef = useRef<HTMLDivElement | null>(null);
  const candidateSummaryRef = useRef<HTMLDivElement | null>(null);
  const reviewSummaryRef = useRef<HTMLDivElement | null>(null);
  const workspaceTouchStartYRef = useRef<number | null>(null);
  const workspaceTouchStartAtTopRef = useRef(false);
  const overviewRevealReadyRef = useRef(false);
  const overviewRevealReadyTimerRef = useRef<number | null>(null);
  const candidateItemCacheRef = useRef<Record<string, PlanningCandidateItem>>({});
  const initialFiltersAppliedRef = useRef(false);
  const candidateViewStateHydratedRef = useRef(false);
  const lastSavedCandidateViewStateRef = useRef('');
  const initialPlanRequestedRef = useRef(false);
  const orderedCollapseInitializedRef = useRef(false);
  const previousOrderedCollapseKeysRef = useRef<string[]>([]);

  const draftItems = planningState?.draftPlanState?.items || [];
  const orderedItems = planningState?.orderedPlanState?.items || [];
  const reviewChecks = planningState?.reviewState?.checks || [];
  const pendingActions = planningState?.pendingActions || [];
  const reviewCompensationPreview = planningState?.reviewState?.compensationPreview;
  const summary = planningState?.candidatePoolState?.summary;
  const requiredTierCounts = planningState?.candidatePoolState?.requiredTierCounts || {};
  const draftSummary = planningState?.draftPlanState?.summary;
  const orderedSummary = planningState?.orderedPlanState?.summary;
  const reviewSummary = planningState?.reviewState?.summary;
  const workflowStatus = planningState?.workflowStatus;
  const candidateRiskHints = planningState?.candidatePoolState?.riskHints || [];
  const isLegacySubmittedPlan = planningState?.orderedPlanState?.generationMode === 'legacy_submitted';
  const selectedCandidateIdentitySet = useMemo(
    () =>
      new Set(
        [...draftItems, ...orderedItems].flatMap(item => buildCandidateIdentityKeys(item))
      ),
    [draftItems, orderedItems]
  );
  const isCandidateSelected = (candidate?: PlanningCandidateItem) =>
    buildCandidateIdentityKeys(candidate).some(key => selectedCandidateIdentitySet.has(key));
  const volunteerModel = planningState?.candidatePoolState?.volunteerModel || '';
  const candidateTotalPages = Math.max(
    1,
    Math.ceil((candidatePoolResult.total || 0) / (candidatePoolResult.pageSize || 24))
  );
  const candidateItemMap = useMemo(
    () =>
      new Map(
        Object.values(candidateItemCacheRef.current)
          .filter(item => item.volunteerId)
          .map(item => [item.volunteerId as string, item])
      ),
    [candidatePoolResult.items, candidateCacheVersion]
  );
  const cachedCandidateItems = useMemo(
    () => Object.values(candidateItemCacheRef.current),
    [candidatePoolResult.items, candidateCacheVersion]
  );
  const candidateLegacyPrefixMap = useMemo(() => {
    const result = new Map<string, PlanningCandidateItem>();
    cachedCandidateItems.forEach(item => {
      const prefix = getVolunteerLegacyPrefix(item.volunteerId);
      if (prefix && !result.has(prefix)) {
        result.set(prefix, item);
      }
    });
    return result;
  }, [cachedCandidateItems]);
  const candidateSchoolMajorMap = useMemo(() => {
    const result = new Map<string, PlanningCandidateItem>();
    cachedCandidateItems.forEach(item => {
      if (!item.schoolName || !item.majorName) {
        return;
      }
      const key = `${item.schoolName.trim()}\n${item.majorName.trim()}`;
      if (!result.has(key)) {
        result.set(key, item);
      }
    });
    return result;
  }, [cachedCandidateItems]);
  const resolveCandidateItemForPlan = (
    volunteerId?: string,
    schoolName?: string,
    majorName?: string
  ) => {
    const exact = volunteerId ? candidateItemMap.get(volunteerId) : null;
    if (exact) {
      return exact;
    }
    const legacyPrefix = getVolunteerLegacyPrefix(volunteerId);
    const legacyMatched = legacyPrefix ? candidateLegacyPrefixMap.get(legacyPrefix) : null;
    if (legacyMatched) {
      return legacyMatched;
    }
    const schoolMajorKey =
      schoolName && majorName ? `${schoolName.trim()}\n${majorName.trim()}` : '';
    return schoolMajorKey ? candidateSchoolMajorMap.get(schoolMajorKey) || null : null;
  };

  const attributeFilterOptions = useMemo<FilterPanelGroup[]>(() => {
    const candidateItems = cachedCandidateItems;
    const fallbackMajorDisciplineValues = uniqueStrings(
      candidateItems.map(item => (item as PlanningCandidateItem & { majorDiscipline?: string }).majorDiscipline)
    );
    const fallbackMajorKeywordValues = uniqueStrings([
      ...((candidateFilterOptions as PlanningCandidateFilterOptionsRes & { majorKeywords?: string[] }).majorKeywords || []),
      ...candidateItems.map(item => (item as PlanningCandidateItem & { majorCategory?: string }).majorCategory),
    ]);
    const majorCategoryToDiscipline = new Map<string, string>();
    const provinceToCities = new Map<string, Set<string>>();
    candidateItems.forEach(item => {
      const majorCategory = ((item as PlanningCandidateItem & { majorCategory?: string }).majorCategory || '').trim();
      const majorDiscipline = ((item as PlanningCandidateItem & { majorDiscipline?: string }).majorDiscipline || '').trim();
      if (majorCategory && majorDiscipline && !majorCategoryToDiscipline.has(majorCategory)) {
        majorCategoryToDiscipline.set(majorCategory, majorDiscipline);
      }
      const provinceName = (item.provinceName || '').trim();
      const cityName = (item.cityName || '').trim();
      if (provinceName && cityName) {
        const cities = provinceToCities.get(provinceName) || new Set<string>();
        cities.add(cityName);
        provinceToCities.set(provinceName, cities);
      }
    });

    const backendGroups =
      candidateFilterOptions.groups && candidateFilterOptions.groups.length > 0
        ? candidateFilterOptions.groups
        : [
            { groupName: '院校省份', filterField: 'provinceNames', values: candidateFilterOptions.provinceNames || [] },
            { groupName: '院校城市', filterField: 'cityNames', values: candidateFilterOptions.cityNames || [] },
            { groupCode: 'school.name', groupName: '院校名称', filterField: 'schoolKeywords', values: candidateFilterOptions.schoolKeywords || [] },
            {
              groupName: '院校标签',
              filterField: 'schoolTags',
              values: (candidateFilterOptions.schoolTags || []).filter(
                tag => !isGeoLikeSchoolTag(tag, candidateFilterOptions.provinceNames || [], candidateFilterOptions.cityNames || [])
              ),
            },
            { groupCode: 'major.discipline', groupName: '专业门类', filterField: 'majorTags', values: fallbackMajorDisciplineValues },
            { groupCode: 'major.category', groupName: '专业大类', filterField: 'majorKeywords', values: fallbackMajorKeywordValues },
          ];

    const hasMajorCategoryGroup = backendGroups.some(group => group.groupCode === 'major.category');
    const hasMajorDisciplineGroup = backendGroups.some(group => group.groupCode === 'major.discipline');
    const hasSchoolNameGroup = backendGroups.some(group => group.groupCode === 'school.name');
    const normalizedGroups = [...backendGroups];
    if (!hasSchoolNameGroup && (candidateFilterOptions.schoolKeywords || []).length > 0) {
      normalizedGroups.push({
        groupCode: 'school.name',
        groupName: '院校名称',
        filterField: 'schoolKeywords',
        values: candidateFilterOptions.schoolKeywords,
      });
    }
    if (!hasMajorCategoryGroup && fallbackMajorKeywordValues.length > 0) {
      normalizedGroups.push({
        groupCode: 'major.category',
        groupName: '专业大类',
        filterField: 'majorKeywords',
        values: fallbackMajorKeywordValues,
      });
    }
    if (!hasMajorDisciplineGroup && fallbackMajorDisciplineValues.length > 0) {
      normalizedGroups.push({
        groupCode: 'major.discipline',
        groupName: '专业门类',
        filterField: 'majorTags',
        values: fallbackMajorDisciplineValues,
      });
    }
    const allMajorDisciplineValues = uniqueStrings(
      normalizedGroups
        .filter(group => group.groupCode === 'major.discipline')
        .flatMap(group => group.values || [])
    );
    const resolveDisciplineForCategory = (category: string) => {
      const explicitDiscipline = majorCategoryToDiscipline.get(category);
      if (explicitDiscipline) {
        return explicitDiscipline;
      }
      const dictionaryDisciplines = MAJOR_CATEGORY_TO_DISCIPLINES[category] || [];
      return (
        dictionaryDisciplines.find(discipline => allMajorDisciplineValues.includes(discipline)) ||
        dictionaryDisciplines[0] ||
        ''
      );
    };

    const toPanelGroup = (group: CandidateFilterOptionGroup): FilterPanelGroup | null => {
      const field = (group.filterField || '') as FilterTokenField;
      if (!['provinceNames', 'cityNames', 'schoolKeywords', 'schoolTags', 'majorTags', 'majorKeywords'].includes(field)) {
        return null;
      }
      const groupLabel = group.groupName || FILTER_FIELD_META[field].label;
      const optionValues = uniqueStrings(group.values || []).filter(value => {
        if (field !== 'schoolTags') {
          return true;
        }
        return !isGeoLikeSchoolTag(value, candidateFilterOptions.provinceNames || [], candidateFilterOptions.cityNames || []);
      });
      const options = optionValues.map(value => ({
        label: value,
        title: `${groupLabel} · ${value}`,
        field,
        value,
      }));
      return {
        label: groupLabel,
        options,
      };
    };

    const provinceValues = uniqueStrings(
      normalizedGroups
        .filter(group => group.filterField === 'provinceNames')
        .flatMap(group => group.values || [])
    );
    const cityValues = uniqueStrings(
      normalizedGroups
        .filter(group => group.filterField === 'cityNames')
        .flatMap(group => group.values || [])
    );
    const backendRegionTree = (candidateFilterOptions.regionTree || [])
      .map(node => ({
        provinceName: (node.provinceName || '').trim(),
        cityNames: uniqueStrings(node.cityNames || []).filter(city => cityValues.includes(city)),
      }))
      .filter(node => node.provinceName && provinceValues.includes(node.provinceName));
    const provinceChildren: FilterPanelGroup[] = (
      backendRegionTree.length > 0
        ? backendRegionTree.map(node => ({
            province: node.provinceName,
            cities: node.cityNames,
          }))
        : provinceValues.map(province => ({
            province,
            cities: uniqueStrings(Array.from(provinceToCities.get(province) || []))
              .filter(city => cityValues.includes(city)),
          }))
    ).map(({ province, cities }) => ({
      label: province,
      option: {
        label: province,
        title: `院校省份 · ${province}`,
        field: 'provinceNames' as FilterTokenField,
        value: province,
      },
      children: cities.length > 0
        ? cities.map(city => ({
            label: city,
            option: {
              label: city,
              title: `院校城市 · ${province} · ${city}`,
              field: 'cityNames' as FilterTokenField,
              value: city,
            },
          }))
        : undefined,
    }));

    const regularGroups = normalizedGroups
      .filter(group => !isMajorFilterGroup(group) && !['provinceNames', 'cityNames'].includes(group.filterField || ''))
      .map(group => {
        return toPanelGroup(group);
      })
      .filter(Boolean) as FilterPanelGroup[];

    const categoryValues = uniqueStrings(
      normalizedGroups
        .filter(group => group.groupCode === 'major.category')
        .flatMap(group => group.values || [])
    );
    const groupedCategories = new Map<string, string[]>();
    const unmatchedCategories: string[] = [];
    categoryValues.forEach(value => {
      const discipline = resolveDisciplineForCategory(value);
      if (!discipline) {
        unmatchedCategories.push(value);
        return;
      }
      groupedCategories.set(discipline, [...(groupedCategories.get(discipline) || []), value]);
    });

    const backendMajorTree = (candidateFilterOptions.majorTree || [])
      .map(disciplineNode => {
        const disciplineName = (disciplineNode.disciplineName || '').trim();
        const categories = (disciplineNode.categories || [])
          .map(categoryNode => {
            const categoryName = (categoryNode.categoryName || '').trim();
            const majorNames = uniqueStrings(categoryNode.majorNames || []);
            if (!categoryName || majorNames.length === 0) {
              return null;
            }
            return {
              categoryName,
              majorNames,
            };
          })
          .filter(Boolean) as Array<{ categoryName: string; majorNames: string[] }>;
        if (!disciplineName || categories.length === 0) {
          return null;
        }
        return {
          disciplineName,
          categories,
        };
      })
      .filter(Boolean) as Array<{
        disciplineName: string;
        categories: Array<{ categoryName: string; majorNames: string[] }>;
      }>;

    const majorChildren: FilterPanelGroup[] = backendMajorTree.length > 0
      ? backendMajorTree.map(disciplineNode => ({
          label: disciplineNode.disciplineName,
          option: {
            label: disciplineNode.disciplineName,
            title: `专业门类 · ${disciplineNode.disciplineName}`,
            field: 'majorTags' as FilterTokenField,
            value: disciplineNode.disciplineName,
          },
          children: disciplineNode.categories.map(categoryNode => ({
            label: categoryNode.categoryName,
            option: {
              label: categoryNode.categoryName,
              title: `专业大类 · ${disciplineNode.disciplineName} · ${categoryNode.categoryName}`,
              field: 'majorKeywords' as FilterTokenField,
              value: categoryNode.categoryName,
            },
            children: categoryNode.majorNames.map(majorName => ({
              label: majorName,
              option: {
                label: majorName,
                title: `专业名称 · ${disciplineNode.disciplineName} · ${categoryNode.categoryName} · ${majorName}`,
                field: 'majorKeywords' as FilterTokenField,
                value: majorName,
              },
            })),
          })),
        }))
      : allMajorDisciplineValues.map(discipline => ({
          label: discipline,
          option: {
            label: discipline,
            title: `专业门类 · ${discipline}`,
            field: 'majorTags' as FilterTokenField,
            value: discipline,
          },
          children: (groupedCategories.get(discipline) || []).map(value => ({
            label: value,
            option: {
              label: value,
              title: `专业大类 · ${discipline} · ${value}`,
              field: 'majorKeywords' as FilterTokenField,
              value,
            },
          })),
        }));

    if (backendMajorTree.length === 0 && unmatchedCategories.length > 0) {
      majorChildren.push({
        label: '其他专业大类',
        children: unmatchedCategories.map(value => ({
          label: value,
          option: {
            label: value,
            title: `专业大类 · ${value}`,
            field: 'majorKeywords' as FilterTokenField,
            value,
          },
        })),
      });
    }

    normalizedGroups
      .filter(group => ['admission.type', 'constraint.limit'].includes(group.groupCode || ''))
      .map(group => toPanelGroup(group))
      .filter(Boolean)
      .forEach(group => {
        const subGroup = group as FilterPanelGroup;
        majorChildren.push({
          label: subGroup.label,
          children: (subGroup.options || []).map(option => ({
            label: option.label,
            option,
          })),
        });
      });

    const mappedGroups: FilterPanelGroup[] = [{
      label: '推荐标签',
      options: [
        {
          label: '专家优选组合',
          title: '推荐标签 · 专家优选组合',
          field: 'expertPreferredOnly',
          value: '专家优选组合',
        },
      ],
    }, ...regularGroups];

    if (provinceChildren.some(hasFilterPanelOptions)) {
      mappedGroups.splice(1, 0, {
        label: '院校地域',
        children: provinceChildren,
      });
    }

    if (majorChildren.some(hasFilterPanelOptions)) {
      mappedGroups.push({
        label: '专业',
        children: majorChildren,
      });
    }

    return mappedGroups.filter(hasFilterPanelOptions);
  }, [cachedCandidateItems, candidateFilterOptions]);

  const selectedAttributeFilterTokens = useMemo(() => {
    const tokens: string[] = [];
    filters.provinceNames.forEach(name => {
      tokens.push(buildFilterTokenValue('provinceNames', 'positive', name));
    });
    filters.negativeProvinceNames.forEach(name => {
      tokens.push(buildFilterTokenValue('provinceNames', 'negative', name));
    });
    filters.cityNames.forEach(name => {
      tokens.push(buildFilterTokenValue('cityNames', 'positive', name));
    });
    filters.negativeCityNames.forEach(name => {
      tokens.push(buildFilterTokenValue('cityNames', 'negative', name));
    });
    filters.schoolKeywords.forEach(name => {
      tokens.push(buildFilterTokenValue('schoolKeywords', 'positive', name));
    });
    filters.negativeSchoolKeywords.forEach(name => {
      tokens.push(buildFilterTokenValue('schoolKeywords', 'negative', name));
    });
    filters.schoolTags.forEach(tag => {
      tokens.push(buildFilterTokenValue('schoolTags', 'positive', tag));
    });
    filters.negativeSchoolTags.forEach(tag => {
      tokens.push(buildFilterTokenValue('schoolTags', 'negative', tag));
    });
    filters.majorTags.forEach(tag => {
      tokens.push(buildFilterTokenValue('majorTags', 'positive', tag));
    });
    filters.negativeMajorTags.forEach(tag => {
      tokens.push(buildFilterTokenValue('majorTags', 'negative', tag));
    });
    filters.majorKeywords.forEach(tag => {
      tokens.push(buildFilterTokenValue('majorKeywords', 'positive', tag));
    });
    filters.negativeMajorKeywords.forEach(tag => {
      tokens.push(buildFilterTokenValue('majorKeywords', 'negative', tag));
    });
    if (filters.expertPreferredOnly) {
      tokens.push(buildFilterTokenValue('expertPreferredOnly', 'positive', '专家优选组合'));
    }
    return uniqueStrings(tokens);
  }, [
    filters.provinceNames,
    filters.negativeProvinceNames,
    filters.cityNames,
    filters.negativeCityNames,
    filters.schoolKeywords,
    filters.negativeSchoolKeywords,
    filters.schoolTags,
    filters.negativeSchoolTags,
    filters.majorTags,
    filters.negativeMajorTags,
    filters.majorKeywords,
    filters.negativeMajorKeywords,
    filters.expertPreferredOnly,
  ]);

  const filteredAttributeFilterOptions = useMemo(() => {
    const keyword = filterSearchKeyword.trim().toLowerCase();
    if (!keyword) {
      return attributeFilterOptions;
    }
    const filterGroup = (group: FilterPanelGroup): FilterPanelGroup | null => {
      const groupMatched = group.label.toLowerCase().includes(keyword);
      const options = groupMatched
        ? group.options
        : group.options?.filter(
            option =>
              option.title.toLowerCase().includes(keyword) ||
              option.label.toLowerCase().includes(keyword)
          );
      const children = groupMatched
        ? group.children
        : group.children
            ?.map(filterGroup)
            .filter(Boolean) as FilterPanelGroup[] | undefined;
      const nextGroup = {
        ...group,
        options,
        children,
      };
      return hasFilterPanelOptions(nextGroup) ? nextGroup : null;
    };
    return attributeFilterOptions.map(filterGroup).filter(Boolean) as FilterPanelGroup[];
  }, [attributeFilterOptions, filterSearchKeyword]);

  const activeFilterChips = useMemo<ActiveFilterChip[]>(() => {
    const chips: ActiveFilterChip[] = [];
    filters.provinceNames.forEach(name => {
      chips.push({
        key: `region-positive-${name}`,
        label: `院校所在省 · 去${name}`,
        field: 'provinceNames',
        polarity: 'positive',
        value: name,
      });
    });
    filters.negativeProvinceNames.forEach(name => {
      chips.push({
        key: `region-negative-${name}`,
        label: `院校所在省 · 不去${name}`,
        field: 'provinceNames',
        polarity: 'negative',
        value: name,
      });
    });
    filters.cityNames.forEach(name => {
      chips.push({
        key: `city-positive-${name}`,
        label: `院校所在市 · 去${name}`,
        field: 'cityNames',
        polarity: 'positive',
        value: name,
      });
    });
    filters.negativeCityNames.forEach(name => {
      chips.push({
        key: `city-negative-${name}`,
        label: `院校所在市 · 不去${name}`,
        field: 'cityNames',
        polarity: 'negative',
        value: name,
      });
    });
    filters.schoolKeywords.forEach(name => {
      chips.push({
        key: `school-keyword-positive-${name}`,
        label: `院校名称 · ${name}`,
        field: 'schoolKeyword',
        polarity: 'positive',
        value: name,
      });
    });
    filters.negativeSchoolKeywords.forEach(name => {
      chips.push({
        key: `school-keyword-negative-${name}`,
        label: `院校名称 · 不看${name}`,
        field: 'schoolKeyword',
        polarity: 'negative',
        value: name,
      });
    });
    filters.majorKeywords.forEach(name => {
      chips.push({
        key: `major-keyword-positive-${name}`,
        label: `专业 · ${name}`,
        field: 'majorKeyword',
        polarity: 'positive',
        value: name,
      });
    });
    filters.negativeMajorKeywords.forEach(name => {
      chips.push({
        key: `major-keyword-negative-${name}`,
        label: `专业 · 不看${name}`,
        field: 'majorKeyword',
        polarity: 'negative',
        value: name,
      });
    });
    filters.schoolTags.forEach(tag => {
      chips.push({
        key: `school-tag-positive-${tag}`,
        label: `院校标签 · ${tag}`,
        field: 'schoolTags',
        polarity: 'positive',
        value: tag,
      });
    });
    filters.negativeSchoolTags.forEach(tag => {
      chips.push({
        key: `school-tag-negative-${tag}`,
        label: `院校标签 · 不看${tag}`,
        field: 'schoolTags',
        polarity: 'negative',
        value: tag,
      });
    });
    filters.majorTags.forEach(tag => {
      chips.push({
        key: `major-tag-positive-${tag}`,
        label: `专业条件 · ${tag}`,
        field: 'majorTags',
        polarity: 'positive',
        value: tag,
      });
    });
    filters.negativeMajorTags.forEach(tag => {
      chips.push({
        key: `major-tag-negative-${tag}`,
        label: `专业条件 · 不看${tag}`,
        field: 'majorTags',
        polarity: 'negative',
        value: tag,
      });
    });
    if (filters.expertPreferredOnly) {
      chips.push({
        key: 'generic-positive-expert-preferred',
        label: '推荐标签 · 专家优选组合',
        field: 'expertPreferredOnly',
        polarity: 'positive',
        value: '专家优选组合',
      });
    }
    return chips;
  }, [
    filters.provinceNames,
    filters.negativeProvinceNames,
    filters.cityNames,
    filters.negativeCityNames,
    filters.schoolKeywords,
    filters.negativeSchoolKeywords,
    filters.majorKeywords,
    filters.negativeMajorKeywords,
    filters.schoolTags,
    filters.negativeSchoolTags,
    filters.majorTags,
    filters.negativeMajorTags,
    filters.expertPreferredOnly,
  ]);

  const attributeFilterTriggerText = useMemo(() => {
    if (!activeFilterChips.length) {
      return '筛选 / 排除标签';
    }
    const labels = activeFilterChips.map(chip => chip.label);
    if (!labels.length) {
      return '筛选 / 排除标签';
    }
    if (labels.length <= 2) {
      return labels.join('，');
    }
    return `${labels.slice(0, 2).join('，')} +${labels.length - 2}`;
  }, [activeFilterChips]);

  const parseMetricValue = (item: PlanningCandidateItem, key: string) => {
    const sourceList = [...(item.riskFlags || []), ...(item.reasonCodes || [])];
    const matched = sourceList.find(entry => entry.startsWith(`${key}:`));
    if (!matched) {
      return null;
    }
    const rawValue = matched.slice(key.length + 1).trim();
    const parsed = Number(rawValue);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const getSortableValue = (item: PlanningCandidateItem, field: CandidateSortField) => {
    if (field === 'hotIndex') {
      return item.hotIndex ?? parseMetricValue(item, 'hot_index');
    }
    if (field === 'salaryAvg') {
      return item.salaryAvg ?? parseMetricValue(item, 'salary_avg');
    }
    if (field === 'admissionRatio') {
      return item.schoolEnrollRatio ?? item.admissionRatio ?? null;
    }
    return item[field] ?? null;
  };

  const sortedCandidateItems = useMemo(() => {
    const items = [...(candidatePoolResult.items || [])];
    const { sortField, sortOrder } = filters;
    items.sort((left, right) => {
      const leftValue = getSortableValue(left, sortField);
      const rightValue = getSortableValue(right, sortField);
      const normalizedLeft = leftValue ?? (sortOrder === 'desc' ? -Infinity : Infinity);
      const normalizedRight = rightValue ?? (sortOrder === 'desc' ? -Infinity : Infinity);
      return sortOrder === 'desc'
        ? Number(normalizedRight) - Number(normalizedLeft)
        : Number(normalizedLeft) - Number(normalizedRight);
    });
    return items;
  }, [candidatePoolResult.items, filters.sortField, filters.sortOrder]);

  const groupedCandidateList = useMemo(() => {
    const tierRank = (tier?: string) => {
      if (tier === '冲') return 1;
      if (tier === '稳') return 2;
      if (tier === '保') return 3;
      return 9;
    };
    const groupedMap = new Map<string, CandidateGroup>();
    sortedCandidateItems.forEach(item => {
      const tier = (item.tier || '') as CandidateTier;
      const schoolName = item.schoolName || '未知院校';
      const key = `${tier}__${item.planSchoolDataId || item.schoolId || schoolName}`;
      const existed = groupedMap.get(key);
      if (existed) {
        existed.items.push(item);
        existed.maxScore = Math.max(existed.maxScore, item.finalScore || 0);
        return;
      }
      groupedMap.set(key, {
        key,
        tier,
        schoolName,
        provinceName: item.provinceName,
        cityName: item.cityName,
        items: [item],
        maxScore: item.finalScore || 0,
        topItem: item,
        schoolEnrollRatio: item.schoolEnrollRatio ?? item.admissionRatio ?? null,
        preferred: Boolean(item.preferred),
      });
    });

    return Array.from(groupedMap.values())
      .map(group => ({
        ...group,
        preferred: group.items.some(item => Boolean(item.preferred)),
        schoolEnrollRatio: group.items.reduce<number | null>((current, item) => {
          const nextValue = item.schoolEnrollRatio ?? item.admissionRatio ?? null;
          if (nextValue === null || nextValue === undefined) {
            return current;
          }
          if (current === null || current === undefined) {
            return nextValue;
          }
          return Math.max(current, nextValue);
        }, group.schoolEnrollRatio ?? null),
      }))
      .filter(group => !filters.tier || group.tier === filters.tier)
      .filter(group => !filters.expertPreferredOnly || group.preferred)
      .sort((left, right) => {
        const leftSortValue =
          filters.sortField === 'admissionRatio'
            ? left.topItem.schoolEnrollRatio ?? left.topItem.admissionRatio ?? null
            : getSortableValue(left.topItem, filters.sortField);
        const rightSortValue =
          filters.sortField === 'admissionRatio'
            ? right.topItem.schoolEnrollRatio ?? right.topItem.admissionRatio ?? null
            : getSortableValue(right.topItem, filters.sortField);
        const normalizedLeft = leftSortValue ?? (filters.sortOrder === 'desc' ? -Infinity : Infinity);
        const normalizedRight = rightSortValue ?? (filters.sortOrder === 'desc' ? -Infinity : Infinity);
        if (normalizedLeft !== normalizedRight) {
          return filters.sortOrder === 'desc'
            ? Number(normalizedRight) - Number(normalizedLeft)
            : Number(normalizedLeft) - Number(normalizedRight);
        }
        const tierDiff = tierRank(left.tier) - tierRank(right.tier);
        if (tierDiff !== 0) {
          return tierDiff;
        }
        return (right.maxScore || 0) - (left.maxScore || 0);
      });
  }, [sortedCandidateItems, filters.tier, filters.expertPreferredOnly, filters.sortField, filters.sortOrder]);

  const buildCandidateQuery = (page: number = 1) => {
    return {
      filters: {
        tiers: filters.tier ? [filters.tier] : [],
        provinceNames: filters.provinceNames,
        negativeProvinceNames: filters.negativeProvinceNames,
        cityNames: filters.cityNames,
        negativeCityNames: filters.negativeCityNames,
        schoolKeywords: filters.schoolKeywords,
        negativeSchoolKeywords: filters.negativeSchoolKeywords,
        majorKeywords: filters.majorKeywords,
        negativeMajorKeywords: filters.negativeMajorKeywords,
        schoolTags: filters.schoolTags,
        negativeSchoolTags: filters.negativeSchoolTags,
        majorTags: filters.majorTags,
        negativeMajorTags: filters.negativeMajorTags,
      },
      sort: {
        field: filters.sortField,
        order: filters.sortOrder,
      },
      page,
      pageSize: candidatePoolResult.pageSize || 12,
    };
  };

  const buildCandidateViewStatePayload = (): PlanningCandidateViewState => ({
    filters: {
      tiers: filters.tier ? [filters.tier] : [],
      provinceNames: filters.provinceNames,
      negativeProvinceNames: filters.negativeProvinceNames,
      cityNames: filters.cityNames,
      negativeCityNames: filters.negativeCityNames,
      schoolKeywords: filters.schoolKeywords,
      negativeSchoolKeywords: filters.negativeSchoolKeywords,
      majorKeywords: filters.majorKeywords,
      negativeMajorKeywords: filters.negativeMajorKeywords,
      schoolTags: filters.schoolTags,
      negativeSchoolTags: filters.negativeSchoolTags,
      majorTags: filters.majorTags,
      negativeMajorTags: filters.negativeMajorTags,
    },
    sort: {
      field: filters.sortField,
      order: filters.sortOrder,
    },
    expertPreferredOnly: filters.expertPreferredOnly,
  });

  const resetCandidateFilters = () => {
    setFilters(prev => ({
      ...prev,
      ...createDefaultFilters(),
    }));
  };

  const mergeCandidateItemsToCache = (items?: PlanningCandidateItem[]) => {
    const candidateItems = items || [];
    if (candidateItems.length > 0) {
      candidateItems.forEach(item => {
        const key =
          item.volunteerId ||
          `${item.planSchoolDataId || item.schoolId || item.schoolName}-${item.majorId || item.majorName}`;
        if (key) {
          candidateItemCacheRef.current[key] = item;
        }
      });
      setCandidateCacheVersion(version => version + 1);
    }
  };

  const applyPlanningState = (data: PlanningStateRes) => {
    mergeCandidateItemsToCache(data.candidatePoolState?.items);
    setPlanningState(data);
  };

  const mergeWorkspaceState = (data: PlanningStateRes) => {
    mergeCandidateItemsToCache(data.candidatePoolState?.items);
    setPlanningState(prev => ({
      ...(prev || {}),
      ...data,
      candidatePoolState: {
        ...(prev?.candidatePoolState || {}),
        ...(data.candidatePoolState || {}),
        items: [],
      },
    }));
  };

  const fetchWorkspaceState = async () => {
    if (planningLoading) {
      return;
    }
    setPlanningLoading(true);
    try {
      const { data, code } = await getPlanningWorkspaceStateApi(
        routerParams.tenantId,
        routerParams.chatSessionId
      );
      if (code === 0 && data) {
        mergeWorkspaceState(data);
      } else {
        message.error('获取工作台状态失败');
      }
    } catch (error) {
      message.error('获取工作台状态异常，请稍后重试');
    }
    setPlanningLoading(false);
  };

  const ensureInitialPlanReady = async () => {
    if (initialPlanRequestedRef.current) {
      return;
    }
    if (!planningState) {
      return;
    }
    if ((planningState.draftPlanState?.items || []).length > 0) {
      return;
    }
    if ((planningState.orderedPlanState?.items || []).length > 0) {
      return;
    }
    initialPlanRequestedRef.current = true;
    setPlanningLoading(true);
    try {
      const { data, code } = await generatePlanningInitialPlanApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        false,
        true,
        false
      );
      if (code === 0 && data) {
        applyPlanningState(data);
        setActiveView('ordered');
      } else {
        initialPlanRequestedRef.current = false;
      }
    } catch (error) {
      initialPlanRequestedRef.current = false;
    }
    setPlanningLoading(false);
  };

  const fetchCandidateFilterOptions = async () => {
    try {
      const { data, code } = await getPlanningCandidateFilterOptionsApi(
        routerParams.tenantId,
        routerParams.chatSessionId
      );
      if (code === 0 && data) {
        setCandidateFilterOptions({
          provinceNames: data.provinceNames || [],
          cityNames: data.cityNames || [],
          schoolKeywords: data.schoolKeywords || [],
          schoolTags: data.schoolTags || [],
          majorTags: data.majorTags || [],
          majorKeywords: data.majorKeywords || [],
          groups: data.groups || [],
          regionTree: data.regionTree || [],
          majorTree: data.majorTree || [],
        });
      }
    } catch (error) {
      console.warn('获取候选筛选项失败', error);
    }
  };

  const hasLoadedFilterOptions = useMemo(() => {
    return Boolean(
      (candidateFilterOptions.groups && candidateFilterOptions.groups.length > 0) ||
        (candidateFilterOptions.schoolKeywords && candidateFilterOptions.schoolKeywords.length > 0) ||
        (candidateFilterOptions.majorTree && candidateFilterOptions.majorTree.length > 0) ||
        (candidateFilterOptions.provinceNames && candidateFilterOptions.provinceNames.length > 0) ||
        (candidateFilterOptions.cityNames && candidateFilterOptions.cityNames.length > 0) ||
        (candidateFilterOptions.schoolTags && candidateFilterOptions.schoolTags.length > 0) ||
        (candidateFilterOptions.majorTags && candidateFilterOptions.majorTags.length > 0) ||
        ((candidateFilterOptions as PlanningCandidateFilterOptionsRes & { majorKeywords?: string[] }).majorKeywords &&
          (candidateFilterOptions as PlanningCandidateFilterOptionsRes & { majorKeywords?: string[] }).majorKeywords!.length > 0)
    );
  }, [candidateFilterOptions]);

  const ensureCandidatePoolReady = async (forceRegenerate: boolean = false) => {
    const shouldGenerate =
      forceRegenerate ||
      Boolean(planningState?.staleFlags?.candidatePool) ||
      !planningState?.candidatePoolState?.summary?.total;
    if (!shouldGenerate) {
      return true;
    }

    setCandidatePoolLoading(true);
    try {
      const { data, code } = await generatePlanningCandidatePoolApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        true
      );
      if (code === 0 && data) {
        applyPlanningState(data);
        return true;
      }
      message.error('刷新候选池失败');
    } catch (error) {
      message.error('刷新候选池异常，请稍后重试');
    }
    setCandidatePoolLoading(false);
    return false;
  };

  const queryCandidatePool = async (page: number = 1, append: boolean = false) => {
    const requestKey = `${append ? 'append' : 'replace'}:${page}`;
    if (candidateQueryInFlightPagesRef.current.has(requestKey)) {
      return;
    }
    candidateQueryInFlightPagesRef.current.add(requestKey);
    setCandidatePoolLoading(true);
    try {
      const { data, code } = await queryPlanningCandidatePoolApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        buildCandidateQuery(page)
      );
      if (code === 0 && data) {
        setCandidatePoolResult(prev => {
          const nextItems = append ? [...(prev.items || []), ...(data.items || [])] : data.items || [];
          const mergedItems = nextItems.filter((item, index, array) => {
            const key = item.volunteerId || `${item.planSchoolDataId || item.schoolId || item.schoolName}-${item.majorId || item.majorName}`;
            return array.findIndex(candidate => {
              const candidateKey = candidate.volunteerId || `${candidate.planSchoolDataId || candidate.schoolId || candidate.schoolName}-${candidate.majorId || candidate.majorName}`;
              return candidateKey === key;
            }) === index;
          });
          mergedItems.forEach(item => {
            const key = item.volunteerId || `${item.planSchoolDataId || item.schoolId || item.schoolName}-${item.majorId || item.majorName}`;
            if (key) {
              candidateItemCacheRef.current[key] = item;
            }
          });
          const loadedUnitCount = !isMajorGroupMode
            ? mergedItems.length
            : new Set(
              mergedItems.map(item =>
                item.planSchoolDataId || item.schoolId || item.schoolName || item.volunteerId || ''
              )
            ).size;
          return {
            items: mergedItems,
            page: data.page || page,
            pageSize: data.pageSize || prev.pageSize || 24,
            total: data.total || 0,
            totalUnitCount: data.totalUnitCount ?? prev.totalUnitCount ?? 0,
            loadedEntryCount: mergedItems.length,
            loadedUnitCount,
          };
        });
      } else {
        message.error('查询候选志愿失败');
      }
    } catch (error) {
      message.error('查询候选志愿异常，请稍后重试');
    } finally {
      candidateQueryInFlightPagesRef.current.delete(requestKey);
      setCandidatePoolLoading(false);
    }
  };

  const refreshCandidatePool = async (forceRegenerate: boolean = false) => {
    const ready = await ensureCandidatePoolReady(forceRegenerate);
    if (ready) {
      queryCandidatePool(1);
    }
  };

  const handleAddCandidateToDraft = async (volunteerId?: string) => {
    if (!volunteerId || actionLoading) {
      return;
    }
    setActionLoading('draft');
    try {
      const { data, code } = await selectPlanningDraftItemsApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        [volunteerId],
        'manual_workspace_v2'
      );
      if (code === 0) {
        message.success('已加入方案');
        if (data) {
          applyPlanningState(data);
        } else {
          await fetchWorkspaceState();
        }
        if (volunteerId) {
          setFocusVolunteerIds([volunteerId]);
        }
      } else {
        message.error('加入方案失败');
      }
    } catch (error) {
      message.error('加入方案异常，请稍后重试');
    }
    setActionLoading(null);
  };

  const handleRemoveDraftItem = async (volunteerId?: string) => {
    if (!volunteerId || actionLoading) {
      return;
    }
    setActionLoading('draft');
    try {
      const { data, code } = await removePlanningDraftItemsApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        [volunteerId]
      );
      if (code === 0) {
        message.success('已移出方案');
        if (data) {
          applyPlanningState(data);
        } else {
          await fetchWorkspaceState();
        }
      } else {
        message.error('移出方案失败');
      }
    } catch (error) {
      message.error('移出方案异常，请稍后重试');
    }
    setActionLoading(null);
  };

  const handleRemoveDraftGroup = async (group: DraftGroup) => {
    const volunteerIds = group.items
      .map(item => item.draftItem.volunteerId || '')
      .filter(Boolean);
    if (!volunteerIds.length || actionLoading) {
      return;
    }
    setActionLoading('draft');
    try {
      const { data, code } = await removePlanningDraftItemsApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        volunteerIds
      );
      if (code === 0) {
        message.success('已移出该专业组');
        if (data) {
          applyPlanningState(data);
        } else {
          await fetchWorkspaceState();
        }
      } else {
        message.error('移出专业组失败');
      }
    } catch (error) {
      message.error('移出专业组异常，请稍后重试');
    }
    setActionLoading(null);
  };

  const applyMoveOrderedItem = async (
    item: PlanningOrderedItem,
    targetPosition: number,
    loadingText: string,
    successText?: string
  ) => {
    if (!item?.volunteerId || actionLoading) {
      return;
    }
    const normalizedTargetPosition = Math.max(1, Math.min(targetPosition, orderedItems.length));
    const currentPosition = orderedItems.findIndex(orderedItem => orderedItem.volunteerId === item.volunteerId) + 1;
    if (!currentPosition || normalizedTargetPosition === currentPosition) {
      return;
    }
    setActionLoading('ordered');
    setOrderedActionVolunteerId(item.volunteerId);
    const hideLoading = message.loading(loadingText, 0);
    try {
      const { data, code } = await movePlanningOrderedItemApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        item.volunteerId,
        normalizedTargetPosition
      );
      if (code === 0) {
        if (successText) {
          message.success(successText);
        }
        if (data) {
          setPlanningState(prev => ({
            ...(prev || {}),
            ...data,
            orderedPlanState: data.orderedPlanState || prev?.orderedPlanState,
          }));
        }
      } else {
        message.error('更新排序位置失败');
      }
    } catch (error) {
      message.error('更新排序位置异常，请稍后重试');
    }
    hideLoading();
    setActionLoading(null);
    setOrderedActionVolunteerId(null);
  };

  const handleMoveOrderedItem = async (
    item?: PlanningOrderedItem,
    currentIndex: number = 0,
    direction: 'up' | 'down' = 'up'
  ) => {
    if (!item?.volunteerId || actionLoading) {
      return;
    }
    const currentPosition = currentIndex + 1;
    const targetPosition = direction === 'up' ? currentPosition - 1 : currentPosition + 1;
    if (targetPosition < 1 || targetPosition > orderedItems.length) {
      return;
    }
    await applyMoveOrderedItem(
      item,
      targetPosition,
      direction === 'up' ? '正在上移志愿...' : '正在下移志愿...'
    );
  };

  const openOrderedMoveModal = (item: PlanningOrderedItem, currentIndex: number) => {
    if (!item?.volunteerId || actionLoading) {
      return;
    }
    const currentPosition = currentIndex + 1;
    setOrderedMoveModal({
      item,
      currentPosition,
    });
    setOrderedMoveTargetPosition(currentPosition);
  };

  const closeOrderedMoveModal = () => {
    if (actionLoading === 'ordered') {
      return;
    }
    setOrderedMoveModal(null);
  };

  const handleMoveOrderedItemToTarget = async () => {
    if (!orderedMoveModal?.item || actionLoading) {
      return;
    }
    await applyMoveOrderedItem(
      orderedMoveModal.item,
      orderedMoveTargetPosition,
      '正在移动志愿...',
      '方案位置已更新'
    );
    setOrderedMoveModal(null);
  };

  const applyMoveOrderedUnit = async (
    group: OrderedGroup,
    targetPosition: number,
    loadingText: string,
    successText?: string
  ) => {
    if (!group?.key || actionLoading) {
      return;
    }
    const normalizedTargetPosition = Math.max(1, Math.min(targetPosition, groupedOrderedList.length));
    const currentPosition = groupedOrderedList.findIndex(item => item.key === group.key) + 1;
    if (!currentPosition || normalizedTargetPosition === currentPosition) {
      return;
    }
    setActionLoading('ordered');
    setOrderedActionVolunteerId(group.key);
    const hideLoading = message.loading(loadingText, 0);
    try {
      const { data, code } = await movePlanningOrderedUnitApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        group.key,
        normalizedTargetPosition
      );
      if (code === 0) {
        if (successText) {
          message.success(successText);
        }
        if (data) {
          setPlanningState(prev => ({
            ...(prev || {}),
            ...data,
            orderedPlanState: data.orderedPlanState || prev?.orderedPlanState,
          }));
        }
      } else {
        message.error('更新专业组位置失败');
      }
    } catch (error) {
      message.error('更新专业组位置异常，请稍后重试');
    }
    hideLoading();
    setActionLoading(null);
    setOrderedActionVolunteerId(null);
  };

  const handleMoveOrderedUnit = async (
    group: OrderedGroup,
    currentIndex: number,
    direction: 'up' | 'down'
  ) => {
    const currentPosition = currentIndex + 1;
    const targetPosition = direction === 'up' ? currentPosition - 1 : currentPosition + 1;
    if (targetPosition < 1 || targetPosition > groupedOrderedList.length) {
      return;
    }
    await applyMoveOrderedUnit(
      group,
      targetPosition,
      direction === 'up' ? '正在上移专业组...' : '正在下移专业组...'
    );
  };

  const openOrderedUnitMoveModal = (group: OrderedGroup, currentIndex: number) => {
    if (!group?.key || actionLoading) {
      return;
    }
    const currentPosition = currentIndex + 1;
    setOrderedUnitMoveModal({
      group,
      currentPosition,
    });
    setOrderedUnitMoveTargetPosition(currentPosition);
  };

  const closeOrderedUnitMoveModal = () => {
    if (actionLoading === 'ordered') {
      return;
    }
    setOrderedUnitMoveModal(null);
  };

  const handleMoveOrderedUnitToTarget = async () => {
    if (!orderedUnitMoveModal?.group || actionLoading) {
      return;
    }
    await applyMoveOrderedUnit(
      orderedUnitMoveModal.group,
      orderedUnitMoveTargetPosition,
      '正在移动专业组...',
      '专业组位置已更新'
    );
    setOrderedUnitMoveModal(null);
  };

  const handleRemoveOrderedUnit = async (group: OrderedGroup) => {
    if (!group?.key || actionLoading) {
      return;
    }
    setActionLoading('ordered');
    setOrderedActionVolunteerId(group.key);
    try {
      const { data, code } = await removePlanningOrderedUnitApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        [group.key]
      );
      if (code === 0) {
        message.success('已移出该专业组');
        if (data) {
          setPlanningState(prev => ({
            ...(prev || {}),
            ...data,
            orderedPlanState: data.orderedPlanState || prev?.orderedPlanState,
          }));
        } else {
          await fetchWorkspaceState();
        }
      } else {
        message.error('移出专业组失败');
      }
    } catch (error) {
      message.error('移出专业组异常，请稍后重试');
    }
    setActionLoading(null);
    setOrderedActionVolunteerId(null);
  };

  const handleExportOrderedPlan = async () => {
    if (!routerParams?.tenantId || !routerParams?.chatSessionId || exportLoading) {
      return;
    }
    if (!orderedItems.length) {
      message.warning('当前方案为空，请先生成方案后再导出');
      return;
    }
    try {
      setExportLoading(true);
      const response: any = await exportPlanningOrderedPlanApi(
        routerParams.tenantId,
        routerParams.chatSessionId
      );
      let fileName = `方案_${new Date().toLocaleDateString()}.xlsx`;
      const contentDisposition =
        response.headers?.['content-disposition'] || response.headers?.['Content-Disposition'];
      if (contentDisposition) {
        const utf8FileNameMatch = contentDisposition.match(/filename\*=UTF-8''(.+)/i);
        const regularFileNameMatch = contentDisposition.match(/filename=\"?([^\"]+)\"?/i);
        if (utf8FileNameMatch) {
          fileName = decodeURIComponent(utf8FileNameMatch[1]);
        } else if (regularFileNameMatch) {
          fileName = regularFileNameMatch[1];
        }
      }

      const downloadUrl = window.URL.createObjectURL(response.data);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);
      fetchWorkspaceState();
    } catch (error) {
      message.error('导出方案失败，请稍后重试');
      console.error('导出方案失败:', error);
    } finally {
      setExportLoading(false);
    }
  };

  const handleRunReview = async () => {
    if (!routerParams?.tenantId || !routerParams?.chatSessionId || actionLoading || !orderedItems.length) {
      return;
    }
    setActionLoading('review');
    try {
      const { code } = await runPlanningReviewApi(routerParams.tenantId, routerParams.chatSessionId);
      if (code === 0) {
        message.success('审查完成');
        await fetchWorkspaceState();
      } else {
        message.error('审查失败');
      }
    } catch (error) {
      message.error('审查异常，请稍后重试');
    }
    setActionLoading(null);
  };

  const handleSortOrderedPlan = async () => {
    if (!routerParams?.tenantId || !routerParams?.chatSessionId || actionLoading || !orderedItems.length) {
      return;
    }
    setActionLoading('ordered');
    try {
      const { code, data } = await sortPlanningOrderedPlanApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        selectedOrderedSortField
      );
      if (code === 0) {
        message.success('方案顺序已排序');
        setSortModalOpen(false);
        if (data) {
          setPlanningState(prev => ({
            ...(prev || {}),
            ...data,
            orderedPlanState: data.orderedPlanState || prev?.orderedPlanState,
          }));
        } else {
          await fetchWorkspaceState();
        }
      } else {
        message.error('方案排序失败');
      }
    } catch (error) {
      message.error('方案排序异常，请稍后重试');
    }
    setActionLoading(null);
  };

  useEffect(() => {
    if (!routerParams.tenantId || !routerParams.chatSessionId) {
      return;
    }
    fetchWorkspaceState();
    fetchCandidateFilterOptions();
  }, [routerParams.tenantId, routerParams.chatSessionId, fetchFlag]);

  useEffect(() => {
    initialFiltersAppliedRef.current = false;
    candidateViewStateHydratedRef.current = false;
    lastSavedCandidateViewStateRef.current = '';
    initialPlanRequestedRef.current = false;
    orderedCollapseInitializedRef.current = false;
    previousOrderedCollapseKeysRef.current = [];
    candidateQueryInFlightPagesRef.current.clear();
    candidateItemCacheRef.current = {};
    setCandidateCacheVersion(version => version + 1);
    setPlanningState(null);
    setCandidatePoolResult({
      items: [],
      page: 1,
      pageSize: 24,
      total: 0,
      totalUnitCount: 0,
      loadedEntryCount: 0,
      loadedUnitCount: 0,
    });
    setCandidateFilterOptions({
      ...EMPTY_CANDIDATE_FILTER_OPTIONS,
    });
    setFilters(createDefaultFilters());
    setFilterSearchKeyword('');
    setFilterPanelOpen(false);
    setCollapsedOrderedGroupKeys([]);
    setFocusVolunteerIds([]);
    setExpandedSchoolMetaKeys([]);
    setDraftExpanded(false);
  }, [routerParams.chatSessionId, fetchFlag]);

  useEffect(() => {
    ensureInitialPlanReady();
  }, [planningState?.sessionId, draftItems.length, orderedItems.length]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const storedView = window.sessionStorage.getItem(
      getWorkspaceViewStorageKey(routerParams.chatSessionId)
    );
    if (storedView === 'candidate' || storedView === 'ordered') {
      setActiveView(storedView);
      return;
    }
    setActiveView('ordered');
  }, [routerParams.chatSessionId]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.sessionStorage.setItem(
      getWorkspaceViewStorageKey(routerParams.chatSessionId),
      activeView
    );
  }, [activeView, routerParams.chatSessionId]);

  useEffect(() => {
    if (activeView === 'candidate') {
      refreshCandidatePool(false);
    }
    workspaceBodyRef.current?.scrollTo({ top: 0 });
    setShowBackTop(false);
  }, [activeView]);

  useEffect(() => {
    if (!routerParams.tenantId || !routerParams.chatSessionId) {
      return;
    }
    const candidatePoolReady = Boolean(
      planningState?.candidatePoolState?.summary?.unitTotal ||
        planningState?.candidatePoolState?.summary?.total ||
        (candidatePoolResult.items || []).length
    );
    if (!candidatePoolReady || hasLoadedFilterOptions) {
      return;
    }
    fetchCandidateFilterOptions();
  }, [
    routerParams.tenantId,
    routerParams.chatSessionId,
    planningState?.candidatePoolState?.summary?.unitTotal,
    planningState?.candidatePoolState?.summary?.total,
    candidatePoolResult.items?.length,
    hasLoadedFilterOptions,
  ]);

  useEffect(() => {
    if (!planningState || initialFiltersAppliedRef.current) {
      return;
    }
    const candidateViewState = planningState.candidateViewState;
    setFilters(prev => ({
      ...prev,
      tier: (candidateViewState?.filters?.tiers?.[0] as CandidateTier) || '',
      provinceNames: uniqueStrings(candidateViewState?.filters?.provinceNames || []),
      negativeProvinceNames: uniqueStrings(candidateViewState?.filters?.negativeProvinceNames || []),
      cityNames: uniqueStrings(candidateViewState?.filters?.cityNames || []),
      negativeCityNames: uniqueStrings(candidateViewState?.filters?.negativeCityNames || []),
      schoolKeywords: uniqueStrings(candidateViewState?.filters?.schoolKeywords || []),
      negativeSchoolKeywords: uniqueStrings(candidateViewState?.filters?.negativeSchoolKeywords || []),
      majorKeywords: uniqueStrings(candidateViewState?.filters?.majorKeywords || []),
      negativeMajorKeywords: uniqueStrings(candidateViewState?.filters?.negativeMajorKeywords || []),
      schoolTags: uniqueStrings(candidateViewState?.filters?.schoolTags || []),
      negativeSchoolTags: uniqueStrings(candidateViewState?.filters?.negativeSchoolTags || []),
      majorTags: uniqueStrings(candidateViewState?.filters?.majorTags || []),
      negativeMajorTags: uniqueStrings(candidateViewState?.filters?.negativeMajorTags || []),
      expertPreferredOnly: Boolean(candidateViewState?.expertPreferredOnly),
      sortField: (candidateViewState?.sort?.field as CandidateSortField) || 'finalScore',
      sortOrder: candidateViewState?.sort?.order || 'desc',
    }));
    initialFiltersAppliedRef.current = true;
    candidateViewStateHydratedRef.current = true;
    lastSavedCandidateViewStateRef.current = JSON.stringify(candidateViewState || {});
  }, [planningState?.sessionId, planningState?.candidateViewState]);

  useEffect(() => {
    if (!planningState?.sessionId || !candidateViewStateHydratedRef.current) {
      return undefined;
    }
    const payload = buildCandidateViewStatePayload();
    const payloadText = JSON.stringify(payload);
    if (payloadText === lastSavedCandidateViewStateRef.current) {
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      try {
        const { code } = await updatePlanningCandidateViewStateApi(
          routerParams.tenantId,
          routerParams.chatSessionId,
          payload
        );
        if (code === 0) {
          lastSavedCandidateViewStateRef.current = payloadText;
        }
      } catch (error) {
        // Candidate filter persistence should not interrupt interaction.
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [
    planningState?.sessionId,
    routerParams.tenantId,
    routerParams.chatSessionId,
    filters.tier,
    filters.provinceNames,
    filters.negativeProvinceNames,
    filters.cityNames,
    filters.negativeCityNames,
    filters.schoolKeywords,
    filters.negativeSchoolKeywords,
    filters.majorKeywords,
    filters.negativeMajorKeywords,
    filters.schoolTags,
    filters.negativeSchoolTags,
    filters.majorTags,
    filters.negativeMajorTags,
    filters.expertPreferredOnly,
    filters.sortField,
    filters.sortOrder,
  ]);

  useEffect(() => {
    if (activeView !== 'candidate') {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      queryCandidatePool(1, false);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [
    activeView,
    filters.tier,
    filters.provinceNames,
    filters.negativeProvinceNames,
    filters.cityNames,
    filters.negativeCityNames,
    filters.schoolKeywords,
    filters.negativeSchoolKeywords,
    filters.majorKeywords,
    filters.negativeMajorKeywords,
    filters.schoolTags,
    filters.negativeSchoolTags,
    filters.majorTags,
    filters.negativeMajorTags,
    filters.sortField,
    filters.sortOrder,
  ]);

  useEffect(() => {
    const container = workspaceBodyRef.current;
    if (!container) {
      return;
    }
    const handleScroll = () => {
      const shouldShow = container.scrollTop > 240;
      setShowBackTop(prev => (prev === shouldShow ? prev : shouldShow));
      if (container.scrollTop > 48) {
        overviewRevealReadyRef.current = false;
        if (overviewRevealReadyTimerRef.current) {
          window.clearTimeout(overviewRevealReadyTimerRef.current);
          overviewRevealReadyTimerRef.current = null;
        }
        setOverviewCollapsed(prev => (prev ? prev : true));
        return;
      }
      if (container.scrollTop <= 0 && overviewCollapsed && !overviewRevealReadyTimerRef.current) {
        overviewRevealReadyTimerRef.current = window.setTimeout(() => {
          overviewRevealReadyRef.current = true;
          overviewRevealReadyTimerRef.current = null;
        }, 220);
      }
    };
    const handleWheel = (event: WheelEvent) => {
      if (container.scrollTop <= 0 && event.deltaY < -8 && overviewRevealReadyRef.current) {
        setOverviewCollapsed(false);
        overviewRevealReadyRef.current = false;
      }
    };
    const handleTouchStart = (event: TouchEvent) => {
      workspaceTouchStartYRef.current = event.touches[0]?.clientY ?? null;
      workspaceTouchStartAtTopRef.current = container.scrollTop <= 0 && overviewCollapsed;
    };
    const handleTouchMove = (event: TouchEvent) => {
      const startY = workspaceTouchStartYRef.current;
      const currentY = event.touches[0]?.clientY;
      if (startY === null || currentY === undefined) {
        return;
      }
      if (workspaceTouchStartAtTopRef.current && container.scrollTop <= 0 && currentY - startY > 48) {
        setOverviewCollapsed(false);
        workspaceTouchStartAtTopRef.current = false;
      }
    };
    handleScroll();
    container.addEventListener('scroll', handleScroll);
    container.addEventListener('wheel', handleWheel, { passive: true });
    container.addEventListener('touchstart', handleTouchStart, { passive: true });
    container.addEventListener('touchmove', handleTouchMove, { passive: true });
    return () => {
      container.removeEventListener('scroll', handleScroll);
      container.removeEventListener('wheel', handleWheel);
      container.removeEventListener('touchstart', handleTouchStart);
      container.removeEventListener('touchmove', handleTouchMove);
      if (overviewRevealReadyTimerRef.current) {
        window.clearTimeout(overviewRevealReadyTimerRef.current);
        overviewRevealReadyTimerRef.current = null;
      }
    };
  }, [activeView, overviewCollapsed]);

  useEffect(() => {
    if (activeView !== 'candidate') {
      return;
    }
    const container = workspaceBodyRef.current;
    if (!container) {
      return;
    }
    const handleScroll = () => {
      if (candidatePoolLoading) {
        return;
      }
      const currentPage = candidatePoolResult.page || 1;
      if (currentPage >= candidateTotalPages) {
        return;
      }
      const distanceToBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      if (distanceToBottom > 180) {
        return;
      }
      queryCandidatePool(currentPage + 1, true);
    };
    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, [activeView, candidatePoolLoading, candidatePoolResult.page, candidateTotalPages]);

  useEffect(() => {
    if (!workspaceIntent) {
      return;
    }
    const nextView = workspaceIntent.targetView === 'ordered' ? 'ordered' : 'candidate';
    if (nextView === 'ordered') {
      setActiveView('ordered');
    } else {
      setActiveView('candidate');
      if (workspaceIntent.candidateFilters) {
        setFilters(prev => ({
          ...prev,
          tier: (workspaceIntent.candidateFilters?.tiers?.[0] as CandidateTier) || '',
          provinceNames: workspaceIntent.candidateFilters?.provinceNames || [],
          negativeProvinceNames: workspaceIntent.candidateFilters?.negativeProvinceNames || [],
          cityNames: workspaceIntent.candidateFilters?.cityNames || [],
          negativeCityNames: workspaceIntent.candidateFilters?.negativeCityNames || [],
          schoolKeywords: workspaceIntent.candidateFilters?.schoolKeywords || [],
          negativeSchoolKeywords: workspaceIntent.candidateFilters?.negativeSchoolKeywords || [],
          majorKeywords: workspaceIntent.candidateFilters?.majorKeywords || [],
          negativeMajorKeywords: workspaceIntent.candidateFilters?.negativeMajorKeywords || [],
          schoolTags: workspaceIntent.candidateFilters?.schoolTags || [],
          negativeSchoolTags: workspaceIntent.candidateFilters?.negativeSchoolTags || [],
          majorTags: workspaceIntent.candidateFilters?.majorTags || [],
          negativeMajorTags: workspaceIntent.candidateFilters?.negativeMajorTags || [],
        }));
      }
      window.requestAnimationFrame(() => {
        candidateSummaryRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
    setFocusVolunteerIds(workspaceIntent.volunteerIds || []);
    if (workspaceIntent.refresh) {
      if (nextView === 'candidate') {
        refreshCandidatePool(false);
      }
    }
    onWorkspaceIntentConsumed?.();
  }, [workspaceIntent?.nonce]);

  useEffect(() => {
    if (!focusVolunteerIds.length) {
      return;
    }
    const targetVolunteerId = focusVolunteerIds[0];
    const nextAnimationFrame = window.requestAnimationFrame(() => {
      const targetElement =
        (activeView === 'ordered'
          ? orderedItemRefs.current[targetVolunteerId]
          : candidateItemRefs.current[targetVolunteerId]) ||
        draftItemRefs.current[targetVolunteerId];
      targetElement?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    });
    return () => window.cancelAnimationFrame(nextAnimationFrame);
  }, [activeView, draftExpanded, focusVolunteerIds, candidatePoolResult.items, orderedItems.length, draftItems.length]);

  useEffect(() => {
    if (!draftExpanded) {
      return undefined;
    }
    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node | null;
      if (!target) {
        return;
      }
      if (draftBasketRef.current?.contains(target)) {
        return;
      }
      setDraftExpanded(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('touchstart', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('touchstart', handlePointerDown);
    };
  }, [draftExpanded]);

  const actionableReviewChecks = reviewChecks.filter(
    check =>
      check.passed === false &&
      (check.level === 'risk' || check.level === 'warn')
  );
  const actionableReviewCheckCodes = new Set(
    actionableReviewChecks.map(check => check.code).filter(Boolean)
  );
  const actionablePendingActions = pendingActions.filter(
    action =>
      Boolean((action.summary || '').trim() || (action.detail || '').trim()) &&
      (!action.sourceCheckCode || !actionableReviewCheckCodes.has(action.sourceCheckCode))
  );
  const isReviewStale = workflowStatus?.reviewStatus === 'stale' || planningState?.staleFlags?.review === true;
  const hasActionableReviewChecks =
    !isReviewStale && (actionableReviewChecks.length > 0 || actionablePendingActions.length > 0);
  const getReviewCheckDisplayLabel = (check: PlanningReviewCheck) => {
    switch (check.code) {
      case 'safety_guard':
        return '保底不足';
      case 'probability_inversion':
        return '顺序倒挂';
      case 'probability_gap':
        return '梯度断层';
      case 'count_validation':
        return '数量不足';
      case 'unit_major_count_validation':
        return '组内数量待补';
      case 'high_tuition':
        return '高收费提醒';
      case 'admission_limit':
        return '限报提醒';
      case 'special_enrollment':
        return '特殊招生提醒';
      case 'edge_score':
        return '压线提醒';
      case 'cooperative_program':
        return '中外合作提醒';
      default:
        return check.summary || '待处理提醒';
    }
  };

  const getReviewTooltipText = (check: PlanningReviewCheck) => {
    return check.suggestedAction || check.detail || check.summary || '';
  };

  const getCandidateTargetHint = () => {
    if (!filters.tier) {
      if (!planningState?.candidatePoolState?.requiredCount) {
        return '';
      }
      return `目标总数 ${planningState.candidatePoolState.requiredCount}`;
    }
    const tierTargetCount = requiredTierCounts[filters.tier];
    if (!tierTargetCount) {
      return '';
    }
    return `${filters.tier}区建议 ${tierTargetCount}`;
  };

  const handleAttributeFilterChange = (values: string[]) => {
    const nextProvinceNames: string[] = [];
    const nextNegativeProvinceNames: string[] = [];
    const nextCityNames: string[] = [];
    const nextNegativeCityNames: string[] = [];
    const nextSchoolKeywords: string[] = [];
    const nextNegativeSchoolKeywords: string[] = [];
    const nextSchoolTags: string[] = [];
    const nextNegativeSchoolTags: string[] = [];
    const nextMajorKeywords: string[] = [];
    const nextNegativeMajorKeywords: string[] = [];
    const nextMajorTags: string[] = [];
    const nextNegativeMajorTags: string[] = [];
    let nextExpertPreferredOnly = false;

    values.forEach(token => {
      const parsed = parseFilterTokenValue(token);
      if (!parsed) {
        return;
      }
      if (parsed.field === 'provinceNames') {
        if (parsed.polarity === 'negative') {
          nextNegativeProvinceNames.push(parsed.value);
        } else {
          nextProvinceNames.push(parsed.value);
        }
        return;
      }
      if (parsed.field === 'cityNames') {
        if (parsed.polarity === 'negative') {
          nextNegativeCityNames.push(parsed.value);
        } else {
          nextCityNames.push(parsed.value);
        }
        return;
      }
      if (parsed.field === 'schoolKeywords') {
        if (parsed.polarity === 'negative') {
          nextNegativeSchoolKeywords.push(parsed.value);
        } else {
          nextSchoolKeywords.push(parsed.value);
        }
        return;
      }
      if (parsed.field === 'schoolTags') {
        if (parsed.polarity === 'negative') {
          nextNegativeSchoolTags.push(parsed.value);
        } else {
          nextSchoolTags.push(parsed.value);
        }
        return;
      }
      if (parsed.field === 'majorKeywords') {
        if (parsed.polarity === 'negative') {
          nextNegativeMajorKeywords.push(parsed.value);
        } else {
          nextMajorKeywords.push(parsed.value);
        }
        return;
      }
      if (parsed.field === 'majorTags') {
        if (parsed.polarity === 'negative') {
          nextNegativeMajorTags.push(parsed.value);
        } else {
          nextMajorTags.push(parsed.value);
        }
        return;
      }
      if (parsed.field === 'expertPreferredOnly' && parsed.value === '专家优选组合') {
        nextExpertPreferredOnly = true;
      }
    });

    setFilters(prev => ({
      ...prev,
      provinceNames: uniqueStrings(nextProvinceNames),
      negativeProvinceNames: uniqueStrings(nextNegativeProvinceNames),
      cityNames: uniqueStrings(nextCityNames),
      negativeCityNames: uniqueStrings(nextNegativeCityNames),
      schoolKeywords: uniqueStrings(nextSchoolKeywords),
      negativeSchoolKeywords: uniqueStrings(nextNegativeSchoolKeywords),
      schoolTags: uniqueStrings(nextSchoolTags),
      negativeSchoolTags: uniqueStrings(nextNegativeSchoolTags),
      majorKeywords: uniqueStrings(nextMajorKeywords),
      negativeMajorKeywords: uniqueStrings(nextNegativeMajorKeywords),
      majorTags: uniqueStrings(nextMajorTags),
      negativeMajorTags: uniqueStrings(nextNegativeMajorTags),
      expertPreferredOnly: nextExpertPreferredOnly,
    }));
  };

  const isAttributeFilterActive = (
    field: FilterTokenField,
    polarity: FilterTokenPolarity,
    value: string
  ) => {
    const token = buildFilterTokenValue(field, polarity, value);
    return selectedAttributeFilterTokens.includes(token);
  };

  const toggleAttributeFilterOption = (
    field: FilterTokenField,
    polarity: FilterTokenPolarity,
    value: string
  ) => {
    const positiveToken = buildFilterTokenValue(field, 'positive', value);
    const negativeToken = buildFilterTokenValue(field, 'negative', value);
    const currentToken = buildFilterTokenValue(field, polarity, value);
    const nextValues = selectedAttributeFilterTokens.filter(
      token => token !== positiveToken && token !== negativeToken
    );
    if (!selectedAttributeFilterTokens.includes(currentToken)) {
      nextValues.push(currentToken);
    }
    handleAttributeFilterChange(nextValues);
  };

  const removeActiveFilterChip = (chip: ActiveFilterChip) => {
    setFilters(prev => {
      const removeValue = (values: string[]) => values.filter(value => value !== chip.value);
      if (chip.field === 'expertPreferredOnly') {
        return {
          ...prev,
          expertPreferredOnly: false,
        };
      }
      if (chip.field === 'provinceNames') {
        return {
          ...prev,
          provinceNames:
            chip.polarity === 'positive' ? removeValue(prev.provinceNames) : prev.provinceNames,
          negativeProvinceNames:
            chip.polarity === 'negative'
              ? removeValue(prev.negativeProvinceNames)
              : prev.negativeProvinceNames,
        };
      }
      if (chip.field === 'cityNames') {
        return {
          ...prev,
          cityNames: chip.polarity === 'positive' ? removeValue(prev.cityNames) : prev.cityNames,
          negativeCityNames:
            chip.polarity === 'negative'
              ? removeValue(prev.negativeCityNames)
              : prev.negativeCityNames,
        };
      }
      if (chip.field === 'schoolKeyword') {
        return {
          ...prev,
          schoolKeywords:
            chip.polarity === 'positive' ? removeValue(prev.schoolKeywords) : prev.schoolKeywords,
          negativeSchoolKeywords:
            chip.polarity === 'negative'
              ? removeValue(prev.negativeSchoolKeywords)
              : prev.negativeSchoolKeywords,
        };
      }
      if (chip.field === 'majorKeyword') {
        return {
          ...prev,
          majorKeywords: chip.polarity === 'positive' ? removeValue(prev.majorKeywords) : prev.majorKeywords,
          negativeMajorKeywords:
            chip.polarity === 'negative'
              ? removeValue(prev.negativeMajorKeywords)
              : prev.negativeMajorKeywords,
        };
      }
      if (chip.field === 'schoolTags') {
        return {
          ...prev,
          schoolTags: chip.polarity === 'positive' ? removeValue(prev.schoolTags) : prev.schoolTags,
          negativeSchoolTags:
            chip.polarity === 'negative'
              ? removeValue(prev.negativeSchoolTags)
              : prev.negativeSchoolTags,
        };
      }
      if (chip.field === 'majorTags') {
        return {
          ...prev,
          majorTags: chip.polarity === 'positive' ? removeValue(prev.majorTags) : prev.majorTags,
          negativeMajorTags:
            chip.polarity === 'negative'
              ? removeValue(prev.negativeMajorTags)
              : prev.negativeMajorTags,
        };
      }
      return prev;
    });
  };

  const renderReviewAlertTooltip = (
    checks: PlanningReviewCheck[],
    actions: NonNullable<PlanningStateRes['pendingActions']>
  ) => {
    if (!checks.length && !actions.length) {
      return <div className={style.reviewTooltipEmpty}>当前没有需要关注的问题</div>;
    }
    return (
      <div className={style.reviewTooltipList}>
        {checks.slice(0, 8).map((check, index) => (
          <div key={`${check.code || check.summary || 'review'}-${index}`} className={style.reviewTooltipItem}>
            <div className={style.reviewTooltipItemTitle}>{getReviewCheckDisplayLabel(check)}</div>
            <div className={style.reviewTooltipItemDetail}>
              {getReviewTooltipText(check) || check.summary || '请留意当前方案中的对应问题'}
            </div>
          </div>
        ))}
        {actions.slice(0, Math.max(0, 8 - checks.length)).map((action, index) => (
          <div key={`${action.type || action.summary || 'pending'}-${index}`} className={style.reviewTooltipItem}>
            <div className={style.reviewTooltipItemTitle}>{action.summary || '待处理建议'}</div>
            <div className={style.reviewTooltipItemDetail}>
              {action.detail || '可结合当前方案情况继续查看或确认是否处理'}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const orderedToolbarHint = orderedItems.some(item => item.orderedBy === 'user')
    ? '你已手动调整过方案，继续上移、下移或固定志愿来优化。'
    : '当前顺序是系统初排结果，你可以上移、下移、固定或删除来调整。';

  const renderMajorName = (majorName?: string) => {
    const trimmed = (majorName || '').trim();
    if (!trimmed) {
      return <span className={style.majorNameMain}>未知专业</span>;
    }
    const firstParenIndex = trimmed.indexOf('(');
    const hasExtra = firstParenIndex > -1;
    const mainName = (hasExtra ? trimmed.slice(0, firstParenIndex) : trimmed).trim();
    const extra = hasExtra ? trimmed.slice(firstParenIndex).trim() : '';
    return (
      <span className={style.majorName}>
        <span className={style.majorNameMain}>{mainName}</span>
        {extra ? <span className={style.majorNameExtra}>{extra}</span> : null}
      </span>
    );
  };

  const formatPercent = (value?: number | null) => {
    if (value === null || value === undefined || value < 0) {
      return '-';
    }
    return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
  };

  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined || value < 0) {
      return '-';
    }
    return Number.isInteger(value) ? value : value.toFixed(1);
  };

  const formatMetricNumber = (value?: number | null, suffix: string = '') => {
    const formatted = formatNumber(value);
    return formatted === '-' ? '-' : `${formatted}${suffix}`;
  };

  const renderHistoryScores = (
    scores?: Array<{
      year?: number;
      score?: number | null;
      pos?: number | null;
    }>
  ) => {
    if (!scores?.length) {
      return null;
    }
    return scores
      .filter(item => item?.year)
      .sort((left, right) => Number(right.year || 0) - Number(left.year || 0))
      .slice(0, 4)
      .map(item => (
        <div key={`${item.year}-${item.score}-${item.pos}`} className={style.historyScoreChip}>
          <span className={style.historyYear}>{item.year}</span>
          <span className={style.historyValue}>最低分 {item.score && item.score > 0 ? item.score : '-'}</span>
          <span className={style.historyValue}>位次 {item.pos && item.pos > 0 ? item.pos : '-'}</span>
        </div>
      ));
  };

  const renderOrderedMajorTable = (
    majorName: React.ReactNode,
    candidateItem: PlanningCandidateItem | null | undefined,
    rowKey: string,
    actions: React.ReactNode
  ) => {
    const historyYears = getFixedHistoryYears(candidateItem?.majorHistoryScores || [], 3);
    const hasHistory = historyYears.some(Boolean);
    return (
      <div className={style.orderedMajorTableCard}>
        <div className={style.majorTable}>
          <div className={style.orderedMajorTableHeader}>
            <div className={style.majorNameColumn}>专业</div>
            <div className={style.majorPlanColumn}>{planYearTitle}</div>
            <div className={style.majorDataTypeColumn}>数据类型</div>
            {historyYears.map((year, yearIndex) => (
              <div key={`${rowKey}-ordered-year-${year || yearIndex}`} className={style.majorYearColumn}>
                {year || '-'}
              </div>
            ))}
            <div className={style.majorRatioColumn}>操作</div>
          </div>
          <div className={style.orderedMajorTableBody}>
            <div className={style.majorInfoCell} style={{ gridColumn: '1', gridRow: '1 / span 3' }}>
              <div className={style.majorLine}>{majorName}</div>
              <div className={style.orderedMajorPrimaryTags}>
                <Tag bordered={false} color="orange">
                  专业录取率 {formatPercent(candidateItem?.admissionRatio)}
                </Tag>
              </div>
            </div>
            <div className={style.majorPlanCell} style={{ gridColumn: '2', gridRow: '1 / span 3' }}>
              <div>计划数：{formatNumber(candidateItem?.planNum)}</div>
              <div>学制：{candidateItem?.duration || '-'}</div>
              <div>学费：{formatMetricNumber(candidateItem?.tuitionPerYear, '/年')}</div>
              {candidateItem?.mustSubjects?.length ? (
                <div>选科：{candidateItem.mustSubjects.join(' / ')}</div>
              ) : null}
            </div>
            {[
              { label: '录取人数', field: 'enrollNum' as const, row: 1 },
              { label: '最低分数', field: 'score' as const, row: 2 },
              { label: '最低位次', field: 'pos' as const, row: 3 },
            ].map(row => (
              <React.Fragment key={`${rowKey}-ordered-${row.label}`}>
                <div className={style.majorHistoryTypeCell} style={{ gridColumn: '3', gridRow: `${row.row}` }}>
                  {row.label}
                </div>
                {historyYears.map((year, yearIndex) => (
                  <div
                    key={`${rowKey}-ordered-${row.label}-${year || yearIndex}`}
                    className={style.majorHistoryValueCell}
                    style={{ gridColumn: `${4 + yearIndex}`, gridRow: `${row.row}` }}
                  >
                    {hasHistory && year ? getHistoryValue(candidateItem?.majorHistoryScores || [], year, row.field) : '-'}
                  </div>
                ))}
              </React.Fragment>
            ))}
            <div className={style.orderedMajorActionCell} style={{ gridColumn: '7', gridRow: '1 / span 3' }}>
              {actions}
            </div>
          </div>
        </div>
        <div className={style.majorActionBar}>
          <div className={style.cardMetrics}>
            <span>推荐系数 {formatNumber(candidateItem?.finalScore)}</span>
            <span>区间位次 #{formatNumber(candidateItem?.rankInTier)}</span>
            <span>专业热度 {formatNumber(candidateItem?.hotIndex)}</span>
            <Tooltip title={SALARY_AVG_TOOLTIP}>
              <span>薪酬指数 {formatNumber(candidateItem?.salaryAvg)}</span>
            </Tooltip>
            <span>专业代码 {candidateItem?.majorCode || '-'}</span>
          </div>
        </div>
        <div className={style.mobileMajorCard}>
          <div className={style.mobileMajorTop}>
            <div className={style.mobileMajorTitle}>{majorName}</div>
            <div className={style.orderedMobileActions}>{actions}</div>
          </div>
          <div className={style.mobileMajorInfoGrid}>
            <div>
              <span>计划数</span>
              <strong>{formatNumber(candidateItem?.planNum)}</strong>
            </div>
            <div>
              <span>学制</span>
              <strong>{candidateItem?.duration || '-'}</strong>
            </div>
            <div>
              <span>学费</span>
              <strong>{formatMetricNumber(candidateItem?.tuitionPerYear, '/年')}</strong>
            </div>
            <div>
              <span>专业代码</span>
              <strong>{candidateItem?.majorCode || '-'}</strong>
            </div>
          </div>
          {candidateItem?.mustSubjects?.length ? (
            <div className={style.mobileMajorSubject}>
              选科：{candidateItem.mustSubjects.join(' / ')}
            </div>
          ) : null}
          {historyYears.length > 0 ? (
            <div className={style.mobileHistoryList}>
              {historyYears.map((year, yearIndex) => (
                <div
                  key={`${rowKey}-ordered-mobile-history-${year || yearIndex}`}
                  className={style.mobileHistoryItem}
                >
                  <div className={style.mobileHistoryYear}>{year || '-'}</div>
                  <div>人数 {year ? getHistoryValue(candidateItem?.majorHistoryScores || [], year, 'enrollNum') : '-'}</div>
                  <div>分数 {year ? getHistoryValue(candidateItem?.majorHistoryScores || [], year, 'score') : '-'}</div>
                  <div>位次 {year ? getHistoryValue(candidateItem?.majorHistoryScores || [], year, 'pos') : '-'}</div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    );
  };

  const getHistoryYears = (scores?: Array<{ year?: number }>) => {
    return Array.from(
      new Set((scores || []).map(item => item?.year).filter(Boolean) as number[])
    ).sort((left, right) => right - left);
  };

  const getFixedHistoryYears = (scores?: Array<{ year?: number }>, count: number = 3) => {
    const years = getHistoryYears(scores).slice(0, count);
    while (years.length < count) {
      years.push(0);
    }
    return years;
  };

  const getHistoryValue = (
    scores: NonNullable<PlanningCandidateItem['majorHistoryScores']>,
    year: number,
    field: 'enrollNum' | 'score' | 'pos'
  ) => {
    const target = scores.find(item => item.year === year);
    if (!target) {
      return '-';
    }
    const value = target[field];
    return value === null || value === undefined || value <= 0 ? '-' : value;
  };

  const getTierClassName = (tier?: string) => {
    if (tier === '冲') return style.tierSprint;
    if (tier === '稳') return style.tierSafe;
    if (tier === '保') return style.tierProtect;
    return '';
  };

  const normalizeTierLabel = (tier?: string) => {
    if (tier === '冲' || tier === '稳' || tier === '保') {
      return tier;
    }
    const normalized = (tier || '').toLowerCase();
    if (normalized.includes('sprint')) return '冲';
    if (normalized.includes('safe')) return '稳';
    if (normalized.includes('protect')) return '保';
    return '';
  };

  const getMajorTierLabel = (item: PlanningCandidateItem) => {
    return normalizeTierLabel(item.majorTier || item.majorLevel || item.tier);
  };

  const isMajorGroupMode = volunteerModel === 'majorGroup';

  const getGroupCountLabel = (count: number) => {
    return isMajorGroupMode ? `组内${count}` : `专业${count}`;
  };

  const getPlanSchoolRankTags = (tags?: string[]) => {
    return (tags || []).filter(tag => tag.includes('院校排名'));
  };

  const getSchoolMetaItems = (item?: PlanningCandidateItem | null) => {
    if (!item) {
      return [];
    }
    return (item.schoolBasicTags || []).length
      ? item.schoolBasicTags || []
      : [
          [item.provinceName, item.cityName].filter(Boolean).join('/'),
          item.schoolBatch,
          item.schoolNature,
          item.schoolCategory,
          item.schoolLevel,
        ].filter(Boolean);
  };

  const groupedOrderedList = useMemo<OrderedGroup[]>(() => {
    if (!isMajorGroupMode) {
      return [];
    }
    const orderedUnits = planningState?.orderedPlanState?.units || [];
    if (orderedUnits.length > 0) {
      const orderedItemByVolunteerId = new Map(
        orderedItems
          .filter(item => item.volunteerId)
          .map(item => [item.volunteerId as string, item])
      );
      const orderedItemByLegacyPrefix = new Map<string, PlanningOrderedItem>();
      orderedItems.forEach(item => {
        const prefix = getVolunteerLegacyPrefix(item.volunteerId);
        if (prefix && !orderedItemByLegacyPrefix.has(prefix)) {
          orderedItemByLegacyPrefix.set(prefix, item);
        }
      });

      return (orderedUnits as PlanningOrderedUnit[]).map((unit, unitIndex) => {
        const unitMajorItems = unit.majorItems || [];
        const groupKey = unit.unitId || unit.schoolName || `ordered-unit-${unitIndex}`;
        const entries = unitMajorItems.map((major, majorIndex) => {
          const candidateItem = resolveCandidateItemForPlan(
            major.volunteerId,
            unit.schoolName,
            major.majorName
          );
          const legacyPrefix = getVolunteerLegacyPrefix(major.volunteerId);
          const orderedItem =
            (major.volunteerId ? orderedItemByVolunteerId.get(major.volunteerId) : null) ||
            (legacyPrefix ? orderedItemByLegacyPrefix.get(legacyPrefix) : null) ||
            ({
              volunteerId: major.volunteerId || `${groupKey}-${majorIndex}`,
              tier: major.tier || unit.tier,
              schoolName: unit.schoolName || candidateItem?.schoolName,
              majorName: major.majorName || candidateItem?.majorName,
              source: unit.source,
            } as PlanningOrderedItem);
          const displayCandidate: PlanningCandidateItem = candidateItem || {
            volunteerId: major.volunteerId || orderedItem.volunteerId,
            tier: major.tier || orderedItem.tier || unit.tier,
            schoolName: unit.schoolName || orderedItem.schoolName,
            provinceName: unit.provinceName,
            cityName: unit.cityName,
            schoolEnrollRatio: unit.schoolEnrollRatio ?? unit.admissionRatio,
            majorId: major.majorId,
            majorName: major.majorName || orderedItem.majorName,
            majorCode: major.majorCode,
            admissionRatio: major.admissionRatio,
            finalScore: major.finalScore,
            intentScore: major.intentScore,
            preferred: major.preferred,
            tuitionPerYear: major.tuitionPerYear,
            rankInTier: major.rankInTier,
          };
          return {
            orderedItem,
            candidateItem: displayCandidate,
          };
        });
        const topCandidate = entries.find(entry => entry.candidateItem)?.candidateItem || null;
        const schoolEnrollRatio =
          unit.schoolEnrollRatio ??
          unit.admissionRatio ??
          topCandidate?.schoolEnrollRatio ??
          topCandidate?.admissionRatio;
        return {
          key: groupKey,
          tier: unit.tier || topCandidate?.tier || '',
          schoolName: unit.schoolName || topCandidate?.schoolName || '未知院校',
          provinceName: unit.provinceName || topCandidate?.provinceName,
          cityName: unit.cityName || topCandidate?.cityName,
          schoolBatch: topCandidate?.schoolBatch,
          schoolNature: topCandidate?.schoolNature,
          schoolCategory: topCandidate?.schoolCategory,
          schoolLevel: topCandidate?.schoolLevel,
          schoolEnrollRatio,
          schoolBasicTags: topCandidate?.schoolBasicTags || [],
          schoolRankTags: topCandidate?.schoolRankTags || [],
          schoolPopupTags: topCandidate?.schoolPopupTags || [],
          topScore: topCandidate?.finalScore ?? unit.finalScore,
          topItem: topCandidate,
          orderedItems: entries,
        };
      });
    }

    const grouped = new Map<string, OrderedGroup>();
    orderedItems.forEach(item => {
      const candidateItem = resolveCandidateItemForPlan(item.volunteerId, item.schoolName, item.majorName);
      const schoolName = candidateItem?.schoolName || item.schoolName || '未知院校';
      const key =
        candidateItem?.planSchoolDataId ||
        candidateItem?.schoolId ||
        getVolunteerLegacyPrefix(item.volunteerId) ||
        schoolName;
      const existing = grouped.get(key);
      if (existing) {
        existing.orderedItems.push({
          orderedItem: item,
          candidateItem,
        });
        return;
      }
      grouped.set(key, {
        key,
        tier: item.tier || candidateItem?.tier || '',
        schoolName,
        provinceName: candidateItem?.provinceName,
        cityName: candidateItem?.cityName,
        schoolBatch: candidateItem?.schoolBatch,
        schoolNature: candidateItem?.schoolNature,
        schoolCategory: candidateItem?.schoolCategory,
        schoolLevel: candidateItem?.schoolLevel,
        schoolEnrollRatio: candidateItem?.schoolEnrollRatio,
        schoolBasicTags: candidateItem?.schoolBasicTags || [],
        schoolRankTags: candidateItem?.schoolRankTags || [],
        schoolPopupTags: candidateItem?.schoolPopupTags || [],
        topScore: candidateItem?.finalScore,
        topItem: candidateItem,
        orderedItems: [
          {
            orderedItem: item,
            candidateItem,
          },
        ],
      });
    });
    return Array.from(grouped.values());
  }, [
    candidateItemMap,
    candidateLegacyPrefixMap,
    candidateSchoolMajorMap,
    isMajorGroupMode,
    orderedItems,
    planningState?.orderedPlanState?.units,
  ]);

  const orderedCollapseKeys = useMemo(() => {
    if (isMajorGroupMode) {
      return groupedOrderedList.map(group => group.key);
    }
    return orderedItems.map((item, index) => item.volunteerId || `${item.schoolName || 'ordered'}-${index}`);
  }, [groupedOrderedList, isMajorGroupMode, orderedItems]);

  const orderedCollapseSignature = orderedCollapseKeys.join('|');

  useEffect(() => {
    if (!orderedCollapseSignature) {
      setCollapsedOrderedGroupKeys([]);
      orderedCollapseInitializedRef.current = false;
      previousOrderedCollapseKeysRef.current = [];
      return;
    }
    const nextKeys = orderedCollapseSignature.split('|');
    const previousKeySet = new Set(previousOrderedCollapseKeysRef.current);
    const isFirstCollapseInit = !orderedCollapseInitializedRef.current;
    setCollapsedOrderedGroupKeys(prev => {
      if (isFirstCollapseInit) {
        return nextKeys.slice(1);
      }
      const nextKeySet = new Set(nextKeys);
      const preservedCollapsedKeys = prev.filter(key => nextKeySet.has(key));
      const newCollapsedKeys = nextKeys.filter(key => !previousKeySet.has(key));
      return Array.from(new Set([...preservedCollapsedKeys, ...newCollapsedKeys]));
    });
    orderedCollapseInitializedRef.current = true;
    previousOrderedCollapseKeysRef.current = nextKeys;
  }, [orderedCollapseSignature]);

  const groupedDraftList = useMemo<DraftGroup[]>(() => {
    if (!isMajorGroupMode) {
      return [];
    }

    const draftUnits = planningState?.draftPlanState?.units || [];
    if (draftUnits.length > 0) {
      return draftUnits.map((unit: PlanningDraftUnit, index) => ({
        key: unit.unitId || unit.schoolName || `draft-unit-${index}`,
        tier: unit.tier || '',
        schoolName: unit.schoolName || '未知院校',
        source: unit.source,
        items: (unit.majorItems || []).map(major => {
          const volunteerId = major.volunteerId;
          const draftItem =
            draftItems.find(item => item.volunteerId === volunteerId) || {
              volunteerId,
              tier: major.tier || unit.tier,
              schoolName: unit.schoolName,
              majorName: major.majorName,
              source: unit.source,
            };
          return {
            draftItem,
            candidateItem: resolveCandidateItemForPlan(
              volunteerId,
              unit.schoolName,
              major.majorName
            ),
          };
        }),
      }));
    }

    const grouped = new Map<string, DraftGroup>();
    draftItems.forEach((item, index) => {
      const candidateItem = resolveCandidateItemForPlan(
        item.volunteerId,
        item.schoolName,
        item.majorName
      );
      const key =
        candidateItem?.planSchoolDataId ||
        candidateItem?.schoolId ||
        item.volunteerId?.split('_')[0] ||
        item.schoolName ||
        `draft-fallback-${index}`;
      const existing = grouped.get(key);
      if (existing) {
        existing.items.push({ draftItem: item, candidateItem });
        return;
      }
      grouped.set(key, {
        key,
        tier: item.tier || candidateItem?.tier || '',
        schoolName: candidateItem?.schoolName || item.schoolName || '未知院校',
        source: item.source,
        items: [{ draftItem: item, candidateItem }],
      });
    });
    return Array.from(grouped.values());
  }, [
    candidateItemMap,
    candidateLegacyPrefixMap,
    candidateSchoolMajorMap,
    draftItems,
    isMajorGroupMode,
    planningState?.draftPlanState?.units,
  ]);

  const basketDraftGroups = useMemo<DraftGroup[]>(() => {
    if (!isMajorGroupMode) {
      return [];
    }
    if (orderedItems.length <= 0) {
      return groupedDraftList;
    }
    return groupedOrderedList.map(group => ({
      key: group.key,
      tier: group.tier,
      schoolName: group.schoolName,
      source: group.orderedItems.find(entry => entry.orderedItem.source)?.orderedItem.source,
      items: group.orderedItems.map(entry => ({
        draftItem: {
          volunteerId: entry.orderedItem.volunteerId,
          tier: entry.orderedItem.tier,
          schoolName: entry.orderedItem.schoolName,
          majorName: entry.orderedItem.majorName,
          source: entry.orderedItem.source,
        },
        candidateItem: entry.candidateItem,
      })),
    }));
  }, [groupedDraftList, groupedOrderedList, isMajorGroupMode, orderedItems.length]);
  const basketItems = orderedItems.length > 0 ? orderedItems : draftItems;

  const candidatePoolUnitFallbackTotal = useMemo(() => {
    if (!isMajorGroupMode) {
      return cachedCandidateItems.length || (candidatePoolResult.items || []).length || 0;
    }
    return new Set(
      cachedCandidateItems.map(item =>
        item.planSchoolDataId || item.schoolId || item.schoolName || item.volunteerId || ''
      )
    ).size;
  }, [cachedCandidateItems, candidatePoolResult.items?.length, isMajorGroupMode]);

  const candidateUnitTierFallbackCounts = useMemo(() => {
    if (!isMajorGroupMode) {
      return summary?.tierCounts ?? {};
    }
    const tierUnitMap = new Map<string, Set<string>>();
    cachedCandidateItems.forEach(item => {
      const tier = item.tier || '';
      const unitId = item.planSchoolDataId || item.schoolId || item.schoolName || item.volunteerId || '';
      if (!tier || !unitId) {
        return;
      }
      if (!tierUnitMap.has(tier)) {
        tierUnitMap.set(tier, new Set());
      }
      tierUnitMap.get(tier)?.add(unitId);
    });
    return {
      冲: tierUnitMap.get('冲')?.size || 0,
      稳: tierUnitMap.get('稳')?.size || 0,
      保: tierUnitMap.get('保')?.size || 0,
    };
  }, [cachedCandidateItems, isMajorGroupMode, summary?.tierCounts]);

  const firstPositiveNumber = (...values: Array<number | undefined | null>) => {
    const matched = values.find(value => typeof value === 'number' && value > 0);
    return matched || 0;
  };
  const candidateUnitTotal = firstPositiveNumber(
    isMajorGroupMode ? summary?.unitTotal : summary?.total,
    summary?.unitTotal,
    candidatePoolResult.totalUnitCount,
    candidatePoolResult.total,
    candidatePoolUnitFallbackTotal
  );
  const candidateUnitTierCounts =
    Object.values(summary?.unitTierCounts || {}).some(value => value > 0)
      ? summary?.unitTierCounts
      : Object.values(summary?.tierCounts || {}).some(value => value > 0)
        ? summary?.tierCounts
        : candidateUnitTierFallbackCounts;
  const candidateGroupedDisplayTotal = isMajorGroupMode ? groupedCandidateList.length : candidatePoolResult.total || 0;
  const orderedDisplayTotal = firstPositiveNumber(
    isMajorGroupMode ? orderedSummary?.unitTotal : orderedSummary?.total,
    orderedSummary?.unitTotal,
    orderedSummary?.total,
    isMajorGroupMode ? groupedOrderedList.length : orderedItems.length
  );
  const orderedTargetTotal = firstPositiveNumber(orderedSummary?.targetUnitCount, orderedSummary?.targetCount);
  const draftDisplayTotal = firstPositiveNumber(
    isMajorGroupMode ? draftSummary?.unitTotal : draftSummary?.total,
    draftSummary?.unitTotal,
    draftSummary?.total,
    isMajorGroupMode ? groupedDraftList.length : draftItems.length
  );
  const draftTierCounts = draftSummary?.unitTierCounts ?? draftSummary?.tierCounts ?? {};
  const planDisplayTotal = orderedDisplayTotal || draftDisplayTotal;
  const planTargetTotal =
    orderedTargetTotal ||
    draftSummary?.targetUnitCount ||
    draftSummary?.targetCount ||
    planningState?.candidatePoolState?.requiredUnitCount ||
    planningState?.candidatePoolState?.requiredCount ||
    0;
  const planTierCounts =
    Object.values(orderedSummary?.unitTierCounts || {}).some(value => value > 0)
      ? orderedSummary?.unitTierCounts
      : Object.values(orderedSummary?.tierCounts || {}).some(value => value > 0)
        ? orderedSummary?.tierCounts
        : draftTierCounts;
  const candidateFilteredUnitTotal = candidatePoolResult.totalUnitCount ?? candidateGroupedDisplayTotal ?? 0;
  const candidateLoadedDisplayTotal = isMajorGroupMode
    ? groupedCandidateList.length
    : Math.min(candidatePoolResult.items?.length || 0, candidatePoolResult.total || 0);
  const candidateLoadedEntryTotal = candidatePoolResult.items?.length || 0;
  const reviewPassedRuleCount = reviewSummary?.passedRuleCount ?? reviewSummary?.passedCount ?? 0;
  const reviewTotalRuleCount = reviewSummary?.totalRuleCount ?? reviewSummary?.total ?? 0;
  const reviewRiskRuleCount = reviewSummary?.riskRuleCount ?? reviewSummary?.riskCount ?? 0;
  const reviewWarnRuleCount = reviewSummary?.warnRuleCount ?? reviewSummary?.warnCount ?? 0;
  const reviewOverviewLabel =
    workflowStatus?.reviewStatus === 'has_risk'
      ? '有风险，请查看方案'
      : workflowStatus?.reviewStatus === 'has_warning'
        ? '有提醒，请查看方案'
        : workflowStatus?.reviewStatus === 'stale'
          ? '待重新审查'
          : workflowStatus?.reviewStatus === 'passed'
            ? '通过'
            : workflowStatus?.reviewStatus === 'failed'
              ? '失败'
              : '未审查';
  const candidateDetailMessages = [
    planningState?.candidatePoolState?.statusMessage,
    ...candidateRiskHints,
  ].filter(Boolean);
  const candidateLowCountTooltip =
    workflowStatus?.candidateStatus === 'low_count' && candidateDetailMessages.length
      ? candidateDetailMessages.join('；')
      : '';
  const candidateEmptyDescription =
    workflowStatus?.candidateStatus === 'empty'
      ? candidateDetailMessages.join('；') || '当前条件下没有可用志愿候选'
      : activeFilterChips.length > 0 && candidateFilteredUnitTotal === 0
        ? '当前筛选结果为空'
      : '暂无候选志愿';

  const getOrderedItemStatusLabel = (item: PlanningOrderedItem) => {
    if (item.pinned) {
      return '已固定';
    }
    if (item.orderReason === 'append_new_draft') {
      return '新增';
    }
    if (item.orderedBy === 'user') {
      return '已调整';
    }
    return '';
  };

  const toggleSchoolMeta = (groupKey: string) => {
    setExpandedSchoolMetaKeys(prev =>
      prev.includes(groupKey) ? prev.filter(item => item !== groupKey) : [...prev, groupKey]
    );
  };

  const toggleOrderedGroupCollapsed = (groupKey: string) => {
    setCollapsedOrderedGroupKeys(prev =>
      prev.includes(groupKey) ? prev.filter(item => item !== groupKey) : [...prev, groupKey]
    );
  };

  const openSchoolHistoryModal = (group: CandidateGroup) => {
    setSchoolHistoryModal({
      schoolName: group.schoolName,
      basicTags: group.topItem.schoolBasicTags || [],
      rankTags: group.topItem.schoolRankTags || [],
      popupTags: group.topItem.schoolPopupTags || [],
      scores: group.topItem.schoolHistoryScores || [],
    });
  };

  const buildMajorTags = (item: PlanningCandidateItem) => {
    return (item.majorRankTags || [])
      .filter((tag, index, source) => Boolean(tag) && source.indexOf(tag) === index)
      .slice(0, 6);
  };

  const renderFilterPanelOptionRows = (groupKey: string, options: FilterPanelOption[] = []) => (
    <div className={style.filterPanelGroupList}>
      {options.map(option => {
        const positiveActive = isAttributeFilterActive(option.field, 'positive', option.value);
        const negativeActive = isAttributeFilterActive(option.field, 'negative', option.value);
        return (
          <div key={`${groupKey}-${option.value}`} className={style.filterPanelRow}>
            <span className={style.filterPanelRowLabel}>{option.label}</span>
            <div className={style.filterPanelRowActions}>
              <button
                type="button"
                className={`${style.filterPanelAction} ${
                  positiveActive ? style.filterPanelActionActive : ''
                }`}
                onClick={() => toggleAttributeFilterOption(option.field, 'positive', option.value)}
              >
                筛选
              </button>
              <button
                type="button"
                className={`${style.filterPanelAction} ${
                  negativeActive ? style.filterPanelActionExclude : ''
                }`}
                onClick={() => toggleAttributeFilterOption(option.field, 'negative', option.value)}
              >
                排除
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );

  const renderFilterPanelTitleActions = (option?: FilterPanelOption) => {
    if (!option) {
      return null;
    }
    const positiveActive = isAttributeFilterActive(option.field, 'positive', option.value);
    const negativeActive = isAttributeFilterActive(option.field, 'negative', option.value);
    return (
      <div className={style.filterPanelTitleActions}>
        <button
          type="button"
          className={`${style.filterPanelAction} ${positiveActive ? style.filterPanelActionActive : ''}`}
          onClick={() => toggleAttributeFilterOption(option.field, 'positive', option.value)}
        >
          筛选
        </button>
        <button
          type="button"
          className={`${style.filterPanelAction} ${negativeActive ? style.filterPanelActionExclude : ''}`}
          onClick={() => toggleAttributeFilterOption(option.field, 'negative', option.value)}
        >
          排除
        </button>
      </div>
    );
  };

  const renderFilterPanelGroup = (group: FilterPanelGroup, depth = 0, parentKey = ''): React.ReactNode => {
    const groupKey = `${parentKey}-${group.label}`;
    const hasChildren = Boolean(group.children?.length);
    const hasOptions = Boolean(group.options?.length);
    const hasExpandableContent = hasChildren || hasOptions;
    const autoExpanded = Boolean(filterSearchKeyword.trim());
    const expanded = autoExpanded || expandedFilterGroupKeys.includes(groupKey);
    const titleClassName = `${depth === 0 ? style.filterPanelGroupTitle : style.filterPanelSubGroupTitle} ${
      hasExpandableContent ? style.filterPanelGroupToggle : ''
    } ${group.option ? style.filterPanelActionableTitle : ''}`;
    return (
      <div
        key={groupKey}
        className={`${depth === 0 ? style.filterPanelGroup : style.filterPanelSubGroup} ${
          depth > 1 ? style.filterPanelNestedGroup : ''
        }`}
      >
        <div className={titleClassName}>
          <button
            type="button"
            className={style.filterPanelTitleButton}
            onClick={() => {
              if (!hasExpandableContent || autoExpanded) {
                return;
              }
              setExpandedFilterGroupKeys(prev =>
                prev.includes(groupKey) ? prev.filter(key => key !== groupKey) : [...prev, groupKey]
              );
            }}
          >
            {group.label}
            {hasExpandableContent && !autoExpanded && (
              <DownOutlined className={`${style.filterPanelGroupToggleIcon} ${expanded ? style.filterPanelGroupToggleIconOpen : ''}`} />
            )}
          </button>
          {renderFilterPanelTitleActions(group.option)}
        </div>
        {group.options && group.options.length > 0 && expanded && renderFilterPanelOptionRows(groupKey, group.options)}
        {expanded && group.children?.map(child => renderFilterPanelGroup(child, depth + 1, groupKey))}
      </div>
    );
  };

  const handleBackToTop = () => {
    workspaceBodyRef.current?.scrollTo({
      top: 0,
      behavior: 'smooth',
    });
  };

  const renderSchoolHistoryModal = () => {
    if (!schoolHistoryModal) {
      return null;
    }
    const years = getHistoryYears(schoolHistoryModal.scores);
    const rows = [
      { label: '录取人数', field: 'enrollNum' as const },
      { label: '最低分数', field: 'score' as const },
      { label: '最低位次', field: 'pos' as const },
    ];
    return (
      <Modal
        width={760}
        title="历年录取分数线"
        open
        footer={null}
        onCancel={() => setSchoolHistoryModal(null)}
      >
        <div className={style.historyModalTitle}>{schoolHistoryModal.schoolName}</div>
        <div className={style.historyModalTags}>
          {[...schoolHistoryModal.rankTags, ...schoolHistoryModal.popupTags].map(tag => (
            <Tag key={`modal-tag-${tag}`} color="volcano">
              {tag}
            </Tag>
          ))}
        </div>
        <div className={style.historyModalBasicTags}>
          {schoolHistoryModal.basicTags.join(' / ')}
        </div>
        <div className={style.historyModalTable}>
          <div
            className={style.historyModalTableGrid}
            style={{ gridTemplateColumns: `120px repeat(${years.length}, minmax(80px, 1fr))` }}
          >
            <div className={style.historyModalHeaderCell}>数据类型</div>
            {years.map(year => (
              <div key={`modal-year-${year}`} className={style.historyModalHeaderCell}>
                {year}
              </div>
            ))}
            {rows.map(row => (
              <React.Fragment key={`modal-row-${row.label}`}>
                <div className={style.historyModalLabelCell}>{row.label}</div>
                {years.map(year => (
                  <div key={`modal-${row.label}-${year}`} className={style.historyModalValueCell}>
                    {getHistoryValue(schoolHistoryModal.scores, year, row.field)}
                  </div>
                ))}
              </React.Fragment>
            ))}
          </div>
        </div>
      </Modal>
    );
  };

  return (
    <div className={style.workspacePanel}>
      <div className={`${style.stageHeader} ${overviewCollapsed ? style.stageHeaderCollapsed : ''}`}>
        <div className={`${style.metricsGrid} ${overviewCollapsed ? style.metricsGridCollapsed : ''}`}>
          <div className={style.metricCard}>
            <div className={style.metricValue}>{candidateUnitTotal}</div>
            <div className={style.metricLabel}>候选</div>
            <div className={style.metricMeta}>
              冲{candidateUnitTierCounts?.['冲'] || 0} / 稳{candidateUnitTierCounts?.['稳'] || 0} / 保
              {candidateUnitTierCounts?.['保'] || 0}
            </div>
          </div>
          <div className={`${style.metricCard} ${style.metricCardAccent}`}>
            <div className={style.metricValue}>
              {planTargetTotal ? `${planDisplayTotal}/${planTargetTotal}` : planDisplayTotal}
            </div>
            <div className={style.metricLabel}>方案</div>
            <div className={style.metricMeta}>
              冲{planTierCounts?.['冲'] || 0} / 稳{planTierCounts?.['稳'] || 0} / 保
              {planTierCounts?.['保'] || 0}
            </div>
          </div>
          <div className={style.metricCard}>
            <div className={style.metricValue}>
              {reviewSummary ? `${reviewPassedRuleCount}/${reviewTotalRuleCount}` : '0/0'}
            </div>
            <div className={style.metricLabel}>审查</div>
            <div className={style.metricMeta}>{reviewOverviewLabel}</div>
          </div>
        </div>

        {isLegacySubmittedPlan && !overviewCollapsed && (
          <div className={style.legacySubmittedNotice}>
            历史已提交方案，建议只读查看；如需调整，请先复制或重新生成方案。
          </div>
        )}

        <div className={style.stageToolbar}>
          <div className={style.viewTabs}>
            <button
              type="button"
              className={`${style.viewTab} ${activeView === 'ordered' ? style.viewTabActive : ''}`}
              onClick={() => setActiveView('ordered')}
            >
              方案
            </button>
            <button
              type="button"
              className={`${style.viewTab} ${activeView === 'candidate' ? style.viewTabActive : ''}`}
              onClick={() => setActiveView('candidate')}
            >
              候选
            </button>
          </div>
        </div>
      </div>

      <div className={style.workspaceBody} ref={workspaceBodyRef}>
        <Spin spinning={planningLoading}>
          {activeView === 'candidate' ? (
            <div className={style.candidateView}>
              <div className={style.filtersRow}>
                <div className={style.tierTabs}>
                  {TIER_OPTIONS.map(option => (
                    <button
                      key={option.value || 'all'}
                      type="button"
                      className={`${style.tierTab} ${
                        filters.tier === option.value ? style.tierTabActive : ''
                      }`}
                      onClick={() => setFilters(prev => ({ ...prev, tier: option.value }))}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <Dropdown
                  trigger={['click']}
                  open={filterPanelOpen}
                  onOpenChange={open => setFilterPanelOpen(open)}
                  dropdownRender={() => (
                    <div className={style.filterPanelDropdown}>
                      <div className={style.filterPanelSearchRow}>
                        <input
                          className={style.filterPanelSearchInput}
                          value={filterSearchKeyword}
                          onChange={event => setFilterSearchKeyword(event.target.value)}
                          placeholder="搜索标签"
                        />
                        <button
                          type="button"
                          className={style.filterPanelClearButton}
                          onClick={() => {
                            resetCandidateFilters();
                            setFilterSearchKeyword('');
                          }}
                        >
                          清空
                        </button>
                      </div>
                      <div className={style.filterPanelBody}>
                        {filteredAttributeFilterOptions.length > 0 ? (
                          filteredAttributeFilterOptions.map(group => renderFilterPanelGroup(group))
                        ) : (
                          <div className={style.filterPanelEmpty}>暂无匹配标签</div>
                        )}
                      </div>
                    </div>
                  )}
                >
                  <button type="button" className={style.tagFilterInput}>
                    <span className={style.tagFilterInputText}>{attributeFilterTriggerText}</span>
                    <DownOutlined className={style.tagFilterInputIcon} />
                  </button>
                </Dropdown>
                <Dropdown
                  menu={{
                    items: SORT_FIELD_OPTIONS.map(option => ({
                      key: option.value,
                      label: option.label,
                    })),
                    onClick: ({ key }) =>
                      setFilters(prev => ({
                        ...prev,
                        sortField: key as CandidateSortField,
                      })),
                    selectable: true,
                    selectedKeys: [filters.sortField],
                  }}
                  trigger={['click']}
                >
                  <Button
                    className={style.sortTrigger}
                    icon={<FilterOutlined />}
                    title="排序字段"
                  >
                    {SORT_FIELD_OPTIONS.find(option => option.value === filters.sortField)?.label}
                  </Button>
                </Dropdown>
                <button
                  type="button"
                  className={style.sortOrderButton}
                  onClick={() =>
                    setFilters(prev => ({
                      ...prev,
                      sortOrder: prev.sortOrder === 'asc' ? 'desc' : 'asc',
                    }))
                  }
                  title={filters.sortOrder === 'asc' ? '当前升序' : '当前降序'}
                >
                  <span
                    className={`${style.sortArrow} ${
                      filters.sortOrder === 'asc' ? style.sortArrowActive : style.sortArrowMuted
                    }`}
                  >
                    <ArrowUpOutlined />
                  </span>
                  <span
                    className={`${style.sortArrow} ${
                      filters.sortOrder === 'desc' ? style.sortArrowActive : style.sortArrowMuted
                    }`}
                  >
                    <ArrowDownOutlined />
                  </span>
                </button>
              </div>

              {activeFilterChips.length > 0 ? (
                <div className={style.activeFilterChips}>
                  {activeFilterChips.map(chip => (
                    <span
                      key={chip.key}
                      className={`${style.activeFilterChip} ${
                        chip.polarity === 'negative' ? style.activeFilterChipNegative : ''
                      }`}
                    >
                      <span className={style.activeFilterChipText}>{chip.label}</span>
                      <button
                        type="button"
                        className={style.activeFilterChipRemove}
                        onClick={() => removeActiveFilterChip(chip)}
                        aria-label={`移除${chip.label}`}
                      >
                        x
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}

              <div className={style.candidateList}>
                <Spin spinning={candidatePoolLoading}>
                  <div className={style.candidateSummaryBar} ref={candidateSummaryRef}>
                    <span>
                      {isMajorGroupMode ? `总候选专业组 ${candidateUnitTotal}` : `总候选单元 ${candidateUnitTotal}`}
                    </span>
                    <span>
                      {isMajorGroupMode
                        ? `当前筛选专业组 ${candidateFilteredUnitTotal}`
                        : `当前筛选结果 ${candidatePoolResult.total || 0}`}
                    </span>
                    <span>
                      {isMajorGroupMode
                        ? `已加载专业组 ${candidateLoadedDisplayTotal}`
                        : `已加载 ${candidateLoadedDisplayTotal}/${candidatePoolResult.total || 0}`}
                    </span>
                    {!isMajorGroupMode ? <span>{`已加载条目 ${candidateLoadedEntryTotal}`}</span> : null}
                    {getCandidateTargetHint() ? <span>{getCandidateTargetHint()}</span> : null}
                    {candidateLowCountTooltip ? (
                      <Tooltip title={candidateLowCountTooltip}>
                        <Tag color="warning">候选不足</Tag>
                      </Tooltip>
                    ) : null}
                  </div>
                  {groupedCandidateList.length > 0 ? (
                    groupedCandidateList.map((group, groupIndex) => {
                      const groupSelected = group.items.some(item => isCandidateSelected(item));
                      return (
                      <div key={group.key} className={style.candidateTierSection}>
                        <Collapse
                          ghost
                          defaultActiveKey={[]}
                          className={style.candidateCollapse}
                        >
                          <Panel
                            key={group.key}
                            header={
                              <div className={style.candidateGroupHeader}>
                                <div className={style.candidateGroupMain}>
                                  {(() => {
                                    const schoolMetaExpanded = expandedSchoolMetaKeys.includes(group.key);
                                    const inlineMetaItems = (group.topItem.schoolBasicTags || []).length
                                      ? group.topItem.schoolBasicTags || []
                                      : [
                                          [group.provinceName, group.cityName].filter(Boolean).join('/'),
                                          group.topItem.schoolBatch,
                                          group.topItem.schoolNature,
                                          group.topItem.schoolCategory,
                                          group.topItem.schoolLevel,
                                        ].filter(Boolean);
                                    const expandedMetaItems = [
                                      group.topItem.baoyanRatio && group.topItem.baoyanRatio > 0
                                        ? `保研率 ${formatPercent(group.topItem.baoyanRatio)}`
                                        : '',
                                      group.topItem.upgradeRatio && group.topItem.upgradeRatio > 0
                                        ? `升学率 ${formatPercent(group.topItem.upgradeRatio)}`
                                        : '',
                                      group.topItem.masterCount && group.topItem.masterCount > 0
                                        ? `硕士点 ${formatNumber(group.topItem.masterCount)}`
                                        : '',
                                      group.topItem.doctorCount && group.topItem.doctorCount > 0
                                        ? `博士点 ${formatNumber(group.topItem.doctorCount)}`
                                        : '',
                                    ].filter(Boolean);
                                    return (
                                      <>
                                  <div className={`${style.cardTitleRow} ${style.groupTitleRow}`}>
                                    <div className={style.cardTitle}>
                                      {groupIndex + 1}、{group.schoolName}
                                    </div>
                                    {groupSelected ? (
                                      <Tag bordered={false} color="processing">
                                        已选择
                                      </Tag>
                                    ) : null}
                                    {(group.topItem.schoolRankTags || []).map(tag => (
                                      <Tag bordered={false} color="volcano" key={`${group.key}-${tag}`}>
                                        {tag}
                                      </Tag>
                                    ))}
                                    {group.topItem.preferred ? (
                                      <Tag color="gold" bordered={false}>
                                        专家优选组合
                                      </Tag>
                                    ) : null}
                                  </div>
                                  <div className={style.cardSubtitle}>
                                    <div className={style.inlineMetaRow}>
                                      {inlineMetaItems.map(meta => (
                                        <span key={`${group.key}-${meta}`} className={style.inlineMetaItem}>
                                          {meta}
                                        </span>
                                      ))}
                                      {expandedMetaItems.length > 0 ? (
                                        <button
                                          type="button"
                                          className={style.groupMetaToggle}
                                          onClick={event => {
                                            event.stopPropagation();
                                            toggleSchoolMeta(group.key);
                                          }}
                                          aria-label={schoolMetaExpanded ? '收起附加信息' : '展开附加信息'}
                                        >
                                          <span className={style.ellipsisTrigger}>...</span>
                                          <DownOutlined
                                            className={`${style.groupMetaToggleIcon} ${
                                              schoolMetaExpanded ? style.groupMetaToggleIconExpanded : ''
                                            }`}
                                          />
                                        </button>
                                      ) : null}
                                    </div>
                                  </div>
                                  {schoolMetaExpanded && expandedMetaItems.length > 0 ? (
                                    <div className={style.groupMetaDetailRow}>
                                      {expandedMetaItems.map(meta => (
                                        <span key={`${group.key}-extra-${meta}`}>{meta}</span>
                                      ))}
                                    </div>
                                  ) : null}
                                  {group.topItem.schoolHistoryScores?.length ? (
                                    <button
                                      type="button"
                                      className={style.historyLink}
                                      onClick={event => {
                                        event.stopPropagation();
                                        openSchoolHistoryModal(group);
                                      }}
                                    >
                                      历年录取分数线
                                    </button>
                                  ) : null}
                                      </>
                                    );
                                  })()}
                                </div>
                                <div className={`${style.candidateGroupScore} ${getTierClassName(group.tier)}`}>
                                  <div className={style.candidateGroupScoreValue}>
                                    {formatPercent(group.schoolEnrollRatio)}
                                  </div>
                                  <div className={style.candidateGroupScoreTier}>
                                    {normalizeTierLabel(group.tier)}
                                  </div>
                                  <div className={style.candidateGroupScoreMeta}>
                                    {getGroupCountLabel(group.items.length)}
                                  </div>
                                </div>
                              </div>
                            }
                            showArrow
                          >
                            <div className={style.groupMajorList}>
                              {group.items.map(item => {
                                const isSelected = isCandidateSelected(item);
                                const isFocused = item.volunteerId
                                  ? focusVolunteerIds.includes(item.volunteerId)
                                  : false;
                                const historyYears = getFixedHistoryYears(item.majorHistoryScores, 3);
                                return (
                                  <div
                                    key={item.volunteerId}
                                    ref={element => {
                                      if (item.volunteerId) {
                                        candidateItemRefs.current[item.volunteerId] = element;
                                      }
                                    }}
                                    className={`${style.majorTableCard} ${isFocused ? style.focusedCard : ''}`}
                                  >
                                    <div className={style.majorTable}>
                                      <div className={style.majorTableHeader}>
                                        <div className={style.majorNameColumn}>专业</div>
                                        <div className={style.majorPlanColumn}>{planYearTitle}</div>
                                        <div className={style.majorDataTypeColumn}>数据类型</div>
                                        {historyYears.map((year, yearIndex) => (
                                          <div
                                            key={`${item.volunteerId}-year-${year || yearIndex}`}
                                            className={style.majorYearColumn}
                                          >
                                            {year || '-'}
                                          </div>
                                        ))}
                                        <div className={style.majorRatioColumn}>录取率</div>
                                      </div>
                                      <div className={style.majorTableBody}>
                                        <div
                                          className={style.majorInfoCell}
                                          style={{ gridColumn: '1', gridRow: '1 / span 3' }}
                                        >
                                          <div className={style.majorLine}>
                                            {renderMajorName(item.majorName)}
                                          </div>
                                          <div className={style.reasonTags}>
                                            {isSelected ? (
                                              <Tag bordered={false} color="processing">
                                                已选择
                                              </Tag>
                                            ) : null}
                                            {buildMajorTags(item)
                                              .filter(Boolean)
                                              .map(reason => (
                                                <Tag key={`${item.volunteerId}-${reason}`}>{reason}</Tag>
                                              ))}
                                          </div>
                                        </div>
                                        <div
                                          className={style.majorPlanCell}
                                          style={{ gridColumn: '2', gridRow: '1 / span 3' }}
                                        >
                                          <div>计划数：{formatNumber(item.planNum)}</div>
                                          <div>学制：{item.duration || '-'}</div>
                                          <div>学费：{formatMetricNumber(item.tuitionPerYear, '/年')}</div>
                                          {item.mustSubjects?.length ? (
                                            <div>选科：{item.mustSubjects.join(' / ')}</div>
                                          ) : null}
                                        </div>
                                        {[
                                          { label: '录取人数', field: 'enrollNum' as const, row: 1 },
                                          { label: '最低分数', field: 'score' as const, row: 2 },
                                          { label: '最低位次', field: 'pos' as const, row: 3 },
                                        ].map(row => (
                                          <React.Fragment key={`${item.volunteerId}-${row.label}`}>
                                            <div
                                              className={style.majorHistoryTypeCell}
                                              style={{ gridColumn: '3', gridRow: `${row.row}` }}
                                            >
                                              {row.label}
                                            </div>
                                            {historyYears.map((year, yearIndex) => (
                                              <div
                                                key={`${item.volunteerId}-${row.label}-${year || yearIndex}`}
                                                className={style.majorHistoryValueCell}
                                                style={{ gridColumn: `${4 + yearIndex}`, gridRow: `${row.row}` }}
                                              >
                                                {year
                                                  ? getHistoryValue(item.majorHistoryScores || [], year, row.field)
                                                  : '-'}
                                              </div>
                                            ))}
                                          </React.Fragment>
                                        ))}
                                        <div
                                          className={style.majorRatioCell}
                                          style={{ gridColumn: '7', gridRow: '1 / span 3' }}
                                        >
                                          <div className={`${style.majorRatioBadge} ${getTierClassName(getMajorTierLabel(item))}`}>
                                            <span>{formatPercent(item.admissionRatio) || '--'}</span>
                                            <span>{getMajorTierLabel(item)}</span>
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                    <div className={style.mobileMajorCard}>
                                      <div className={style.mobileMajorTop}>
                                        <div className={style.mobileMajorTitle}>
                                          {renderMajorName(item.majorName)}
                                        </div>
                                        <div className={`${style.majorRatioBadge} ${getTierClassName(getMajorTierLabel(item))}`}>
                                          <span>{formatPercent(item.admissionRatio) || '--'}</span>
                                          <span>{getMajorTierLabel(item)}</span>
                                        </div>
                                      </div>
                                      <div className={style.reasonTags}>
                                        {isSelected ? (
                                          <Tag bordered={false} color="processing">
                                            已选择
                                          </Tag>
                                        ) : null}
                                        {buildMajorTags(item)
                                          .filter(Boolean)
                                          .map(reason => (
                                            <Tag key={`${item.volunteerId}-mobile-${reason}`}>{reason}</Tag>
                                          ))}
                                      </div>
                                      <div className={style.mobileMajorInfoGrid}>
                                        <div>
                                          <span>计划数</span>
                                          <strong>{formatNumber(item.planNum)}</strong>
                                        </div>
                                        <div>
                                          <span>学制</span>
                                          <strong>{item.duration || '-'}</strong>
                                        </div>
                                        <div>
                                          <span>学费</span>
                                          <strong>{formatMetricNumber(item.tuitionPerYear, '/年')}</strong>
                                        </div>
                                        <div>
                                          <span>专业代码</span>
                                          <strong>{item.majorCode || '-'}</strong>
                                        </div>
                                      </div>
                                      {item.mustSubjects?.length ? (
                                        <div className={style.mobileMajorSubject}>
                                          选科：{item.mustSubjects.join(' / ')}
                                        </div>
                                      ) : null}
                                      {historyYears.length > 0 ? (
                                        <div className={style.mobileHistoryList}>
                                          {historyYears.map((year, yearIndex) => (
                                            <div
                                              key={`${item.volunteerId}-mobile-history-${year || yearIndex}`}
                                              className={style.mobileHistoryItem}
                                            >
                                              <div className={style.mobileHistoryYear}>{year || '-'}</div>
                                              <div>人数 {year ? getHistoryValue(item.majorHistoryScores || [], year, 'enrollNum') : '-'}</div>
                                              <div>分数 {year ? getHistoryValue(item.majorHistoryScores || [], year, 'score') : '-'}</div>
                                              <div>位次 {year ? getHistoryValue(item.majorHistoryScores || [], year, 'pos') : '-'}</div>
                                            </div>
                                          ))}
                                        </div>
                                      ) : null}
                                    </div>
                                    <div className={style.majorActionBar}>
                                      <div className={style.cardMetrics}>
                                        <span>推荐系数 {formatNumber(item.finalScore)}</span>
                                        <span>区间位次 #{formatNumber(item.rankInTier)}</span>
                                        <span>专业热度 {formatNumber(item.hotIndex)}</span>
                                        <Tooltip title={SALARY_AVG_TOOLTIP}>
                                          <span>薪酬指数 {formatNumber(item.salaryAvg)}</span>
                                        </Tooltip>
                                        <span>专业代码 {item.majorCode || '-'}</span>
                                      </div>
                                      <Button
                                        type={isSelected ? 'default' : 'primary'}
                                        icon={<PlusOutlined />}
                                        disabled={isSelected || !item.volunteerId}
                                        loading={actionLoading === 'draft' && !isSelected}
                                        onClick={() => handleAddCandidateToDraft(item.volunteerId)}
                                      >
                                        {isSelected ? '已加入方案' : '加入方案'}
                                      </Button>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </Panel>
                        </Collapse>
                      </div>
                      );
                    })
                  ) : (
                    <Empty description={candidateEmptyDescription} />
                  )}
                  {(candidatePoolResult.page || 1) < candidateTotalPages ? (
                    <div className={style.candidatePaginationHint}>
                      {candidatePoolLoading ? '加载中...' : '下滑继续加载更多候选'}
                    </div>
                  ) : null}
                </Spin>
              </div>
            </div>
          ) : (
            <div className={style.orderedView}>
              {(orderedItems || []).length > 0 ? (
                <>
                  <div className={style.reviewSummaryBar} ref={reviewSummaryRef}>
                    <div className={style.reviewSummaryMain}>
                      <span className={style.reviewSummaryHint}>{orderedToolbarHint}</span>
                    </div>
                    <div className={style.reviewSummaryAction}>
                      {hasActionableReviewChecks ? (
                        <Tooltip
                          placement="bottomRight"
                          title={renderReviewAlertTooltip(actionableReviewChecks, actionablePendingActions)}
                          overlayClassName={style.reviewTooltipOverlay}
                        >
                          <button
                            type="button"
                            className={style.reviewAlertButton}
                            aria-label="查看方案警示"
                          >
                            <ExclamationCircleOutlined />
                          </button>
                        </Tooltip>
                      ) : null}
                      <Button
                        className={style.reviewActionButton}
                        size="small"
                        icon={<SafetyCertificateOutlined />}
                        loading={actionLoading === 'review'}
                        onClick={handleRunReview}
                        disabled={!orderedItems.length}
                      >
                        审查
                      </Button>
                      <Button
                        className={style.reviewActionButton}
                        size="small"
                        icon={<SortAscendingOutlined />}
                        loading={actionLoading === 'ordered'}
                        onClick={() => setSortModalOpen(true)}
                        disabled={!orderedItems.length}
                      >
                        排序
                      </Button>
                      <Button
                        className={style.reviewActionButton}
                        size="small"
                        icon={<DownloadOutlined />}
                        loading={exportLoading}
                        onClick={handleExportOrderedPlan}
                        disabled={!orderedItems.length}
                      >
                        导出
                      </Button>
                    </div>
                  </div>
                  <div className={style.orderedList}>
                    {isMajorGroupMode
                      ? groupedOrderedList.map((group, groupIndex) => {
                          const groupFocused = group.orderedItems.some(entry =>
                            focusVolunteerIds.includes(entry.orderedItem.volunteerId || '')
                          );
                          const groupCollapsed = collapsedOrderedGroupKeys.includes(group.key);
                          const metaItems = getSchoolMetaItems(group.topItem);
                          return (
                            <div
                              key={group.key}
                              className={`${style.orderedCard} ${groupFocused ? style.focusedCard : ''}`}
                            >
                              <div
                                className={`${style.orderedMain} ${style.orderedGroupHeaderClickable}`}
                                onClick={() => toggleOrderedGroupCollapsed(group.key)}
                                role="button"
                                tabIndex={0}
                                onKeyDown={event => {
                                  if (event.key === 'Enter' || event.key === ' ') {
                                    event.preventDefault();
                                    toggleOrderedGroupCollapsed(group.key);
                                  }
                                }}
                                aria-expanded={!groupCollapsed}
                              >
                                <div className={style.positionBadge}>{groupIndex + 1}</div>
                                <div className={style.orderedContent}>
                                  <div className={`${style.cardTitleRow} ${style.groupTitleRow} ${style.orderedTitleRow}`}>
                                    <div className={style.cardTitle}>
                                      {groupIndex + 1}、{group.schoolName}
                                    </div>
                                    {getPlanSchoolRankTags(group.schoolRankTags).map(tag => (
                                      <Tag bordered={false} color="volcano" key={`${group.key}-${tag}`}>
                                        {tag}
                                      </Tag>
                                    ))}
                                    {group.schoolEnrollRatio !== undefined && group.schoolEnrollRatio !== null ? (
                                      <Tag bordered={false} color="orange" key={`${group.key}-school-enroll-ratio`}>
                                        录取率 {formatPercent(group.schoolEnrollRatio)}
                                      </Tag>
                                    ) : null}
                                  </div>
                                  {metaItems.length > 0 ? (
                                    <div className={style.cardSubtitle}>
                                      <div className={style.inlineMetaRow}>
                                        {metaItems.map(meta => (
                                          <span key={`${group.key}-${meta}`} className={style.inlineMetaItem}>
                                            {meta}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}
                                </div>
                                <div className={`${style.orderedActions} ${style.orderedGroupActions}`}>
                                  <Tooltip title="整组上移">
                                    <Button
                                      icon={<VerticalAlignTopOutlined />}
                                      loading={orderedActionVolunteerId === group.key && actionLoading === 'ordered'}
                                      disabled={groupIndex === 0 || (actionLoading === 'ordered' && orderedActionVolunteerId !== group.key)}
                                      onClick={event => {
                                        event.stopPropagation();
                                        handleMoveOrderedUnit(group, groupIndex, 'up');
                                      }}
                                    />
                                  </Tooltip>
                                  <Tooltip title="整组下移">
                                    <Button
                                      icon={<VerticalAlignBottomOutlined />}
                                      loading={orderedActionVolunteerId === group.key && actionLoading === 'ordered'}
                                      disabled={groupIndex === groupedOrderedList.length - 1 || (actionLoading === 'ordered' && orderedActionVolunteerId !== group.key)}
                                      onClick={event => {
                                        event.stopPropagation();
                                        handleMoveOrderedUnit(group, groupIndex, 'down');
                                      }}
                                    />
                                  </Tooltip>
                                  <Tooltip title="整组移动到指定位置">
                                    <Button
                                      icon={<SwapOutlined />}
                                      loading={orderedActionVolunteerId === group.key && actionLoading === 'ordered'}
                                      disabled={groupedOrderedList.length <= 1 || (actionLoading === 'ordered' && orderedActionVolunteerId !== group.key)}
                                      onClick={event => {
                                        event.stopPropagation();
                                        openOrderedUnitMoveModal(group, groupIndex);
                                      }}
                                    />
                                  </Tooltip>
                                  <Tooltip title="整组删除">
                                    <Button
                                      danger
                                      icon={<DeleteOutlined />}
                                      loading={orderedActionVolunteerId === group.key && actionLoading === 'ordered'}
                                      disabled={actionLoading === 'ordered' && orderedActionVolunteerId !== group.key}
                                      onClick={event => {
                                        event.stopPropagation();
                                        handleRemoveOrderedUnit(group);
                                      }}
                                    />
                                  </Tooltip>
                                </div>
                              </div>
                              {!groupCollapsed ? (
                                <div className={style.orderedGroupMajorList}>
                                  {group.orderedItems.map((entry, itemIndex) => {
                                  const item = entry.orderedItem;
                                  const candidateItem = entry.candidateItem;
                                  const itemFocused = focusVolunteerIds.includes(item.volunteerId || '');
                                  const absoluteIndex = orderedItems.findIndex(
                                    orderedEntry => orderedEntry.volunteerId === item.volunteerId
                                  );
                                  const itemActions = (
                                    <div className={style.orderedActions}>
                                      <Tooltip title="上移">
                                        <Button
                                          icon={<VerticalAlignTopOutlined />}
                                          loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                          disabled={absoluteIndex <= 0 || (actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId)}
                                          onClick={() => handleMoveOrderedItem(item, absoluteIndex, 'up')}
                                        />
                                      </Tooltip>
                                      <Tooltip title="下移">
                                        <Button
                                          icon={<VerticalAlignBottomOutlined />}
                                          loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                          disabled={absoluteIndex === orderedItems.length - 1 || (actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId)}
                                          onClick={() => handleMoveOrderedItem(item, absoluteIndex, 'down')}
                                        />
                                      </Tooltip>
                                      <Tooltip title="移动到指定位置">
                                        <Button
                                          icon={<SwapOutlined />}
                                          loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                          disabled={orderedItems.length <= 1 || (actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId)}
                                          onClick={() => openOrderedMoveModal(item, absoluteIndex)}
                                        />
                                      </Tooltip>
                                      <Tooltip title="删除">
                                        <Button
                                          danger
                                          icon={<DeleteOutlined />}
                                          loading={actionLoading === 'draft' || actionLoading === 'ordered'}
                                          onClick={() => handleRemoveDraftItem(item.volunteerId)}
                                        />
                                      </Tooltip>
                                    </div>
                                  );
                                  return (
                                    <div
                                      key={item.volunteerId}
                                      ref={element => {
                                        if (item.volunteerId) {
                                          orderedItemRefs.current[item.volunteerId] = element;
                                        }
                                      }}
                                      className={`${style.orderedMajorRow} ${
                                        itemFocused ? style.orderedMajorRowFocused : ''
                                      }`}
                                    >
                                      {renderOrderedMajorTable(
                                        (
                                          <>
                                            <span className={style.orderedMajorIndex}>#{itemIndex + 1}</span>
                                            {renderMajorName(item.majorName)}
                                          </>
                                        ),
                                        candidateItem,
                                        item.volunteerId || `${group.key}-${itemIndex}`,
                                        itemActions
                                      )}
                                    </div>
                                  );
                                  })}
                                </div>
                              ) : null}
                            </div>
                          );
                        })
                      : orderedItems.map((item, index) => {
                          const candidateItem = resolveCandidateItemForPlan(
                            item.volunteerId,
                            item.schoolName,
                            item.majorName
                          );
                          const itemKey = item.volunteerId || `${item.schoolName || 'ordered'}-${index}`;
                          const itemCollapsed = collapsedOrderedGroupKeys.includes(itemKey);
                          const metaItems = getSchoolMetaItems(candidateItem);
                          const itemActions = (
                            <div className={style.orderedActions}>
                              <Tooltip title="上移">
                                <Button
                                  icon={<VerticalAlignTopOutlined />}
                                  loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                  disabled={index === 0 || (actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId)}
                                  onClick={() => handleMoveOrderedItem(item, index, 'up')}
                                />
                              </Tooltip>
                              <Tooltip title="下移">
                                <Button
                                  icon={<VerticalAlignBottomOutlined />}
                                  loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                  disabled={index === orderedItems.length - 1 || (actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId)}
                                  onClick={() => handleMoveOrderedItem(item, index, 'down')}
                                />
                              </Tooltip>
                              <Tooltip title="移动到指定位置">
                                <Button
                                  icon={<SwapOutlined />}
                                  loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                  disabled={orderedItems.length <= 1 || (actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId)}
                                  onClick={() => openOrderedMoveModal(item, index)}
                                />
                              </Tooltip>
                              <Tooltip title="删除">
                                <Button
                                  danger
                                  icon={<DeleteOutlined />}
                                  loading={actionLoading === 'draft' || actionLoading === 'ordered'}
                                  onClick={() => handleRemoveDraftItem(item.volunteerId)}
                                />
                              </Tooltip>
                            </div>
                          );
                          return (
                            <div
                              key={itemKey}
                              ref={element => {
                                if (item.volunteerId) {
                                  orderedItemRefs.current[item.volunteerId] = element;
                                }
                              }}
                              className={`${style.orderedCard} ${
                                focusVolunteerIds.includes(item.volunteerId || '') ? style.focusedCard : ''
                              }`}
                            >
                              <div
                                className={`${style.orderedMain} ${style.orderedGroupHeaderClickable}`}
                                onClick={() => toggleOrderedGroupCollapsed(itemKey)}
                                role="button"
                                tabIndex={0}
                                onKeyDown={event => {
                                  if (event.key === 'Enter' || event.key === ' ') {
                                    event.preventDefault();
                                    toggleOrderedGroupCollapsed(itemKey);
                                  }
                                }}
                                aria-expanded={!itemCollapsed}
                              >
                                <div className={style.positionBadge}>{index + 1}</div>
                                <div className={style.orderedContent}>
                                  <div className={`${style.cardTitleRow} ${style.groupTitleRow} ${style.orderedTitleRow}`}>
                                    <div className={style.cardTitle}>
                                      {index + 1}、{item.schoolName}
                                    </div>
                                    {getPlanSchoolRankTags(candidateItem?.schoolRankTags).map(tag => (
                                      <Tag bordered={false} color="volcano" key={`${item.volunteerId}-${tag}`}>
                                        {tag}
                                      </Tag>
                                    ))}
                                    {candidateItem?.admissionRatio !== undefined && candidateItem?.admissionRatio !== null ? (
                                      <Tag bordered={false} color="orange" key={`${item.volunteerId}-admission-ratio`}>
                                        录取率 {formatPercent(candidateItem.admissionRatio)}
                                      </Tag>
                                    ) : null}
                                  </div>
                                  {metaItems.length > 0 ? (
                                    <div className={style.cardSubtitle}>
                                      <div className={style.inlineMetaRow}>
                                        {metaItems.map(meta => (
                                          <span key={`${itemKey}-${meta}`} className={style.inlineMetaItem}>
                                            {meta}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}
                                </div>
                                {itemCollapsed ? (
                                  <div className={style.orderedHeaderActions} onClick={event => event.stopPropagation()}>
                                    {itemActions}
                                  </div>
                                ) : null}
                              </div>
                              {!itemCollapsed ? (
                                <div className={style.orderedSingleMajorDetail}>
                                  {renderOrderedMajorTable(
                                    renderMajorName(item.majorName),
                                    candidateItem,
                                    itemKey,
                                    itemActions
                                  )}
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                  </div>
                </>
              ) : (
                <div className={style.emptyOrdered}>
                  <Empty
                    description="当前还没有方案，请先到候选中补充或等待系统生成"
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                  >
                    <Button type="primary" onClick={() => setActiveView('candidate')}>
                      去候选查看
                    </Button>
                  </Empty>
                </div>
              )}
            </div>
          )}
        </Spin>
      </div>
      {renderSchoolHistoryModal()}

      {showBackTop ? (
        <Button
          className={`${style.backTopButton} ${
            activeView === 'candidate' ? style.backTopButtonWithBasket : ''
          }`}
          type="primary"
          shape="circle"
          icon={<VerticalAlignTopOutlined />}
          aria-label="回到顶部"
          onClick={handleBackToTop}
        />
      ) : null}

      <Modal
        title="排序方案"
        open={sortModalOpen}
        okText="确认排序"
        cancelText="取消"
        confirmLoading={actionLoading === 'ordered'}
        onOk={handleSortOrderedPlan}
        onCancel={() => setSortModalOpen(false)}
      >
        <div className={style.sortModalBody}>
          <div className={style.sortModalHint}>
            排序会改变当前方案顺序，固定的志愿会保留在原位置，确认后仍可继续手动调整。
          </div>
          <div className={style.sortOptionList}>
            {ORDERED_SORT_OPTIONS.map(option => (
              <button
                key={option.value}
                type="button"
                className={`${style.sortOption} ${
                  selectedOrderedSortField === option.value ? style.sortOptionActive : ''
                }`}
                onClick={() => setSelectedOrderedSortField(option.value)}
              >
                <span className={style.sortOptionTitle}>{option.label}</span>
                <span className={style.sortOptionDesc}>{option.description}</span>
              </button>
            ))}
          </div>
        </div>
      </Modal>

      <Modal
        title="移动志愿"
        open={Boolean(orderedMoveModal)}
        okText="确认移动"
        cancelText="取消"
        confirmLoading={actionLoading === 'ordered'}
        onOk={() => handleMoveOrderedItemToTarget()}
        onCancel={closeOrderedMoveModal}
      >
        <div className={style.moveModalBody}>
          <div className={style.moveModalHint}>
            当前第 {orderedMoveModal?.currentPosition || '-'} 位，移动后会改变当前方案顺序，审查结果需要重新确认。
          </div>
          <div className={style.moveTargetRow}>
            <span>目标位置</span>
            <InputNumber
              min={1}
              max={Math.max(orderedItems.length, 1)}
              precision={0}
              value={orderedMoveTargetPosition}
              onChange={value => setOrderedMoveTargetPosition(Number(value || 1))}
            />
            <span>位</span>
          </div>
          <div className={style.moveQuickActions}>
            <Button
              disabled={actionLoading === 'ordered' || orderedMoveModal?.currentPosition === 1}
              type={orderedMoveTargetPosition === 1 ? 'primary' : 'default'}
              onClick={() => setOrderedMoveTargetPosition(1)}
            >
              移到顶部
            </Button>
            <Button
              disabled={actionLoading === 'ordered' || orderedMoveModal?.currentPosition === orderedItems.length}
              type={orderedMoveTargetPosition === orderedItems.length ? 'primary' : 'default'}
              onClick={() => setOrderedMoveTargetPosition(orderedItems.length)}
            >
              移到底部
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        title="移动专业组"
        open={Boolean(orderedUnitMoveModal)}
        okText="确认移动"
        cancelText="取消"
        confirmLoading={actionLoading === 'ordered'}
        onOk={() => handleMoveOrderedUnitToTarget()}
        onCancel={closeOrderedUnitMoveModal}
      >
        <div className={style.moveModalBody}>
          <div className={style.moveModalHint}>
            当前第 {orderedUnitMoveModal?.currentPosition || '-'} 组，移动后会改变当前方案顺序，审查结果需要重新确认。
          </div>
          <div className={style.moveTargetRow}>
            <span>目标位置</span>
            <InputNumber
              min={1}
              max={Math.max(groupedOrderedList.length, 1)}
              precision={0}
              value={orderedUnitMoveTargetPosition}
              onChange={value => setOrderedUnitMoveTargetPosition(Number(value || 1))}
            />
            <span>组</span>
          </div>
          <div className={style.moveQuickActions}>
            <Button
              disabled={actionLoading === 'ordered' || orderedUnitMoveModal?.currentPosition === 1}
              type={orderedUnitMoveTargetPosition === 1 ? 'primary' : 'default'}
              onClick={() => setOrderedUnitMoveTargetPosition(1)}
            >
              移到顶部
            </Button>
            <Button
              disabled={actionLoading === 'ordered' || orderedUnitMoveModal?.currentPosition === groupedOrderedList.length}
              type={orderedUnitMoveTargetPosition === groupedOrderedList.length ? 'primary' : 'default'}
              onClick={() => setOrderedUnitMoveTargetPosition(groupedOrderedList.length)}
            >
              移到底部
            </Button>
          </div>
        </div>
      </Modal>

      {activeView === 'candidate' ? (
        <div
          ref={draftBasketRef}
          className={`${style.draftBasket} ${draftExpanded ? style.draftBasketExpanded : ''}`}
        >
          <button
            className={style.draftToggle}
            type="button"
            onClick={() => setDraftExpanded(prev => !prev)}
          >
            方案 {planDisplayTotal}
          </button>
          {draftExpanded && (
            <div className={style.draftPanel}>
              <div className={style.draftHeader}>
                <span>当前方案</span>
                <div className={style.draftHeaderActions}>
                  <Button
                    type="text"
                    size="small"
                    className={style.draftHeaderCollapse}
                    icon={<ShrinkOutlined />}
                    onClick={() => setDraftExpanded(false)}
                  >
                    收起
                  </Button>
                </div>
              </div>
              <div className={style.draftList}>
                {basketItems.length > 0 ? (
                  isMajorGroupMode ? (
                    basketDraftGroups.map(group => (
                      <div key={group.key} className={style.draftGroup}>
                        <div className={style.draftGroupHeader}>
                          <div className={style.draftGroupHeaderMain}>
                            <Tag color={group.tier === '冲' ? 'red' : group.tier === '稳' ? 'gold' : 'green'}>
                              {group.tier}
                            </Tag>
                            <div className={style.draftText}>
                              <div className={style.draftSchool}>{group.schoolName}</div>
                              <div className={style.draftMajor}>{getGroupCountLabel(group.items.length)}</div>
                            </div>
                          </div>
                          <Tooltip title="整组删除">
                            <Button
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={() => handleRemoveDraftGroup(group)}
                            />
                          </Tooltip>
                        </div>
                        <div className={style.draftGroupItems}>
                          {group.items.map(({ draftItem }, itemIndex) => (
                          <div
                            key={draftItem.volunteerId || `${group.key}-${itemIndex}`}
                            ref={element => {
                              if (draftItem.volunteerId) {
                                draftItemRefs.current[draftItem.volunteerId] = element;
                              }
                            }}
                            className={`${style.draftGroupRow} ${
                              focusVolunteerIds.includes(draftItem.volunteerId || '') ? style.focusedCard : ''
                            }`}
                          >
                            <div className={style.draftGroupRowMain}>
                              <div className={style.draftText}>
                                <div className={style.draftMajor}>{draftItem.majorName}</div>
                              </div>
                            </div>
                            <div className={style.draftItemActions}>
                              <Tooltip title="删除">
                                <Button
                                  size="small"
                                  danger
                                  icon={<DeleteOutlined />}
                                  onClick={() => handleRemoveDraftItem(draftItem.volunteerId)}
                                />
                              </Tooltip>
                            </div>
                          </div>
                          ))}
                        </div>
                      </div>
                    ))
                  ) : (
                    basketItems.map(item => (
                      <div
                        key={item.volunteerId}
                        ref={element => {
                          if (item.volunteerId) {
                            draftItemRefs.current[item.volunteerId] = element;
                          }
                        }}
                        className={`${style.draftItem} ${
                          focusVolunteerIds.includes(item.volunteerId || '') ? style.focusedCard : ''
                        }`}
                      >
                        <div className={style.draftItemMain}>
                          <Tag color={item.tier === '冲' ? 'red' : item.tier === '稳' ? 'gold' : 'green'}>
                            {item.tier}
                          </Tag>
                          <div className={style.draftText}>
                            <div className={style.draftSchool}>{item.schoolName}</div>
                            <div className={style.draftMajor}>{item.majorName}</div>
                          </div>
                        </div>
                        <div className={style.draftItemActions}>
                          <Tooltip title="删除">
                            <Button
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={() => handleRemoveDraftItem(item.volunteerId)}
                            />
                          </Tooltip>
                        </div>
                      </div>
                    ))
                  )
                ) : (
                  <Empty description="方案为空" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                )}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
};

export default WorkspacePanel;
