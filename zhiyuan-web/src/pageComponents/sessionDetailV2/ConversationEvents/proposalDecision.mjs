// 提案卡「点下去之后 → 结果回来之前」的等待态（纯逻辑，node:test 直接测）。
//
// 为什么单独一个 .mjs（而不是写在 ProposalCard.tsx 里）✗✓：
// 本仓没有 React 渲染测试的基建（同 `proposalCardText.mjs` / `fetchQueue.mjs` 先例 ✓），
// 而"点了没反应"这类观感事故正是这段状态机的落点 ✓，得有单测钉住 ✓。
//
// 事故（2026-10-09 用户实测，会话 10041981）：点"确认更新"之后**没有任何过渡** ✗——
// 旧实现在组件里有一个 `submitting` ✓，但它只包住"发帧"这一个 await ✗
//（`sendMessage` 是即发即返回的 ✓，帧一出门它就被 `finally` 清掉了 ✓）；
// 而 `conversationAction.result` 要等 claim/execute 走完才回来 ✓
//（补录全量重拉实测 ~24s ✓）→ 中间这段空白就是用户说的"结果突然出现、观感割裂" ✓。
//
// 状态机（`decision`，`{ action, proposalRef, startedAt, timedOut } | null`）：
//   · 点击 confirm/cancel → 进入等待 ✓：两颗按钮都锁 ✓、被点的那颗转圈 + "确认中…/取消中…" ✓，
//     **重复点击被拦** ✓（`beginProposalDecision` 返回原状态，引用相等即"什么都没发生" ✓）；
//   · 收到**该 `proposalRef`** 的 `conversationAction.result`（**任何 status** ✓：applied /
//     cancelled / failed / conflict / stale_state / applying…）→ 清回 `null` ✓，
//     后面照旧走既有状态更新（Tag / 说明 / 收按钮 ✓）；
//   · 等待超过 `PROPOSAL_DECISION_TIMEOUT_MS` → `timedOut: true` ✓（按钮恢复可点 ✓、
//     卡上提示可重试 ✓）；迟到结果到了照样把整条清掉 ✓（"可重试"的提示随之收起 ✓）。

/** 点击后等待结果的超时（与输入框那条 `ANSWER_TIMEOUT` 同档 ✓）：超时恢复可点、提示可重试 ✓。 */
export const PROPOSAL_DECISION_TIMEOUT_MS = 30_000;

/** 等待中的按钮文案（与状态表里 `applying` 的"确认中…"同一个词 ✓）。 */
export const PROPOSAL_DECISION_PENDING_TEXT = {
  confirm: '确认中…',
  cancel: '取消中…',
};

/** 还在等结果（未超时）——按钮锁住、重复点击被拦的判据。 */
export function isProposalDecisionPending(decision) {
  return Boolean(decision && decision.action && !decision.timedOut);
}

/**
 * 点击确认/取消：开一条等待态 ✓。
 * **重复点击被拦** ✓：已有等待中（未超时）的状态 → 原样返回（调用方据此判"没发生新动作" ✓）。
 * 超时之后的重试 → 开新的一条（`timedOut` 清零 ✓，重试提示随之收起 ✓）。
 *
 * @param {any} current 现有等待态（`null` = 没在等 ✓）
 * @param {'confirm' | 'cancel'} action 这次点的哪颗按钮 ✓
 * @param {string} [proposalRef] 这条等待的归属（只认这一格的结果 ✓）
 * @param {number} [now] 起始时间戳（测试可注入 ✓）
 */
export function beginProposalDecision(current, action, proposalRef, now = Date.now()) {
  if (isProposalDecisionPending(current)) return current;
  return {
    action: action === 'cancel' ? 'cancel' : 'confirm',
    proposalRef: String(proposalRef || ''),
    startedAt: now,
    timedOut: false,
  };
}

/** 超时兜底 ✓：等待中 → 标记 `timedOut`（按钮恢复可点 ✓、卡上提示可重试 ✓）；其余原样返回 ✓。 */
export function expireProposalDecision(current) {
  if (!isProposalDecisionPending(current)) return current;
  return { ...current, timedOut: true };
}

/**
 * 结果到达 → 清等待态 ✓（**任何 status 都算** ✓——结果一到就说明这一格走过一轮了 ✓）。
 * 只认**同一 `proposalRef`** 的结果 ✗✓：别的卡的结果不许把这张的 loading 关掉 ✗；
 * `result.proposalRef` 缺失不算匹配 ✓（宁可等超时兜底 ✓，也不误清 ✗）。
 * 已 `timedOut`（等重试）的那条也一起清掉 ✓：迟到结果到了，就不该再劝用户"重试" ✓。
 *
 * @param {any} current 现有等待态
 * @param {{ proposalRef?: string } | null | undefined} result `conversationAction.result` 载荷 ✓
 * @returns {null | any} `null` = 已清（等待结束 ✓）；原引用 = 没动（不是这条的结果 ✓）
 */
export function clearProposalDecision(current, result) {
  if (!current) return current;
  const resultRef = String(result?.proposalRef || '');
  if (!resultRef || resultRef !== String(current.proposalRef || '')) return current;
  return null;
}

/**
 * 按钮要画的样子（判据都在这 ✓，组件只做渲染 ✓）：
 * `{ locked, confirmLoading, cancelLoading, confirmText, cancelText }` ✓——
 * 等待中两颗都锁 ✓、被点的那颗 `loading` ✓ 且文案换成"确认中…/取消中…" ✓。
 *
 * @param {any} decision 等待态
 * @param {{ confirmText?: string, cancelText?: string }} [baseText] 常态按钮文案（补录卡与方案卡不同 ✓）
 */
export function proposalDecisionButtonState(decision, { confirmText, cancelText } = {}) {
  const pending = isProposalDecisionPending(decision);
  const action = pending ? decision.action : '';
  return {
    locked: pending,
    confirmLoading: action === 'confirm',
    cancelLoading: action === 'cancel',
    confirmText: action === 'confirm' ? PROPOSAL_DECISION_PENDING_TEXT.confirm : confirmText,
    cancelText: action === 'cancel' ? PROPOSAL_DECISION_PENDING_TEXT.cancel : cancelText,
  };
}
