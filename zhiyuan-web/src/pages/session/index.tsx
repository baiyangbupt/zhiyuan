import React, { useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { message, Button, ConfigProvider, Tag, Tooltip, Modal, Input } from 'antd';
import {
  ESessionStatus,
  ICreateSessionParams,
  ISubject,
  ISubjectScoreList,
} from '@/interface/api/assistant';
import {
  createSession,
  saveVolunteerInfo,
  getSessionList,
  callMajorRecommendation,
  bindTencentMeeting,
  getLimitSettingsApi,
} from '@/service/apis/sessionDetail';
import { checkUserRightsApi } from '@/service/apis/user';
import ModalForm from '@/pageComponents/session/ModalForm';
import DrawerModule from '@/pageComponents/session/DrawerModule';
import Extable from '@/pageComponents/session/exTable';
import { IRefParams } from '@/pageComponents/session/subjectScores';
import ExSearch from '@/pageComponents/session/exSearch';
import Header from '@/pageComponents/session/Header';
import useList from '../../hooks/useSessionList';
import useAuthParams from '../../hooks/useAuthParams';
import styles from './style.module.scss';
import { navigateTo } from '@/utils/router';
import { resolveCreatedSession } from '@/utils/session';
import { EStorageKey, getStorage, setStorage } from '@/utils/tool';
import { useIsMinip } from '@/hooks/useIsMinip';
import { PlusOutlined } from '@ant-design/icons';

const formatTime = (record: number | null) =>
  record ? (
    <Tooltip
      title={new Date(record).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })}
    >
      {new Date(record).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })}
    </Tooltip>
  ) : (
    '-'
  );

const configTable = [
  {
    prop: 'id',
    label: 'ID',
    width: 88,
    render: (record: any) => (
      <Tooltip title={record}>
        <span className={styles.sessionIdCell}>{record}</span>
      </Tooltip>
    ),
  },
  {
    prop: 'sessionStatus',
    label: '状态',
    width: 100,
    render(record: string) {
      switch (record) {
        case ESessionStatus.WAIT:
          return <Tag color="blue">初始化</Tag>;
        case ESessionStatus.GOING:
          return <Tag color="green">服务中</Tag>;
        case ESessionStatus.FINISHED:
          return <Tag color="red">已提交</Tag>;
        default:
          return record;
      }
    },
  },
  {
    label: '基本信息',
    tips: '基本信息：（分数/姓名/批次/省份/选科/位次）',
    prop: 'infoSummary',
    width: 260,
    render: (record: string) => (
      <Tooltip title={record}>
        <span style={{ cursor: 'pointer' }}>{record}</span>
      </Tooltip>
    ),
  },
  {
    label: '填报类型',
    prop: 'prepareType',
    width: 120,
    render: (record: any) => {
      if (record?.desc) {
        return <Tag color="blue">{record.desc}</Tag>;
      }
      return '-';
    },
  },
  {
    label: '创建时间',
    prop: 'createTime',
    width: 160,
    render: (record: any) => formatTime(record),
  },
  {
    label: '开始时间',
    prop: 'startTime',
    width: 160,
    render: (record: any) => formatTime(record),
  },
  {
    label: '结束时间',
    prop: 'endTime',
    width: 160,
    render: (record: any) => formatTime(record),
  },
];

