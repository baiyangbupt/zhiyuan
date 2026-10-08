import React, { useState } from 'react';
import { Alert, Button, Space, Tag, Typography } from 'antd';

import {
  PROPOSAL_STALE_STATE_TEXT,
  isSettledProposalStatus,
  proposalBlockedText,
  proposalFailureText,
  proposalStatusLabel,
  proposalSummaryDuplicatesReason,
} from './proposalCardText.mjs';

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
 *   · 要确认 —— 给"确认/取消" ✓；
 *   · 其余（如 `ready` 但不需要确认）—— 只展示 ✓。
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
  subjects?: { subject?: string; subjectName?: string; score?: number }[];
};

export type ProposalPayload = {
  proposalRef?: string;
  sourceVersion?: number;
  expiresAt?: string;
  diff?: {
    title?: string;
    summary?: string;
    status?: string;
    strategy?: string;
    requiresConfirmation?: boolean;
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
  actionResult?: { actionStatus?: string; proposalRef?: string; code?: string; message?: string };
  disabled?: boolean;
};

// 状态文案与"还有没有按钮"的判据在 `proposalCardText.mjs` ✓（纯逻辑 + 单测 ✓）——
// H1 的教训：白名单漏一档（`stale_state`）就是"英文机器态直出 + 按钮复活" ✗。

const ProposalCard: React.FC<Props> = ({ proposal, onDecide, actionResult, disabled }) => {
  const [submitting, setSubmitting] = useState(false);
  const diff = proposal.diff || {};
  const status = String(diff.status || '');
  const blocked = status === 'blocked';
  const action = String(actionResult?.actionStatus || '');
  // 到了结果就收按钮（`applying` 除外 ✓）——排除法，见 `isSettledProposalStatus` ✓。
  const settled = isSettledProposalStatus(action);
  const needsConfirm = !blocked && !settled && diff.requiresConfirmation !== false && status !== '';
  const locked = Boolean(disabled) || submitting;
  const scoreUpdate = diff.scoreUpdate;
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

  const decide = async (action: 'confirm' | 'cancel') => {
    setSubmitting(true);
    try {
      await onDecide(action);
    } finally {
      setSubmitting(false);
    }
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
          {/* `blocked` 优先于动作状态 ✓：这张卡本身没编译出可执行的方案 ✓，
              标签就该是"无法执行" ✓（冷加载兜底卡若带 `actionStatus=active` ✓，
              不许把它说成"待处理" ✗——那会让卡片自相矛盾 ✓）。 */}
          {blocked ? '无法执行' : action ? proposalStatusLabel(action) : '待确认'}
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
      {action === 'failed' ? (
        <Alert
          type="error"
          showIcon
          data-testid="proposal-failure-reason"
          message={failureReason || '这次确认没有生效，请重试或换一种说法。'}
        />
      ) : null}
      {needsConfirm ? (
        <Space>
          <Button
            type="primary"
            disabled={locked}
            loading={submitting}
            data-testid="proposal-confirm"
            onClick={() => void decide('confirm')}
          >
            {scoreUpdate ? '确认更新' : '采纳'}
          </Button>
          <Button
            disabled={locked}
            data-testid="proposal-cancel"
            onClick={() => void decide('cancel')}
          >
            {scoreUpdate ? '取消' : '放弃'}
          </Button>
        </Space>
      ) : null}
    </div>
  );
};

export default ProposalCard;
