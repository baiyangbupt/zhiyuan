import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatAdmissionProbability,
  formatRank,
  formatEvidencePayload,
  normalizeConversationEvent,
  isConversationV1Event,
  toConversationEvent,
  resolveArtifact,
  parseConversationActionResult,
  applyPendingActionResult,
  sanitizeV1Payload,
} from './conversationEvents.mjs';

test('reads action results from native and compatibility websocket envelopes', () => {
  const result = { type: 'conversationAction.result', actionResult: { proposalRef: 'p1', actionStatus: 'applying' } };
  for (const type of ['reply', 'text', 'conversationAction.result']) {
    assert.deepEqual(parseConversationActionResult({ type, content: JSON.stringify(result) }), result);
  }
  assert.deepEqual(parseConversationActionResult(result), result);
  assert.equal(parseConversationActionResult({ type: 'text', content: '操作成功' }), null);
  assert.equal(parseConversationActionResult({ type: 'text', content: '{invalid' }), null);
});

test('updates only the referenced pending card from authoritative action states', () => {
  const card = { pendingId: 'p1', status: 'active', clickable: true };
  for (const actionStatus of ['applying', 'applied', 'cancelled', 'expired', 'stale_state', 'failed']) {
    const updated = applyPendingActionResult(card, { proposalRef: 'p1', actionStatus });
    assert.equal(updated.status, actionStatus);
    assert.equal(updated.clicked, actionStatus === 'applied');
    assert.equal(updated.clickable, false);
  }
  assert.equal(applyPendingActionResult(card, { proposalRef: 'p2', actionStatus: 'applied' }), card);
  assert.equal(applyPendingActionResult(card, { proposalRef: 'p1', actionStatus: 'unknown' }), card);
  assert.equal(applyPendingActionResult(card, {}), card);
});

test('formats backend artifact values without parsing assistant markdown', () => {
  assert.equal(formatAdmissionProbability(0.68), '≤1%');
  assert.equal(formatAdmissionProbability(1), '≤1%');
  assert.equal(formatAdmissionProbability(38), '38%');
  assert.equal(formatRank(18320), '18320');
  assert.equal(normalizeConversationEvent({ type: 'planning.status', payload: {} }).type, 'planning.status');
});

test('unknown artifact returns empty value', () => {
  assert.equal(resolveArtifact({ artifactId: 'missing' }, {}), null);
});

test('evidence payload keeps dataVersion and limitations', () => {
  assert.deepEqual(
    formatEvidencePayload({ evidenceId: 'ev-1', dataVersion: '2026.09.07', limitations: ['样本有限'] }),
    { evidenceId: 'ev-1', dataVersion: '2026.09.07', limitations: ['样本有限'] },
  );
});

test('planning status hides tool names and raw arguments', () => {
  const event = normalizeConversationEvent({
    type: 'planning.status',
    payload: { tool: 'admission.get_history', arguments: { userId: 'secret' }, status: 'completed' },
  });
  assert.deepEqual(event, { type: 'planning.status', payload: { status: 'completed' } });
});

test('legacy reply and card events remain unchanged', () => {
  const reply = { type: 'reply', content: '旧回复' };
  const card = { type: 'card', content: '旧卡片' };
  assert.deepEqual(normalizeConversationEvent(reply), reply);
  assert.deepEqual(normalizeConversationEvent(card), card);
});

test('action proposed is normalized to a pending preview without apply fields', () => {
  assert.deepEqual(
    normalizeConversationEvent({
      type: 'action.proposed',
      payload: { proposalId: 'p1', summary: '调整方案', apply: true, sourceVersion: 42 },
    }),
    { type: 'action.proposed', payload: { proposalId: 'p1', summary: '调整方案', status: 'pending' } },
  );
});

test('normalizes structured major group facts without reading assistant text', () => {
  const event = normalizeConversationEvent({
    type: 'admission.facts.updated',
    content: '录取率 99%',
    payload: {
      admissionMode: 'majorGroup',
      admissionFacts: [
        {
          admissionMode: 'major_group',
          admissionUnitId: 'unit-1',
          schoolId: 'school-1',
          groupCode: '101',
          unitAdmissionRate: 45,
          riskTier: '冲',
          majorItems: [{ majorId: 'm-1', majorAdmissionRate: 85 }],
        },
      ],
      evidenceIds: ['ev-1'],
    },
  });

  assert.equal(event.type, 'admission.facts.updated');
  assert.equal(event.payload.admissionMode, 'major_group');
  assert.equal(event.payload.admissionFacts[0].unitAdmissionRate, 45);
  assert.equal(event.payload.admissionFacts[0].majorItems[0].majorAdmissionRate, 85);
  assert.deepEqual(event.payload.evidenceIds, ['ev-1']);
});

