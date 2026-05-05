import React, { useEffect, useState } from 'react';
import { Drawer, List, Tag, Spin, Empty, Button, message, Modal } from 'antd';
import { RightOutlined, PlusOutlined } from '@ant-design/icons';
import { getSessionList, getLimitSettingsApi } from '@/service/apis/sessionDetail';
import { checkUserRightsApi } from '@/service/apis/user';
import useAuthParams from '@/hooks/useAuthParams';
import { navigateTo } from '@/utils/router';
import { setStorage } from '@/utils/tool';
import { ESessionStatus } from '@/interface/api/assistant';
import type { ISessionListResItem } from '@/interface/api/assistant';
import style from './style.module.scss';

interface SessionListDrawerProps {
  visible: boolean;
  onClose: () => void;
  onSelectSession?: (record: ISessionListResItem) => void;
  /** 移动端：点击创建智能方案且权益通过时调用，用于打开流程弹窗而非跳转 */
  onOpenCreatePlan?: () => void;
}

const statusMap: Record<string, { label: string; color: string }> = {
  [ESessionStatus.WAIT]: { label: '初始化', color: 'blue' },
  [ESessionStatus.GOING]: { label: '服务中', color: 'green' },
  [ESessionStatus.FINISHED]: { label: '已提交', color: 'red' },
  [ESessionStatus.CLOSE]: { label: '已关闭', color: 'default' },
};

const formatTime = (record: string | number | null) => {
  if (!record) return '-';
  const t = typeof record === 'number' ? record : parseInt(String(record), 10);
  if (isNaN(t)) return String(record);
  return new Date(t).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
};

const SessionListDrawer: React.FC<SessionListDrawerProps> = ({
  visible,
  onClose,
  onSelectSession,
  onOpenCreatePlan,
}) => {
  const { botId, tenantId } = useAuthParams();
  const [records, setRecords] = useState<ISessionListResItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [limitSettings, setLimitSettings] = useState<{
    createSession?: { useCount?: number; settingCount?: number };
  }>({});
  const [isCheckingRights, setIsCheckingRights] = useState(false);

  const fetchLimitSettings = async () => {
    try {
      const res = await getLimitSettingsApi();
      if (res.code === 0 && res.data) {
        setLimitSettings(res.data);
      }
    } catch (e) {
      console.error('获取限制设置失败', e);
    }
  };

  const fetchList = async () => {
    if (!tenantId || !botId) return;
    setLoading(true);
    try {
      const { code, data } = await getSessionList(tenantId, {
        botId,
        statusList: [],
        orderBy: [{ isAsc: false, orderBy: 'id' }],
        searchWord: '',
        page: 1,
        pageSize: 20,
      });
      if (code === 0 && data?.records) {
        setRecords(data.records);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible && tenantId && botId) {
      fetchList();
    }
  }, [visible, tenantId, botId]);

  useEffect(() => {
    if (visible) {
      fetchLimitSettings();
    }
  }, [visible]);

  const handleSelect = (record: ISessionListResItem) => {
    setStorage([{ key: 'infoSummary', value: record.infoSummary }]);
    navigateTo('/sessionDetailV2', {
      chatSessionId: record.id,
      userId: String(record.userId),
      userName: String(record.userName || ''),
      page: 1,
      pageSize: 10,
    });
    onSelectSession?.(record);
    onClose();
  };

  const handleCreatePlan = async () => {
    if (isCheckingRights) return;
    setIsCheckingRights(true);
    try {
      const { code, data, msg } = await checkUserRightsApi({
        checkPoint: 'CreateSession',
      });
      if (code === 0 && data?.canOperate) {
        onClose();
        if (onOpenCreatePlan) {
          onOpenCreatePlan();
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
  };

  const useCount = limitSettings?.createSession?.useCount ?? '-';
  const settingCount = limitSettings?.createSession?.settingCount ?? '-';

  return (
    <Drawer
      title="会话列表"
      placement="right"
      width="100%"
      className={style.sessionListDrawer}
      open={visible}
      onClose={onClose}
      extra={
        <Button
          type="primary"
          size="small"
          className={style.createPlanBtn}
          icon={<PlusOutlined />}
          loading={isCheckingRights}
          onClick={handleCreatePlan}
        >
          创建智能方案
          <span className={style.limitTip}>
            （{useCount}/{settingCount}）
          </span>
        </Button>
      }
    >
      <Spin spinning={loading}>
        {records.length === 0 && !loading ? (
          <Empty description="暂无会话" style={{ marginTop: 60 }} />
        ) : (
          <div className={style.listWrapper}>
            <List
              split={false}
              dataSource={records}
            renderItem={(item) => {
              const status = statusMap[item.sessionStatus] || {
                label: item.sessionStatus,
                color: 'default',
              };
              return (
                <List.Item
                  className={style.sessionCard}
                  onClick={() => handleSelect(item)}
                >
                  <div className={style.cardContent}>
                    <div className={style.cardMain}>
                      <div className={style.cardTop}>
                        <div className={style.cardTopLeft}>
                          <Tag color={status.color} className={style.statusTag}>
                            {status.label}
                          </Tag>
                          {item.prepareType?.desc && (
                            <span className={style.prepareType}>
                              {item.prepareType.desc}
                            </span>
                          )}
                        </div>
                        <span className={style.createTime}>
                          {formatTime(item.createTime)}
                        </span>
                      </div>
                      <div className={style.infoSummary}>
                        {item.infoSummary || '暂无基本信息'}
                      </div>
                    </div>
                    <div className={style.enterIcon}>
                      <RightOutlined />
                    </div>
                  </div>
                </List.Item>
              );
            }}
            />
          </div>
        )}
      </Spin>
    </Drawer>
  );
};

export default SessionListDrawer;
