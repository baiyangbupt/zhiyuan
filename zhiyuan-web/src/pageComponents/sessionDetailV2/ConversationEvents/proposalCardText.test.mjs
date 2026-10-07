import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PROPOSAL_STALE_STATE_TEXT,
  isSettledProposalStatus,
  proposalFailureText,
  proposalStatusLabel,
} from './proposalCardText.mjs';

// ── 终态判据（H1 的"按钮复活"就是漏在 `stale_state` 上） ──────────────────────

test('stale_state 是终态：被取代的卡不许再给按钮（F09 拒绝路径）', () => {
  assert.equal(isSettledProposalStatus('stale_state'), true);
});

test('其余终态一档不漏：applied / cancelled / declined / expired / failed / conflict / not_executable', () => {
  for (const status of ['applied', 'cancelled', 'declined', 'expired', 'failed', 'conflict', 'not_executable']) {
    assert.equal(isSettledProposalStatus(status), true, `${status} 应该是终态`);
  }
});

test('applying 不是终态（确认中还要让用户看得见"已提交，等结果"）', () => {
  assert.equal(isSettledProposalStatus('applying'), false);
});

test('没有结果（空状态）不判终态：还没点过的卡要有按钮', () => {
  assert.equal(isSettledProposalStatus(''), false);
  assert.equal(isSettledProposalStatus(undefined), false);
  assert.equal(isSettledProposalStatus(null), false);
});

test('未知机器态也收按钮（排除法：到了结果就说明这一格走过一轮，宁可不给也别复活）', () => {
  assert.equal(isSettledProposalStatus('some_future_state'), true);
});

// ── 状态 → 中文（H1：原样渲染英文机器态是事故） ──────────────────────────────

test('stale_state 说中文，且与 legacy 卡口径一致（"需重新确认"）', () => {
  assert.equal(proposalStatusLabel('stale_state'), '需重新确认');
  assert.match(PROPOSAL_STALE_STATE_TEXT, /方案已变化/);
  assert.match(PROPOSAL_STALE_STATE_TEXT, /重新生成预览/);
});

test('已知状态逐个给中文（applied/cancelled/declined/expired/failed/applying）', () => {
  assert.equal(proposalStatusLabel('applied'), '已生效');
  assert.equal(proposalStatusLabel('cancelled'), '已放弃');
  assert.equal(proposalStatusLabel('declined'), '已放弃');
  assert.equal(proposalStatusLabel('expired'), '已过期');
  assert.equal(proposalStatusLabel('failed'), '未生效');
  assert.equal(proposalStatusLabel('applying'), '确认中…');
});

test('未知状态给中文兜底，绝不把英文机器态直出', () => {
  const label = proposalStatusLabel('some_future_state');
  assert.equal(label, '处理结果未知');
  assert.doesNotMatch(label, /[A-Za-z]/);
});

test('没有状态时不做映射（由调用方决定"待确认/无法执行"那一档）', () => {
  assert.equal(proposalStatusLabel(''), '');
  assert.equal(proposalStatusLabel(undefined), '');
});

// ── 失败文案（M1：以 code 为锚点、文案中文） ────────────────────────────────

test('stale 家族的码给中文，且带 code 锚点、不含 Java 英文原文与版本号', () => {
  const text = proposalFailureText({
    code: 'proposal_version_mismatch',
    message: 'planning version conflict: current=1 expected=0',
  });
  assert.equal(text, '[proposal_version_mismatch] 方案在你确认前发生了变化，请重新生成预览后再确认。');
  assert.doesNotMatch(text, /current=|expected=|planning/);
});

test('每个网关自产的拒绝码都有中文映射（proposal_reference_mismatch 等）', () => {
  for (const code of [
    'proposal_reference_mismatch',
    'proposal_version_missing',
    'proposal_version_mismatch',
    'proposal_version_invalid',
    'pending_revision_missing',
    'action_not_executable',
  ]) {
    const text = proposalFailureText({ code, message: 'internal english message' });
    assert.match(text, new RegExp(`^\\[${code}\\] `), `${code} 要带锚点`);
    // 去掉锚点后不许再出现英文词（机器态/内部术语都被映射挡在外面）。
    assert.doesNotMatch(text.replace(`[${code}]`, ''), /[A-Za-z]{3,}/, `${code} 文案里不该留英文`);
    assert.match(text, /[㐀-鿿]/, `${code} 文案要中文`);
  }
});

test('码没有映射、但服务端 message 本来就是中文 → 转述它（Java 的校验话要留住）', () => {
  const text = proposalFailureText({ code: '110', message: '请填写各科成绩后再创建会话' });
  assert.equal(text, '[110] 请填写各科成绩后再创建会话');
});

test('码没有映射、message 是英文内部消息 → 只用通用中文兜底，不直出', () => {
  const text = proposalFailureText({ code: '40904', message: 'planning version conflict: current=1 expected=0' });
  assert.equal(text, '[40904] 这次确认没有生效，请重试或重新生成预览后再确认。');
  assert.doesNotMatch(text, /conflict|current/);
});

test('没有 code、没有 message → 通用中文兜底（失败不许空着）', () => {
  assert.equal(proposalFailureText({}), '这次确认没有生效，请重试或重新生成预览后再确认。');
  assert.equal(proposalFailureText(), '这次确认没有生效，请重试或重新生成预览后再确认。');
});

test('没有 code、有中文 message → 原样转述（不凭空加锚点）', () => {
  assert.equal(proposalFailureText({ message: '版本不一致' }), '版本不一致');
});
