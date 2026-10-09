import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PROPOSAL_DECISION_PENDING_TEXT,
  PROPOSAL_DECISION_TIMEOUT_MS,
  beginProposalDecision,
  clearProposalDecision,
  expireProposalDecision,
  isProposalDecisionPending,
  proposalDecisionButtonState,
} from './proposalDecision.mjs';

// ── ① 点击 → loading 出现（用户在会话 10041981 说的"没有过渡"就是这一步） ──────

test('点击确认：进入等待态，按钮锁住 + 转圈 + 文案换"确认中…"', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  assert.equal(isProposalDecisionPending(decision), true);
  assert.deepEqual(proposalDecisionButtonState(decision, { confirmText: '确认更新', cancelText: '取消' }), {
    locked: true,
    confirmLoading: true,
    cancelLoading: false,
    confirmText: '确认中…',
    cancelText: '取消',
  });
});

test('点击取消：同一套锁，被点的那颗换成"取消中…"', () => {
  const decision = beginProposalDecision(null, 'cancel', 'pending-1', 1_000);
  const buttons = proposalDecisionButtonState(decision, { confirmText: '确认更新', cancelText: '取消' });
  assert.equal(buttons.locked, true);
  assert.equal(buttons.confirmLoading, false);
  assert.equal(buttons.cancelLoading, true);
  assert.equal(buttons.confirmText, '确认更新');
  assert.equal(buttons.cancelText, '取消中…');
});

test('等待态里带上了 proposalRef（只认这一格的结果）与起始时间（超时从那刻起算）', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 12_345);
  assert.equal(decision.proposalRef, 'pending-1');
  assert.equal(decision.startedAt, 12_345);
  assert.equal(decision.timedOut, false);
});

test('没在等时不锁按钮：常态两颗都可点、文案原样', () => {
  const buttons = proposalDecisionButtonState(null, { confirmText: '采纳', cancelText: '放弃' });
  assert.deepEqual(buttons, {
    locked: false,
    confirmLoading: false,
    cancelLoading: false,
    confirmText: '采纳',
    cancelText: '放弃',
  });
});

// ── ② 结果事件 → 清除（任何 status 都算：结果一到这一格就走过一轮了） ──────────

test('结果到达即清等待态：applied / cancelled / failed / conflict / stale_state / applying 一视同仁', () => {
  for (const actionStatus of [
    'applied',
    'cancelled',
    'declined',
    'failed',
    'conflict',
    'stale_state',
    'expired',
    'applying',
  ]) {
    const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
    assert.equal(
      clearProposalDecision(decision, { proposalRef: 'pending-1', actionStatus }),
      null,
      `${actionStatus} 到了就该清掉等待态`,
    );
  }
});

test('只认同一 proposalRef 的结果：别的卡的结果不许把这张的 loading 关掉', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  assert.equal(clearProposalDecision(decision, { proposalRef: 'pending-2', actionStatus: 'applied' }), decision);
});

test('结果没带 proposalRef 不算匹配（宁可等超时兜底，也不误清）', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  assert.equal(clearProposalDecision(decision, { actionStatus: 'applied' }), decision);
  assert.equal(clearProposalDecision(decision, null), decision);
  assert.equal(clearProposalDecision(decision, undefined), decision);
});

test('没在等时结果到达是空操作（冷加载卡上已有 actionStatus 的老结果不许被当成新结果）', () => {
  assert.equal(clearProposalDecision(null, { proposalRef: 'pending-1', actionStatus: 'applied' }), null);
});

test('结果事件不区分来源：点卡与打字确认同形（载荷里根本没有"来源"字段），同 ref 就该收等待态', () => {
  // 白名单载荷（`conversationEvents.mjs` 的 `conversationAction.result`）逐键照抄 ✓：
  // 服务端两条通道（点卡 / 模型在回合里发 confirm_proposal）走的是**同一个发射器** ✓，
  // 前端拿到的载荷一模一样 ✓——所以清除判据只许认 `proposalRef` ✓，不许去认来源 ✗。
  const fromEitherChannel = {
    proposalRef: 'pending-1',
    actionStatus: 'applied',
    newStateVersion: 4,
    workspaceVersion: 4,
    code: '0',
    message: '',
  };
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  assert.equal(clearProposalDecision(decision, fromEitherChannel), null);
  // 载荷多带别的键也不影响（比对只认 ref ✓，不按整包形状比 ✓）。
  assert.equal(
    clearProposalDecision(decision, { ...fromEitherChannel, source: 'typed_confirmation' }),
    null,
  );
});

// ── ③ 超时 → 恢复可点（并提示可重试；迟到结果照样收尾） ────────────────────────

test('等待超时：标记 timedOut，按钮恢复可点、文案回到常态（组件据此提示可重试）', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  const expired = expireProposalDecision(decision);
  assert.equal(expired.timedOut, true);
  assert.equal(isProposalDecisionPending(expired), false);
  assert.deepEqual(proposalDecisionButtonState(expired, { confirmText: '确认更新', cancelText: '取消' }), {
    locked: false,
    confirmLoading: false,
    cancelLoading: false,
    confirmText: '确认更新',
    cancelText: '取消',
  });
});

test('超时判定挂在 30s 档上（与输入框 ANSWER_TIMEOUT 同档）', () => {
  assert.equal(PROPOSAL_DECISION_TIMEOUT_MS, 30_000);
});

test('超时只对"还在等"的那条生效：没在等（含已超时）不重复标记', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  const expired = expireProposalDecision(decision);
  assert.equal(expireProposalDecision(expired), expired);
  assert.equal(expireProposalDecision(null), null);
});

test('超时之后迟到结果到达：整条清掉（"可以重试"的提示随之收起，不许与终态并存）', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  const expired = expireProposalDecision(decision);
  assert.equal(clearProposalDecision(expired, { proposalRef: 'pending-1', actionStatus: 'applied' }), null);
});

test('超时后重试：开新的一条等待态（timedOut 清零，重新锁 + 转圈）', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  const expired = expireProposalDecision(decision);
  const retried = beginProposalDecision(expired, 'confirm', 'pending-1', 40_000);
  assert.notEqual(retried, expired);
  assert.equal(retried.timedOut, false);
  assert.equal(retried.startedAt, 40_000);
  assert.equal(isProposalDecisionPending(retried), true);
  assert.equal(proposalDecisionButtonState(retried, { confirmText: '确认更新' }).confirmLoading, true);
});

// ── ④ 重复点击被拦（等待中再点：原样返回，不重开、不换按钮） ────────────────────

test('等待中重复点击确认：原样返回（调用方按引用相等判"没发生新动作"）', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  const again = beginProposalDecision(decision, 'confirm', 'pending-1', 1_200);
  assert.equal(again, decision);
  assert.equal(again.startedAt, 1_000, '不许把超时起点顺延');
});

test('等待中连另一颗按钮（取消）也点不动：锁是整对按钮的，不是单颗', () => {
  const decision = beginProposalDecision(null, 'confirm', 'pending-1', 1_000);
  const viaCancel = beginProposalDecision(decision, 'cancel', 'pending-1', 1_200);
  assert.equal(viaCancel, decision);
  assert.equal(viaCancel.action, 'confirm');
});

// ── 文案常量 ────────────────────────────────────────────────────────────────

test('等待文案与卡上状态表同一个词（"确认中…"），取消侧补一个"取消中…"', () => {
  assert.equal(PROPOSAL_DECISION_PENDING_TEXT.confirm, '确认中…');
  assert.equal(PROPOSAL_DECISION_PENDING_TEXT.cancel, '取消中…');
});
