import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import { Button, Spin, message } from 'antd';
import { MessageOutlined, OrderedListOutlined } from '@ant-design/icons';
import MessageList from '@/pageComponents/sessionDetailV2/MessageList';
import LegacyVolunteer from '@/pageComponents/sessionDetailLegacy';
import { IDialogueResData, IUserInfoParams } from '@/interface/api/sessionDetail';
import { getSessionDetailApi } from '@/service/apis/sessionDetail';
import { checkUserRightsApi } from '@/service/apis/user';
import { getStorage, getValueFromUrlBykey } from '@/utils/tool';
import { navigateTo } from '@/utils/router';
import useAuthParams from '@/hooks/useAuthParams';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import style from './style.module.scss';

type MobileTab = 'chat' | 'plan';

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
  const [mobileTab, setMobileTab] = useState<MobileTab>('plan');
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
    navigateTo('/session', {
      tenantId,
      botId,
      userId,
    });
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
            <div className={style.mobileTabs}>
              <Button
                type={mobileTab === 'plan' ? 'primary' : 'default'}
                icon={<OrderedListOutlined />}
                onClick={() => setMobileTab('plan')}
              >
                志愿表
              </Button>
              <Button
                type={mobileTab === 'chat' ? 'primary' : 'default'}
                icon={<MessageOutlined />}
                onClick={() => setMobileTab('chat')}
              >
                对话
              </Button>
            </div>
            <div className={style.mobileContent}>
              {mobileTab === 'plan' ? renderPlan() : renderChat()}
            </div>
          </main>
        ) : (
          <main className={style.desktopMain}>
            {renderChat()}
            {renderPlan()}
          </main>
        )}
      </Spin>
    </div>
  );
};

export default SessionDetailLegacy;
