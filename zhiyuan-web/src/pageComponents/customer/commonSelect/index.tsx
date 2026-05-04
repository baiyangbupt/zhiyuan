import {useMemo} from 'react';
import classnames from 'classnames';
import {ISelectTypeEnum, ISelectDataItem} from '@/interface/api/updateBaseInfo';
import styles from './index.module.scss';

interface ICommonSelectProps{
    bigItem?:boolean; // true代表展示大的item
    formDisabled?:boolean; // 是否禁用
    selectType:ISelectTypeEnum; // 单选 or 多选
    limitNum?:number; // 多选可选的个数
    type?:string;
    data: ISelectDataItem[];
    selectedDataIndex:string[];
    onChooseItem:(item:ISelectDataItem)=>void;
}

const CommonSelect = (props:ICommonSelectProps) => {
    const {selectType, limitNum, data, selectedDataIndex, bigItem, formDisabled, type, onChooseItem} = props;
    const disabled:boolean = useMemo(
        () => selectType === ISelectTypeEnum.Mutiple && selectedDataIndex.length === limitNum,
        [selectType, selectedDataIndex, limitNum]
    );

    // 切换选中状态
    const toogleSelectStatus = (item:ISelectDataItem) => {
        if (formDisabled) {
            return;
        }
        const index = selectedDataIndex.findIndex(ele => ele === item.value);
        // 达到最大数量限制，不能继续选择
        if (index === -1 && disabled) {
            return;
        }
        onChooseItem(item);
    };

    return (
        <div className={styles.wrapper}>
            {data.map((item:ISelectDataItem) => (
                <div
                    key={item.value}
                    onClick={() => {
                        toogleSelectStatus(item);
                    }}
                    className={classnames({
                        [styles.active]: selectedDataIndex.indexOf(item.value) !== -1,
                        [styles.item]: true,
                        [styles.smallItem]: !bigItem && !type,
                        [styles.smallTypeItem]: !bigItem && type,
                        [styles.bigItem]: bigItem,
                        [styles.disabled]: disabled
                    })}
                >
                    {item.name}
                </div>
            ))}
        </div>
    );
};
export default CommonSelect;
