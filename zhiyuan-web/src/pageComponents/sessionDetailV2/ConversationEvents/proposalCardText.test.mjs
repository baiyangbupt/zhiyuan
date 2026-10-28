import test from 'node:test';
import assert from 'node:assert/strict';

import {
  COLD_FALLBACK_HIDDEN_KINDS,
  compactActionReceiptText,
  COLD_FALLBACK_SETTLED_HIDDEN_KINDS,
  PROPOSAL_STALE_STATE_TEXT,
  UNKNOWN_STATUS_TEXT,
  coldFallbackProposalVisible,
  isSettledProposalStatus,
  legacyPendingCardBadgeText,
  proposalBlockedText,
  proposalCardStatusTagText,
  proposalFailureText,
  proposalNeedsConfirmation,
  proposalShortageLine,
  proposalStatusLabel,
  proposalStrategyLabel,
  proposalSummaryDuplicatesReason,
} from './proposalCardText.mjs';

test('review_paused 放在 msg 时也按中文暂停文案展示', () => {
  const text = proposalFailureText({ code: 409, message: 'review_paused' });
  assert.match(text, /\[409\]/);
  assert.match(text, /审查当前暂停/);
  assert.match(text, /可以取消/);
});

test('84009 按上游数据策略失败展示，而非要求用户反复刷新确认', () => {
  const text = proposalFailureText({ code: 84009, message: '当前策略已失效，请刷新页面' });
  assert.match(text, /84009/);
  assert.match(text, /上游.*数据策略/);
  assert.match(text, /核对.*模式/);
  assert.doesNotMatch(text, /请刷新页面/);
});

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
    'admission_evidence_missing',
    '40905',
  ]) {
    const text = proposalFailureText({ code, message: 'internal english message' });
    assert.match(text, new RegExp(`^\\[${code}\\] `), `${code} 要带锚点`);
    // 去掉锚点后不许再出现英文词（机器态/内部术语都被映射挡在外面）。
    assert.doesNotMatch(text.replace(`[${code}]`, ''), /[A-Za-z]{3,}/, `${code} 文案里不该留英文`);
    assert.match(text, /[㐀-鿿]/, `${code} 文案要中文`);
  }
});

