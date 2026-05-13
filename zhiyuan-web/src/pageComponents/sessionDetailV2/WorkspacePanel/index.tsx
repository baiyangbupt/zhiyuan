import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Collapse, Dropdown, Empty, Modal, Spin, Tag, Tooltip, message } from 'antd';
import {
  PlusOutlined,
  PushpinOutlined,
  VerticalAlignTopOutlined,
  VerticalAlignBottomOutlined,
  DeleteOutlined,
  LockOutlined,
  UnlockOutlined,
  FilterOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
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
  lockPlanningDraftItemsApi,
  movePlanningOrderedItemApi,
  pinPlanningOrderedItemApi,
  queryPlanningCandidatePoolApi,
  removePlanningDraftItemsApi,
  runPlanningReviewApi,
  selectPlanningDraftItemsApi,
  sortPlanningOrderedPlanApi,
  unpinPlanningOrderedItemApi,
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
  locked: boolean;
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
  options?: FilterPanelOption[];
  children?: FilterPanelGroup[];
}

interface WorkspacePanelProps {
  routerParams: IUserInfoParams;
  fetchFlag: number;
  workspaceIntent?: PlanningWorkspaceIntent | null;
  onWorkspaceIntentConsumed?: () => void;
}

const getWorkspaceViewStorageKey = (chatSessionId?: string) =>
  `session_detail_v2_active_view_${chatSessionId || 'default'}`;

