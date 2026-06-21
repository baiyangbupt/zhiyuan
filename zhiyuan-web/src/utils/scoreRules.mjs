export const HAINAN_PROVINCE_CODE = '460000';
export const SHANGHAI_PROVINCE_CODE = '310000';
export const DEFAULT_MAIN_SUBJECT_MAX = 150;
export const DEFAULT_ELECTIVE_SUBJECT_MAX = 100;
export const SHANGHAI_ELECTIVE_SUBJECT_MAX = 70;
export const HAINAN_SCORE_MIN = 100;
export const HAINAN_SCORE_MAX = 900;

export function isHainanProvince(provinceCode) {
  return provinceCode === HAINAN_PROVINCE_CODE;
}

export function resolveSubjectScoreMax(areaId, subjectGroup) {
  if (isHainanProvince(areaId)) {
    return HAINAN_SCORE_MAX;
  }
  if (subjectGroup === 'main') {
    return DEFAULT_MAIN_SUBJECT_MAX;
  }
  return areaId === SHANGHAI_PROVINCE_CODE ? SHANGHAI_ELECTIVE_SUBJECT_MAX : DEFAULT_ELECTIVE_SUBJECT_MAX;
}

export function validateHainanTotalScore(value) {
  if (value === undefined || value === null || value === '') {
    return '请输入最终总分';
  }
  const score = Number(value);
  if (!Number.isFinite(score) || score < HAINAN_SCORE_MIN || score > HAINAN_SCORE_MAX) {
    return `最终总分范围为${HAINAN_SCORE_MIN}～${HAINAN_SCORE_MAX}分`;
  }
  return null;
}

export function resolveTotalScoreLabel(provinceCode, defaultLabel = '高考总成绩') {
  return isHainanProvince(provinceCode) ? '最终总分' : defaultLabel;
}

export function shouldAutoCalculateTotalScore(provinceCode) {
  return !isHainanProvince(provinceCode);
}
