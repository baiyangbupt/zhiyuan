import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatAdmissionProbability,
  formatRank,
  formatEvidencePayload,
  normalizeConversationEvent,
  resolveArtifact,
} from './conversationEvents.mjs';

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
