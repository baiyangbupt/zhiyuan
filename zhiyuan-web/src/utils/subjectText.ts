const SUBJECT_SHORT_NAME_MAP: Record<string, string> = {
  物理: '物',
  化学: '化',
  生物: '生',
  历史: '历',
  地理: '地',
  政治: '政',
  思想政治: '政',
  技术: '技',
  通用技术: '技',
  信息技术: '技',
  语文: '语',
  数学: '数',
  英语: '英',
};

const SUBJECT_PARSE_ORDER = [
  '思想政治',
  '通用技术',
  '信息技术',
  '物理',
  '化学',
  '生物',
  '历史',
  '地理',
  '政治',
  '技术',
  '语文',
  '数学',
  '英语',
];

const formatSubjectGroupShortText = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed) {
    return '';
  }
  const parts = trimmed
    .split(/[./、,，\s]+/)
    .map(part => part.trim())
    .filter(Boolean);
  if (parts.length > 1) {
    return parts.map(formatSubjectGroupShortText).join('');
  }
  if (SUBJECT_SHORT_NAME_MAP[trimmed]) {
    return SUBJECT_SHORT_NAME_MAP[trimmed];
  }
  let cursor = trimmed;
  let result = '';
  while (cursor) {
    const matched = SUBJECT_PARSE_ORDER.find(subject => cursor.startsWith(subject));
    if (matched) {
      result += SUBJECT_SHORT_NAME_MAP[matched];
      cursor = cursor.slice(matched.length);
    } else {
      result += cursor[0];
      cursor = cursor.slice(1);
    }
  }
  return result;
};

export const formatSubjectShortText = (subjects?: Array<string | null | undefined>) =>
  (subjects || [])
    .map(item => String(item || '').trim())
    .filter(Boolean)
    .map(formatSubjectGroupShortText)
    .join('');
