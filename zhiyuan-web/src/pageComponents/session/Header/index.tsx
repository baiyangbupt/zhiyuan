import React, { useEffect, useMemo, useState } from 'react';
import {
  DropboxOutlined,
  LogoutOutlined,
  QuestionCircleOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Avatar, Button, Dropdown, Modal, Popconfirm, Space } from 'antd';
import { navigateTo } from '@/utils/router';
import { clearStorage, EStorageKey, getStorage } from '@/utils/tool';
import { useIsMinip } from '@/hooks/useIsMinip';
import style from './style.module.scss';
import LogoImg from '@/images/icons/logo2.png';
import type { MenuProps } from 'antd';
import type { IUserInfo } from '@/interface/api/user';

const navList = [
  { label: 'ai志愿填报', value: 'customer' },
  { label: '会话列表', value: 'session' },
  { label: '帮助文档', value: 'help' },
  // { label: '关于我们', value: 'about' },
];

interface IHeaderProps {
  userInfo?: Pick<IUserInfo, 'userName' | 'avatarUrl'>;
  currentItem?: string;
}
const Header: React.FC<IHeaderProps> = ({ userInfo, currentItem }) => {
  const isMinip = useIsMinip();
  const [activeItem, setActiveItem] = useState<string>('');
  const [openTips, setOpenTips] = useState<boolean>(false);

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
      setDisplayUserInfo({
        userName: userInfo.userName || '用户名称',
        avatarUrl: userInfo.avatarUrl || '',
      });
    }
  }, [userInfo]);

  useEffect(() => {
    setActiveItem(currentItem || '');
  }, [currentItem]);

  const handleUserCenter = () => {
    navigateTo('/userCenter');
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
      'infoSummary',
      'userInfo',
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
      case 'customer':
        navigateTo('/customer');
        break;
      case 'session':
        navigateTo('/session');
        break;
      case 'help':
        handleHelp();
        break;
      case 'about':
        break;
    }
  };

  const items: MenuProps['items'] = useMemo(() => {
    const menuItems: MenuProps['items'] = [
      {
        key: '1',
        label: (
          <a onClick={handleUserCenter} style={{ fontSize: '16px' }}>
            个人中心
          </a>
        ),
      },
    ];
    
    // 当storedChannel是gaotu时，不显示退出登录
    if (storedChannel !== 'gaotu') {
      menuItems.push({
        key: '2',
        label: (
          <a onClick={() => setOpenTips(true)} style={{ fontSize: '16px' }}>
            退出登录
          </a>
        ),
      });
    }
    
    return menuItems;
  }, [storedChannel]);
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

  // 动态计算导航项
  const filteredNavList = useMemo(() => {
    if (storedIsCustomer && storedChannel === 'gaotu') {
      return navList;
    }
    return navList.filter(item => item.value !== 'customer');
  }, [storedIsCustomer, storedChannel]);

  if (isMinip) return null;

  return (
    <header className={style.header}>
      <div className={style.headerWrapper}>
        <div className={style.leftNav}>
          <div className={style.logoContainer} onClick={handleClickTarget}>
            <img src={LogoImg.src} alt="高途logo" className={style.illustrationImage} />
          </div>
          <nav className={style.navContainer}>
            {filteredNavList.map(item => (
              <div
                key={item.value}
                className={`${style.navItem} ${activeItem === item.value ? style.active : ''}`}
                onClick={() => handleClickNav(item)}
              >
                {item.label}
              </div>
            ))}
          </nav>
        </div>
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
                  <div className={style.userName}>{displayUserInfo.userName || '用户名称'}</div>
                </Space>
              )}
            </a>
          </Dropdown>
        </div>
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
