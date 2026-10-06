import React, { useState } from 'react';
import { Alert, Button, Space, Tag, Typography } from 'antd';

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

/** 终态：这几档之后就不该再给按钮了 ✓（`applying` 不是终态 ✓，它只是"确认中" ✓）。 */
const SETTLED_STATUSES = ['applied', 'cancelled', 'expired', 'failed', 'conflict'];
const STATUS_TEXT: Record<string, string> = {
  applying: '确认中…',
  applied: '已生效',
  cancelled: '已放弃',
  declined: '已放弃',
  expired: '已过期',
  failed: '未生效',
  conflict: '版本冲突，请重新生成',
};

const ProposalCard: React.FC<Props> = ({ proposal, onDecide, actionResult, disabled }) => {
  const [submitting, setSubmitting] = useState(false);
  const diff = proposal.diff || {};
  const status = String(diff.status || '');
  const blocked = status === 'blocked';
  const action = String(actionResult?.actionStatus || '');
  const settled = SETTLED_STATUSES.includes(action);
  const needsConfirm = !blocked && !settled && diff.requiresConfirmation !== false && status !== '';
  const locked = Boolean(disabled) || submitting;
  const scoreUpdate = diff.scoreUpdate;
  const failureReason =
    action === 'failed'
      ? [actionResult?.code ? `[${actionResult.code}]` : '', actionResult?.message || '']
          .filter(Boolean)
          .join(' ')
      : '';

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
      style={{ padding: '4px 0' }}
    >
      <Typography.Text strong>{diff.title || '方案调整预览'}</Typography.Text>
      <Space size={4} style={{ marginLeft: 8 }}>
        <Tag data-testid="proposal-status">
          {action ? STATUS_TEXT[action] || action : blocked ? '无法执行' : '待确认'}
        </Tag>
      </Space>
      {action && !settled ? (
        <Typography.Text type="secondary" data-testid="proposal-pending-note">
          （已提交，等结果 ✓）
        </Typography.Text>
      ) : null}
      {diff.summary ? (
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
            {[scoreUpdate.provinceName, scoreUpdate.subjectType, scoreUpdate.batchName]
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
      {blocked ? (
        <Alert
          type="warning"
          showIcon
          data-testid="proposal-blocked"
          message={diff.blockingReason || '这一版方案暂时无法执行。'}
        />
      ) : null}
      {/*
        **失败原因不许静默** ✓✓（110 / 40904 / 84009 / -1 …）：只把状态翻成"未生效"
        是不够的 ✓——用户需要知道**为什么**（缺哪一科、版本怎么冲突了 ✓），
        否则只能反复点同一个确认 ✗。`code` 一并给出 ✓：它是排障与对账的锚点 ✓。
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
