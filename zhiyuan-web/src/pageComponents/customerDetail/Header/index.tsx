import React, { useEffect, useState } from 'react';
import {
  DropboxOutlined,
  LogoutOutlined,
  MessageOutlined,
  QuestionCircleOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Avatar, Button, Divider, Dropdown, Modal, Popconfirm, Space, Typography } from 'antd';
import { navigateTo } from '@/utils/router';
import { clearStorage, EStorageKey, getStorage, getValueFromUrlBykey } from '@/utils/tool';
import { useIsMinip } from '@/hooks/useIsMinip';
import style from './style.module.scss';
import LogoImg from '@/images/icons/logo2.png';
import type { MenuProps } from 'antd';
const { Text, Title } = Typography;
const navList = [
  { label: '会话列表', value: 'session' },
  { label: '帮助文档', value: 'help' },
  // { label: '关于我们', value: 'about' },
];

interface IUserInfo {
  userName: string;
  avatarUrl: string;
}

interface IHeaderProps {
  userInfo: IUserInfo;
}

const Header: React.FC<IHeaderProps> = ({ userInfo }) => {
  const isMinip = useIsMinip();
  const [activeItem, setActiveItem] = useState<string>('session');
  const [openTips, setOpenTips] = useState<boolean>(false);
  const page = getValueFromUrlBykey('page');
  const pageSize = getValueFromUrlBykey('pageSize');


  const [displayUserInfo, setDisplayUserInfo] = useState({
    userName: '用户名称',
    avatarUrl: '',
  });
  const [storedIsCustomer, setStoredIsCustomer] = useState<boolean>(false);
  const [storedChannel, setStoredChannel] = useState<string>('');

  useEffect(() => {
    setStoredChannel((getStorage(EStorageKey.CHANNEL) as string) || '');
    setStoredIsCustomer((getStorage(EStorageKey.ISCUSTOMER) as boolean) || false);
  }, []);

  useEffect(() => {
    if (userInfo) {
      setDisplayUserInfo(userInfo);
    }
  }, [userInfo]);

  // logo跳转
  const handleClickTarget = () => {
    if (isMinip) {
      navigateTo('/customer', { source: 'minip', openSessionList: 1 });
      return;
    }

    if (storedIsCustomer && storedChannel === 'gaotu') {
      window.location.href = 'https://www.gaotuzhiyuan.com';
      return;
    }

    navigateTo('/session');
  };

  const handleLogout = () => {
    // 清除所有认证相关的存储
    clearStorage([
      EStorageKey.TOKEN,
      EStorageKey.BOT_ID,
      EStorageKey.TENANT_ID,
      EStorageKey.HASADDINFO,
      EStorageKey.ISCUSTOMER,
      EStorageKey.CHANNEL,
      'userInfo',
      'infoSummary',
    ]);
    // 跳转到登录页
    navigateTo('/login');
  };

  const handleHelp = () => {
    // 在新窗口中打开帮助文档
    window.open('https://yuzhiweilai.feishu.cn/wiki/JO3ZwMchziZsDpkQhuHcr9VMn1k', '_blank');
  };
  const handleClickNav = (item: any) => {
    switch (item.value) {
      case 'session':
        break;
      case 'help':
        handleHelp();
        break;
      case 'about':
        break;
    }
  };

  const jumpListPage = () => {
    navigateTo('/session', {
      page: page || 1,
      pageSize: pageSize || 20,
    });
  };

  const items: MenuProps['items'] = [
    {
      key: '1',
      label: (
        <a target="_blank" rel="noopener noreferrer" href="#" style={{ fontSize: '16px' }}>
          个人中心
        </a>
      ),
      disabled: true,
    },
    {
      key: '2',
      label: (
        <a onClick={() => setOpenTips(true)} style={{ fontSize: '16px' }}>
          退出登录
        </a>
      ),
    },
  ];

  if (isMinip) return null;

  return (
    <header className={style.header}>
      <div className={style.headerWrapper}>
        <div className={style.leftNav}>
          <div className={style.logoContainer} onClick={handleClickTarget}>
            <img src={LogoImg.src} alt="高途logo" className={style.illustrationImage} />
            <Divider type="vertical" className={style.divider} />
            <Text type="secondary" className={style.text}>
              基于您的高考成绩和志愿偏好，为您提供科学的志愿填报建议和方案
            </Text>
          </div>
        </div>
        {/* {storedIsCustomer && storedChannel === 'gaotu' ? null : (
          <div className={style.userInfo}>
            <Dropdown menu={{ items }}>
              <a onClick={e => e.preventDefault()}>
                {userInfo && (
                  <Space>
                    {displayUserInfo.avatarUrl ? (
                      <Avatar src={displayUserInfo.avatarUrl} />
                    ) : (
                      <Avatar icon={<UserOutlined />} />
                    )}
                    <div className={style.userName}>{displayUserInfo.userName}</div>
                  </Space>
                )}
              </a>
            </Dropdown>
          </div>
        )} */}
        <nav className={style.nav}>
          <Button
            onClick={jumpListPage}
            type="text"
            className={style.navBtn}
            icon={<MessageOutlined />}
          >
            会话列表
          </Button>
        </nav>
      </div>
      <Modal
        width={320}
        title="提示"
        open={openTips}
        onOk={handleLogout}
        onCancel={() => setOpenTips(false)}
        okText="确认"
        cancelText="取消"
      >
        确定退出登录？
      </Modal>
    </header>
  );
};

export default Header;
