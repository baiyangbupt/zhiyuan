import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Space, Tag, Typography } from 'antd';

import {
  PROPOSAL_STALE_STATE_TEXT,
  compactActionReceiptText,
  isSettledProposalStatus,
  proposalBlockedText,
  proposalCardStatusTagText,
  proposalFailureText,
  proposalNeedsConfirmation,
  proposalSummaryDuplicatesReason,
} from './proposalCardText.mjs';
import {
  PROPOSAL_DECISION_PENDING_TEXT,
  PROPOSAL_DECISION_TIMEOUT_MS,
  beginProposalDecision,
  clearProposalDecision,
  expireProposalDecision,
  isProposalDecisionPending,
  proposalDecisionButtonState,
} from './proposalDecision.mjs';

/**
 * **提案卡**（`proposal.preview` ✓）——会话里第二类"要用户动作"的卡 ✓。
 *
 * 与澄清卡的分工 ✓：澄清卡问的是"你指哪一个"（`clarification.requested` ✓），
 * 提案卡问的是"**这份调整要不要采纳**"（`proposal.preview` ✓）；
 * 两者都由服务端给 `requestId`/`proposalRef` 作为唯一句柄 ✓，客户端不自己造 ✓。
 *
 * 载荷形状由**网关翻译**过来 ✓（`_proposal_preview_payload` ✓）：
 * `{proposalRef, sourceVersion, expiresAt, diff:{title, summary, status, requiresConfirmation, …}}` ✓
 *——刻意**不**让前端去认 Java 的字段名 ✗（那会让载荷随求解器版本漂移 ✓）。
 *
 * 三种状态要分得开 ✓（照设计里"等待/已答/过期可区分"那条 ✓）：
 *   · `blocked` —— 求解器没能给出可用方案 ✓：**只解释原因、不给按钮** ✗
 *     （给了按钮就是"让用户确认一个不存在的东西" ✗）；
 *   · 要确认 —— 给"确认/取消" ✓（`ready` ✓，"待确认"这个标签只说给它 ✓）；
 *   · 其余（`info` / `preview_only` / `ready` 但不需要确认）—— 只展示 ✓
 *     （"无需调整"/"仅供参考" ✓，也没有按钮 ✓）。
 */
/**
 * 补录成绩卡的结构化摘要（`diff.scoreUpdate` ✓）：来源是 **Java 按合并后成绩算的**
 * `scoreSummary`（`ChatSessionBizService.buildScoreUpdateSummary` ✓），经网关
 * `_proposal_preview_payload` 白名单带过来 ✓（`server.py` ✓）——不是模型文本的复述 ✓。
 */
export type ScoreUpdateSummary = {
  provinceName?: string;
  provinceCode?: string;
  subjectType?: string;
  subjectTypeCode?: string;
  examYear?: number;
  batchName?: string;
  batchLevel?: string;
  batchScore?: number;
  totalScore?: number;
  totalScorePos?: number;
  specialPlan?: boolean;
  specialPlanLabel?: string;
  specialPlanPrevious?: boolean;
  specialPlanImpact?: string;
  subjects?: { subject?: string; subjectName?: string; score?: number }[];
};

export type ProposalPayload = {
  proposalRef?: string;
  sourceVersion?: number;
  expiresAt?: string;
  diff?: {
    title?: string;
    summary?: string;
    /** 生命周期说明（确认前不动；确认后写入本会话并重新生成/刷新）——由网关白名单带过来。 */
    impact?: string;
    status?: string;
    strategy?: string;
    requiresConfirmation?: boolean;
    /** 旧审查暂停：卡可查看/取消，但不能确认。 */
    reviewPaused?: boolean;
    disabledReason?: string;
    blockingReason?: string;
    blockingReasonCodes?: string[];
    /**
     * `blocked` 卡的人话明细（网关侧从"实际发出去的规则"生成 ✓，形如
     * "地域：北方/北京/上海/广州/深圳" ✓）：**可能没有** ✗✓——有就展示、没有就优雅降级 ✓，
     * 前端不依赖它存在 ✓、也不去解析 Java 的内部字段名 ✗。
     */
    attemptedRuleBrief?: string;
    /** `blocked` 卡的候选缺口（Java 侧 ✓）：多条时择要展示 ✓（见 `proposalBlockedText` ✓）。 */
    candidateShortages?: Array<{
      scope?: string;
      reasonCode?: string;
      targetTier?: string;
      requiredCount?: number;
      currentCount?: number;
      shortageCount?: number;
      availableCount?: number;
      message?: string;
    }>;
    /** 补录成绩（score_update 动作族）✓：有它这张卡就画成绩明细 ✓、按钮文案换一组 ✓。 */
    scoreUpdate?: ScoreUpdateSummary;
  };
};

