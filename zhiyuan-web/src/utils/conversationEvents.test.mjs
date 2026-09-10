import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatAdmissionProbability,
  formatRank,
  formatEvidencePayload,
  normalizeConversationEvent,
  resolveArtifact,
  parseConversationActionResult,
  applyPendingActionResult,
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
  assert.equal(formatAdmissionProbability(0.68), '68%');
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
