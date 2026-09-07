import React from 'react';
import { Alert, Card, Empty, List, Tag, Typography } from 'antd';
import { ConversationArtifact } from '@/interface/api/conversation';
import { formatAdmissionProbability, formatRank } from '@/utils/conversationEvents.mjs';

interface ArtifactRendererProps {
  artifact?: ConversationArtifact | null;
}

const displayValue = (item: Record<string, unknown>, key: string) => {
  if (key === 'admissionRatio' || key === 'admissionProbability') {
    return formatAdmissionProbability(item[key] as number | string | null | undefined);
  }
  if (key === 'rank' || key === 'minRank' || key === 'maxRank') {
    return formatRank(item[key] as number | string | null | undefined);
  }
  const value = item[key];
  return value === null || typeof value === 'undefined' ? '—' : String(value);
};

export const ArtifactRenderer: React.FC<ArtifactRendererProps> = ({ artifact }) => {
  if (!artifact) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可展示数据" />;

  const rows = Array.isArray(artifact.items) ? artifact.items : [];
  return (
    <Card size="small" title={artifact.title || '规划数据'}>
      <Typography.Paragraph type="secondary">
        数据版本 {artifact.stateVersion}
      </Typography.Paragraph>
      {artifact.blockingFindings?.length ? (
        <Alert type="error" showIcon message="存在阻断项" description={artifact.blockingFindings.join('；')} />
      ) : null}
      {artifact.warnings?.length ? (
        <Alert type="warning" showIcon message="请注意" description={artifact.warnings.join('；')} />
      ) : null}
      {rows.length ? (
        <List
          size="small"
          dataSource={rows}
          renderItem={item => (
            <List.Item>
              <span>{String(item.schoolName || item.name || item.majorName || '候选')}</span>
              <span>
                {item.riskBand ? <Tag>{String(item.riskBand)}</Tag> : null}
                {item.admissionRatio !== undefined ? (
                  <Tag color="blue">录取率 {displayValue(item, 'admissionRatio')}</Tag>
                ) : null}
                {item.rank !== undefined ? <Tag>位次 {displayValue(item, 'rank')}</Tag> : null}
              </span>
            </List.Item>
          )}
        />
      ) : (
        <Typography.Paragraph>{artifact.message ? String(artifact.message) : '暂无条目'}</Typography.Paragraph>
      )}
      {artifact.limitations?.length ? (
        <Typography.Paragraph type="secondary">限制：{artifact.limitations.join('；')}</Typography.Paragraph>
      ) : null}
    </Card>
  );
};

export default ArtifactRenderer;