type Props = {
  proposal: ProposalPayload;
  /** 采纳/放弃：**帧由调用方发** ✓（它才知道 sessionId 与连接 ✓）。 */
  onDecide: (action: 'confirm' | 'cancel') => void | Promise<void>;
  /** 服务端回来的**结果**（`conversationAction.result` ✓）：到了就说明这一格已经走过一轮 ✓，
   *  按钮要收起来 ✓，并把状态说出来 ✓（"确认中" ≠ "已生效" ✗——设计里那条分得很清 ✓）。
   *  `code`/`message` 是**失败原因**（110 / 40904 / 84009 / -1 …）✓——失败不许静默 ✓，
   *  卡上要说得出"未生效 + 为什么" ✓。 */
  actionResult?: {
    actionStatus?: string;
    proposalRef?: string;
    code?: string;
    message?: string;
    receipt?: {
      addedCount?: number;
      removedCount?: number;
      reorderedCount?: number;
      after?: number;
      countMode?: string;
    };
    actualChanges?: Array<{
      type?: string;
      volunteerIds?: string[];
      removedVolunteerIds?: string[];
      removedUnitIds?: string[];
      movedVolunteerIds?: string[];
      movedUnitIds?: string[];
      fromPosition?: number;
      toPosition?: number;
      addedCount?: number;
      addedUnitCount?: number;
      removedCount?: number;
      targetCountBefore?: number;
      targetCountAfter?: number;
      /** 约束类回执：执行后实际规模与目标规模（单位 = countMode）。 */
      actualCount?: number;
      requiredCount?: number;
      shortage?: number;
      countMode?: string;
    }>;
    reviewState?: {
      summary?: {
        passedCount?: number;
        warnCount?: number;
        riskCount?: number;
        blockCount?: number;
      };
    };
  };
  disabled?: boolean;
};

// 状态文案与"还有没有按钮"的判据在 `proposalCardText.mjs` ✓（纯逻辑 + 单测 ✓）——
// H1 的教训：白名单漏一档（`stale_state`）就是"英文机器态直出 + 按钮复活" ✗。

