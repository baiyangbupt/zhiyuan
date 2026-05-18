import { clearStorage, getStorage, setStorage } from '@/utils/tool';

const DRAFT_VERSION = 1;
const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const STEP_MIN = -1;
const STEP_MAX = 4;

export interface CustomerDetailDraft {
  version: number;
  tenantId: string;
  botId: string;
  userKey: string;
  currentStep: number;
  values: Record<string, any>;
  updatedAt: number;
}

const normalizeKeyPart = (value: unknown, fallback: string) => {
  const text = String(value ?? '').trim();
  return text || fallback;
};

export const resolveCustomerDetailDraftUserKey = (userInfo: any) => {
  const userId =
    userInfo?.userId ||
    userInfo?.id ||
    userInfo?.uid ||
    userInfo?.userScoreOb?.userId ||
    userInfo?.userScoreOb?.id;
  if (userId) return String(userId);

  const scoreInfo = userInfo?.userScoreOb || {};
  return [
    scoreInfo?.province?.code,
    scoreInfo?.examYear,
    scoreInfo?.subjectType?.code,
  ]
    .filter(Boolean)
    .join('_') || 'anonymous';
};

export const getCustomerDetailDraftKey = (tenantId: string, botId: string, userInfo: any) => {
  const userKey = resolveCustomerDetailDraftUserKey(userInfo);
  return [
    'customer_detail_draft',
    normalizeKeyPart(tenantId, 'unknown_tenant'),
    normalizeKeyPart(botId, 'unknown_bot'),
    normalizeKeyPart(userKey, 'anonymous'),
  ].join(':');
};

const isValidDraft = (
  draft: any,
  tenantId: string,
  botId: string,
  userInfo: any
): draft is CustomerDetailDraft => {
  if (!draft || typeof draft !== 'object') return false;
  if (draft.version !== DRAFT_VERSION) return false;
  if (draft.tenantId !== normalizeKeyPart(tenantId, 'unknown_tenant')) return false;
  if (draft.botId !== normalizeKeyPart(botId, 'unknown_bot')) return false;
  if (draft.userKey !== resolveCustomerDetailDraftUserKey(userInfo)) return false;
  if (typeof draft.currentStep !== 'number') return false;
  if (draft.currentStep < STEP_MIN || draft.currentStep > STEP_MAX) return false;
  if (!draft.updatedAt || Date.now() - draft.updatedAt > DRAFT_TTL_MS) return false;
  if (!draft.values || typeof draft.values !== 'object') return false;
  return true;
};

export const loadCustomerDetailDraft = (
  tenantId: string,
  botId: string,
  userInfo: any
): CustomerDetailDraft | null => {
  const key = getCustomerDetailDraftKey(tenantId, botId, userInfo);
  const draft = getStorage(key);
  if (!draft) return null;
  if (!isValidDraft(draft, tenantId, botId, userInfo)) {
    clearStorage([key]);
    return null;
  }
  return draft;
};

export const saveCustomerDetailDraft = (params: {
  tenantId: string;
  botId: string;
  userInfo: any;
  currentStep: number;
  values: Record<string, any>;
}) => {
  const { tenantId, botId, userInfo, currentStep, values } = params;
  const key = getCustomerDetailDraftKey(tenantId, botId, userInfo);
  const draft: CustomerDetailDraft = {
    version: DRAFT_VERSION,
    tenantId: normalizeKeyPart(tenantId, 'unknown_tenant'),
    botId: normalizeKeyPart(botId, 'unknown_bot'),
    userKey: resolveCustomerDetailDraftUserKey(userInfo),
    currentStep,
    values,
    updatedAt: Date.now(),
  };
  setStorage([{ key, value: draft }]);
};

export const clearCustomerDetailDraft = (tenantId: string, botId: string, userInfo: any) => {
  clearStorage([getCustomerDetailDraftKey(tenantId, botId, userInfo)]);
};
