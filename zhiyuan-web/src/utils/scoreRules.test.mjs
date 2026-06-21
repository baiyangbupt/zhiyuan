import test from 'node:test';
import assert from 'node:assert/strict';

import {
  resolveSubjectScoreMax,
  resolveTotalScoreLabel,
  shouldAutoCalculateTotalScore,
  validateHainanTotalScore,
} from './scoreRules.mjs';

test('subject score max follows province-specific rules', () => {
  assert.equal(resolveSubjectScoreMax('460000', 'main'), 900);
  assert.equal(resolveSubjectScoreMax('460000', 'elective'), 900);
  assert.equal(resolveSubjectScoreMax('310000', 'elective'), 70);
  assert.equal(resolveSubjectScoreMax('110000', 'main'), 150);
  assert.equal(resolveSubjectScoreMax('110000', 'elective'), 100);
});

test('hainan total score is manual final score in 100-900 range', () => {
  assert.equal(validateHainanTotalScore(undefined), '请输入最终总分');
  assert.equal(validateHainanTotalScore(99), '最终总分范围为100～900分');
  assert.equal(validateHainanTotalScore(901), '最终总分范围为100～900分');
  assert.equal(validateHainanTotalScore(650), null);
  assert.equal(resolveTotalScoreLabel('460000'), '最终总分');
  assert.equal(resolveTotalScoreLabel('110000'), '高考总成绩');
  assert.equal(shouldAutoCalculateTotalScore('460000'), false);
  assert.equal(shouldAutoCalculateTotalScore('110000'), true);
});
