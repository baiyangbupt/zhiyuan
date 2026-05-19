import React, { useEffect, useMemo, useRef, useState } from 'react';
import { message } from 'antd';
import { getCollectFlowApi } from '@/service/apis/customerDetail';
import { createSession, getSubjectPolicy } from '@/service/apis/sessionDetail';
import { navigateTo } from '@/utils/router';
import { getStorage } from '@/utils/tool';
import { resolveCreatedSession } from '@/utils/session';
import {
  clearCustomerDetailDraft,
  loadCustomerDetailDraft,
  saveCustomerDetailDraft,
} from '@/utils/customerDetailDraft';
import { hydrateCreateSessionBatch } from '@/utils/customerDetailSession';
import type { ICollectflowRes } from '@/interface/api/customerDetail';
import type { IActions } from '@/interface/api/customerDetail';
import ConfirmGkInfo from '@/pageComponents/customerDetail/Steps/ConfirmGkInfo';
import WelcomeIntro from '@/pageComponents/customerDetail/Steps/WelcomeIntro';
import PersonalInfoCollect from '@/pageComponents/customerDetail/Steps/PersonalInfoCollect';
import ClarifyMajorIntention from '@/pageComponents/customerDetail/Steps/ClarifyMajorIntention';
import CityPreference from '@/pageComponents/customerDetail/Steps/CityPreference';
import VolunteerStrategy from '@/pageComponents/customerDetail/Steps/VolunteerStrategy';
import styles from './style.module.scss';

const STEP_SHORT_TITLES = ['高考信息', '个人信息', '专业意向', '区域意向', '志愿方案'];

export interface CustomerDetailFlowProps {
  tenantId: string;
  botId: string;
  /** 创建成功后的回调（弹窗场景下可先关弹窗再跳转） */
  onSuccess?: (params: { chatSessionId: string; userId: string; userName: string }) => void;
  /** 可选：关闭入口（弹窗时传，用于关闭弹窗） */
  onClose?: () => void;
  /** 是否嵌入弹窗（仅影响样式：紧凑步骤条） */
  embedded?: boolean;
  /** 嵌入弹窗时由父组件在 header 展示步骤，子组件通过此回调同步当前步骤 */
  onStepChange?: (stepIndex: number, stepTitle: string) => void;
}

