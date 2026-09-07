import React, { useEffect, useState } from 'react';
import { Alert, Descriptions, Drawer, Spin, Typography } from 'antd';
import { ConversationEvidence } from '@/interface/api/conversation';
import { getConversationEvidenceApi } from '@/interface/api/volunteer';

interface EvidenceDrawerProps {
  tenantId: string;
  chatSessionId: string;
  evidenceId?: string | null;
  open: boolean;
  onClose: () => void;
}

export const EvidenceDrawer: React.FC<EvidenceDrawerProps> = ({
  tenantId,
  chatSessionId,
  evidenceId,
  open,
  onClose,
}) => {
  const [loading, setLoading] = useState(false);
  const [evidence, setEvidence] = useState<ConversationEvidence | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !evidenceId) return;
    let active = true;
    setLoading(true);
    setError('');
    getConversationEvidenceApi(tenantId, chatSessionId, evidenceId)
      .then(response => {
        if (active) setEvidence(response.data || response);
      })
      .catch(() => {
        if (active) setError('Evidence 暂时无法加载');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [chatSessionId, evidenceId, open, tenantId]);

  return (
    <Drawer title={evidenceId ? `Evidence ${evidenceId}` : 'Evidence'} open={open} onClose={onClose} width={420}>
      {loading ? <Spin /> : null}
      {error ? <Alert type="warning" message={error} /> : null}
      {evidence ? (
        <>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="招生类型">
              {evidence.admissionMode === 'major_group' ? '院校专业组' : evidence.admissionMode === 'major' ? '专业+大学' : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="招生单元">{evidence.admissionUnitId || '—'}</Descriptions.Item>
            <Descriptions.Item label="专业组">{evidence.groupCode || '—'}</Descriptions.Item>
            <Descriptions.Item label="数据版本">{evidence.dataVersion || '—'}</Descriptions.Item>
            <Descriptions.Item label="来源等级">{evidence.sourceLevel || '—'}</Descriptions.Item>
            <Descriptions.Item label="算法版本">{evidence.algorithmVersion || '—'}</Descriptions.Item>
            <Descriptions.Item label="状态版本">{evidence.stateVersion ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="观测时间">{evidence.observedAt || '—'}</Descriptions.Item>
          </Descriptions>
          <Typography.Paragraph type="secondary">
            限制：{evidence.limitations?.length ? evidence.limitations.join('；') : '无'}
          </Typography.Paragraph>
        </>
      ) : null}
    </Drawer>
  );
};

export default EvidenceDrawer;
