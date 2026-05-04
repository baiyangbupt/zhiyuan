import React, { useEffect, useState, useRef, useMemo } from 'react';
import Head from 'next/head';
import { Layout, message, Modal, Spin, Steps, Typography } from 'antd';
import { EStorageKey, getStorage } from '@/utils/tool';
import useAuthParams from '@/hooks/useAuthParams';
import { createSession, getSubjectPolicy } from '@/service/apis/sessionDetail';
import { getCollectFlowApi } from '@/service/apis/customerDetail';
import styles from './style.module.scss';
import { navigateTo } from '@/utils/router';
import { resolveCreatedSession } from '@/utils/session';
const { Sider, Content } = Layout;
const { Title } = Typography;
import Bg from '@/images/icons/bg-custom.png';
import ConfirmGkInfo from '@/pageComponents/customerDetail/Steps/ConfirmGkInfo';
import type { ICollectflowRes } from '@/interface/api/customerDetail';
import type { IActions } from '@/interface/api/customerDetail';
import WelcomeIntro from '@/pageComponents/customerDetail/Steps/WelcomeIntro';
import PersonalInfoCollect from '@/pageComponents/customerDetail/Steps/PersonalInfoCollect';
import ClarifyMajorIntention from '@/pageComponents/customerDetail/Steps/ClarifyMajorIntention';
import CityPreference from '@/pageComponents/customerDetail/Steps/CityPreference';
import VolunteerStrategy from '@/pageComponents/customerDetail/Steps/VolunteerStrategy';
import StepDoneIcon from '@/images/icons/step-done.png';
import StepCurrentIcon from '@/images/icons/step-current.png';
import Header from '@/pageComponents/customerDetail/Header';
import { useRouter } from 'next/router';
import { useMediaQuery } from '@/hooks/useMediaQuery';

const MOBILE_BREAKPOINT = 768;
const STEP_SHORT_TITLES = ['高考信息', '个人信息', '专业意向', '区域意向', '志愿方案'];

