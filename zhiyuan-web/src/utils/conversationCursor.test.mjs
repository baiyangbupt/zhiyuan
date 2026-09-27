import assert from 'node:assert/strict';
import test from 'node:test';

import { cursorFromState } from './conversationCursor.mjs';

test('真代际 + 有效序号 → 给出游标', () => {
  assert.deepEqual(cursorFromState({ streamEpoch: 'epoch-1', lastSequence: 7 }), {
    epoch: 'epoch-1',
    sequence: 7,
  });
});

test('老信封的本地序号不能当游标（localSequence 不可用于恢复）', () => {
  // 这条是"别把假的编号发出去"：发出去服务端会按它补，补出来的东西对不上页面状态。
  assert.equal(cursorFromState({ streamEpoch: 'local', lastSequence: 7 }), null);
});

test('还没采纳代际时没有游标', () => {
  assert.equal(cursorFromState({ streamEpoch: null, lastSequence: 0 }), null);
  assert.equal(cursorFromState({ streamEpoch: '', lastSequence: 0 }), null);
});

test('序号必须是正整数：0／负数／小数／非数字都不行', () => {
  for (const sequence of [0, -1, 1.5, '7', null, undefined, Number.NaN]) {
    assert.equal(
      cursorFromState({ streamEpoch: 'epoch-1', lastSequence: sequence }),
      null,
      `sequence=${String(sequence)} 不该给出游标`,
    );
  }
});

test('状态缺失或不是对象时返回 null，不抛', () => {
  assert.equal(cursorFromState(null), null);
  assert.equal(cursorFromState(undefined), null);
  assert.equal(cursorFromState({}), null);
});
