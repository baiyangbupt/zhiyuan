import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildClarificationAnswerFrame,
  buildPendingConfirmationFrame,
  buildTurnInterruptFrame,
  buildTurnSteerFrame,
  stableClientRequestId,
} from './conversationProtocol.mjs';

test('作答帧走独立字段，不复用 conversationAction', () => {
  const frame = buildClarificationAnswerFrame({
    sessionId: '42',
    turnId: 't1',
    requestId: 'q1',
    clientRequestId: 'answer-1',
    answer: { inputKind: 'choice', answers: { major: { answers: ['计算机类'] } } },
  });

  assert.equal(frame.type, 'clarificationAnswer');
  assert.equal(frame.content, '', '控制消息必须带空串');
  assert.equal(frame.clarificationAnswer.requestId, 'q1');
  assert.equal(frame.clarificationAnswer.inputKind, 'choice');
  // conversationAction 的语义是"确认/取消一个提案"，混用会让两种确认无法区分。
  assert.equal(frame.conversationAction, undefined);
});

test('form 作答同样走独立字段，并保留 action/content 形状', () => {
  const frame = buildClarificationAnswerFrame({
    sessionId: '42',
    turnId: 't1',
    requestId: 'q2',
    clientRequestId: 'answer-2',
    answer: { inputKind: 'form', action: 'accept', content: { confirm: true } },
  });

  assert.equal(frame.clarificationAnswer.inputKind, 'form');
  assert.equal(frame.clarificationAnswer.action, 'accept');
  assert.deepEqual(frame.clarificationAnswer.content, { confirm: true });
});

test('停止帧带空内容，且必须有回合号', () => {
  const frame = buildTurnInterruptFrame({ sessionId: '42', turnId: 't1', clientRequestId: 'stop-1' });

  assert.equal(frame.type, 'turnInterrupt');
  assert.equal(frame.content, '');
  assert.equal(frame.turnId, 't1');

  // 没有回合号的停止请求是无处可去的：服务端会按 turn_mismatch 拒掉，
  // 所以在这里就拦住，而不是发出去等一个"没生效"。
  assert.throws(
    () => buildTurnInterruptFrame({ sessionId: '42', turnId: '', clientRequestId: 'stop-1' }),
    /missing_turnId/,
  );
});

test('转述帧必须带内容——空的转述等于什么都没说', () => {
  const frame = buildTurnSteerFrame({
    sessionId: '42',
    turnId: 't1',
    text: '再保守一点',
    clientRequestId: 'steer-1',
  });

  assert.equal(frame.content, '再保守一点');
  assert.throws(
    () => buildTurnSteerFrame({ sessionId: '42', turnId: 't1', text: '   ', clientRequestId: 'steer-1' }),
    /missing_text/,
  );
});

test('缺会话或请求号时直接拒绝，不发出半个请求', () => {
  assert.throws(() => buildTurnInterruptFrame({ sessionId: '', turnId: 't1', clientRequestId: 'x' }), /missing_sessionId/);
  assert.throws(() => buildClarificationAnswerFrame({ sessionId: '42', turnId: 't1', requestId: 'q1', clientRequestId: '', answer: {} }), /missing_clientRequestId/);
});

test('重发沿用同一个 clientRequestId', () => {
  // 换新的 id 重试，等于让服务端把同一次作答执行两次。
  assert.equal(stableClientRequestId('answer', 'q1'), stableClientRequestId('answer', 'q1'));
});

test('待采纳确认帧：content 必须是空串（服务端的 schema 就这么写）', () => {
  // 这条钉的是**踩过的坑** ✓：手拼帧时把 `content` 塞成了对象 ✓，
  // 而 `WSMessage.content` 是 `str` ✓ → 服务端拒收 ✓、**且不记日志** ✗✓
  //（实测：点"放弃"什么都没发生 ✓，agent 日志里只有握手 ✓）。
  const frame = buildPendingConfirmationFrame({
    sessionId: '900047',
    userId: '900002',
    action: 'cancel',
    proposalRef: 'ugp_1',
    sourceVersion: 0,
    clientRequestId: 'proposal-ugp_1',
  });

  assert.equal(frame.type, 'pendingConfirmation');
  assert.equal(frame.content, ''); // ← 空串 ✓，不是对象 ✗
  assert.equal(typeof frame.content, 'string');
  assert.equal(frame.conversationAction.actionType, 'cancel_proposal');
  assert.equal(frame.conversationAction.expectedSourceVersion, 0);
  assert.equal(frame.conversationAction.intent, 'explicit');
});

test('采纳与放弃只差 actionType', () => {
  const base = { sessionId: 's', userId: 'u', proposalRef: 'p', sourceVersion: 1 };
  assert.equal(
    buildPendingConfirmationFrame({ ...base, action: 'confirm' }).conversationAction.actionType,
    'confirm_proposal',
  );
  assert.equal(
    buildPendingConfirmationFrame({ ...base, action: 'cancel' }).conversationAction.actionType,
    'cancel_proposal',
  );
});
