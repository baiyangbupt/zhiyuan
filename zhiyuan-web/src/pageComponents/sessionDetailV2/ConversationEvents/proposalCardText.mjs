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
  // **待确认行的"活着"态** ✓✓（Java `LastProposalVo.actionStatus` 的四档之一 ✓，
  // 冷加载兜底卡走的就是它 ✓）：以前不在表里 → 刷新后卡片显示"处理结果未知" ✗
  //（用户实测："一张空的方案调整预览卡" ✓）——它是**已知状态** ✓，说的是"等你处理" ✓。
  active: '待处理',
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
  // 求解器没编译出可执行方案（`status=blocked` ✓）：与卡上那个"无法执行" Tag 同一口径 ✓。
  blocked: '无法执行',
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

// ── 卡面 Tag：**提案状态**（`diff.status` ✓，Java `RepairProposalTaxonomy.Status` ✓）──────
//
// 与上面 `PROPOSAL_STATUS_TEXT`（动作**结果** `actionStatus` ✓）是**两张不同的表** ✗✓——
// 两张表都带"状态"两个字，来源却是两个完全不同的字段 ✓。
//
// 事故（2026-10-13 用户实测）：`status=info` 的卡（summary："当前方案里已经有 3 个专业组…
// 本轮不需要为了这个目标调整方案" ✓、`requiresConfirmation=false` 本来就没有按钮 ✓）
// 却挂着"待确认" ✗——旧实现把"还没有 actionStatus"的卡**一律**兜底成"待确认" ✗，
// 而真正在等用户点确认的只有 `ready` 一档 ✓（Java 侧 `ready` ⇔ `requiresConfirmation=true` ✓）。
export const PROPOSAL_DIFF_STATUS_TEXT = {
  // **唯一**名副其实的"待确认" ✓：可执行、等用户点"采纳/放弃" ✓（按钮与它配套出现 ✓）。
  ready: '待确认',
  // 提醒/核验档（`Status.INFO` ✓："本轮不需要为了这个目标调整方案" ✓）：与 summary 同义 ✓。
  // 工作台侧同档的口径："这项主要是提醒或核验，不会直接调整方案"（`getFixProposalStatusDescription` ✓）。
  info: '无需调整',
  // 只给预览、没有可确认动作（`Status.PREVIEW_ONLY` ✓，`requiresConfirmation=false` ✓）：
  // 工作台侧口径"可以先参考预览"（同 `getFixProposalStatusDescription` ✓）。
  preview_only: '仅供参考',
  // 求解器没编出可执行方案（`Status.BLOCKED` ✓）：与卡上 Alert / 既有 Tag 同一口径 ✓。
  blocked: '无法执行',
};

/** 已知**不可确认**的三档（Java 侧 `blocked`/`info`/`preview_only` 一律 `requiresConfirmation=false` ✓，没有任何可确认动作 ✓）。 */
const DIFF_STATUS_NON_CONFIRMABLE = new Set(['blocked', 'info', 'preview_only']);

/**
 * 卡面 Tag 的文案 ✓（判据从组件里挪出来 ✓，才有单测钉 ✓）。优先级与旧实现**逐字对齐** ✓，
 * 只改兜底那一步 ✗✓：
 *   ① `status=blocked` → "无法执行" ✓（它优先于动作结果 ✓：这张卡本身没编出方案 ✓，
 *      不许因为带了个 `actionStatus=active` 就说成"待处理/待确认" ✗——自相矛盾 ✓）；
 *   ② 动作结果（`actionStatus` ✓）到了 → 照 `PROPOSAL_STATUS_TEXT` 翻中文 ✓；
 *   ③ 本地等待态（`pendingText` ✓——点了还没回结果先顶着 ✓）→ "确认中…/取消中…" ✓；
 *   ④ 落回**提案状态表**（`diff.status` ✓）命中；
 *   ⑤ 都不认识 → "处理结果未知" ✓——**不许**默认声称"待确认" ✗✗（"待确认"只说
 *      真正在等用户点确认的卡 ✓，见 `PROPOSAL_DIFF_STATUS_TEXT` ✓；用户实测的
 *      "info 卡挂着待确认"就是这一步兜错造成的 ✗）。
 */
