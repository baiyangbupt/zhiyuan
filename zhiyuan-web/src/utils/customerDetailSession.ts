import { getBatchList, getSubjectPolicy } from '@/service/apis/sessionDetail';

const hasBatchCode = (batch: any) => Boolean(batch?.code);

const normalizeScore = (score: any) => {
  if (score === undefined || score === null || score === '') return undefined;
  const parsed = Number.parseFloat(String(score));
  return Number.isFinite(parsed) ? parsed : undefined;
};

const buildBatchName = (batchOption: any) => {
  const title = String(batchOption?.batchTitle || batchOption?.name || '').trim();
  const score = normalizeScore(batchOption?.score);
  if (!title) return undefined;
  if (score === undefined) return title;
  return `${title}(批次线${score}分)`;
};

export const buildCreateSessionBatchPayload = (batchOption: any) => {
  if (!batchOption) return undefined;

  const code = batchOption.batch || batchOption.code;
  if (!code) return undefined;

  return {
    code,
    level:
      typeof batchOption.level === 'object' ? batchOption.level?.key : batchOption.level,
    pos: batchOption.pos ? Number(batchOption.pos) : undefined,
    score: normalizeScore(batchOption.score),
    name: buildBatchName(batchOption),
  };
};

export const hydrateCreateSessionBatch = async (values: any, userInfo: any) => {
  if (hasBatchCode(values?.batch)) return values;

  const provinceCode = values?.province?.code || userInfo?.userScoreOb?.province?.code;
  const subjectCode = values?.subjectType?.code || userInfo?.userScoreOb?.subjectType?.code;
  if (!provinceCode || !subjectCode) return values;

  const policyRes = await getSubjectPolicy(provinceCode);
  const prepareType = policyRes?.data?.prepareType;
  const prepareTypeCode = prepareType?.code || values?.prepareType?.code;
  if (policyRes?.code !== 0 || !prepareTypeCode) return values;

  const batchRes = await getBatchList({
    areaId: provinceCode,
    prepareType: prepareTypeCode,
    subject: subjectCode,
  });
  const batchList = Array.isArray(batchRes?.data?.batchList) ? batchRes.data.batchList : [];
  const savedBatch = values?.batch;
  const selectedBatch =
    batchList.find(
      (item: any) =>
        savedBatch?.code &&
        String(item.batch) === String(savedBatch.code) &&
        (!savedBatch.level || String(item.level?.key) === String(savedBatch.level))
    ) ||
    batchList.find((item: any) => savedBatch?.code && String(item.batch) === String(savedBatch.code)) ||
    batchList[0];

  const batch = buildCreateSessionBatchPayload(selectedBatch);
  if (!batch) return values;

  return {
    ...values,
    batch,
    prepareType: values?.prepareType || (selectedBatch as any)?.prepareType || prepareType,
  };
};
