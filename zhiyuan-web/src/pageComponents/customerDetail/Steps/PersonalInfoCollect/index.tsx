import AudioContent from '@/pageComponents/customerDetail/Components/AudioContent';
import style from './style.module.scss';
import { Button, Checkbox, Form, FormInstance, Input, List, Radio, Select } from 'antd';
import {
  IActions,
  ICollectflowRes,
  IPosRangeParams,
  IScoreSubject,
  ISegments,
  ISubSteps,
} from '@/interface/api/customerDetail';
import { getStorage } from '@/utils/tool';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReturnPng from '@/images/icons/return.png';
import { LinkOutlined } from '@ant-design/icons';
import { getBatchList, getSubjectPolicy } from '@/service/apis/sessionDetail';
import { getPositionRangeApi, getEthnicityListApi } from '@/service/apis/customerDetail';
import ModalImage from '../../Components/ModalImage';
import { flushSync } from 'react-dom';
import { buildCreateSessionBatchPayload } from '@/utils/customerDetailSession';
const { Option } = Select;
const CheckboxGroup = Checkbox.Group;

interface ICollectflowProps {
  stepsData: ICollectflowRes;
  onNextStep: (btn: IActions, formValues?: any) => void;
  onDraftChange?: (formValues?: any) => void;
  userSubjectList: any;
  onBackStep?: () => void;
  savedValues?: any;
}

interface IFormState {
  values: any;
  showSummary: boolean;
  processFlag: boolean;
}

const sexOptions = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
];