export function proposalCardStatusTagText({ status, actionStatus, pendingText } = {}) {
  const statusValue = String(status || '');
  if (statusValue === 'blocked') return PROPOSAL_DIFF_STATUS_TEXT.blocked;
  const actionValue = String(actionStatus || '');
  if (actionValue) return proposalStatusLabel(actionValue);
  const pendingValue = String(pendingText || '');
  if (pendingValue) return pendingValue;
  return PROPOSAL_DIFF_STATUS_TEXT[statusValue] || UNKNOWN_STATUS_TEXT;
}

/**
 * 这张卡现在要不要出"确认/取消"按钮 ✓（判据从组件里挪出来 ✓，info 卡的"无按钮"才有单测钉 ✓）。
 * 旧组件里的式子逐字搬来 ✓：`!blocked && !settled && requiresConfirmation !== false && status !== ''`；
 * 只多一条**按状态自保** ✓：三档"没有可确认动作"的已知状态（`DIFF_STATUS_NON_CONFIRMABLE` ✓）
 * 永远不给按钮 ✗——就算哪天某个入口漏了 `requiresConfirmation=false` 那个 flag ✗，
 * 也不许让"无需调整"的卡配着确认按钮 ⇒ 自相矛盾 ✓。
 */
export function proposalNeedsConfirmation({ status, actionStatus, requiresConfirmation } = {}) {
  const statusValue = String(status || '');
  if (DIFF_STATUS_NON_CONFIRMABLE.has(statusValue)) return false;
  if (isSettledProposalStatus(actionStatus)) return false;
  if (requiresConfirmation === false) return false;
  return statusValue !== '';
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
  // 整轮契约失败（`recoverable.error` 的复合串形态 ✓）：模型这轮引用的录取数据
  // 凭证没对上账本 → 网关先给过一次自动修复回合、修不好才把整轮作废 ✓
  //（2026-10-13 会话 10041981 实测：模型把两个招生单元拼成一个复合单元号 ✗）。
  admission_evidence_missing: '这轮引用的录取数据凭证没对上，已自动中止——稍后重试或换个问法。',
};

const DEFAULT_FAILURE_TEXT = '这次确认没有生效，请重试或重新生成预览后再确认。';

/**
 * 失败码的查表（**带归一化** ✓✓，2026-10-09）：同一条失败，两种码形都会到前端 ✓——
 * `conversationAction.result` 那条是**裸码** ✓（`proposal_reference_mismatch` ✓），
 * 而 `recoverable.error`（整轮失败）那条是**复合串** ✗：裸码 + 冒号 + 英文明细 ✓
 * （实测 `proposal_reference_mismatch: proposal action does not match active proposal` ✗，
 * 会话 10041980 ✓）。复合串精确匹配落空 ✗ → 用户只拿到通用兜底 ✗（真正该说的
 * "这张确认已经失效"被丢掉 ✓）。
 *
 * 查表顺序：原串（保持现状优先级 ✓）→ 原串小写 → **冒号前的裸码** → 裸码小写 ✓。
 * 裸码本身没有冒号 ✓ → 前两条查法就是它的 ✓ → **裸码路径行为逐字不变** ✓。
 */
const failureTextByCode = (rawCode) => {
  const bareCode = rawCode.split(':')[0].trim();
  return (
    FAILURE_TEXT_BY_CODE[rawCode] ||
    FAILURE_TEXT_BY_CODE[rawCode.toLowerCase()] ||
    FAILURE_TEXT_BY_CODE[bareCode] ||
    FAILURE_TEXT_BY_CODE[bareCode.toLowerCase()] ||
    ''
  );
};