test('admission_evidence_missing 的复合码（裸码: 单元号明细）也说人话（会话 10041981）', () => {
  // 真事故形状：`admission_evidence_missing: 43020271000088_43020272000269`
  // ——裸码先取冒号前那段再查表；正文（锚点之后）只留人话，英文原文不铺。
  const text = proposalFailureText({
    code: 'admission_evidence_missing: 43020271000088_43020272000269',
    message: 'admission evidence missing',
  });
  assert.equal(
    text,
    '[admission_evidence_missing: 43020271000088_43020272000269] 这轮引用的录取数据凭证没对上，已自动中止——稍后重试或换个问法。',
  );
  // 锚点（`[code]`，排障对账要它）之外的正文不许再出现服务端明细。
  const body = text.slice(text.indexOf('] ') + 2);
  assert.doesNotMatch(body, /43020271000088|evidence missing|admission/);
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

test('复合码（裸码: 英文明细）先取冒号前的裸码再查表——整轮失败不再掉兜底（会话 10041980）', () => {
  // `recoverable.error`（整轮失败）的码是复合串（裸码 + 冒号 + 英文明细 ✗），
  // 精确匹配落空 → 以前用户只看到通用兜底 ✗；锚点仍是完整原串（排障要用 ✓）。
  const rawCode = 'proposal_reference_mismatch: proposal action does not match active proposal';
  assert.equal(
    proposalFailureText({ code: rawCode, message: '当前对话引擎暂时不可用，请稍后重试。' }),
    `[${rawCode}] 这张确认已经失效（会话里已有更新的预览），请用最新预览重新确认。`,
  );
  // 边界：冒号带空白也认；裸码全大写走原有"另试全小写"查法 ✓。
  assert.match(proposalFailureText({ code: 'proposal_version_mismatch : detail' }), /方案在你确认前发生了变化/);
  assert.match(proposalFailureText({ code: 'Proposal_Reference_Mismatch: detail' }), /这张确认已经失效/);
});

test('裸码路径逐字不变：归一化只对精确匹配落空的原串生效', () => {
  assert.equal(
    proposalFailureText({ code: 'proposal_reference_mismatch', message: 'internal english message' }),
    '[proposal_reference_mismatch] 这张确认已经失效（会话里已有更新的预览），请用最新预览重新确认。',
  );
  // 裸码查表落空时的老优先级不变：中文 message 转述 > 通用兜底 ✓。
  assert.equal(
    proposalFailureText({ code: '110', message: '请填写各科成绩后再创建会话' }),
    '[110] 请填写各科成绩后再创建会话',
  );
});

test('未知复合码仍然走 message / 通用兜底（不许把冒号后半截当码查）', () => {
  const rawCode = '40904: planning version conflict: current=1 expected=0';
  assert.equal(
    proposalFailureText({ code: rawCode, message: 'planning version conflict: current=1 expected=0' }),
    `[${rawCode}] 这次确认没有生效，请重试或重新生成预览后再确认。`,
  );
  assert.equal(
    proposalFailureText({ code: rawCode, message: '版本不一致' }),
    `[${rawCode}] 版本不一致`,
  );
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

test('user_goal_unclear × 补足形态：建议句给"要一个具体数字"，不落通用句（会话 10041983）', () => {
  const text = proposalBlockedText({
    blockingReasonCodes: ['user_goal_unclear'],
    blockingReason: '补齐目标数量必须是大于 0 的整数。',
    strategy: 'fill_missing_count',
  });
  assert.match(text.suggestion, /具体数字/);
  assert.match(text.suggestion, /多少个/);
  assert.doesNotMatch(text.suggestion, /说得再具体一点/);
  // 没有 fill 形态（无 strategy / 别的 strategy）时仍用通用句 ✓，不误伤其他 user_goal_unclear。
  const generic = proposalBlockedText({ blockingReasonCodes: ['user_goal_unclear'] });
  assert.match(generic.suggestion, /说得再具体一点/);
  const other = proposalBlockedText({ blockingReasonCodes: ['user_goal_unclear'], strategy: 'only_keep_scope' });
  assert.match(other.suggestion, /说得再具体一点/);
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

// ── 卡面 Tag 的兜底语义（2026-10-13 用户实测：`status=info` 的卡挂着"待确认" ✗）────────
// 事故形状：`status=info`、summary"当前方案里已经有 3 个专业组…本轮不需要为了这个目标
// 调整方案"、`requiresConfirmation=false`（无按钮 ✓）——标签却是"待确认" ✗，误导。

test('info 卡 → "无需调整"：绝不出现"待确认"，也没有按钮', () => {
  const tag = proposalCardStatusTagText({ status: 'info' });
  assert.equal(tag, '无需调整');
  assert.notEqual(tag, '待确认');
  // 服务端本来就把 info 标成 requiresConfirmation=false ✓ → 无按钮 ✓。
  assert.equal(proposalNeedsConfirmation({ status: 'info', requiresConfirmation: false }), false);
  // 就算哪天某个入口漏了那个 flag ✗，也不许给"无需调整"的卡配确认按钮 ✓（按状态自保 ✓）。
  assert.equal(proposalNeedsConfirmation({ status: 'info' }), false);
});

test('ready 卡行为不变：仍"待确认"、仍配确认按钮（唯一的等待档 ✓）', () => {
  assert.equal(proposalCardStatusTagText({ status: 'ready' }), '待确认');
  assert.equal(proposalNeedsConfirmation({ status: 'ready', requiresConfirmation: true }), true);
});

test('applying 不再给确认/取消按钮：Java 只允许取消 active', () => {
  assert.equal(
    proposalNeedsConfirmation({ status: 'ready', actionStatus: 'applying', requiresConfirmation: true }),
    false,
  );
  assert.equal(
    proposalNeedsConfirmation({ status: 'ready', requiresConfirmation: true }),
    true,
  );
});

test("动作结果（actionStatus）行为不变：'active' → '待处理'，且优先于提案状态表", () => {
  assert.equal(proposalCardStatusTagText({ actionStatus: 'active' }), '待处理');
  assert.equal(proposalCardStatusTagText({ status: 'ready', actionStatus: 'active' }), '待处理');
  assert.equal(proposalCardStatusTagText({ status: 'info', actionStatus: 'applied' }), '已生效');
  assert.equal(proposalCardStatusTagText({ actionStatus: 'some_future_state' }), UNKNOWN_STATUS_TEXT);
});

test('未知提案状态不误称"待确认"：中性兜底"处理结果未知"', () => {
  for (const status of ['', undefined, null, 'some_future_state']) {
    const tag = proposalCardStatusTagText({ status });
    assert.notEqual(tag, '待确认', `${String(status)} 不许说"待确认"`);
    assert.equal(tag, UNKNOWN_STATUS_TEXT);
  }
});

test('preview_only 卡 → "仅供参考"：只给看、不配按钮（preview-only 策略本来就没有可确认动作 ✓）', () => {
  assert.equal(proposalCardStatusTagText({ status: 'preview_only' }), '仅供参考');
  assert.equal(proposalNeedsConfirmation({ status: 'preview_only' }), false);
});

test('blocked 优先于动作结果的口径不变："无法执行"、无按钮', () => {
  assert.equal(proposalCardStatusTagText({ status: 'blocked', actionStatus: 'active' }), '无法执行');
  assert.equal(proposalNeedsConfirmation({ status: 'blocked', requiresConfirmation: true }), false);
});

test('本地等待态（点了还没回结果）优先于提案状态表', () => {
  assert.equal(proposalCardStatusTagText({ status: 'ready', pendingText: '确认中…' }), '确认中…');
  assert.equal(proposalCardStatusTagText({ status: 'info', pendingText: '取消中…' }), '取消中…');
});

// ── legacy `pendingConfirmationCard` 的徽标兜底（`MessageList/index.tsx` ✓）：同一原则 ✓ ────

test('legacy 待确认卡：active / 缺省 → "待确认"；未知状态 → 中性文案，不冒充', () => {
  // 家族惯例：缺省视作 active ✓（`(status || 'active') === 'active'` ✓）。
  assert.equal(legacyPendingCardBadgeText('active'), '待确认');
  assert.equal(legacyPendingCardBadgeText(undefined), '待确认');
  assert.equal(legacyPendingCardBadgeText(''), '待确认');
  const unknown = legacyPendingCardBadgeText('some_future_state');
  assert.notEqual(unknown, '待确认', '未知状态不许冒充"待确认" ✗');
  assert.equal(unknown, UNKNOWN_STATUS_TEXT);
});

// ── 冷加载兜底卡"要不要画"（2026-10-16 用户实测：career 卡"结果未知 + 重复出卡" ✗）──────
// 事故形状（会话 10041983 ✓）：同一个 career 待确认出现了事件流回合卡 ✓ 与刷新后的
// 兜底空壳卡 ✗（无明细 → 标题"方案调整预览" + 词表外状态 → "处理结果未知" ✓）两张卡面。

test('兜底初衷不变：没有回合卡、也没在别处画过 → 照绘画（F13 第③条要保）', () => {
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'pending-1', actionStatus: 'active' }),
    true,
  );
  // 提案族没有 scoreSummary 也要照画（它的"方案调整预览"标题是贴切的）——
  // 去重不许按"scoreSummary 为空"一刀切 ✗。
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'pending-2', kind: 'plan_change_proposal' }),
    true,
  );
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'pending-3', kind: 'score_update' }),
    true,
  );
});

