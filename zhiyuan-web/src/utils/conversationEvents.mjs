// ── v1 统一事件（协议版本 1） ────────────────────────────────────────
// 白名单同时是"渲染面"的定义：不在里面的类型不会被页面渲染，
// 服务端新增事件类型时必须两边一起改，而不是靠前端"认不出来就画个默认"。
export const CONVERSATION_V1_TYPES = new Set([
  'turn.started',
  'turn.phase',
  'tool.progress',
  'understanding.preview',
  'clarification.requested',
  'clarification.resolved',
  'proposal.preview',
  'conversationAction.result',
  // 录取解读卡：有界摘要（scenarios 不带完整 path；caveats/drivers 已截断），
  // 完整结果留在工具结果/正文。缺数据由卡片如实标 unknown/数据缺口。
  'interpretation.preview',
  // 助手增量文本：**可丢弃的提示**（首字延迟感知）。丢一条不影响正确性——
  // 权威文本始终是终态 `assistant.completed`（到达时整段替换，重连不补播）。
  'assistant.delta',
  'assistant.completed',
  'turn.completed',
  'recoverable.error',
  'session.resync',
]);

export const isConversationV1Event = event =>
  !!event
  && event.protocolVersion === 1
  && CONVERSATION_V1_TYPES.has(event.type)
  && typeof event.sessionId === 'string'
  && typeof event.turnId === 'string'
  && typeof event.sequence === 'number';

const V1_PAYLOAD_WHITELIST = {
  // 回合开始的墙钟时间戳：排序仍由 reducer 按 sequence 做（不必依赖时钟），
  // 时间戳只作展示/诊断用；不给它留位置的话它会被静默过滤掉。
  'turn.started': ['startedAt'],
  'tool.progress': ['itemId', 'tool', 'status', 'label'],
  'turn.phase': ['phase', 'status', 'label'],
  'understanding.preview': ['summary', 'entities', 'constraints'],
  'clarification.requested': ['requestId', 'inputKind', 'questions', 'requestedSchema', 'expiresIn'],
  'clarification.resolved': ['requestId', 'status'],
  'proposal.preview': ['proposalRef', 'diff', 'sourceVersion', 'expiresAt'],
  // `code`/`message`：动作失败时**必须**能说出原因（110 / 40904 / 84009 …）——
  // 只有 actionStatus 的话，卡上只剩一句"未生效"，用户与排障都无从判断 ✗
  //（服务端 `server.py` 的 action_payload 已把这两个键带上 ✓，这里同步放行 ✓）。
  'conversationAction.result': [
    'proposalRef', 'actionStatus', 'newStateVersion', 'workspaceVersion',
    'actualChanges', 'reviewState', 'code', 'message',
    'origin', 'actionType', 'scope', 'receipt',
  ],
  // 解读卡只放有界摘要；完整 path/evidenceRefs 由服务端在适配层裁掉。
  'interpretation.preview': [
    'status', 'planVersion', 'admissionMode', 'safetyCoverage',
    'dataCompletenessBand', 'tierCoverage', 'ratioCoverage', 'dataCompleteness',
    'orderAnomaly', 'tierSequence', 'tierSequenceStatus', 'userOrderRespected',
    'baseLanding', 'scenarios', 'caveats', 'caveatDetails',
  ],
  'assistant.delta': ['chunk', 'itemId'],
  'assistant.completed': ['message', 'responseType', 'executionStatus', 'limitations'],
  'turn.completed': ['executionStatus', 'toolStatus', 'runtimeStatus'],
  'recoverable.error': ['code', 'message'],
};

/** 只放过白名单字段：原生形状里的额外字段不该顺手流到页面上。 */
export const sanitizeV1Payload = (type, payload) => {
  const allowed = V1_PAYLOAD_WHITELIST[type];
  if (!allowed || !payload || typeof payload !== 'object') return {};
  return Object.fromEntries(
    allowed.filter(key => payload[key] !== undefined).map(key => [key, payload[key]]),
  );
};

/**
 * 把**旧信封**里的帧转成 v1 形状，并分配一个本地序号。
 *
 * 旧帧里没有序号，所以这里的序号只在本次连接内有意义——它能让 reducer 正常工作，
 * 但**不能**跨重连去重。真正可重放的编号要等服务端接上事件存储后由它给出。
 * 因此这条路径产出的状态永远带着 `localSequence: true`，页面据此决定是否可以
 * 用序号做断线恢复（答案是：不可以）。
 */
export const toConversationEvent = (frame, { sessionId, streamEpoch, sequence }) => {
  if (!frame || typeof frame !== 'object') return null;
  if (isConversationV1Event(frame)) return frame;
  const knownTypes = new Set([...CONVERSATION_V1_TYPES, 'planning.status', 'text', 'reply']);
  if (!knownTypes.has(frame.type)) return null;
  const parsed = parseNestedContent(frame.content);
  const innerType = parsed && CONVERSATION_V1_TYPES.has(parsed.type) ? parsed.type : null;
  if (!innerType) return null;
  return {
    protocolVersion: 1,
    type: innerType,
    sessionId: String(sessionId || ''),
    turnId: String(frame.turnId || parsed.turnId || ''),
    streamEpoch: String(streamEpoch || 'local'),
    sequence,
    payload: sanitizeV1Payload(innerType, {
      ...parsed,
      itemId: parsed.itemId,
      label: parsed.message || parsed.label,
      status: parsed.stage || parsed.status,
    }),
    localSequence: true,
  };
};

const parseNestedContent = content => {
  if (content && typeof content === 'object') return content;
  if (typeof content !== 'string') return null;
  try {
    const parsed = JSON.parse(content);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
};

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

// 录取率字段是百分比点（38 = 38%，1.0 = 1%），不是 0–1 小数。
// 1.0 可能是上游对极低录取率的截断/取整，展示为“≤1%”，避免误读成 100%。
export const formatAdmissionRate = value => {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return '—';
  if (parsed > 0 && parsed <= 1) return '≤1%';
  return `${Math.round(parsed)}%`;
};

// 保留旧导出名，避免调用方一次性大改；语义已统一为录取率百分比。
export const formatAdmissionProbability = formatAdmissionRate;

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
  // v1 统一事件先过一遍：它自带协议版本、会话、代际与序号，
  // 不需要（也不该）再走下面那套按类型猜形状的兼容逻辑。
  if (isConversationV1Event(event)) {
    return {
      ...event,
      payload: sanitizeV1Payload(event.type, event.payload || {}),
    };
  }
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