// 中文兜底判据：`message` 只有在**本身就是中文**（Java 许多校验文案是中文 ✓，
// 如"请填写各科成绩后再创建会话" ✓）时才值得转述 ✓；英文内部消息（含版本号那种 ✗）
// 一律不直出 ✓。
const CJK_CHARACTER = /[㐀-鿿]/;

/**
 * 失败卡的一句话：
 *   ① 先按 `code` 查中文映射 ✓（复合码 `裸码: 明细` 会先取裸码再查 ✓，见
 *      `failureTextByCode` ✓）；
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
  const mapped = failureTextByCode(rawCode);
  const text = mapped || (CJK_CHARACTER.test(rawMessage) ? rawMessage : DEFAULT_FAILURE_TEXT);
  return rawCode ? `[${rawCode}] ${text}` : text;
}

// ── `blocked` 卡（`status=blocked`，"无法执行"那一档）说人话 ──────────────────
//
// 事故（2026-10-08 用户实测）：模型产出的规则被 Java 拒 → 预览 status=blocked ✓，
// 卡上却只有 Tag"无法执行" + 一行 Java 校验原文（形如
// "暂不支持同档前置规则字段：location.region" ✓，是给排障看的黑话 ✗）——
// **没有正文明细、没有下一步** ✓，用户看到的就是"一张坏卡" ✗。
//
// 修法与失败卡（M1）同思路 ✓：**以码为锚、文案中文** ✓——
//   · `blockingReasonCodes[0]` → 一句人话解释 + 一句建议动作（下表 ✓）；
//   · 明细行：`strategy` 的中文名 ✓ / 网关补的 `attemptedRuleBrief`（"本来想调整什么" ✓，
//     **有就展示、没有就优雅降级** ✗✓——不依赖它存在 ✓）/ `candidateShortages` 择要 ✓；
//   · Java 原文 `blockingReason` 降级成次要一行（带 code 锚点 ✓）——排障对账都要它 ✓。

/** `strategy` → 中文名（与工作台 `getFixProposalStrategyLabel` 同口径 ✓，另补对话侧两档 ✓）。 */
export const PROPOSAL_STRATEGY_TEXT = {
  fill_missing_count: '补足数量',
  sort_by_probability: '按录取率重排',
  remove_risk_items: '移除风险项',
  adjust_major_group_inner_safety: '补更稳的组内专业',
  replace_risk_items: '替换风险项',
  rebalance_tier_ratio: '调整冲稳保结构',
  fill_probability_gap: '补梯度断层',
  add_safety_items: '补安全垫',
  only_keep_scope: '只保留目标范围',
  must_include_scope: '至少保留目标范围',
  exclude_scope: '避开目标范围',
  prioritize_within_tier: '同档内优先',
  no_op: '仅需关注',
  cannot_satisfy: '暂不处理',
};

/** 未知 `strategy` 返回空串 ✓——明细行宁可少一行 ✓，也不把英文机器码直出给用户 ✗。 */
export function proposalStrategyLabel(strategy) {
  const value = String(strategy || '').trim();
  return value ? PROPOSAL_STRATEGY_TEXT[value] || '' : '';
}

/**
 * `blockingReasonCodes` 里**已知**的码 → { 解释, 建议 } ✓（码来自 Java 校验器 ✓：
 * `UserGoalProposalBuilder` 的 REASON_* 一族 ✓ + `PlanningObjectiveCompiler` 的 compile 码 ✓）。
 * 查不到就落通用中文（`DEFAULT_*` ✓）——**绝不**把英文码或英文原文铺在正文 ✗。
 */
