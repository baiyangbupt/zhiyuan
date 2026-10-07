// 提案卡的结果文案与"还有没有按钮"的判据（纯逻辑，node:test 直接测）。
//
// 为什么单独放一个 .mjs（而不是写在 ProposalCard.tsx 里）✗✓：
// 本仓没有 React 渲染测试的基建（见 `fetchQueue.mjs` 同款先例 ✓），而这两件事
// ——"机器态说人话"与"终态收按钮"——正是 F09 拒绝路径翻过车的地方 ✓，得有单测钉住 ✓。
//
// 2026-10-07 独立审查的两条（H1 / M1）：
//   · H1：`stale_state` 不在状态映射里 → 卡上原样渲染英文机器态 ✗，而且因为它不在
//     "终态"名单里 ✓ → `needsConfirm` 判真 ✓ → **按钮复活** ✗（用户对着一个已经被
//     取代的提案继续点确认 ✓）；口径要与 legacy 卡对齐 ✓（legacy 卡
//     `MessageList/index.tsx` 对同一状态给的是"方案已变化，请重新生成预览" ✓）。
//   · M1：失败卡把服务端 `message` 原样铺出来 ✗——那是 Java 的内部英文（形如
//     `planning version conflict: current=1 expected=0` ✓，含版本号 ✓），
//     用户看不懂、也不该看到内部术语 ✓。修法：**以 `code` 为锚点** ✓（排障与对账
//     都要它 ✓），文案一律中文 ✓。

/** 已知的 actionStatus → 卡上中文。**未知状态不在这里** ✓（见 `proposalStatusLabel` ✓）。 */
export const PROPOSAL_STATUS_TEXT = {
  applying: '确认中…',
  applied: '已生效',
  cancelled: '已放弃',
  declined: '已放弃',
  expired: '已过期',
  failed: '未生效',
  conflict: '版本冲突，请重新生成',
  // legacy 卡的 badge 口径（`MessageList/index.tsx` 的 `stale_state` 分支 ✓）：
  // "需重新确认" ✓——它说的是"这张卡要重来" ✓，不是"这个方案失败了" ✗。
  stale_state: '需重新确认',
  not_executable: '不可执行',
};

/** 未知状态的兜底文案：宁可说"不确定" ✓，也不把英文机器态直出给用户 ✗。 */
export const UNKNOWN_STATUS_TEXT = '处理结果未知';

/**
 * 服务端回了一条 `conversationAction.result` ⇒ **这一格已经走过一轮** ✓，
 * 按钮必须收起来 ✓——唯一的例外是 `applying` ✓（"确认中"不是终态 ✓，
 * 它只是执行权被认领了 ✓，见设计里那条分得很清的注释 ✓）。
 *
 * 这里用**排除法**而不是终态白名单 ✗✓（H1 就是白名单漏了 `stale_state` 才让按钮复活的 ✓）：
 * 服务端以后新增一种终态 ✓，也不会再出现"卡上状态是英文 + 按钮复活"这一对 ✗。
 */
export function isSettledProposalStatus(status) {
  const value = String(status || '');
  return value !== '' && value !== 'applying';
}

/** 已知状态给中文 ✓；未知状态给"处理结果未知" ✓——**永远不返回原始机器态** ✗。 */
export function proposalStatusLabel(status) {
  const value = String(status || '');
  if (!value) return '';
  return PROPOSAL_STATUS_TEXT[value] || UNKNOWN_STATUS_TEXT;
}

/** `stale_state` 的说明（legacy 卡 statusText 的口径 ✓）：卡上要说得出"下一步做什么" ✓。 */
export const PROPOSAL_STALE_STATE_TEXT = '方案已变化，请重新生成预览后再确认。';

/** `failed` 的**按 code 说中文**映射 ✓（M1）。锚点是 `code` ✓，文案是中文 ✓。 */
const FAILURE_TEXT_BY_CODE = {
  proposal_reference_mismatch: '这张确认已经失效（会话里已有更新的预览），请用最新预览重新确认。',
  proposal_version_missing: '这张卡没有带上版本信息，请重新生成预览后再确认。',
  proposal_version_mismatch: '方案在你确认前发生了变化，请重新生成预览后再确认。',
  proposal_version_invalid: '这张卡的版本信息无法识别，请重新生成预览后再确认。',
  pending_revision_missing: '这条待确认已经结束或被取代，请重新生成预览后再确认。',
  action_not_executable: '这个动作当前不可执行，请按对话提示重新发起。',
};

const DEFAULT_FAILURE_TEXT = '这次确认没有生效，请重试或重新生成预览后再确认。';

// 中文兜底判据：`message` 只有在**本身就是中文**（Java 许多校验文案是中文 ✓，
// 如"请填写各科成绩后再创建会话" ✓）时才值得转述 ✓；英文内部消息（含版本号那种 ✗）
// 一律不直出 ✓。
const CJK_CHARACTER = /[㐀-鿿]/;

/**
 * 失败卡的一句话：
 *   ① 先按 `code` 查中文映射 ✓；
 *   ② 查不到、但服务端 `message` 本身是中文 ✓ → 用它（那是给用户看的话 ✓）；
 *   ③ 都不是 → 通用中文兜底 ✓（**绝不**把英文内部消息铺出来 ✗）。
 *
 * `code` 只要存在就**始终**作为排障锚点带出 ✓（形如 `[code] 中文` ✓）。
 *
 * @param {{ code?: string | number | null, message?: string | null }} [result]
 * @returns {string}
 */
export function proposalFailureText({ code, message } = {}) {
  const rawCode = String(code ?? '').trim();
  const rawMessage = String(message ?? '').trim();
  const mapped = FAILURE_TEXT_BY_CODE[rawCode] || FAILURE_TEXT_BY_CODE[rawCode.toLowerCase()] || '';
  const text = mapped || (CJK_CHARACTER.test(rawMessage) ? rawMessage : DEFAULT_FAILURE_TEXT);
  return rawCode ? `[${rawCode}] ${text}` : text;
}
