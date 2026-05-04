import {Spin} from 'antd';
import {useRouter} from 'next/router';
import {useEffect, useState} from 'react';
import styles from './style.module.scss';

const Loading = () => {
    const router = useRouter();

    const [loading, setLoading] = useState<boolean>(false);

    useEffect(() => {
        const handleRouteChange = () => {
            setLoading(true);
        };
        const handleRouteChangeComplete = () => {
            setLoading(false);
            const nextEle = document.getElementById('__next');
            const scrollToTop = () => {
                const isTop = nextEle?.scrollTop;
                if (isTop && nextEle) {
                    nextEle.scrollTo(0, 0);
                }
            };

            if (nextEle) {
                window.requestAnimationFrame(scrollToTop);
            }
        };

        router.events.on('routeChangeStart', handleRouteChange);
        router.events.on('routeChangeComplete', handleRouteChangeComplete);

        return () => {
            router.events.off('routeChangeStart', handleRouteChange);
            router.events.off('routeChangeComplete', handleRouteChangeComplete);
        };
    }, []);

    return (
        <>
            {loading && (
                <div className={styles.loading}>
                    <Spin />
                </div>
            )}
        </>
    );
};

export default Loading;