const BLOCKED_TEXT_BY_CODE = {
  priority_rule_invalid: {
    explanation: '这条调整里有一处系统暂时处理不了的说法：把"优先靠前"限定到了具体的地域、专业或院校（同档前置规则）。',
    suggestion: '换一种说法重试，例如直接说"优先北京的学校"。',
  },
  priority_target_not_in_plan: {
    explanation: '要优先的目标不在当前方案里，没办法把它排到同档更靠前的位置。',
    suggestion: '先把想优先的院校或专业加进方案，再说"把它在同档里排前面"。',
  },
  priority_pinned_position_conflict: {
    explanation: '想优先的目标和方案里已经锁定的位置冲突，排不出新的顺序。',
    suggestion: '先解除相关志愿的锁定，或换一个不冲突的目标重试。',
  },
  priority_tier_unavailable: {
    explanation: '这个档位里没有可以挪动的志愿，排不出"同档更靠前"的效果。',
    suggestion: '换一个档位或换一批目标重试。',
  },
  priority_composite_not_supported: {
    explanation: '优先排序暂时不能和其他调整在同一轮里一起执行。',
    suggestion: '分成两步：先说优先排序，确认后再做其他调整。',
  },
  tier_quota_composite_not_supported: {
    explanation: '冲稳保目标暂时不能和筛选要求或优先规则组合执行。',
    suggestion: '分成两步：先单独确认冲稳保目标，再做其他调整。',
  },
  tier_quota_invalid: {
    explanation: '冲稳保目标目前只支持"补齐到指定数量"这一种做法。',
    suggestion: '改成"补齐到 N 个志愿"的说法重试。',
  },
  preserve_count_requires_include: {
    explanation: '"保持方案总数"的调整必须带上明确数量的"至少包含"要求。',
    suggestion: '换成"保持总数、但至少包含 N 个某类院校/专业"的说法重试。',
  },
  fill_to_count_cannot_trim_compliant_items: {
    explanation: '方案里已经有符合要求的志愿，补足数量时没法再精简它们。',
    suggestion: '先说明想放弃哪些志愿，再重新试一次。',
  },
  solver_complexity_limit: {
    explanation: '这次的要求组合太复杂，系统没能算出可以执行的调整方案。',
    suggestion: '把要求拆开、一次只调一个方向再试。',
  },
  candidate_pool_insufficient: {
    explanation: '当前候选里没有足够符合条件的志愿，这一版调整没法直接生成。',
    suggestion: '先放宽地域、专业或院校条件，再重新试一次。',
  },
  hard_constraints_candidate_insufficient: {
    explanation: '已确认的筛选条件把可选范围收得太窄，找不到足够的候选。',
    suggestion: '先放宽已确认的条件，再重新试一次。',
  },
  source_version_mismatch: {
    explanation: '方案在这期间发生了变化，这一版调整已经对不上了。',
    suggestion: '按最新的方案重新说一次调整要求。',
  },
  user_goal_unclear: {
    explanation: '这次的要求还不够明确，系统没法确定要调整什么。',
    suggestion: '把调整内容说得再具体一点，例如"优先北京的学校"。',
  },
  user_goal_target_not_found: {
    explanation: '要求里提到的目标没能在方案或候选中找到。',
    suggestion: '换成方案里已有的院校或专业名，再试一次。',
  },
};

const DEFAULT_BLOCKED_EXPLANATION = '这条调整暂时没法生成可以执行的方案。';
const DEFAULT_BLOCKED_SUGGESTION = '换一种更明确、更简单的说法重试。';

/**
 * 同一码、不同 `strategy` 缺的东西不一样（2026-10-15，会话 10041983）：
 * `user_goal_unclear` × `fill_missing_count` 缺的只是**数量**（用户已经说清"补足"，
 * 差的是一个数字）——通用句"说得再具体一点"对不上，这里给专用建议；
 * 查不到组合就回退到通用表 ✓。
 */
const BLOCKED_SUGGESTION_BY_CODE_STRATEGY = {
  user_goal_unclear: {
    fill_missing_count: '补足数量需要一个具体数字——直接告诉我要补到多少个即可（例如"补到 30 个"）。',
  },
};

/** `candidateShortages` 行的 scope/原因 中文（短口径 ✓）——查不到就略过该半句 ✓，**不铺原始码** ✗。 */
const SHORTAGE_SCOPE_TEXT = {
  candidate_pool: '候选池',
  current_plan: '当前方案',
  current_view: '当前筛选视图',
  hard_constraints: '已确认条件',
  policy_or_profile_constraints: '政策或个人条件',
  capacity_or_replacement: '替换方案',
  objective_validation: '调整效果',
  soft_preference: '偏好排序',
};

