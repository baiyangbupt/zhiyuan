import {useEffect} from 'react';
import {ISelectConfig} from '@/interface/api/updateBaseInfo';
import CommonSelect from '../commonSelect';
import styles from './index.module.scss';

interface ISelectPopupProps {
    formDisabled: boolean;
    selectConfig:ISelectConfig[] | ISelectConfig;
    children?:JSX.Element;
    type?:string;
    onConfirm?:()=>void;
    blurEvent?:()=> void;
}

const SelectPopup = (props: ISelectPopupProps) => {
    const {selectConfig, formDisabled, type, onConfirm, blurEvent} = props;
    useEffect(() => {
        if (Array.isArray(selectConfig) && selectConfig[0]?.config?.data.length) {
            onConfirm?.();
        }
    }, [selectConfig]);
    return (
        <div
            className={styles.content}
            onBlur={blurEvent}
            // @ts-ignore
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
            tabIndex="0"
        >
            <div className={styles.main}>
                {Array.isArray(selectConfig)
                    ? selectConfig.map((item:ISelectConfig, index:number) => (
                    // eslint-disable-next-line react/no-array-index-key
                        <div key={index} className={styles.selectItem}>
                            {item.name && (
                                <p className={styles.name}>
                                    {item.name}
                                </p>
                            )}
                            <CommonSelect
                                {...item.config}
                                type={type}
                                formDisabled={formDisabled}
                            />
                        </div>
                    ))
                    : (
                        <div>
                            {selectConfig.name && (
                                <p className={styles.name}>
                                    {selectConfig.name}
                                </p>
                            )}
                            <CommonSelect
                                {...selectConfig.config}
                                type={type}
                                formDisabled={formDisabled}
                            />
                        </div>
                    )}

            </div>
        </div>
    );

};
export default SelectPopup;
