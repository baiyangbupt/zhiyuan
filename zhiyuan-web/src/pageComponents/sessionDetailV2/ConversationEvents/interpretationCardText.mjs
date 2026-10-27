// 录取解读卡的文案映射（纯逻辑，node:test 直接测）。
// 口径：只讲结构与条件情景，不讲录取概率；缺数据标“无法判断/数据缺口”。

export const SCENARIO_LABELS = {
  base: '基准情形',
  upside: '向上情形',
  downside: '向下情形',
  no_safe: '无保底情形',
};

export const SCENARIO_CONDITIONS = {
  base: '前序志愿均未满足时',
  upside: '冲档命中时',
  downside: '稳档也未被满足时',
  no_safe: '当前没有可识别的保底档位',
};

export const SAFETY_TEXT = {
  '有保底档位': '有保底档位',
  '保底档位存在、数据不足': '保底档位存在、数据不足',
  '无保底档位': '无保底档位',
  '无法判断': '无法判断',
};

export const DATA_BAND_TEXT = {
  '完整': '数据完整',
  '有缺口': '数据有缺口',
  '严重缺口': '数据严重缺口',
};

export function scenarioTitle(scenario) {
  const label = String(scenario?.label || scenario?.scenarioId || '');
  return SCENARIO_LABELS[label] || '结构情景';
}

export function scenarioCondition(scenario) {
  const condition = String(scenario?.condition || '').trim();
  if (condition && condition !== '无') return condition;
  const label = String(scenario?.label || scenario?.scenarioId || '');
  return SCENARIO_CONDITIONS[label] || '';
}

export function landingText(landing) {
  if (!landing) return '';
  const school = String(landing.schoolName || '').trim();
  const major = String(landing.majorName || '').trim();
  const position = landing.position != null ? `第 ${landing.position} 个` : '';
  const tier = String(landing.pathTier || '').trim();
  const parts = [];
  if (position) parts.push(position);
  if (school) parts.push(school);
  if (major) parts.push(major);
  if (tier && tier !== 'unknown') parts.push(`${tier}档`);
  return parts.join(' · ');
}

export function dataGapText(payload) {
  const parts = [];
  const safety = SAFETY_TEXT[payload?.safetyCoverage];
  if (safety) parts.push(`安全覆盖：${safety}`);
  const band = DATA_BAND_TEXT[payload?.dataCompletenessBand];
  if (band) parts.push(band);
  if (payload?.tierSequenceStatus === 'unknown') parts.push('档位顺序只能部分判断');
  if (payload?.orderAnomaly || payload?.tierSequenceStatus === 'inverted') {
    parts.push('存在跨档位排列（按实际顺序展示，不自动修正）');
  }
  return parts.join('；');
}