const SHORTAGE_REASON_TEXT = {
  no_candidate: '没有可用候选',
  insufficient_candidate: '可用候选不足',
  insufficient_replacement_pair: '替换配对不足',
  hard_constraint_filtered: '已确认条件筛掉了',
  objective_not_improved: '调整后改善不明显',
  candidate_pool_insufficient: '候选数量不足',
  count_over_limit: '方案数量超出要求',
  safety_candidate_insufficient: '安全垫候选不足',
  tier_candidate_insufficient: '目标层级候选不足',
  probability_gap_candidate_insufficient: '断层区间候选不足',
  major_group_safety_candidate_insufficient: '组内更稳专业不足',
  partial_major_group_safety_candidate_missing: '组内更稳专业不足',
  safe_replacement_candidate_insufficient: '安全替换候选不足',
  risk_item_unresolved_or_replacement_missing: '安全替换候选不足',
  replacement_pair_missing: '替换配对不足',
  no_sort_or_replacement_candidate: '替换配对不足',
};

const shortageLabel = (table, code) => {
  const value = String(code || '').trim();
  return (value && (table[value] || table[value.toLowerCase()])) || '';
};

/**
 * `summary` 与 `blockingReason` 是不是**同一句话** ✓✓——Java 的 blocked 提案
 * （`UserGoalProposalBuilder.buildScopeBlockedProposal` ✓）把两者写成同一份校验原文 ✓，
 * 卡上铺两遍就是"同一句黑话出现两次" ✗（`blocked` 的正文本来就该是人话 ✓）。
 * 相等时调用方只留 Alert 里那份（带 code 锚点 ✓）；不相等就都保留 ✓（各自有信息 ✓）。
 *
 * @param {{ summary?: string | null, blockingReason?: string | null }} [diff]
 * @returns {boolean}
 */
export function proposalSummaryDuplicatesReason(diff = {}) {
  const summary = String((diff || {}).summary || '').trim();
  const reason = String((diff || {}).blockingReason || '').trim();
  return summary !== '' && summary === reason;
}

/**
 * 一条 shortage → 一行人话（`候选情况：候选池，候选数量不足，当前 4，需要 10` ✓）；
 * 三样（scope / 原因 / 数量）都取不到 → 返回空串 ✓（宁可少一行 ✗ 不给空白行 ✓）。
 *
 * @param {Record<string, any>} [shortage]
 * @returns {string}
 */
export function proposalShortageLine(shortage = {}) {
  const counts = [
    shortage.targetTier ? `目标层级 ${shortage.targetTier}` : '',
    typeof shortage.requiredCount === 'number' ? `需要 ${shortage.requiredCount}` : '',
    typeof shortage.currentCount === 'number' ? `当前 ${shortage.currentCount}` : '',
    typeof shortage.shortageCount === 'number' ? `缺口 ${shortage.shortageCount}` : '',
    typeof shortage.availableCount === 'number' ? `可用 ${shortage.availableCount}` : '',
  ].filter(Boolean);
  const parts = [
    shortageLabel(SHORTAGE_SCOPE_TEXT, shortage.scope),
    shortageLabel(SHORTAGE_REASON_TEXT, shortage.reasonCode),
    counts.join('，'),
  ].filter(Boolean);
  return parts.length > 0 ? `候选情况：${parts.join('，')}` : '';
}

