import { useState, useEffect } from 'react';
import { getStorage, EStorageKey } from '@/utils/tool';
import { getValueFromUrlBykey } from '@/utils/tool';

/**
 * 判断当前是否为小程序端（source=minip）
 * 用于控制 Header 隐藏、弹窗替代路由等
 */
export const useIsMinip = (): boolean => {
  const [isMinip, setIsMinip] = useState(false);

  useEffect(() => {
    const fromUrl = getValueFromUrlBykey('source') === 'minip';
    const fromStorage = getStorage(EStorageKey.SOURCE) === 'minip';
    setIsMinip(fromUrl || fromStorage);
  }, []);

  return isMinip;
};