test('drops unsupported admission rates instead of displaying invented values', () => {
  const event = normalizeConversationEvent({
    type: 'admission.facts.updated',
    payload: {
      admissionMode: 'major',
      admissionFacts: [
        {
          admissionMode: 'major',
          admissionUnitId: 'unit-1',
          schoolId: 'school-1',
          majorId: 'm-1',
          unitAdmissionRate: 99.01,
          riskTier: '保',
        },
      ],
    },
  });

  assert.equal(event, null);
});

test('rejects a mismatched unit tier and malformed nested detail', () => {
  const event = normalizeConversationEvent({
    type: 'admission.facts.updated',
    payload: {
      admissionMode: 'major_group',
      admissionFacts: [{
        admissionMode: 'major_group',
        admissionUnitId: 'unit-1',
        schoolId: 'school-1',
        groupCode: '101',
        unitAdmissionRate: 70,
        riskTier: '稳',
        majorItems: [{ majorId: 'm-1', majorAdmissionRate: 100 }],
      }],
    },
  });

  assert.equal(event, null);
});

// ── v1 统一事件 ──────────────────────────────────────────────────────

test('v1 事件直通，且只放过白名单字段', () => {
  const event = {
    protocolVersion: 1,
    type: 'tool.progress',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    sequence: 3,
    payload: {
      itemId: 'i1',
      tool: 'admission.get_history',
      status: 'started',
      label: '正在查询历年录取',
      arguments: { private: 'do-not-display' },
    },
  };

  const normalized = normalizeConversationEvent(event);

  assert.equal(normalized.type, 'tool.progress');
  assert.equal(normalized.sequence, 3);
  assert.equal(normalized.payload.arguments, undefined, '参数原文不该进渲染面');
  assert.equal(normalized.payload.label, '正在查询历年录取');
});

test('缺协议字段的"像 v1"事件不被误判', () => {
  // 少一个 sequence 就不是 v1 事件；当成 v1 会让 reducer 收到 undefined 序号。
  const notV1 = {
    protocolVersion: 1,
    type: 'tool.progress',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    payload: {},
  };
  assert.equal(isConversationV1Event(notV1), false);
});

test('未知 v1 类型不直通', () => {
  const unknown = {
    protocolVersion: 1,
    type: 'something.brand.new',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    sequence: 1,
    payload: {},
  };
  assert.equal(isConversationV1Event(unknown), false);
});

test('旧信封里的进度帧被转换成带本地序号的 v1 事件', () => {
  const frame = {
    type: 'planning.status',
    session_id: '42',
    turnId: 't1',
    content: JSON.stringify({
      type: 'tool.progress',
      itemId: 'i1',
      stage: 'started',
      message: '正在查询历年录取',
    }),
  };

  const converted = toConversationEvent(frame, { sessionId: '42', streamEpoch: 'e1', sequence: 1 });

  assert.equal(converted.type, 'tool.progress');
  assert.equal(converted.sequence, 1);
  assert.equal(converted.payload.itemId, 'i1');
  assert.equal(converted.payload.status, 'started');
  assert.equal(converted.payload.label, '正在查询历年录取');
  // 本地序号不能跨重连去重——这一点必须能从事件上看出来。
  assert.equal(converted.localSequence, true);
});

test('旧信封里认不出类型的帧被丢弃，而不是画成默认气泡', () => {
  const frame = { type: 'text', content: '普通回复' };
  assert.equal(toConversationEvent(frame, { sessionId: '42', streamEpoch: 'e1', sequence: 1 }), null);
});

test('助手增量事件直通，且只保留 chunk/itemId', () => {
  const normalized = normalizeConversationEvent({
    protocolVersion: 1,
    type: 'assistant.delta',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    sequence: 4,
    payload: { chunk: '{"message": "你', itemId: 'msg_1', privateField: 'do-not-display' },
  });

  assert.equal(normalized.type, 'assistant.delta');
  assert.equal(normalized.payload.chunk, '{"message": "你');
  assert.equal(normalized.payload.itemId, 'msg_1');
  assert.equal(normalized.payload.privateField, undefined, '白名单外的字段不该进渲染面');
});

test('助手增量事件是合法的 v1 类型（服务端发了不会被整条丢掉）', () => {
  assert.equal(
    isConversationV1Event({
      protocolVersion: 1,
      type: 'assistant.delta',
      sessionId: '42',
      turnId: 't1',
      streamEpoch: 'e1',
      sequence: 1,
      payload: { chunk: 'x' },
    }),
    true,
  );
});

test('回合开始事件保留墙钟时间戳，白名单外的字段不过去', () => {
  // 时间戳只是诊断信息（排序仍按 sequence）——但白名单里没有位置的话它会被
  // 静默过滤掉：服务端发了也白发，这是"两边一起改"那条约定的一部分。
  const normalized = normalizeConversationEvent({
    protocolVersion: 1,
    type: 'turn.started',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    sequence: 1,
    payload: { startedAt: 1728000000000, internal: 'do-not-display' },
  });

  assert.equal(normalized.type, 'turn.started');
  assert.equal(normalized.payload.startedAt, 1728000000000);
  assert.equal(normalized.payload.internal, undefined, '白名单外的字段不该进渲染面');
});

