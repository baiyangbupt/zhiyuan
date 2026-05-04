import {Button, Drawer} from 'antd';
import styles from './index.module.scss';

interface IDrawerProps {
    title?: string; // 抽屉标题
    isOpen?: boolean; // 是否打开
    children?: React.ReactNode; // 抽屉内容
    footer?: React.ReactNode; // 抽屉底部
    leftButton?:string;
    rightButton?:string;
    onVerify?:() => void; // 确定回调
    onClose?: () => void; // 关闭回调
    isLoading?: boolean; // 是否加载
}

const DrawerModule: React.FC<IDrawerProps> = ({
    title, isOpen, children, footer,
    onVerify, onClose,
    leftButton = '取消', rightButton = '确定', isLoading = false
}) => (
    <Drawer
        className={styles.drawer}
        destroyOnClose
        closeIcon={null}
        title={title}
        extra={(
            <button
                onClick={onClose}
                type="button" aria-label="Close" className="ant-drawer-close"
            >
                <span role="img" aria-label="close" className="anticon anticon-close">
                    <svg fillRule="evenodd" viewBox="64 64 896 896" focusable="false" data-icon="close" width="1em" height="1em" fill="currentColor" aria-hidden="true">
                        <path d="M799.86 166.31c.02 0 .04.02.08.06l57.69 57.7c.04.03.05.05.06.08a.12.12 0 010 .06c0 .03-.02.05-.06.09L569.93 512l287.7 287.7c.04.04.05.06.06.09a.12.12 0 010 .07c0 .02-.02.04-.06.08l-57.7 57.69c-.03.04-.05.05-.07.06a.12.12 0 01-.07 0c-.03 0-.05-.02-.09-.06L512 569.93l-287.7 287.7c-.04.04-.06.05-.09.06a.12.12 0 01-.07 0c-.02 0-.04-.02-.08-.06l-57.69-57.7c-.04-.03-.05-.05-.06-.07a.12.12 0 010-.07c0-.03.02-.05.06-.09L454.07 512l-287.7-287.7c-.04-.04-.05-.06-.06-.09a.12.12 0 010-.07c0-.02.02-.04.06-.08l57.7-57.69c.03-.04.05-.05.07-.06a.12.12 0 01.07 0c.03 0 .05.02.09.06L512 454.07l287.7-287.7c.04-.04.06-.05.09-.06a.12.12 0 01.07 0z"></path>
                    </svg>
                </span>
            </button>
        )}
        onClose={onClose}
        open={isOpen}
        width={675}
        placement="right"
        footer={(
            <div className={styles.footer}>
                <Button className={styles.cancel} onClick={onClose}>
                    {leftButton}
                </Button>
                <Button type="primary" onClick={onVerify} loading={isLoading}>
                    {rightButton}
                </Button>
            </div>
        )}
    >
        {children}
        {footer}
    </Drawer>
);


export default DrawerModule;
