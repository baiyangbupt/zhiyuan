import React from 'react';
import { DropboxOutlined, LogoutOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { navigateTo } from '@/utils/router';
import { clearStorage, EStorageKey } from '@/utils/tool';
import style from './style.module.scss';

const Header = () => {
  const handleLogout = () => {
    // 清除所有认证相关的存储
    clearStorage([
      EStorageKey.TOKEN,
      EStorageKey.BOT_ID,
      EStorageKey.TENANT_ID,
      EStorageKey.HASADDINFO,
      EStorageKey.ISCUSTOMER,
      EStorageKey.CHANNEL,
    ]);
    // 跳转到登录页
    navigateTo('/login');
  };

  const handleHelp = () => {
    // 在新窗口中打开帮助文档
    window.open('https://yuzhiweilai.feishu.cn/wiki/JO3ZwMchziZsDpkQhuHcr9VMn1k', '_blank');
  };

  return (
    <header className={style.header}>
      <div className={style.logoContainer}>
        <DropboxOutlined className={style.logoIcon} />
        <h1>高考规划AI助手</h1>
      </div>
      <nav className={style.navContainer}>
        <Button
          onClick={handleHelp}
          type="text"
          className={style.navBtn}
          icon={<QuestionCircleOutlined />}
        >
          帮助
        </Button>
        <Button
          onClick={handleLogout}
          type="text"
          className={style.navBtn}
          icon={<LogoutOutlined />}
        >
          退出登录
        </Button>
      </nav>
    </header>
  );
};

export default Header;