const PersonalInfoCollect = (props: ICollectflowProps) => {
  const [scoreForm] = Form.useForm();
  const [detailForm] = Form.useForm();
  const formStrengthSubjectList = Form.useWatch('strengthSubjectList', scoreForm);
  const formColorSistuation = Form.useWatch('colorSistuation', detailForm);
  const { stepsData, onNextStep, onDraftChange, userSubjectList, onBackStep, savedValues } = props;
  const stepsRef = useRef<ICollectflowRes>();
  stepsRef.current = stepsData;
  const formsRef = useRef<FormInstance[]>([]);
  const summaryRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const [batchOptions, setBatchOptions] = useState<any>([]);
  const [subjectType, setSubjectType] = useState<any>(null); // 学科类型-首选科目
  const [subjectSecondList, setSubjectSecondList] = useState<any>(); // 学科类型-次选科目
  const [formStates, setFormStates] = useState<IFormState[]>([]);
  const [totalScore, setTotalScore] = useState(0);
  const [bonusPolicy, setBonusPolicy] = useState(false);
  // 在组件顶部添加状态
  const [allFormValues, setAllFormValues] = useState<Record<number, any>>({});
  const [currentImageUrl, setCurrentImageUrl] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [ethnicityList, setEthnicityList] = useState<any>([]); // 民族列表
  const [subjectPolicyData, setSubjectPolicyData] = useState<any>(null);
  // 用于防止请求竞态条件的 ref
  const positionRangeRequestIdRef = useRef<number>(0);

  // const storedUserInfo: any = getStorage('userInfo') || '{}';
  // const userInfo = JSON.parse(storedUserInfo);

  const [userInfo, setUserInfo] = useState<any>(null);
  useEffect(() => {
    const storedUserInfo: any = getStorage('userInfo') || null;
    const userInfoData = JSON.parse(storedUserInfo);
    setUserInfo(userInfoData);
  }, []);

  // 拉取学科政策
  const fetchSubjectPolicy = async () => {
    if (!userInfo) return;
    const { code, data } = await getSubjectPolicy(userInfo.userScoreOb?.province?.code);
    if (code === 0 && data) {
      setSubjectPolicyData(data);
      handleBatchInfoRequest(data.prepareType, data.subjectTypeList);
    }
  };

  useEffect(() => {
    fetchSubjectPolicy();
  }, [userInfo]);

  const splitSubjectListField = (subSteps: any) => {
    return subSteps.map((subStep: any) => {
      if (!subStep.formConfig?.fields) return subStep;

      const updatedFields: any = [];

      subStep.formConfig.fields.forEach((field: any) => {
        if (field.fieldId === 'subjectList') {
          // 获取 options：优先使用 subjectPolicyData.subjectList，如果为空则用 subjectTypeList
          let options: any[] = [];
          if (subjectPolicyData?.subjectList?.length) {
            options = subjectPolicyData.subjectList.map((item: any) => ({
              code: item.subject,
              name: item.subjectName,
              isFirst: item.isFirst,
              subject: item.subject,
              subjectType: item.subjectType,
              subjectName: item.subjectName,
            }));
          } else if (subjectPolicyData?.subjectTypeList?.length) {
            options = subjectPolicyData.subjectTypeList.map((item: any) => ({
              code: item.code,
              name: item.desc,
              subject: item.code,
            }));
          }
          // 根据用户科目类型处理首选/次选逻辑
          if (userInfo?.userScoreOb?.subjectType?.code === 'N') {
            updatedFields.push({
              ...field,
              defaultValue: field.defaultValue.map((item: any) => item.value),
              mutiSelectType: 'subjectList',
              options,
            });
          } else if (
            userInfo?.userScoreOb?.subjectType?.code === 'L' ||
            userInfo?.userScoreOb?.subjectType?.code === 'W'
          ) {
            updatedFields.push({
              ...field,
              fieldId: 'subjectList',
              fieldName: '全部科目',
              options,
              helpConfig: {
                ...field.helpConfig,
                helpText: field.helpConfig.helpText + '（首选）',
              },
              defaultValue: userInfo?.userScoreOb?.subjectType?.code,
              fieldType: 'radio',
              mutiSelectType: 'subjectList',
            });
          } else if (
            userInfo?.userScoreOb?.subjectType?.code === 'WL' ||
            userInfo?.userScoreOb?.subjectType?.code === 'LS'
          ) {
            const firstChoiceOptions = options.filter(opt => opt.isFirst);
            const secondChoiceOptions = options.filter(opt => !opt.isFirst);

            const firstChoiceDefaultValues =
              field.defaultValue?.filter((value: any) =>
                firstChoiceOptions.some((opt: any) => opt.subject === value.value)
              ) || [];
            // setSubjectType(firstChoiceDefaultValues[0]);

            const secondChoiceDefaultValues =
              field.defaultValue?.filter((value: any) =>
                secondChoiceOptions.some((opt: any) => opt.subject === value.value)
              ) || [];
            setSubjectSecondList(secondChoiceDefaultValues);

            const firstChoiceField = {
              ...field,
              fieldId: 'subjectList_first',
              fieldName: '首选科目',
              defaultValue: firstChoiceDefaultValues.map((item: any) => item.value),
              options: firstChoiceOptions,
              helpConfig: {
                ...field.helpConfig,
                helpText: field.helpConfig.helpText + '（首选）',
              },
              mutiSelectType: 'subjectList',
            };

            const secondChoiceField = {
              ...field,
              fieldId: 'subjectList_second',
              fieldName: '次选科目',
              defaultValue: secondChoiceDefaultValues.map((item: any) => item.value),
              options: secondChoiceOptions,
              helpConfig: {
                ...field.helpConfig,
                helpText: field.helpConfig.helpText + '（次选）',
              },
              mutiSelectType: 'subjectList',
            };

            updatedFields.push(firstChoiceField, secondChoiceField);
          }
        } else {
          updatedFields.push(field);
        }
      });

      return {
        ...subStep,
        formConfig: {
          ...subStep.formConfig,
          fields: updatedFields,
        },
      };
    });
  };
  // processedStepsData 依赖 subjectPolicyData
  const processedStepsData = useMemo(() => {
    if (!stepsData?.subSteps || !userInfo || !subjectPolicyData) return stepsData;

    return {
      ...stepsData,
      subSteps: splitSubjectListField(stepsData.subSteps),
    };
  }, [stepsData, userInfo, subjectPolicyData]);

  // 获取民族列表
  const getEthnicityList = async () => {
    const { code, data } = await getEthnicityListApi();
    if (code === 0 && data) {
      setEthnicityList(data);
    }
  };
  // 初始化表单状态
  useEffect(() => {
    getEthnicityList();
  }, []);

  // 构建初始值
  const getBatchFieldValue = (options = batchOptions) => {
    const savedBatch = savedValues?.batch;
    if (!savedBatch || !Array.isArray(options) || !options.length) return undefined;
    const matched =
      options.find(
        (item: any) =>
          String(item.batch) === String(savedBatch.code) &&
          (!savedBatch.level || String(item.level?.key) === String(savedBatch.level))
      ) ||
      options.find((item: any) => String(item.batch) === String(savedBatch.code)) ||
      options.find(
        (item: any) =>
          String(item.batchTitle || '') === String(savedBatch.name || '').split('(')[0] ||
          String(item.label) === String(savedBatch.name)
      );
    return matched?.id;
  };

  const resolveBatchOption = (batchValue: any) => {
    const options = Array.isArray(batchOptions) ? batchOptions : [];
    if (!options.length) return null;
    const normalizedBatchValue =
      batchValue === undefined || batchValue === null ? '' : String(batchValue);
    const savedBatch = savedValues?.batch;

    return (
      (normalizedBatchValue
        ? options.find((item: any) => String(item.id) === normalizedBatchValue)
        : null) ||
      (normalizedBatchValue
        ? options.find((item: any) => String(item.batch) === normalizedBatchValue)
        : null) ||
      (savedBatch
        ? options.find(
            (item: any) =>
              String(item.batch) === String(savedBatch.code) &&
              (!savedBatch.level || String(item.level?.key) === String(savedBatch.level))
          )
        : null) ||
      (savedBatch
        ? options.find((item: any) => String(item.batch) === String(savedBatch.code))
        : null) ||
      options[0] ||
      null
    );
  };

  const buildBatchPayload = (batchOption: any) => {
    return buildCreateSessionBatchPayload(batchOption) || savedValues?.batch;
  };

  const getSubjectCodes = (filter?: 'first' | 'second') => {
    const subjectList = Array.isArray(savedValues?.subjectList) ? savedValues.subjectList : [];
    return subjectList
      .filter((item: any) => {
        if (filter === 'first') return item?.isFirst === 1;
        if (filter === 'second') return item?.isFirst !== 1;
        return true;
      })
      .map((item: any) => item?.value || item?.subject || item?.code)
      .filter(Boolean);
  };

  const getSavedValuesForSubStep = (subStep: any) => {
    const values: any = {};
    if (!savedValues || !subStep?.formConfig?.fields) return values;

    if (subStep.subStepId === 'personal_info_step1') {
      subStep.formConfig.fields.forEach((field: any) => {
        if (field.fieldId === 'subjectList_first') {
          values.subjectList_first = getSubjectCodes('first');
        } else if (field.fieldId === 'subjectList_second') {
          values.subjectList_second = getSubjectCodes('second');
        } else if (field.fieldId === 'subjectList') {
          values.subjectList =
            field.fieldType === 'radio'
              ? savedValues?.subjectType?.code || getSubjectCodes()[0]
              : getSubjectCodes();
        }
      });

      if (Array.isArray(savedValues?.subjectScoreList)) {
        savedValues.subjectScoreList.forEach((item: any) => {
          if (item?.subject && item?.subjectName) {
            values[`subjectScoreList-${item.subjectName}-${item.subject}`] = item.score;
          }
        });
      }
      if (Array.isArray(savedValues?.strengthSubjectList)) {
        values.strengthSubjectList = savedValues.strengthSubjectList
          .map((item: any) => item?.subject || item?.value || item?.code)
          .filter(Boolean);
      }
      if (Object.prototype.hasOwnProperty.call(savedValues, 'bonusPolicy')) {
        values.bonusPolicy = savedValues.bonusPolicy;
      }
      if (Object.prototype.hasOwnProperty.call(savedValues, 'bonusScore')) {
        values.bonusScore = savedValues.bonusScore;
      }
      if (Object.prototype.hasOwnProperty.call(savedValues, 'totalScore')) {
        values.totalScore = savedValues.totalScore;
      }
      if (Object.prototype.hasOwnProperty.call(savedValues, 'totalScorePos')) {
        values.totalScorePos = savedValues.totalScorePos;
      }
      const savedBatchId = getBatchFieldValue();
      if (savedBatchId !== undefined) values.batch = savedBatchId;
    }

    if (subStep.subStepId === 'personal_info_step2') {
      if (savedValues?.sex?.code) values.sex = savedValues.sex.code;
      if (Object.prototype.hasOwnProperty.call(savedValues, 'height')) {
        values.height = savedValues.height;
      }
      if (Array.isArray(savedValues?.colorSistuation)) {
        values.colorSistuation = savedValues.colorSistuation;
      }
      if (savedValues?.visionAbility) {
        values['visionMutiInput-left'] = savedValues.visionAbility.left;
        values['visionMutiInput-right'] = savedValues.visionAbility.right;
      }
      if (savedValues?.ethnicity?.code) values.ethnicity = savedValues.ethnicity.code;
      if (savedValues?.politicalStatus?.code) values.politicalStatus = savedValues.politicalStatus.code;
      if (Object.prototype.hasOwnProperty.call(savedValues, 'specialPlan')) {
        values.specialPlan = savedValues.specialPlan;
      }
    }

    return values;
  };

  const getInitialValues = (subStep: any) => {
    const initialValues: any = {};
    if (subStep.formConfig?.fields) {
      subStep.formConfig.fields.forEach((field: any) => {
        initialValues[field.fieldId] = field.defaultValue;
      });
    }
    return {
      ...initialValues,
      ...getSavedValuesForSubStep(subStep),
    };
  };

  // 初始化表单状态和表单实例
  useEffect(() => {
    if (processedStepsData?.subSteps) {
      const restoredValues: Record<number, any> = {};
      const initialStates = processedStepsData.subSteps.map((subStep, index) => {
        const savedSubStepValues = getSavedValuesForSubStep(subStep);
        const hasSavedValues = Object.keys(savedSubStepValues).length > 0;
        const initialValues = getInitialValues(subStep);
        if (hasSavedValues) {
          restoredValues[index] = { ...initialValues, subStepId: subStep.subStepId };
        }
        return {
          values: hasSavedValues ? initialValues : null,
          showSummary: hasSavedValues,
          processFlag: hasSavedValues,
        };
      });
      setFormStates(initialStates);
      if (Object.keys(restoredValues).length) {
        setAllFormValues(prev => ({ ...prev, ...restoredValues }));
      }

      processedStepsData.subSteps.forEach((subStep, index) => {
        const initValues = getInitialValues(subStep);
        const stepForm = getStepForm(index);
        formsRef.current[index] = stepForm;
        stepForm.setFieldsValue(initValues);
      });

      // 这里可以调用 provinceChange，因为现在有表单实例了
      if (userInfo) provinceChange();
    }
  }, [processedStepsData, userInfo]);

  useEffect(() => {
    if (!processedStepsData?.subSteps) return;
    const restoredValues: Record<number, any> = {};
    setFormStates(prev => {
      const nextStates = processedStepsData.subSteps.map((subStep, index) => {
        const savedSubStepValues = getSavedValuesForSubStep(subStep);
        const hasSavedValues = Object.keys(savedSubStepValues).length > 0;
        const initialValues = getInitialValues(subStep);
        const prevState = prev[index];
        const currentValues = prevState?.values ?? (hasSavedValues ? initialValues : null);
        if (currentValues) {
          restoredValues[index] = { ...currentValues, subStepId: subStep.subStepId };
        }
        return {
          values: currentValues,
          showSummary: Boolean(prevState?.showSummary || hasSavedValues),
          processFlag: prevState?.processFlag ?? hasSavedValues,
        };
      });
      return nextStates;
    });

    processedStepsData.subSteps.forEach((subStep, index) => {
      const initValues = getInitialValues(subStep);
      const stepForm = getStepForm(index);
      formsRef.current[index] = stepForm;
      stepForm.setFieldsValue(initValues);
    });

    if (Object.keys(restoredValues).length) {
      setAllFormValues(prev => ({ ...prev, ...restoredValues }));
    }
    if (Object.prototype.hasOwnProperty.call(savedValues || {}, 'totalScore')) {
      setTotalScore(Number(savedValues.totalScore) || 0);
    }
    if (Object.prototype.hasOwnProperty.call(savedValues || {}, 'bonusPolicy')) {
      setBonusPolicy(Boolean(savedValues.bonusPolicy));
    }
  }, [processedStepsData, batchOptions, savedValues]);

  const getStepForm = (index: number) => (index === 0 ? scoreForm : detailForm);

  const getScrollParent = (node: HTMLElement): HTMLElement | null => {
    let parent = node.parentElement;
    while (parent) {
      const style = window.getComputedStyle(parent);
      const overflowY = style.overflowY;
      if (
        (overflowY === 'auto' || overflowY === 'scroll') &&
        parent.scrollHeight > parent.clientHeight
      ) {
        return parent;
      }
      parent = parent.parentElement;
    }
    return null;
  };

  const scrollSummaryDownIfNeeded = (index: number) => {
    const target = summaryRefs.current[index];
    if (!target || typeof window === 'undefined') return;

    const gap = 24;
    const targetRect = target.getBoundingClientRect();
    const scrollParent = getScrollParent(target);

    if (scrollParent) {
      const parentRect = scrollParent.getBoundingClientRect();
      const overflowDistance = targetRect.bottom - parentRect.bottom + gap;
      if (overflowDistance > 0) {
        scrollParent.scrollBy({ top: overflowDistance, behavior: 'smooth' });
      }
      return;
    }

    const overflowDistance = targetRect.bottom - window.innerHeight + gap;
    if (overflowDistance > 0) {
      window.scrollBy({ top: overflowDistance, behavior: 'smooth' });
    }
  };

  // 表单提交处理
  const handleFormFinish = (values: any, index: number, subStepId: string) => {
    const allValue = { ...allFormValues, [index]: { ...values, subStepId } };
    flushSync(() => {
      setFormStates(prev => {
        const next = [...prev];
        next[index] = {
          ...next[index],
          values,
          processFlag: true,
          showSummary: true,
        };
        return next;
      });
      setAllFormValues(allValue);
    });
    handleConfirmedDraftChange(allValue);

    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => scrollSummaryDownIfNeeded(index));
    });
  };

  const scrollToFirstErrorField = (errorInfo: any, index: number) => {
    const firstError = errorInfo?.errorFields?.[0];
    if (!firstError) return;
    const currentForm = formsRef.current[index] || getStepForm(index);
    currentForm?.scrollToField(firstError.name, {
      behavior: 'smooth',
      block: 'center',
    });
  };

  const transformFormValues = (values: Record<number, any>) => {
    // 合并所有已提交的表单值

    let transformedFormValues = Object.values(values).map(value => {
      const stepData = stepsRef.current?.subSteps.find(
        subStep => subStep.subStepId === value.subStepId
      );
      const fields = stepData?.formConfig?.fields || [];
      if (value.subStepId === 'personal_info_step1') {
        const selectedBatch = resolveBatchOption(value.batch);
        const subListKeys = Object.keys(value)
          .filter(key => key.includes('subjectList'))
          .reduce((result, key) => {
            if (Array.isArray(value[key])) {
              result.push(...value[key]);
            }
            return result;
          }, []);
        const subjectList = fields
          ?.find(field => field.fieldId === 'subjectList')
          ?.options.filter(option => subListKeys.includes(option.subject));
        const subjectTypeItem = subjectList.find(subject =>
          Object.hasOwnProperty.call(subject, 'subjectType')
        );
        // 擅长学科
        const strengthSubjectList = fields
          ?.find(field => field.fieldId === 'strengthSubjectList')
          ?.options.filter(option => value?.strengthSubjectList.includes(option.subject))
          ?.map(item => ({ subject: item.subject, subjectName: item.subjectName }));

        return {
          bonusPolicy: value?.bonusPolicy,
          bonusScore: value?.bonusScore,
          totalScore: value?.totalScore,
          totalScorePos: value?.totalScorePos,
          strengthSubjectList,
          subjectList: subjectList?.map(item => {
            const data = { name: item.subjectName, value: item.subject, isFirst: item.isFirst };
            if (item.subjectType) {
              return {
                ...data,
              };
            }
            return item.subjectType ? { ...data, subjectType: item.subjectType } : { ...data };
          }),
          subjectType: userInfo.userScoreOb?.subjectType,
          // subjectType: {
          //   code: subjectTypeItem.subjectType,
          //   desc: subjectTypeItem.subjectName,
          // },
          subjectScoreList: Object.entries(value)
            .filter(([key]) => key.startsWith('subjectScoreList-') && key.split('-').length === 3)
            .map(([key, value]) => {
              const [, subjectName, subjectCode] = key.split('-');
              return {
                subject: subjectCode,
                subjectName: subjectName,
                score: Number(value),
              };
            }),
          batch: buildBatchPayload(selectedBatch),
          prepareType: selectedBatch?.prepareType || savedValues?.prepareType,
        };
      }
      if (value.subStepId === 'personal_info_step2') {
        return {
          height: value?.height,
          colorSistuation: value?.colorSistuation,
          sex: fields
            .find(field => field.fieldId === 'sex')
            ?.options.find(sex => sex.code === value.sex),
          visionAbility: {
            left: value?.['visionMutiInput-left'],
            right: value?.['visionMutiInput-right'],
          },
          ethnicity: fields
            .find(item => item.fieldId === 'ethnicity')
            ?.options.find(ethnicity => ethnicity.code === value.ethnicity),
          politicalStatus: fields
            .find(item => item.fieldId === 'politicalStatus')
            ?.options.find(politicalStatus => politicalStatus.code === value.politicalStatus),
          specialPlan:
            value?.specialPlan === true ||
            value?.specialPlan === 'true' ||
            value?.specialPlan === '1',
        };
      }
    });
    const mergedValues = Object.assign({}, ...transformedFormValues);
    console.log('mergedValues', mergedValues);
    return mergedValues;
  };

  const handleConfirmedDraftChange = (values: Record<number, any>) => {
    const mergedValues = transformFormValues(values);
    onDraftChange?.(mergedValues);
    return mergedValues;
  };

  // 下一步处理
  const handleClickNextStep = (item: ISubSteps, values: Record<number, any>) => {
    const latestValues = { ...values };
    processedStepsData?.subSteps?.forEach((subStep, index) => {
      if (!formStates[index]?.processFlag) return;
      const currentFormValues = formsRef.current[index]?.getFieldsValue?.() || {};
      latestValues[index] = {
        ...latestValues[index],
        ...currentFormValues,
        subStepId: subStep.subStepId,
      };
    });
    const mergedValues = handleConfirmedDraftChange(latestValues);

    // 传递合并后的表单值
    const btn = {
      actionType: 'next',
      nextSubStepId: 'major_preference_step1',
      label: '了解完成，继续下一步',
    };

    onNextStep(btn, mergedValues);
  };

  // 计算总分
  const calculateTotalScore = (values: any, allValues: any, index?: number) => {
    let sum = 0;
    
    // 获取省份code和batch level
    const provinceCode = userInfo?.userScoreOb?.province?.code;
    const batchId = allValues.batch || (index !== undefined ? formsRef.current[index]?.getFieldValue('batch') : null);
    const batchLevel = batchId ? batchOptions?.find(item => item.id === batchId)?.level?.key : null;
    
    // 判断是否是北京/天津/上海 + 专科批（level = '02'）
    const isSpecialProvinceJuniorCollege = 
      ['110000', '120000', '310000'].includes(provinceCode) && batchLevel === '02';
    
    // 语数外三科的subject code
    const mainSubjects = ['08', '10', '11']; // 语文、数学、英语
    
    Object.entries(values)
      .filter(([key]) => key.startsWith('subjectScoreList-') && key.split('-').length === 3)
      .forEach(([key, score]) => {
        if (score && !isNaN(Number(score))) {
          // 如果是专科批（北京/天津/上海），只计算语数外三科
          if (isSpecialProvinceJuniorCollege) {
            const subjectCode = key.split('-')[2]; // 从 key 中提取 subject code
            if (mainSubjects.includes(subjectCode)) {
              sum += Number(score);
            }
          } else {
            // 否则计算所有科目
            sum += Number(score);
          }
        }
      });

    // 加分始终要加上
    if (allValues.bonusScore && !isNaN(Number(allValues.bonusScore))) {
      sum += Number(allValues.bonusScore);
    }
    return sum;
  };

  // 表单值变化监听
  const handleWatchValues = (values: any, allValues: any, index: number) => {
    if (values.bonusPolicy !== undefined) {
      setBonusPolicy(values.bonusPolicy);
    }

    if (index !== 0) return;

    const scoreMutiInputData = Object.entries(allValues).reduce((acc, [key, value]) => {
      if (key.includes('subjectScoreList')) {
        acc[key] = value;
      }
      return acc;
    }, {});

    // 传递 index 以便获取 batch 值
    const newTotalScore = calculateTotalScore(scoreMutiInputData, allValues, index);
    setTotalScore(newTotalScore);

    // 使用 ref 中的表单实例
    if (formsRef.current[index]) {
      formsRef.current[index].setFieldsValue({
        totalScore: newTotalScore,
      });
    }

    // 使用新计算的总分来判断和更新排名
    // 从表单实例中获取 batch 值，因为 allValues 可能不包含 batch
    const batchValue = formsRef.current[index]?.getFieldValue('batch');
    if (newTotalScore && batchValue) {
      getPositionRange({ ...allValues, batch: batchValue }, newTotalScore);
    }
  };

  // 获取成绩位次
  const getPositionRange = async (allValues: any, totalScoreValue?: number) => {
    // 生成新的请求 ID，用于防止竞态条件
    const currentRequestId = ++positionRangeRequestIdRef.current;
    
    const dataLevel = batchOptions?.find(item => item.id === allValues.batch)?.level.key;
    // 优先使用传入的总分值，如果没有则使用 allValues 中的值
    const score = totalScoreValue !== undefined ? totalScoreValue : allValues.totalScore;
    const params: IPosRangeParams = {
      areaId: userInfo?.userScoreOb?.province?.code,
      subject: userInfo?.userScoreOb?.subjectType.code,
      dataLevel,
      year: userInfo?.userScoreOb?.examYear,
      score: String(score),
    };
    const { code, data } = await getPositionRangeApi(params);
    // 只有当前请求是最新的请求时才更新排名，避免旧请求覆盖新结果
    if (code === 0 && data && currentRequestId === positionRangeRequestIdRef.current) {
      formsRef.current.forEach(form => {
        form?.setFieldValue('totalScorePos', data.lowestRank || 0);
      });
    }
  };

  // 获取批次信息
  const provinceChange = async () => {
    const { code, data } = await getSubjectPolicy(userInfo.userScoreOb?.province?.code);
    if (code === 0 && data) {
      handleBatchInfoRequest(data.prepareType, data.subjectTypeList);
    }
  };

  const handleBatchInfoRequest = async (prepareType: any, subjectTypeList: any) => {
    const { code, data } = await getBatchList({
      areaId: userInfo.userScoreOb?.province?.code,
      prepareType: prepareType.code,
      subject: userInfo.userScoreOb?.subjectType?.code,
    });
    if (code === 0 && data) {
      const list = data.batchList?.map(item => ({
        ...item,
        label: buildCreateSessionBatchPayload(item)?.name || item.batchTitle,
        value: item.id,
      }));
      const currentBatchId = scoreForm.getFieldValue('batch');
      const validCurrentBatchId = list?.some(item => String(item.id) === String(currentBatchId))
        ? currentBatchId
        : undefined;
      scoreForm.setFieldsValue({
        batch: getBatchFieldValue(list) || validCurrentBatchId || list?.[0]?.id,
      });
      setBatchOptions(list);
    }
  };

  // 点击查看图片
  const handleShowModal = (rich: any) => {
    setCurrentImageUrl(rich.materialUrl);
    setIsModalOpen(true);
  };

  const gradesRules = (max: any) => [
    {
      validator(rule: any, value: any) {
        if (value >= 0 && value <= max) {
          return Promise.resolve();
        }
        return Promise.reject(new Error(`只能输入0-${max}`));
      },
    },
  ];

  // 渲染表单字段
  const renderFormField = (field: any, currentForm: FormInstance) => {
    switch (field.fieldType) {
      case 'mutiSelect':
        return field.mutiSelectType === 'subjectList' || field.fieldId === 'strengthSubjectList' ? (
          <CheckboxGroup defaultValue={field.defaultValue}>
            {field.options?.map((config: any) => (
              <Checkbox
                key={config.subject}
                disabled={
                  !field.editable ||
                  (field.fieldId === 'strengthSubjectList' &&
                    formStrengthSubjectList?.length >= field.validation.limit &&
                    !formStrengthSubjectList?.includes(config.subject))
                }
                value={config.subject}
              >
                {config.subjectName}
              </Checkbox>
            ))}
          </CheckboxGroup>
        ) : (
          <CheckboxGroup defaultValue={field.defaultValue}>
            {field.options?.map((config: any, index: number) => (
              <Checkbox
                key={`${config.value}-${index}`}
                disabled={
                  !field.editable ||
                  (field.fieldId === 'colorSistuation' && config.value === 'normal'
                    ? formColorSistuation?.includes('colorBlind') ||
                      formColorSistuation?.includes('colorWeak')
                    : formColorSistuation?.includes('normal'))
                }
                value={config.value}
              >
                {config.label}
              </Checkbox>
            ))}
          </CheckboxGroup>
        );

      case 'radio':
        return field.fieldId === 'ethnicity' ? (
          <Select
            options={field.options.map(item => ({ label: item.name, value: item.code }))}
            disabled={!field.editable}
          />
        ) : (
          <Radio.Group defaultValue={field.defaultValue}>
            {field.options?.map((config: any) => (
              <Radio.Button key={config.code} value={config.code} disabled={!field.editable}>
                {config.name}
              </Radio.Button>
            ))}
          </Radio.Group>
        );

      case 'scoreMutiInput':
        return (
          <div className="scoreSubject">
            {field.inputList.map((inp: IScoreSubject) => (
              <Form.Item
                key={inp.subject}
                name={`subjectScoreList-${inp.subjectName}-${inp.subject}`}
                style={{ marginBottom: 0 }}
                rules={[
                  {
                    required: true,
                    message: '请输入',
                  },
                  ...gradesRules(['08', '10', '11'].includes(inp.subject) ? 150 : 100),
                ]}
              >
                <Input placeholder={inp.subjectName} disabled={!field.editable} />
              </Form.Item>
            ))}
          </div>
        );

      case 'visionMutiInput':
        return (
          <div className="visionMutiStyle">
            {field.inputList.map((inp: any) => (
              <Form.Item
                key={inp.value}
                name={`visionMutiInput-${inp.value}`}
                style={{ marginBottom: 0 }}
                rules={[
                  {
                    required: true,
                    message: `请输入${inp.label}`,
                  },
                ]}
              >
                <Input placeholder={inp.label} disabled={!field.editable} />
              </Form.Item>
            ))}
          </div>
        );

      default:
        if (currentForm.getFieldValue('bonusPolicy') && field.fieldId === 'bonusScore') {
          return <Input placeholder="请输入加分" disabled={!bonusPolicy} />;
        } else if (field.fieldId === 'totalScore') {
          return <Input placeholder="总分" disabled value={totalScore} readOnly />;
        } else if (field.fieldType === 'apiGet' && field.fieldId === 'totalScorePos') {
          return <Input placeholder={field.validation.required} disabled readOnly />;
        } else if (field.fieldType === 'input' && field.fieldId === 'height') {
          return (
            <Input placeholder={field.validation.required} disabled={!field.editable} suffix="cm" />
          );
        } else if (field.fieldType === 'apiGet' && field.fieldId === 'batch') {
          return <Select options={batchOptions} disabled={!field.editable} />;
        }
        return null;
    }
  };

  const shouldValidateOuterField = (field: any) => {
    return !['scoreMutiInput', 'visionMutiInput'].includes(field.fieldType);
  };

  // 渲染单个步骤
  const renderStep = (item: any, index: number) => {
    const formState = formStates[index] || { values: null, showSummary: false, processFlag: false };
    const currentForm = getStepForm(index);
    formsRef.current[index] = currentForm;

    // 控制步骤显示逻辑
    if (index > 0 && !formStates[index - 1]?.processFlag) {
      return null;
    }

    return (
      <div className={style.confirmSubSteps} key={item.subStepId}>
        {/* 内容片段 */}
        {item.contentSegments?.map((cs: ISegments) =>
          cs.type === 'audio' ? (
            <div className={style.confirmWrapper} key={cs.segmentId}>
              <AudioContent audioData={cs} />
            </div>
          ) : cs.type === 'image' ? (
            <div className={style.confirmWrapper} key={cs.segmentId}>
              <img src={cs.materialUrl} alt={cs.content?.title} />
            </div>
          ) : null
        )}

        {/* 表单部分 */}
        {item.formConfig && (
          <div className={style.confirmForm}>
            <div className={style.title}>{item.formConfig.title}</div>
            <Form
              form={currentForm}
              name={`confirmForm-${index}`}
              onFinish={values => handleFormFinish(values, index, item.subStepId)}
              onFinishFailed={errorInfo => scrollToFirstErrorField(errorInfo, index)}
              initialValues={getInitialValues(item)}
              onValuesChange={(values, allValues) => handleWatchValues(values, allValues, index)}
              labelCol={{ flex: '110px' }}
              labelAlign="right"
              labelWrap
            >
              {item.formConfig.fields?.map((field: any) => {
                if (field.fieldId === 'bonusScore' && !currentForm.getFieldValue('bonusPolicy')) {
                  return null;
                }
                const isOuterValidatedField = shouldValidateOuterField(field);
                return (
                  <Form.Item
                    key={field.fieldId}
                    label={field.fieldName}
                    name={isOuterValidatedField ? field.fieldId : undefined}
                    initialValue={isOuterValidatedField ? field.defaultValue : undefined}
                    rules={
                      isOuterValidatedField
                        ? [
                            {
                              required: field.required,
                              message: field.validation?.required,
                            },
                          ]
                        : undefined
                    }
                    extra={
                      field.helpConfig ? (
                        <>
                          {field.helpConfig?.showFieldHelp ? (
                            <span style={{ color: '#919296', fontSize: 12 }}>
                              {field.helpConfig.helpText}
                            </span>
                          ) : null}
                          {field.helpConfig?.rich ? (
                            <span
                              style={{
                                color: '#FF5750',
                                fontSize: 12,
                                marginLeft: 8,
                                cursor: 'pointer',
                              }}
                              onClick={() => handleShowModal(field.helpConfig.rich)}
                            >
                              {field.helpConfig.rich.title}
                            </span>
                          ) : null}
                        </>
                      ) : null
                    }
                  >
                    {renderFormField(field, currentForm)}
                  </Form.Item>
                );
              })}

              <Form.Item style={{ marginBottom: 16 }}>
                <div className={style.formActions}>
                  {onBackStep && (
                    <Button className={style.backActionButton} onClick={onBackStep}>
                      上一步
                    </Button>
                  )}
                  <Button className={style.submitActionButton} type="primary" htmlType="submit">
                    确认提交
                  </Button>
                </div>
              </Form.Item>
            </Form>
          </div>
        )}

        {/* 确认信息 */}
        {formState.values && (
          <div className={style.rightAnswer}>
            <div className={style.answerBtn}>确认提交</div>
          </div>
        )}

        {/* 总结信息 */}
        {formState.showSummary && (
          <>
            {item.summarySegments?.map((cs: ISegments) =>
              cs.type === 'audio' ? (
                <div className={style.confirmWrapper} key={cs.segmentId}>
                  <AudioContent audioData={cs} />
                </div>
              ) : cs.type === 'file' ? (
                <div className={style.link} key={cs.segmentId}>
                  <div className={style.answerBtn}>
                    <LinkOutlined />
                    {cs.materialUrl}
                  </div>
                </div>
              ) : cs.type === 'image' ? (
                <div className={style.confirmWrapper} key={cs.segmentId}>
                  <img src={cs.materialUrl} alt={cs.content?.title} />
                </div>
              ) : null
            )}

            <div className={style.buttons}>
              {item.actions?.map(
                (btn: IActions) =>
                  btn.actionType === 'next' && (
                    <div
                      className={`${style.nextBtn} ${btn.actionType}`}
                      onClick={() => handleClickNextStep(item, allFormValues)}
                      key={btn.actionType}
                    >
                      <span>{btn.label}</span>
                      <img src={ReturnPng.src} alt="右箭头" />
                    </div>
                  )
              )}
            </div>
          </>
        )}
        <div
          ref={node => {
            summaryRefs.current[index] = node;
          }}
        ></div>
      </div>
    );
  };
  return (
    <div className={style.confirmGkInfoContainer}>
      {processedStepsData?.subSteps?.map((item, index) => renderStep(item, index))}
      <ModalImage
        imageUrl={currentImageUrl}
        isModalOpen={isModalOpen}
        setIsModalOpen={setIsModalOpen}
      />
    </div>
  );
};

export default PersonalInfoCollect;
