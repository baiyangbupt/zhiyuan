import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import { Drawer, message, ConfigProvider, Modal, Skeleton } from 'antd';
import { MessageOutlined } from '@ant-design/icons';
import Header from '@/pageComponents/customer/Header';
import SessionListDrawer from '@/pageComponents/customer/SessionListDrawer';
import CustomerDetailFlow from '@/pageComponents/customerDetail/CustomerDetailFlow';
import { useIsMinip } from '@/hooks/useIsMinip';
import useAuthParams from '@/hooks/useAuthParams';
import styles from './style.module.scss';
import { Swiper, SwiperSlide } from 'swiper/react';
import { Autoplay, Navigation } from 'swiper/modules';
import 'swiper/css';
import 'swiper/css/navigation';
import 'swiper/css/autoplay';
import { getStorage, EStorageKey, getValueFromUrlBykey } from '@/utils/tool';
import TipsImg from '@/images/icons/tip.png';
import TextImg from '@/images/icons/text.png';
import ButtonImg from '@/images/icons/startBtn.png';
import TeacherInfoImg from '@/images/icons/teacherInfo.png';
import ServiceImg from '@/images/icons/service.png';
import ProcessImg from '@/images/icons/process.png';
// import CaseImg from '@/images/icons/case.png';
import CaseImg1 from '@/images/icons/caseStu-1.png';
import CaseImg2 from '@/images/icons/caseStu-2.png';
import CaseImg3 from '@/images/icons/caseStu-3.png';
import CaseImg4 from '@/images/icons/caseStu-4.png';
import CaseImg5 from '@/images/icons/caseStu-5.png';
import CaseImg6 from '@/images/icons/caseStu-6.png';
import CaseImg7 from '@/images/icons/caseStu-7.png';
import UserInfoModal from '@/pageComponents/customer/UserInfoModal';
import { navigateTo } from '@/utils/router';
import { checkUserRightsApi } from '@/service/apis/user';
import { getSessionList } from '@/service/apis/sessionDetail';

const preloadImages = (urls: string[]) => {
  return Promise.all(
    urls.map(
      url =>
        new Promise<void>(resolve => {
          const img = new Image();
          img.src = url;
          img.onload = () => resolve();
          img.onerror = () => resolve();
        })
    )
  );
};