const Session: React.FC = () => {
  const router = useRouter();
  const isMinip = useIsMinip();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const modalFormRef = useRef<IRefParams>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [limitSettings, setLimitSettings] = useState<any>({});
  const [isCheckingRights, setIsCheckingRights] = useState(false);

  const { botId, tenantId } = useAuthParams();

  // 小程序端进入 /session 时重定向至介绍页并打开会话列表
  useEffect(() => {
    if (isMinip && botId && tenantId) {
      router.replace('/customer?source=minip&openSessionList=1');
    }
  }, [isMinip, botId, tenantId, router]);

  // isCustomer true-C端 false-B端
  const storedIsCustomer = getStorage(EStorageKey.ISCUSTOMER) as boolean;

  const storedUserInfo: any = getStorage('userInfo') || '{}';
  const userInfo = JSON.parse(storedUserInfo);

  useEffect(() => {
    getLimitSettings();
  }, []);

  // 获取限制设置
  const getLimitSettings = async () => {
    try {
      const res = await getLimitSettingsApi();
      if (res.code === 0) {
        setLimitSettings(res.data);
      }
    } catch (error) {
      console.error('获取限制设置失败', error);
    }
  };

  // 简洁的useList调用
  const {
    combinedData,
    pagination,
    handlePageChange,
    handleSizeChange,
    searchLoading,
    search,
    refresh,
    reset,
    searchOptions,
    configSearch,
  } = useList({
    listApi: getSessionList,
    tenantId,
    otherParams: {
      botId,
      orderBy: [
        {
          isAsc: false,
          orderBy: 'id',
        },
      ],
    },
    tableConfig: ['records', 'total'],
    pageConfig: ['page', 'pageSize'],
    beforeRefreshData(dataParams: any) {
      return {
        ...dataParams, // 保留原始参数（ botId、orderBy）
        statusList: dataParams.sessionStatus ? [dataParams.sessionStatus] : dataParams.statusList,
        searchWord: dataParams.infoSummary || dataParams.searchWord,
        sessionStatus: undefined,
        infoSummary: undefined,
      };
    },
  });

  const onVerify = () => {
    const { prepareType, subjectType, memberSubjectList, subjectScoreList } =
      modalFormRef.current?.getSaveParamsData() || {};
    const normalizedSubjectScoreList = (subjectScoreList || []) as ISubjectScoreList[];
    const dealParamsData = modalFormRef.current?.getDealParamsData() || {};

    modalFormRef.current?.form
      .validateFields()
      .then(async (res: any) => {
        console.log('res', res);
        const {
          height,
          examYear,
          specialPlan,
          // minority,
          // colorBlindness,
          colorSistuation,
          bonusPolicy,
          bonusScore,
          totalScore,
          userName,
          // targetType,
          visionAbility,
          strengthSubjectList,
          totalScorePos,
          preferredMajors,
          acceptForeignSchool,
          preferredRegions,
          tuitionRange: tuitionRangeValue,
        } = res;
        const params = {
          // ...res,
          height,
          examYear,
          specialPlan,
          // minority,
          // colorBlindness,
          colorSistuation,
          bonusPolicy,
          bonusScore,
          totalScore,
          userName,
          // targetType,
          ...dealParamsData,
          prepareType,
          subjectScoreList: normalizedSubjectScoreList,
          visionAbility,
          totalScorePos,
          preferredMajors,
          acceptForeignSchool,
          preferredRegions,
          tuitionRange: tuitionRangeValue
            ? {
                min: tuitionRangeValue[0],
                max: tuitionRangeValue[1],
              }
            : undefined,
        } as unknown as ICreateSessionParams;
        console.log('params', params);
        setIsLoading(true);
        try {
          const { code, data, msg } = await createSession(tenantId, params);
          if (code === 0) {
            const createdSession = await resolveCreatedSession(tenantId, botId, data);
            if (!createdSession) {
              message.error('创建成功，但未拿到会话信息，请刷新列表后重试');
              setIsLoading(false);
              return;
            }
            message.success('创建会话成功');
            setIsModalOpen(false);

            // refresh();
            navigateTo('/sessionDetailV2', {
              chatSessionId: createdSession.id,
              userId: createdSession.userId,
              userName: createdSession.userName,
              page: 1,
              pageSize: 10,
            });
            setStorage([
              {
                key: 'infoSummary',
                value: createdSession.infoSummary,
              },
            ]);
          } else {
            message.error(msg || '创建会话失败');
            setIsLoading(false);
          }
        } catch (error) {
          message.error('请求失败，请稍后重试');
          setIsLoading(false);
        }
      })
      .catch(() => {
        setIsLoading(false);
      });
  };

  const onEnter = (record: any) => {
    const { page, pageSize } = pagination;
    navigateTo('/sessionDetailV2', {
      chatSessionId: record.id,
      page,
      pageSize,
    });
    setStorage([
      {
        key: 'infoSummary',
        value: record.infoSummary,
      },
    ]);
  };

  // 小程序端重定向，避免闪屏
  if (isMinip) {
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
          <title>高途AI志愿填报-会话管理</title>
        </Head>
        <div className={styles.sessionWrapper} style={{ alignItems: 'center', justifyContent: 'center' }}>
          跳转中...
        </div>
      </ConfigProvider>
    );
  }

  // 只有当参数准备好时才渲染内容
  if (!botId || !tenantId) {
    return null;
  }

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
        <title>高途AI志愿填报-会话管理</title>
      </Head>
      <div className={styles.sessionWrapper}>
        <Header userInfo={userInfo} currentItem={'session'} />
        <div className={styles.contentContainer}>
          <ExSearch
            searchOptions={searchOptions}
            configSearch={configSearch}
            isLoading={searchLoading}
            search={search}
            reset={reset}
          />
          <Extable
            configTable={[
              ...configTable,
              {
                label: '操作',
                prop: 'action',
                fixed: 'right' as boolean | 'left' | 'right',
                render: (_: any, record: any) => (
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <a style={{ color: '#ff443d' }} onClick={() => onEnter(record)}>
                      进入
                    </a>
                  </div>
                ),
                width: 100,
              },
            ]}
            combinedData={combinedData}
            isLoading={searchLoading}
            pagination={pagination}
            pageChange={handlePageChange}
            sizeChange={handleSizeChange}
            rightRender={() => (
          <Button
                className={styles.button}
                type="primary"
                icon={<PlusOutlined />}
            loading={isCheckingRights}
            onClick={async () => {
              setIsCheckingRights(true);
              try {
                const { code, data, msg } = await checkUserRightsApi({
                  checkPoint: 'CreateSession',
                  prepareType: 'VOLUNTEER',
                });

                if (code === 0 && data?.canOperate) {
                  if (storedIsCustomer) {
                    navigateTo('/customerDetail');
                  } else {
                    setIsLoading(false);
                    setIsModalOpen(true);
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
                创建智能方案
                <span>
                  {limitSettings?.createSession?.useCount}
                  <i style={{ margin: '0 4px' }}>/</i>
                  {limitSettings?.createSession?.settingCount}
                </span>
              </Button>
            )}
          />
        </div>
        <DrawerModule
          title="请完善学生的高考信息"
          isOpen={isModalOpen}
          onClose={() => {
            setIsLoading(false);
            setIsModalOpen(false);
          }}
          onVerify={onVerify}
          isLoading={isLoading}
        >
          <ModalForm ref={modalFormRef} />
        </DrawerModule>
      </div>
    </ConfigProvider>
  );
};

export default Session;
