import { useState, useCallback, useMemo, useRef } from 'react';
import {
  ISubjectType,
  ISubjectItem,
  ISelectConfig,
  ISelectTypeEnum,
  ISelectDataItem,
  ISubjectList,
} from '@/interface/api/updateBaseInfo';

const useForm = (drawerForm: any) => {
  const form = drawerForm;
  const [subjectType, setSubjectType] = useState<ISubjectType>(); // 学科类型
  const [selectedArtsOrSciences, setSelectedArtsOrSciences] = useState<string[]>([]); // 文理分科
  const [firstNum, setFirstNum] = useState<number>(0); // 首选科目数量
  const [selectedFirstSubject, setSelectedFirstSubject] = useState<string[]>([]); // 首选科目
  const [selectedSecondSubject, setSelectedSecondSubject] = useState<string[]>([]); // 次选科目
  const [secondNum, setSecondNum] = useState<number>(0); // 次选科目数量
  const [artsOrSciencesList, setArtsOrSciencesList] = useState<any[]>([]); // 文理分科
  const [firstSubjectList, setFirstSubjectList] = useState<any[]>([]); // 首选科目
  const [secondSubjectList, setSecondSubjectList] = useState<any[]>([]); // 次选科目

  const policy = useRef<string>(ISubjectType.ArtsOrSciences); // 策略

  // 表单校验
  const rules = [
    {
      // eslint-disable-next-line complexity
      validator(_: any, value: string) {
        const areaId = form.form.getFieldValue('areaId');
        if (subjectType === ISubjectType.ArtsOrSciences && !selectedArtsOrSciences.length) {
          return Promise.reject(new Error('请选择科类'));
        }
        if (
          subjectType === ISubjectType.FirstAndSecond &&
          selectedFirstSubject.length !== firstNum
        ) {
          return Promise.reject(new Error(`请选择${firstNum}门首选科目`));
        }
        if (
          subjectType === ISubjectType.FirstAndSecond &&
          selectedSecondSubject.length !== secondNum
        ) {
          return Promise.reject(new Error(`请选择${secondNum}门次选科目`));
        }
        if (
          subjectType === ISubjectType.ThreeOutOfSix &&
          selectedSecondSubject.length !== secondNum
        ) {
          return Promise.reject(new Error(`请选择${secondNum}门科目`));
        }
        if (!value) {
          return Promise.reject(new Error('请输入'));
        }
        if (
          areaId === '310000' && // 上海
          (+value < 100 || +value > 660)
        ) {
          return Promise.reject(new Error('上海高考成绩范围为100～660分'));
        }
        if (
          areaId === '460000' && // 海南
          (+value < 100 || +value > 900)
        ) {
          return Promise.reject(new Error('海南高考成绩范围为100～900分'));
        } // 其他省份
        if (areaId !== '310000' && areaId !== '460000' && (+value < 100 || +value > 750)) {
          return Promise.reject(new Error('高考成绩范围为100～750分'));
        }
        return Promise.resolve();
      },
    },
  ];

  // 非选表单校验
  const modalRules = [
    {
      // eslint-disable-next-line complexity
      validator(_: any, value: string) {
        const areaId = form?.form.getFieldValue('areaId');
        if (!value) {
          return Promise.reject(new Error('该项为必填项'));
        }
        if (
          areaId === '310000' && // 上海
          (+value < 100 || +value > 660)
        ) {
          return Promise.reject(new Error('上海高考成绩范围为100～660分'));
        }
        if (
          areaId === '460000' && // 海南
          (+value < 100 || +value > 900)
        ) {
          return Promise.reject(new Error('海南高考成绩范围为100～900分'));
        } // 其他省份
        if (areaId !== '310000' && areaId !== '460000' && (+value < 100 || +value > 750)) {
          return Promise.reject(new Error('高考成绩范围为100～750分'));
        }
        return Promise.resolve();
      },
    },
  ];

  const createOrderRules = [
    {
      // eslint-disable-next-line complexity
      validator(_: any, value: string) {
        // 首选与次选科目的互相依赖性检查
        if (subjectType === ISubjectType.FirstAndSecond) {
          if (
            (selectedFirstSubject.length > 0 && selectedSecondSubject.length === 0) ||
            (selectedSecondSubject.length > 0 && selectedFirstSubject.length === 0)
          ) {
            return Promise.reject(new Error('首选科目和次选科目必须同时选择'));
          }
          if (selectedFirstSubject.length > 0 && selectedFirstSubject.length !== firstNum) {
            return Promise.reject(new Error(`请选择${firstNum}门首选科目`));
          }
          if (selectedSecondSubject.length > 0 && selectedSecondSubject.length !== secondNum) {
            return Promise.reject(new Error(`请选择${secondNum}门次选科目`));
          }
        }
        // 六选三
        if (
          subjectType === ISubjectType.ThreeOutOfSix &&
          selectedSecondSubject.length > 0 &&
          selectedSecondSubject.length !== secondNum
        ) {
          return Promise.reject(new Error(`请选择${secondNum}门科目`));
        }

        // 如果没有选择任何科目或选择了完整的科目数量，则通过验证
        return Promise.resolve();
      },
    },
  ];

  // 学科校验
  const subjectRules = [
    {
      // eslint-disable-next-line complexity
      validator(_: any, value: string) {
        // console.log(form.form.getFieldsValue(), 'value');
        if (subjectType === ISubjectType.ArtsOrSciences && !selectedArtsOrSciences.length) {
          return Promise.reject(new Error('请选择科类'));
        }
        if (
          subjectType === ISubjectType.FirstAndSecond &&
          selectedFirstSubject.length !== firstNum
        ) {
          return Promise.reject(new Error(`请选择${firstNum}门首选科目`));
        }
        if (
          subjectType === ISubjectType.FirstAndSecond &&
          selectedSecondSubject.length !== secondNum
        ) {
          return Promise.reject(new Error(`请选择${secondNum}门次选科目`));
        }
        if (
          subjectType === ISubjectType.ThreeOutOfSix &&
          selectedSecondSubject.length !== secondNum
        ) {
          return Promise.reject(new Error(`请选择${secondNum}门科目`));
        }
        return Promise.resolve();
      },
    },
  ];

  const scoreChange = (e: any) => {
    if (e.target.value.includes('.') || Number.isNaN(+e.target.value)) {
      e.target.value = e.target.value.slice(0, e.target.value.length - 1);
    } else if (+e.target.value === 0) {
      e.target.value = '';
    }
    form.form.setFieldValue('totalScore', e.target.value);
  };

  const memberScoreByType = (tempSubjectList: any) => {
    const {
      firstNum,
      secondNum,
      policy: policySelect,
      subjectTypeList,
      subjectList,
    } = tempSubjectList!;
    console.log('policySelect', policySelect);
    setSubjectType(policySelect);
    setFirstNum(firstNum);
    setSecondNum(secondNum);
    switch (policySelect) {
      case ISubjectType.ArtsOrSciences: {
        const res: any[] = [];
        subjectTypeList.forEach((item: { desc: any; code: any }) => {
          res.push({ name: item.desc, value: item.code });
        });
        setArtsOrSciencesList(res);
        break;
      }
      case ISubjectType.FirstAndSecond: {
        const firstSubjectList = subjectList
          .filter((item: { isFirst: number }) => item.isFirst === 1)
          .map((item: { subjectName: any; subject: any; subjectType?: any; isFirst: any }) => ({
            name: item.subjectName,
            value: item.subject,
            subjectType: item.subjectType || '',
            isFirst: item.isFirst,
          }));
        const secondSubjectList = subjectList
          .filter((item: { isFirst: number }) => item.isFirst === 0)
          // eslint-disable-next-line max-len
          .map((item: { subjectName: any; subject: any; isFirst: any }) => ({
            name: item.subjectName,
            value: item.subject,
            isFirst: item.isFirst,
          }));
        setFirstSubjectList(firstSubjectList);
        setSecondSubjectList(secondSubjectList);
        break;
      }
      case ISubjectType.ThreeOutOfSix: {
        // 也需要设置ArtsOrSciencesList，保存时候会用到其中的值
        const res: any[] = [];
        subjectTypeList.forEach((item: { desc: string; code: string }) => {
          res.push({ name: item.desc, value: item.code });
        });
        setArtsOrSciencesList(res);
        const secondSubjectList = subjectList
          .filter((item: { isFirst: number }) => item.isFirst === 0)
          // eslint-disable-next-line max-len
          .map((item: { subjectName: string; subject: any; isFirst: any }) => ({
            name: item.subjectName,
            value: item.subject,
            isFirst: item.isFirst,
          }));
        setSecondSubjectList(secondSubjectList);
        break;
      }
    }
  };

  // 回填数据
  const setDefaultSubject = (
    subjectType: { code: string; desc: string },
    memberSubjectList: { subject: string; isFirst: boolean }[]
  ) => {
    console.log('回填数据.current', policy.current);
    switch (policy.current) {
      case ISubjectType.ArtsOrSciences: {
        setSelectedArtsOrSciences([subjectType?.code || '']);
        break;
      }
      case ISubjectType.FirstAndSecond: {
        // 首选科目
        const firstItems = memberSubjectList.filter(ele => ele.isFirst);
        const confirmFirst: string[] = [];
        firstItems.forEach(ele => {
          confirmFirst.push(ele.subject);
        });
        setSelectedFirstSubject(confirmFirst);
        // 次选科目
        const secondItems = memberSubjectList.filter(ele => !ele.isFirst);
        const confirmSecond: string[] = [];
        secondItems.forEach(ele => {
          confirmSecond.push(ele.subject);
        });
        setSelectedSecondSubject(confirmSecond);
        break;
      }
      case ISubjectType.ThreeOutOfSix: {
        const secondItems = memberSubjectList.filter(ele => !ele.isFirst);
        const confirmSecond: string[] = [];
        secondItems.forEach(ele => {
          confirmSecond.push(ele.subject);
        });
        setSelectedSecondSubject(confirmSecond);
      }
    }
  };

  // 选择学科
  const handleSubjectChange = useCallback(
    (subjectType: ISubjectType, item: ISubjectItem, isFirst?: boolean) => {
      switch (subjectType) {
        case ISubjectType.ArtsOrSciences: {
          setSelectedArtsOrSciences([item.value]);
          break;
        }
        case ISubjectType.FirstAndSecond: {
          if (isFirst) {
            if (selectedFirstSubject.length && item.value === selectedFirstSubject[0]) {
              setSelectedFirstSubject([]);
            } else {
              setSelectedFirstSubject([item.value]);
            }
          } else {
            const selected = selectedSecondSubject.slice();
            const index = selectedSecondSubject.findIndex(ele => ele === item.value);
            if (index === -1) {
              // 选择
              selected.push(item.value);
            } else {
              // 取消
              selected.splice(index, 1);
            }
            const selectedItems = secondSubjectList.filter(
              ele => selected.indexOf(ele.value) !== -1
            );
            const res: string[] = [];
            selectedItems.forEach(ele => {
              res.push(ele.value);
            });
            setSelectedSecondSubject(res);
          }
          break;
        }
        case ISubjectType.ThreeOutOfSix: {
          const selected = selectedSecondSubject.slice();
          const index = selectedSecondSubject.findIndex(ele => ele === item.value);
          if (index === -1) {
            // 选择
            selected.push(item.value);
          } else {
            // 取消
            selected.splice(index, 1);
          }
          const selectedItems = secondSubjectList.filter(ele => selected.indexOf(ele.value) !== -1);
          const res: string[] = [];
          selectedItems.forEach(ele => {
            res.push(ele.value);
          });
          setSelectedSecondSubject(res);
          break;
        }
      }
    },
    [selectedFirstSubject, secondSubjectList, selectedSecondSubject]
  );

  const subjectSelectConfig: ISelectConfig[] = useMemo(() => {
    let config: ISelectConfig[] = [];
    switch (subjectType) {
      case ISubjectType.ArtsOrSciences: {
        config = [
          {
            config: {
              bigItem: true,
              data: artsOrSciencesList,
              selectedDataIndex: selectedArtsOrSciences,
              selectType: ISelectTypeEnum.Single,
              onChooseItem(item: ISelectDataItem) {
                handleSubjectChange(ISubjectType.ArtsOrSciences, item);
              },
            },
          },
        ];
        break;
      }
      case ISubjectType.FirstAndSecond: {
        config = [
          {
            name: '首选科目',
            config: {
              data: firstSubjectList,
              selectedDataIndex: selectedFirstSubject,
              selectType: ISelectTypeEnum.Single,
              limitNum: firstNum,
              onChooseItem(item: ISelectDataItem) {
                handleSubjectChange(ISubjectType.FirstAndSecond, item, true);
              },
            },
          },
          {
            name: '次选科目',
            config: {
              data: secondSubjectList,
              selectedDataIndex: selectedSecondSubject,
              selectType: ISelectTypeEnum.Mutiple,
              limitNum: secondNum,
              onChooseItem(item: ISelectDataItem) {
                handleSubjectChange(ISubjectType.FirstAndSecond, item);
              },
            },
          },
        ];
        break;
      }
      case ISubjectType.ThreeOutOfSix: {
        config = [
          {
            config: {
              data: secondSubjectList,
              selectedDataIndex: selectedSecondSubject,
              selectType: ISelectTypeEnum.Mutiple,
              limitNum: secondNum,
              onChooseItem(item: ISelectDataItem) {
                handleSubjectChange(ISubjectType.ThreeOutOfSix, item);
              },
            },
          },
        ];
        break;
      }
    }
    return config;
    // eslint-disable-next-line max-len
  }, [
    artsOrSciencesList,
    firstSubjectList,
    handleSubjectChange,
    secondNum,
    secondSubjectList,
    selectedArtsOrSciences,
    selectedFirstSubject,
    selectedSecondSubject,
    subjectType,
  ]);

  // 获取选科参数
  const getParams = () => {
    let type = '';
    let subjectTypeObject = {};
    const subjectList: { subject: string; isFirst: number }[] = [];
    let subjectMapList: ISubjectList[] = [];
    console.log('???????', selectedArtsOrSciences);
    switch (subjectType) {
      case ISubjectType.ArtsOrSciences: {
        type = selectedArtsOrSciences[0] || '';
        subjectTypeObject = { desc: selectedArtsOrSciences[0], code: selectedArtsOrSciences[0] };
        break;
      }
      case ISubjectType.FirstAndSecond: {
        selectedFirstSubject.forEach(item => {
          subjectList.push({
            isFirst: 1,
            subject: item,
          });
        });
        selectedSecondSubject.forEach(item => {
          subjectList.push({
            isFirst: 0,
            subject: item,
          });
        });
        // 合并首选和再选科目
        subjectMapList = [
          ...(firstSubjectList?.filter(item => selectedFirstSubject.includes(item.value)) || []),
          ...(secondSubjectList?.filter(item => selectedSecondSubject.includes(item.value)) || []),
        ];

        type =
          firstSubjectList.find(item => item.value === selectedFirstSubject[0])?.subjectType || '';
        subjectTypeObject = {
          desc: firstSubjectList.find(item => item.value === selectedFirstSubject[0]).name || '',
          code:
            firstSubjectList.find(item => item.value === selectedFirstSubject[0])?.subjectType ||
            '',
        };
        break;
      }
      case ISubjectType.ThreeOutOfSix: {
        selectedSecondSubject.forEach(item => {
          subjectList.push({
            isFirst: 0,
            subject: item,
          });
        });
        subjectMapList =
          secondSubjectList?.filter(item => selectedSecondSubject.includes(item.value)) || [];
        type = artsOrSciencesList[0].value || '';
        subjectTypeObject = { desc: artsOrSciencesList[0].name, code: artsOrSciencesList[0].value };
        break;
      }
    }
    return { type, subjectList, subjectMapList, artsOrSciencesList, subjectTypeObject };
  };

  return {
    form,
    rules,
    subjectRules,
    subjectType,
    selectedArtsOrSciences,
    firstNum,
    selectedFirstSubject,
    selectedSecondSubject,
    secondNum,
    subjectSelectConfig,
    artsOrSciencesList,
    firstSubjectList,
    secondSubjectList,
    modalRules,
    createOrderRules,
    policy,
    setSecondSubjectList,
    setFirstSubjectList,
    setArtsOrSciencesList,
    setSecondNum,
    setDefaultSubject,
    setSelectedSecondSubject,
    setSelectedFirstSubject,
    setFirstNum,
    scoreChange,
    setSubjectType,
    setSelectedArtsOrSciences,
    memberScoreByType,
    getParams,
  };
};
export default useForm;
