import AudioContent from '@/pageComponents/customerDetail/Components/AudioContent';
import style from './style.module.scss';
import { Button, Checkbox, Form, Input, List, Radio, Select } from 'antd';
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
const { Option } = Select;
const CheckboxGroup = Checkbox.Group;

interface ICollectflowProps {
  stepsData: ICollectflowRes;
  onNextStep: (btn: IActions, formValues?: any) => void;
  userSubjectList: any;
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
  const [form] = Form.useForm();
  const formStrengthSubjectList = Form.useWatch('strengthSubjectList', form);
  const formColorSistuation = Form.useWatch('colorSistuation', form);
  const { stepsData, onNextStep, userSubjectList } = props;
  const stepsRef = useRef<ICollectflowRes>();
  stepsRef.current = stepsData;
  const formsRef = useRef<FormInstance[]>([]);
  const [isNextConfirmBtn, setIsNextConfirmBtn] = useState(false);
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
  const getInitialValues = (subStep: any) => {
    const initialValues: any = {};
    if (subStep.formConfig?.fields) {
      subStep.formConfig.fields.forEach((field: any) => {
        initialValues[field.fieldId] = field.defaultValue;
      });
    }
    return initialValues;
  };

  // 初始化表单状态和表单实例
  useEffect(() => {
    if (processedStepsData?.subSteps) {
      const initialStates = processedStepsData.subSteps.map(() => ({
        values: null,
        showSummary: false,
        processFlag: false,
      }));
      setFormStates(initialStates);

      processedStepsData.subSteps.forEach((subStep, index) => {
        const initValues = getInitialValues(subStep);
        if (formsRef.current[index]) {
          formsRef.current[index].setFieldsValue(initValues);
        }
      });

      // 初始化表单实例数组
      formsRef.current = new Array(processedStepsData.subSteps.length).fill(null);

      // 这里可以调用 provinceChange，因为现在有表单实例了
      if (userInfo) provinceChange();
    }
  }, [processedStepsData, userInfo]);

  const scrollRef = useRef<HTMLDivElement>(null);

  // 表单提交处理
  const handleFormFinish = (values: any, index: number, subStepId: string) => {
    const newFormStates = [...formStates];
    newFormStates[index] = {
      ...newFormStates[index],
      values,
      processFlag: true,
    };
    setFormStates(newFormStates);
    // 保存当前步骤的表单值
    const allValue = { ...allFormValues, [index]: { ...values, subStepId } };
    setAllFormValues(allValue);

    setTimeout(() => {
      const updatedStates = [...newFormStates];
      updatedStates[index] = {
        ...updatedStates[index],
        showSummary: false,
      };
      setFormStates(updatedStates);
      scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
      // 👉 判断是否是最后一个表单，如果是就直接下一步
      const isLastStep = index === (stepsRef.current?.subSteps.length ?? 0) - 1;
      if (isLastStep) {
        const btn = stepsRef.current?.subSteps[index].actions?.find(a => a.actionType === 'next');
        if (btn) {
          handleClickNextStep(stepsRef.current!.subSteps[index], allValue);
        }
      }
    }, 100);
  };

  const scrollToFirstErrorField = (errorInfo: any, index: number) => {
    const firstError = errorInfo?.errorFields?.[0];
    if (!firstError) return;
    const currentForm = formsRef.current[index] || form;
    currentForm?.scrollToField(firstError.name, {
      behavior: 'smooth',
      block: 'center',
    });
  };

  // 下一步处理
  const handleClickNextStep = (item: ISubSteps, values: Record<number, any>) => {
    // 合并所有已提交的表单值

    let transformedFormValues = Object.values(values).map(value => {
      const stepData = stepsRef.current?.subSteps.find(
        subStep => subStep.subStepId === value.subStepId
      );
      const fields = stepData?.formConfig?.fields || [];
      if (value.subStepId === 'personal_info_step1') {
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
          batch: batchOptions
            ?.filter(batch => batch.id === value.batch)
            .map(bat => {
              return {
                code: bat.batch,
                level: bat.level.key,
                pos: bat.pos ? Number(bat.pos) : undefined,
                score: bat.score ? parseFloat(bat.score) : undefined,
                name: `${bat.batchTitle}(批次线${+bat.score.slice(0, 5)}分)`,
              };
            })?.[0],
          prepareType: batchOptions
            ?.filter(batch => batch.id === value.batch)
            .map(bat => bat.prepareType)?.[0],
        };
      }
      if (item.subStepId === 'personal_info_step2') {
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
          specialPlan: value?.specialPlan === 'true' ? true : false,
        };
      }
    });
    const mergedValues = Object.assign({}, ...transformedFormValues);
    console.log('mergedValues', mergedValues);
    setIsNextConfirmBtn(true);

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
        // label: item.batchTitle,
        label: `${item.batchTitle}(批次线${+item.score.slice(0, 5)}分)`,
        value: item.id,
      }));
      form.setFieldValue('batch', list?.[0].id);
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
  const renderFormField = (field: any) => {
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
        if (form.getFieldValue('bonusPolicy') && field.fieldId === 'bonusScore') {
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

  // 渲染单个步骤
  const renderStep = (item: any, index: number) => {
    const formState = formStates[index] || { values: null, showSummary: false, processFlag: false };

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
              form={form}
              ref={formInstance => {
                formsRef.current[index] = formInstance;
              }}
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
                if (field.fieldId === 'bonusScore' && !form.getFieldValue('bonusPolicy')) {
                  return null;
                }
                return (
                  <Form.Item
                    key={field.fieldId}
                    label={field.fieldName}
                    name={field.fieldId}
                    initialValue={field.defaultValue}
                    rules={[
                      {
                        required: field.required,
                        message:
                          field.fieldId === 'subjectScoreList' ? '' : field.validation?.required,
                      },
                    ]}
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
                    {renderFormField(field)}
                  </Form.Item>
                );
              })}

              <Form.Item wrapperCol={{ offset: 7 }} style={{ marginBottom: 16 }}>
                <Button type="primary" htmlType="submit" block>
                  确认提交
                </Button>
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

              {isNextConfirmBtn && (
                <div className={style.rightAnswer}>
                  <div className={style.answerBtn}>了解完成，继续下一步</div>
                </div>
              )}
            </div>
          </>
        )}
        <div ref={scrollRef}></div>
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