const EMPTY_CANDIDATE_FILTER_OPTIONS: PlanningCandidateFilterOptionsRes = {
  provinceNames: [],
  cityNames: [],
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
  if (!['provinceNames', 'cityNames', 'schoolTags', 'majorTags', 'majorKeywords', 'expertPreferredOnly'].includes(normalizedField)) {
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

const hasFilterPanelOptions = (group: FilterPanelGroup): boolean =>
  Boolean(group.options?.length || group.children?.some(hasFilterPanelOptions));

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
  const [candidatePoolLoading, setCandidatePoolLoading] = useState(false);
  const [candidateCacheVersion, setCandidateCacheVersion] = useState(0);
  const [showBackTop, setShowBackTop] = useState(false);
  const [sortModalOpen, setSortModalOpen] = useState(false);
  const [selectedOrderedSortField, setSelectedOrderedSortField] =
    useState<PlanningOrderedSortField>('admissionRatio');
  const candidateQueryInFlightPagesRef = useRef<Set<string>>(new Set());
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const [filterSearchKeyword, setFilterSearchKeyword] = useState('');
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
  const candidateItemCacheRef = useRef<Record<string, PlanningCandidateItem>>({});
  const initialFiltersAppliedRef = useRef(false);
  const candidateViewStateHydratedRef = useRef(false);
  const lastSavedCandidateViewStateRef = useRef('');
  const initialPlanRequestedRef = useRef(false);

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
  const draftIdSet = useMemo(
    () => new Set(draftItems.map(item => item.volunteerId).filter(Boolean)),
    [draftItems]
  );
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
            {
              groupName: '院校标签',
              filterField: 'schoolTags',
              values: (candidateFilterOptions.schoolTags || []).filter(
                tag => !isGeoLikeSchoolTag(tag, candidateFilterOptions.provinceNames || [], candidateFilterOptions.cityNames || [])
              ),
            },
            { groupCode: 'major.discipline', groupName: '专业门类', filterField: 'majorTags', values: fallbackMajorDisciplineValues },
            { groupCode: 'major.category', groupName: '专业大类', filterField: 'majorKeywords', values: fallbackMajorKeywordValues },
            { groupName: '专业标签', filterField: 'majorTags', values: candidateFilterOptions.majorTags || [] },
          ];

    const hasMajorCategoryGroup = backendGroups.some(group => group.groupCode === 'major.category');
    const hasMajorDisciplineGroup = backendGroups.some(group => group.groupCode === 'major.discipline');
    const normalizedGroups = [...backendGroups];
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
      if (!['provinceNames', 'cityNames', 'schoolTags', 'majorTags', 'majorKeywords'].includes(field)) {
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
    const usedCitySet = new Set<string>();
    const provinceChildren: FilterPanelGroup[] = provinceValues.map(province => {
      const cities = uniqueStrings(Array.from(provinceToCities.get(province) || []))
        .filter(city => cityValues.includes(city));
      cities.forEach(city => usedCitySet.add(city));
      return {
        label: province,
        options: [{
          label: '全省/市',
          title: `院校省份 · ${province}`,
          field: 'provinceNames' as FilterTokenField,
          value: province,
        }],
        children: cities.length > 0
          ? [{
              label: '城市',
              options: cities.map(city => ({
                label: city,
                title: `院校城市 · ${province} · ${city}`,
                field: 'cityNames' as FilterTokenField,
                value: city,
              })),
            }]
          : undefined,
      };
    });
    const unmatchedCityValues = cityValues.filter(city => !usedCitySet.has(city));
    if (unmatchedCityValues.length > 0) {
      provinceChildren.push({
        label: '其他城市',
        options: unmatchedCityValues.map(city => ({
          label: city,
          title: `院校城市 · ${city}`,
          field: 'cityNames' as FilterTokenField,
          value: city,
        })),
      });
    }

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

    const majorChildren: FilterPanelGroup[] = allMajorDisciplineValues.map(discipline => {
      const options = (groupedCategories.get(discipline) || []).map(value => ({
        label: value,
        title: `专业大类 · ${discipline} · ${value}`,
        field: 'majorKeywords' as FilterTokenField,
        value,
      }));
      return {
        label: discipline,
        options,
      };
    });

    if (unmatchedCategories.length > 0) {
      majorChildren.push({
        label: '其他专业大类',
        options: unmatchedCategories.map(value => ({
          label: value,
          title: `专业大类 · ${value}`,
          field: 'majorKeywords' as FilterTokenField,
          value,
        })),
      });
    }

    normalizedGroups
      .filter(group => ['admission.type', 'constraint.limit', 'major.tag'].includes(group.groupCode || ''))
      .map(group => toPanelGroup(group))
      .filter(Boolean)
      .forEach(group => {
        majorChildren.push(group as FilterPanelGroup);
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
        label: `专业大类 · ${name}`,
        field: 'majorKeyword',
        polarity: 'positive',
        value: name,
      });
    });
    filters.negativeMajorKeywords.forEach(name => {
      chips.push({
        key: `major-keyword-negative-${name}`,
        label: `专业大类 · 不看${name}`,
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
        label: `专业标签 · ${tag}`,
        field: 'majorTags',
        polarity: 'positive',
        value: tag,
      });
    });
    filters.negativeMajorTags.forEach(tag => {
      chips.push({
        key: `major-tag-negative-${tag}`,
        label: `专业标签 · 不看${tag}`,
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
          schoolTags: data.schoolTags || [],
          majorTags: data.majorTags || [],
          majorKeywords: data.majorKeywords || [],
          groups: data.groups || [],
        });
      }
    } catch (error) {
      console.warn('获取候选筛选项失败', error);
    }
  };

  const hasLoadedFilterOptions = useMemo(() => {
    return Boolean(
      (candidateFilterOptions.groups && candidateFilterOptions.groups.length > 0) ||
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
        queryCandidatePool(candidatePoolResult.page || 1);
      } else {
        message.error('加入方案失败');
      }
    } catch (error) {
      message.error('加入方案异常，请稍后重试');
    }
    setActionLoading(null);
  };

  const handleRemoveDraftItem = async (volunteerId?: string) => {
    const draftItem = draftItems.find(item => item.volunteerId === volunteerId);
    if (!volunteerId || actionLoading) {
      return;
    }
    if (draftItem?.locked) {
      message.warning('方案项已锁定，请先解除锁定再删除');
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
        queryCandidatePool(candidatePoolResult.page || 1);
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
    const hasLocked = group.items.some(item => Boolean(item.draftItem.locked));
    if (hasLocked) {
      message.warning('该专业组里有已锁定专业，请先解除锁定再整组删除');
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
        queryCandidatePool(candidatePoolResult.page || 1);
      } else {
        message.error('移出专业组失败');
      }
    } catch (error) {
      message.error('移出专业组异常，请稍后重试');
    }
    setActionLoading(null);
  };

  const handleToggleDraftLock = async (item?: PlanningDraftItem) => {
    if (!item?.volunteerId || actionLoading) {
      return;
    }
    setActionLoading('draft');
    try {
      const { data, code } = await lockPlanningDraftItemsApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        [item.volunteerId],
        !item.locked
      );
      if (code === 0) {
        message.success(item.locked ? '已解除锁定' : '已锁定方案项');
        if (data) {
          applyPlanningState(data);
        } else {
          await fetchWorkspaceState();
        }
      } else {
        message.error('更新方案项锁定状态失败');
      }
    } catch (error) {
      message.error('更新方案项锁定状态异常，请稍后重试');
    }
    setActionLoading(null);
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
    setActionLoading('ordered');
    setOrderedActionVolunteerId(item.volunteerId);
    const hideLoading = message.loading(direction === 'up' ? '正在上移志愿...' : '正在下移志愿...', 0);
    try {
      const { data, code } = await movePlanningOrderedItemApi(
        routerParams.tenantId,
        routerParams.chatSessionId,
        item.volunteerId,
        targetPosition
      );
      if (code === 0) {
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

  const handleTogglePin = async (item?: PlanningOrderedItem) => {
    if (!item?.volunteerId || actionLoading) {
      return;
    }
    setActionLoading('ordered');
    setOrderedActionVolunteerId(item.volunteerId);
    const hideLoading = message.loading(item.pinned ? '正在取消固定...' : '正在固定志愿...', 0);
    try {
      const api = item.pinned ? unpinPlanningOrderedItemApi : pinPlanningOrderedItemApi;
      const { data, code } = await api(
        routerParams.tenantId,
        routerParams.chatSessionId,
        item.volunteerId,
        item.position || 1
      );
      if (code === 0) {
        if (data) {
          setPlanningState(prev => ({
            ...(prev || {}),
            ...data,
            orderedPlanState: data.orderedPlanState || prev?.orderedPlanState,
          }));
        }
      } else {
        message.error('更新固定状态失败');
      }
    } catch (error) {
      message.error('更新固定状态异常，请稍后重试');
    }
    hideLoading();
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
    };
    handleScroll();
    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, [activeView]);

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
  const hasActionableReviewChecks = actionableReviewChecks.length > 0 || actionablePendingActions.length > 0;
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

  const groupedOrderedList = useMemo<OrderedGroup[]>(() => {
    if (!isMajorGroupMode) {
      return [];
    }
    const grouped = new Map<string, OrderedGroup>();
    orderedItems.forEach(item => {
      const candidateItem = item.volunteerId ? candidateItemMap.get(item.volunteerId) || null : null;
      const schoolName = candidateItem?.schoolName || item.schoolName || '未知院校';
      const key = candidateItem?.planSchoolDataId || candidateItem?.schoolId || schoolName;
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
  }, [candidateItemMap, isMajorGroupMode, orderedItems]);

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
        locked: Boolean(unit.locked),
        items: (unit.majorItems || []).map(major => {
          const volunteerId = major.volunteerId;
          const draftItem =
            draftItems.find(item => item.volunteerId === volunteerId) || {
              volunteerId,
              tier: major.tier || unit.tier,
              schoolName: unit.schoolName,
              majorName: major.majorName,
              locked: unit.locked,
              source: unit.source,
            };
          return {
            draftItem,
            candidateItem: volunteerId ? candidateItemMap.get(volunteerId) || null : null,
          };
        }),
      }));
    }

    const grouped = new Map<string, DraftGroup>();
    draftItems.forEach((item, index) => {
      const candidateItem = item.volunteerId ? candidateItemMap.get(item.volunteerId) || null : null;
      const key =
        candidateItem?.planSchoolDataId ||
        candidateItem?.schoolId ||
        item.volunteerId?.split('_')[0] ||
        item.schoolName ||
        `draft-fallback-${index}`;
      const existing = grouped.get(key);
      if (existing) {
        existing.items.push({ draftItem: item, candidateItem });
        existing.locked = existing.locked || Boolean(item.locked);
        return;
      }
      grouped.set(key, {
        key,
        tier: item.tier || candidateItem?.tier || '',
        schoolName: candidateItem?.schoolName || item.schoolName || '未知院校',
        source: item.source,
        locked: Boolean(item.locked),
        items: [{ draftItem: item, candidateItem }],
      });
    });
    return Array.from(grouped.values());
  }, [candidateItemMap, draftItems, isMajorGroupMode, planningState?.draftPlanState?.units]);

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
              <span className={style.filterPanelActionDivider}>|</span>
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

  const renderFilterPanelGroup = (group: FilterPanelGroup, depth = 0, parentKey = ''): React.ReactNode => {
    const groupKey = `${parentKey}-${group.label}`;
    return (
      <div
        key={groupKey}
        className={depth === 0 ? style.filterPanelGroup : style.filterPanelSubGroup}
      >
        <div className={depth === 0 ? style.filterPanelGroupTitle : style.filterPanelSubGroupTitle}>
          {group.label}
        </div>
        {group.options && group.options.length > 0 && renderFilterPanelOptionRows(groupKey, group.options)}
        {group.children?.map(child => renderFilterPanelGroup(child, depth + 1, groupKey))}
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
      <div className={style.stageHeader}>
        <div className={style.metricsGrid}>
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

        {isLegacySubmittedPlan && (
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
                    groupedCandidateList.map((group, groupIndex) => (
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
                                <div className={style.candidateGroupScore}>
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
                                const inDraft = item.volunteerId ? draftIdSet.has(item.volunteerId) : false;
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
                                        <div className={style.majorPlanColumn}>2025招生计划</div>
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
                                        type={inDraft ? 'default' : 'primary'}
                                        icon={<PlusOutlined />}
                                        disabled={inDraft || !item.volunteerId}
                                        loading={actionLoading === 'draft' && !inDraft}
                                        onClick={() => handleAddCandidateToDraft(item.volunteerId)}
                                      >
                                        {inDraft ? '已加入方案' : '加入方案'}
                                      </Button>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </Panel>
                        </Collapse>
                      </div>
                    ))
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
                          const metaItems = (group.schoolBasicTags || []).length
                            ? group.schoolBasicTags
                            : [
                                [group.provinceName, group.cityName].filter(Boolean).join('/'),
                                group.schoolBatch,
                                group.schoolNature,
                                group.schoolCategory,
                                group.schoolLevel,
                              ].filter(Boolean);
                          const orderedStatusLabels = Array.from(
                            new Set(group.orderedItems.map(entry => getOrderedItemStatusLabel(entry.orderedItem)))
                          );
                          const hasLocked = group.orderedItems.some(entry => entry.orderedItem.locked);
                          const isPreferredGroup = group.orderedItems.some(
                            entry => entry.orderedItem.source === 'initial_auto'
                          );
                          return (
                            <div
                              key={group.key}
                              className={`${style.orderedCard} ${groupFocused ? style.focusedCard : ''}`}
                            >
                              <div className={style.orderedMain}>
                                <div className={style.positionBadge}>{groupIndex + 1}</div>
                                <div className={style.orderedContent}>
                                  <div className={`${style.cardTitleRow} ${style.groupTitleRow}`}>
                                    <div className={style.cardTitle}>{group.schoolName}</div>
                                    {hasLocked ? (
                                      <Tag bordered={false} className={style.orderedLockedTag}>
                                        已锁定
                                      </Tag>
                                    ) : null}
                                    {isPreferredGroup ? (
                                      <Tag bordered={false} className={style.orderedPreferredTag}>
                                        优选
                                      </Tag>
                                    ) : null}
                                    {(group.schoolRankTags || []).map(tag => (
                                      <Tag bordered={false} color="volcano" key={`${group.key}-${tag}`}>
                                        {tag}
                                      </Tag>
                                    ))}
                                    {orderedStatusLabels.map(label => (
                                      <Tag key={`${group.key}-${label}`} bordered={false} className={style.orderedStatusTag}>
                                        {label}
                                      </Tag>
                                    ))}
                                  </div>
                                  <div className={style.orderedGroupMeta}>
                                    {metaItems.map(meta => (
                                      <span key={`${group.key}-${meta}`} className={style.inlineMetaItem}>
                                        {meta}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                                <div className={style.candidateGroupScore}>
                                  <div className={style.candidateGroupScoreValue}>
                                    {formatPercent(group.schoolEnrollRatio)}
                                  </div>
                                  <div className={style.candidateGroupScoreTier}>
                                    {normalizeTierLabel(group.tier)}
                                  </div>
                                  <div className={style.candidateGroupScoreMeta}>
                                    {getGroupCountLabel(group.orderedItems.length)}
                                  </div>
                                </div>
                              </div>
                              <div className={style.orderedGroupMajorList}>
                                {group.orderedItems.map((entry, itemIndex) => {
                                  const item = entry.orderedItem;
                                  const candidateItem = entry.candidateItem;
                                  const itemFocused = focusVolunteerIds.includes(item.volunteerId || '');
                                  const absoluteIndex = orderedItems.findIndex(
                                    orderedEntry => orderedEntry.volunteerId === item.volunteerId
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
                                      <div className={style.orderedMajorInfo}>
                                        <div className={style.orderedMajorTitleRow}>
                                          <span className={style.orderedMajorIndex}>#{itemIndex + 1}</span>
                                          <div className={style.orderedMajorName}>{renderMajorName(item.majorName)}</div>
                                        </div>
                                        <div className={style.orderedMajorMeta}>
                                          <span>录取率 {formatPercent(candidateItem?.admissionRatio)}</span>
                                          <span>推荐系数 {formatNumber(candidateItem?.finalScore)}</span>
                                          <span>专业热度 {formatNumber(candidateItem?.hotIndex)}</span>
                                          <Tooltip title={SALARY_AVG_TOOLTIP}>
                                            <span>薪酬指数 {formatNumber(candidateItem?.salaryAvg)}</span>
                                          </Tooltip>
                                          <span>学费 {formatMetricNumber(candidateItem?.tuitionPerYear, '/年')}</span>
                                          <span>专业代码 {candidateItem?.majorCode || '-'}</span>
                                        </div>
                                      </div>
                                      <div className={style.orderedActions}>
                                        <Tooltip title={item.pinned ? '取消固定' : '固定位置'}>
                                          <Button
                                            icon={<PushpinOutlined />}
                                            type={item.pinned ? 'primary' : 'default'}
                                            loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                            disabled={actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId}
                                            onClick={() => handleTogglePin(item)}
                                          />
                                        </Tooltip>
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
                                        <Tooltip title="删除">
                                          <Button
                                            danger
                                            icon={<DeleteOutlined />}
                                            disabled={Boolean(item.locked)}
                                            loading={actionLoading === 'draft' || actionLoading === 'ordered'}
                                            onClick={() => handleRemoveDraftItem(item.volunteerId)}
                                          />
                                        </Tooltip>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })
                      : orderedItems.map((item, index) => {
                          const candidateItem = item.volunteerId ? candidateItemMap.get(item.volunteerId) || null : null;
                          return (
                            <div
                              key={item.volunteerId}
                              ref={element => {
                                if (item.volunteerId) {
                                  orderedItemRefs.current[item.volunteerId] = element;
                                }
                              }}
                              className={`${style.orderedCard} ${
                                focusVolunteerIds.includes(item.volunteerId || '') ? style.focusedCard : ''
                              }`}
                            >
                              <div className={style.orderedMain}>
                                <div className={style.positionBadge}>{index + 1}</div>
                                <div className={style.orderedContent}>
                                  <div className={style.cardTitleRow}>
                                    <Tag color={item.tier === '冲' ? 'red' : item.tier === '稳' ? 'gold' : 'green'}>
                                      {item.tier}
                                    </Tag>
                                    <div className={style.cardTitle}>{item.schoolName}</div>
                                    {item.locked ? (
                                      <Tag bordered={false} className={style.orderedLockedTag}>
                                        已锁定
                                      </Tag>
                                    ) : null}
                                    {item.source === 'initial_auto' ? (
                                      <Tag bordered={false} className={style.orderedPreferredTag}>
                                        优选
                                      </Tag>
                                    ) : null}
                                    {(candidateItem?.schoolRankTags || []).map(tag => (
                                      <Tag bordered={false} color="volcano" key={`${item.volunteerId}-${tag}`}>
                                        {tag}
                                      </Tag>
                                    ))}
                                    <Tag bordered={false} className={style.orderedStatusTag}>
                                      {getOrderedItemStatusLabel(item)}
                                    </Tag>
                                  </div>
                                  <div className={style.cardSubtitle}>{renderMajorName(item.majorName)}</div>
                                  <div className={style.orderedMajorMeta}>
                                    <span>录取率 {formatPercent(candidateItem?.admissionRatio)}</span>
                                    <span>推荐系数 {formatNumber(candidateItem?.finalScore)}</span>
                                    <span>专业热度 {formatNumber(candidateItem?.hotIndex)}</span>
                                    <Tooltip title={SALARY_AVG_TOOLTIP}>
                                      <span>薪酬指数 {formatNumber(candidateItem?.salaryAvg)}</span>
                                    </Tooltip>
                                    <span>学费 {formatMetricNumber(candidateItem?.tuitionPerYear, '/年')}</span>
                                    <span>专业代码 {candidateItem?.majorCode || '-'}</span>
                                  </div>
                                </div>
                                <div className={style.orderedActions}>
                                  <Tooltip title={item.pinned ? '取消固定' : '固定位置'}>
                                    <Button
                                      icon={<PushpinOutlined />}
                                      type={item.pinned ? 'primary' : 'default'}
                                      loading={orderedActionVolunteerId === item.volunteerId && actionLoading === 'ordered'}
                                      disabled={actionLoading === 'ordered' && orderedActionVolunteerId !== item.volunteerId}
                                      onClick={() => handleTogglePin(item)}
                                    />
                                  </Tooltip>
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
                                  <Tooltip title="删除">
                                    <Button
                                      danger
                                      icon={<DeleteOutlined />}
                                      disabled={Boolean(item.locked)}
                                      loading={actionLoading === 'draft' || actionLoading === 'ordered'}
                                      onClick={() => handleRemoveDraftItem(item.volunteerId)}
                                    />
                                  </Tooltip>
                                </div>
                              </div>
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
                {draftItems.length > 0 ? (
                  isMajorGroupMode ? (
                    groupedDraftList.map(group => (
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
                              disabled={group.locked}
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
                              <Tooltip title={draftItem.locked ? '解除锁定' : '锁定'}>
                                <Button
                                  size="small"
                                  icon={draftItem.locked ? <UnlockOutlined /> : <LockOutlined />}
                                  onClick={() => handleToggleDraftLock(draftItem)}
                                />
                              </Tooltip>
                              <Tooltip title="删除">
                                <Button
                                  size="small"
                                  danger
                                  icon={<DeleteOutlined />}
                                  disabled={Boolean(draftItem.locked)}
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
                    draftItems.map(item => (
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
                          <Tooltip title={item.locked ? '解除锁定' : '锁定'}>
                            <Button
                              size="small"
                              icon={item.locked ? <UnlockOutlined /> : <LockOutlined />}
                              onClick={() => handleToggleDraftLock(item)}
                            />
                          </Tooltip>
                          <Tooltip title="删除">
                            <Button
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              disabled={Boolean(item.locked)}
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
