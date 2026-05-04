import React, { useEffect, useRef, useState } from 'react';
import { Modal, List, Steps, Select, Button, Space, Form, Input, Checkbox, message } from 'antd';
import { IUserInfoRes } from '@/interface/api/sessionDetail';

import style from './style.module.scss';
import StepsAct1 from '@/images/icons/steps1_active.png';
import Steps2 from '@/images/icons/steps2.png';
import StepsAct2 from '@/images/icons/steps2_active.png';
import SelectOption from '../selectOption';
import useForm from '@/pageComponents/session/ModalForm/useForm';
import { getProvinceLists, getSubjectPolicy, getYearList } from '@/service/apis/sessionDetail';
import { updateUserInfoApi } from '@/service/apis/user';
import { navigateTo } from '@/utils/router';
import { EStorageKey, setStorage } from '@/utils/tool';

interface UserInfoModalProps {
  visible: boolean;
  onCancel: () => void;
  userInfoFromlData: any;
}
const sexOptions = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
];

const UserInfoModal: React.FC<UserInfoModalProps> = ({ visible, onCancel, userInfoFromlData }) => {
  const [form] = Form.useForm();
  const [currentStep, setCurrentStep] = useState(0);
  const [provinceList, setProvinceList] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [yearList, setYearList] = useState<any[]>([]);
  const [isFormComplete, setIsFormComplete] = useState<boolean>(false); // 新增状态
  const isSubjectTypeRef = useRef<boolean>(false); // 是否展示科目类型
  const prepareTypeRef = useRef<any>();

  const {
    setSelectedSecondSubject,
    setSelectedFirstSubject,
    setSelectedArtsOrSciences,
    memberScoreByType,
    setSubjectType,
    subjectSelectConfig,
    policy,
    getParams,
  } = useForm(form);
  // 监听表单字段变化
  const onFieldsChange = () => {
    checkFormCompletion();
  };

  // 检查表单完成状态
  const checkFormCompletion = () => {
    const values = form.getFieldsValue();

    // 检查第一步的必填字段
    const step1Complete = values.areaId && values.examYear;

    // 检查第二步的必填字段
    const step2Complete = values.sex; // 根据实际情况添加更多检查

    if (currentStep === 0) {
      setIsFormComplete(step1Complete);
    } else if (currentStep === 1) {
      setIsFormComplete(step1Complete && step2Complete);
    }
  };

  // 自定义关闭处理函数
  const handleCancel = () => {
    if (isFormComplete) {
      onCancel();
    } else {
      message.warning('请先完成所有必填信息的填写');
    }
  };

  // 在步骤切换时也检查完成状态
  useEffect(() => {
    checkFormCompletion();
  }, [currentStep]);
  // 清空科目
  const clearSubject = (val?: boolean) => {
    // 清空相关字段
    form.setFieldsValue({
      subject: '',
      grades: '',
      totalScore: '',
      batch: '',
    });
    // 清空科目成绩
    // scoreFormRef.current?.form.setFieldsValue({
    //   grades1: '',
    //   grades2: '',
    //   grades3: '',
    //   grades4: '',
    //   grades5: '',
    //   grades6: '',
    // });
    // subject && setSubject('');
    // grades && setGrades('');
    // totalScore && setTotalScore(undefined);
    val && setSubjectType(undefined);
    setSelectedSecondSubject([]);
    setSelectedFirstSubject([]);
    setSelectedArtsOrSciences([]);
    isSubjectTypeRef.current = false;
  };

  // 性别变化
  const sexChange = async (value: string) => {
    // 只需要更新表单值
    form.setFieldsValue({ sex: value });
  };

  // 省份变化
  const provinceChange = async (areaId: string) => {
    const { code, data } = await getSubjectPolicy(areaId);
    if (code === 0 && data) {
      clearSubject();
      policy.current = data.policy;
      isSubjectTypeRef.current = true;
      memberScoreByType(data);
      prepareTypeRef.current = data.prepareType;
    }
  };

  // 省份
  const getProvinceList = async () => {
    const { code, data } = await getProvinceLists();
    if (code === 0 && data) {
      setProvinceList(data);
    }
  };
  // 年份
  const yearListHandle = async () => {
    const { code, data } = await getYearList();
    if (code === 0 && data) {
      const yearList = data.examYearList.map((year: any) => ({ label: year, value: year }));
      setYearList(yearList);
    }
  };

  const handleVerify = () => {
    const params = getParams();
    form
      .validateFields()
      .then(async (values: any) => {
        // 再次确认所有字段值
        const allFieldsAfterValidate = form.getFieldsValue(true);
        const { areaId, examYear, totalScore } = allFieldsAfterValidate;
        const sexValue = form.getFieldValue('sex');
        const selectedOption = sexOptions.find(opt => opt.value === sexValue);

        const provinceValue = form.getFieldValue('areaId');
        const selectedProvinceOption = provinceList.find(opt => opt.code === provinceValue);

        const infoParams = {
          userName: userInfoFromlData?.userName,
          avatarUrl: userInfoFromlData?.avatarUrl,
          userScoreOb: {
            examYear,
            sex: selectedOption
              ? {
                  code: selectedOption.value,
                  name: selectedOption.label,
                }
              : null,
            province: selectedProvinceOption
              ? {
                  code: selectedProvinceOption.code,
                  name: selectedProvinceOption.label,
                }
              : null,
            subjectList: params.subjectMapList,
            subjectType: params.subjectTypeObject,
          },
        };
        console.log('验证后的所有字段:', infoParams);
        setIsLoading(true);
        try {
          const { code, data, msg } = await updateUserInfoApi(infoParams);
          if (code === 0) {
            message.success('完善信息成功');
            form.resetFields();
            setStorage([
              {
                key: 'userInfo',
                value: JSON.stringify(data),
              },
            ]);
            setStorage([
              {
                key: EStorageKey.HASADDINFO,
                value: data.hasAddInfo,
              },
              {
                key: EStorageKey.ISCUSTOMER,
                value: data.isCustomer,
              },
            ]);
            onCancel();
          } else {
            message.error('完善信息失败');
          }
        } catch (error) {
          message.error('请求失败，请稍后重试');
          setIsLoading(false);
        }
      })
      .catch(error => {
        console.log('表单验证失败:', error);
        console.log('错误详情:', error.errorFields);
      });
  };

  useEffect(() => {
    yearListHandle();
    getProvinceList();
  }, []);
  const steps = [
    {
      title: '省份及年份',
      content: (
        <div>
          <div style={{ marginBottom: '24px' }}>
            <Form.Item key="areaId" label="高考省份" name="areaId" rules={[{ required: true }]}>
              <Select
                placeholder="请选择高考省份"
                fieldNames={{
                  label: 'label',
                  value: 'code',
                }}
                popupClassName="userModalPopup"
                options={provinceList}
                onChange={provinceChange}
              />
            </Form.Item>
          </div>
          <div style={{ marginBottom: '24px' }}>
            <Form.Item key="examYear" label="高考年份" name="examYear" rules={[{ required: true }]}>
              <Select
                options={yearList}
                placeholder="请选择您参加的高考年份"
                popupClassName="userModalPopup"
              />
            </Form.Item>
          </div>

          <Button
            type="primary"
            size="large"
            block
            onClick={() => setCurrentStep(1)}
            disabled={!form.getFieldValue('areaId') && !form.getFieldValue('examYear')}
            style={{ marginTop: '110px' }}
          >
            下一步
          </Button>
        </div>
      ),
    },
    {
      title: '科目及成绩',
      content: (
        <div>
          <SelectOption selectConfig={subjectSelectConfig} formDisabled={false} />
          <div style={{ marginBottom: '24px', color: '#999' }}>
            {/* <Form.Item
              key="totalScore"
              label="高考成绩"
              name="totalScore"
              rules={[{ required: true }]}
            >
              <div>
                <Input value={totalScore} placeholder="请输入" />
              </div>
            </Form.Item> */}
            <Form.Item key="sex" label="性别" name="sex" rules={[{ required: true }]}>
              <Select placeholder="请输入性别" options={sexOptions} onChange={sexChange} />
            </Form.Item>
          </div>
          <div className="buttonGroup">
            <Button onClick={() => setCurrentStep(0)} size="large">
              上一步
            </Button>
            <Button type="primary" size="large" onClick={handleVerify} loading={isLoading}>
              完成
            </Button>
          </div>
        </div>
      ),
    },
  ];

  const customIcons = [
    <img key="0" src={StepsAct1.src} alt="步骤1" style={{ width: 24, height: 24 }} />,
    <img
      key="1"
      src={currentStep >= 1 ? StepsAct2.src : Steps2.src}
      alt="步骤2"
      style={{ width: 24, height: 24 }}
    />,
  ];
  return (
    <Modal
      title="完善您的高考信息"
      open={visible}
      maskClosable={false}
      // onCancel={onCancel}
      onCancel={handleCancel} // 使用自定义的关闭处理函数
      footer={null}
      width={420}
      centered={true}
      className={style.userInfoModal}
      closable={isFormComplete} // 只有表单完成时才显示关闭按钮
    >
      <div className={style.subTitle}>高考信息决定了各大高校的招生政策，请认真填写</div>
      <div className={style.stepContainer}>
        <Steps
          current={currentStep}
          labelPlacement="vertical"
          items={[
            {
              title: (
                <span
                  style={{
                    color: currentStep >= 0 ? '#A38BEE' : ' rgb(163, 139, 238, 0.5)',
                    fontSize: '12px',
                    fontWeight: 'normal',
                  }}
                >
                  省份及年份
                </span>
              ),
              icon: customIcons[0],
            },
            {
              title: (
                <span
                  style={{
                    color: currentStep >= 1 ? '#A38BEE' : ' rgb(163, 139, 238, 0.5)',
                    fontSize: '12px',
                    fontWeight: 'normal',
                  }}
                >
                  科目及成绩
                </span>
              ),
              icon: customIcons[1],
            },
          ]}
        />
      </div>
      <div className={style.stepsContent}>
        <Form form={form} className={style.searchForm} onFieldsChange={onFieldsChange}>
          {steps[currentStep].content}
        </Form>
      </div>
    </Modal>
  );
};

export default UserInfoModal;