const Customer: React.FC = () => {
  const isMinip = useIsMinip();
  const { botId, tenantId } = useAuthParams();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [sessionListDrawerVisible, setSessionListDrawerVisible] = useState(false);
  const [customerDetailDrawerVisible, setCustomerDetailDrawerVisible] = useState(false);
  const [flowStepIndicator, setFlowStepIndicator] = useState({ stepIndex: 0, stepTitle: '高考信息' });
  const [isLoading, setIsLoading] = useState(true);
  const [isCheckingRights, setIsCheckingRights] = useState(false);
  const [isCheckingLatestSession, setIsCheckingLatestSession] = useState(true);

  const storedHasAddInfo = getStorage(EStorageKey.HASADDINFO) as boolean;
  const storedUserInfo: any = getStorage('userInfo') || '{}';
  const userInfo = JSON.parse(storedUserInfo);

  useEffect(() => {
    setIsModalVisible(!storedHasAddInfo);
  }, [storedHasAddInfo]);

  useEffect(() => {
    if (getValueFromUrlBykey('openSessionList') === '1') {
      setSessionListDrawerVisible(true);
    }
  }, []);

  useEffect(() => {
    const openSessionList = getValueFromUrlBykey('openSessionList') === '1';

    if (!tenantId || !botId || openSessionList) {
      setIsCheckingLatestSession(false);
      return;
    }

    let cancelled = false;

    const redirectToLatestSession = async () => {
      try {
        const { code, data } = await getSessionList(tenantId, {
          botId,
          statusList: [],
          orderBy: [{ isAsc: false, orderBy: 'id' }],
          searchWord: '',
          page: 1,
          pageSize: 1,
        });

        if (cancelled) {
          return;
        }

        const latestSession = data?.records?.[0];
        if (code === 0 && latestSession) {
          navigateTo('/sessionDetailV2', {
            chatSessionId: latestSession.id,
            userId: String(latestSession.userId),
            userName: String(latestSession.userName || ''),
            page: 1,
            pageSize: 10,
          });
          return;
        }
      } catch (error) {
        console.error('获取最新会话失败', error);
      } finally {
        if (!cancelled) {
          setIsCheckingLatestSession(false);
        }
      }
    };

    redirectToLatestSession();

    return () => {
      cancelled = true;
    };
  }, [tenantId, botId]);

  useEffect(() => {
    const urls = [
      TipsImg.src,
      TextImg.src,
      ButtonImg.src,
      TeacherInfoImg.src,
      ServiceImg.src,
      ProcessImg.src,
      // CaseImg.src,
      CaseImg1.src,
      CaseImg2.src,
      CaseImg3.src,
      CaseImg4.src,
      CaseImg5.src,
      CaseImg6.src,
      CaseImg7.src,
    ];
    preloadImages(urls).then(() => setIsLoading(false));
  }, []);

  return (
    <ConfigProvider
      theme={{
        hashed: false,
        token: {
          colorPrimary: '#FF443D',
          colorPrimaryHover: '#FF443D',
          colorPrimaryActive: '#FF443D',
        },
      }}
    >
      <Head>
        <title>高途AI志愿填报-首页</title>
      </Head>
      {isLoading || isCheckingLatestSession ? (
        // 🦴 骨架屏部分
        <div className={styles.skeletonWrapper}>
          <div className={styles.skeletonContent}>
            <Skeleton.Avatar active size={64} shape="circle" />
            <Skeleton active paragraph={{ rows: 4 }} />
            <Skeleton.Button active size="large" shape="round" />
            <Skeleton.Image active style={{ width: 200, height: 120, marginTop: 24 }} />
          </div>
        </div>
      ) : (
        // 🧾 正式页面部分
        <div className={styles.customerWrapper}>
          <div className={styles.firstPart}>
            <Header userInfo={userInfo} />
            <div className={styles.assistant}>
              <div className={styles.assInteraction}>
                <div className={styles.assTop}>
                  <div className={styles.assTip}>
                    <img src={TipsImg.src} alt="提示图标" className={styles.illustrationImage} />
                  </div>
                  <div className={styles.assText}>
                    <img src={TextImg.src} alt="文字信息" className={styles.illustrationImage} />
                  </div>
                </div>
                <div
                  className={styles.assButton}
                  onClick={async () => {
                    if (isCheckingRights) {
                      return;
                    }
                    setIsCheckingRights(true);
                    try {
                      const { code, data, msg } = await checkUserRightsApi({
                        checkPoint: 'CreateSession',
                      });
                      if (code === 0 && data?.canOperate) {
                        if (isMinip) {
                          setCustomerDetailDrawerVisible(true);
                        } else {
                          navigateTo('/customerDetail');
                        }
                      } else {
                        Modal.info({
                          title: '提示',
                          content: data?.reason || msg || '当前权益不足，无法继续此操作',
                        });
                      }
                    } catch (error) {
                      message.error('权益校验失败，请稍后重试');
                    } finally {
                      setIsCheckingRights(false);
                    }
                  }}
                >
                  <span>开启志愿填报</span>
                </div>
              </div>
              <div className={styles.assInfo}>
                <img src={TeacherInfoImg.src} alt="教师信息" className={styles.teacherInfoImage} />
              </div>
            </div>
          </div>

          <div className={styles.service}>
            <div className={styles.partContainer}>
              <div className={styles.title}>服务特色</div>
              <div className={styles.serviceContainer}>
                <img src={ServiceImg.src} alt="服务特色" className={styles.illustrationImage} />
              </div>
            </div>
          </div>

          <div className={styles.lastPart}>
            <div className={styles.partContainer}>
              <div className={styles.process}>
                <div className={styles.title}>填报流程</div>
                <div className={styles.serviceContainer}>
                  <img src={ProcessImg.src} alt="填报流程" className={styles.illustrationImage} />
                </div>
              </div>
            </div>
            <div className={styles.partContainer}>
              <div className={styles.case}>
                <div className={styles.title}>成功案例</div>
                <div className={styles.serviceContainer}>
                  <div className={styles.caseWrapper}>
                    <Swiper
                      modules={[Autoplay]}
                      spaceBetween={20}
                      slidesPerView={3.5}
                      loop={true}
                      autoplay={{
                        delay: 2500,
                        disableOnInteraction: false,
                      }}
                      breakpoints={{
                        320: { slidesPerView: 1.5 },
                        768: { slidesPerView: 2.5 },
                        1024: { slidesPerView: 3.5 },
                      }}
                    >
                      {[CaseImg1, CaseImg2, CaseImg3, CaseImg4, CaseImg5, CaseImg6, CaseImg7].map(
                        (img, index) => (
                          <SwiperSlide key={index}>
                            <div className={styles.caseCard}>
                              <img
                                src={img.src}
                                alt={`案例${index + 1}`}
                                className={styles.caseImage}
                              />
                            </div>
                          </SwiperSlide>
                        )
                      )}
                    </Swiper>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <UserInfoModal
            visible={isModalVisible}
            onCancel={() => setIsModalVisible(false)}
            userInfoFromlData={userInfo}
          />

          {isMinip && (
            <div
              className={styles.sessionListFab}
              onClick={() => setSessionListDrawerVisible(true)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && setSessionListDrawerVisible(true)}
            >
              <MessageOutlined />
              <span>会话列表</span>
            </div>
          )}

          <SessionListDrawer
            visible={sessionListDrawerVisible}
            onClose={() => setSessionListDrawerVisible(false)}
            onOpenCreatePlan={
              isMinip
                ? () => {
                    setSessionListDrawerVisible(false);
                    setCustomerDetailDrawerVisible(true);
                  }
                : undefined
            }
          />

          {isMinip && (
            <Drawer
              title="志愿填报"
              placement="right"
              width="100%"
              open={customerDetailDrawerVisible}
              onClose={() => setCustomerDetailDrawerVisible(false)}
              destroyOnClose
              rootClassName={styles.customerDetailDrawer}
              extra={
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
                  <span style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
                    步骤 {flowStepIndicator.stepIndex + 1}/5
                  </span>
                  <span style={{ fontSize: 16, fontWeight: 600, color: '#ff443d' }}>
                    {flowStepIndicator.stepTitle}
                  </span>
                </div>
              }
              styles={{ body: { padding: 0, height: '100%', display: 'flex', flexDirection: 'column' } }}
            >
              {tenantId && botId && (
                <CustomerDetailFlow
                  tenantId={tenantId}
                  botId={botId}
                  embedded
                  onStepChange={(stepIndex, stepTitle) => setFlowStepIndicator({ stepIndex, stepTitle })}
                  onSuccess={params => {
                    setCustomerDetailDrawerVisible(false);
                    navigateTo('/sessionDetailV2', {
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
        </div>
      )}
    </ConfigProvider>
  );
};

export default Customer;