const CustomerDetail: React.FC = () => {
  const isMobile = useMediaQuery(MOBILE_BREAKPOINT);
  const [currentStep, setCurrentStep] = useState<number>(-1);
  const [stepsData, setStepsData] = useState<any>([]);
  const { botId, tenantId } = useAuthParams();
  const storedIsCustomer = getStorage(EStorageKey.ISCUSTOMER) as boolean;
  const storedUserInfo: any = getStorage('userInfo') || '{}';
  const userInfo = JSON.parse(storedUserInfo);
  const [userSubjectList, setUserSubjectList] = useState<any>([]);
  const [createSessionValues, setCreateSessionValues] = useState<any>({});
  const [createLoading, setCreateLoading] = useState<boolean>(false);
  const [finalSubmitLoading, setFinalSubmitLoading] = useState(false);

  const modalVisibleRef = useRef(false);
  const router = useRouter();

  const shouldConfirmExit = currentStep !== -1 && currentStep < 4;

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (shouldConfirmExit) {
        e.preventDefault();
        e.returnValue = '';
      }
    };

    const handlePopState = () => {
      if (!shouldConfirmExit) return;

      // 如果 Modal 已经显示，则不再弹出
      if (modalVisibleRef.current) return;

      modalVisibleRef.current = true;

      Modal.confirm({
        title: '提示',
        content: '您的步骤尚未完成，离开后将不保存已填写信息，确定要离开吗？',
        okText: '确认离开',
        cancelText: '继续填写',
        okButtonProps: {
          style: {
            backgroundColor: '#FF443D',
            color: '#fff', // 字体白色
            borderRadius: '4px', // 圆角
            border: 'none',
            padding: '0 16px',
            height: '32px',
          },
        },
        cancelButtonProps: {
          style: {
            backgroundColor: '#fff', // 灰色背景
            color: '#2C2E40', // 字体黑色
            borderRadius: '4px',
            border: '1px solid #EBEBEF',
            padding: '0 16px',
            height: '32px',
          },
        },
        onOk: () => {
          modalVisibleRef.current = false;
          // 直接跳转到首页或其他安全页面，不调用 history.back()
          router.push('/customer');
        },
        onCancel: () => {
          modalVisibleRef.current = false;
          // 压回当前页面，保持在当前步骤
          window.history.pushState(null, '', window.location.pathname);
        },
      });
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    window.addEventListener('popstate', handlePopState);

    // 初始化 history 防止直接后退
    window.history.pushState(null, '', window.location.pathname);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      window.removeEventListener('popstate', handlePopState);
    };
  }, [currentStep, router]);

  const items = [
    {
      title: '确认高考信息',
    },
    {
      title: '个人信息采集',
    },
    {
      title: '明确专业意向',
    },
    {
      title: '明确区域意向 ',
    },
    {
      title: '确认志愿方案 ',
    },
  ];

  const stepItems = items.map((step, index) => {
    // 处理已完成和进行中
    let icon = undefined; // 默认 undefined → 显示 AntD 数字
    let stepCurrent = currentStep;

    // 当 currentStep 为 -1 时，将第一步作为进行中
    const actualCurrent = currentStep === -1 ? 0 : currentStep;

    if (index < actualCurrent) {
      // 已完成
      icon = <img src={StepDoneIcon.src} alt="" style={{ width: 28, height: 28 }} />;
    } else if (index === actualCurrent) {
      // 进行中
      icon = <img src={StepCurrentIcon.src} alt="" style={{ width: 28, height: 28 }} />;
    }

    return {
      ...step,
      icon, // 仅给已完成和进行中设置 icon
    };
  });

  const getCollectFlow = async () => {
    const res = await getCollectFlowApi({ tenantId });
    const { code, data } = res;
    if (code === 0 && data) {
      setStepsData(data.majorSteps);
    } else {
      message.error(res.msg);
    }
  };

  const currentData = useMemo(() => {
    return stepsData?.find((item: ICollectflowRes) => item.order === currentStep + 2);
  }, [currentStep, stepsData]);

  useEffect(() => {
    getCollectFlow();
  }, []);

  useEffect(() => {
    const provinceCode = userInfo?.userScoreOb?.province?.code;
    if (!provinceCode) return;
    const fetchList = async () => {
      const { code, data } = await getSubjectPolicy(provinceCode);
      if (code === 0 && data) {
        setUserSubjectList(data.subjectTypeList);
      }
    };
    fetchList();
  }, []);

  // 点击继续下一步
  const handleNextStep = async (btnProps: IActions, formValues: any) => {
    console.log('点击继续下一步', btnProps, formValues);
    const values = { ...createSessionValues, ...formValues };
    setCreateSessionValues(values);
    if (currentStep === -1) {
      // 如果当前是 -1，表示第一次点击“下一步”，将 currentStep 设置为 0
      setCurrentStep(0);
    } else if (btnProps.actionType === 'next') {
      setCurrentStep(prev => prev + 1);
    } else if (btnProps.actionType === 'autoNext') {
      // setCurrentStep(prev => prev + 1);
    } else if (btnProps.actionType === 'finalSubmit') {
      try {
        setCreateLoading(true);
        setFinalSubmitLoading(true); // 打开 loading

        const { code, data, msg } = await createSession(tenantId, { botId, ...values });
        setCreateLoading(false);
        setFinalSubmitLoading(false); // 关闭 loading

        if (code === 0) {
          const createdSession = await resolveCreatedSession(tenantId, botId, data);
          if (!createdSession) {
            message.error('创建成功，但未拿到会话信息，请返回会话列表重试');
            return;
          }
          message.success('创建会话成功');
          navigateTo('/sessionDetailV2', {
            chatSessionId: createdSession.id,
            userId: createdSession.userId,
            userName: createdSession.userName,
            page: 1,
            pageSize: 10,
          });
        } else {
          message.error(msg || '创建会话失败，请稍后重试');
        }
      } catch (error) {
        setCreateLoading(false);
        setFinalSubmitLoading(false); // 关闭 loading
        message.error('请求失败，请稍后重试');
      }
    }
  };

  const mainRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    mainRef.current?.scrollTo({
      top: 0,
      behavior: 'smooth',
    });
  }, [currentStep]);

  useEffect(() => {
    if (!isMobile) return;
    const html = document.documentElement;
    const body = document.body;
    const prevHtmlOverflowX = html.style.overflowX;
    const prevBodyOverflowX = body.style.overflowX;
    const prevHtmlWidth = html.style.width;
    const prevBodyWidth = body.style.width;
    html.style.overflowX = 'hidden';
    body.style.overflowX = 'hidden';
    html.style.width = '100%';
    body.style.width = '100%';
    return () => {
      html.style.overflowX = prevHtmlOverflowX;
      body.style.overflowX = prevBodyOverflowX;
      html.style.width = prevHtmlWidth;
      body.style.width = prevBodyWidth;
    };
  }, [isMobile]);

  return (
    <Layout className={styles.antLayout}>
      <Head>
        <title>高途AI志愿填报-志愿填报流程</title>
      </Head>
      {/* <Header
        className={styles.headerStyle}
        onClick={() => navigateTo(storedIsCustomer ? '/customer' : '/session')}
      >
        <img src={Logo.src} alt="高途logo" />
        <Divider type="vertical" className={styles.divider} />
        <Text type="secondary" className={styles.text}>
          基于您的高考成绩和志愿偏好，为您评估现有志愿方案，并提供科学的志愿填报建议
        </Text>
      </Header> */}

      <Header userInfo={userInfo} />
      {/* 全屏 loading：接口耗时长，移动端需明显反馈 */}
      <Spin
        spinning={finalSubmitLoading}
        tip="正在提交志愿信息，请稍候..."
        size="large"
        fullscreen
      />
      <Layout className={isMobile ? styles.mobileLayout : undefined}>
        {isMobile ? (
          <>
            <div className={styles.mobileStepBar}>
              <div className={styles.mobileStepIndicator}>
                <span className={styles.mobileStepLabel}>
                  步骤 {((currentStep === -1 ? 0 : currentStep) + 1)}/5
                </span>
                <span className={styles.mobileStepTitle}>
                  {STEP_SHORT_TITLES[currentStep === -1 ? 0 : currentStep]}
                </span>
              </div>
            </div>
            <Content className={styles.mainStyle} ref={mainRef}>
              {currentStep == -1 && (
                <WelcomeIntro stepsData={currentData} onNextStep={handleNextStep} />
              )}
              {currentStep == 0 && (
                <ConfirmGkInfo stepsData={currentData} onNextStep={handleNextStep} />
              )}
              {currentStep == 1 && (
                <PersonalInfoCollect
                  userSubjectList={userSubjectList}
                  stepsData={currentData}
                  onNextStep={handleNextStep}
                />
              )}
              {currentStep == 2 && (
                <ClarifyMajorIntention
                  stepsData={currentData}
                  paramsValues={createSessionValues}
                  onNextStep={handleNextStep}
                />
              )}
              {currentStep === 3 && (
                <CityPreference stepsData={currentData} onNextStep={handleNextStep} />
              )}
              {currentStep == 4 && (
                <VolunteerStrategy
                  stepsData={currentData}
                  onNextStep={handleNextStep}
                  loading={createLoading}
                  finalSubmitLoading={finalSubmitLoading}
                  setFinalSubmitLoading={setFinalSubmitLoading}
                />
              )}
            </Content>
          </>
        ) : (
          <>
            <Sider width={'40%'} theme="light" className={styles.sideStyle}>
              <img src={Bg.src} alt="" />
              <div className="step-container">
                <Title level={4}>完成全部对话，生成专属于你的志愿表</Title>
                <Steps
                  size="small"
                  current={currentStep === -1 ? 0 : currentStep}
                  labelPlacement="vertical"
                  items={stepItems}
                />
              </div>
            </Sider>
            <Content className={styles.mainStyle} ref={mainRef}>
              {currentStep == -1 && (
                <WelcomeIntro stepsData={currentData} onNextStep={handleNextStep} />
              )}
              {currentStep == 0 && (
                <ConfirmGkInfo stepsData={currentData} onNextStep={handleNextStep} />
              )}
              {currentStep == 1 && (
                <PersonalInfoCollect
                  userSubjectList={userSubjectList}
                  stepsData={currentData}
                  onNextStep={handleNextStep}
                />
              )}
              {currentStep == 2 && (
                <ClarifyMajorIntention
                  stepsData={currentData}
                  paramsValues={createSessionValues}
                  onNextStep={handleNextStep}
                />
              )}
              {currentStep === 3 && (
                <CityPreference stepsData={currentData} onNextStep={handleNextStep} />
              )}
              {currentStep == 4 && (
                <VolunteerStrategy
                  stepsData={currentData}
                  onNextStep={handleNextStep}
                  loading={createLoading}
                  finalSubmitLoading={finalSubmitLoading}
                  setFinalSubmitLoading={setFinalSubmitLoading}
                />
              )}
            </Content>
          </>
        )}
      </Layout>
    </Layout>
  );
};

export default CustomerDetail;
