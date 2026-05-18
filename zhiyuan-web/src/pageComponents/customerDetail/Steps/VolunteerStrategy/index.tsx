import AudioContent from '@/pageComponents/customerDetail/Components/AudioContent';
import style from './style.module.scss';
import { Button, Checkbox, Form, FormInstance, Input, Radio, Select, Spin } from 'antd';
import {
  IActions,
  ICollectflowRes,
  IScoreSubject,
  ISegments,
  ISubSteps,
} from '@/interface/api/customerDetail';
import { useEffect, useRef, useState } from 'react';
import ReturnPng from '@/images/icons/return.png';
import { LinkOutlined } from '@ant-design/icons';
import ModalImage from '../../Components/ModalImage';
const { Option } = Select;
const CheckboxGroup = Checkbox.Group;

// 策略卡片组件
interface StrategyCardProps {
  option: any;
  selected: boolean;
  disabled: boolean;
  onClick: () => void;
}

const StrategyCard: React.FC<StrategyCardProps> = ({ option, selected, disabled, onClick }) => {
  const { chartConfig, advantages, disadvantages } = option;
  const total = (chartConfig?.rush || 0) + (chartConfig?.stable || 0) + (chartConfig?.secure || 0);
  
  // 计算圆形图表的路径
  const getCirclePath = (): string[] => {
    if (!total) return [];
    const radius = 42;
    const centerX = 50;
    const centerY = 50;
    
    const rushRatio = (chartConfig?.rush || 0) / total;
    const stableRatio = (chartConfig?.stable || 0) / total;
    const secureRatio = (chartConfig?.secure || 0) / total;
    
    const rushAngle = rushRatio * 360;
    const stableAngle = stableRatio * 360;
    const secureAngle = secureRatio * 360;
    
    let currentAngle = -90; // 从顶部开始
    
    const paths: string[] = [];
    
    // 冲（红色）
    if (rushAngle > 0) {
      const startAngle = (currentAngle * Math.PI) / 180;
      const endAngle = ((currentAngle + rushAngle) * Math.PI) / 180;
      const x1 = centerX + radius * Math.cos(startAngle);
      const y1 = centerY + radius * Math.sin(startAngle);
      const x2 = centerX + radius * Math.cos(endAngle);
      const y2 = centerY + radius * Math.sin(endAngle);
      const largeArc = rushAngle > 180 ? 1 : 0;
      paths.push(
        `M ${centerX} ${centerY} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`
      );
      currentAngle += rushAngle;
    }
    
    // 稳（绿色）
    if (stableAngle > 0) {
      const startAngle = (currentAngle * Math.PI) / 180;
      const endAngle = ((currentAngle + stableAngle) * Math.PI) / 180;
      const x1 = centerX + radius * Math.cos(startAngle);
      const y1 = centerY + radius * Math.sin(startAngle);
      const x2 = centerX + radius * Math.cos(endAngle);
      const y2 = centerY + radius * Math.sin(endAngle);
      const largeArc = stableAngle > 180 ? 1 : 0;
      paths.push(
        `M ${centerX} ${centerY} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`
      );
      currentAngle += stableAngle;
    }
    
    // 保（蓝色）
    if (secureAngle > 0) {
      const startAngle = (currentAngle * Math.PI) / 180;
      const endAngle = ((currentAngle + secureAngle) * Math.PI) / 180;
      const x1 = centerX + radius * Math.cos(startAngle);
      const y1 = centerY + radius * Math.sin(startAngle);
      const x2 = centerX + radius * Math.cos(endAngle);
      const y2 = centerY + radius * Math.sin(endAngle);
      const largeArc = secureAngle > 180 ? 1 : 0;
      paths.push(
        `M ${centerX} ${centerY} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`
      );
    }
    
    return paths;
  };

  const paths = getCirclePath();
  const rushRatio = chartConfig?.rush || 0;
  const stableRatio = chartConfig?.stable || 0;
  const secureRatio = chartConfig?.secure || 0;

  return (
    <div
      className={`${style.strategyCard} ${selected ? style.strategyCardSelected : ''} ${disabled ? style.strategyCardDisabled : ''}`}
      onClick={disabled ? undefined : onClick}
    >
      <div className={style.strategyCardContent}>
        {/* 左侧圆形图表 */}
        <div className={style.strategyChart}>
          <svg width="100" height="100" viewBox="0 0 100 100" style={{ pointerEvents: 'none' }}>
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke="#E5E5E5"
              strokeWidth="6"
            />
            {paths.map((path: string, index: number) => {
              let color = '#FF5750'; // 默认红色（冲）
              if (index === 1) color = '#52C41A'; // 绿色（稳）
              if (index === 2) color = '#1890FF'; // 蓝色（保）
              return (
                <path
                  key={index}
                  d={path}
                  fill={color}
                  stroke="none"
                />
              );
            })}
            <text
              x="50"
              y="50"
              textAnchor="middle"
              dominantBaseline="middle"
              fill="#fff"
              fontSize="12"
              fontWeight="500"
            >
              {option.name}
            </text>
          </svg>
        </div>
        
        {/* 右侧内容 */}
        <div className={style.strategyInfo}>
          {/* 比例文字 */}
          <div className={style.strategyRatio}>
            <span className={style.ratioLabel}>冲: 稳: 保 = </span>
            <span className={style.ratioValueRush}>{rushRatio}</span>
            <span className={style.ratioSeparator}>: </span>
            <span className={style.ratioValueStable}>{stableRatio}</span>
            <span className={style.ratioSeparator}>: </span>
            <span className={style.ratioValueSecure}>{secureRatio}</span>
          </div>
          
          {/* 优势 */}
          <div className={style.strategyAdvantage}>
            <span className={style.strategyLabel}>优势：</span>
            <span className={style.strategyText}>{advantages}</span>
          </div>
          
          {/* 劣势 */}
          <div className={style.strategyDisadvantage}>
            <span className={style.strategyLabel}>劣势：</span>
            <span className={style.strategyText}>{disadvantages}</span>
          </div>
        </div>
      </div>
    </div>
  );
};

