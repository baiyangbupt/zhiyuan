import {ReactNode} from 'react';
import useApp from '@/store/message';

interface IProps {
    children: ReactNode;

}

const AppComponent = (props: IProps) => {
    useApp();
    return (
        <>
            {props.children}
        </>
    );
};

export default AppComponent;
