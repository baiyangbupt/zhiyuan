const toFiniteNumber = value => {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
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
