/* eslint-disable prefer-promise-reject-errors */
import {
  Badge,
  Checkbox,
  Col,
  Flex,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Row,
  Select,
  Slider,
} from 'antd';
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import {
  getProvinceLists,
  getSubjectPolicy,
  getYearList,
  getBatchList,
} from '@/service/apis/sessionDetail';
import SubjectScores, { IRefParams } from '../subjectScores';
import SelectOption from '../selectOption';
import useForm from './useForm';
import {
  ISexAndProvinceAndBatchObject,
  ISubjectTypeAndExamObject,
} from '@/interface/api/updateBaseInfo';
import useAuthParams from '@/hooks/useAuthParams';
import { IPosRangeParams } from '@/interface/api/customerDetail';
import {
  getEthnicityListApi,
  getMajorEducationApi,
  getPositionRangeApi,
  getRegionProvinceApi,
  getUnacceptableMajorsListApi,
} from '@/service/apis/customerDetail';
import {
  HAINAN_PROVINCE_CODE,
  resolveTotalScoreLabel,
  validateHainanTotalScore,
} from '@/utils/scoreRules.mjs';
import styles from './style.module.scss';

const CheckboxGroup = Checkbox.Group;

interface MajorSub {
  majorSubId: string;
  majorSubName: string;
}

interface RegionSub {
  provinceId: string;
  provinceName: string;
}

const MAX_NAME_LENGTH = 5;
const LSubject = ['物理', '化学', '生物'];
const WSubject = ['政治', '历史', '地理'];
const sexOptions = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
];

const StrategyTypeListData = [
  {
    value: 'aggressive',
    label: '激进型',
  },
  {
    value: 'cautious',
    label: '稳妥型',
  },
  {
    value: 'traditional',
    label: '保守型',
  },
];
const TargetListData = [
  {
    label: '院校优先',
    value: 'SCHOOL_FIRST',
    disabled: false,
  },
  {
    label: '专业优先',
    value: 'MAJOR_FIRST',
    disabled: true,
  },
  {
    label: '地域优先',
    value: 'CITY_FIRST',
    disabled: true,
  },
];
const colorSistuationOptions = [
  {
    label: '正常',
    value: 'normal',
  },
  {
    label: '色盲',
    value: 'colorBlind',
  },
  {
    label: '色弱',
    value: 'colorWeak',
  },
];
const politicalStatusOptions = [
  {
    label: '中共党员',
    value: 'partyMember',
  },
  {
    label: '共青团员',
    value: 'leagueMember',
  },
  {
    label: '群众',
    value: 'masses',
  },
];

