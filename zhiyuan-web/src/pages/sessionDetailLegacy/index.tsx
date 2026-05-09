import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import { Button, Drawer, Spin, message } from 'antd';
import { MessageOutlined, OrderedListOutlined } from '@ant-design/icons';
import MessageList from '@/pageComponents/sessionDetailV2/MessageList';
import LegacyVolunteer from '@/pageComponents/sessionDetailLegacy';
import SessionListDrawer from '@/pageComponents/customer/SessionListDrawer';
import CustomerDetailFlow from '@/pageComponents/customerDetail/CustomerDetailFlow';
import { IDialogueResData, IUserInfoParams } from '@/interface/api/sessionDetail';
import { getSessionDetailApi } from '@/service/apis/sessionDetail';
import { checkUserRightsApi } from '@/service/apis/user';
import { getStorage, getValueFromUrlBykey } from '@/utils/tool';
import { navigateTo } from '@/utils/router';
import useAuthParams from '@/hooks/useAuthParams';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import style from './style.module.scss';

const SessionDetailLegacy = () => {
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
  const [prepareTypeDesc, setPrepareTypeDesc] = useState<string>('');
  const [fetchFlag, setFetchFlag] = useState(1);
  const [planDrawerVisible, setPlanDrawerVisible] = useState(false);
  const [sessionListDrawerVisible, setSessionListDrawerVisible] = useState(false);
  const [customerDetailDrawerVisible, setCustomerDetailDrawerVisible] = useState(false);
  const [flowStepIndicator, setFlowStepIndicator] = useState({
    stepIndex: 0,
    stepTitle: '高考信息',
  });
  const [doChatRights, setDoChatRights] = useState<{ canOperate: boolean; reason?: string } | null>(
    null
  );

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
        setPrepareTypeDesc(data.prepareType?.desc || '');
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

  const openV2 = () => {
    navigateTo('/sessionDetailV2', {
      chatSessionId,
      userId,
    });
  };

  const openSessionList = () => {
    setSessionListDrawerVisible(true);
  };

  if (!isInitialized || !tenantId || !botId || !chatSessionId) {
    return <div className={style.loadingPage}>加载中...</div>;
  }

  const renderChat = () => (
    <div className={style.chatPanel}>
      <MessageList
        setEntityCardList={setEntityCardList}
        routerParams={routerParams}
        scrollEleIndex={scrollEleIndex}
        setScrollEleIndex={setScrollEleIndex}
        setFetchFlag={setFetchFlag}
        doChatRights={doChatRights || undefined}
        alwaysShowQuickReplyActions={isMobile}
        quickReplyActions={
          isMobile
            ? [
                {
                  label: '志愿方案',
                  icon: <OrderedListOutlined />,
                  onClick: () => setPlanDrawerVisible(true),
                },
                {
                  label: '会话列表',
                  icon: <MessageOutlined />,
                  onClick: openSessionList,
                },
              ]
            : undefined
        }
      />
    </div>
  );

  const renderPlan = () => (
    <div className={style.planPanel}>
      <LegacyVolunteer
        routerParams={routerParams}
        version={0}
        setScrollEleIndex={setScrollEleIndex}
        entityCardList={entityCardList}
        fetchFlag={fetchFlag}
        sessionStatus={sessionStatus}
        fetchSessionDetail={fetchSessionDetail}
      />
    </div>
  );

  return (
    <div className={style.sessionDetailLegacy}>
      <Head>
        <title>高途AI志愿填报-旧版方案</title>
      </Head>
      <Spin spinning={isLoading}>
        <header className={style.header}>
          <div className={style.headerMain}>
            <div className={style.titleBlock}>
              <div className={style.title}>旧版志愿方案</div>
              <div className={style.summary}>{infoSummary || '用于迁移期查看历史方案'}</div>
            </div>
            <div className={style.headerMeta}>
              <span className={style.metaBadge}>Legacy</span>
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
            <Button onClick={openV2}>返回 V2 工作台</Button>
            <Button onClick={openSessionList}>会话列表</Button>
          </div>
        </header>

        {isMobile ? (
          <main className={style.mobileMain}>
            <div className={style.mobileContent}>{renderChat()}</div>
          </main>
        ) : (
          <main className={style.desktopMain}>
            {renderChat()}
            {renderPlan()}
          </main>
        )}
        <Drawer
          title="志愿方案"
          placement="right"
          width="100%"
          open={planDrawerVisible}
          onClose={() => setPlanDrawerVisible(false)}
          styles={{ body: { padding: isMobile ? '0 12px' : 0, height: '100%' } }}
        >
          {renderPlan()}
        </Drawer>
        <SessionListDrawer
          visible={sessionListDrawerVisible}
          onClose={() => setSessionListDrawerVisible(false)}
          onSelectSession={record => {
            navigateTo('/sessionDetailLegacy', {
              chatSessionId: record.id,
              userId: String(record.userId),
              userName: String(record.userName || ''),
              page: 1,
              pageSize: 10,
            });
          }}
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
                onSuccess={params => {
                  setCustomerDetailDrawerVisible(false);
                  navigateTo('/sessionDetailLegacy', {
                    chatSessionId: params.chatSessionId,
                    userId: params.userId,
                    userName: params.userName,
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

export default SessionDetailLegacy;