const ProposalCard: React.FC<Props> = ({ proposal, onDecide, actionResult, disabled }) => {
  // ── 等待态：点击 → 结果回来之前的这段空白（2026-10-09 用户实测"没有过渡"✗）────────
  // 判据全在 `proposalDecision.mjs`（纯逻辑 + 单测 ✓）；这里只做"挂表 + 定时器 + 渲染"。
  // 旧实现在这放了个 `submitting`，但它只包住"发帧"那一个 await ✗——`sendMessage`
  // 是即发即返回的 ✓，帧一出门 loading 就没了 ✓，而结果要等 claim/execute 才回来 ✓。
  const compactReceipt = compactActionReceiptText(actionResult);
  const [decision, setDecision] = useState<any>(null);
  // ref 是同步的真相来源（同一帧里的重复点击靠它拦 ✓），state 只负责触发渲染 ✓。
  const decisionRef = useRef<any>(null);
  const decisionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applyDecision = useCallback((next: any) => {
    if (next === decisionRef.current) return;
    decisionRef.current = next;
    setDecision(next);
  }, []);

  const clearDecisionTimer = useCallback(() => {
    if (decisionTimerRef.current) {
      clearTimeout(decisionTimerRef.current);
      decisionTimerRef.current = null;
    }
  }, []);

  // 超时兜底（~30s 无结果）：标记"可重试" ✓。自续定到点 ✓——真到点前不标记，
  // 免得定时器早触发一次就把等待态永远卡在"锁着但没人再叫醒它" ✗。
  const armDecisionTimeout = useCallback(
    (startedAt: number) => {
      clearDecisionTimer();
      const schedule = () => {
        const remaining = startedAt + PROPOSAL_DECISION_TIMEOUT_MS - Date.now();
        if (remaining > 0) {
          decisionTimerRef.current = setTimeout(schedule, remaining);
          return;
        }
        decisionTimerRef.current = null;
        applyDecision(expireProposalDecision(decisionRef.current));
      };
      schedule();
    },
    [applyDecision, clearDecisionTimer],
  );

  useEffect(() => () => clearDecisionTimer(), [clearDecisionTimer]);

  // **结果到达（任何 status）就收等待态** ✓：收回后照旧走既有状态更新那条路
  // （Tag / 说明 / 收按钮 ✓）。依赖是 `actionResult` 本身 ✓——它来自 reducer 里存的那份
  // 对象 ✓，identity 只在**新结果事件**到达时变 ✓（同一条结果重复渲染不会反复触发 ✓）。
  useEffect(() => {
    if (!decisionRef.current) return;
    applyDecision(clearProposalDecision(decisionRef.current, actionResult));
    clearDecisionTimer();
  }, [actionResult, applyDecision, clearDecisionTimer]);

  const diff = proposal.diff || {};
  const status = String(diff.status || '');
  const blocked = status === 'blocked';
  const action = String(actionResult?.actionStatus || '');
  // 到了结果就收按钮（`applying` 除外 ✓）——排除法，见 `isSettledProposalStatus` ✓。
  const settled = isSettledProposalStatus(action);
  // 要不要出按钮的判据在 `proposalCardText.mjs` ✓（2026-10-13：info/preview_only 这类
  // "没有可确认动作"的已知状态由状态表自保 ✓——"无需调整"的卡不许配确认按钮 ✗）。
  const needsConfirm = !diff.reviewPaused && proposalNeedsConfirmation({
    status,
    actionStatus: action,
    requiresConfirmation: diff.requiresConfirmation,
  });
  const scoreUpdate = diff.scoreUpdate;
  // 按钮要画的样子（锁 / 转圈 / "确认中…"）——判据在 `proposalDecision.mjs` ✓。
  const buttons = proposalDecisionButtonState(decision, {
    confirmText: scoreUpdate ? '确认更新' : '采纳',
    cancelText: scoreUpdate ? '取消' : '放弃',
  });
  const locked = Boolean(disabled) || buttons.locked;
  // 卡面那一档"处理中" ✓（与按钮级配套，不过度）：等结果时 Tag 就换成"确认中…/取消中…" ✓
  // （与状态表里 `applying` 同一个词 ✓），而不是一直停在"待确认" ✓。
  const pendingTagText = isProposalDecisionPending(decision)
    ? PROPOSAL_DECISION_PENDING_TEXT[decision.action as 'confirm' | 'cancel'] || ''
    : '';
  // 失败原因**按 code 说中文** ✓（M1）：服务端 `message` 是 Java 的内部英文（含版本号 ✗），
  // 直出给用户既看不懂又像报错 ✓；`code` 仍作排障锚点带出 ✓。
  const failureReason = action === 'failed' ? proposalFailureText(actionResult || {}) : '';
  // `blocked` 卡要说人话（2026-10-08 用户实测"像一张坏卡"✗）：解释 + 明细 + 建议动作，
  // Java 原文降级成次要一行 ✓——纯逻辑在 `proposalCardText.mjs`（有单测 ✓）。
  const blockedText = blocked ? proposalBlockedText(diff) : null;
  // **原文别铺两遍** ✓✓：Java 的 blocked 提案把 `summary` 和 `blockingReason` 写成
  // **同一句校验话**（`UserGoalProposalBuilder.buildScopeBlockedProposal` ✓）——
  // 上面那行 summary 与 Alert 尾行的原文是同一份 ✓，一起铺就是"同一句黑话出现两次" ✗。
  // 相等时只留 Alert 里那一份（它带了 code 锚点与上下文 ✓）；不相等则都保留 ✓（各有信息 ✓）。
  const blockedSummaryDuplicatesReason = blocked && proposalSummaryDuplicatesReason(diff);

  const decide = (action: 'confirm' | 'cancel') => {
    // 没有句柄的卡**不进等待态** ✗：发帧那一侧对空 `proposalRef` 是静默返回 ✓，
    // 进了等待就必然干等满 30s 超时 ✗——那是假的"没反应"，比不转圈更难查 ✓。
    if (!proposal.proposalRef) {
      void onDecide(action);
      return;
    }
    const next = beginProposalDecision(decisionRef.current, action, proposal.proposalRef);
    // 等待中（或已超时未重试前）：`begin` 原样返回 → 这里直接退出 ✓——**重复点击被拦** ✓。
    if (next === decisionRef.current) return;
    applyDecision(next);
    armDecisionTimeout(next.startedAt);
    // 帧的发送仍是调用方的活 ✓（它才知道 sessionId 与连接 ✓）；发不出去就地恢复可点 ✓，
    // 免得用户对着一个永远不会来的结果干等满超时 ✗。
    void Promise.resolve(onDecide(action)).catch((error) => {
      console.warn('提案动作发送失败', error);
      applyDecision(expireProposalDecision(decisionRef.current));
      clearDecisionTimer();
    });
  };

  return (
    <div
      data-testid="proposal-card"
      data-proposal-ref={proposal.proposalRef || ''}
      data-status={status}
      // 结果状态（机器态本身）留一格给排障与 e2e ✓——**界面文案**一律中文 ✓（H1）。
      data-action-status={action}
      style={{ padding: '4px 0' }}
    >
      <Typography.Text strong>{diff.title || '方案调整预览'}</Typography.Text>
      <Space size={4} style={{ marginLeft: 8 }}>
        <Tag data-testid="proposal-status">
          {/* 文案判据全在 `proposalCardText.mjs` 的 `proposalCardStatusTagText` ✓（有单测钉 ✓）：
              `blocked` 优先于动作状态 ✓（这张卡本身没编译出可执行的方案 ✓，不许把它说成
              "待处理/待确认" ✗——那会让卡片自相矛盾 ✓）；结果没到时本地等待态先顶上
              "确认中…/取消中…" ✓（2026-10-09 ✓）；**"待确认"只属于 `status=ready`
              这一档** ✓——2026-10-13 用户实测：`status=info`（"本轮不需要调整方案" ✓、
              本来就没有按钮 ✓）的卡挂着"待确认" ✗，误导。 */}
          {proposalCardStatusTagText({ status, actionStatus: action, pendingText: pendingTagText })}
        </Tag>
      </Space>
      {action && !settled ? (
        <Typography.Text type="secondary" data-testid="proposal-pending-note">
          （已提交，等结果 ✓）
        </Typography.Text>
      ) : null}
      {/*
        **补录卡不再铺"一句话摘要"**（2026-10-08 用户实测"确认卡从没正常显示过"✗）：
        `scoreUpdate` 结构化块（下方 `proposal-score-summary` ✓）与这行摘要是**同一份
        合并后数据**产出的 ✓、信息九成重复——两遍铺出来就是"杂乱、不像正常卡"的观感来源 ✗。
        结构化块在场时只留结构化块（信息不丢：省份/科类/批次/年份/各科/总分/位次全在 ✓）；
        方案调整卡（无 `scoreUpdate`）不受影响 ✓，`proposal-summary` testid 保留 ✓。
      */}
      {diff.summary && !scoreUpdate && !blockedSummaryDuplicatesReason ? (
        <div data-testid="proposal-summary">
          <Typography.Text type="secondary">{diff.summary}</Typography.Text>
        </div>
      ) : null}
      {/*
        生命周期（Batch A2）：卡面必须说清"确认前不动、确认后写入本会话并重新生成"，
        不能统一说"仅本次"，也不能在无命中时暗示已经记下。文案由 Java 按真实行为生成，
        网关白名单透传，前端只展示、不改写。
      */}
      {diff.impact ? (
        <div data-testid="proposal-impact">
          <Typography.Text type="secondary">{diff.impact}</Typography.Text>
        </div>
      ) : null}
      {/*
        补录成绩的**结构化明细** ✓（省份/科类/批次/各科/总分/位次 ✓）——数据来源是
        Java 按"服务端既有成绩 + 本次草稿"合并后的那份 ✓（模型说的数字不作数 ✗）：
        用户在这一格里核对的正是"系统到底打算把哪些字段写成什么" ✓。
      */}
      {scoreUpdate ? (
        <div data-testid="proposal-score-summary">
          <Typography.Text type="secondary">
            {[
              scoreUpdate.provinceName,
              scoreUpdate.subjectType,
              scoreUpdate.batchName,
              scoreUpdate.examYear ? `${scoreUpdate.examYear} 年` : '',
            ]
              .filter(Boolean)
              .join(' · ')}
          </Typography.Text>
          {scoreUpdate.subjects && scoreUpdate.subjects.length > 0 ? (
            <div data-testid="proposal-score-subjects">
              <Typography.Text type="secondary">
                {scoreUpdate.subjects
                  .filter((item) => item && item.score !== undefined && item.score !== null)
                  .map((item) => `${item.subjectName || item.subject || '科目'} ${item.score}`)
                  .join(' · ')}
              </Typography.Text>
            </div>
          ) : null}
          <div data-testid="proposal-score-total">
            <Typography.Text>
              {[
                scoreUpdate.totalScore !== undefined && scoreUpdate.totalScore !== null
                  ? `总分 ${scoreUpdate.totalScore}`
                  : '',
                scoreUpdate.totalScorePos !== undefined && scoreUpdate.totalScorePos !== null
                  ? `位次 ${scoreUpdate.totalScorePos}`
                  : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </Typography.Text>
          </div>
          {scoreUpdate.specialPlan !== undefined ? (
            <div data-testid="proposal-score-special-plan">
              <Typography.Text type="secondary">
                {scoreUpdate.specialPlanPrevious !== undefined
                  ? `专项资格：${scoreUpdate.specialPlanPrevious ? '有' : '无'} → ${
                      scoreUpdate.specialPlan ? '有（类别待核验）' : '无'
                    }`
                  : scoreUpdate.specialPlanLabel
                    || (scoreUpdate.specialPlan ? '有专项资格（类别待核验）' : '无专项资格')}
                {scoreUpdate.specialPlanImpact ? `；${scoreUpdate.specialPlanImpact}` : ''}
              </Typography.Text>
            </div>
          ) : null}
        </div>
      ) : null}
      {/*
        **"无法执行"卡要可读** ✓✓（2026-10-08 用户实测：正文只有一行 Java 校验黑话
        ——"暂不支持同档前置规则字段：location.region" ✗，没有正文明细、没有下一步 ✓
        →"看上去像坏卡" ✗）。现在正文按"解释 → 明细 → 建议"三段铺 ✓：
          · 解释：`blockingReasonCodes[0]` 查中文表 ✓（如 `priority_rule_invalid` ✓）；
          · 明细：调整方向（`strategy` 中文名 ✓）、想调整的规则（`attemptedRuleBrief` ✓，
            网关**可能**还没补它 ✗✓ → 没有就少一行，不报错 ✓）、候选情况（`candidateShortages` ✓）；
          · 建议动作：一句"换一种说法重试，例如……" ✓；
          · Java 原文作**次要信息**留在最后一行 ✓（排障对账的锚点 ✓，不是正文 ✗）。
        **不**给确认按钮 ✓（`requiresConfirmation=false` ✓，本来就没编出可执行方案 ✓）。
      */}
      {blocked && blockedText ? (
        <Alert
          type="warning"
          showIcon
          data-testid="proposal-blocked"
          message={blockedText.explanation}
          description={
            <>
              {blockedText.details.map((line, index) => (
                <div key={`${index}-${line}`} data-testid="proposal-blocked-detail">
                  {line}
                </div>
              ))}
              <div data-testid="proposal-blocked-suggestion">建议：{blockedText.suggestion}</div>
              {blockedText.reason ? (
                <div
                  data-testid="proposal-blocked-raw"
                  style={{ color: 'rgba(0, 0, 0, 0.45)', marginTop: 4 }}
                >
                  系统提示：{blockedText.reason}
                </div>
              ) : null}
            </>
          }
        />
      ) : null}
      {/*
        **被取代的卡要说清下一步** ✓（H1 ✓，口径与 legacy 卡一致 ✓）：
        `stale_state` 是"这张卡已经作废、要重新生成预览" ✓，不是"方案失败" ✗——
        光把这个状态翻成中文还不够 ✗，得说出**用户该做什么** ✓（否则只能反复点同一个确认 ✗）。
      */}
      {action === 'stale_state' ? (
        <Alert
          type="warning"
          showIcon
          data-testid="proposal-stale-reason"
          message={
            actionResult?.code
              ? `[${actionResult.code}] ${PROPOSAL_STALE_STATE_TEXT}`
              : PROPOSAL_STALE_STATE_TEXT
          }
        />
      ) : null}
      {/*
        **失败原因不许静默** ✓✓（110 / 40904 / 84009 / -1 …）：只把状态翻成"未生效"
        是不够的 ✓——用户需要知道**为什么**（缺哪一科、版本怎么冲突了 ✓），
        否则只能反复点同一个确认 ✗。文案走 `proposalFailureText` ✓：**code 作锚点、
        说中文** ✓（M1——Java 的内部英文消息不再直出 ✗）。
      */}
      {diff.reviewPaused ? (
        <Alert
          type="info"
          showIcon
          data-testid="proposal-review-paused"
          message="方案质量审查暂停，这张旧审查卡不能确认；可以取消。方案本身仍可查看和修改。"
        />
      ) : null}
      {action === 'failed' ? (
        <Alert
          type="error"
          showIcon
          data-testid="proposal-failure-reason"
          message={failureReason || '这次确认没有生效，请重试或换一种说法。'}
        />
      ) : null}
      {/*
        已生效的回执：实际加入数量 + 审查摘要（add_units 新链路）。
        旧后端没有这两个字段时整块不渲染，旧前端行为不变。
      */}
      {action === 'applied' &&
      (actionResult?.actualChanges?.length || actionResult?.reviewState?.summary || compactReceipt) ? (
        <div data-testid="proposal-action-receipt" style={{ marginTop: 8, fontSize: 13 }}>
          {compactReceipt ? <div data-testid="proposal-compact-receipt">{compactReceipt}</div> : null}
          {actionResult?.actualChanges?.map((change, index) => {
            const before = change.targetCountBefore;
            const after =
              change.targetCountAfter != null ? change.targetCountAfter : change.actualCount;
            // 约束类回执（纯学费/替换）：没有逐条 added/removed，只说总数与缺口——
            // 不能让"51 组缩到 36 组"只显示成一句"已生效"。
            if (change.type === 'constraint') {
              return (
                <div key={index} data-testid="proposal-constraint-receipt">
                  方案调整已生效
                  {before != null && after != null ? `；总数 ${before} → ${after}` : ''}
                  {Number(change.shortage || 0) > 0 ? `；还差 ${change.shortage}` : ''}
                </div>
              );
            }
            if (change.type === 'remove') {
              return (
                <div key={index} data-testid="proposal-remove-receipt">
                  实际移除 {Number(change.removedCount || 0)} 条
                  {before != null && after != null ? `；总数 ${before} → ${after}` : ''}
                  ；未新增条目
                </div>
              );
            }
            if (change.type === 'move') {
              return (
                <div key={index} data-testid="proposal-move-receipt">
                  已调整顺序
                  {change.fromPosition != null && change.toPosition != null
                    ? `：第 ${change.fromPosition} 位 → 第 ${change.toPosition} 位`
                    : ''}
                  ；条目集合不变
                </div>
              );
            }
            const added = Number(change.addedCount || 0);
            const isReplace = change.type === 'replace';
            return (
              <div key={index}>
                {isReplace ? '实际替换：换入' : '实际加入'} {added} 条
                {change.addedUnitCount != null ? `（${change.addedUnitCount} 个专业组）` : ''}
                {before != null && after != null ? `；总数 ${before} → ${after}` : ''}
                {change.removedCount
                  ? `；${isReplace ? '换出' : '移除'} ${change.removedCount} 条`
                  : '；未删除现有条目'}
              </div>
            );
          })}
          {actionResult?.reviewState?.summary ? (
            <div>
              审查：通过 {Number(actionResult.reviewState.summary.passedCount || 0)} 项
              {actionResult.reviewState.summary.warnCount
                ? ` / 提示 ${actionResult.reviewState.summary.warnCount} 项`
                : ''}
              {actionResult.reviewState.summary.riskCount
                ? ` / 风险 ${actionResult.reviewState.summary.riskCount} 项`
                : ''}
            </div>
          ) : null}
        </div>
      ) : null}
      {/*
        **超时兜底** ✓✓（2026-10-09）：等 ~30s 还没有该 `proposalRef` 的结果 →
        按钮恢复可点 ✓、这里明说"可以重试" ✓——不给这句的话，用户只能对着一张
        转完圈的卡干猜"到底生效没有" ✗。（迟到结果到了，等待态整条清掉，本行也随之收起 ✓。）
      */}
      {decision && decision.timedOut ? (
        <Alert
          type="warning"
          showIcon
          data-testid="proposal-decision-timeout"
          message="长时间没有收到执行结果，可以重试；若已生效请刷新页面查看。"
        />
      ) : null}
      {needsConfirm ? (
        <Space>
          <Button
            type="primary"
            disabled={locked}
            loading={buttons.confirmLoading}
            data-testid="proposal-confirm"
            onClick={() => decide('confirm')}
          >
            {buttons.confirmText}
          </Button>
          <Button
            disabled={locked}
            loading={buttons.cancelLoading}
            data-testid="proposal-cancel"
            onClick={() => decide('cancel')}
          >
            {buttons.cancelText}
          </Button>
        </Space>
      ) : null}
    </div>
  );
};

export default ProposalCard;
