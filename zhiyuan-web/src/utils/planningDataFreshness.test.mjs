import test from 'node:test';
import assert from 'node:assert/strict';

import {
  hasDataFreshnessChangeSummary,
  resolveCandidateRefreshMode,
  shouldShowDataFreshnessNotice,
} from './planningDataFreshness.mjs';

test('data freshness notice only opens for detailed changed state that should notify', () => {
  assert.equal(shouldShowDataFreshnessNotice({ statusCode: 'current', shouldNotify: false, changedCount: 2 }), false);
  assert.equal(shouldShowDataFreshnessNotice({ statusCode: 'changed', shouldNotify: false, changedCount: 2 }), false);
  assert.equal(shouldShowDataFreshnessNotice({ statusCode: 'changed', shouldNotify: true, summary: '检测到高途招生计划源数据有更新' }), false);
  assert.equal(shouldShowDataFreshnessNotice({ statusCode: 'changed', shouldNotify: true, removedCount: 1 }), true);
  assert.equal(shouldShowDataFreshnessNotice({ statusCode: 'changed', summary: '招生计划数据已变化：更新 1 项。' }), true);
});

test('tooltip can still show recent summary when current state keeps historical counts', () => {
  assert.equal(hasDataFreshnessChangeSummary({ statusCode: 'current', shouldNotify: false, updatedCount: 1 }), true);
  assert.equal(shouldShowDataFreshnessNotice({ statusCode: 'current', shouldNotify: false, updatedCount: 1 }), false);
});

test('candidate refresh mode avoids second source sync for detailed candidate changes', () => {
  assert.equal(resolveCandidateRefreshMode({ statusCode: 'current', requiresCandidateRefresh: true, changedCount: 1 }), 'none');
  assert.equal(resolveCandidateRefreshMode({ statusCode: 'changed', requiresCandidateRefresh: false, changedCount: 1 }), 'none');
  assert.equal(resolveCandidateRefreshMode({ statusCode: 'changed', requiresCandidateRefresh: true, summary: '检测到高途招生计划源数据有更新' }), 'source_sync');
  assert.equal(resolveCandidateRefreshMode({ statusCode: 'changed', requiresCandidateRefresh: true, updatedCount: 1 }), 'local_query');
});
