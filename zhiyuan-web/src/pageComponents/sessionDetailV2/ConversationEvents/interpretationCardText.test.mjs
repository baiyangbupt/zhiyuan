import test from 'node:test';
import assert from 'node:assert/strict';

import {
  dataGapText,
  landingText,
  scenarioCondition,
  scenarioTitle,
} from './interpretationCardText.mjs';

test('四类情景有中文标题与条件口径', () => {
  assert.equal(scenarioTitle({ label: 'base' }), '基准情形');
  assert.equal(scenarioTitle({ label: 'upside' }), '向上情形');
  assert.equal(scenarioTitle({ label: 'downside' }), '向下情形');
  assert.equal(scenarioTitle({ label: 'no_safe' }), '无保底情形');
  assert.equal(scenarioCondition({ label: 'base' }), '前序志愿均未满足时');
  assert.equal(scenarioCondition({ label: 'upside' }), '冲档命中时');
});

test('落地条目只说位置/院校/专业/档位，不拼概率或分数', () => {
  const text = landingText({
    position: 14,
    schoolName: '潍坊学院（专业组203）',
    majorName: '',
    pathTier: '稳',
    admissionRatio: 0.55,
  });

  assert.equal(text, '第 14 个 · 潍坊学院（专业组203） · 稳档');
  assert.doesNotMatch(text, /0\.55|55%|概率/);
});

test('缺数据用“无法判断/数据缺口”，不伪装安全', () => {
  assert.equal(
    dataGapText({ safetyCoverage: '无法判断', dataCompletenessBand: '有缺口' }),
    '安全覆盖：无法判断；数据有缺口',
  );
  assert.equal(
    dataGapText({ safetyCoverage: '无保底档位', orderAnomaly: true }),
    '安全覆盖：无保底档位；存在跨档位排列（按实际顺序展示，不自动修正）',
  );
  assert.equal(dataGapText({}), '');
});
