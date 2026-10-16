import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Head from 'next/head';
import { Button, Drawer, Modal, Spin, Tooltip, message } from 'antd';
import {
  AuditOutlined,
  ArrowLeftOutlined,
  CompassOutlined,
  DownOutlined,
  InfoCircleOutlined,
  MessageOutlined,
  OrderedListOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import MessageList from '@/pageComponents/sessionDetailV2/MessageList';
import WorkspacePanel from '@/pageComponents/sessionDetailV2/WorkspacePanel';
import SessionListDrawer from '@/pageComponents/customer/SessionListDrawer';
import CustomerDetailFlow from '@/pageComponents/customerDetail/CustomerDetailFlow';
import { IDialogueResData, IUserInfoParams } from '@/interface/api/sessionDetail';
import {
  PlanningDataFreshnessState,
  PlanningStateRes,
  PlanningWorkspaceIntent,
} from '@/interface/api/volunteer';
import { getPlanningWorkspaceStateApi, getSessionDetailApi } from '@/service/apis/sessionDetail';
import { checkUserRightsApi } from '@/service/apis/user';
import { getStorage, getValueFromUrlBykey } from '@/utils/tool';
import { navigateTo } from '@/utils/router';
import useAuthParams from '@/hooks/useAuthParams';
import { hasDataFreshnessChangeSummary, shouldShowDataFreshnessNotice } from '@/utils/planningDataFreshness.mjs';
import { isPredictPrepareType, isVolunteerPrepareType } from '@/utils/prepareTypeText.mjs';
import { buildIntentTags } from '@/utils/intentTags.mjs';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { useIsMinip } from '@/hooks/useIsMinip';
import { formatSubjectShortText } from '@/utils/subjectText';
import style from './style.module.scss';

// 意向标签派生已收敛到 '@/utils/intentTags.mjs'（2026-10-13：横幅改读权威字段
// hardPlanningObjectives，softPreferences=legacy 只读仍读；派生纯逻辑+单测在模块内）。

const formatFreshnessTime = (value?: string) => {
  if (!value) {
    return '';
  }
  return value.slice(0, 16).replace('T', ' ');
};

const padFreshnessTime = (value: number) => String(value).padStart(2, '0');

const formatLocalFreshnessDateTime = (date: Date) =>
  `${date.getFullYear()}-${padFreshnessTime(date.getMonth() + 1)}-${padFreshnessTime(date.getDate())} ${padFreshnessTime(date.getHours())}:${padFreshnessTime(date.getMinutes())}`;

const addMinutesToFreshnessTime = (value?: string, minutes?: number) => {
  if (!value || !minutes) {
    return '';
  }
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return '';
  }
  return formatLocalFreshnessDateTime(new Date(timestamp + minutes * 60 * 1000));
};

const resolveFreshnessSyncedAt = (state: PlanningDataFreshnessState | null) =>
  state?.lastCheckedAt || state?.fetchTime || '';

const resolveNextFreshnessCheckAt = (state: PlanningDataFreshnessState | null) =>
  state?.nextCheckAt ||
  addMinutesToFreshnessTime(resolveFreshnessSyncedAt(state), state?.checkIntervalMinutes);

// 模式码归一已收敛到 '@/utils/prepareTypeText.mjs'（2026-10-08：code 优先，
// 修"desc=智能填报 的 PREDICT 会话被误判 VOLUNTEER"的顺序 bug）。

const buildDataFreshnessNoticeKey = (
  chatSessionId: string,
  state: PlanningDataFreshnessState | null
) => [
  'session_detail_v2_data_freshness_notice',
  chatSessionId || 'unknown',
  state?.latestSourceDataHash || state?.latestDataHash || state?.dataHash || '',
  state?.changedCount || 0,
  state?.removedCount || 0,
  state?.updatedCount || 0,
  state?.addedCount || 0,
].join(':');


const buildDataFreshnessTip = (
  state: PlanningDataFreshnessState | null,
  checking: boolean,
  prepareTypeCode?: string | null,
  prepareTypeDesc?: string
) => {
  if (isPredictPrepareType(prepareTypeCode, prepareTypeDesc)) {
    return '数据为2025年的志愿数据';
  }
  if (checking) {
    return '志愿数据同步中';
  }
  const hasChanged = state?.statusCode === 'changed';
  if (hasChanged) {
    const actions = [
      state?.requiresCandidateRefresh ? '刷新候选' : '',
      state?.requiresReview ? '重新审查' : '',
    ].filter(Boolean);
    return actions.length
      ? `志愿数据有更新，可${actions.join('或')}`
      : '志愿数据有更新，建议复核方案';
  }
  const checkedAt = formatFreshnessTime(resolveFreshnessSyncedAt(state));
  return checkedAt ? `数据同步于 ${checkedAt}` : '';
};

