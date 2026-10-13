import test from 'node:test';
import assert from 'node:assert/strict';

import { buildIntentTags } from './intentTags.mjs';

// 根因回归（2026-10-13 队列 21，会话 10041981）：4.0 apply 只写
// hardPlanningObjectives.priorityRules（「北京同档靠前」），横幅旧实现不读它 →
// 顶部误显示"暂无已记录意向"。这条断言守住"权威字段派生标签"。
test('根因回归：只有 hardPlanningObjectives.priorityRules 也出标签（优先地域: 北京（同档靠前））', () => {
  const tags = buildIntentTags({
    constraintState: {
      hardConstraints: {},
      hardPlanningObjectives: {
        priorityRules: [
          {
            domain: 'region',
            key: 'city',
            values: ['北京'],
            orderingTarget: 'rank_before',
            scope: 'within_tier',
            rawText: '北京的更优先一些',
          },
        ],
      },
    },
  });
  assert.deepEqual(tags, [
    { key: '优先地域-北京（同档靠前）', text: '优先地域: 北京（同档靠前）', type: 'positive' },
  ]);
});

test('跨源去重：softPreferences/explicitProfile 与 priorityRules 都有"北京"只出一个（权威优先）', () => {
  const tags = buildIntentTags({
    constraintState: {
      softPreferences: { preferRegions: ['北京', '上海'] },
      hardPlanningObjectives: {
        priorityRules: [
          { domain: 'region', key: 'city', values: ['北京'], orderingTarget: 'rank_before' },
        ],
      },
    },
    profileState: { explicitProfile: { positiveRegions: ['北京'] } },
  });
  assert.deepEqual(
    tags.map(tag => tag.text),
    ['优先地域: 北京（同档靠前）', '优先地域: 上海']
  );
});

test('legacy 内部去重：softPreferences 与 explicitProfile 同值不重复（既有行为保留）', () => {
  const tags = buildIntentTags({
    constraintState: { softPreferences: { preferMajors: ['会计学'] } },
    profileState: { explicitProfile: { positiveMajors: ['会计学', '审计学'] } },
  });
  assert.deepEqual(
    tags.map(tag => tag.text),
    ['优先专业: 会计学', '优先专业: 审计学']
  );
});

test('旧会话兼容：softPreferences/explicitProfile/hardConstraints 标签原样保留（读取不删）', () => {
  const tags = buildIntentTags({
    constraintState: {
      softPreferences: { preferRegions: ['上海'], avoidMajors: ['土木工程'] },
      hardConstraints: { mustIncludeSchools: ['天津商业大学'], mustExcludeRegions: ['山东'] },
    },
    profileState: {
      explicitProfile: { positiveMajors: ['会计学'], negativeSchools: ['某学院'] },
    },
  });
  assert.deepEqual(
    tags.map(tag => ({ text: tag.text, type: tag.type })),
    [
      { text: '优先地域: 上海', type: 'positive' },
      { text: '优先专业: 会计学', type: 'positive' },
      { text: '不优先专业: 土木工程', type: 'negative' },
      { text: '不优先院校: 某学院', type: 'negative' },
      { text: '只看院校: 天津商业大学', type: 'required' },
      { text: '避开地域: 山东', type: 'excluded' },
    ]
  );
});

test('priorityRules 域映射：major/school 转专业/院校；缺省 orderingTarget 也算同档靠前，非 rank_before 不加后缀', () => {
  const tags = buildIntentTags({
    constraintState: {
      hardPlanningObjectives: {
        priorityRules: [
          { domain: 'major', key: 'major', values: ['临床医学'] },
          { domain: 'school', key: 'schools', values: ['北工大'], orderingTarget: 'rank_after' },
        ],
      },
    },
  });
  assert.deepEqual(
    tags.map(tag => tag.text),
    ['优先专业: 临床医学（同档靠前）', '优先院校: 北工大']
  );
});

test('coverageRequirements → 「至少 N 个 X」；minCount 缺省按 1', () => {
  const tags = buildIntentTags({
    constraintState: {
      hardPlanningObjectives: {
        coverageRequirements: [
          { domain: 'region', key: 'province', values: ['上海'], minCount: 5 },
          { domain: 'major', key: 'major', values: ['法学'] },
        ],
      },
    },
  });
  assert.deepEqual(
    tags.map(tag => tag.text),
    ['覆盖要求: 至少 5 个上海', '覆盖要求: 至少 1 个法学']
  );
});

test('tierQuotaGoal → 档位配比（精确/区间/比例三种 schema 都说人话，不甩裸权重）', () => {
  const exact = buildIntentTags({
    constraintState: {
      hardPlanningObjectives: {
        tierQuotaGoal: { type: 'exact_counts', sprintCount: 10, stableCount: 20, protectCount: 20 },
      },
    },
  });
  assert.deepEqual(
    exact.map(tag => tag.text),
    ['档位配比: 冲 10 个、稳 20 个、保 20 个']
  );

  const ranges = buildIntentTags({
    constraintState: {
      hardPlanningObjectives: {
        tierQuotaGoal: {
          type: 'count_ranges',
          sprint: { minCount: 8, maxCount: 15 },
          stable: { maxCount: 30 },
          protect: { minCount: 20 },
        },
      },
    },
  });
  assert.deepEqual(
    ranges.map(tag => tag.text),
    ['档位配比: 冲 8~15 个、稳 30 个以内、保 20 个以上']
  );

  const ratios = buildIntentTags({
    constraintState: {
      hardPlanningObjectives: {
        tierQuotaGoal: { type: 'ratios', sprintWeight: 2, stableWeight: 1, protectWeight: 1 },
      },
    },
  });
  assert.deepEqual(
    ratios.map(tag => tag.text),
    ['档位配比: 冲 50%、稳 25%、保 25%']
  );
});

test('多条规则/多值展开为逐值标签且 key 不重复；同值跨来源只出一次', () => {
  const tags = buildIntentTags({
    constraintState: {
      hardPlanningObjectives: {
        priorityRules: [
          { domain: 'region', values: ['北京', '上海'], orderingTarget: 'rank_before' },
        ],
      },
      softPreferences: { preferRegions: ['上海', '浙江'] },
    },
  });
  assert.deepEqual(
    tags.map(tag => tag.text),
    ['优先地域: 北京（同档靠前）', '优先地域: 上海（同档靠前）', '优先地域: 浙江']
  );
  assert.equal(new Set(tags.map(tag => tag.key)).size, tags.length);
});

test('防御：空态/异常态返回空数组；空值不产标签', () => {
  assert.deepEqual(buildIntentTags(undefined), []);
  assert.deepEqual(buildIntentTags(null), []);
  assert.deepEqual(buildIntentTags({}), []);
  assert.deepEqual(buildIntentTags({ constraintState: {} }), []);
  assert.deepEqual(
    buildIntentTags({
      constraintState: {
        hardPlanningObjectives: {
          priorityRules: [{ domain: 'region', values: [] }],
          coverageRequirements: [{ values: [] }],
          tierQuotaGoal: {},
        },
      },
    }),
    []
  );
});
