import React, { use, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Head from 'next/head';
import {
  Modal,
  List,
  Steps,
  Select,
  Button,
  Space,
  Form,
  Input,
  Checkbox,
  message,
  Upload,
  Radio,
  Tabs,
  Spin,
} from 'antd';
import dayjs from 'dayjs';
import type { UploadChangeParam } from 'antd/es/upload';
import type { RcFile, UploadFile, UploadProps } from 'antd/es/upload/interface';
import style from './style.module.scss';
import Header from '@/pageComponents/session/Header';
import useForm from '@/pageComponents/session/ModalForm/useForm';
import { getProvinceLists, getSubjectPolicy, getYearList } from '@/service/apis/sessionDetail';
import { getOssSignApi, getUserInfoApi, updateUserInfoApi } from '@/service/apis/user';
import { LoadingOutlined, PlusOutlined } from '@ant-design/icons';
import { EStorageKey, getStorage, getYuzhiToken, setStorage } from '@/utils/tool';
import {
  ISelectConfig,
  ISelectDataItem,
  ISelectTypeEnum,
  ISubjectItem,
  ISubjectList,
  ISubjectType,
} from '@/interface/api/updateBaseInfo';
import { navigateTo } from '@/utils/router';

const sexOptions = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
];

const USER_LEVEL_LABEL_MAP: Record<string, string> = {
  SUPER_VIP: '超级VIP',
  VIP: 'VIP',
  ORIGIN: '普通用户',
  DEFAULT: '普通用户',
};

const RIGHTS_DESCRIPTION_MAP: Record<
  string,
  {
    intro: string;
    privileges: string[];
    limitations: string[];
  }
> = {
  SUPER_VIP: {
    intro: '超级VIP享有全量志愿填报能力。',
    privileges: [
      '最多创建 50 次AI对话或志愿方案',
      '每个招生季最多可修改成绩信息 20 次',
      '高级数据对比分析与专属顾问服务',
    ],
    limitations: [
      '账号仅限本人使用',
      '超过次数需求可联系专属顾问处理',
      '到期后权限自动降级为普通用户',
    ],
  },
  VIP: {
    intro: 'VIP用户享有主要志愿服务功能，权益有效期 365 天。',
    privileges: [
      '最多创建 20 次AI对话或志愿方案',
      '最多可修改成绩信息 10 次'
    ],
    limitations: [
      '账号不可共享、不可多人同时使用',
      '超过次数需求可联系专属顾问处理',
      '到期后权限自动降级为普通用户',
    ],
  },
  ORIGIN: {
    intro: '普通用户可查看基础信息，智能填报需开通志愿服务权益。',
    privileges: [
      '基础志愿政策解读',
    ],
    limitations: [
      '智能填报需开通志愿服务权益后使用',
      '高级功能需开通VIP会员后使用',
    ],
  },
  DEFAULT: {
    intro: '该账号暂未开通会员权益，可体验基础功能。',
    privileges: [
      '每日最多创建 1 次 AI 对话或志愿方案',
      '基础志愿政策资讯浏览',
    ],
    limitations: [
      '高级功能暂不可用',
      '开通会员即可解锁更多权益',
    ],
  },
};