const splitDataFreshnessDetailLines = (detail?: string, summary?: string) => {
  if (!detail || detail === summary) {
    return [];
  }
  return detail
    .split(/\n+/)
    .map(line => line.trim())
    .filter(Boolean);
};

const buildDataFreshnessTooltipLines = (
  state: PlanningDataFreshnessState | null,
  checking: boolean,
  prepareTypeCode?: string | null,
  prepareTypeDesc?: string
) => {
  const lines: string[] = [];
  if (isPredictPrepareType(prepareTypeCode, prepareTypeDesc)) {
    lines.push('模拟填报使用2025年的志愿数据，不参与招生计划自动同步。');
    return lines;
  }
  if (checking) {
    lines.push('正在检查最新志愿数据');
  }
  const checkedAt = formatFreshnessTime(resolveFreshnessSyncedAt(state));
  if (checkedAt) {
    lines.push(`最新同步时间：${checkedAt}`);
  }
  const nextCheckAt = formatFreshnessTime(resolveNextFreshnessCheckAt(state));
  if (nextCheckAt) {
    lines.push(`预计下次同步：${nextCheckAt}`);
  }
  if (state?.statusCode === 'changed' || hasDataFreshnessChangeSummary(state)) {
    const isCurrentSummary = state?.statusCode !== 'changed';
    lines.push(
      isCurrentSummary
        ? `最近更新：${state?.summary || '检测到招生计划数据有更新'}`
        : state?.summary || '检测到招生计划数据有更新'
    );
    splitDataFreshnessDetailLines(state?.detail, state?.summary).forEach(line => lines.push(line));
    const changedCount =
      state?.changedCount ||
      state?.updatedCount ||
      state?.affectedVolunteerIds?.length ||
      state?.affectedUnitIds?.length ||
      0;
    if (changedCount > 0) {
      lines.push(`影响 ${changedCount} 项`);
    }
    const changeParts = [
      state?.addedCount ? `新增 ${state.addedCount}` : '',
      state?.removedCount ? `下线 ${state.removedCount}` : '',
      state?.updatedCount ? `更新 ${state.updatedCount}` : '',
      state?.invalidCount ? `失效 ${state.invalidCount}` : '',
    ].filter(Boolean);
    if (changeParts.length > 0) {
      lines.push(changeParts.join(' / '));
    }
  } else if (state?.lastCheckStatus === 'failed') {
    lines.push(state.summary || '招生计划检查暂时失败，系统会继续重试');
    if (state.lastError) {
      lines.push(state.lastError);
    }
  } else if (state?.lastCheckedAt) {
    lines.push('暂未检测到招生计划变化');
  }
  return lines.filter(Boolean);
};