test('补录成绩卡的结构化摘要随 diff 一起通过白名单', () => {
  // 卡片按 `diff.scoreUpdate` 渲染明细行（省份/科类/各科/总分/位次）——
  // 它在 `diff` 里面，跟着 diff 整份通过；白名单外的顶层字段照旧被滤掉。
  const normalized = normalizeConversationEvent({
    protocolVersion: 1,
    type: 'proposal.preview',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    sequence: 5,
    payload: {
      proposalRef: 'pending-score-1',
      sourceVersion: 8,
      diff: {
        title: '更新成绩',
        summary: '浙江省 · 总分 641',
        status: 'pending',
        requiresConfirmation: true,
        scoreUpdate: {
          provinceName: '浙江省',
          totalScore: 641,
          subjects: [{ subjectName: '语文', score: 118 }],
        },
      },
      internal: 'do-not-display',
    },
  });

  assert.equal(normalized.payload.proposalRef, 'pending-score-1');
  assert.equal(normalized.payload.diff.title, '更新成绩');
  assert.equal(normalized.payload.diff.scoreUpdate.totalScore, 641);
  assert.equal(normalized.payload.diff.scoreUpdate.subjects[0].score, 118);
  assert.equal(normalized.payload.internal, undefined, '白名单外的字段不该进渲染面');
});

test('失败原因、回执与 J3 动作元数据随动作结果通过白名单', () => {
  // "未生效"之外还要说得出**为什么**（110 / 40904 / 84009 / -1 …）——
  // 服务端发了 code/message，白名单不放行的话卡上只剩一句"未生效"。
  // J3：origin/actionType/scope/receipt 也要放行，同时仍是一张卡。
  const actualChanges = [{ type: 'add', volunteerIds: ['v2'], addedCount: 1 }];
  const reviewState = { summary: { passedCount: 10, warnCount: 4, riskCount: 0 } };
  const receipt = {
    operationId: 'op-1',
    actionType: 'add_units',
    countMode: 'volunteer',
    before: 45,
    after: 46,
    addedCount: 1,
    postconditionSatisfied: true,
  };
  const normalized = normalizeConversationEvent({
    protocolVersion: 1,
    type: 'conversationAction.result',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    sequence: 6,
    payload: {
      proposalRef: 'pending-score-1',
      actionStatus: 'applied',
      code: '0',
      message: '已生效',
      origin: 'user',
      actionType: 'add_units',
      scope: 'plan',
      receipt,
      actualChanges,
      reviewState,
      unknownField: 'do-not-display',
    },
  });

  assert.equal(normalized.payload.actionStatus, 'applied');
  assert.equal(normalized.payload.code, '0');
  assert.equal(normalized.payload.message, '已生效');
  assert.equal(normalized.payload.origin, 'user');
  assert.equal(normalized.payload.actionType, 'add_units');
  assert.equal(normalized.payload.scope, 'plan');
  assert.deepEqual(normalized.payload.receipt, receipt);
  assert.deepEqual(normalized.payload.actualChanges, actualChanges);
  assert.deepEqual(normalized.payload.reviewState, reviewState);
  assert.equal(normalized.payload.unknownField, undefined);
});

test('interpretation.preview 是合法 V1 事件，且只放行有界摘要字段', () => {
  const frame = {
    protocolVersion: 1,
    type: 'interpretation.preview',
    sessionId: '42',
    turnId: 't1',
    streamEpoch: 'e1',
    sequence: 3,
    payload: {},
  };
  assert.equal(isConversationV1Event(frame), true);

  const payload = sanitizeV1Payload('interpretation.preview', {
    status: 'completed',
    planVersion: 5,
    safetyCoverage: '有保底档位',
    scenarios: [{ label: 'base' }],
    baseLanding: { label: 'base' },
    caveatDetails: [
      { text: '审查：本省保底不足', level: 'hard', code: 'safety_guard' },
      { text: '结构说明，不是录取概率', level: 'soft' },
    ],
    // 原生结果里的额外字段不该流到页面。
    path: [{ id: 'u1' }],
    evidenceRefs: ['ev_x'],
  });

  assert.equal(payload.planVersion, 5);
  assert.equal(payload.safetyCoverage, '有保底档位');
  assert.deepEqual(payload.scenarios, [{ label: 'base' }]);
  assert.equal(payload.caveatDetails[0].level, 'hard');
  assert.equal(payload.caveatDetails[1].level, 'soft');
  assert.equal(payload.path, undefined);
  assert.equal(payload.evidenceRefs, undefined);
});
