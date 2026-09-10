const toFiniteNumber = value => {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

export const parseConversationActionResult = value => {
  const asObject = raw => {
    if (typeof raw !== 'string') return raw;
    try { return JSON.parse(raw); } catch { return null; }
  };
  const event = asObject(value);
  if (!event || typeof event !== 'object') return null;
  if (event.type === 'conversationAction.result' && event.actionResult) return event;
  if (!['conversationAction.result', 'reply', 'text'].includes(event.type)) return null;
  const content = asObject(event.content);
  return content?.type === 'conversationAction.result' && content.actionResult ? content : null;
};

export const applyPendingActionResult = (card, result) => {
  const reference = card?.proposalRef || card?.pendingId;
  if (!reference || !result?.proposalRef || String(reference) !== String(result.proposalRef)) return card;
  if (!['applying', 'applied', 'cancelled', 'expired', 'stale_state', 'failed'].includes(result.actionStatus)) {
    return card;
  }
  return { ...card, status: result.actionStatus, clickable: false, clicked: result.actionStatus === 'applied' };
};

export const formatAdmissionProbability = value => {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return '—';
  const percentage = parsed >= 0 && parsed <= 1 ? parsed * 100 : parsed;
  return `${Math.round(percentage)}%`;
};

export const formatRank = value => {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return '—';
  return String(Math.round(parsed));
};

export const formatEvidencePayload = evidence => {
  if (!evidence || typeof evidence !== 'object') return null;
  return {
    evidenceId: typeof evidence.evidenceId === 'string' ? evidence.evidenceId : '',
    dataVersion: typeof evidence.dataVersion === 'string' ? evidence.dataVersion : '',
    limitations: Array.isArray(evidence.limitations)
      ? evidence.limitations.filter(item => typeof item === 'string')
      : [],
  };
};

export const normalizeAdmissionMode = value => {
  if (value === 'major') return 'major';
  if (value === 'majorGroup' || value === 'major_group') return 'major_group';
  return null;
};

const normalizeAdmissionFact = (raw, mode) => {
  if (!raw || typeof raw !== 'object') return null;
  const factMode = normalizeAdmissionMode(raw.admissionMode || raw.admission_mode || mode);
  const unitId = raw.admissionUnitId || raw.admission_unit_id;
  const schoolId = raw.schoolId || raw.school_id;
  const groupCode = raw.groupCode || raw.group_code;
  const majorId = raw.majorId || raw.major_id;
  const rate = toFiniteNumber(raw.unitAdmissionRate ?? raw.unit_admission_rate);
  if (!factMode || !unitId || !schoolId || rate === null || rate < 0 || rate > 99) return null;
  if (factMode === 'major' && !majorId) return null;
  if (factMode === 'major_group' && !groupCode) return null;
  const riskTier = raw.riskTier || raw.risk_tier;
  const expectedTier = rate < 50 ? '冲' : rate < 70 ? '稳' : '保';
  if (riskTier !== expectedTier) return null;
  const rawMajorItems = raw.majorItems || raw.major_items;
  const majorItems = Array.isArray(rawMajorItems)
    ? rawMajorItems.map(item => {
      if (!item || typeof item !== 'object') return null;
      const detailRate = toFiniteNumber(item.majorAdmissionRate ?? item.major_admission_rate);
      const detailId = item.majorId || item.major_id;
      if (!detailId || detailRate === null || detailRate < 0 || detailRate > 99) return null;
      return {
        majorId: String(detailId),
        ...(item.majorName || item.major_name ? { majorName: item.majorName || item.major_name } : {}),
        majorAdmissionRate: detailRate,
      };
    })
    : [];
  if (majorItems.some(item => item === null)) return null;
  const majorIds = majorItems.map(item => item.majorId);
  if (new Set(majorIds).size !== majorIds.length) return null;
  return {
    admissionUnitId: String(unitId),
    admissionMode: factMode,
    schoolId: String(schoolId),
    ...(raw.schoolName ? { schoolName: String(raw.schoolName) } : {}),
    ...(majorId ? { majorId: String(majorId) } : {}),
    ...(raw.majorName ? { majorName: String(raw.majorName) } : {}),
    ...(groupCode ? { groupCode: String(groupCode) } : {}),
    majorItems,
    unitAdmissionRate: rate,
    riskTier,
    ...(Array.isArray(raw.limitations) ? { limitations: raw.limitations.filter(item => typeof item === 'string') } : {}),
  };
};

export const normalizeAdmissionFactsPayload = payload => {
  if (!payload || typeof payload !== 'object') return null;
  const mode = normalizeAdmissionMode(payload.admissionMode || payload.admission_mode);
  const rawFacts = payload.admissionFacts || payload.admission_facts;
  if (!mode || !Array.isArray(rawFacts)) return null;
  const facts = rawFacts.map(fact => normalizeAdmissionFact(fact, mode)).filter(Boolean);
  if (!facts.length) return null;
  if (facts.some(fact => fact.admissionMode !== mode)) return null;
  const evidenceIds = Array.isArray(payload.evidenceIds)
    ? payload.evidenceIds.filter(item => typeof item === 'string')
    : [];
  return {
    admissionMode: mode,
    admissionFacts: facts,
    evidenceIds,
    ...(typeof payload.stateVersion === 'number' ? { stateVersion: payload.stateVersion } : {}),
    ...(typeof payload.dataVersion === 'string' ? { dataVersion: payload.dataVersion } : {}),
    limitations: Array.isArray(payload.limitations)
      ? payload.limitations.filter(item => typeof item === 'string')
      : [],
  };
};

const artifactIdOf = artifact => artifact?.artifactId || artifact?.artifact_id;

export const resolveArtifact = (ref, artifacts) => {
  const wanted = artifactIdOf(ref);
  if (!wanted) return null;
  if (Array.isArray(artifacts)) {
    return artifacts.find(item => artifactIdOf(item) === wanted) || null;
  }
  if (artifacts && typeof artifacts === 'object') {
    const candidate = artifacts[wanted];
    return candidate && artifactIdOf(candidate) === wanted ? candidate : null;
  }
  return null;
};

const stablePayload = payload => {
  if (!payload || typeof payload !== 'object') return {};
  return payload;
};

export const normalizeConversationEvent = event => {
  if (!event || typeof event !== 'object' || typeof event.type !== 'string') return null;
  if (event.type === 'reply' || event.type === 'card') return event;

  if (event.type === 'planning.status') {
    const payload = stablePayload(event.payload);
    const safe = {};
    if (typeof payload.status === 'string') safe.status = payload.status;
    if (typeof payload.stage === 'string') safe.stage = payload.stage;
    if (typeof payload.message === 'string') safe.message = payload.message;
    return { type: event.type, payload: safe };
  }
  if (event.type === 'assistant.delta' || event.type === 'assistant.completed') {
    return { type: event.type, content: typeof event.content === 'string' ? event.content : '' };
  }
  if (event.type === 'evidence.updated') {
    const payload = stablePayload(event.payload);
    const evidenceIds = Array.isArray(payload.evidenceIds)
      ? payload.evidenceIds.filter(item => typeof item === 'string')
      : Array.isArray(event.evidenceIds)
        ? event.evidenceIds.filter(item => typeof item === 'string')
        : [];
    return { type: event.type, evidenceIds };
  }
  if (event.type === 'admission.facts.updated') {
    const payload = normalizeAdmissionFactsPayload(stablePayload(event.payload));
    return payload ? { type: event.type, payload } : null;
  }
  if (event.type === 'recommendation.card') {
    const artifactId = event.artifactId || event.payload?.artifactId;
    return typeof artifactId === 'string' ? { type: event.type, artifactId } : null;
  }
  if (event.type === 'action.proposed') {
    const payload = stablePayload(event.payload);
    return {
      type: event.type,
      payload: {
        proposalId: typeof payload.proposalId === 'string' ? payload.proposalId : '',
        summary: typeof payload.summary === 'string' ? payload.summary : '',
        status: 'pending',
      },
    };
  }
  if (event.type === 'recoverable.error') {
    const payload = stablePayload(event.payload);
    return {
      type: event.type,
      payload: {
        code: typeof payload.code === 'string' ? payload.code : '',
        message: typeof payload.message === 'string' ? payload.message : '',
      },
    };
  }
  return null;
};