const SessionDetailV2 = () => {
  const isMobile = useMediaQuery(768);
  const isMinip = useIsMinip();
  const isMinipMobile = isMobile && isMinip;
  const { botId, tenantId } = useAuthParams();
  const [chatSessionId, setChatSessionId] = useState('');
  const [userId, setUserId] = useState('');
  const [isInitialized, setIsInitialized] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [scrollEleIndex, setScrollEleIndex] = useState<number>(-1);
  /**
   * 会话里**最后一条提案**的落定状态（详情接口给 ✓）：冷加载时卡片状态只活在事件流里 ✗，
   * 刷新/重连后没有游标、服务端也只补在飞回合 ✓ → 卡重建不出来 ✗（F13 的第③条 ✓），
   * 所以详情里带一格 ✓，由 `MessageList` 在"回合里没画过"时补一张只读卡 ✓。
   */
  const [lastProposal, setLastProposal] = useState<{
    proposalRef?: string;
    proposalId?: string;
    actionStatus?: string;
    /** 下面几格服务端**可能**会带上（`blocked` 那一档的卡要说得出"为什么" ✓）：
     *  有就展示、没有就优雅降级 ✓——前端不依赖它们存在 ✗（口径见 `MessageList`）。 */
    kind?: string;
    scoreSummary?: Record<string, any> | null;
    title?: string;
    strategy?: string;
    blockingReason?: string;
    blockingReasonCodes?: string[];
    attemptedRuleBrief?: string;
  } | null>(null);
  const [entityCardList, setEntityCardList] = useState<IDialogueResData>({});
  const [sessionStatus, setSessionStatus] = useState<string>('');
  const [infoSummary, setInfoSummary] = useState<string>('');
  const [studentName, setStudentName] = useState<string>('');
  const [prepareTypeDesc, setPrepareTypeDesc] = useState<string>('');
  const [prepareTypeCode, setPrepareTypeCode] = useState<string>('');
  const [examYear, setExamYear] = useState<number | string | null>(null);
  const [doChatRights, setDoChatRights] = useState<{ canOperate: boolean; reason?: string } | null>(
    null
  );
  const [workspaceDrawerVisible, setWorkspaceDrawerVisible] = useState(false);
  const [sessionListDrawerVisible, setSessionListDrawerVisible] = useState(false);
  const [customerDetailDrawerVisible, setCustomerDetailDrawerVisible] = useState(false);
  const [flowStepIndicator, setFlowStepIndicator] = useState({
    stepIndex: 0,
    stepTitle: '高考信息',
  });
  const [workspaceIntent, setWorkspaceIntent] = useState<PlanningWorkspaceIntent | null>(null);
  const [planningWorkspaceState, setPlanningWorkspaceState] = useState<PlanningStateRes | null>(null);
  const [intentExpanded, setIntentExpanded] = useState(false);
  const [dataFreshnessState, setDataFreshnessState] = useState<PlanningDataFreshnessState | null>(null);
  const [dataFreshnessNoticeState, setDataFreshnessNoticeState] = useState<PlanningDataFreshnessState | null>(null);
  const [dataFreshnessChecking, setDataFreshnessChecking] = useState(false);
  const [fetchFlag, setFetchFlag] = useState(1);
  const dataFreshnessNoticeKeyRef = useRef('');

  useEffect(() => {
    setChatSessionId(getValueFromUrlBykey('chatSessionId') || '');
    const storedUserInfo = (getStorage('userInfo') as string) || '';
    let storageUserId = '';
    if (storedUserInfo) {
      try {
        const parsedUserInfo = JSON.parse(storedUserInfo);
        if (parsedUserInfo?.id) {
          storageUserId = String(parsedUserInfo.id);
        }
      } catch (error) {
        console.warn('解析本地用户信息失败，将回退到 URL 参数获取 userId');
      }
    }
    setUserId(storageUserId || getValueFromUrlBykey('userId') || '');
    setIsInitialized(true);
  }, []);

  const routerParams: IUserInfoParams = {
    tenantId,
    chatSessionId,
    botId,
    userId,
  };

  const studentSummary = planningWorkspaceState?.studentSummary;
  const studentInfoText = useMemo(() => {
    const scoreText =
      studentSummary?.score !== undefined && studentSummary?.score !== null
        ? `${studentSummary.score}分`
        : '';
    const rankText =
      studentSummary?.rank !== undefined && studentSummary?.rank !== null
        ? `${studentSummary.rank}位次`
        : '';
    const batchName = studentSummary?.batchName || '';
    const batchScore = studentSummary?.batchScore;
    const batchText = batchName
      ? `${batchName}${
          batchScore !== undefined && batchScore !== null && !batchName.includes('批次线')
            ? `(批次线${batchScore}分)`
            : ''
        }`
      : '';
    return [
      studentSummary?.sex,
      scoreText,
      rankText,
      batchText,
      studentSummary?.provinceName,
      (studentSummary?.subjects || []).join('.'),
      (studentSummary?.strengthSubjects || []).length
        ? `优势学科${(studentSummary?.strengthSubjects || []).join('、')}`
        : '',
    ]
      .filter(Boolean)
      .join('/');
  }, [studentSummary]);
  const mobileStudentInfoText = useMemo(() => {
    const scoreText =
      studentSummary?.score !== undefined && studentSummary?.score !== null
        ? `${studentSummary.score}分`
        : '';
    const rankText =
      studentSummary?.rank !== undefined && studentSummary?.rank !== null
        ? `${studentSummary.rank}位次`
        : '';
    const batchName = studentSummary?.batchName || '';
    const batchScore = studentSummary?.batchScore;
    const batchText = batchName
      ? `${batchName}${
          batchScore !== undefined && batchScore !== null && !batchName.includes('批次线')
            ? `(批次线${batchScore}分)`
            : ''
        }`
      : '';
    return [
      scoreText,
      rankText,
      batchText,
      studentSummary?.provinceName,
      formatSubjectShortText(studentSummary?.subjects),
    ]
      .filter(Boolean)
      .join('/');
  }, [studentSummary]);

  // 标签派生在 '@/utils/intentTags.mjs'（纯模块 + 单测）：权威 hardPlanningObjectives
  // →「优先地域: 北京（同档靠前）/覆盖要求/档位配比」，softPreferences=legacy 只读仍读。
  const intentTags = useMemo(
    () => buildIntentTags(planningWorkspaceState),
    [planningWorkspaceState]
  );

  const handlePlanningStateChange = useCallback((nextState: PlanningStateRes | null) => {
    setPlanningWorkspaceState(prev => {
      if (!nextState) {
        return prev;
      }
      return {
        ...(prev || {}),
        ...nextState,
        studentSummary: nextState.studentSummary || prev?.studentSummary,
        profileState: nextState.profileState || prev?.profileState,
        constraintState: nextState.constraintState || prev?.constraintState,
      };
    });
  }, []);

  const fetchPlanningHeaderState = async () => {
    if (!tenantId || !chatSessionId) {
      return;
    }
    try {
      const { code, data } = await getPlanningWorkspaceStateApi(tenantId, chatSessionId);
      if (code === 0 && data) {
        setPlanningWorkspaceState(prev => ({
          ...(prev || {}),
          ...data,
          studentSummary: data.studentSummary || prev?.studentSummary,
          profileState: data.profileState || prev?.profileState,
          constraintState: data.constraintState || prev?.constraintState,
        }));
      }
    } catch (error) {
      console.warn('获取工作台标题信息失败', error);
    }
  };

  const fetchSessionDetail = async () => {
    if (!tenantId || !chatSessionId) {
      return;
    }
    setIsLoading(true);
    try {
      const { code, data, msg } = await getSessionDetailApi(tenantId, chatSessionId);
      if (code === 0 && data) {
        setSessionStatus(data.sessionStatus || '');
        setInfoSummary(data.infoSummary || '');
        // 详情里"最后一条提案"那一格（服务端新加 ✓）：冷加载重建卡片用 ✓（见 state 声明处的注释 ✓）。
        setLastProposal((data as any).lastProposal || null);
        setStudentName(String(data.userName || '').trim());
        setPrepareTypeDesc(data.prepareType?.desc || '');
        setPrepareTypeCode(data.prepareType?.code || '');
        setExamYear(data.examYear || null);
        if (data.studentSummary) {
          setPlanningWorkspaceState(prev => ({
            ...(prev || {}),
            studentSummary: data.studentSummary,
          }));
        }
      } else {
        message.error(msg || '获取会话详情失败');
      }
    } catch (error) {
      message.error('获取会话详情异常，请稍后重试');
    }
    setIsLoading(false);
  };

  useEffect(() => {
    if (!isInitialized || !tenantId || !chatSessionId) {
      return;
    }
    fetchSessionDetail();
    fetchPlanningHeaderState();
  }, [isInitialized, tenantId, chatSessionId]);

  useEffect(() => {
    if (!isInitialized || !tenantId || !chatSessionId) {
      return;
    }
    const verifyRights = async () => {
      try {
        const { code, data, msg } = await checkUserRightsApi({
          checkPoint: 'DoChat',
        });
        if (code === 0 && data) {
          setDoChatRights(data);
        } else {
          setDoChatRights({
            canOperate: false,
            reason: data?.reason || msg || '当前权益不足，无法继续此操作',
          });
        }
      } catch (error) {
        setDoChatRights({
          canOperate: false,
          reason: '当前权益校验失败，请稍后重试',
        });
      }
    };
    verifyRights();
  }, [isInitialized, tenantId, chatSessionId]);

  useEffect(() => {
    const noticeState = dataFreshnessNoticeState;
    if (!chatSessionId || !isVolunteerPrepareType(noticeState?.prepareType || prepareTypeCode, prepareTypeDesc)) {
      return;
    }
    if (!noticeState || !shouldShowDataFreshnessNotice(noticeState)) {
      return;
    }
    const noticeKey = buildDataFreshnessNoticeKey(chatSessionId, noticeState);
    if (!noticeKey || dataFreshnessNoticeKeyRef.current === noticeKey) {
      setDataFreshnessNoticeState(null);
      return;
    }
    if (typeof window !== 'undefined' && window.localStorage.getItem(noticeKey) === '1') {
      dataFreshnessNoticeKeyRef.current = noticeKey;
      setDataFreshnessNoticeState(null);
      return;
    }
    dataFreshnessNoticeKeyRef.current = noticeKey;
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(noticeKey, '1');
    }
    const changeParts = [
      noticeState.addedCount ? `新增 ${noticeState.addedCount} 项` : '',
      noticeState.updatedCount ? `更新 ${noticeState.updatedCount} 项` : '',
      noticeState.removedCount ? `下线 ${noticeState.removedCount} 项` : '',
      noticeState.invalidCount ? `失效 ${noticeState.invalidCount} 项` : '',
    ].filter(Boolean);
    const detailLines = splitDataFreshnessDetailLines(noticeState.detail, noticeState.summary);
    const contentLines = [
      noticeState.summary || '检测到2026年招生计划数据有更新。',
      ...detailLines,
      changeParts.length ? changeParts.join(' / ') : '',
      noticeState.removedCount || noticeState.invalidCount
        ? '部分志愿可能已失效或被上游清理，方案和审查结果需要重新确认。'
        : '',
      noticeState.requiresCandidateRefresh
        ? '系统会在工作区内刷新候选和专家推荐；进入候选区可查看最新候选。'
        : '系统已刷新候选和专家推荐；当前方案未自动调整，请按需复核。',
      noticeState.requiresReview ? '建议重新审查当前方案。' : '',
    ].filter(Boolean);
    Modal.info({
      title: '2026年招生计划数据已更新',
      content: (
        <div className={style.dataFreshnessNoticeBody}>
          {contentLines.map((line, index) => (
            <div key={`${line}-${index}`}>{line}</div>
          ))}
        </div>
      ),
      okText: '知道了',
    });
    setDataFreshnessNoticeState(null);
  }, [chatSessionId, dataFreshnessNoticeState, prepareTypeCode, prepareTypeDesc]);

  const handleWorkspaceIntent = (intent: Omit<PlanningWorkspaceIntent, 'nonce'>) => {
    const shouldRefreshWorkspace = Boolean(
      intent.refresh && (
        !intent.targetView ||
        intent.refreshTargets?.some(target => ['review', 'draft', 'workingPlan'].includes(target))
      )
    );
    if (isMobile && !intent.preserveView && intent.targetView) {
      setWorkspaceDrawerVisible(true);
    }
    setWorkspaceIntent({
      ...intent,
      nonce: Date.now(),
    });
    if (shouldRefreshWorkspace) {
      setFetchFlag(prev => prev + 1);
    }
  };

  const handleOpenSessionList = () => {
    if (isMobile) {
      setSessionListDrawerVisible(true);
      return;
    }
    navigateTo('/session', {
      tenantId,
      botId,
      userId,
    });
  };

  if (!isInitialized || !tenantId || !botId || !chatSessionId) {
    return <div className={style.loadingPage}>加载中...</div>;
  }

  const renderChatPanel = (expanded: boolean = false) => (
    <div className={`${style.chatPanel} ${expanded ? style.chatPanelExpanded : ''}`}>
      <MessageList
        setEntityCardList={setEntityCardList}
        routerParams={routerParams}
        scrollEleIndex={scrollEleIndex}
        setScrollEleIndex={setScrollEleIndex}
        setFetchFlag={setFetchFlag}
        doChatRights={doChatRights || undefined}
        onWorkspaceIntent={handleWorkspaceIntent}
        lastProposal={lastProposal}
        alwaysShowQuickReplyActions={isMobile}
        quickReplyActions={
          isMobile
            ? [
                {
                  label: '志愿方案',
                  icon: <OrderedListOutlined />,
                  onClick: () => {
                    setWorkspaceIntent({
                      targetView: 'ordered',
                      refresh: true,
                      nonce: Date.now(),
                    });
                    setWorkspaceDrawerVisible(true);
                  },
                },
                {
                  label: '会话列表',
                  icon: <MessageOutlined />,
                  onClick: handleOpenSessionList,
                },
              ]
            : [
                {
                  label: '看看现在的方案',
                  icon: <OrderedListOutlined />,
                  messageText: '看看现在的方案',
                },
                {
                  label: '我适合什么方向',
                  icon: <CompassOutlined />,
                  messageText: '我适合什么方向',
                },
                {
                  label: '有哪些机会可看',
                  icon: <QuestionCircleOutlined />,
                  messageText: '有哪些机会可看',
                },
                {
                  label: '方案哪里要注意',
                  icon: <AuditOutlined />,
                  messageText: '方案哪里要注意',
                },
              ]
        }
      />
    </div>
  );

  const renderWorkspacePanel = (expanded: boolean = false) => (
    <div className={`${style.workspacePanel} ${expanded ? style.workspacePanelExpanded : ''}`}>
      <WorkspacePanel
        routerParams={routerParams}
        fetchFlag={fetchFlag}
        examYear={examYear}
        prepareTypeCode={prepareTypeCode}
        prepareTypeDesc={prepareTypeDesc}
        workspaceIntent={workspaceIntent}
        onWorkspaceIntentConsumed={() => setWorkspaceIntent(null)}
        onPlanningStateChange={handlePlanningStateChange}
        onDataFreshnessStateChange={(state, checking) => {
          setDataFreshnessState(state);
          if (shouldShowDataFreshnessNotice(state)) {
            setDataFreshnessNoticeState(state);
          }
          setDataFreshnessChecking(checking);
        }}
        mobileLayoutMode={isMinipMobile ? 'minip' : 'default'}
      />
    </div>
  );

  const effectiveFreshnessPrepareTypeCode = dataFreshnessState?.prepareType || prepareTypeCode;
  const dataFreshnessTip = buildDataFreshnessTip(
    dataFreshnessState,
    dataFreshnessChecking,
    effectiveFreshnessPrepareTypeCode,
    prepareTypeDesc
  );
  const dataFreshnessTooltipLines = buildDataFreshnessTooltipLines(
    dataFreshnessState,
    dataFreshnessChecking,
    effectiveFreshnessPrepareTypeCode,
    prepareTypeDesc
  );
  const sessionStatusText =
    ({ GOING: '进行中', FINISHED: '已完成', WAIT: '等待中', CLOSE: '已关闭' } as Record<string, string>)[sessionStatus] ||
    sessionStatus;
  const headerSummaryText = isMinipMobile ? mobileStudentInfoText : studentInfoText;

  return (
    <div className={`${style.sessionDetailV2} ${isMinipMobile ? style.minipMobile : ''}`}>
      <Head>
        <title>高途AI志愿填报-会话详情 V2</title>
      </Head>
      <Spin spinning={isLoading}>
        <header className={style.header}>
          <div className={style.headerContent}>
            <div className={style.headerTopRow}>
              <div className={style.headerMain}>
                <div className={style.titleBlock}>
                  <div className={style.titleMetaRow}>
                    <div className={style.titleLine}>
                      {studentName ? <span className={style.studentNameInline}>{studentName}的</span> : null}
                      <span className={style.title}>志愿规划工作台</span>
                    </div>
                    <div className={style.mobileHeaderMeta}>
                      {prepareTypeDesc && <span className={style.metaBadge}>{prepareTypeDesc}</span>}
                      {sessionStatus && (
                        <span
                          className={`${style.metaBadge} ${
                            sessionStatus === 'GOING' ? style.metaBadgeActive : ''
                          }`}
                        >
                          {sessionStatusText}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className={style.profileLine}>
                    <div className={style.summary} title={headerSummaryText || infoSummary}>
                      {headerSummaryText || infoSummary || '正在读取会话信息'}
                    </div>
                    <button
                      type="button"
                      className={style.intentToggleButton}
                      onClick={() => setIntentExpanded(prev => !prev)}
                      aria-expanded={intentExpanded}
                    >
                      查看意向
                      <DownOutlined
                        className={`${style.intentToggleIcon} ${
                          intentExpanded ? style.intentToggleIconExpanded : ''
                        }`}
                      />
                    </button>
                  </div>
                </div>
                <div className={style.headerMeta}>
                  {!isMinipMobile && dataFreshnessTip ? (
                    <span
                      className={`${style.dataFreshnessTip} ${
                        dataFreshnessChecking ? style.dataFreshnessTipSyncing : ''
                      } ${
                        dataFreshnessState?.statusCode === 'changed' ? style.dataFreshnessTipChanged : ''
                      }`}
                    >
                      <span className={style.dataFreshnessTipText}>{dataFreshnessTip}</span>
                      {dataFreshnessTooltipLines.length > 0 ? (
                        <Tooltip
                          title={
                            <div className={style.dataFreshnessTooltip}>
                              {dataFreshnessTooltipLines.map((line, index) => (
                                <div key={`${line}-${index}`}>{line}</div>
                              ))}
                            </div>
                          }
                        >
                          <InfoCircleOutlined className={style.dataFreshnessInfoIcon} />
                        </Tooltip>
                      ) : null}
                    </span>
                  ) : null}
                  {!isMinipMobile && prepareTypeDesc && <span className={style.metaBadge}>{prepareTypeDesc}</span>}
                  {!isMinipMobile && sessionStatus && (
                    <span
                      className={`${style.metaBadge} ${
                        sessionStatus === 'GOING' ? style.metaBadgeActive : ''
                      }`}
                    >
                      {sessionStatusText}
                    </span>
                  )}
                </div>
              </div>
              {!isMinipMobile ? (
                <div className={style.headerActions}>
                  <Button
                    className={style.sessionListButton}
                    type="primary"
                    icon={<ArrowLeftOutlined />}
                    onClick={handleOpenSessionList}
                  >
                    {isMobile ? '会话列表' : '返回会话列表'}
                  </Button>
                </div>
              ) : null}
            </div>
            {intentExpanded ? (
              <div className={style.intentSummaryRow}>
                {intentTags.length > 0 ? (
                  intentTags.map(tag => (
                    <span
                      key={tag.key}
                      className={`${style.intentSummaryTag} ${
                        style[`intentSummaryTag_${tag.type}`] || ''
                      }`}
                    >
                      {tag.text}
                    </span>
                  ))
                ) : (
                  <span className={style.intentSummaryEmpty}>暂无已记录意向</span>
                )}
              </div>
            ) : null}
          </div>
        </header>

        {isMobile ? (
          <main className={style.mobileMain}>
            <div className={style.mobileContent}>{renderChatPanel()}</div>
          </main>
        ) : (
          <main className={style.desktopMain}>
            {renderChatPanel()}
            {renderWorkspacePanel()}
          </main>
        )}
        <Drawer
          title="工作台"
          placement="right"
          width="100%"
          open={workspaceDrawerVisible}
          onClose={() => setWorkspaceDrawerVisible(false)}
          rootClassName={isMinipMobile ? style.mobileWorkspaceDrawer : undefined}
          styles={{ body: { padding: isMinipMobile ? 0 : isMobile ? '0 12px' : 0, height: '100%' } }}
        >
          {renderWorkspacePanel(true)}
        </Drawer>
        <SessionListDrawer
          visible={sessionListDrawerVisible}
          onClose={() => setSessionListDrawerVisible(false)}
          onOpenCreatePlan={() => {
            setSessionListDrawerVisible(false);
            setCustomerDetailDrawerVisible(true);
          }}
        />
        {isMobile && (
          <Drawer
            title="志愿填报"
            placement="right"
            width="100%"
            open={customerDetailDrawerVisible}
            onClose={() => setCustomerDetailDrawerVisible(false)}
            destroyOnClose
            extra={
              <div className={style.flowStepExtra}>
                <span className={style.flowStepCount}>步骤 {flowStepIndicator.stepIndex + 1}/5</span>
                <span className={style.flowStepTitle}>{flowStepIndicator.stepTitle}</span>
              </div>
            }
            styles={{
              body: { padding: 0, height: '100%', display: 'flex', flexDirection: 'column' },
            }}
          >
            {tenantId && botId && (
              <CustomerDetailFlow
                tenantId={tenantId}
                botId={botId}
                embedded
                onStepChange={(stepIndex, stepTitle) =>
                  setFlowStepIndicator({ stepIndex, stepTitle })
                }
                onSuccess={createdSession => {
                  setCustomerDetailDrawerVisible(false);
                  navigateTo('/sessionDetailV2', {
                    chatSessionId: createdSession.chatSessionId,
                    userId: createdSession.userId,
                    userName: createdSession.userName || '',
                    page: 1,
                    pageSize: 10,
                  });
                }}
                onClose={() => setCustomerDetailDrawerVisible(false)}
              />
            )}
          </Drawer>
        )}
      </Spin>
    </div>
  );
};

export default SessionDetailV2;