const CustomerDetailFlow: React.FC<CustomerDetailFlowProps> = ({
  tenantId,
  botId,
  onSuccess,
  onClose,
  embedded = false,
  onStepChange,
}) => {
  const storedUserInfo: any = getStorage('userInfo') || '{}';
  const userInfo = useMemo(() => JSON.parse(storedUserInfo), [storedUserInfo]);

  const [currentStep, setCurrentStep] = useState(-1);
  const [stepsData, setStepsData] = useState<any[]>([]);
  const [userSubjectList, setUserSubjectList] = useState<any[]>([]);
  const [createSessionValues, setCreateSessionValues] = useState<any>({});
  const [createLoading, setCreateLoading] = useState(false);
  const [finalSubmitLoading, setFinalSubmitLoading] = useState(false);
  const mainRef = useRef<HTMLDivElement>(null);

  const currentData = useMemo(() => {
    return stepsData?.find((item: ICollectflowRes) => item.order === currentStep + 2);
  }, [currentStep, stepsData]);

  const getCollectFlow = async () => {
    const res = await getCollectFlowApi({ tenantId });
    const { code, data } = res;
    if (code === 0 && data) {
      setStepsData(data.majorSteps || []);
    } else {
      message.error(res.msg);
    }
  };

  useEffect(() => {
    const draft = loadCustomerDetailDraft(tenantId, botId, userInfo);
    if (!draft) {
      setCurrentStep(-1);
      setCreateSessionValues({});
      return;
    }
    setCurrentStep(draft.currentStep);
    setCreateSessionValues(draft.values || {});
  }, [tenantId, botId, userInfo]);

  useEffect(() => {
    getCollectFlow();
  }, [tenantId]);

  useEffect(() => {
    const provinceCode = userInfo?.userScoreOb?.province?.code;
    if (!provinceCode) {
      setUserSubjectList([]);
      return;
    }
    const fetchList = async () => {
      const { code, data } = await getSubjectPolicy(provinceCode);
      if (code === 0 && data) {
        setUserSubjectList(data.subjectTypeList || []);
      }
    };
    fetchList();
  }, [userInfo?.userScoreOb?.province?.code]);

  const handleNextStep = async (btnProps: IActions, formValues: any) => {
    const values = { ...createSessionValues, ...formValues };
    setCreateSessionValues(values);
    if (currentStep === -1) {
      const nextStep = 0;
      setCurrentStep(nextStep);
      saveCustomerDetailDraft({ tenantId, botId, userInfo, currentStep: nextStep, values });
    } else if (btnProps.actionType === 'next') {
      const nextStep = currentStep + 1;
      setCurrentStep(nextStep);
      saveCustomerDetailDraft({ tenantId, botId, userInfo, currentStep: nextStep, values });
    } else if (btnProps.actionType === 'finalSubmit') {
      saveCustomerDetailDraft({ tenantId, botId, userInfo, currentStep, values });
      try {
        setCreateLoading(true);
        setFinalSubmitLoading(true);
        const submitValues = await hydrateCreateSessionBatch(values, userInfo);
        if (!submitValues?.batch?.code) {
          message.error('请选择批次后再创建会话');
          return;
        }
        if (submitValues !== values) {
          setCreateSessionValues(submitValues);
          saveCustomerDetailDraft({ tenantId, botId, userInfo, currentStep, values: submitValues });
        }
        const { code, data: sessionData, msg } = await createSession(tenantId, {
          botId,
          ...submitValues,
        });
        if (code === 0) {
          const createdSession = await resolveCreatedSession(tenantId, botId, sessionData);
          if (!createdSession) {
            message.error('创建成功，但未拿到会话信息，请返回会话列表重试');
            return;
          }
          message.success('创建会话成功');
          clearCustomerDetailDraft(tenantId, botId, userInfo);
          if (onSuccess) {
            onSuccess({
              chatSessionId: String(createdSession.id),
              userId: String(createdSession.userId || ''),
              userName: String(createdSession.userName || ''),
            });
          } else {
            navigateTo('/sessionDetailV2', {
              chatSessionId: createdSession.id,
              userId: createdSession.userId,
              userName: createdSession.userName,
              page: 1,
              pageSize: 10,
            });
          }
        } else {
          message.error(msg || '创建会话失败，请稍后重试');
        }
      } catch (error) {
        message.error('请求失败，请稍后重试');
      } finally {
        setCreateLoading(false);
        setFinalSubmitLoading(false);
      }
    }
  };

  const handleDraftChange = (formValues: any = {}) => {
    const values = { ...createSessionValues, ...formValues };
    setCreateSessionValues(values);
    saveCustomerDetailDraft({
      tenantId,
      botId,
      userInfo,
      currentStep,
      values,
    });
  };

  const handleBackStep = () => {
    const nextStep = Math.max(currentStep - 1, -1);
    setCurrentStep(nextStep);
    saveCustomerDetailDraft({
      tenantId,
      botId,
      userInfo,
      currentStep: nextStep,
      values: createSessionValues,
    });
  };

  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [currentStep]);

  const stepIndex = currentStep === -1 ? 0 : currentStep;
  const stepTitle = STEP_SHORT_TITLES[stepIndex];

  useEffect(() => {
    onStepChange?.(stepIndex, stepTitle);
  }, [stepIndex, stepTitle, onStepChange]);

  const showStepInBody = !embedded || !onStepChange;

  return (
    <div className={embedded ? styles.embeddedWrap : styles.wrap}>
      {showStepInBody && (
        <div className={styles.stepIndicator}>
          <div className={styles.stepIndicatorInner}>
            <span className={styles.stepLabel}>步骤 {stepIndex + 1}/5</span>
            <span className={styles.stepTitle}>{stepTitle}</span>
          </div>
        </div>
      )}
      <div className={styles.main} ref={mainRef}>
        {currentStep === -1 && (
          <WelcomeIntro stepsData={currentData} onNextStep={handleNextStep} />
        )}
        {currentStep === 0 && (
          <ConfirmGkInfo
            stepsData={currentData}
            savedValues={createSessionValues}
            onNextStep={handleNextStep}
            onDraftChange={handleDraftChange}
            onBackStep={handleBackStep}
          />
        )}
        {currentStep === 1 && (
          <PersonalInfoCollect
            userSubjectList={userSubjectList}
            stepsData={currentData}
            savedValues={createSessionValues}
            onNextStep={handleNextStep}
            onDraftChange={handleDraftChange}
            onBackStep={handleBackStep}
          />
        )}
        {currentStep === 2 && (
          <ClarifyMajorIntention
            stepsData={currentData}
            paramsValues={createSessionValues}
            savedValues={createSessionValues}
            onNextStep={handleNextStep}
            onDraftChange={handleDraftChange}
            onBackStep={handleBackStep}
          />
        )}
        {currentStep === 3 && (
          <CityPreference
            stepsData={currentData}
            savedValues={createSessionValues}
            onNextStep={handleNextStep}
            onDraftChange={handleDraftChange}
            onBackStep={handleBackStep}
          />
        )}
        {currentStep === 4 && (
          <VolunteerStrategy
            stepsData={currentData}
            savedValues={createSessionValues}
            onNextStep={handleNextStep}
            onDraftChange={handleDraftChange}
            onBackStep={handleBackStep}
            loading={createLoading}
            finalSubmitLoading={finalSubmitLoading}
            setFinalSubmitLoading={setFinalSubmitLoading}
          />
        )}
      </div>
    </div>
  );
};

export default CustomerDetailFlow;
