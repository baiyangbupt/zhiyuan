export const sessionDetailMock = {
  code: 0,
  msg: 'success',
  data: {
    id: 5,
    userId: 2,
    userName: null,
    botVo: {
      id: 1,
      tenantId: 1,
      nickName: '本地测试机器人',
      avatarUrl: '',
      introduce: 'local bot',
      createTime: 1775430846000,
      updateTime: null,
    },
    infoSummary: '517分/本科批(批次线477分)/安徽/化学.生物.历史',
    sessionStatus: 'GOING',
    mobile: null,
    startTime: 1775432140000,
    endTime: null,
    createTime: 1775432134000,
    updateTime: 1775432140000,
    prepareType: {
      code: 'PREDICT',
      desc: '模拟填报',
    },
  },
};

export const messageListMock = {
  code: 0,
  msg: 'success',
  data: {
    current: 1,
    total: 6,
    records: [
      {
        id: 1,
        chatSessionId: 5,
        messageFrom: '0',
        messageFromUserName: null,
        contentType: 'TEXT',
        content:
          '感谢你的耐心配合，我已经结合你的分数、选科、意向地区和专业偏好生成了第一版志愿建议。右侧工作区可以继续查看候选池、草稿和排序方案。',
        feedback: 0,
        displayTime: '09:42',
        nerList: [],
        contentSegments: [
          {
            type: 'text',
            content:
              '感谢你的耐心配合，我已经结合你的分数、选科、意向地区和专业偏好生成了第一版志愿建议。右侧工作区可以继续查看候选池、草稿和排序方案。',
          },
        ],
      },
      {
        id: 2,
        chatSessionId: 5,
        messageFrom: '0',
        messageFromUserName: null,
        contentType: 'TEXT',
        content:
          '如果你想进一步调整，可以直接告诉我：例如“我更想去广东”“想找更稳一些的师范类专业”“帮我补几个更适合考公的专业”。',
        feedback: 0,
        displayTime: null,
        nerList: [],
        contentSegments: [
          {
            type: 'text',
            content:
              '如果你想进一步调整，可以直接告诉我：例如“我更想去广东”“想找更稳一些的师范类专业”“帮我补几个更适合考公的专业”。',
          },
        ],
      },
      {
        id: 3,
        chatSessionId: 5,
        messageFrom: 'user',
        messageFromUserName: '学生',
        contentType: 'TEXT',
        content: '我想找一些更适合以后进体制的专业，最好还是华南地区。',
        feedback: 0,
        displayTime: null,
        nerList: [
          {
            id: 301,
            tagName: '华南地区',
            startPos: 20,
            endPos: 24,
            category: 'REGION',
            tagAnalyze: null,
          },
        ],
        contentSegments: [
          {
            type: 'text',
            content: '我想找一些更适合以后进体制的专业，最好还是',
          },
          {
            type: 'keyword',
            content: '华南地区',
            nerItem: {
              id: 301,
              tagName: '华南地区',
              startPos: 20,
              endPos: 24,
              category: 'REGION',
              tagAnalyze: null,
            },
          },
          {
            type: 'text',
            content: '。',
          },
        ],
      },
      {
        id: 4,
        chatSessionId: 5,
        messageFrom: '0',
        messageFromUserName: null,
        contentType: 'TEXT',
        content:
          '可以，我先按“考公/体制内适配度 + 华南地区优先”帮你筛一轮，再把更适合进入草稿的项高亮出来。',
        feedback: 0,
        displayTime: null,
        nerList: [],
        contentSegments: [
          {
            type: 'text',
            content:
              '可以，我先按“考公/体制内适配度 + 华南地区优先”帮你筛一轮，再把更适合进入草稿的项高亮出来。',
          },
        ],
      },
      {
        id: 5,
        chatSessionId: 5,
        messageFrom: '0',
        messageFromUserName: null,
        contentType: 'CARD',
        content: JSON.stringify({
          type: 'planningWorkspaceAction',
          title: '已定位到候选池中的重点志愿',
          content: '我筛出了 12 个更适合体制内方向、且地域更贴近华南的候选志愿。',
          actionText: '查看候选池',
          targetView: 'draft',
          volunteerIds: [
            '34020261000722_260',
            '34020261001059_260',
            '34020261001059_842',
          ],
          refresh: true,
        }),
        feedback: 0,
        displayTime: null,
        nerList: [],
        contentSegments: [],
      },
      {
        id: 6,
        chatSessionId: 5,
        messageFrom: '0',
        messageFromUserName: null,
        contentType: 'TEXT',
        content:
          '你可以先看我标出的这些候选项。如果你认可，我可以继续帮你把其中更稳妥的一部分加入草稿，再进一步调整顺序。',
        feedback: 0,
        displayTime: null,
        nerList: [],
        contentSegments: [
          {
            type: 'text',
            content:
              '你可以先看我标出的这些候选项。如果你认可，我可以继续帮你把其中更稳妥的一部分加入草稿，再进一步调整顺序。',
          },
        ],
      },
    ],
  },
};

