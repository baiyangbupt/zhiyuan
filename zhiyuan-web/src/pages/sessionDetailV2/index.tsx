import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import { Button, Drawer, Spin, Tooltip, message } from 'antd';
import {
  AuditOutlined,
  ArrowLeftOutlined,
  CompassOutlined,
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
import { PlanningDataFreshnessState, PlanningWorkspaceIntent } from '@/interface/api/volunteer';
import { getSessionDetailApi } from '@/service/apis/sessionDetail';
import { checkUserRightsApi } from '@/service/apis/user';
import { getStorage, getValueFromUrlBykey } from '@/utils/tool';
import { navigateTo } from '@/utils/router';
import useAuthParams from '@/hooks/useAuthParams';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import style from './style.module.scss';

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
    if (isMobile && !intent.preserveView) {
      setWorkspaceDrawerVisible(true);
    }
    setWorkspaceIntent({
      ...intent,
      nonce: Date.now(),
    });
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
          <div className={style.headerMain}>
            <div className={style.titleBlock}>
              <div className={style.titleLine}>
                {studentName ? <span className={style.studentNameInline}>{studentName}的</span> : null}
                <span className={style.title}>志愿规划工作台</span>
              </div>
              <div className={style.summary}>{infoSummary || '正在读取会话信息'}</div>
            </div>
            <div className={style.headerMeta}>
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
            <Button
              className={style.sessionListButton}
              type="primary"
              icon={<ArrowLeftOutlined />}
              onClick={handleOpenSessionList}
            >
              {isMobile ? '会话列表' : '返回会话列表'}
            </Button>
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
