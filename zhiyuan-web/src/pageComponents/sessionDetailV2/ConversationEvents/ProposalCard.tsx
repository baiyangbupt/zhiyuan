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
  };
};

type Props = {
  proposal: ProposalPayload;
  /** 采纳/放弃：**帧由调用方发** ✓（它才知道 sessionId 与连接 ✓）。 */
  onDecide: (action: 'confirm' | 'cancel') => void | Promise<void>;
  /** 服务端回来的**结果**（`conversationAction.result` ✓）：到了就说明这一格已经走过一轮 ✓，
   *  按钮要收起来 ✓，并把状态说出来 ✓（"确认中" ≠ "已生效" ✗——设计里那条分得很清 ✓）。 */
  actionResult?: { actionStatus?: string; proposalRef?: string };
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
      {blocked ? (
        <Alert
          type="warning"
          showIcon
          data-testid="proposal-blocked"
          message={diff.blockingReason || '这一版方案暂时无法执行。'}
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
            采纳
          </Button>
          <Button
            disabled={locked}
            data-testid="proposal-cancel"
            onClick={() => void decide('cancel')}
          >
            放弃
          </Button>
        </Space>
      ) : null}
    </div>
  );
};

export default ProposalCard;
