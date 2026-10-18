import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createConversationState,
  hasStructuredUnderstanding,
  orderedSteps,
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

test('同一 operationId 的重复回执只保留第一张卡', () => {
  const first = reduceConversation(
    baseline(),
    event({
      sequence: 1,
      type: 'conversationAction.result',
      payload: {
        actionStatus: 'applied',
        proposalRef: 'p1',
        actionType: 'move_units',
        receipt: { operationId: 'op-1', before: 44, after: 44 },
      },
    }),
  );

  const duplicate = reduceConversation(
    first,
    event({
      sequence: 2,
      type: 'conversationAction.result',
      payload: {
        actionStatus: 'applied',
        proposalRef: 'p1',
        actionType: 'duplicate-must-not-replace',
        receipt: { operationId: 'op-1', before: 1, after: 1 },
      },
    }),
  );

  assert.equal(duplicate.turns.t.actionResult.receipt.before, 44);
  assert.equal(duplicate.turns.t.actionResult.actionType, 'move_units');
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

test('增量文本按序累加进回合，终态到达时整段替换', () => {
  const first = reduceConversation(
    baseline(),
    event({ sequence: 1, type: 'assistant.delta', payload: { chunk: '{"message": "你' } }),
  );
  const second = reduceConversation(
    first,
    event({ sequence: 2, type: 'assistant.delta', payload: { chunk: '好"}' } }),
  );
  assert.equal(second.turns.t.answerStream, '{"message": "你好"}');

  const terminal = reduceConversation(
    second,
    event({ sequence: 3, type: 'assistant.completed', payload: { message: '你好' } }),
  );
  // 流式文本只是"可丢弃的提示"：终态是权威——整段替换，不叠加成两份。
  assert.equal(terminal.turns.t.answerStream, '');
  assert.equal(terminal.turns.t.answer.message, '你好');
});

test('已终态的回合不再接受迟到的增量，且 run 结束也作废流式文本', () => {
  const streaming = reduceConversation(
    baseline(),
    event({ sequence: 1, type: 'assistant.delta', payload: { chunk: '半截' } }),
  );
  const done = reduceConversation(
    streaming,
    event({ sequence: 2, type: 'turn.completed', payload: { executionStatus: 'partial' } }),
  );
  // 中止/失败的一轮不该把半截流文本留在回合里（终态一到就清）。
  assert.equal(done.turns.t.answerStream, '');

  const stray = reduceConversation(
    done,
    event({ sequence: 3, type: 'assistant.delta', payload: { chunk: '晚到的增量' } }),
  );
  assert.equal(stray.turns.t.answerStream, '', '终态之后迟到的增量不许把答案刷回流式样子');
  assert.equal(stray.lastSequence, 3, '它本身是合法序号的合法事件，序号照常推进');
});

test('空 chunk 不建回合（免得页面上多一条什么都没画的气泡）', () => {
  const state = reduceConversation(
    baseline(),
    event({ sequence: 1, type: 'assistant.delta', payload: { chunk: '' } }),
  );

  assert.equal(state.turns.t, undefined);
  assert.equal(state.lastSequence, 1);
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

test('老信封的本地占位代际不挡住真代际（混流不该判换代）', () => {
  // 手里那个代际只是老信封的**本地占位**（`local` ✓）时，真 V1 事件一到必须直接采纳，
  // 不能判"换代"→ resync → 清空界面 ✓。
  // 实测背景：失败回合总会带一条老信封兜底帧 ✓（网关有意两条都发 ✓），
  // 于是每失败一次界面就被清一次 ✓，用户看到的是"回合块没了" ✓。
  const withLocal = reduceConversation(
    createConversationState('42'),
    event({ streamEpoch: 'local', sequence: 3, type: 'recoverable.error', payload: { message: 'x' } }),
  );
  assert.equal(withLocal.streamEpoch, 'local');

  const after = reduceConversation(
    withLocal,
    event({ streamEpoch: 'epoch-real', sequence: 40, type: 'tool.progress' }),
  );

  assert.equal(after.needsResync, false, '真代际到达不该判 resync');
  assert.equal(after.streamEpoch, 'epoch-real');
  assert.equal(after.lastSequence, 40, '采纳代际时要一并采纳序号');
});

test('两条本地占位之间照旧连续（同一条 lane 不该自我换代）', () => {
  const first = reduceConversation(
    createConversationState('42'),
    event({ streamEpoch: 'local', sequence: 1, type: 'tool.progress' }),
  );
  const second = reduceConversation(
    first,
    event({ streamEpoch: 'local', sequence: 2, type: 'assistant.completed', payload: { message: 'x' } }),
  );
  assert.equal(second.needsResync, false);
  assert.equal(second.lastSequence, 2);
});

test('真代际之间照旧判换代（这条不能放松）', () => {
  const state = reduceConversation(
    createConversationState('42'),
    event({ streamEpoch: 'epoch-a', sequence: 5, type: 'tool.progress' }),
  );
  const after = reduceConversation(
    state,
    event({ streamEpoch: 'epoch-b', sequence: 6, type: 'tool.progress' }),
  );
  assert.equal(after.needsResync, true, '两条真时间线之间必须 resync');
});

test('真代际在手时，老信封的本地帧既不顶替也不判缺口', () => {
  // 探针实测的顺序（F15 ✓）：V1 的 progress/error/completed 先到 ✓（真代际 ✓），
  // 老信封的兜底帧**最后到** ✓ —— 它必须只折叠内容，不能碰代际与序号、更不能判 resync ✓。
  const real = reduceConversation(
    createConversationState('42'),
    event({ streamEpoch: 'epoch-real', sequence: 60, type: 'turn.completed' }),
  );
  assert.equal(real.needsResync, false);

  const after = reduceConversation(
    real,
    event({
      streamEpoch: 'local',
      sequence: 4,
      type: 'recoverable.error',
      payload: { message: '当前对话引擎暂时不可用，请稍后重试。' },
    }),
  );

  assert.equal(after.needsResync, false, '本地帧不该把真时间线判成缺口');
  assert.equal(after.streamEpoch, 'epoch-real', '代际不许被顶替');
  assert.equal(after.lastSequence, 60, '序号不许回退');
  assert.equal(after.turns.t.error.message, '当前对话引擎暂时不可用，请稍后重试。', '内容照常折叠');
});

test('后到的老信封空文案不许把已有错误文案覆盖成空', () => {
  // F15 探针里的顺序：V1 的 `recoverable.error` 先到（带服务端的具体文案 ✓），
  // 老信封兜底帧后到（失败结果里没有 `reply` → `message` 是空串 ✗，见 server.py 的
  // `_native_reply_frame`）。整体覆盖会把文案擦成空，用户只剩渲染层那句兜底——
  // 空值必须被拦住。
  const withMessage = reduceConversation(
    baseline(),
    event({
      sequence: 1,
      type: 'recoverable.error',
      payload: { code: 'output_schema_invalid: responseType', message: '当前对话引擎暂时不可用，请稍后重试。' },
    }),
  );

  const afterLegacy = reduceConversation(
    withMessage,
    event({
      streamEpoch: 'local',
      sequence: 2,
      type: 'recoverable.error',
      payload: { message: '' },
    }),
  );

  assert.equal(afterLegacy.needsResync, false);
  assert.equal(
    afterLegacy.turns.t.error.message,
    '当前对话引擎暂时不可用，请稍后重试。',
    '空文案不许覆盖非空文案',
  );
});

test('后到的非空错误文案照旧覆盖（只拦空值）', () => {
  const first = reduceConversation(
    baseline(),
    event({ sequence: 1, type: 'recoverable.error', payload: { message: '旧文案' } }),
  );
  const second = reduceConversation(
    first,
    event({ sequence: 2, type: 'recoverable.error', payload: { message: '新文案' } }),
  );

  assert.equal(second.turns.t.error.message, '新文案');
});

test('补录卡的 scoreUpdate 摘要原样进回合', () => {
  // 卡片按 `proposal.diff.scoreUpdate` 渲染明细行（省份/科类/各科/总分/位次）——
  // reducer 不做二次加工（它拿到的已是白名单过滤后的合同形状）。
  const reduced = reduceConversation(
    baseline(),
    event({
      type: 'proposal.preview',
      payload: {
        proposalRef: 'pending-score-1',
        sourceVersion: 8,
        diff: {
          title: '更新成绩',
          status: 'pending',
          requiresConfirmation: true,
          scoreUpdate: {
            provinceName: '浙江省',
            totalScore: 641,
            subjects: [{ subjectName: '语文', score: 118 }],
          },
        },
      },
    }),
  );

  assert.equal(reduced.turns.t.proposal.diff.scoreUpdate.totalScore, 641);
  assert.equal(reduced.turns.t.proposal.diff.scoreUpdate.subjects[0].score, 118);
  assert.equal(reduced.turns.t.proposal.diff.requiresConfirmation, true);
});

test('失败结果的 code/message 与终态一起留在回合里', () => {
  // 卡面失败原因（`proposal-failure-reason`）读的就是这两个字段——
  // reducer 把它们与 actionStatus 一起保留，不许只留状态丢原因。
  const reduced = reduceConversation(
    baseline(),
    event({
      type: 'conversationAction.result',
      payload: {
        actionStatus: 'failed',
        proposalRef: 'pending-score-1',
        code: '110',
        message: '成绩校验未通过：缺少数学',
      },
    }),
  );

  assert.equal(reduced.turns.t.actionResult.actionStatus, 'failed');
  assert.equal(reduced.turns.t.actionResult.code, '110');
  assert.equal(reduced.turns.t.actionResult.message, '成绩校验未通过：缺少数学');
});

test('连续的同工具同标签进度合并为一条并带次数', () => {
  // 2026-10-17 真事故：一个续接回合 15 次「核对选科要求」逐行铺开刷屏。
  // 合并只发生在**连续**段内；中间夹了别的工具就断开。
  let state = baseline();
  const push = (sequence, itemId, label, tool = 'admission.check_eligibility') =>
    reduceConversation(
      state,
      event({
        sequence,
        type: 'tool.progress',
        payload: { itemId, tool, status: 'completed', label },
      }),
    );

  state = push(1, 'a', '核对选科要求');
  state = push(2, 'b', '核对选科要求');
  state = push(3, 'c', '核对选科要求');
  state = push(4, 'd', '检索专业', 'catalog.search_majors');
  state = push(5, 'e', '核对选科要求');

  const steps = orderedSteps(state.turns.t);
  assert.equal(steps.length, 3);
  assert.equal(steps[0].label, '核对选科要求');
  assert.equal(steps[0].count, 3);
  assert.equal(steps[1].label, '检索专业');
  assert.equal(steps[1].count, 1);
  assert.equal(steps[2].count, 1, '夹了别的工具就断开，不跨段合并');

  // 同一 itemId 的 start/completed 在 reducer 里已经归并成一条，这里不会数成两次。
  state = push(6, 'e', '核对选科要求');
  assert.equal(orderedSteps(state.turns.t)[2].count, 1);
});

test('同工具不同标签不合并', () => {
  let state = baseline();
  state = reduceConversation(
    state,
    event({
      sequence: 1,
      type: 'tool.progress',
      payload: { itemId: 'a', tool: 'admission.check_eligibility', status: 'completed', label: '核对选科要求' },
    }),
  );
  state = reduceConversation(
    state,
    event({
      sequence: 2,
      type: 'tool.progress',
      payload: { itemId: 'b', tool: 'admission.check_eligibility', status: 'completed', label: '核对再选科目' },
    }),
  );

  const steps = orderedSteps(state.turns.t);
  assert.equal(steps.length, 2);
  assert.deepEqual(steps.map(step => step.count), [1, 1]);
});

test('interpretation.preview 落到回合的解读卡，后到覆盖先到（同回合只留一张）', () => {
  const first = reduceConversation(
    baseline(),
    event({
      type: 'interpretation.preview',
      payload: { status: 'completed', planVersion: 5, safetyCoverage: '有保底档位' },
    }),
  );
  const second = reduceConversation(
    first,
    event({
      sequence: 2,
      type: 'interpretation.preview',
      payload: { status: 'completed', planVersion: 6, safetyCoverage: '无保底档位' },
    }),
  );

  assert.equal(second.turns.t.interpretation.planVersion, 6);
  assert.equal(second.turns.t.interpretation.safetyCoverage, '无保底档位');
});