interface StrategySelectorProps {
  value?: string;
  onChange?: (value: string) => void;
  options?: any[];
  editable?: boolean;
}

const StrategySelector: React.FC<StrategySelectorProps> = ({ value, onChange, options, editable = true }) => {
  return (
    <div className={style.strategyCardsContainer}>
      {options?.map((config: any) => (
        <StrategyCard
          key={config.code}
          option={config}
          selected={value === config.code}
          disabled={!editable}
          onClick={() => {
            if (!editable) return;
            onChange?.(config.code);
          }}
        />
      ))}
    </div>
  );
};

interface ICollectflowProps {
  stepsData: ICollectflowRes;
  onNextStep: (btn: IActions, formValues?: any) => void;
  onDraftChange?: (formValues?: any) => void;
  loading?: boolean;
  finalSubmitLoading?: boolean;
  setFinalSubmitLoading?: (flag: boolean) => void;
  onBackStep?: () => void;
  savedValues?: any;
}

interface IFormState {
  values: any;
  showSummary: boolean;
  processFlag: boolean;
}

const VolunteerStrategy = (props: ICollectflowProps) => {
  const {
    stepsData,
    onNextStep,
    onDraftChange,
    loading,
    finalSubmitLoading,
    setFinalSubmitLoading,
    onBackStep,
    savedValues,
  } = props;
  const formsRef = useRef<FormInstance[]>([]);
  const [batchOptions] = useState<any>([]);
  const [formStates, setFormStates] = useState<IFormState[]>([]);
  const [totalScore] = useState(0);
  const [bonusPolicy] = useState(false);
  // 在组件顶部添加状态
  const [allFormValues, setAllFormValues] = useState<Record<number, any>>({});
  const [currentImageUrl, setCurrentImageUrl] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 构建初始值
  const getInitialValues = (subStep: any) => {
    const initialValues: any = {};
    if (subStep.formConfig?.fields) {
      subStep.formConfig.fields.forEach((field: any) => {
        initialValues[field.fieldId] = field.defaultValue;
      });
    }
    if (savedValues?.strategyType?.code) {
      initialValues.strategyType = savedValues.strategyType.code;
    }
    return initialValues;
  };

  const [strategyType, setStrategyType] = useState<any>(); // 志愿策略

  useEffect(() => {
    if (!savedValues?.strategyType?.code) return;
    stepsData?.subSteps?.forEach((item, index) => {
      const field = item.formConfig?.fields?.find((f: any) => f.fieldId === 'strategyType');
      const option = field?.options?.find((opt: any) => opt.code === savedValues.strategyType.code);
      if (option) {
        setStrategyType(option);
        setAllFormValues(prev => ({
          ...prev,
          [index]: { strategyType: option.code, subStepId: item.subStepId },
        }));
        formsRef.current[index]?.setFieldsValue({ strategyType: option.code });
      }
    });
  }, [stepsData, savedValues]);

  const buildStrategyPayload = (item: ISubSteps, index: number, overrideValues?: any) => {
    const formValues =
      overrideValues ||
      formsRef.current[index]?.getFieldsValue?.() ||
      allFormValues[index] ||
      {};
    const strategyTypeValue = formValues.strategyType ?? strategyType;
    const strategyTypeOption =
      typeof strategyTypeValue === 'object'
        ? strategyTypeValue
        : item?.formConfig?.fields
            ?.find((field: any) => field.fieldId === 'strategyType')
            ?.options?.find((opt: any) => opt.code === strategyTypeValue);
    const strategyTypePayload = strategyTypeOption
      ? {
          code: strategyTypeOption.code,
          name: strategyTypeOption.name,
        }
      : null;
    return { strategyType: strategyTypePayload };
  };

  // 表单提交处理
  const handleFormFinish = (values: any, index: number, subStepId: string) => {
    console.log('表单提交处理', values, index, subStepId);
    const newFormStates = [...formStates];
    newFormStates[index] = {
      ...newFormStates[index],
      values,
      processFlag: true,
    };
    setFormStates(newFormStates);

    stepsData?.subSteps?.forEach(item => {
      if (item.formConfig?.fields) {
        const field = item.formConfig.fields.find((f: any) => f.fieldId === 'strategyType');
        console.log('field', field);
        if (field?.options && Array.isArray(field.options)) {
          const option = field.options.find((opt: any) => opt.code === values.strategyType);
          console.log('option', option);
          if (option) setStrategyType(option);
        }
      }
    });
    // 保存当前步骤的表单值
    setAllFormValues(prev => ({
      ...prev,
      [index]: { ...values, subStepId },
    }));
    const item = stepsData?.subSteps?.find(subStep => subStep.subStepId === subStepId);
    if (item) {
      onDraftChange?.(buildStrategyPayload(item, index, values));
    }

    const updatedStates = [...newFormStates];
    updatedStates[index] = {
      ...updatedStates[index],
      showSummary: true,
    };
    setFormStates(updatedStates);

    setTimeout(() => {
      scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, 50);
  };

  // 下一步处理
  const handleClickNextStep = (btn: IActions, item: ISubSteps, index: number) => {
    const payload = buildStrategyPayload(item, index, formStates[index]?.values);
    setFinalSubmitLoading?.(true);
    onNextStep(btn, payload);
  };
  // 点击查看图片
  const handleShowModal = (rich: any) => {
    setCurrentImageUrl(rich.materialUrl);
    setIsModalOpen(true);
  };

  const scrollToFirstErrorField = (errorInfo: any, index: number) => {
    const firstError = errorInfo?.errorFields?.[0];
    if (!firstError) return;
    formsRef.current[index]?.scrollToField(firstError.name, {
      behavior: 'smooth',
      block: 'center',
    });
  };

  // 渲染表单字段
  const renderFormField = (field: any) => {
    switch (field.fieldType) {
      case 'mutiSelect':
        return field.mutiSelectType === 'subjectList' || field.fieldId === 'strengthSubjectList' ? (
          <CheckboxGroup defaultValue={field.defaultValue}>
            {field.options?.map((config: any) => (
              <Checkbox key={config.subject} disabled={!field.editable} value={config.subject}>
                {config.subjectName}
              </Checkbox>
            ))}
          </CheckboxGroup>
        ) : (
          <CheckboxGroup defaultValue={field.defaultValue}>
            {field.options?.map((config: any) => (
              <Checkbox key={config.code} disabled={!field.editable} value={config.code}>
                {config.name}
              </Checkbox>
            ))}
          </CheckboxGroup>
        );

      case 'radio':
        if (field.fieldId === 'ethnicity') {
          return <Select options={field.options} disabled={!field.editable} />;
        } else if (field.fieldId === 'strategyType') {
          return <StrategySelector options={field.options} editable={field.editable} />;
        } else {
          return (
            <Radio.Group defaultValue={field.defaultValue}>
              {field.options?.map((config: any) => (
                <Radio.Button key={config.code} value={config.code} disabled={!field.editable}>
                  {config.name}
                </Radio.Button>
              ))}
            </Radio.Group>
          );
        }

      case 'scoreMutiInput':
        return (
          <div className="scoreSubject">
            {field.inputList.map((inp: IScoreSubject) => (
              <Form.Item
                key={inp.subject}
                name={`subjectScoreList-${inp.subjectName}-${inp.subject}`}
                style={{ marginBottom: 0 }}
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
              >
                <Input placeholder={inp.label} disabled={!field.editable} />
              </Form.Item>
            ))}
          </div>
        );

      default:
        if (field.fieldId === 'bonusScore') {
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
              {cs.expand ? (
                <img src={cs.materialUrl} alt={cs.content?.title} />
              ) : (
                <span
                  style={{
                    color: '#4984FA',
                    fontSize: 12,
                    cursor: 'pointer',
                    padding: 10,
                    background: '#fff',
                    borderRadius: 8,
                  }}
                  onClick={() => handleShowModal(cs)}
                >
                  {cs.content?.title}
                </span>
              )}
            </div>
          ) : null
        )}

        {/* 表单部分 */}
        {item.formConfig && (
          <div className={style.confirmForm}>
            <div className={style.title}>{item.formConfig.title}</div>
            <Form
              ref={(formInstance: FormInstance | null) => {
                if (formInstance) {
                  formsRef.current[index] = formInstance;
                }
              }}
              name={`confirmForm-${index}`}
              onFinish={values => handleFormFinish(values, index, item.subStepId)}
              onFinishFailed={errorInfo => scrollToFirstErrorField(errorInfo, index)}
              initialValues={getInitialValues(item)}
              labelCol={{ flex: '110px' }}
              labelAlign="right"
              labelWrap
            >
              {item.formConfig.fields?.map((field: any) => (
                <Form.Item
                  key={field.fieldId}
                  // label={field.fieldName}
                  label={
                    <>
                      <div>{field.fieldName}</div>
                      {field.helpConfig && field.helpConfig?.position == 'top' && (
                        <div style={{ fontSize: 12 }}>{field.helpConfig?.helpText}</div>
                      )}
                    </>
                  }
                  name={field.fieldId}
                  rules={[{ required: field.required, message: field.validation?.required }]}
                  {...(field.helpConfig && !field.helpConfig?.position && (field.helpConfig?.showFieldHelp || field.helpConfig?.rich) ? {
                    extra: (
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
                    )
                  } : {})}
                >
                  {renderFormField(field)}
                </Form.Item>
              ))}

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
                  {cs.expand ? (
                    <img src={cs.materialUrl} alt={cs.content?.title} />
                  ) : (
                    <span
                      style={{
                        color: '#4984FA',
                        fontSize: 12,
                        cursor: 'pointer',
                        padding: 10,
                        background: '#fff',
                        borderRadius: 8,
                      }}
                      onClick={() => handleShowModal(cs)}
                    >
                      {cs.content?.title}
                    </span>
                  )}
                </div>
              ) : null
            )}
          </>
        )}

        {formState.showSummary && (
          <div className={style.buttons}>
            {item.actions?.map(
              (btn: IActions) =>
                btn.actionType === 'finalSubmit' && (
                  <Spin
                    spinning={loading || finalSubmitLoading}
                    key={btn.actionType}
                    tip="正在提交，请稍候..."
                  >
                    <div
                      className={`${style.nextBtn} ${btn.actionType} ${loading || finalSubmitLoading ? style.nextBtnDisabled : ''}`}
                      onClick={
                        loading || finalSubmitLoading
                          ? undefined
                          : () => handleClickNextStep(btn, item, index)
                      }
                    >
                      <span>了解完成，继续下一步</span>
                      <img src={ReturnPng.src} alt="右箭头" />
                    </div>
                  </Spin>
                )
            )}
          </div>
        )}
      </div>
    );
  };
  return (
    <div className={style.confirmGkInfoContainer}>
      {stepsData?.subSteps?.map((item, index) => renderStep(item, index))}
      <div ref={scrollRef} style={{ height: 10 }}></div>
      <ModalImage
        imageUrl={currentImageUrl}
        isModalOpen={isModalOpen}
        setIsModalOpen={setIsModalOpen}
      />
    </div>
  );
};

export default VolunteerStrategy;