export const planningStateMock = {
  code: 0,
  msg: 'success',
  data: {
    sessionId: 5,
    version: 4,
    phase: 'reviewed',
    staleFlags: {
      candidatePool: false,
      orderedPlan: false,
      review: false,
    },
    profileState: {
      explicitProfile: {
        positiveMajors: ['法学类', '经济学类', '工商管理类', '心理学类'],
        negativeMajors: ['土木类'],
        positiveSchools: [],
        negativeSchools: [],
        positiveRegions: ['广东', '广西', '海南'],
        negativeRegions: ['东北地区'],
        strengthSubjects: ['化学', '生物', '历史'],
      },
      latentProfile: {
        futureDevelopment: {
          careerTypes: ['考公', '教师', '事业单位'],
          industryPreferences: ['教育', '公共管理'],
          workStylePreferences: ['稳定', '可持续成长'],
          organizationPreferences: ['体制内', '公办院校'],
          lifeStylePreferences: ['希望留在南方'],
          stabilityVsIncome: '偏稳定',
        },
        interestPersonality: {
          subjectInterests: ['法学', '经济', '心理'],
          activityInterests: ['表达沟通', '组织协调'],
          hobbyTags: ['阅读', '写作'],
          personalityTraits: ['稳重', '细致', '责任感强'],
          workPreference: ['不希望太激进的就业路径'],
        },
        familyContext: {
          financialLevel: '中等',
          tuitionTolerance: '中低',
          familyExpectations: ['更希望未来稳定', '接受师范和法学方向'],
          parentOccupations: ['企业职员', '个体经营'],
          resourceSupportTags: ['接受省内外读书', '更倾向公办'],
        },
      },
      physicalConstraints: {
        vision: {
          left: null,
          right: null,
        },
        colorVision: [],
        height: null,
        specialLimits: [],
      },
    },
    constraintState: {
      hardConstraints: {
        mustIncludeRegions: [],
        mustExcludeRegions: [],
        mustIncludeMajors: [],
        mustExcludeMajors: [],
      },
      softPreferences: {
        preferRegions: ['广东', '广西', '海南'],
        preferMajors: ['法学类', '经济学类', '心理学类'],
        preferSchools: [],
        riskStyle: '稳妥优先',
      },
      derivedPreferences: {
        recommendedMajorClusters: ['法学类', '教育学类', '公共管理类'],
        riskToleranceInferred: '中低',
        tuitionFlexibilityInferred: '偏低',
        employmentOrientationInferred: ['稳定就业', '体制内倾向'],
      },
    },
    candidatePoolState: {
      generatedAt: '2026-04-06T07:38:27.804+08:00',
      sourceVersion: 3,
      requiredCount: 45,
      requiredMajorCount: 6,
      userScore: 517,
      batchScore: 477,
      sourceProvinceName: '安徽',
      volunteerModel: 'majorGroup',
      summary: {
        total: 2590,
        tierCounts: {
          冲: 834,
          稳: 453,
          保: 1303,
        },
      },
      items: [
        {
          volunteerId: '34020261000722_260',
          tier: '冲',
          schoolId: '454',
          schoolName: '广东技术师范大学001专业组',
          provinceName: '广东',
          cityName: '广州',
          majorId: '260',
          majorName: '法学',
          tuitionPerYear: 5050,
          finalScore: 99,
          admissionRatio: 1,
          rankInTier: 1,
          mustSubjects: ['历'],
          reasonCodes: ['意向省份', '意向专业类', '公办', '师范', '学费适中'],
          riskFlags: ['province_preferred', 'career_fit:public_service'],
        },
        {
          volunteerId: '34020261001059_260',
          tier: '冲',
          schoolId: '317',
          schoolName: '海南师范大学001专业组',
          provinceName: '海南',
          cityName: '海口',
          majorId: '260',
          majorName: '法学',
          tuitionPerYear: 4620,
          finalScore: 94,
          admissionRatio: 1,
          rankInTier: 6,
          mustSubjects: ['历'],
          reasonCodes: ['意向省份', '意向专业类', '公办', '师范'],
          riskFlags: ['province_preferred'],
        },
        {
          volunteerId: '34020261001999_842',
          tier: '稳',
          schoolId: '600',
          schoolName: '广西师范大学002专业组',
          provinceName: '广西',
          cityName: '桂林',
          majorId: '842',
          majorName: '会计学',
          tuitionPerYear: 4600,
          finalScore: 88,
          admissionRatio: 68,
          rankInTier: 18,
          mustSubjects: ['历'],
          reasonCodes: ['公办', '师范', '就业稳定', '考公适配'],
          riskFlags: ['career_fit:public_service'],
        },
      ],
    },
    draftPlanState: {
      items: [
        {
          volunteerId: '34020261001999_842',
          tier: '稳',
          schoolName: '广西师范大学002专业组',
          majorName: '会计学',
          locked: false,
          source: 'agent_select',
        },
        {
          volunteerId: '34020261001059_260',
          tier: '冲',
          schoolName: '海南师范大学001专业组',
          majorName: '法学',
          locked: true,
          source: 'user_select',
        },
      ],
      summary: {
        total: 2,
        tierCounts: {
          冲: 1,
          稳: 1,
        },
      },
    },
    orderedPlanState: {
      items: [
        {
          position: 1,
          volunteerId: '34020261001059_260',
          tier: '冲',
          schoolName: '海南师范大学001专业组',
          majorName: '法学',
          locked: true,
          pinned: true,
          pinnedPosition: 1,
          orderedBy: 'user',
          orderReason: 'user_pin',
          source: 'user_select',
        },
        {
          position: 2,
          volunteerId: '34020261001999_842',
          tier: '稳',
          schoolName: '广西师范大学002专业组',
          majorName: '会计学',
          locked: false,
          pinned: false,
          orderedBy: 'system',
          orderReason: 'gradient_balance',
          source: 'agent_select',
        },
      ],
      summary: {
        total: 2,
        tierCounts: {
          冲: 1,
          稳: 1,
        },
        gradientOk: true,
        safetyOk: false,
      },
    },
    reviewState: {
      summary: {
        total: 6,
        passedCount: 3,
        warnCount: 2,
        riskCount: 1,
      },
      checks: [
        {
          code: 'ratio_distribution',
          level: 'warn',
          passed: false,
          summary: '当前冲稳保数量分布还不完整',
          detail: '当前仅形成 2 条排序结果，尚未达到官方要求的完整志愿数量。',
          suggestedAction: '建议继续从候选池补充稳区和保区项目。',
          affectedVolunteerIds: ['34020261001059_260', '34020261001999_842'],
        },
        {
          code: 'safety_guard',
          level: 'risk',
          passed: false,
          summary: '本省保底志愿数量不足',
          detail: '当前保区间中本省院校数量少于 2 所。',
          suggestedAction: '建议优先补充安徽省内保底志愿。',
          affectedVolunteerIds: [],
        },
        {
          code: 'high_tuition',
          level: 'info',
          passed: true,
          summary: '当前方案未发现高收费专业',
          detail: null,
          suggestedAction: null,
          affectedVolunteerIds: [],
        },
      ],
      compensationPreview: {
        status: 'ready',
        sourceVersion: 4,
        totalActions: 1,
        actions: [
          {
            type: 'fill_safe_gap',
            level: 'warn',
            summary: '补充 2 个本省保底志愿',
            detail: '优先建议补入安徽省内公办院校中录取风险较低的专业组。',
            sourceCheckCode: 'safety_guard',
            volunteerIds: ['34020261008888_102', '34020261007777_221'],
          },
        ],
      },
    },
    pendingActions: [
      {
        type: 'confirm_select',
        level: 'info',
        summary: '确认是否将 2 个推荐候选加入草稿',
        detail: '系统已筛出更适合体制内方向的候选志愿，等待用户确认。',
        sourceCheckCode: 'workspace_action',
        volunteerIds: ['34020261000722_260', '34020261001059_260'],
      },
    ],
  },
};

