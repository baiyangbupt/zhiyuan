// 意向横幅标签派生（纯函数，无 React / 环境依赖；index.tsx 只负责渲染）。
//
// 4.0 口径（2026-10-13 队列 21 定稿）：权威意向字段 = `constraintState.hardPlanningObjectives`
// （priorityRules / coverageRequirements / tierQuotaGoal）+ `constraintState.hardConstraints`；
// `softPreferences` 自 4.0 起降级为 **legacy 只读**（字段与读取保留，仅兼容旧会话）；
// `profileState.explicitProfile` 继续读。
// 横幅此前只读 softPreferences + explicitProfile + hardConstraints（不读 hardPlanningObjectives）：
// 新会话 apply 只写 hardPlanningObjectives（如 10041981 的北京同档前置）→ 顶部误显示
// "暂无已记录意向"。本模块把"横幅改读权威字段派生标签"收成纯逻辑。
//
// 映射（说人话、不甩内部数值，10-09 口径）：
//   priorityRules        → 「优先地域/专业/院校: 北京（同档靠前）」（region→地域、major→专业、school→院校；
//                          orderingTarget=rank_before → 同档靠前）
//   coverageRequirements → 「覆盖要求: 至少 N 个 X」
//   tierQuotaGoal        → 「档位配比: 冲 N 个、稳 N 个、保 N 个」（有则出）
//   softPreferences / explicitProfile / hardConstraints → 既有标签原样保留（旧会话兼容）
// 去重：同一意向跨来源同值只出一个标签（priorityRules 权威优先，legacy 同值让位）。

const DOMAIN_LABELS = {
  region: '地域',
  major: '专业',
  school: '院校',
};

const BUCKETS = ['region', 'major', 'school'];

const POSITIVE_GROUPS = [
  { label: '优先地域', bucket: 'region', softKey: 'preferRegions', explicitKey: 'positiveRegions' },
  { label: '优先专业', bucket: 'major', softKey: 'preferMajors', explicitKey: 'positiveMajors' },
  { label: '优先院校', bucket: 'school', softKey: 'preferSchools', explicitKey: 'positiveSchools' },
];

const NEGATIVE_GROUPS = [
  { label: '不优先地域', bucket: 'region', softKey: 'avoidRegions', explicitKey: 'negativeRegions' },
  { label: '不优先专业', bucket: 'major', softKey: 'avoidMajors', explicitKey: 'negativeMajors' },
  { label: '不优先院校', bucket: 'school', softKey: 'avoidSchools', explicitKey: 'negativeSchools' },
];

const REQUIRED_GROUPS = [
  { label: '只看地域', key: 'mustIncludeRegions' },
  { label: '只看专业', key: 'mustIncludeMajors' },
  { label: '只看院校', key: 'mustIncludeSchools' },
];

const EXCLUDED_GROUPS = [
  { label: '避开地域', key: 'mustExcludeRegions' },
  { label: '避开专业', key: 'mustExcludeMajors' },
  { label: '避开院校', key: 'mustExcludeSchools' },
];

// 冲/稳/保：字段后缀 → 展示名。
const TIERS = [
  ['sprint', '冲'],
  ['stable', '稳'],
  ['protect', '保'],
];

const uniqueStrings = values =>
  Array.from(new Set(values.map(item => (item || '').trim()).filter(Boolean)));

const toDisplayString = value => {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value).trim();
  }
  if (typeof value === 'object') {
    const item = value;
    return toDisplayString(
      item.name ||
        item.label ||
        item.value ||
        item.desc ||
        item.data ||
        item.subjectName ||
        item.provinceName ||
        item.majorName ||
        item.majorSubName ||
        item.schoolName
    );
  }
  return '';
};

const toDisplayStrings = value => {
  if (Array.isArray(value)) {
    return uniqueStrings(value.map(toDisplayString));
  }
  const text = toDisplayString(value);
  return text ? [text] : [];
};

const asArray = value => (Array.isArray(value) ? value : []);

const asRecord = value =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {};

const normalizeToken = value => String(value ?? '').trim().toLowerCase();

const domainLabel = value => DOMAIN_LABELS[normalizeToken(value)] || '条件';

const domainBucket = value => {
  const token = normalizeToken(value);
  return BUCKETS.includes(token) ? token : '';
};

const orderingSuffix = orderingTarget => {
  const target = normalizeToken(orderingTarget);
  return !target || target === 'rank_before' ? '（同档靠前）' : '';
};

const toCount = value => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const count = Number(value);
  return Number.isFinite(count) && count >= 0 ? Math.trunc(count) : null;
};

const formatRange = range => {
  const item = asRecord(range);
  const min = toCount(item.minCount);
  const max = toCount(item.maxCount);
  if (min !== null && max !== null) {
    return `${min}~${max} 个`;
  }
  if (min !== null) {
    return `${min} 个以上`;
  }
  if (max !== null) {
    return `${max} 个以内`;
  }
  return '';
};

