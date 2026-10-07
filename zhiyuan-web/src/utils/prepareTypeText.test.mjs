import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizePrepareTypeCode,
  isPredictPrepareType,
  isVolunteerPrepareType,
} from './prepareTypeText.mjs';

// **事故回归**：PREDICT 会话的 desc 常是"智能填报"（后端 desc 混用），
// 旧实现先判 `智能填报` 字样 → 误判成 VOLUNTEER → 弹"2026年招生计划数据已更新" +
// planYear 取 2026，与同一会话后端"模拟填报使用2025年…"摘要同页矛盾。
// code 优先后，这条必须回到 PREDICT。
test('code=PREDICT + desc=智能填报 → PREDICT（旧实现误判 VOLUNTEER 的回归）', () => {
  assert.equal(normalizePrepareTypeCode('PREDICT', '智能填报'), 'PREDICT');
  assert.equal(isPredictPrepareType('PREDICT', '智能填报'), true);
  assert.equal(isVolunteerPrepareType('PREDICT', '智能填报'), false);
});

test('code=VOLUNTEER + desc=智能填报 → VOLUNTEER', () => {
  assert.equal(normalizePrepareTypeCode('VOLUNTEER', '智能填报'), 'VOLUNTEER');
  assert.equal(isVolunteerPrepareType('VOLUNTEER', '智能填报'), true);
});

test('code=PREDICT + desc=模拟填报 → PREDICT（desc 两词并存也不打架）', () => {
  assert.equal(normalizePrepareTypeCode('PREDICT', '模拟填报'), 'PREDICT');
});

test('desc 兜底：无 code 时按本义词判定', () => {
  assert.equal(normalizePrepareTypeCode('', '模拟填报'), 'PREDICT');
  assert.equal(normalizePrepareTypeCode(null, '智能填报'), 'VOLUNTEER');
  assert.equal(normalizePrepareTypeCode(undefined, '模拟填报'), 'PREDICT');
});

test('大小写、空白与空值安全', () => {
  assert.equal(normalizePrepareTypeCode('predict', ''), 'PREDICT');
  assert.equal(normalizePrepareTypeCode('  volunteer  ', ''), 'VOLUNTEER');
  assert.equal(normalizePrepareTypeCode('', ''), '');
  assert.equal(normalizePrepareTypeCode(null, null), '');
  assert.equal(normalizePrepareTypeCode(undefined, undefined), '');
  assert.equal(isPredictPrepareType(undefined, undefined), false);
  assert.equal(isVolunteerPrepareType(undefined, undefined), false);
});