/**
 * `blocked` 卡要说的话（**纯数据** ✓——渲染在 `ProposalCard` ✓，测试在这里钉 ✓）：
 *   · `explanation`：一句人话（按 `blockingReasonCodes[0]` 查表 ✓，查不到用通用中文 ✓）；
 *   · `suggestion`：一句建议动作 ✓（"换一种说法重试……" ✓；同码×`strategy` 有专用句时优先，
 *     如 `user_goal_unclear`×`fill_missing_count` → "补足数量需要一个具体数字……" ✓）；
 *   · `details`：明细行（调整方向 / 想调整的规则 / 候选情况 ✓，按序 ✓）；
 *   · `reason`：Java 原文降级成次要信息 ✓（有 code 就带 `[code]` 锚点 ✓；没有则原样 ✓）。
 *
 * 任何字段缺失都**优雅降级** ✓（`attemptedRuleBrief` 是网关并行补的 ✓，没有就不出那行 ✗）。
 *
 * @param {{
 *   blockingReason?: string | null,
 *   blockingReasonCodes?: (string | null)[] | string | null,
 *   strategy?: string | null,
 *   attemptedRuleBrief?: string | null,
 *   candidateShortages?: Array<Record<string, any>> | null,
 * }} [diff]
 * @returns {{ explanation: string, suggestion: string, details: string[], reason: string }}
 */
export function proposalBlockedText(diff = {}) {
  const source = diff || {};
  const codes = (Array.isArray(source.blockingReasonCodes)
    ? source.blockingReasonCodes
    : [source.blockingReasonCodes]
  )
    .map((code) => String(code ?? '').trim())
    .filter(Boolean);
  const mappedCode = codes.find((code) => BLOCKED_TEXT_BY_CODE[code]) || '';
  const mapped = mappedCode ? BLOCKED_TEXT_BY_CODE[mappedCode] : null;
  const variantSuggestion =
    (BLOCKED_SUGGESTION_BY_CODE_STRATEGY[mappedCode] || {})[String(source.strategy || '').trim()] || '';

  const details = [];
  const strategyText = proposalStrategyLabel(source.strategy);
  if (strategyText) details.push(`调整方向：${strategyText}`);
  const brief = String(source.attemptedRuleBrief || '').trim();
  if (brief) details.push(`想调整的规则：${brief}`);
  const shortages = Array.isArray(source.candidateShortages) ? source.candidateShortages : [];
  for (const shortage of shortages.slice(0, 2)) {
    const line = proposalShortageLine(shortage || {});
    if (line) details.push(line);
  }

  const rawReason = String(source.blockingReason || '').trim();
  const reason = rawReason ? (codes[0] ? `[${codes[0]}] ${rawReason}` : rawReason) : '';
  return {
    explanation: (mapped && mapped.explanation) || DEFAULT_BLOCKED_EXPLANATION,
    suggestion: variantSuggestion || (mapped && mapped.suggestion) || DEFAULT_BLOCKED_SUGGESTION,
    details,
    reason,
  };
}

// ── legacy "待确认卡"（`pendingConfirmationCard` ✓，`MessageList/index.tsx` ✓）的徽标兜底 ────
//
// 该卡的 status 分支表（applied / cancelled / replaced / expired / applying / stale_state /
// failed ✓）在 `MessageList` 里各自覆盖徽标 ✓；这里只管**分支没命中**的那一档 ✗✓。
// 家族惯例：**缺省视作 `active`** ✓（同文件 `(status || 'active') === 'active'` ✓）——
// `active` 才是真正在等用户点确认的卡 ✓ → '待确认' ✓。
// **未知状态不许冒充 '待确认'** ✗（与卡面 Tag `proposalCardStatusTagText` 同一条原则 ✓，
// 2026-10-13 ✓）：用中性文案 ✓——用户至少不会以为自己（还）欠一次点击 ✓。
export function legacyPendingCardBadgeText(status) {
  const value = String(status || 'active');
  return value === 'active' ? '待确认' : UNKNOWN_STATUS_TEXT;
}