const UserCenter: React.FC = () => {
  const [form] = Form.useForm();
  const firstSubject = Form.useWatch('firstSubject', form);
  const secondSubject = Form.useWatch('secondSubject', form);
  const artsOrSciences = Form.useWatch('artsOrSciences', form);

  // isCustomer true-C端 false-B端

  // const storedIsCustomer = (getStorage('isCustomer') as boolean) || false;
  const [storedIsCustomer, setStoredIsCustomer] = useState<boolean>(false);
  const [storedChannel, setStoredChannel] = useState<string>('');
  useEffect(() => {
    setStoredIsCustomer((getStorage('isCustomer') as boolean) || false);
    setStoredChannel((getStorage(EStorageKey.CHANNEL) as string) || '');
  }, []);
  useEffect(() => {
    if (subjectType === '01') {
      setSelectedArtsOrSciences([firstSubject]);
    }
  }, [firstSubject]);

  const [provinceList, setProvinceList] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [yearList, setYearList] = useState<any[]>([]);
  const [userSubjectList, setUserSubjectList] = useState<any[]>([]); // 新增状态存储用户科目列表
  const [loading, setLoading] = useState(false);
  const [imageUrl, setImageUrl] = useState<string>();
  const [ossSign, setOssSign] = useState<any>({});
  const token: any = getYuzhiToken();
  const [updateSelectConfig, setUpdateSelectConfig] = useState<any>([]);
  const [tempSubjectList, setTempSubjectList] = useState<any>();

  const [subjectType, setSubjectType] = useState<ISubjectType>(); // 学科类型
  const [selectedFirstSubject, setSelectedFirstSubject] = useState<string[]>([]); // 首选科目
  const [selectedSecondSubject, setSelectedSecondSubject] = useState<string[]>([]); // 次选科目
  const [selectedArtsOrSciences, setSelectedArtsOrSciences] = useState<string[]>([]); // 文理分科
  const [artsOrSciencesList, setArtsOrSciencesList] = useState<any[]>([]); // 文理分科
  const [firstSubjectList, setFirstSubjectList] = useState<any[]>([]); // 首选科目
  const [secondSubjectList, setSecondSubjectList] = useState<any[]>([]); // 次选科目
  const [policy, setPolicy] = useState<string>('');
  const layout = {
    labelCol: { span: 6 },
    wrapperCol: { span: 18 },
  };

  const [userInfo, setUserInfo] = useState<any>();
  const [activeTab, setActiveTab] = useState<string>('basic');
  const [userInfoLoading, setUserInfoLoading] = useState<boolean>(false);
  
  // 当storedChannel是gaotu时，默认激活权益信息tab
  useEffect(() => {
    if (storedChannel === 'gaotu') {
      setActiveTab('rights');
    }
  }, [storedChannel]);
  const userLevelText =
    USER_LEVEL_LABEL_MAP[userInfo?.userLevel as string] || USER_LEVEL_LABEL_MAP.DEFAULT;
  const currentRights = useMemo(() => {
    return RIGHTS_DESCRIPTION_MAP[userInfo?.userLevel as string] || RIGHTS_DESCRIPTION_MAP.DEFAULT;
  }, [userInfo?.userLevel]);
  const expiredDateText = useMemo(() => {
    const rawValue = userInfo?.expiredDate;
    if (rawValue === null || rawValue === undefined || rawValue === '') return '—';

    const tryParse = (value: number | string) => {
      const parsed = dayjs(value);
      return parsed.isValid() ? parsed.format('YYYY年MM月DD日') : null;
    };

    if (typeof rawValue === 'number') {
      const timestamp = rawValue < 1e12 ? rawValue * 1000 : rawValue;
      const formatted = tryParse(timestamp);
      if (formatted) return formatted;
      return '—';
    }

    const trimmed = String(rawValue).trim();
    if (!trimmed) return '—';

    if (/^\d+$/.test(trimmed)) {
      const numericValue = Number(trimmed);
      if (!Number.isNaN(numericValue)) {
        const timestamp = numericValue < 1e12 ? numericValue * 1000 : numericValue;
        const formatted = tryParse(timestamp);
        if (formatted) return formatted;
      }
    }

    const fallback = tryParse(trimmed);
    return fallback || trimmed;
  }, [userInfo?.expiredDate]);
  const hasInitialized = useRef(false);

  const fetchUserInfo = useCallback(async () => {
    setUserInfoLoading(true);
    try {
      const { code, data, msg } = await getUserInfoApi();
      if (code === 0 && data) {
        setUserInfo(data);
        setStorage([{ key: 'userInfo', value: JSON.stringify(data) }]);
      } else if (msg) {
        message.error(msg || '获取用户信息失败');
      }
    } catch (error) {
      message.error('获取用户信息失败，请稍后重试');
    } finally {
      setUserInfoLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUserInfo();
  }, [fetchUserInfo]);

  // 初始化用户信息
  useEffect(() => {
    setStoredIsCustomer((getStorage('isCustomer') as boolean) || false);
    if (!userInfo || hasInitialized.current) return;
    hasInitialized.current = true;

    const { userScoreOb } = userInfo;

    form.setFieldsValue({
      userName: userInfo.userName || '',
      sex: userScoreOb?.sex?.code || '',
      areaId: userScoreOb?.province?.code || '',
      examYear: userScoreOb?.examYear || '',
      avatar: userInfo.avatarUrl || '',
    });

    if (userInfo.avatarUrl) setImageUrl(userInfo.avatarUrl);

    if (userScoreOb?.subjectList?.length) {
      setUserSubjectList(userScoreOb.subjectList);
      // 文理科回显
      if (userScoreOb.subjectType?.code) {
        form.setFieldValue('artsOrSciences', userScoreOb.subjectType.code);
        setSelectedArtsOrSciences([userScoreOb.subjectType.code]);
      }
      // 首选科目回显
      form.setFieldValue(
        'firstSubject',
        userScoreOb.subjectList.filter(item => item.isFirst === 1).map(item => item.value)?.[0]
      );
      // 次选科目回显
      form.setFieldValue(
        'secondSubject',
        userScoreOb.subjectList.filter(item => item.isFirst === 0).map(item => item.value)
      );
    }

    if (userScoreOb?.province?.code) {
      provinceChange(userScoreOb.province.code);
    }
  }, [userInfo]);

  const getOssSign = async () => {
    try {
      const { code, data, msg } = await getOssSignApi();
      if (code === 0) {
        setOssSign(data);
        return data;
      }
    } catch (error) {
      message.error('请求失败，请稍后重试');
      setIsLoading(false);
    }
  };
  const beforeUpload = (file: RcFile) => {
    const isJpgOrPng = file.type === 'image/jpeg' || file.type === 'image/png';
    if (!isJpgOrPng) {
      message.error('You can only upload JPG/PNG file!');
    }
    const isLt2M = file.size / 1024 / 1024 < 2;
    if (!isLt2M) {
      message.error('Image must smaller than 2MB!');
    }
    return isJpgOrPng && isLt2M;
  };

  const handleChange: UploadProps['onChange'] = async (info: UploadChangeParam<UploadFile>) => {
    if (info.file.status === 'uploading') {
      setLoading(true);
      return;
    }
    if (info.file.status === 'done') {
      if (!userInfo?.id) {
        message.error('用户信息获取中，请稍后再试');
        setLoading(false);
        return;
      }
      const ossSign = await getOssSign();
      // 确保 originFileObj 存在
      if (!info.file.originFileObj) {
        message.error('文件对象不存在，请重新选择文件');
        setLoading(false);
        return;
      }

      // 确保 OSS 签名信息存在
      if (!ossSign.host || !ossSign.policy) {
        message.error('OSS配置信息不完整，请刷新页面重试');
        setLoading(false);
        return;
      }
      const renamedFile = new File([info.file.originFileObj as Blob], `${userInfo.id}_avator.png`, {
        type: (info.file.originFileObj as File).type,
      });
      // 创建 FormData 并上传
      let formData = new FormData();
      formData.append('success_action_status', '200');
      formData.append('name', `${userInfo.id}_avator.png`);
      formData.append('policy', ossSign.policy);
      formData.append('signature', ossSign.signature);
      formData.append('OSSAccessKeyId', ossSign.accessid);
      formData.append('key', `${ossSign.dir}/${userInfo.id}_avator.png`); // 文件名
      formData.append('file', renamedFile); // file 必须为最后一个表单域
      setLoading(true);
      fetch(ossSign.host, {
        method: 'POST',
        body: formData,
      })
        .then(response => {
          setLoading(false);
          if (response.ok) {
            // 获取上传后的图片URL
            const imageUrl = `${ossSign.host}/${ossSign.dir}/${userInfo.id}_avator.png?t=${Date.now()}`;
            console.log('上传后的图片URL:', ossSign, imageUrl);
            setImageUrl(imageUrl);
            message.success('头像上传成功');
          } else {
            message.error('上传失败，请稍后再试');
          }
        })
        .catch(error => {
          setLoading(false);
          console.error('发生错误:', error);
          message.error('上传出错，请稍后再试');
        });
    }

    if (info.file.status === 'error') {
      setLoading(false);
      message.error('文件上传出错');
    }
  };

  const uploadButton = (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {loading && <LoadingOutlined />}
      <div
        style={{
          borderRadius: '0 0 50% 50%',
          backgroundColor: '#02020233',
          position: 'absolute',
          bottom: 0,
          width: '100%',
          color: '#fff',
          fontSize: 12,
          padding: 4,
        }}
      >
        修改
      </div>
    </div>
  );

  // 性别变化
  const sexChange = async (value: string) => {
    // 只需要更新表单值
    form.setFieldsValue({ sex: value });
  };

  // 省份变化
  const isFirstLoad = useRef(true);

  const provinceChange = async (areaId: string) => {
    const { code, data } = await getSubjectPolicy(areaId);
    if (code !== 0 || !data) return;

    // 仅用户手动切换时清空
    if (form && !isFirstLoad.current) {
      form.setFieldsValue({ firstSubject: undefined, secondSubject: [] });
      setSelectedFirstSubject([]);
      setSelectedSecondSubject([]);
      setSelectedArtsOrSciences([]);
    }
    setTempSubjectList(data);
    setPolicy(data.policy);
    setSubjectType(data.policy);

    // 首选科目
    const firstList = data.subjectList
      .filter((item: { isFirst: number }) => item.isFirst === 1)
      .map((item: { subjectName: any; subject: any; subjectType?: any; isFirst: any }) => ({
        name: item.subjectName,
        value: item.subject,
        subjectType: item.subjectType || '',
        isFirst: item.isFirst,
      }));
    setFirstSubjectList(firstList);

    // 次选科目
    const secondList = data.subjectList
      .filter((item: { isFirst: number }) => item.isFirst === 0)
      .map((item: { subjectName: any; subject: any; isFirst: any }) => ({
        name: item.subjectName,
        value: item.subject,
        isFirst: item.isFirst,
      }));
    setSecondSubjectList(secondList);

    // 文理科
    const artsList = data.subjectTypeList?.map((item: any) => ({
      name: item.desc,
      value: item.code,
    }));
    setArtsOrSciencesList(artsList);

    // 生成渲染配置
    const config: ISelectConfig[] = [];
    if (data.policy === ISubjectType.ArtsOrSciences) {
      config.push({
        config: {
          bigItem: true,
          data: artsList,
          selectType: ISelectTypeEnum.Single,
        },
      });
    } else if (data.policy === ISubjectType.FirstAndSecond) {
      config.push({
        name: '首选科目',
        config: {
          data: firstList,
          selectType: ISelectTypeEnum.Single,
        },
      });
      config.push({
        name: '次选科目',
        config: {
          data: secondList,
          selectType: ISelectTypeEnum.Mutiple,
          limitNum: data.secondNum,
        },
      });
    } else if (data.policy === ISubjectType.ThreeOutOfSix) {
      config.push({
        config: {
          data: secondList,
          selectType: ISelectTypeEnum.Mutiple,
          limitNum: data.secondNum,
        },
      });
    }
    setUpdateSelectConfig(config);
    // 初始化完成标记
    if (isFirstLoad.current) isFirstLoad.current = false;
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

  // 获取选科参数
  const getParams = () => {
    let type = '';
    let subjectTypeObject = {};
    let subjectMapList: ISubjectList[] = [];

    switch (subjectType) {
      case ISubjectType.ArtsOrSciences: {
        type = selectedArtsOrSciences[0] || '';
        subjectTypeObject = {
          desc: artsOrSciencesList?.find(item => item.value === artsOrSciences)?.name,
          code: artsOrSciences,
        };
        break;
      }

      case ISubjectType.FirstAndSecond: {
        [firstSubject].forEach(item => {
          tempSubjectList.subjectList.push({
            isFirst: 1,
            subject: item,
          });
        });
        secondSubject.forEach(item => {
          tempSubjectList.subjectList.push({
            isFirst: 0,
            subject: item,
          });
        });
        // 合并首选和再选科目
        subjectMapList = [
          ...(firstSubjectList?.filter(item => [firstSubject].includes(item.value)) || []),
          ...(secondSubjectList?.filter(item => secondSubject.includes(item.value)) || []),
        ];

        type = firstSubjectList.find(item => item.value === firstSubject)?.subjectType || '';
        subjectTypeObject = {
          desc: firstSubjectList.find(item => item.value === firstSubject)?.name || '',
          code: firstSubjectList.find(item => item.value === firstSubject)?.subjectType || '',
        };
        break;
      }

      case ISubjectType.ThreeOutOfSix: {
        secondSubject.forEach(item => {
          tempSubjectList.subjectList.push({
            isFirst: 0,
            subject: item,
          });
        });
        subjectMapList =
          secondSubjectList?.filter(item => secondSubject.includes(item.value)) || [];
        type = artsOrSciencesList[0].value || '';
        subjectTypeObject = { desc: artsOrSciencesList[0].name, code: artsOrSciencesList[0].value };
        break;
      }
    }
    console.log('hhhh', secondSubject, subjectMapList, subjectTypeObject);
    return { type, subjectMapList, artsOrSciencesList, subjectTypeObject };
  };

  const handleVerify = () => {
    let params = null;

    if (storedIsCustomer) {
      params = getParams();
    }
    form.validateFields().then(async values => {
      const { userName, sex, areaId, examYear, firstSubject, secondSubject } = values;
      const selectedOption = sexOptions.find(opt => opt.value === sex);
      const selectedProvince = provinceList.find(opt => opt.code === areaId);

      const basicInfo = { userName, avatarUrl: imageUrl || userInfo?.avatarUrl };
      let infoParams = { ...basicInfo };

      if (storedIsCustomer) {
        const subjectMapList: ISubjectList[] = [];

        if (subjectType === ISubjectType.ArtsOrSciences) {
          subjectMapList.push({ isFirst: 1, subject: firstSubject });
        } else if (
          subjectType === ISubjectType.FirstAndSecond ||
          subjectType === ISubjectType.ThreeOutOfSix
        ) {
          (Array.isArray(secondSubject) ? secondSubject : []).forEach(s => {
            subjectMapList.push({ isFirst: 0, subject: s });
          });
          if (subjectType === ISubjectType.FirstAndSecond) {
            subjectMapList.push({ isFirst: 1, subject: firstSubject });
          }
        }

        infoParams.userScoreOb = {
          examYear,
          province: selectedProvince
            ? { code: selectedProvince.code, name: selectedProvince.label }
            : null,
          sex: selectedOption ? { code: selectedOption.value, name: selectedOption.label } : null,
          subjectList: params?.subjectMapList,
          subjectType: params?.subjectTypeObject,
        };
      }
      console.log('infoParams', params, infoParams);

      try {
        const { code, data } = await updateUserInfoApi(infoParams);
        if (code === 0) {
          message.success('完善信息成功');
          setStorage([{ key: 'userInfo', value: JSON.stringify(data) }]);
          setUserInfo(data);
          navigateTo('/session');
        } else message.error('完善信息失败');
      } catch {
        message.error('请求失败，请稍后重试');
      }
    });
  };

  useEffect(() => {
    yearListHandle();
    getProvinceList();
  }, []);

  return (
    <div className={style.userContainer}>
      <Head>
        <title>高途AI志愿填报-个人中心</title>
      </Head>
      <div className={style.header}>
        <Header userInfo={userInfo} />
      </div>
      <div className={style.userWrapper}>
        <div className={style.title}>个人中心</div>
        <Tabs
          className={style.userTabs}
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            ...(storedChannel !== 'gaotu' ? [{
              key: 'basic',
              label: '基本信息',
              children: (
                <Spin spinning={userInfoLoading}>
                  <div className={style.formWrapper}>
                    <Form form={form} {...layout} className={style.userForm} labelWrap>
                      <Form.Item
                        key="avatar"
                        label="用户头像"
                        name="avatar"
                        rules={[{ required: true }]}
                        className="avatarItem"
                      >
                        <Upload
                          name="avatar"
                          listType="picture-card"
                          className="avatar-uploader"
                          showUploadList={false}
                          beforeUpload={beforeUpload}
                          onChange={handleChange}
                          customRequest={({ file, onSuccess, onError }) => {
                            // 使用自定义请求防止自动上传
                            setTimeout(() => {
                              onSuccess?.('ok');
                            }, 0);
                          }}
                        >
                          <div style={{ position: 'relative', width: '100%', height: '100%' }}>
                            {imageUrl ? (
                              <img src={imageUrl} alt="avatar" style={{ width: '100%' }} key={imageUrl} />
                            ) : (
                              uploadButton
                            )}

                            {/* 下半部分蒙版 */}
                            <div
                              style={{
                                position: 'absolute',
                                bottom: 0,
                                left: 0,
                                right: 0,
                                height: '30%',
                                background: 'rgba(2, 2, 2, 0.2)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                color: '#fff',
                                fontSize: 12,
                                borderBottomLeftRadius: '50%',
                                borderBottomRightRadius: '50%',
                                cursor: 'pointer',
                              }}
                            >
                              修改
                            </div>
                          </div>
                        </Upload>
                      </Form.Item>
                      {storedIsCustomer && (
                        <Form.Item key="sex" label="性别" name="sex" rules={[{ required: true }]}>
                          <Select placeholder="请输入性别" options={sexOptions} onChange={sexChange} />
                        </Form.Item>
                      )}
                      <Form.Item key="userName" label="用户昵称" name="userName" rules={[{ required: true }]}>
                        <Input placeholder="请输入用户昵称" />
                      </Form.Item>
                      {storedIsCustomer && (
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
                      )}
                      {storedIsCustomer && (
                        <Form.Item
                          key="examYear"
                          label="高考年份"
                          name="examYear"
                          rules={[{ required: true }]}
                        >
                          <Select
                            options={yearList}
                            placeholder="请选择您参加的高考年份"
                            popupClassName="userModalPopup"
                          />
                        </Form.Item>
                      )}
                      {storedIsCustomer && (
                        <>
                          {subjectType === ISubjectType.ArtsOrSciences ? (
                            <Form.Item name="artsOrSciences" label="文理科">
                              <Radio.Group>
                                {artsOrSciencesList.map(item => (
                                  <Radio.Button key={item.value} value={item.value}>
                                    {item.name}
                                  </Radio.Button>
                                ))}
                              </Radio.Group>
                            </Form.Item>
                          ) : (
                            <>
                              {updateSelectConfig?.map((item: any, index: number) => {
                                const isSingle = item?.config?.selectType === ISelectTypeEnum.Single;
                                const fieldName = item.name === '首选科目' ? 'firstSubject' : 'secondSubject';

                                return (
                                  <Form.Item
                                    key={index}
                                    name={fieldName}
                                    label={item.name || '全部科目'}
                                    extra={
                                      item.name === '次选科目' && '如需修改科目，需要先去掉旧的已选科目。'
                                    }
                                    rules={[
                                      {
                                        validator: (rule: any, value: any) => {
                                          if (
                                            item?.config?.selectType !== 0 &&
                                            policy === '03' &&
                                            value?.length < 3
                                          ) {
                                            return Promise.reject('科目不能少于3个');
                                          }
                                          if (item.name === '次选科目' && value?.length < 2) {
                                            return Promise.reject('科目不能少于2个');
                                          }
                                          if (
                                            item.name === '首选科目' &&
                                            (!value || !['01', '02'].includes(value))
                                          ) {
                                            return Promise.reject('请选择科目');
                                          }
                                          if (
                                            item?.config?.selectType === 0 &&
                                            ((typeof value !== 'string' && !['01', '02'].includes(value)) ||
                                              typeof value === 'object')
                                          ) {
                                            return Promise.reject('请选择科目');
                                          }

                                          return Promise.resolve();
                                        },
                                      },
                                    ]}
                                  >
                                    {isSingle ? (
                                      <Radio.Group>
                                        {item.config.data.map((config: any) => (
                                          <Radio.Button key={config.value} value={config.value}>
                                            {config.name}
                                          </Radio.Button>
                                        ))}
                                      </Radio.Group>
                                    ) : (
                                      <Checkbox.Group>
                                        {item.config.data.map((config: any) => (
                                          <Checkbox
                                            key={config.value}
                                            value={config.value}
                                            disabled={
                                              form.getFieldValue('secondSubject')?.length >=
                                                item.config.limitNum &&
                                              !(form.getFieldValue('secondSubject') || []).includes(
                                                config.value
                                              )
                                            }
                                          >
                                            {config.name}
                                          </Checkbox>
                                        ))}
                                      </Checkbox.Group>
                                    )}
                                  </Form.Item>
                                );
                              })}
                            </>
                          )}
                        </>
                      )}

                      <Form.Item wrapperCol={{ ...layout.wrapperCol, offset: 4 }}>
                        <Button block type="primary" onClick={handleVerify}>
                          保存信息
                        </Button>
                      </Form.Item>
                    </Form>
                  </div>
                </Spin>
              ),
            }] : []),
            {
              key: 'rights',
              label: '权益信息',
              children: (
                <div className={style.rightsWrapper}>
                    <div className={style.accountInfo}>
                    <div className={style.accountInfoItem}>
                      <span className={style.accountInfoLabel}>会员等级</span>
                      <span className={style.accountInfoValue}>{userLevelText}</span>
                    </div>
                    <div className={style.accountInfoItem}>
                      <span className={style.accountInfoLabel}>账号到期时间</span>
                      <span className={style.accountInfoValue}>{expiredDateText}</span>
                    </div>
                  </div>
                  <div className={style.rightsIntro}>
                    <div className={style.sectionTitle}>权益简介</div>
                    <div className={style.sectionContent}>
                        {currentRights.intro}
                    </div>
                  </div>
                  <div className={style.sectionGroup}>
                    <div className={style.sectionTitle}>可享权益</div>
                    <List
                        dataSource={currentRights.privileges}
                        renderItem={(item: string) => (
                          <List.Item className={style.listItem}>{item}</List.Item>
                        )}
                    />
                  </div>
                  <div className={style.sectionGroup}>
                    <div className={style.sectionTitle}>使用限制</div>
                    <List
                        dataSource={currentRights.limitations}
                        renderItem={(item: string) => (
                          <List.Item className={style.listItem}>{item}</List.Item>
                        )}
                    />
                  </div>
                </div>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
};

export default UserCenter;
