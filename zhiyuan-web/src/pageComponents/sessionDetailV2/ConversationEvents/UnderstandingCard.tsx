import React from 'react';
import { Card, Tag, Typography } from 'antd';

import { hasStructuredUnderstanding } from '@/utils/conversationSession.mjs';

/**
 * 理解卡：把**通过校验的**结构化理解摘要显示出来。
 *
 * 它刻意什么都不"猜"：
 * - 没有结构化理解时**整卡不渲染**。预制一张"我理解你想……"的卡，是在
 *   替模型表态；用户会以为系统听懂了，而它可能什么都没听懂。
 * - 只显示服务端给的三样：摘要、实体、约束。不做二次推断、不补默认。
 * - 理解摘要可以修改，但修改后走的是 `turnSteer`（作为用户新增的一句话），
 *   不是"就地改这个摘要"——后者等于让前端伪造模型的理解。
 */
export interface UnderstandingPayload {
  summary?: string;
  entities?: string[];
  constraints?: string[];
}

export interface UnderstandingCardProps {
  understanding?: UnderstandingPayload;
  /** 有活动回合时允许"补充说明"；没有活动回合时应当由上层改成新消息。 */
  onRefine?: (text: string) => void;
}

export const UnderstandingCard: React.FC<UnderstandingCardProps> = ({ understanding, onRefine }) => {
  if (!hasStructuredUnderstanding(understanding)) return null;
  const { summary, entities = [], constraints = [] } = understanding || {};

  return (
    <Card size="small" data-testid="understanding-card">
      {summary ? <Typography.Paragraph>{summary}</Typography.Paragraph> : null}
      {entities.length > 0 ? (
        <div data-testid="understanding-entities">
          {entities.map(entity => (
            <Tag key={entity}>{entity}</Tag>
          ))}
        </div>
      ) : null}
      {constraints.length > 0 ? (
        <div data-testid="understanding-constraints">
          {constraints.map(constraint => (
            <Tag key={constraint} color="blue">
              {constraint}
            </Tag>
          ))}
        </div>
      ) : null}
      {onRefine ? (
        <Typography.Link data-testid="understanding-refine" onClick={() => onRefine('')}>
          补充说明
        </Typography.Link>
      ) : null}
    </Card>
  );
};

export default UnderstandingCard;
