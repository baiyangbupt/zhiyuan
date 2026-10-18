import React from 'react';
import { Card, Space, Tag, Typography } from 'antd';

import {
  dataGapText,
  landingText,
  scenarioCondition,
  scenarioTitle,
} from './interpretationCardText.mjs';

/**
 * 录取解读卡（`interpretation.preview`）。
 *
 * 它只展示服务端给的**结构与条件情景**：基准/向上/向下/无保底、安全覆盖、
 * 数据完整度、顺序异常。**不展示录取概率**，也不把 base 叫“最可能”。
 * 卡片不做任何二次推断：没有 `landingEntry` 就少一行，缺字段就优雅降级。
 */
export type InterpretationScenario = {
  scenarioId?: string;
  label?: string;
  structureStatus?: string;
  condition?: string;
  landingEntry?: {
    level?: string;
    id?: string;
    position?: number;
    schoolName?: string;
    majorName?: string;
    pathTier?: string;
  };
  drivers?: string[];
  caveats?: string[];
};

export type InterpretationCaveat = {
  text?: string;
  level?: string;
  code?: string;
};

export type InterpretationPayload = {
  status?: string;
  planVersion?: number;
  admissionMode?: string;
  safetyCoverage?: string;
  dataCompletenessBand?: string;
  tierCoverage?: number;
  ratioCoverage?: number;
  dataCompleteness?: number;
  orderAnomaly?: boolean;
  baseLanding?: InterpretationScenario;
  scenarios?: InterpretationScenario[];
  caveats?: string[];
  caveatDetails?: InterpretationCaveat[];
};

type Props = {
  interpretation: InterpretationPayload;
};

const InterpretationCard: React.FC<Props> = ({ interpretation }) => {
  const scenarios = interpretation.scenarios || [];
  const gap = dataGapText(interpretation);
  const caveatDetails = (interpretation.caveatDetails || []).filter(
    item => String(item.text || '').trim(),
  );
  const hardCaveats = caveatDetails.filter(item => item.level === 'hard');
  const softCaveats = caveatDetails.filter(item => item.level !== 'hard');
  return (
    <Card size="small" data-testid="interpretation-card">
      <Space size={6} wrap>
        <Typography.Text strong>当前方案的录取解读</Typography.Text>
        <Tag color="blue">结构与条件</Tag>
        {interpretation.planVersion != null ? (
          <Tag>方案版本 {interpretation.planVersion}</Tag>
        ) : null}
      </Space>
      {interpretation.status === 'no_plan' ? (
        <div data-testid="interpretation-no-plan">
          <Typography.Text type="secondary">
            当前没有可解读的方案条目，请先排出方案。
          </Typography.Text>
        </div>
      ) : null}
      {gap ? (
        <div data-testid="interpretation-data-gap">
          <Typography.Text type="secondary">{gap}</Typography.Text>
        </div>
      ) : null}
      {scenarios.map((scenario, index) => {
        const landing = landingText(scenario.landingEntry);
        return (
          <div
            key={`${scenario.scenarioId || scenario.label || index}`}
            data-testid="interpretation-scenario"
            data-scenario={scenario.scenarioId || scenario.label || ''}
            style={{ marginTop: 8 }}
          >
            <Typography.Text strong>{scenarioTitle(scenario)}</Typography.Text>
            {scenarioCondition(scenario) ? (
              <Typography.Text type="secondary">
                （{scenarioCondition(scenario)}）
              </Typography.Text>
            ) : null}
            {landing ? <div>{landing}</div> : null}
            {(scenario.drivers || []).map((driver, driverIndex) => (
              <div key={`d-${driverIndex}`}>
                <Typography.Text type="secondary">{driver}</Typography.Text>
              </div>
            ))}
          </div>
        );
      })}
      {caveatDetails.length > 0 ? (
        <>
          {hardCaveats.length > 0 ? (
            <div data-testid="interpretation-caveats-hard" style={{ marginTop: 8 }}>
              <Typography.Text strong>硬性要求</Typography.Text>
              {hardCaveats.map((caveat, index) => (
                <div key={`h-${index}`}>
                  <Typography.Text type="secondary">{caveat.text}</Typography.Text>
                </div>
              ))}
            </div>
          ) : null}
          {softCaveats.length > 0 ? (
            <div data-testid="interpretation-caveats-soft" style={{ marginTop: 8 }}>
              <Typography.Text strong>其他提醒</Typography.Text>
              {softCaveats.map((caveat, index) => (
                <div key={`s-${index}`}>
                  <Typography.Text type="secondary">{caveat.text}</Typography.Text>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : (interpretation.caveats || []).length > 0 ? (
        <div data-testid="interpretation-caveats" style={{ marginTop: 8 }}>
          {(interpretation.caveats || []).map((caveat, index) => (
            <div key={`c-${index}`}>
              <Typography.Text type="secondary">{caveat}</Typography.Text>
            </div>
          ))}
        </div>
      ) : null}
      <div data-testid="interpretation-boundary" style={{ marginTop: 8 }}>
        <Typography.Text type="secondary">
          这是结构与条件情景说明，不是录取概率或落点预测。
        </Typography.Text>
      </div>
    </Card>
  );
};

export default InterpretationCard;
