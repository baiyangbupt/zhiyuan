import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Head from 'next/head';
import { Button, Drawer, Spin, Tooltip, message } from 'antd';
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
import { useMediaQuery } from '@/hooks/useMediaQuery';
import style from './style.module.scss';

const uniqueStrings = (values: Array<string | null | undefined>) =>
  Array.from(new Set(values.map(item => (item || '').trim()).filter(Boolean)));

const toDisplayString = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value).trim();
  }
  if (typeof value === 'object') {
    const item = value as Record<string, unknown>;
    return toDisplayString(
      item.name ||
        item.label ||
        item.value ||
        item.desc ||
        item.data ||
        item.subjectName ||
        item.provinceName ||
        item.majorName ||
        item.majorSubName ||
        item.schoolName
    );
  }
  return '';
};

const toDisplayStrings = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return uniqueStrings(value.map(toDisplayString));
  }
  const text = toDisplayString(value);
  return text ? [text] : [];
};

const formatFreshnessTime = (value?: string) => {
  if (!value) {
    return '';
  }
  return value.slice(0, 16).replace('T', ' ');
};

const buildDataFreshnessTip = (
  state: PlanningDataFreshnessState | null,
  checking: boolean
) => {
  if (checking) {
    return '志愿数据同步中';
  }
  const hasChanged = Boolean(state?.shouldNotify || state?.statusCode === 'changed');
  if (hasChanged) {
    const actions = [
      state?.requiresCandidateRefresh ? '刷新候选' : '',
      state?.requiresReview ? '重新审查' : '',
    ].filter(Boolean);
    return actions.length
      ? `志愿数据有更新，可${actions.join('或')}`
      : '志愿数据有更新，建议复核方案';
  }
  const checkedAt = formatFreshnessTime(state?.lastCheckedAt);
  return checkedAt ? `志愿数据最后更新 ${checkedAt}` : '';
};

