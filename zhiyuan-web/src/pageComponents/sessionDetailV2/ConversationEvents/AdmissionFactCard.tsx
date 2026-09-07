import React from 'react';
import { Alert, Card, Empty, List, Tag, Typography } from 'antd';
import { AdmissionFact, AdmissionMode } from '@/interface/api/conversation';
import { formatAdmissionProbability } from '@/utils/conversationEvents.mjs';

interface AdmissionFactCardProps {
  admissionMode: AdmissionMode;
  facts: AdmissionFact[];
  limitations?: string[];
}

const modeLabel = (mode: AdmissionMode) => (mode === 'major_group' ? '院校专业组' : '专业+大学');

export const AdmissionFactCard: React.FC<AdmissionFactCardProps> = ({
  admissionMode,
  facts,
  limitations = [],
}) => {
  if (!facts.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可核验招生事实" />;

  return (
    <Card size="small" title={`招生事实 · ${modeLabel(admissionMode)}`}>
      <List
        size="small"
        dataSource={facts}
        renderItem={fact => (
          <List.Item key={fact.admissionUnitId}>
            <div style={{ width: '100%' }}>
              <Typography.Text strong>
                {fact.schoolName || fact.schoolId}
                {admissionMode === 'major_group'
                  ? ` · 专业组 ${fact.groupCode || '—'}`
                  : ` · ${fact.majorName || fact.majorId || '专业'}`}
              </Typography.Text>
              <div style={{ marginTop: 6 }}>
                <Tag color={fact.riskTier === '冲' ? 'red' : fact.riskTier === '稳' ? 'gold' : 'green'}>
                  {fact.riskTier}
                </Tag>
                <Tag color="blue">单元录取率 {formatAdmissionProbability(fact.unitAdmissionRate)}</Tag>
                <Typography.Text type="secondary">招生单元 {fact.admissionUnitId}</Typography.Text>
              </div>
              {admissionMode === 'major_group' ? (
                fact.majorItems.length ? (
                  <List
                    size="small"
                    dataSource={fact.majorItems}
                    renderItem={item => (
                      <List.Item>
                        <span>{item.majorName || item.majorId}</span>
                        <Typography.Text type="secondary">
                          专业录取率 {formatAdmissionProbability(item.majorAdmissionRate)}
                        </Typography.Text>
                      </List.Item>
                    )}
                  />
                ) : (
                  <Alert type="info" showIcon message="专业组明细暂不可用，组级录取率仍以招生单元为准" />
                )
              ) : null}
            </div>
          </List.Item>
        )}
      />
      {limitations.length ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          限制：{limitations.join('；')}
        </Typography.Paragraph>
      ) : null}
    </Card>
  );
};

export default AdmissionFactCard;
