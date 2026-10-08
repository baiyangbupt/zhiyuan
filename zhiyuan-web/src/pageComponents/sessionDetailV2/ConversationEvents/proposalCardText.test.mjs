import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PROPOSAL_STALE_STATE_TEXT,
  UNKNOWN_STATUS_TEXT,
  isSettledProposalStatus,
  proposalBlockedText,
  proposalFailureText,
  proposalShortageLine,
  proposalStatusLabel,
  proposalStrategyLabel,
  proposalSummaryDuplicatesReason,
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

// ── 冷加载兜底卡的状态（2026-10-08 用户实测：刷新后一张空卡写着"处理结果未知" ✗） ──
// 待确认行的 status（`LastProposalVo.actionStatus` 四档：active / applying / applied /
// cancelled / expired）里，'active' 是**活的**那一档 ✓——它是已知状态 ✓，不是未知 ✗。

test("'active'（待确认行还活着）说'待处理'，不再落'处理结果未知'", () => {
  assert.equal(proposalStatusLabel('active'), '待处理');
  assert.notEqual(proposalStatusLabel('active'), UNKNOWN_STATUS_TEXT);
});

test("'blocked'（求解器没编译出方案）与卡上 Tag 同口径：'无法执行'", () => {
  assert.equal(proposalStatusLabel('blocked'), '无法执行');
});

// ── `blocked` 卡说人话（用户实测"正文只有一行 Java 黑话 → 像一张坏卡" ✗） ──────

test('priority_rule_invalid：正文是说人话的解释 + 建议动作，原文只作次要一行', () => {
  const text = proposalBlockedText({
    blockingReasonCodes: ['priority_rule_invalid'],
    blockingReason: '暂不支持同档前置规则字段：location.region',
    strategy: 'prioritize_within_tier',
    attemptedRuleBrief: '地域：北方/北京/上海/广州/深圳',
  });
  // 解释：中文、说得出"为什么"，不许把 Java 原文或字段名铺在正文 ✗。
  assert.match(text.explanation, /优先/);
  assert.doesNotMatch(text.explanation, /location|region|[A-Za-z]{3,}/);
  // 建议：一句可照做的动作（用户原话口径："换一种说法重试，例如……" ✓）。
  assert.match(text.suggestion, /换一种说法/);
  assert.match(text.suggestion, /优先北京的学校/);
  // 明细：调整方向（strategy 的中文名 ✓）+ 想调整的规则（网关补的 brief ✓）。
  assert.deepEqual(text.details, [
    '调整方向：同档内优先',
    '想调整的规则：地域：北方/北京/上海/广州/深圳',
  ]);
  // 原文降级成次要信息 ✓，带 code 锚点（排障对账要用 ✓）。
  assert.equal(text.reason, '[priority_rule_invalid] 暂不支持同档前置规则字段：location.region');
});

test('网关还没补 attemptedRuleBrief 时优雅降级：少一行明细，不报错、不留空白行', () => {
  const text = proposalBlockedText({
    blockingReasonCodes: ['priority_rule_invalid'],
  });
  assert.deepEqual(text.details, []);
  assert.match(text.explanation, /优先/);
  assert.match(text.suggestion, /换一种说法/);
  assert.equal(text.reason, '');
});

test('未知码 + 英文原文：正文只给通用中文，英文原文只留在次要的 reason 行', () => {
  const text = proposalBlockedText({
    blockingReasonCodes: ['some_future_code'],
    blockingReason: 'internal english message with location.region',
  });
  assert.doesNotMatch(text.explanation, /[A-Za-z]/);
  assert.doesNotMatch(text.suggestion, /[A-Za-z]/);
  assert.equal(text.details.length, 0);
  assert.equal(text.reason, '[some_future_code] internal english message with location.region');
});

test('未知 strategy 不铺机器码（明细行宁缺勿滥）', () => {
  assert.equal(proposalStrategyLabel('some_future_strategy'), '');
  assert.equal(proposalStrategyLabel(''), '');
  const text = proposalBlockedText({
    blockingReasonCodes: ['priority_rule_invalid'],
    strategy: 'some_future_strategy',
  });
  assert.deepEqual(text.details, []);
});

test('candidateShortages 多条时择要展示（最多两行，中文、带数量）', () => {
  const text = proposalBlockedText({
    blockingReasonCodes: ['candidate_pool_insufficient'],
    candidateShortages: [
      { scope: 'candidate_pool', reasonCode: 'tier_candidate_insufficient', targetTier: '稳', requiredCount: 10, currentCount: 6, shortageCount: 4 },
      { scope: 'current_plan', reasonCode: 'count_over_limit', currentCount: 80, requiredCount: 60 },
      { scope: 'hard_constraints', reasonCode: 'insufficient_candidate' },
    ],
  });
  assert.equal(text.details.length, 2, '多条只择要展示 ✓（不把三条全铺上 ✗）');
  assert.match(text.details[0], /^候选情况：候选池，目标层级候选不足/);
  assert.match(text.details[0], /需要 10/);
  assert.match(text.details[0], /缺口 4/);
  assert.match(text.details[1], /^候选情况：当前方案，方案数量超出要求/);
  for (const line of text.details) {
    assert.doesNotMatch(line, /[A-Za-z]{3,}/, '明细行不许带机器码 ✗');
  }
});

test('candidateShortages 里取不到中文的部分略过；全取不到就不出行（不给空白行）', () => {
  assert.equal(proposalShortageLine({ scope: 'some_future_scope', reasonCode: 'some_future_reason' }), '');
  assert.match(proposalShortageLine({ scope: 'candidate_pool' }), /^候选情况：候选池$/);
});

test('diff 什么都没有：也给一句中文解释 + 一句建议（卡不许空着）', () => {
  for (const input of [undefined, {}, null]) {
    const text = proposalBlockedText(input);
    assert.match(text.explanation, /[㐀-鿿]/);
    assert.match(text.suggestion, /[㐀-鿿]/);
    assert.equal(text.reason, '');
  }
});

test('blockingReasonCodes 单个字符串也认（载荷形状容错）', () => {
  const text = proposalBlockedText({
    blockingReasonCodes: 'priority_rule_invalid',
    blockingReason: '原文',
  });
  assert.match(text.explanation, /优先/);
  assert.equal(text.reason, '[priority_rule_invalid] 原文');
});

test('blocked 卡的 summary 与 blockingReason 同句时判重（同一句黑话不许铺两遍）', () => {
  // Java 的 `buildScopeBlockedProposal` 就是两者同句（summary = blockingReason ✓）。
  assert.equal(
    proposalSummaryDuplicatesReason({
      summary: '暂不支持同档前置规则字段：location.region',
      blockingReason: '暂不支持同档前置规则字段：location.region',
    }),
    true,
  );
  // 不同句 / 缺一边 / 空串 → 不判重（那行 summary 有自己的信息，要留住 ✓）。
  assert.equal(proposalSummaryDuplicatesReason({ summary: 'A', blockingReason: 'B' }), false);
  assert.equal(proposalSummaryDuplicatesReason({ summary: 'A' }), false);
  assert.equal(proposalSummaryDuplicatesReason({ blockingReason: 'A' }), false);
  assert.equal(proposalSummaryDuplicatesReason({ summary: '   ', blockingReason: '   ' }), false);
  assert.equal(proposalSummaryDuplicatesReason(null), false);
});