// ── 冷加载兜底卡"要不要画"（`MessageList/index.tsx` 的 `lastProposal` 兜底 ✓）────────────
//
// 事故（2026-10-16 用户实测 ✓，会话 10041983）：同一个 career 待确认出现了**两张卡面** ✗
// ——② 事件流里的回合卡正文 ✓；② 刷新后的**兜底卡** ✗：它只带 `proposalRef`，
// **没有可重建的明细** ✗ → 标题退成"方案调整预览" ✓、状态还是词表外的 `pending` →
// "处理结果未知" ✓ = 一张**标题不对的空壳卡** ✗（与 review §五-60 的"重复出卡"同案 ✓）。
//
// 兜底卡的初衷必须保 ✗✓（F13 用例第③条 ✓：消息历史重建后旧卡仍要可见 ✓）——所以这里
// 只排除两种"不该画"的情形 ✓，其余照旧画：
//   ① **同一待确认已在别的卡面出现过** ✓✓：判据是身份（`proposalRef` ✓，口径与
//      `applyPendingActionResult` 逐字一致 ✓——`proposalRef || pendingId` ✓，不许各取各的 ✗），
//      两个卡面来源都算：事件流回合卡（旧守卫 ✓）+ 历史里的 legacy 待确认卡
//      （`pendingConfirmationCard` ✓，老信封通道落库的那种 ✓，刷新后它会与兜底卡
//      **同时**在屏幕上 ✓ → 同一个 pending 两张卡 ✗）。
//   ② **没有可重建的明细** ✓：`career_update` 一族就属于这种 ✗——`LastProposalVo`
//      里它没有任何能重建卡面正文的字段 ✓（没有 `scoreSummary` ✓、没有 `title` ✓、
//      没有提案族那套 blocked 明细 ✓；结构化那份只在**事件流**的 `proposal.preview`
//      里 ✓）→ 兜底只会画出一张**标题不对**（"方案调整预览" ✗）的空壳 ✓。
//      **按 `kind` 精准排除**而不是按"`scoreSummary` 为空"一刀切 ✗✓：提案族
//      （`plan_change_proposal` ✓）同样没有 `scoreSummary` ✓，但那正是兜底初衷要保的
//      ——它的标题退成"方案调整预览"是**贴切的** ✓（blocked 时还带原因 ✓）。
//      `kind` 缺失/未知时**照旧画** ✓（fail-open：旧数据/旧服务端行为一个字节不变 ✓）。
//
// 判据从组件挪进这里 ✓ 才有单测钉（本仓没有 React 渲染测试的基建 ✓，同 `fetchQueue.mjs` 先例 ✓）。

/** 兜底卡没有可重建明细、不许画的 `kind`（见上；缺失/未知一律放行 ✓）。 */
export const COLD_FALLBACK_HIDDEN_KINDS = new Set(['career_update']);

/**
 * 冷加载兜底卡要不要画 ✓。三条判据（顺序即语义 ✓）：
 *   ① 没有 `proposalRef` → 不画 ✓（旧式判据第一条 ✓，逐字保留）；
 *   ② `alreadyRendered`（同一待确认已在回合卡/legacy 卡上画过 ✓）→ 不画 ✓（去重 ✓）；
 *   ③ 已落定（`liveActionStatus || actionStatus` ✓，与旧实现同一取法 ✓）且会话里已有
 *      回合 → 不画 ✓（旧式判据后半截 ✓，逐字保留：让位给新回合 ✓）；
 *   ④ 明细重建不出来的 `kind` → 不画 ✓（见上 ✓）。
 *
 * @param {{
 *   proposalRef?: string | null,
 *   kind?: string | null,
 *   actionStatus?: string | null,
 *   liveActionStatus?: string | null,
 *   hasTurns?: boolean,
 *   alreadyRendered?: boolean,
 * }} [input]
 * @returns {boolean}
 */
export function coldFallbackProposalVisible({
  proposalRef,
  kind,
  actionStatus,
  liveActionStatus,
  hasTurns,
  alreadyRendered,
} = {}) {
  if (!String(proposalRef || '')) return false;
  if (alreadyRendered) return false;
  if (isSettledProposalStatus(liveActionStatus || actionStatus) && hasTurns) return false;
  if (COLD_FALLBACK_HIDDEN_KINDS.has(String(kind || ''))) return false;
  return true;
}