test('同一待确认已在回合卡/legacy 卡上画过 → 不重复画（两条卡面来源都算）', () => {
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'pending-1', alreadyRendered: true }),
    false,
    '事件流回合卡或 legacy 卡已画过 → 兜底卡让位 ✓',
  );
});

test('career_update 兜底壳不画：没有可重建的明细，画出来是标题不对的空壳', () => {
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'career_1', kind: 'career_update' }),
    false,
  );
  assert.equal(COLD_FALLBACK_HIDDEN_KINDS.has('career_update'), true);
  // blocked 也要拦住：career 没有提案族那套 blocked 明细，空壳加个"无法执行"仍然没内容。
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'career_2', kind: 'career_update', actionStatus: 'active' }),
    false,
  );
});

test('kind 缺失/未知 → fail-open 照旧画（旧数据/旧服务端行为不变）', () => {
  for (const kind of [undefined, null, '', 'some_future_kind']) {
    assert.equal(
      coldFallbackProposalVisible({ proposalRef: 'pending-1', kind }),
      true,
      `kind=${String(kind)} 不许拦 ✓（fail-open）`,
    );
  }
});

test('已落定的成绩单冷加载不画：结果已由续接消息交代；待确认/确认中照画', () => {
  assert.equal(COLD_FALLBACK_SETTLED_HIDDEN_KINDS.has('score_update'), true);
  for (const actionStatus of ['applied', 'cancelled', 'declined', 'expired', 'failed']) {
    assert.equal(
      coldFallbackProposalVisible({
        proposalRef: 'score-1',
        kind: 'score_update',
        actionStatus,
        hasTurns: false,
      }),
      false,
      `${actionStatus} 的成绩单不许再钉在底部`,
    );
  }
  // 待确认/确认中：它是冷加载后唯一的卡面入口，照画 ✓。
  for (const actionStatus of ['active', 'applying']) {
    assert.equal(
      coldFallbackProposalVisible({
        proposalRef: 'score-1',
        kind: 'score_update',
        actionStatus,
        hasTurns: false,
      }),
      true,
      `${actionStatus} 的成绩单要留着 ✓`,
    );
  }
  // 事件流结果优先：详情快照还说 active，但事件已 applied → 不画。
  assert.equal(
    coldFallbackProposalVisible({
      proposalRef: 'score-1',
      kind: 'score_update',
      actionStatus: 'active',
      liveActionStatus: 'applied',
      hasTurns: false,
    }),
    false,
  );
  // 方案调整族（非 score_update）的落定旧卡语义不变：仍照画（兜底初衷）。
  assert.equal(
    coldFallbackProposalVisible({
      proposalRef: 'plan-1',
      kind: 'plan_change_proposal',
      actionStatus: 'applied',
      hasTurns: false,
    }),
    true,
  );
});

