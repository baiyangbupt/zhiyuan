import AudioContent from '@/pageComponents/customerDetail/Components/AudioContent';
import style from './style.module.scss';
import { Button, Form, Select } from 'antd';
import { IActions, ICollectflowRes, ISegments, ISubSteps } from '@/interface/api/customerDetail';
import { useEffect, useRef, useState } from 'react';
import ReturnPng from '@/images/icons/return.png';
import { LinkOutlined } from '@ant-design/icons';
import ModalImage from '../../Components/ModalImage';

interface ICollectflowProps {
  stepsData: ICollectflowRes;
  onNextStep: (btn: IActions, formValues?: any) => void;
  onDraftChange?: (formValues?: any) => void;
  onBackStep?: () => void;
  savedValues?: any;
}
const ConfirmGkInfo = (props: ICollectflowProps) => {
  const { stepsData, onNextStep, onDraftChange, onBackStep, savedValues } = props;
  const [form] = Form.useForm();
  const [isNextConfirmBtn, setIsNextConfirmBtn] = useState(false);
  const [formValues, setFormValues] = useState<any>(null); // 存储表单提交的值
  const [showSummary, setShowSummary] = useState(false); // 控制总结信息的显示

  const [currentImageUrl, setCurrentImageUrl] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  const scrollRef = useRef<HTMLDivElement>(null);

  // 构建初始值
  const getInitialValues = () => {
    const initialValues: any = {};

    stepsData?.subSteps?.forEach(item => {
      if (item.formConfig?.fields) {
        item.formConfig.fields.forEach(field => {
          initialValues[field.fieldId] = field.defaultValue;
        });
      }
    });

    return initialValues;
  };

  const getSavedFormValues = () => {
    const values: any = {};
    if (savedValues?.examYear !== undefined) values.examYear = String(savedValues.examYear);
    if (savedValues?.province?.code) values.examProvince = savedValues.province.code;
    return values;
  };

  const getMergedInitialValues = () => ({
    ...getInitialValues(),
    ...getSavedFormValues(),
  });

  const [province, setProvince] = useState<any>(null);

  useEffect(() => {
    const savedFormValues = getSavedFormValues();
    const hasSavedFormValues = Boolean(savedFormValues.examYear && savedFormValues.examProvince);
    const mergedInitialValues = getMergedInitialValues();

    form.resetFields();
    form.setFieldsValue(mergedInitialValues);
    setFormValues(hasSavedFormValues ? savedFormValues : null);
    setShowSummary(hasSavedFormValues);
    setIsNextConfirmBtn(false);
    if (savedValues?.province) {
      setProvince(savedValues.province);
    } else {
      setProvince(null);
    }
  }, [stepsData, savedValues]);

  const onFinish = (values: any) => {
    // 保存表单值
    setFormValues(values);
    // 查找字段的选项标签
    stepsData?.subSteps?.forEach(item => {
      if (item.formConfig?.fields) {
        const field = item.formConfig.fields.find(f => f.fieldId === 'examProvince');
        console.log('field', field);
        if (field?.options) {
          const option = field.options.find(opt => opt.code === values.examProvince);
          console.log('option', option);
          if (option) {
            setProvince(option);
            onDraftChange?.({
              examYear: values.examYear,
              province: option,
            });
          }
        }
      }
    });
    setShowSummary(true);
  };

  useEffect(() => {
    if (showSummary) {
      scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [showSummary]);

  const onFinishFailed = (errorInfo: any) => {
    const firstError = errorInfo?.errorFields?.[0];
    if (!firstError) return;
    form.scrollToField(firstError.name, {
      behavior: 'smooth',
      block: 'center',
    });
  };

  // 点击查看图片
  const handleShowModal = (rich: any) => {
    setCurrentImageUrl(rich.materialUrl);
    setIsModalOpen(true);
  };
  // 下一步
  const handleClickNextStep = (btn: IActions, item: ISubSteps) => {
    setIsNextConfirmBtn(true);
    const currentFormValues = formValues || form.getFieldsValue();
    console.log('下一步', currentFormValues, province);
    onNextStep(btn, {
      examYear: currentFormValues.examYear,
      province,
    });
  };
  // 生成确认信息文本
  const generateConfirmationText = () => {
    if (!formValues) return '';

    const texts: string[] = [];
    Object.keys(formValues).forEach(fieldId => {
      const value = formValues[fieldId];

      // 查找字段的选项标签
      stepsData?.subSteps?.forEach(item => {
        if (item.formConfig?.fields) {
          const field = item.formConfig.fields.find(f => f.fieldId === fieldId);
          if (field?.options) {
            console.log('fieldId', fieldId);
            const option = field.options.find(opt => opt.code === value);
            console.log('option', option);
            if (option) {
              texts.push(`${option.name}${fieldId === 'examYear' ? '高考' : ''}`);
            } else {
              texts.push(`${value}${fieldId === 'examYear' ? '高考' : ''}`);
            }
          }
        }
      });
    });
    console.log('texts', texts);
    return texts.join('，');
  };

  return (
    <div className={style.confirmGkInfoContainer}>
      {stepsData?.subSteps?.map(item => (
        <div className={style.confirmSubSteps} key={item.subStepId}>
          {item.contentSegments?.map((cs: ISegments) =>
            cs.type == 'audio' ? (
              <div className={style.confirmWrapper} key={cs.segmentId}>
                <AudioContent audioData={cs} />
              </div>
            ) : cs.type == 'image' ? (
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
            ) : (
              <div className={style.confirmWrapper} key={cs.segmentId}>
                <div className={style.confirmTitle}>{cs.content.title}</div>
                <div className={style.confirmMessage}> {cs.content.message}</div>
              </div>
            )
          )}
          {item.formConfig && (
            <div className={style.confirmForm}>
              <div className={style.title}>{item.formConfig.title}</div>
              <Form
                form={form}
                name="confirmForm"
                onFinish={onFinish}
                onFinishFailed={onFinishFailed}
                initialValues={getMergedInitialValues()}
                labelCol={{ flex: '110px' }}
                labelAlign="right"
                labelWrap
              >
                {item.formConfig.fields?.map(field => {
                  const fieldOptions = field.options || [];
                  const fieldHelpConfig = field.helpConfig;
                  return (
                    <Form.Item
                      key={field.fieldId}
                      label={field.fieldName}
                      name={field.fieldId}
                      rules={[{ required: field.required, message: field.validation?.required }]}
                      extra={
                        fieldHelpConfig ? (
                          <>
                            {fieldHelpConfig?.showFieldHelp ? (
                              <span style={{ color: '#919296', fontSize: 12 }}>
                                {fieldHelpConfig.helpText}
                              </span>
                            ) : null}
                            {fieldHelpConfig?.rich ? (
                              <span
                                style={{
                                  color: '#FF5750',
                                  fontSize: 12,
                                  marginLeft: 8,
                                  cursor: 'pointer',
                                }}
                                onClick={() => handleShowModal(fieldHelpConfig.rich)}
                              >
                                {fieldHelpConfig.rich.title}
                              </span>
                            ) : null}
                          </>
                        ) : null
                      }
                    >
                      <Select
                        options={fieldOptions.map(item => ({
                          label: item.name,
                          value: item.code,
                        }))}
                        disabled={!field.editable}
                      />
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
          {/* 确认信息 - 在表单提交后显示 */}
          {formValues && (
            <div className={style.rightAnswer}>
              <div className={style.answerBtn}>{generateConfirmationText()}</div>
            </div>
          )}

          {/* 总结信息 - 在确认信息显示后延迟显示 */}
          {showSummary && (
            <>
              {item.summarySegments?.map((cs: ISegments) =>
                cs.type == 'audio' ? (
                  <div className={style.confirmWrapper} key={cs.segmentId}>
                    <AudioContent audioData={cs} />
                  </div>
                ) : cs.type == 'image' ? (
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
                    )}{' '}
                  </div>
                ) : (
                  <div className={style.confirmWrapper} key={cs.segmentId}>
                    <div className={style.confirmTitle}>{cs.content.title}</div>
                    <div className={style.confirmMessage}> {cs.content.message}</div>
                  </div>
                )
              )}

              <div className={style.buttons}>
                {item.actions?.map(btn => (
                  <div
                    className={`${style.nextBtn} ${btn.actionType}`}
                    onClick={() => handleClickNextStep(btn, item)}
                    key={btn.actionType}
                  >
                    <span>{btn.label}</span>
                    <img src={ReturnPng.src} alt="右箭头" />
                  </div>
                ))}
                {isNextConfirmBtn && (
                  <div className={style.rightAnswer}>
                    <div className={style.answerBtn}>了解完成，继续下一步</div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      ))}
      <div ref={scrollRef} style={{ height: 10 }}></div>
      <ModalImage
        imageUrl={currentImageUrl}
        isModalOpen={isModalOpen}
        setIsModalOpen={setIsModalOpen}
      />
    </div>
  );
};

export default ConfirmGkInfo;