const ModalForm = forwardRef<IRefParams>((_, ref) => {
  const [form] = Form.useForm();
  const [sexData, setSexData] = useState<any>(null); // 修改初始状态为null
  const [provinceList, setProvinceList] = useState<any[]>([]);
  const [subjectOpen, setSubjectOpen] = useState(false);
  const [scoreOpen, setScoreOpen] = useState(false);
  const [yearList, setYearList] = useState<any[]>([]);
  const isSubjectTypeRef = useRef<boolean>(false); // 是否展示科目类型
  const prepareTypeRef = useRef<any>();
  const [batchListData, setBatchListData] = useState<any[]>([]);
  const [batchAllList, setBatchAllList] = useState<any[]>([]);
  const [batchexamType, setBatchexamType] = useState<any>();
  const [batchChoose, setBatchChoose] = useState<any>();
  const [batchPrepareType, setBatchPrepareType] = useState<any>();
  const [grades, setGrades] = useState<string>('');
  const [totalScore, setTotalScore] = useState<number>();
  const [totalScorePos, setTotalScorePos] = useState<number>();
  const [subject, setSubject] = useState<string>('');
  const [selectedSubjects, setSelectedSubjects] = useState<string[]>([]);
  const scoreFormRef = useRef<IRefParams>(null);
  const memberSubjectListRef = useRef<any[]>([]);
  const subjectScoreListRef = useRef<any[]>([]);
  const baseScoreRef = useRef<number>(0); // 添加基础分数引用
  const [strengthSubjectOptions, setStrengthSubjectOptions] = useState<any[]>([]); // 优势学科
  const selectedStrengthSubjects = Form.useWatch('strengthSubjectList', form) || [];
  const colorValues = Form.useWatch('colorSistuation', form) || []; // 色觉情况
  const [ethnicityOptions, setEthnicityOptions] = useState<any[]>([]); // 民族列表
  const [majorsListData, setMajorsListData] = useState<any[]>([]); // 意向专业列表
  const [regionProvinceList, setRegionProvinceList] = useState<any[]>([]); // 按大区分组的省份列表
  const [unAcceptableMajorsOptions, setUnAcceptableMajorsOptions] = useState<any[]>([]); // 不能接受的专业列表
  const tuitionRangeFormValue = Form.useWatch('tuitionRange', form); // 学费区间（从表单获取）
  const provinceValue = Form.useWatch('areaId', form);
  const isHainanProvince = provinceValue === HAINAN_PROVINCE_CODE;
  const [tuitionRange, setTuitionRange] = useState<[number, number]>([0, 100000]); // 学费区间状态（用于Slider显示）

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
  const params = useRef<any>({}); // 提交的参数
  const { botId, tenantId } = useAuthParams();

  useImperativeHandle(ref, () => ({
    form,
    getSaveParamsData: () => ({
      prepareType: batchPrepareType, //  (模拟填报/志愿填报)
      subjectType: params.current.type, // 科目类型 （N、LS、WL）
      memberSubjectList: memberSubjectListRef.current, // 科目成绩
      subjectScoreList: subjectScoreListRef.current, // 科目成绩
    }),
    getDealParamsData: () => {
      const sexValue = form.getFieldValue('sex');
      const selectedOption = sexOptions.find(opt => opt.value === sexValue);
      const provinceValue = form.getFieldValue('areaId');
      const selectedProvinceOption = provinceList.find(opt => opt.code === provinceValue);
      const ethnicityValue = form.getFieldValue('ethnicity');
      const selectedEthnicityOption = ethnicityOptions.find(opt => opt.value === ethnicityValue);
      const politicalStatusValue = form.getFieldValue('politicalStatus');
      const selectedPoliticalStatusOption = politicalStatusOptions.find(
        opt => opt.value === politicalStatusValue
      );
      const strengthSubjectListValue = form.getFieldValue('strengthSubjectList');
      const selectedStrengthSubjectOptions = strengthSubjectOptions
        .filter(opt => strengthSubjectListValue.includes(opt.value))
        ?.map(item => {
          return {
            subject: item.value,
            subjectName: item.label,
          };
        });
      const strategyTypeValue = form.getFieldValue('strategyType');
      const selectedStrategyTypeOption = StrategyTypeListData.find(
        opt => opt.value === strategyTypeValue
      );
      const unacceptableMajorsValue = form.getFieldValue('unacceptableMajors');
      const selectedUnAcceptableMajorsOptions = unAcceptableMajorsOptions
        .filter(opt => unacceptableMajorsValue?.includes(opt.value))
        ?.map(item => {
          return {
            majorId: item.value,
            majorName: item.label,
          };
        });

      return {
        botId: botId,
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
        subjectType: params.current.subjectTypeObject,
        subjectList: params.current.subjectMapList,
        batch: batchChoose,
        strengthSubjectList: selectedStrengthSubjectOptions || [],
        ethnicity: selectedEthnicityOption
          ? {
              code: selectedEthnicityOption.value,
              name: selectedEthnicityOption.label,
            }
          : null,
        politicalStatus: selectedPoliticalStatusOption
          ? {
              code: selectedPoliticalStatusOption.value,
              name: selectedPoliticalStatusOption.label,
            }
          : null,
        strategyType: selectedStrategyTypeOption
          ? {
              code: selectedStrategyTypeOption.value,
              name: selectedStrategyTypeOption.label,
            }
          : null,
        unacceptableMajors: selectedUnAcceptableMajorsOptions || [],
      };
    },
  }));

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
    scoreFormRef.current?.form.setFieldsValue({
      grades1: '',
      grades2: '',
      grades3: '',
      grades4: '',
      grades5: '',
      grades6: '',
    });
    subject && setSubject('');
    grades && setGrades('');
    totalScore && setTotalScore(undefined);
    totalScorePos && setTotalScorePos(undefined);
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

  // 获取民族列表
  const getEthnicityList = async () => {
    const { code, data } = await getEthnicityListApi();
    if (code === 0 && data) {
      setEthnicityOptions(data.map((item: any) => ({ label: item.name, value: item.code })));
    }
  };

  // 获取意向专业列表
  const getMajorDataList = async (batchLevel?: string) => {
    // 根据批次等级映射到educationLevel: 01 -> BACHELOR, 02 -> ASSOCIATE
    let educationLevel = 'BACHELOR'; // 默认本科
    if (batchLevel === '02') {
      educationLevel = 'ASSOCIATE'; // 专科
    } else if (batchLevel === '01') {
      educationLevel = 'BACHELOR'; // 本科
    }
    
    const { code, data } = await getMajorEducationApi(educationLevel);
    if (code === 0 && data) {
      setActiveMajor(data[0].id);
      setMajorsListData([...data]);
    }
  };

  // 获取不能接受的专业列表
  const getUnAcceptableMajorsList = async () => {
    const { code, data } = await getUnacceptableMajorsListApi({
      subjectType: params.current.type,
      educationLevel: batchChoose.level,
      subjectList: params.current.subjectMapList,
    });
    if (code === 0 && data) {
      setUnAcceptableMajorsOptions(
        data.map((item: any) => ({ label: item.majorName, value: item.majorId }))
      );
    }
  };
  // 获取按大区分组的省份列表
  const getRegionProvinceList = async () => {
    const { code, data } = await getRegionProvinceApi();
    if (code === 0 && data) {
      setRegionProvinceList(data);
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

  // 批次
  const batchChange = (value: string) => {
    const batchObject = batchListData?.find(item => item.value === value);
    const batchType = batchAllList?.find(item => item.batch === value);
    // console.log('批次=>>>>>', batchListData, batchObject, batchType);
    const newBatchChoose = {
      code: batchObject.value,
      name: batchObject.label,
      level: batchObject.level,
      pos: batchObject.pos ? Number(batchObject.pos) : undefined,
      score: batchObject.score ? parseFloat(batchObject.score) : undefined,
    };
    setBatchChoose(newBatchChoose);
    setBatchPrepareType(batchType.prepareType);
    
    // 根据批次等级获取专业列表
    if (newBatchChoose.level) {
      getMajorDataList(newBatchChoose.level);
    }

    // code=level.key,name=batchTitle,score=score
  };
  // 加分
  const handleBonusScoreChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    console.log('e.target.value', e.target.value);
    if (isHainanProvince) {
      return;
    }
    const bonusScore = Number(e.target.value) || 0;
    const score = baseScoreRef.current + bonusScore;
    form.setFieldsValue({ totalScore: score });
    setTotalScore(score);
  };

  const handleTotalScoreChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value.replace(/\D/g, '');
    const score = value ? Number(value) : undefined;
    setTotalScore(score);
    form.setFieldsValue({ totalScore: score });
  };

  const validateHainanFinalScore = (_: any, value: any) => {
    if (!isHainanProvince) {
      return Promise.resolve();
    }
    const error = validateHainanTotalScore(value);
    return error ? Promise.reject(new Error(error)) : Promise.resolve();
  };
  
  // 重新计算总分（当批次或省份变化时）
  const recalculateTotalScore = () => {
    const subjectScoreList = subjectScoreListRef.current;
    if (!subjectScoreList || subjectScoreList.length === 0) {
      return;
    }
    
    // 获取省份code和批次level
    const provinceCode = form.getFieldValue('areaId');
    if (provinceCode === HAINAN_PROVINCE_CODE) {
      return;
    }
    const batchLevel = batchChoose?.level;
    
    // 判断是否是北京/天津/上海 + 专科批（level = '02'）
    const isSpecialProvinceJuniorCollege = 
      ['110000', '120000', '310000'].includes(provinceCode) && batchLevel === '02';
    
    // 语数外三科的subject code
    const mainSubjects = ['08', '10', '11']; // 语文、数学、英语
    
    // 计算总分
    let totalScore = 0;
    if (isSpecialProvinceJuniorCollege) {
      // 如果是专科批（北京/天津/上海），只计算语数外三科
      const mainSubjectScores = subjectScoreList.filter(item => mainSubjects.includes(item.subject));
      totalScore = mainSubjectScores.reduce((acc, curr) => acc + (curr.score || 0), 0);
    } else {
      // 否则计算所有科目
      totalScore = subjectScoreList.reduce((acc, curr) => acc + (curr.score || 0), 0);
    }
    
    baseScoreRef.current = totalScore; // 更新基础分数
    const bonusScore = Number(form.getFieldValue('bonusScore')) || 0;
    const finalScore = totalScore + bonusScore;
    form.setFieldsValue({ totalScore: finalScore });
    setTotalScore(finalScore);
  };

  const handleBatchInfoRequest = async () => {
    params.current = getParams();
    const { code, data } = await getBatchList({
      areaId: form.getFieldValue('areaId'),
      prepareType: prepareTypeRef.current.code,
      subject: params.current.type,
    });
    if (code === 0 && data) {
      const { batchList, type } = data;
      // 更新批次列表
      const newBatchList = batchList.map((i: any) => ({
        value: i.batch,
        level: i.level.key,
        pos: i.pos,
        score: i.score,
        label: `${i.batchTitle}(批次线${+i.score.slice(0, 5)}分)`,
      }));
      setBatchListData(newBatchList);
      setBatchAllList(batchList);
      setBatchexamType(type);
    } else {
      message.error('获取批次信息失败');
    }
    form.setFieldValue('batch', '');
  };

  // 监听字段变化
  const totalScoreValue = Form.useWatch('totalScore', form);
  const batchValue = Form.useWatch('batch', form);

  useEffect(() => {
    // 当 totalScore 和 batch 都存在时，调用 getPositionRange
    if (totalScoreValue && batchValue) {
      if (isHainanProvince) {
        const score = Number(totalScoreValue);
        if (Number.isNaN(score) || score < 100 || score > 900) {
          return;
        }
      }
      const allValues = form.getFieldsValue(['totalScore', 'batch']);
      getPositionRange(allValues);
    }
  }, [totalScoreValue, batchValue, isHainanProvince]);

  useEffect(() => {
    // 当批次变化时，重新获取专业列表和不能接受的专业列表
    if (batchValue && batchChoose?.level) {
      getMajorDataList(batchChoose.level);
      getUnAcceptableMajorsList();
      // 重新计算总分（考虑特殊省份+专科批次的逻辑）
      recalculateTotalScore();
    }
  }, [batchValue, batchChoose?.level]);
  
  // 监听省份变化，重新计算总分
  useEffect(() => {
    if (provinceValue && subjectScoreListRef.current?.length > 0 && !isHainanProvince) {
      recalculateTotalScore();
    }
  }, [provinceValue, isHainanProvince]);

  // 获取成绩位次
  const getPositionRange = async (allValues: any) => {
    const dataLevel = batchListData?.find(item => item.value === allValues.batch)?.level;

    const { code, data } = await getPositionRangeApi({
      areaId: form.getFieldValue('areaId'),
      subject: params.current.type,
      dataLevel: dataLevel,
      year: form.getFieldValue('examYear'),
      score: allValues.totalScore,
    });
    if (code === 0 && data) {
      form.setFieldsValue({ totalScorePos: data.lowestRank || 0 });
      setTotalScorePos(data.lowestRank || 0);
    }
  };

  const handleSubjectOk = () => {
    setSubjectOpen(false);
    handleBatchInfoRequest();
    // debugger;
    const configGroups = subjectSelectConfig.flatMap(group => group.config.data);
    // 处理理科和文科
    if (params.current.type === 'L' || params.current.type === 'W') {
      if (params.current.type === 'L') {
        setSelectedSubjects(LSubject);
      } else {
        setSelectedSubjects(WSubject);
      }
      const subjectObj = configGroups.find((item: any) => item.value === params.current.type);
      if (subjectObj) {
        subjectSelectConfig[0].config.data.forEach((i: any) => {
          if (i.value === params.current.type) {
            setSubject(i.name);
            form.setFieldValue('subject', i.name);
          }
        });
      }
      return;
    }
    // 处理选中科目并反显到表单
    const selectedSubjects = params.current.subjectList.map((subjectItem: any) => {
      const matchedSubject = configGroups.find(
        configItem => configItem.value === subjectItem.subject
      );
      return matchedSubject ? matchedSubject.name : '';
    });
    setSelectedSubjects(selectedSubjects);
    const subjectText = selectedSubjects.join(',');
    setSubject(subjectText);
    form.setFieldsValue({ subject: subjectText });
  };

  const handleScoreOk = () => {
    scoreFormRef.current?.form.validateFields().then(res => {
      const memberSubjectList = [
        {
          subjectCode: {
            data: '语文',
            key: '08',
          },
          score: Number(res.grades1),
        },
        {
          subjectCode: {
            data: '数学',
            key: '10',
          },
          score: Number(res.grades2),
        },
        {
          subjectCode: {
            data: '英语',
            key: '11',
          },
          score: Number(res.grades3),
        },
      ];
      const subjectScoreList = [
        {
          subjectName: '语文',
          subject: '08',
          score: Number(res.grades1),
        },
        {
          subjectName: '数学',
          subject: '10',
          score: Number(res.grades2),
        },
        {
          subjectName: '英语',
          subject: '11',
          score: Number(res.grades3),
        },
      ];
      const selectedSubjects = form.getFieldValue('subject').split(',');
      const configGroups = subjectSelectConfig.flatMap(group => group.config.data);
      selectedSubjects.forEach((subject: string, index: number) => {
        const subjectConfig = configGroups.find(item => item.name === subject);
        if (subjectConfig) {
          memberSubjectList.push({
            subjectCode: {
              data: subject,
              key: subjectConfig.value,
            },
            score: Number(res[`grades${index + 4}`]),
          });

          subjectScoreList.push({
            subjectName: subject,
            subject: subjectConfig.value,
            score: Number(res[`grades${index + 4}`]),
          });
        }
      });
      memberSubjectListRef.current = memberSubjectList;
      subjectScoreListRef.current = subjectScoreList;
      const concatenatedString = Object.values(res).join(',');
      
      // 获取省份code和批次level
      const provinceCode = form.getFieldValue('areaId');
      const batchLevel = batchChoose?.level;
      
      // 判断是否是北京/天津/上海 + 专科批（level = '02'）
      const isSpecialProvinceJuniorCollege = 
        ['110000', '120000', '310000'].includes(provinceCode) && batchLevel === '02';
      
      // 语数外三科的subject code
      const mainSubjects = ['08', '10', '11']; // 语文、数学、英语
      
      // 计算总分
      if (provinceCode === HAINAN_PROVINCE_CODE) {
        form.setFieldsValue({ grades: concatenatedString });
        setGrades(concatenatedString);
        setScoreOpen(false);
        const subjectStrengthList = subjectScoreList?.map(item => ({
          label: item.subjectName,
          value: item.subject,
        }));
        setStrengthSubjectOptions(subjectStrengthList);
        return;
      }

      let totalScore = 0;
      if (isSpecialProvinceJuniorCollege) {
        // 如果是专科批（北京/天津/上海），只计算语数外三科
        const mainSubjectScores = subjectScoreList.filter(item => mainSubjects.includes(item.subject));
        totalScore = mainSubjectScores.reduce((acc, curr) => acc + (curr.score || 0), 0);
      } else {
        // 否则计算所有科目
        totalScore = Object.values(res)
          .map((value: any) => Number(value.trim()))
          .reduce((acc, curr) => acc + curr, 0);
      }

      baseScoreRef.current = totalScore; // 保存各科成绩的基础分数
      const bonusScore = Number(form.getFieldValue('bonusScore')) || 0;
      const finalScore = totalScore + bonusScore;
      form.setFieldsValue({ totalScore: finalScore });
      form.setFieldsValue({ grades: concatenatedString });
      setTotalScore(finalScore);
      setGrades(concatenatedString);
      setScoreOpen(false);
      // 擅长科目
      const subjectStrengthList = subjectScoreList?.map(item => ({
        label: item.subjectName,
        value: item.subject,
      }));
      setStrengthSubjectOptions(subjectStrengthList);
    });
  };

  const openSubjectModal = () => {
    if (form.getFieldValue('areaId')) {
      setSubjectOpen(true);
    } else {
      message.error('请先选择省份');
    }
  };

  const openScoreModal = () => {
    if (form.getFieldValue('subject')) {
      setScoreOpen(true);
    } else {
      message.error('请先选择高考科目');
    }
  };

  const handleBatchChange = () => {
    // 注意：这里不清空批次选择，只更新批次的禁用状态
    // 获取所有科目的总分（不考虑特殊省份+专科批次的逻辑）
    // 这样用户可以自由切换批次，不会因为总分变化而被限制
    const subjectScoreList = subjectScoreListRef.current;
    let allSubjectsTotalScore = 0;
    if (subjectScoreList && subjectScoreList.length > 0) {
      // 计算所有科目的总分
      allSubjectsTotalScore = subjectScoreList.reduce((acc, curr) => acc + (curr.score || 0), 0);
      // 加上加分
      const bonusScore = Number(form.getFieldValue('bonusScore')) || 0;
      allSubjectsTotalScore += bonusScore;
    } else {
      // 如果没有科目成绩，使用表单中的总分
      const userScore = form.getFieldValue('totalScore');
      allSubjectsTotalScore = userScore ? Number(userScore) : 0;
    }
    
    if (allSubjectsTotalScore > 0) {
      // 检查用户分数是否高于所有批次
      const isHigherThanAll = batchListData.every(
        (item: any) => allSubjectsTotalScore > Number(item.score.slice(0, 5))
      );

      // 检查用户分数是否低于所有批次
      const isLowerThanAll = batchListData.every(
        (item: any) => allSubjectsTotalScore < Number(item.score.slice(0, 5))
      );
      console.log('isLowerThanAll', isLowerThanAll);

      if (isHigherThanAll) {
        // 如果分数高于所有批次，启用所有批次
        batchListData.forEach((item: any) => {
          item.disabled = false;
        });
      } else if (isLowerThanAll) {
        // 如果分数低于所有批次，只启用最后一个批次
        batchListData.forEach((item: any, index: number) => {
          item.disabled = index !== batchListData.length - 1;
        });
      } else {
        // 对于在批次之间的分数，启用分数更高的批次
        batchListData.forEach((item: any) => {
          item.disabled = allSubjectsTotalScore < Number(item.score.slice(0, 5));
        });
      }
    }
  };

  const [selectedMajors, setSelectedMajors] = useState<{
    [major: string]: MajorSub[];
  }>({});

  // const handleMajorSelect = (value: string, label: string) => {
  //   const currentMajorSubs = selectedMajors[activeMajor] || [];
  //   if (currentMajorSubs.some(m => m.majorSubId === value)) {
  //     setSelectedMajors(prev => ({
  //       ...prev,
  //       [activeMajor]: currentMajorSubs.filter(m => m.majorSubId !== value),
  //     }));

  //     const allSelectedMajors = Object.values(selectedMajors).flat();
  //     form.setFieldsValue({
  //       preferredMajors: allSelectedMajors,
  //     });
  //     return;
  //   }
  //   setSelectedMajors(prev => ({
  //     ...prev,
  //     [activeMajor]: [...(prev[activeMajor] || []), { majorSubId: value, majorSubName: label }],
  //   }));

  //   const allSelectedMajors = Object.values(selectedMajors).flat();
  //   form.setFieldsValue({
  //     preferredMajors: allSelectedMajors,
  //   });
  // };

  // const handleSelectAll = () => {
  //   if (selectedMajors[activeMajor]?.length === majorList?.length) {
  //     setSelectedMajors(prev => ({
  //       ...prev,
  //       [activeMajor]: [],
  //     }));

  //     const allSelectedMajors = Object.values(selectedMajors).flat();
  //     form.setFieldsValue({
  //       preferredMajors: allSelectedMajors,
  //     });
  //     return;
  //   }
  //   setSelectedMajors(prev => ({
  //     ...prev,
  //     [activeMajor]: [
  //       ...(majorList || []).map(item => ({ majorSubId: item.id, majorSubName: item.label })),
  //     ],
  //   }));

  //   const allSelectedMajors = Object.values(selectedMajors).flat();
  //   form.setFieldsValue({
  //     preferredMajors: allSelectedMajors,
  //   });
  // };
  // 单选专业
  const handleMajorSelect = (value: string, label: string) => {
    const currentMajorSubs = selectedMajors[activeMajor] || [];

    let newCurrentMajorSubs: MajorSub[];
    if (currentMajorSubs.some(m => m.majorSubId === value)) {
      // 取消选中
      newCurrentMajorSubs = currentMajorSubs.filter(m => m.majorSubId !== value);
    } else {
      // 添加选中
      newCurrentMajorSubs = [...currentMajorSubs, { majorSubId: value, majorSubName: label }];
    }

    // 更新 state
    setSelectedMajors(prev => {
      const newSelected = {
        ...prev,
        [activeMajor]: newCurrentMajorSubs,
      };

      // 更新 Form
      const allSelectedMajors = Object.values(newSelected)
        .flat()
        .map(item => ({
          majorSubName: item.majorSubName,
          majorSubId: item.majorSubId,
        }));

      setTimeout(() => {
        form.setFieldValue('preferredMajors', allSelectedMajors);
      }, 100);

      return newSelected;
    });
  };

  // 全选/取消全选
  const handleSelectAll = () => {
    let newCurrentMajorSubs: MajorSub[] = [];

    if (selectedMajors[activeMajor]?.length === majorList?.length) {
      // 已全选，取消全选
      newCurrentMajorSubs = [];
    } else {
      // 全选
      newCurrentMajorSubs = (majorList || []).map(item => ({
        majorSubId: item.id,
        majorSubName: item.label,
      }));
    }
    // 更新 state
    setSelectedMajors(prev => {
      const newSelected = {
        ...prev,
        [activeMajor]: newCurrentMajorSubs,
      };

      // 更新 Form
      const allSelectedMajors = Object.values(newSelected)
        .flat()
        .map(item => ({
          majorSubName: item.majorSubName,
          majorSubId: item.majorSubId,
        }));
      setTimeout(() => {
        form.setFieldValue('preferredMajors', allSelectedMajors);
      }, 100);

      return newSelected;
    });
  };

  const [preferredRegions, setPreferredRegions] = useState<RegionSub[]>([]);

  const handleProvinceClick = (id: string, label: string) => {
    if (preferredRegions.some(m => m.provinceId === id)) {
      setPreferredRegions(preferredRegions.filter(m => m.provinceId !== id));
      form.setFieldsValue({ preferredRegions: preferredRegions.filter(m => m.provinceId !== id) });
      return;
    }
    setPreferredRegions([...preferredRegions, { provinceId: id, provinceName: label }]);
    form.setFieldsValue({
      preferredRegions: [...preferredRegions, { provinceId: id, provinceName: label }],
    });
  };

  // 处理地区全选/取消全选
  const handleToggleRegion = (provinces: { id: string; label: string }[]) => {
    if (!provinces?.length) return;
    const allSelected = provinces.every(province =>
      preferredRegions.some(m => m.provinceId === province.id)
    );
    if (allSelected) {
      // 取消全选：移除该地区所有省份
      const newRegions = preferredRegions.filter(
        m => !provinces.some(province => province.id === m.provinceId)
      );
      setPreferredRegions(newRegions);
      form.setFieldsValue({ preferredRegions: newRegions });
    } else {
      // 全选：添加该地区所有省份
      const nextRegions = [...preferredRegions];
      provinces.forEach(province => {
        if (!nextRegions.some(m => m.provinceId === province.id)) {
          nextRegions.push({ provinceId: province.id, provinceName: province.label });
        }
      });
      setPreferredRegions(nextRegions);
      form.setFieldsValue({ preferredRegions: nextRegions });
    }
  };

  useEffect(() => {
    yearListHandle();
    getProvinceList();
    getEthnicityList();
    getRegionProvinceList();
    // 初始化学费区间
    form.setFieldsValue({ tuitionRange: [0, 100000] });
    setTuitionRange([0, 100000]);
    // 专业列表需要等批次选择后再获取，所以不在这里调用
  }, []);

  // 同步表单值到状态（用于Slider显示）
  useEffect(() => {
    if (tuitionRangeFormValue && Array.isArray(tuitionRangeFormValue) && tuitionRangeFormValue.length === 2) {
      setTuitionRange(tuitionRangeFormValue as [number, number]);
    }
  }, [tuitionRangeFormValue]);

  useEffect(() => {
    handleBatchChange();
  }, [form.getFieldValue('totalScore')]);

  const [activeMajor, setActiveMajor] = useState<string>('1');
  const handleMajorClick = (majorId: string) => {
    setActiveMajor(majorId);
  };

  const majorList = useMemo(() => {
    return majorsListData?.find(major => major.id === activeMajor)?.children;
  }, [activeMajor, majorsListData]);

  return (
    <>
      <Form form={form} className={styles.modalForm}>
        <Form.Item key="userName" label="姓名" name="userName" rules={[{ required: true }]}>
          <Input placeholder="请输入姓名" maxLength={MAX_NAME_LENGTH} />
        </Form.Item>
        <Form.Item key="sex" label="性别" name="sex" rules={[{ required: true }]}>
          <Select placeholder="请输入性别" options={sexOptions} onChange={sexChange} />
        </Form.Item>
        <Form.Item key="height" label="身高" name="height">
          <InputNumber placeholder="请输入身高" addonAfter="cm" />
        </Form.Item>
        <Form.Item key="examYear" label="高考年份" name="examYear" rules={[{ required: true }]}>
          <Select options={yearList} placeholder="请选择高考年份" />
        </Form.Item>
        <Form.Item key="areaId" label="高考省份" name="areaId" rules={[{ required: true }]}>
          <Select
            placeholder="请选择高考省份"
            fieldNames={{
              label: 'label',
              value: 'code',
            }}
            options={provinceList}
            onChange={provinceChange}
          />
        </Form.Item>
        <Form.Item
          label="专项填报资格"
          name="specialPlan"
          rules={[{ required: true, message: '请输入专项填报资格' }]}
        >
          <Select
            placeholder="请选择专项填报资格"
            options={[
              { value: false, label: '否' },
              { value: true, label: '是' },
            ]}
          />
        </Form.Item>
        {/* <Form.Item
          key="colorBlindness"
          label="色盲色弱"
          name="colorBlindness"
          rules={[{ required: true }]}
        >
          <Select
            placeholder="请选择是否色盲色弱"
            options={[
              { value: false, label: '否' },
              { value: true, label: '是' },
            ]}
          />
        </Form.Item> */}

        <Form.Item
          key="colorSistuation"
          label="色觉情况"
          name="colorSistuation"
          rules={[{ required: true, message: '请选择色觉情况' }]}
        >
          <CheckboxGroup>
            {colorSistuationOptions.map(config => {
              const isNormalChecked = colorValues.includes('normal');
              const hasOtherChecked =
                colorValues.includes('colorBlind') || colorValues.includes('colorWeak');

              return (
                <Checkbox
                  key={config.value}
                  value={config.value}
                  disabled={
                    (isNormalChecked && config.value !== 'normal') ||
                    (hasOtherChecked && config.value === 'normal')
                  }
                >
                  {config.label}
                </Checkbox>
              );
            })}
          </CheckboxGroup>
        </Form.Item>

        <Form.Item label="视力情况">
          <Input.Group compact>
            <Form.Item
              name={['visionAbility', 'left']}
              noStyle
            >
              <Input placeholder="左眼裸眼视力" style={{ width: '50%' }} />
            </Form.Item>
            <Form.Item
              name={['visionAbility', 'right']}
              noStyle
            >
              <Input placeholder="右眼裸眼视力" style={{ width: '50%' }} />
            </Form.Item>
          </Input.Group>
        </Form.Item>

        {/* <Form.Item key="minority" label="少数民族" name="minority" rules={[{ required: true }]}>
          <Select
            placeholder="请选择是否少数民族"
            options={[
              { value: false, label: '否' },
              { value: true, label: '是' },
            ]}
          />
        </Form.Item> */}
        <Form.Item key="ethnicity" label="民族" name="ethnicity" rules={[{ required: true }]}>
          <Select options={ethnicityOptions} placeholder="请选择民族" />
        </Form.Item>
        <Form.Item key="subject" label="高考科目" name="subject" rules={[{ required: true }]}>
          <div onClick={openSubjectModal}>
            <Input placeholder="请输入高考科目" readOnly value={subject} />
          </div>
        </Form.Item>
        <Form.Item key="grades" label="各科成绩" name="grades" rules={[{ required: true }]}>
          <div onClick={openScoreModal}>
            <Input readOnly value={grades} placeholder="请选择各科成绩" />
          </div>
        </Form.Item>
        <Form.Item
          key="strengthSubjectList"
          label="擅长科目"
          name="strengthSubjectList"
          rules={[
            { required: true, message: '请至少选择一个科目' },
            {
              validator: (_, value) => {
                if (!value || value.length <= 2) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error('最多只能选择两个科目'));
              },
            },
          ]}
        >
          <Select
            mode="multiple"
            placeholder="请选择擅长科目"
            options={strengthSubjectOptions.map(opt => {
              return {
                ...opt,
                disabled:
                  selectedStrengthSubjects.length >= 2 &&
                  !selectedStrengthSubjects.includes(opt.value),
              };
            })}
          />
        </Form.Item>
        <Form.Item
          key="bonusPolicy"
          label="全国政策加分"
          name="bonusPolicy"
          rules={[{ required: true }]}
        >
          <Select
            placeholder="请选择全国政策加分"
            options={[
              { value: false, label: '否' },
              { value: true, label: '是' },
            ]}
            onChange={value => {
              if (!value) {
                form.setFieldsValue({ bonusScore: 0 });
              }
            }}
          />
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(prevValues, currentValues) =>
            prevValues.bonusPolicy !== currentValues.bonusPolicy
          }
        >
          {({ getFieldValue }) => {
            const bonusPolicy = getFieldValue('bonusPolicy');
            return (
              <Form.Item
                key="bonusScore"
                label="加分"
                name="bonusScore"
                rules={[
                  { required: true, message: '请输入加分' },
                  {
                    validator(_, value) {
                      if (bonusPolicy && (!value || Number(value) <= 0)) {
                        return Promise.reject(
                          '由于您选择了全国政策加分为是，所以这个选项必须大于0'
                        );
                      }
                      return Promise.resolve();
                    },
                  },
                ]}
              >
                <Input
                  readOnly={!bonusPolicy}
                  placeholder={bonusPolicy ? '请输入分数' : '0'}
                  defaultValue={bonusPolicy ? undefined : 0}
                  onChange={handleBonusScoreChange}
                />
              </Form.Item>
            );
          }}
        </Form.Item>
        <Form.Item
          key="totalScore"
          label={resolveTotalScoreLabel(provinceValue, '高考总成绩')}
          name="totalScore"
          rules={[{ required: true }, { validator: validateHainanFinalScore }]}
          extra={
            isHainanProvince
              ? '请填写转换/赋分后用于投档和查位次的最终总成绩，不是各科成绩相加。'
              : undefined
          }
        >
          <div>
            <Input
              readOnly={!isHainanProvince}
              value={totalScore}
              placeholder={isHainanProvince ? '请输入最终总分' : '自动计算'}
              onChange={isHainanProvince ? handleTotalScoreChange : undefined}
            />
          </div>
        </Form.Item>
        <Form.Item key="batch" label="填报批次" rules={[{ required: true }]} name="batch">
          <Select placeholder="请选择填报批次" options={batchListData} onChange={batchChange} />
        </Form.Item>
        <Form.Item
          key="totalScorePos"
          label="成绩排名"
          name="totalScorePos"
          rules={[{ required: true }]}
        >
          <div>
            <Input readOnly value={totalScorePos} placeholder="自动计算" />
          </div>
        </Form.Item>
        <Form.Item
          key="politicalStatus"
          label="政治面貌"
          rules={[{ required: true }]}
          name="politicalStatus"
        >
          <Select placeholder="请选择政治面貌" options={politicalStatusOptions} />
        </Form.Item>

        <Form.Item
          key="preferredMajors"
          label="意向专业"
          name="preferredMajors"
          rules={[{ required: false }]}
        >
          <div className={styles.preferredMajor}>
            <Row className={styles.majorRow}>
              <Col className={styles.majorColLeft}>
                {majorsListData?.map((major, index) => (
                  <div
                    key={major.id}
                    className={[
                      styles.majorItem,
                      activeMajor === major.id ? styles.majorItemActive : '',
                      majorsListData?.findIndex(item => item.id === activeMajor) - 1 === index
                        ? styles.majorActiveBefore
                        : '',
                      majorsListData?.findIndex(item => item.id === activeMajor) + 1 === index
                        ? styles.majorActiveAfter
                        : '',
                    ].join(' ')}
                    onClick={() => {
                      handleMajorClick(major.id);
                    }}
                  >
                    <span>{major.label}</span>
                    {selectedMajors[major.id]?.length > 0 && (
                      <Badge count={selectedMajors[major.id]?.length}></Badge>
                    )}
                  </div>
                ))}
              </Col>
              <Col className={styles.majorColRight}>
                <div
                  className={[
                    styles.majorItem,
                    selectedMajors[activeMajor]?.length === majorList?.length
                      ? styles.majorItemActive
                      : '',
                  ].join(' ')}
                  onClick={() => {
                    handleSelectAll();
                  }}
                >
                  <span>全选</span>
                  <Checkbox
                    checked={
                      selectedMajors[activeMajor]?.length === majorList?.length &&
                      selectedMajors[activeMajor]?.length !== 0
                    }
                  />
                </div>

                {majorList?.map(major => (
                  <div
                    className={[
                      styles.majorItem,
                      selectedMajors[activeMajor]?.some(m => m.majorSubId === major.id)
                        ? styles.majorItemActive
                        : '',
                    ].join(' ')}
                    key={major.id}
                    onClick={() => {
                      handleMajorSelect(major.id, major.label);
                    }}
                  >
                    <span> {major.label}</span>
                    <Checkbox
                      checked={selectedMajors[activeMajor]?.some(m => m.majorSubId === major.id)}
                    />
                  </div>
                ))}
              </Col>
            </Row>
          </div>
        </Form.Item>
        <Form.Item
          key="unacceptableMajors"
          label="不能接受的专业"
          name="unacceptableMajors"
          rules={[{ required: false }]}
        >
          <Select
            placeholder="请选择不能接受的专业"
            mode="multiple"
            maxTagCount="responsive"
            options={unAcceptableMajorsOptions}
          />
        </Form.Item>
        <Form.Item
          key="acceptForeignSchool"
          label="是否接受中外合作专业"
          name="acceptForeignSchool"
          rules={[{ required: true }]}
        >
          <Select
            placeholder="请选择是否接受中外合作专业"
            options={[
              { value: false, label: '否' },
              { value: true, label: '是' },
            ]}
          />
        </Form.Item>
        <Form.Item
          key="tuitionRange"
          label="学费区间"
          name="tuitionRange"
          rules={[{ required: true, message: '请选择学费区间' }]}
        >
          <div>
            <Slider
              range
              min={0}
              max={100000}
              step={1000}
              value={tuitionRange}
              onChange={(value) => {
                setTuitionRange(value as [number, number]);
                form.setFieldsValue({ tuitionRange: value });
              }}
              marks={{
                0: '0元/年',
                100000: '10万/年',
              }}
              tooltip={{ formatter: (val) => {
                if (val === undefined) return '';
                if (val >= 10000) {
                  const wan = val / 10000;
                  const text = Number.isInteger(wan) ? wan.toFixed(0) : wan.toFixed(1);
                  return `${text}万/年`;
                }
                return `${val.toLocaleString()}元/年`;
              }}}
            />
            <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
              已选择：
              <span style={{ color: '#1890ff', fontWeight: 500, marginLeft: 4 }}>
                {tuitionRange[0] >= 10000
                  ? `${(tuitionRange[0] / 10000).toFixed(tuitionRange[0] % 10000 === 0 ? 0 : 1)}万/年`
                  : `${tuitionRange[0].toLocaleString()}元/年`}{' '}
                -{' '}
                {tuitionRange[1] >= 10000
                  ? `${(tuitionRange[1] / 10000).toFixed(tuitionRange[1] % 10000 === 0 ? 0 : 1)}万/年`
                  : `${tuitionRange[1].toLocaleString()}元/年`}
              </span>
            </div>
          </div>
        </Form.Item>
        <Form.Item
          key="preferredRegions"
          label="地区偏好选择"
          rules={[{ required: true }]}
          name="preferredRegions"
        >
          {regionProvinceList?.map((item: any) => {
            const regionProvinces = item.provinces || [];
            const isAllSelected = regionProvinces.length > 0 && regionProvinces.every((province: any) =>
              preferredRegions.some(m => m.provinceId === province.id)
            );
            const isPartSelected = regionProvinces.some((province: any) =>
              preferredRegions.some(m => m.provinceId === province.id)
            ) && !isAllSelected;
            
            return (
              <div className={styles.regionMajor} key={item.regionName}>
                <div className={styles.title}>
                  <span>{item.regionName}</span>
                  <Checkbox
                    style={{ marginLeft: 12 }}
                    checked={isAllSelected}
                    indeterminate={isPartSelected}
                    onChange={() => handleToggleRegion(regionProvinces)}
                  >
                    全选
                  </Checkbox>
                </div>
                <Flex wrap gap={8} className={styles.regionFlex}>
                  {regionProvinces.map((province: any) => (
                    <Col
                      className={[
                        styles.regionItem,
                        preferredRegions.some(m => m.provinceId === province.id)
                          ? styles.regionItemActive
                          : '',
                      ].join(' ')}
                      key={province.id}
                      onClick={() => {
                        handleProvinceClick(province.id, province.label);
                      }}
                    >
                      {province.label}
                    </Col>
                  ))}
                </Flex>
              </div>
            );
          })}
        </Form.Item>
        <Form.Item
          key="strategyType"
          label="志愿填报策略"
          rules={[{ required: true }]}
          name="strategyType"
        >
          <Select placeholder="请选择志愿填报策略" options={StrategyTypeListData} />
        </Form.Item>
        {/* <Form.Item key="targetType" label="填报思路" rules={[{ required: true }]} name="targetType">
          <Select placeholder="请选择填报思路" options={TargetListData} />
        </Form.Item> */}
      </Form>
      <Modal open={subjectOpen} onCancel={() => setSubjectOpen(false)} onOk={handleSubjectOk}>
        <SelectOption selectConfig={subjectSelectConfig} formDisabled={false} />
      </Modal>
      <Modal open={scoreOpen} onCancel={() => setScoreOpen(false)} onOk={handleScoreOk}>
        <div style={{ margin: '20px' }}>
          <SubjectScores
            ref={scoreFormRef}
            selectedSubjects={selectedSubjects}
            areaId={form.getFieldValue('areaId')}
          />
        </div>
      </Modal>
    </>
  );
});

export default ModalForm;
