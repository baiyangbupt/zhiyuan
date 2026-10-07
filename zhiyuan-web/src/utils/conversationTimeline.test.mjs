import assert from 'node:assert/strict';
import test from 'node:test';

import { buildConversationTimeline, normalizeTimelineText, turnAnchorText } from './conversationTimeline.mjs';

// 真实形状（2026-10-07 会话 10041967 实测）：REST 历史 id 为数字、messageFrom '0'=助手 '1'=用户
const userMsg = (id, content) => ({ id, messageFrom: '1', contentType: 'TEXT', content });
const aiMsg = (id, content) => ({ id, messageFrom: '0', contentType: 'TEXT', content });
const turn = (id, message, startedAt, extra = {}) => ({
  id,
  startedAt,
  terminal: true,
  answer: message === null ? null : { message },
  ...extra,
});

const kinds = items => items.map(item => (item.kind === 'turn' ? `T${item.turn.id}` : item.message.id));

test('冷加载（无回合）：顺序与历史一致，逐条画一份', () => {
  const messages = [userMsg(1, '你好'), aiMsg(2, '收到'), userMsg(3, '再问')];
  const items = buildConversationTimeline({ messages, turns: [] });
  assert.deepEqual(kinds(items), [1, 2, 3]);
});

test('一轮问答后：回合块锚到答案记录的位置，问答交错（不再是"问题在上答案在下"）', () => {
  const messages = [userMsg(1, '你好'), aiMsg(2, '收到'), userMsg(3, '第二问'), aiMsg(4, '好的')];
  const items = buildConversationTimeline({
    messages,
    turns: [turn('t1', '收到', 100), turn('t2', '好的', 200)],
  });
  // 2 和 4 被回合块认领：u1 T1 u3 T2 —— 助手不再各画两份
  assert.deepEqual(kinds(items), [1, 'Tt1', 3, 'Tt2']);
});

test('答案尚未落进历史（在飞/刷新未到）：回合块排末尾，不吞任何历史', () => {
  const messages = [userMsg(1, '你好'), aiMsg(2, '收到'), userMsg(3, '第二问')];
  const items = buildConversationTimeline({ messages, turns: [turn('t1', '收到', 100), turn('t2', '好的', 200)] });
  assert.deepEqual(kinds(items), [1, 'Tt1', 3, 'Tt2']);
});

test('认领是从新到旧：只有最新一轮在手里时锚到最新那条同文记录', () => {
  // 同文两轮（用户实测场景：重复问"请只回两个字"）——历史里两条同文记录
  const messages = [userMsg(1, '第1问'), aiMsg(2, '请讲'), userMsg(3, '第2问'), aiMsg(4, '请讲')];
  const items = buildConversationTimeline({ messages, turns: [turn('t2', '请讲', 200)] });
  // 最新回合认领第 4 条（最新），第 2 条历史照常画 → 内容一条不少
  assert.deepEqual(kinds(items), [1, 2, 3, 'Tt2']);
});

test('同文多轮各自认领：一对一，互不吞并（旧 v1AnsweredTexts 会两条一起滤掉）', () => {
  const messages = [userMsg(1, '第1问'), aiMsg(2, '请讲'), userMsg(3, '第2问'), aiMsg(4, '请讲')];
  const items = buildConversationTimeline({
    messages,
    turns: [turn('t1', '请讲', 100), turn('t2', '请讲', 200)],
  });
  assert.deepEqual(kinds(items), [1, 'Tt1', 3, 'Tt2']);
});

test('空白差异不挡锚定（归一：折叠空白再去首尾）', () => {
  const messages = [aiMsg(2, '好  的\n在的')];
  const items = buildConversationTimeline({ messages, turns: [turn('t1', ' 好 的 在的 ', 100)] });
  assert.deepEqual(kinds(items), ['Tt1']);
});

test('错误回合：用 error.message 锚定（与渲染口径一致）', () => {
  const messages = [userMsg(1, '在吗'), aiMsg(2, '服务开小差了，请稍后再试')];
  const items = buildConversationTimeline({
    messages,
    turns: [{ id: 't1', startedAt: 100, terminal: true, answer: null, error: { message: '服务开小差了，请稍后再试' } }],
  });
  assert.deepEqual(kinds(items), [1, 'Tt1']);
});

test('非终态回合永不锚定：排末尾（在飞的那一轮就该在底部）', () => {
  const messages = [userMsg(1, '你好'), aiMsg(2, '收到'), userMsg(3, '在吗')];
  const items = buildConversationTimeline({
    messages,
    turns: [turn('t1', '收到', 100), { id: 't2', startedAt: 200, terminal: false, answer: null }],
  });
  assert.deepEqual(kinds(items), [1, 'Tt1', 3, 'Tt2']);
});

test('未锚定回合按 startedAt 升序排末尾（旧在前、新在后，最后一块永远是新一轮）', () => {
  const messages = [userMsg(1, '你好')];
  const items = buildConversationTimeline({
    messages,
    turns: [turn('t9', '晚', 900), turn('t2', '早', 200)],
  });
  assert.deepEqual(kinds(items), [1, 'Tt2', 'Tt9']);
});

test('认领目标不限正文字段名：助手 TEXT 记录才可被认领（CARD/用户消息不受影响）', () => {
  const messages = [userMsg(1, '收到'), { id: 2, messageFrom: '0', contentType: 'CARD', content: '收到' }];
  const items = buildConversationTimeline({ messages, turns: [turn('t1', '收到', 100)] });
  // 用户消息/CARD 不会被锚掉，回合排末尾
  assert.deepEqual(kinds(items), [1, 2, 'Tt1']);
});

test('空输入与脏输入不炸', () => {
  assert.deepEqual(buildConversationTimeline(), []);
  assert.deepEqual(buildConversationTimeline({ messages: null, turns: null }), []);
  assert.deepEqual(buildConversationTimeline({ messages: [null, undefined], turns: [null, {}, { id: '' }] }), []);
});

test('normalizeTimelineText / turnAnchorText 口径', () => {
  assert.equal(normalizeTimelineText(' a \n b '), 'a b');
  assert.equal(normalizeTimelineText(undefined), '');
  assert.equal(normalizeTimelineText(123), '123');
  assert.equal(turnAnchorText(turn('t', ' x ', 1)), 'x');
  assert.equal(turnAnchorText({ terminal: false, answer: { message: 'x' } }), '');
  assert.equal(turnAnchorText({ terminal: true, answer: null, error: null }), '');
});