const buildDataFreshnessTooltipLines = (
  state: PlanningDataFreshnessState | null,
  checking: boolean
) => {
  const lines: string[] = [];
  if (checking) {
    lines.push('正在检查最新志愿数据');
  }
  const checkedAt = formatFreshnessTime(state?.lastCheckedAt);
  if (checkedAt) {
    lines.push(`最新同步时间：${checkedAt}`);
  }
  const nextCheckAt = formatFreshnessTime(state?.nextCheckAt);
  if (nextCheckAt) {
    lines.push(`预计下次同步：${nextCheckAt}`);
  }
  if (state?.statusCode === 'changed' || state?.shouldNotify) {
    lines.push(state.summary || '检测到招生计划数据有更新');
    if (state.detail && state.detail !== state.summary) {
      lines.push(state.detail);
    }
    const changedCount =
      state.changedCount ||
      state.updatedCount ||
      state.affectedVolunteerIds?.length ||
      state.affectedUnitIds?.length ||
      0;
    if (changedCount > 0) {
      lines.push(`影响 ${changedCount} 项`);
    }
    const changeParts = [
      state.addedCount ? `新增 ${state.addedCount}` : '',
      state.removedCount ? `下线 ${state.removedCount}` : '',
      state.updatedCount ? `更新 ${state.updatedCount}` : '',
      state.invalidCount ? `失效 ${state.invalidCount}` : '',
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
  const { botId, tenantId } = useAuthParams();
  const [chatSessionId, setChatSessionId] = useState('');
  const [userId, setUserId] = useState('');
  const [isInitialized, setIsInitialized] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [scrollEleIndex, setScrollEleIndex] = useState<number>(-1);
  const [entityCardList, setEntityCardList] = useState<IDialogueResData>({});
  const [sessionStatus, setSessionStatus] = useState<string>('');
  const [infoSummary, setInfoSummary] = useState<string>('');
  const [studentName, setStudentName] = useState<string>('');
  const [prepareTypeDesc, setPrepareTypeDesc] = useState<string>('');
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
  const [dataFreshnessChecking, setDataFreshnessChecking] = useState(false);
  const [fetchFlag, setFetchFlag] = useState(1);

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

  const intentTags = useMemo(() => {
    const constraintState = planningWorkspaceState?.constraintState || {};
    const hard = (constraintState.hardConstraints || {}) as Record<string, unknown>;
    const soft = (constraintState.softPreferences || {}) as Record<string, unknown>;
    const explicit = planningWorkspaceState?.profileState?.explicitProfile || {};
    const groups: Array<{
      label: string;
      values: string[];
      type: 'positive' | 'negative' | 'required' | 'excluded';
    }> = [
      {
        label: '优先地域',
        values: uniqueStrings([
          ...toDisplayStrings(soft.preferRegions),
          ...toDisplayStrings(explicit.positiveRegions),
        ]),
        type: 'positive',
      },
      {
        label: '优先专业',
        values: uniqueStrings([
          ...toDisplayStrings(soft.preferMajors),
          ...toDisplayStrings(explicit.positiveMajors),
        ]),
        type: 'positive',
      },
      {
        label: '优先院校',
        values: uniqueStrings([
          ...toDisplayStrings(soft.preferSchools),
          ...toDisplayStrings(explicit.positiveSchools),
        ]),
        type: 'positive',
      },
      {
        label: '不优先地域',
        values: uniqueStrings([
          ...toDisplayStrings(soft.avoidRegions),
          ...toDisplayStrings(explicit.negativeRegions),
        ]),
        type: 'negative',
      },
      {
        label: '不优先专业',
        values: uniqueStrings([
          ...toDisplayStrings(soft.avoidMajors),
          ...toDisplayStrings(explicit.negativeMajors),
        ]),
        type: 'negative',
      },
      {
        label: '不优先院校',
        values: uniqueStrings([
          ...toDisplayStrings(soft.avoidSchools),
          ...toDisplayStrings(explicit.negativeSchools),
        ]),
        type: 'negative',
      },
      {
        label: '只看地域',
        values: toDisplayStrings(hard.mustIncludeRegions),
        type: 'required',
      },
      {
        label: '只看专业',
        values: toDisplayStrings(hard.mustIncludeMajors),
        type: 'required',
      },
      {
        label: '只看院校',
        values: toDisplayStrings(hard.mustIncludeSchools),
        type: 'required',
      },
      {
        label: '避开地域',
        values: toDisplayStrings(hard.mustExcludeRegions),
        type: 'excluded',
      },
      {
        label: '避开专业',
        values: toDisplayStrings(hard.mustExcludeMajors),
        type: 'excluded',
      },
      {
        label: '避开院校',
        values: toDisplayStrings(hard.mustExcludeSchools),
        type: 'excluded',
      },
    ];
    return groups.flatMap(group =>
      group.values.map(value => ({
        key: `${group.label}-${value}`,
        text: `${group.label}: ${value}`,
        type: group.type,
      }))
    );
  }, [planningWorkspaceState]);

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
        setStudentName(String(data.userName || '').trim());
        setPrepareTypeDesc(data.prepareType?.desc || '');
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
        prepareTypeDesc={prepareTypeDesc}
        workspaceIntent={workspaceIntent}
        onWorkspaceIntentConsumed={() => setWorkspaceIntent(null)}
        onPlanningStateChange={handlePlanningStateChange}
        onDataFreshnessStateChange={(state, checking) => {
          setDataFreshnessState(state);
          setDataFreshnessChecking(checking);
        }}
      />
    </div>
  );

  const dataFreshnessTip = buildDataFreshnessTip(dataFreshnessState, dataFreshnessChecking);
  const dataFreshnessTooltipLines = buildDataFreshnessTooltipLines(
    dataFreshnessState,
    dataFreshnessChecking
  );

  return (
    <div className={style.sessionDetailV2}>
      <Head>
        <title>高途AI志愿填报-会话详情 V2</title>
      </Head>
      <Spin spinning={isLoading}>
        <header className={style.header}>
          <div className={style.headerContent}>
            <div className={style.headerTopRow}>
              <div className={style.headerMain}>
                <div className={style.titleBlock}>
                  <div className={style.titleLine}>
                    {studentName ? <span className={style.studentNameInline}>{studentName}的</span> : null}
                    <span className={style.title}>志愿规划工作台</span>
                  </div>
                  <div className={style.profileLine}>
                    <div className={style.summary} title={studentInfoText || infoSummary}>
                      {studentInfoText || infoSummary || '正在读取会话信息'}
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
                  {prepareTypeDesc && <span className={style.metaBadge}>{prepareTypeDesc}</span>}
                  {sessionStatus && (
                    <span
                      className={`${style.metaBadge} ${
                        sessionStatus === 'GOING' ? style.metaBadgeActive : ''
                      }`}
                    >
                      {({ GOING: '进行中', FINISHED: '已完成', WAIT: '等待中', CLOSE: '已关闭' } as Record<string, string>)[sessionStatus] || sessionStatus}
                    </span>
                  )}
                </div>
              </div>
              <div className={style.headerActions}>
                {dataFreshnessTip ? (
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
                <Button
                  className={style.sessionListButton}
                  type="primary"
                  icon={<ArrowLeftOutlined />}
                  onClick={handleOpenSessionList}
                >
                  {isMobile ? '会话列表' : '返回会话列表'}
                </Button>
              </div>
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
          styles={{ body: { padding: isMobile ? '0 12px' : 0, height: '100%' } }}
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