test('无 proposalRef → 不画（旧判据第一条逐字保留）；已落定且已有新回合 → 让位', () => {
  assert.equal(coldFallbackProposalVisible({ proposalRef: '' }), false);
  assert.equal(coldFallbackProposalVisible({}), false);
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'p', actionStatus: 'applied', hasTurns: true }),
    false,
  );
  // 事件流结果优先于详情快照（与组件同一取法）：live 落定 + 已有回合 → 收起 ✓。
  assert.equal(
    coldFallbackProposalVisible({
      proposalRef: 'p',
      actionStatus: 'active',
      liveActionStatus: 'applied',
      hasTurns: true,
    }),
    false,
  );
  // 落定但还没有回合（历史重建中）→ 照画 ✓（兜底初衷：旧卡仍要可见 ✓，逐字保留旧语义 ✓）。
  assert.equal(
    coldFallbackProposalVisible({ proposalRef: 'p', actionStatus: 'applied', hasTurns: false }),
    true,
  );
});

test('J4b 新增动作有中文 strategy 名', () => {
  assert.equal(proposalStrategyLabel('remove_units'), '移除志愿');
  assert.equal(proposalStrategyLabel('move_units'), '调整顺序');
});


test('compact server receipt shows actual counts and final size without internal identifiers', () => {
  const text=compactActionReceiptText({receipt:{operationId:'private-op',actionType:'move_units',
    addedCount:0,removedCount:0,reorderedCount:1,after:10,countMode:'volunteer'}});
  assert.equal(text,'新增 0 条；删除 0 条；调整顺序 1 条；当前方案 10 条');
  assert.doesNotMatch(text,/private-op|move_units|operationId/);
  assert.equal(compactActionReceiptText({receipt:{addedCount:2,removedCount:1,after:11,countMode:'unit'}}),
    '新增 2 组；删除 1 组；当前方案 11 组');
});

test('compact receipt does not duplicate detailed changes or invent missing counts', () => {
  assert.equal(compactActionReceiptText({actualChanges:[{type:'move'}],receipt:{reorderedCount:1}}),'');
  assert.equal(compactActionReceiptText({receipt:{operationId:'internal-only'}}),'');
  assert.equal(compactActionReceiptText({receipt:{addedCount:-1,removedCount:'2',after:null}}),'');
  assert.equal(compactActionReceiptText({receipt:{after:0}}),'当前方案 0 条');
  assert.equal(compactActionReceiptText(null),'');
});
