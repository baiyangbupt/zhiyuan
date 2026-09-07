import React from 'react';
import { Alert, Tag } from 'antd';

interface PlanningStatusProps {
  status?: string;
  stage?: string;
  message?: string;
}

export const PlanningStatus: React.FC<PlanningStatusProps> = ({ status, stage, message }) => (
  <Alert
    type={status === 'error' ? 'error' : 'info'}
    showIcon
    message={
      <span>
        规划进度 <Tag color={status === 'completed' ? 'green' : 'blue'}>{status || '进行中'}</Tag>
        {stage ? <Tag>{stage}</Tag> : null}
      </span>
    }
    description={message || '正在整理事实和规划依据'}
  />
);

export default PlanningStatus;
