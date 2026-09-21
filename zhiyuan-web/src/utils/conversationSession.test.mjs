import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createConversationState,
  hasStructuredUnderstanding,
  pendingClarifications,
  reduceConversation,
} from './conversationSession.mjs';

const event = (overrides = {}) => ({
  protocolVersion: 1,
  sessionId: '42',
  turnId: 't',
  streamEpoch: 'e1',
  sequence: 1,
  type: 'turn.phase',
  payload: {},
  ...overrides,
});

const baseline = () => {
  const state = createConversationState('42');
  return { ...state, streamEpoch: 'e1' };
};

test('重复事件不产生第二次完成', () => {
  const initial = { ...baseline(), lastSequence: 0 };
  const done = event({ type: 'turn.completed', payload: { executionStatus: 'partial' } });

  const once = reduceConversation(initial, done);
  const twice = reduceConversation(once, done);

  assert.deepEqual(twice, once);
  assert.equal(once.turns.t.executionStatus, 'partial');
  assert.equal(once.turns.t.terminal, true);
});

test('旧会话的事件不污染当前页', () => {
  const state = baseline();
  const foreign = event({ sessionId: '99', type: 'turn.completed' });

  assert.equal(reduceConversation(state, foreign), state);
});

test('序号有缺口时要求 resync，而不是把洞补平', () => {
  const state = { ...baseline(), lastSequence: 3 };

  const gap = reduceConversation(state, event({ sequence: 5 }));

  assert.equal(gap.needsResync, true);
  assert.equal(gap.lastSequence, 3, '缺口不该被当成正常前进');
});

test('代际变化时要求 resync', () => {
  const state = { ...baseline(), lastSequence: 3 };

  const changed = reduceConversation(state, event({ streamEpoch: 'epoch-2', sequence: 4 }));

  assert.equal(changed.needsResync, true);
});

test('首帧接受服务端给的代际，不要求序号从 1 开始', () => {
  const fresh = createConversationState('42');

  const first = reduceConversation(fresh, event({ sequence: 7 }));

  assert.equal(first.needsResync, false);
  assert.equal(first.streamEpoch, 'e1');
  assert.equal(first.lastSequence, 7);
});

test('resync 快照重置基线而不是接在基线后面', () => {
  const state = { ...baseline(), lastSequence: 9, needsResync: true };

  const resynced = reduceConversation(
    state,
    event({
      type: 'session.resync',
      sequence: 0,
      streamEpoch: 'epoch-2',
      payload: { baseline: { lastSequence: 0, turns: { t2: { id: 't2', answer: { message: '历史' } } } } },
    }),
  );

  assert.equal(resynced.needsResync, false);
  assert.equal(resynced.streamEpoch, 'epoch-2');
  assert.equal(resynced.turns.t2.answer.message, '历史');
  assert.equal(resynced.turns.t, undefined, '重置应当丢掉旧基线');
});

test('applied 之后迟到的 applying 不把它刷回去', () => {
  const applied = reduceConversation(
    baseline(),
    event({
      sequence: 1,
      type: 'conversationAction.result',
      payload: { actionStatus: 'applied', proposalRef: 'p1' },
    }),
  );

  const stale = reduceConversation(
    applied,
    event({
      sequence: 2,
      type: 'conversationAction.result',
      payload: { actionStatus: 'applying', proposalRef: 'p1' },
    }),
  );

  assert.equal(stale.turns.t.actionResult.actionStatus, 'applied');
});

test('工具进度按 itemId 归并而不是堆成一串', () => {
  const started = reduceConversation(
    baseline(),
    event({
      sequence: 1,
      type: 'tool.progress',
      payload: { itemId: 'i1', tool: 'admission.get_history', status: 'started', label: '正在查询历年录取' },
    }),
  );
  const completed = reduceConversation(
    started,
    event({
      sequence: 2,
      type: 'tool.progress',
      payload: { itemId: 'i1', tool: 'admission.get_history', status: 'completed', label: '正在查询历年录取' },
    }),
  );

  assert.equal(Object.keys(completed.turns.t.steps).length, 1);
  assert.equal(completed.turns.t.steps.i1.status, 'completed');
});

test('运行结束与诉求完成是两个字段，互不推导', () => {
  const state = reduceConversation(
    baseline(),
    event({
      sequence: 1,
      type: 'turn.completed',
      payload: { executionStatus: 'partial', toolStatus: 'completed' },
    }),
  );

  // 工具全成功不能把"用户诉求"抬成 completed —— 那是服务端 P2 的同一类错误。
  assert.equal(state.turns.t.executionStatus, 'partial');
  assert.equal(state.turns.t.toolStatus, 'completed');
});

test('澄清卡的待答与已答可区分', () => {
  const asked = reduceConversation(
    baseline(),
    event({
      sequence: 1,
      type: 'clarification.requested',
      payload: { requestId: 'q1', inputKind: 'choice', questions: [{ id: 'major' }] },
    }),
  );
  assert.equal(pendingClarifications(asked.turns.t).length, 1);

  const answered = reduceConversation(
    asked,
    event({
      sequence: 2,
      type: 'clarification.resolved',
      payload: { requestId: 'q1', status: 'answered' },
    }),
  );
  assert.equal(pendingClarifications(answered.turns.t).length, 0);
});

test('未知事件类型不改变状态，也不报错', () => {
  const state = baseline();
  const unknown = reduceConversation(state, event({ type: 'something.new', sequence: 1 }));

  // 不认识的类型仍会推进序号（它就是一条合法事件），但不产生任何渲染面——
  // 建一个空回合会让页面上多出一条什么都没有的气泡。
  assert.equal(unknown.lastSequence, 1);
  assert.equal(unknown.turns.t, undefined);
});

test('乱序到达的旧事件被丢弃', () => {
  const state = { ...baseline(), lastSequence: 4 };

  assert.equal(reduceConversation(state, event({ sequence: 2 })), state);
});

test('非法输入不炸', () => {
  const state = baseline();

  assert.equal(reduceConversation(state, null), state);
  assert.equal(reduceConversation(null, event()), null);
});

test('没有结构化理解时不生成理解卡', () => {
  // 揣测用户意图的卡是有害的：用户会以为系统听懂了。
  assert.equal(hasStructuredUnderstanding(undefined), false);
  assert.equal(hasStructuredUnderstanding({}), false);
  assert.equal(hasStructuredUnderstanding({ summary: '   ' }), false);
  assert.equal(hasStructuredUnderstanding({ entities: [], constraints: [] }), false);
});

test('有摘要或实体或约束时才算有结构化理解', () => {
  assert.equal(hasStructuredUnderstanding({ summary: '你想查计算机类' }), true);
  assert.equal(hasStructuredUnderstanding({ entities: ['浙江大学'] }), true);
  assert.equal(hasStructuredUnderstanding({ constraints: ['学费≤10000'] }), true);
});
