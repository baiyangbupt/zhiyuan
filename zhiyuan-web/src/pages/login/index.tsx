import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import { Form, Input, Button, Typography, Spin, message, Tabs, Checkbox, Modal } from 'antd';
import {
  UserOutlined,
  LockOutlined,
  MobileOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import style from './style.module.scss';
import LoginImg from '@/images/login/login.png';
import LoginVectorImg from '@/images/login/vector.png';
import { ILoginMobileParams, ILoginParams } from '@/interface/api/user';
import {
  getLoginByTokenApi,
  getUserInfoApi,
  loginApi,
  loginMobileApi,
  sendCodeApi,
} from '@/service/apis/user';
import { setStorage, EStorageKey, clearStorage } from '@/utils/tool';
import { navigateTo, replaceTo } from '@/utils/router';
import { CheckboxChangeEvent } from 'antd/lib/checkbox/Checkbox';

const { Title, Text } = Typography;

const navigateAfterLogin = (isCustomer: boolean, replace: boolean = false) => {
  const targetPath = isCustomer ? '/customer' : '/session';
  const query = isCustomer ? { openSessionList: 1 } : undefined;
  if (replace) {
    replaceTo(targetPath, query);
    return;
  }
  navigateTo(targetPath, query);
};

const Index: React.FC = () => {
  const [form] = Form.useForm();
  const [smsForm] = Form.useForm();
  const [isLoading, setIsLoading] = useState(false); // 登陆按钮loading
  const [smsLoading, setSmsLoading] = useState(false); // 发送短信按钮loading
  const [countdown, setCountdown] = useState(0);
  const [activeTab, setActiveTab] = useState('1');
  const [isRemember, setIsRemember] = useState(false); // 记住密码
  const [isAgreed, setIsAgreed] = useState(false); // 是否同意协议
  const [shouldShake, setShouldShake] = useState(false); // 是否触发抖动
  const [isModalVisible, setIsModalVisible] = useState(false); // Modal 显示状态
  const [modalMessage, setModalMessage] = useState(''); // Modal 消息内容
  const [isSilentLogin, setIsSilentLogin] = useState(false); // 是否是静默登录（从其他页面跳转）

  // ✅ 新增：表单校验状态
  const [isSmsFormValid, setIsSmsFormValid] = useState(false);
  const [isPwdFormValid, setIsPwdFormValid] = useState(false);

  useEffect(() => {
    // localStorage.clear();
    clearStorage([
      EStorageKey.TOKEN,
      EStorageKey.BOT_ID,
      EStorageKey.TENANT_ID,
      EStorageKey.HASADDINFO,
      EStorageKey.ISCUSTOMER,
      EStorageKey.CHANNEL,
      EStorageKey.SOURCE,
      'userInfo',
      'infoSummary',
    ]);
  }, []);

  // 获取用户信息
  const getUserInfo = async () => {
    try {
      const { code, data } = await getUserInfoApi();
      if (code === 0 && data) {
        setStorage([{ key: 'userInfo', value: JSON.stringify(data) }]);
      } else {
        message.error('获取用户信息失败');
      }
    } catch (error) {
      message.error('获取用户信息失败');
    }
  };

  // ✅ 新增：URL token 登录逻辑
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const channel = params.get('channel') || 'gaotu';
    const token = params.get('token');
    const source = params.get('source');

    if (channel && token) {
      setIsSilentLogin(true); // 设置静默登录状态
      autoLoginByToken(channel, token, source);
    }
  }, []);

  // ✅ 自动登录方法
  const autoLoginByToken = async (channel: string, token: string, source?: string | null) => {
    setIsLoading(true);
    try {
      const { code, data, msg } = await getLoginByTokenApi({ channel, token });
      console.log('msg', msg);
      if (code === 0 && data) {
        // 登录成功，存储信息
        const storageItems: { key: EStorageKey | string; value: unknown }[] = [
          { key: EStorageKey.TOKEN, value: data.loginToken },
          { key: EStorageKey.BOT_ID, value: data.botId },
          { key: EStorageKey.TENANT_ID, value: data.tenantId },
          { key: EStorageKey.HASADDINFO, value: data.hasAddInfo },
          { key: EStorageKey.ISCUSTOMER, value: data.isCustomer },
          { key: EStorageKey.CHANNEL, value: data.channel },
        ];
        if (source) {
          storageItems.push({ key: EStorageKey.SOURCE, value: source });
        }
        setStorage(storageItems);
        message.success('登录成功！');
        await getUserInfo();
        navigateAfterLogin(data.isCustomer, true);
      } else {
        handleLoginFail(channel, msg);
      }
    } catch (error) {
      handleLoginFail(channel, '权益校验失败，请重新登录');
    } finally {
      setIsLoading(false);
    }
  };

  // ✅ 登录失败处理
  const handleLoginFail = (channel: string, msg: string) => {
    if (channel === 'gaotu') {
      setModalMessage(msg || '权益校验失败，请重新登录');
      setIsModalVisible(true);
    }
  };

  // ✅ 处理 Modal 确认按钮点击
  const handleModalConfirm = () => {
    setIsModalVisible(false);
    window.location.href = 'https://www.gaotuzhiyuan.com';
  };

  // 倒计时效果
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (countdown > 0) {
      timer = setTimeout(() => setCountdown(countdown - 1), 1000);
    }
    return () => clearTimeout(timer);
  }, [countdown]);

  // 抖动效果结束后重置状态
  useEffect(() => {
    if (shouldShake) {
      const timer = setTimeout(() => {
        setShouldShake(false);
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [shouldShake]);

  // ✅ 新增：表单校验函数
  const checkFormValid = (
    formInstance: any,
    setValid: React.Dispatch<React.SetStateAction<boolean>>
  ) => {
    const values = formInstance.getFieldsValue();
    const hasError = formInstance.getFieldsError().some(({ errors }: any) => errors.length);
    const allFilled = Object.values(values).every(value => value !== undefined && value !== '');
    setValid(allFilled && !hasError);
  };

  // 记住密码
  const onChangRemember = (e: CheckboxChangeEvent) => {
    setIsRemember(e.target.checked);
  };

  // 处理协议勾选变化
  const onChangAgree = (e: CheckboxChangeEvent) => {
    setIsAgreed(e.target.checked);
    if (e.target.checked) {
      setShouldShake(false);
    }
  };

  // 检查协议是否同意
  const checkAgreement = () => {
    if (!isAgreed) {
      setShouldShake(true);
      message.warning('请先阅读并同意用户协议和隐私政策');
      return false;
    }
    return true;
  };

  // 账号密码登录
  const onPasswordFinish = async (values: ILoginParams) => {
    if (!checkAgreement()) return;
    setIsLoading(true);
    try {
      const { data, code } = await loginApi(values);
      if (code === 0 && data) {
        setStorage([
          { key: EStorageKey.TOKEN, value: data.loginToken },
          { key: EStorageKey.BOT_ID, value: data.botId },
          { key: EStorageKey.TENANT_ID, value: data.tenantId },
          { key: EStorageKey.HASADDINFO, value: data.hasAddInfo },
          { key: EStorageKey.ISCUSTOMER, value: data.isCustomer },
        ]);
        message.success('登录成功！');
        setTimeout(() => {
          getUserInfo().then(() => {
            navigateAfterLogin(data.isCustomer);
          });
        }, 100);
      } else {
        message.error('登录失败，请检查用户名和密码');
      }
    } catch (error) {
      message.error('登录失败，请稍后重试');
    }
    setIsLoading(false);
  };

  // 发送短信验证码
  const sendSmsCode = async () => {
    try {
      const values = await smsForm.validateFields(['mobile']);
      setSmsLoading(true);
      const { code } = await sendCodeApi({ mobile: values.mobile });
      if (code === 0) {
        message.success('发送成功，请注意查收');
        setCountdown(60);
      } else {
        message.error('发送失败，请稍后重试');
      }
    } catch (error) {
      message.error('请输入正确的手机号');
    } finally {
      setSmsLoading(false);
    }
  };

  // 手机号登录
  const onSmsFinish = async (values: ILoginMobileParams) => {
    if (!checkAgreement()) return;
    setIsLoading(true);
    try {
      const { data, code } = await loginMobileApi(values);
      if (code === 0 && data) {
        console.log('data,手机号登录', data);
        setStorage([
          { key: EStorageKey.TOKEN, value: data.loginToken },
          { key: EStorageKey.BOT_ID, value: data.botId },
          { key: EStorageKey.TENANT_ID, value: data.tenantId },
          { key: EStorageKey.HASADDINFO, value: data.hasAddInfo },
          { key: EStorageKey.ISCUSTOMER, value: data.isCustomer },
        ]);
        message.success('登录成功！');
        setTimeout(() => {
          getUserInfo().then(() => {
            navigateAfterLogin(data.isCustomer);
          });
        }, 100);
      } else {
        message.error('登录失败，请检查手机号和验证码');
      }
    } catch (error) {
      message.error('登录失败，请稍后重试');
    }
    setIsLoading(false);
  };

  const onFinishFailed = (errorInfo: any) => {
    console.log('表单验证失败:', errorInfo);
  };

  const onChangeTab = (key: string) => {
    setActiveTab(key);
    key === '1' ? form.resetFields() : smsForm.resetFields();
  };

  return (
    <div className={style.loginWrapper}>
      <Head>
        <title>高途AI志愿填报-登录</title>
      </Head>
      <div className={style.loginContainer}>
        <div className={`${style.loginLeft} ${style.loginItem}`}>
          <div className={style.illustration}>
            <img src={LoginImg.src} alt="团队协作插图" className={style.illustrationImage} />
            <img src={LoginVectorImg.src} alt="云朵插图" className={style.vectorImage} />
          </div>
        </div>

        <div className={`${style.loginRight}  ${style.loginItem}`}>
          <div className={style.loginFormWrapper}>
            {isSilentLogin ? (
              <div style={{ textAlign: 'center', padding: '40px 20px' }}>
                <Spin size="large" />
                <div style={{ marginTop: '20px', fontSize: '16px', color: '#666' }}>
                  {isLoading ? '正在自动登录中，请稍候...' : '登录处理中，请稍候...'}
                </div>
              </div>
            ) : (
              <Tabs
                defaultActiveKey="1"
                onChange={onChangeTab}
                items={[
                  {
                    label: `手机号登录`,
                    key: '1',
                    children: (
                      <Form
                        form={smsForm}
                        name="smsLoginForm"
                        className={style.loginForm}
                        onFinish={onSmsFinish}
                        onFinishFailed={onFinishFailed}
                        layout="vertical"
                        size="large"
                        // onValuesChange={() => checkFormValid(smsForm, setIsSmsFormValid)} // ✅
                        onFieldsChange={() => {
                          const hasErrors = smsForm
                            .getFieldsError()
                            .some(field => field.errors.length > 0);
                          const allFilled =
                            smsForm.getFieldsValue(['mobile', 'verifyCode']).mobile &&
                            smsForm.getFieldsValue(['mobile', 'verifyCode']).verifyCode;
                          setIsSmsFormValid(allFilled && !hasErrors);
                        }}
                      >
                        <Form.Item
                          name="mobile"
                          rules={[
                            { required: true, message: '请输入手机号' },
                            { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号格式' },
                          ]}
                        >
                          <Input
                            prefix={<span className="inputPrefix">+86</span>}
                            placeholder="请输入手机号"
                            maxLength={11}
                          />
                        </Form.Item>

                        <Form.Item
                          name="verifyCode"
                          rules={[
                            { required: true, message: '请输入验证码' },
                            { len: 6, message: '验证码为6位数字' },
                          ]}
                        >
                          <Input
                            prefix={<SafetyCertificateOutlined className="inputPrefix" />}
                            placeholder="请输入验证码"
                            maxLength={6}
                            suffix={
                              <Button
                                type="link"
                                loading={smsLoading}
                                className="smsCode"
                                onClick={sendSmsCode}
                              >
                                {countdown > 0 ? `${countdown}秒重新获取` : '获取验证码'}
                              </Button>
                            }
                          />
                        </Form.Item>

                        <Form.Item>
                          <div className={style.tips}>新用户登录后自动创建账号</div>
                          <Button
                            type="primary"
                            htmlType="submit"
                            className={style.loginButton}
                            block
                            loading={isLoading}
                            disabled={!isSmsFormValid} // ✅ 这里
                          >
                            开启高途志愿
                          </Button>
                          <div className={`${style.agree} ${shouldShake ? style.shake : ''}`}>
                            <Checkbox checked={isAgreed} onChange={onChangAgree}>
                              我已阅读并同意<span className="redStyle">用户协议</span>和
                              <span className="redStyle">隐私政策</span>
                            </Checkbox>
                          </div>
                        </Form.Item>
                      </Form>
                    ),
                  },
                  {
                    label: `账号登录`,
                    key: '2',
                    children: (
                      <Form
                        form={form}
                        name="passwordLoginForm"
                        className={style.loginForm}
                        onFinish={onPasswordFinish}
                        onFinishFailed={onFinishFailed}
                        layout="vertical"
                        size="large"
                        // onValuesChange={() => checkFormValid(form, setIsPwdFormValid)} // ✅

                        onFieldsChange={() => {
                          const hasErrors = form
                            .getFieldsError()
                            .some(field => field.errors.length > 0);
                          const allFilled =
                            form.getFieldsValue(['userName', 'password']).userName &&
                            form.getFieldsValue(['userName', 'password']).password;
                          setIsPwdFormValid(allFilled && !hasErrors);
                        }}
                      >
                        <Form.Item
                          name="userName"
                          rules={[{ required: true, message: '请输入用户名' }]}
                        >
                          <Input prefix={<UserOutlined />} placeholder="请输入用户名" />
                        </Form.Item>

                        <Form.Item
                          name="password"
                          rules={[{ required: true, message: '请输入密码' }]}
                        >
                          <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" />
                        </Form.Item>

                        <Form.Item>
                          <div className={style.remember}>
                            <Checkbox onChange={onChangRemember}>记住密码</Checkbox>
                            <div className={style.forgetPwd}>忘记密码</div>
                          </div>
                          <Button
                            type="primary"
                            htmlType="submit"
                            className={style.loginButton}
                            block
                            loading={isLoading}
                            disabled={!isPwdFormValid} // ✅ 这里
                          >
                            开启高途志愿
                          </Button>
                          <div className={`${style.agree} ${shouldShake ? style.shake : ''}`}>
                            <Checkbox checked={isAgreed} onChange={onChangAgree}>
                              我已阅读并同意<span className="redStyle">用户协议</span>和
                              <span className="redStyle">隐私政策</span>
                            </Checkbox>
                          </div>
                        </Form.Item>
                      </Form>
                    ),
                  },
                ]}
              />
            )}
          </div>
        </div>
      </div>
      <Spin spinning={isLoading} fullscreen />

      {/* 登录失败提示 Modal */}
      <Modal
        title="温馨提示"
        open={isModalVisible}
        onOk={handleModalConfirm}
        onCancel={handleModalConfirm}
        okText="我已了解"
        cancelButtonProps={{ style: { display: 'none' } }}
        centered
      >
        <p>{modalMessage}</p>
      </Modal>
    </div>
  );
};

export default Index;