// 档位配比 → 人话（type：exact_counts / count_ranges / ratios；字段缺失再按序兜底）。
const formatTierQuota = goal => {
  const raw = asRecord(goal);
  const type = normalizeToken(raw.type);

  const renderCounts = () =>
    TIERS.map(([field, name]) => [name, toCount(raw[`${field}Count`])])
      .filter(([, count]) => count !== null)
      .map(([name, count]) => `${name} ${count} 个`)
      .join('、');

  const renderRanges = () =>
    TIERS.map(([field, name]) => [name, formatRange(raw[field])])
      .filter(([, text]) => text)
      .map(([name, text]) => `${name} ${text}`)
      .join('、');

  const renderRatios = () => {
    const entries = TIERS.map(([field, name]) => [name, toCount(raw[`${field}Weight`])]).filter(
      ([, weight]) => weight !== null && weight > 0
    );
    const total = entries.reduce((sum, [, weight]) => sum + weight, 0);
    if (!total) {
      return '';
    }
    // 权重是内部系数 → 折算成百分比（说人话，不甩 2:1:1 之外的裸权重）。
    return entries
      .map(([name, weight]) => `${name} ${Math.round((weight / total) * 100)}%`)
      .join('、');
  };

  const byType = {
    exact_counts: renderCounts,
    count_ranges: renderRanges,
    ratios: renderRatios,
  };
  const renderers = byType[type]
    ? [byType[type], renderCounts, renderRanges, renderRatios]
    : [renderCounts, renderRanges, renderRatios];
  for (const render of renderers) {
    const text = render();
    if (text) {
      return text;
    }
  }
  return '';
};

const priorityRuleTag = rule => {
  const raw = asRecord(rule);
  const values = toDisplayStrings(raw.values);
  if (!values.length) {
    return null;
  }
  return {
    label: `优先${domainLabel(raw.domain)}`,
    suffix: orderingSuffix(raw.orderingTarget),
    values,
    bucket: domainBucket(raw.domain),
  };
};

const coverageRequirementValue = requirement => {
  const raw = asRecord(requirement);
  const values = toDisplayStrings(raw.values);
  if (!values.length) {
    return '';
  }
  const minCount = toCount(raw.minCount);
  return `至少 ${minCount === null || minCount < 1 ? 1 : minCount} 个${values.join('、')}`;
};

/**
 * 从 planning workspace state（`PlanningStateRes`）派生横幅标签。
 * @returns {Array<{key: string, text: string, type: 'positive'|'negative'|'required'|'excluded'}>}
 */
export function buildIntentTags(planningWorkspaceState) {
  const state = asRecord(planningWorkspaceState);
  const constraintState = asRecord(state.constraintState);
  const objectives = asRecord(constraintState.hardPlanningObjectives);
  const hard = asRecord(constraintState.hardConstraints);
  // legacy 只读（4.0 起）：字段与读取保留，仅兼容旧会话；新写链只写硬约束/硬目标。
  const soft = asRecord(constraintState.softPreferences);
  const explicit = asRecord(asRecord(state.profileState).explicitProfile);

  const tags = [];
  const seenKeys = new Set();
  const emit = (label, value, type) => {
    const text = value ? `${label}: ${value}` : label;
    const key = `${label}-${value}`;
    if (seenKeys.has(key)) {
      return;
    }
    seenKeys.add(key);
    tags.push({ key, text, type });
  };

  // ① 权威：hardPlanningObjectives.priorityRules（同档前置 → 「优先X: 值（同档靠前）」）。
  //    与 legacy 同域同值去重：priorityRules 先占位，softPreferences/explicitProfile 让位。
  const priorityByBucket = { region: [], major: [], school: [] };
  const otherPriorityTags = [];
  asArray(objectives.priorityRules).forEach(rule => {
    const tag = priorityRuleTag(rule);
    if (!tag) {
      return;
    }
    if (tag.bucket) {
      priorityByBucket[tag.bucket].push(tag);
    } else {
      otherPriorityTags.push(tag);
    }
  });

  const claimedPositive = { region: new Set(), major: new Set(), school: new Set() };
  POSITIVE_GROUPS.forEach(({ label, bucket, softKey, explicitKey }) => {
    priorityByBucket[bucket].forEach(tag => {
      tag.values.forEach(value => {
        emit(label, `${value}${tag.suffix}`, 'positive');
        claimedPositive[bucket].add(value);
      });
    });
    // ② legacy 兼容：softPreferences（只读）+ explicitProfile 的既有读取原样保留。
    uniqueStrings([
      ...toDisplayStrings(soft[softKey]),
      ...toDisplayStrings(explicit[explicitKey]),
    ])
      .filter(value => !claimedPositive[bucket].has(value))
      .forEach(value => emit(label, value, 'positive'));
  });
  otherPriorityTags.forEach(tag => {
    tag.values.forEach(value => emit(tag.label, `${value}${tag.suffix}`, 'positive'));
  });

  // ③ 权威：coverageRequirements → 「覆盖要求: 至少 N 个 X」。
  asArray(objectives.coverageRequirements).forEach(requirement => {
    const value = coverageRequirementValue(requirement);
    if (value) {
      emit('覆盖要求', value, 'required');
    }
  });

  // ④ 权威：tierQuotaGoal → 「档位配比: …」（有则出）。
  const quotaValue = formatTierQuota(objectives.tierQuotaGoal);
  if (quotaValue) {
    emit('档位配比', quotaValue, 'required');
  }

  // ⑤ legacy 负向（softPreferences 只读 + explicitProfile）：既有读取原样保留。
  NEGATIVE_GROUPS.forEach(({ label, softKey, explicitKey }) => {
    uniqueStrings([
      ...toDisplayStrings(soft[softKey]),
      ...toDisplayStrings(explicit[explicitKey]),
    ]).forEach(value => emit(label, value, 'negative'));
  });

  // ⑥ 硬约束（权威）：既有读取原样保留。
  REQUIRED_GROUPS.forEach(({ label, key }) => {
    toDisplayStrings(hard[key]).forEach(value => emit(label, value, 'required'));
  });
  EXCLUDED_GROUPS.forEach(({ label, key }) => {
    toDisplayStrings(hard[key]).forEach(value => emit(label, value, 'excluded'));
  });

  return tags;
}