export const userBasicProfileMock = {
  code: 0,
  msg: 'success',
  data: {
    userBasic: [
      { name: '省份', value: ['安徽'] },
      { name: '年份', value: ['2026'] },
      { name: '科类', value: ['历史类'] },
      { name: '批次', value: ['本科批'] },
      { name: '优势学科', value: ['历史', '生物'] },
    ],
    userScore: [
      { name: '总分', value: ['517'] },
      { name: '位次', value: ['约 24567'] },
      { name: '化学', value: ['A'] },
      { name: '生物', value: ['A'] },
      { name: '历史', value: ['A+'] },
    ],
  },
};

export const userDynasticProfileMock = {
  code: 0,
  msg: 'success',
  data: [
    {
      name: '地域-省份',
      pDetails: [
        {
          dimension: 'cityProvince',
          polarity: 'POSITIVE',
          label: '广东',
          code: '440000',
          emotion: 'Strong',
          emotionDesc: '强烈',
        },
        {
          dimension: 'cityProvince',
          polarity: 'POSITIVE',
          label: '海南',
          code: '460000',
          emotion: 'Neutral',
          emotionDesc: '一般',
        },
      ],
      nDetails: [
        {
          dimension: 'cityProvince',
          polarity: 'NEGATIVE',
          label: '东北地区',
          code: null,
          emotion: 'Weak',
          emotionDesc: '轻微',
        },
      ],
    },
    {
      name: '本科专业',
      pDetails: [
        {
          dimension: 'majorLevel2',
          polarity: 'POSITIVE',
          label: '法学类',
          code: '08',
          emotion: 'Strong',
          emotionDesc: '强烈',
        },
        {
          dimension: 'majorLevel2',
          polarity: 'POSITIVE',
          label: '经济学类',
          code: '03',
          emotion: 'Neutral',
          emotionDesc: '一般',
        },
        {
          dimension: 'majorLevel2',
          polarity: 'POSITIVE',
          label: '心理学类',
          code: '71',
          emotion: 'Neutral',
          emotionDesc: '一般',
        },
      ],
      nDetails: [
        {
          dimension: 'majorLevel2',
          polarity: 'NEGATIVE',
          label: '土木类',
          code: '81',
          emotion: 'Weak',
          emotionDesc: '轻微',
        },
      ],
    },
    {
      name: '院校',
      pDetails: [
        {
          dimension: 'college',
          polarity: 'POSITIVE',
          label: '师范类院校',
          code: null,
          emotion: 'Neutral',
          emotionDesc: '一般',
        },
      ],
      nDetails: [],
    },
  ],
};

