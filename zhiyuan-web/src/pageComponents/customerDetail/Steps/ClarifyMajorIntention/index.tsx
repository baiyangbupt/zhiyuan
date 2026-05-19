import AudioContent from '@/pageComponents/customerDetail/Components/AudioContent';
import style from './style.module.scss';
import { Badge, Button, Checkbox, Col, Flex, Form, InputNumber, message, Radio, Row, Select, Slider, Switch } from 'antd';
import { IActions, ICollectflowRes, ISegments, ISubSteps } from '@/interface/api/customerDetail';
import { getStorage } from '@/utils/tool';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReturnPng from '@/images/icons/return.png';
import { LinkOutlined } from '@ant-design/icons';
import ModalImage from '../../Components/ModalImage';
import { getMajorRecommendApi } from '@/service/apis/customerDetail';
import useAuthParams from '@/hooks/useAuthParams';

const { Option } = Select;

interface ICollectflowProps {
  stepsData: ICollectflowRes;
  onNextStep: (btn: IActions, formValues?: any) => void;
  paramsValues: IMajorParams;
  onDraftChange?: (formValues?: any) => void;
  onBackStep?: () => void;
  savedValues?: any;
}

interface IMajorParams {
  province: {
    code: string;
    name: string;
  };
  sex: {
    code: string;
    name: string;
  };
  strengthSubjectList?: Array<{
    subject: string;
    subjectName: string;
    // score?: number; // 如果有分数可以加上
  }>;
  subjectList?: Array<{
    isFirst: number; // 1 表示首选，0 表示次选
    name: string;
    subjectType?: string;
    value: string;
  }>;
  subjectListSecond?: Array<{
    isFirst: number; // 1 表示首选，0 表示次选
    name: string;
    subjectType: string;
    value: string;
  }>;
  subjectScoreList?: Array<{
    score: number;
    subject: string;
    subjectName: string;
  }>;
  subjectType: {
    code: string;
    name: string;
  };
  batch?: {
    code: string;
    level: string;
    pos?: string;
    score: string;
    name: string;
  };
}

interface MajorSub {
  majorSubId: string;
  majorSubName: string;
}

interface Major {
  majorId: string;
  majorName: string;
}

interface RawMajor {
  label: string;
  value: string; // 父级 id
  children: {
    label: string;
    value: string; // 子专业 id
  }[];
}

interface SelectedMajor {
  major_id: string; // 子专业 id
  major: string; // 子专业名称
  score?: number;
}

// 返回值类型
interface SelectedMajorsMap {
  [parentId: string]: { majorSubId: string; majorSubName: string }[];
}

const ClarifyMajorIntention = (props: ICollectflowProps) => {
  const { stepsData, onNextStep, paramsValues, onDraftChange, onBackStep, savedValues } = props;
  const [isNextConfirmBtn, setIsNextConfirmBtn] = useState(false);
  const [formValues, setFormValues] = useState<any>(null); // 存储表单提交的值
  const [showSummary, setShowSummary] = useState(false); // 控制总结信息的显示

  const [currentImageUrl, setCurrentImageUrl] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const requiredFieldRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const { botId, tenantId } = useAuthParams();

  const scrollToRequiredField = (fieldId: string) => {
    const target = requiredFieldRefs.current[fieldId];
    target?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
      inline: 'nearest',
    });
  };

  const mapSelectedMajors = (
    rawData: RawMajor[],
    selectedData: SelectedMajor[]
  ): SelectedMajorsMap => {
    const result: SelectedMajorsMap = {};

    selectedData.forEach(item => {
      for (const parent of rawData || []) {
        const matchChild = parent.children?.find(child => child.value === item.major_id);
        if (matchChild) {
          if (!result[parent.value]) {
            result[parent.value] = [];
          }
          result[parent.value].push({
            majorSubId: matchChild.value,
            majorSubName: matchChild.label,
          });
          break; // 找到父级就跳出内层循环
        }
      }
    });

    return result;
  };

  const normalizePreferredMajors = () => {
    const preferredMajors = Array.isArray(savedValues?.preferredMajors)
      ? savedValues.preferredMajors
      : [];
    return preferredMajors.map((item: any) => ({
      major_id: item?.major_id || item?.majorId || item?.majorSubId || item?.value || '',
      major: item?.major || item?.majorName || item?.majorSubName || item?.label || '',
    }));
  };

  const hasSavedPreferredMajors = normalizePreferredMajors().length > 0;
  const hasSavedUnacceptableMajors = Array.isArray(savedValues?.unacceptableMajors) && savedValues.unacceptableMajors.length > 0;
  const hasSavedAcceptForeignSchool =
    savedValues?.acceptForeignSchool !== undefined && savedValues?.acceptForeignSchool !== null;
  const hasSavedTuitionRange = Boolean(savedValues?.tuitionRange);
  const buildRestoredDraftPayload = () => ({
    preferredMajors: Array.isArray(savedValues?.preferredMajors) ? savedValues.preferredMajors : [],
    unacceptableMajors: Array.isArray(savedValues?.unacceptableMajors) ? savedValues.unacceptableMajors : [],
    acceptForeignSchool: savedValues?.acceptForeignSchool,
    tuitionRange: savedValues?.tuitionRange
      ? {
          min: Number(savedValues.tuitionRange.min ?? savedValues.tuitionRange[0]),
          max: Number(savedValues.tuitionRange.max ?? savedValues.tuitionRange[1]),
        }
      : undefined,
  });

  const getBatchLevel = () => {
    const level: any = paramsValues?.batch?.level;
    if (level && typeof level === 'object') {
      return String(level.key || level.code || level.value || '');
    }
    return level ? String(level) : undefined;
  };

  // 根据 batch.level 获取正确的 majors 数据源
  const getMajorsByBatchLevel = (field: any) => {
    const batchLevel = getBatchLevel();
    if (batchLevel === '01') {
      return field?.bachelorMajors || field?.majors;
    } else if (batchLevel === '02') {
      return field?.associateMajors || field?.majors;
    }
    return field?.majors;
  };

  const getUnacceptableOptionsByBatchLevel = (field: any) => {
    const batchLevel = getBatchLevel();
    const bachelorMajors = Array.isArray(field?.bachelorMajors) ? field.bachelorMajors : [];
    const associateMajors = Array.isArray(field?.associateMajors) ? field.associateMajors : [];

    if (batchLevel === '01') {
      return bachelorMajors.length ? bachelorMajors : associateMajors;
    }
    if (batchLevel === '02') {
      return associateMajors.length ? associateMajors : bachelorMajors;
    }

    if (bachelorMajors.length || associateMajors.length) {
      return bachelorMajors.length ? bachelorMajors : associateMajors;
    }

    return [];
  };

  // 获取默认意向专业
  const getMajorRecommend = async () => {
    const { province, sex, strengthSubjectList, subjectList, subjectScoreList, subjectType, batch } =
      paramsValues;
    const params = {
      province,
      sex,
      strengthSubjectList,
      subjectList,
      subjectScoreList,
      subjectType,
      batch,
    };
    const res = await getMajorRecommendApi(tenantId, params);
    if (res.code === 0 && res.data?.length) {
      const field = stepsData?.subSteps
        .find(item => item.subStepId === 'major_preference_step1')
        ?.formConfig?.fields?.find(item => item.fieldId === 'preferredMajors');
      const rawData = (getMajorsByBatchLevel(field) || []) as any[];
      const initialSelected = mapSelectedMajors(rawData, res.data);
      
      // 保存系统推荐的快照（深拷贝）
      const snapshot = JSON.parse(JSON.stringify(initialSelected));
      setRecommendedMajorsSnapshot(snapshot);

      if (!hasSavedPreferredMajors) {
        setSelectedMajors(initialSelected);
        setIsRecommendationApplied(true);

        // ✅ 同步禁用非意向专业选项
        const allSelected = Object.values(initialSelected).flat();
        setDisabledUnacceptableMajors(allSelected.map(m => m.majorSubId));
      }
    }
  };

  useEffect(() => {
    getMajorRecommend();
  }, [stepsData, paramsValues?.batch?.level, savedValues]);

  // 点击查看图片
  const handleShowModal = (rich: any) => {
    setCurrentImageUrl(rich.materialUrl);
    setIsModalOpen(true);
  };
  // 下一步
  const handleClickNextStep = (btn: IActions) => {
    setIsNextConfirmBtn(true);
    const payload = buildDraftPayload();
    onNextStep(btn, payload);
  };

  const buildDraftPayload = () => {
    const allSelectedMajors = Object.values(selectedMajors).flat();
    return {
      preferredMajors: allSelectedMajors,
      unacceptableMajors: unacceptableMajors,
      acceptForeignSchool: acceptForeignSchool,
      tuitionRange: tuitionRange
        ? {
            min: tuitionRange[0],
            max: tuitionRange[1],
          }
        : undefined,
    };
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
            const option = field.options.find(opt => opt.value === value);
            console.log('option', option);
            if (option) {
              texts.push(`${option.label}${fieldId === 'examYear' ? '高考' : ''}`);
            } else {
              texts.push(`${value}`);
            }
          }
        }
      });
    });

    return texts.join('，');
  };
  const [activeMajor, setActiveMajor] = useState<string>('1');
  const handleMajorClick = (majorId: string) => {
    setActiveMajor(majorId);
  };

  const majorList = useMemo(() => {
    const field = stepsData?.subSteps
      .find(item => item.subStepId === 'major_preference_step1')
      ?.formConfig?.fields?.find(f => f.fieldId === 'preferredMajors');
    const majors = getMajorsByBatchLevel(field) || [];
    return majors.find((major: any) => major.value === activeMajor)?.children;
  }, [activeMajor, paramsValues?.batch?.level, stepsData]);

  const [selectedMajors, setSelectedMajors] = useState<{
    [major: string]: MajorSub[];
  }>({});

  // 保存系统推荐的原始数据快照
  const [recommendedMajorsSnapshot, setRecommendedMajorsSnapshot] = useState<{
    [major: string]: MajorSub[];
  }>({});
  
  // 标记是否应用了系统推荐
  const [isRecommendationApplied, setIsRecommendationApplied] = useState<boolean>(false);

  const [unacceptableMajors, setUnacceptableMajors] = useState<Major[]>([]);
  const [disabledUnacceptableMajors, setDisabledUnacceptableMajors] = useState<string[]>([]);
  const [disabledPreferredMajors, setDisabledPreferredMajors] = useState<string[]>([]);

  const handleMajorSelect = (value: string, label: string) => {
    const currentMajorSubs = selectedMajors[activeMajor] || [];
    const alreadySelected = currentMajorSubs.some(m => m.majorSubId === value);

    let newSelected;
    if (alreadySelected) {
      newSelected = currentMajorSubs.filter(m => m.majorSubId !== value);
    } else {
      newSelected = [...currentMajorSubs, { majorSubId: value, majorSubName: label }];
    }

    const newSelectedMajors = {
      ...selectedMajors,
      [activeMajor]: newSelected,
    };

    setSelectedMajors(newSelectedMajors);

    // ✅ 更新禁用的非意向专业选项
    const allSelected = Object.values(newSelectedMajors).flat();
    setDisabledUnacceptableMajors(allSelected.map(m => m.majorSubId));
  };

  const handleSelectAll = () => {

    const allSelected = selectedMajors[activeMajor] || [];
    const allIds = (majorList || []).map((item: any) => item.value);
    const isAllSelected = allIds.length > 0 && allIds.every((id: string) => allSelected.some(m => m.majorSubId === id));

    let newSelected;
    if (isAllSelected) {
      newSelected = [];
    } else {
      newSelected = (majorList || []).map((item: any) => ({
        majorSubId: item.value,
        majorSubName: item.label,
      }));
    }

    const newSelectedMajors = {
      ...selectedMajors,
      [activeMajor]: newSelected,
    };

    setSelectedMajors(newSelectedMajors);

    // ✅ 同步禁用非意向专业
    const allSelectedNew = Object.values(newSelectedMajors).flat();
    setDisabledUnacceptableMajors(allSelectedNew.map(m => m.majorSubId));
  };

  const handleUnacceptableMajorClick = (value: string, label: string) => {
    let newUnacceptable;
    if (unacceptableMajors.some(m => m.majorId === value)) {
      newUnacceptable = unacceptableMajors.filter(m => m.majorId !== value);
    } else {
      newUnacceptable = [...unacceptableMajors, { majorId: value, majorName: label }];
    }
    setUnacceptableMajors(newUnacceptable);

    // ✅ 更新禁用的意向专业选项
    setDisabledPreferredMajors(newUnacceptable.map(m => m.majorId));
  };

  const handleUnacceptableSelectAll = (unacceptableOptions: any[]) => {
    // 获取所有可选项（排除被禁用的）
    const availableOptions = unacceptableOptions.filter(
      item => !disabledUnacceptableMajors.includes(item.value)
    );
    const availableIds = availableOptions.map(item => item.value);
    
    // 检查所有可选项是否都已选中
    const isAllSelected = availableIds.length > 0 && 
      availableIds.every(id => unacceptableMajors.some(m => m.majorId === id));

    let newUnacceptable;
    if (isAllSelected) {
      // 如果全部选中，则取消所有选择
      newUnacceptable = unacceptableMajors.filter(
        m => !availableIds.includes(m.majorId)
      );
    } else {
      // 如果未全部选中，则选中所有可选项
      const existingIds = unacceptableMajors.map(m => m.majorId);
      const toAdd = availableOptions
        .filter(item => !existingIds.includes(item.value))
        .map(item => ({ majorId: item.value, majorName: item.label }));
      newUnacceptable = [...unacceptableMajors, ...toAdd];
    }
    
    setUnacceptableMajors(newUnacceptable);
    
    // ✅ 更新禁用的意向专业选项
    setDisabledPreferredMajors(newUnacceptable.map(m => m.majorId));
  };

  // 切换推荐状态：取消推荐或恢复推荐
  const handleToggleRecommendation = (checked: boolean) => {
    if (checked) {
      // 恢复推荐：恢复到系统推荐的原始状态
      const snapshot = JSON.parse(JSON.stringify(recommendedMajorsSnapshot));
      setSelectedMajors(snapshot);
      setIsRecommendationApplied(true);
      
      // 重新计算并设置禁用的非意向专业选项
      const allSelected = Object.values(snapshot).flat() as MajorSub[];
      setDisabledUnacceptableMajors(allSelected.map((m: MajorSub) => m.majorSubId));
    } else {
      // 取消推荐：清空所有选择
      setSelectedMajors({});
      setDisabledUnacceptableMajors([]);
      setIsRecommendationApplied(false);
    }
  };

  const [acceptForeignSchool, setAcceptForeignSchool] = useState<Boolean>();
  const [tuitionRange, setTuitionRange] = useState<[number, number]>([0, 1000000]);

  const [messageApi, contextHolder] = message.useMessage();

  useEffect(() => {
    const field = stepsData?.subSteps
      .find(item => item.subStepId === 'major_preference_step1')
      ?.formConfig?.fields?.find(f => f.fieldId === 'preferredMajors');
    const rawData = (getMajorsByBatchLevel(field) || []) as any[];
    const savedPreferredMajors = normalizePreferredMajors();
    const hasSavedDraftValues =
      savedPreferredMajors.length > 0 ||
      hasSavedUnacceptableMajors ||
      hasSavedAcceptForeignSchool ||
      hasSavedTuitionRange;

    if (!hasSavedDraftValues) {
      setSelectedMajors({});
      setUnacceptableMajors([]);
      setDisabledUnacceptableMajors([]);
      setDisabledPreferredMajors([]);
      setRecommendedMajorsSnapshot({});
      setIsRecommendationApplied(false);
      setActiveMajor('1');
      setAcceptForeignSchool(undefined);
      const tuitionField = stepsData?.subSteps
        .find(item => item.subStepId === 'major_preference_step1')
        ?.formConfig?.fields?.find(f => f.fieldId === 'tuitionRange') as any;
      const min = tuitionField?.min ?? 0;
      const max = tuitionField?.max ?? 1000000;
      setTuitionRange([
        tuitionField?.defaultValue?.minValue ?? min,
        tuitionField?.defaultValue?.maxValue ?? max,
      ]);
      setFormValues(null);
      setShowSummary(false);
      setIsNextConfirmBtn(false);
      return;
    }

    if (savedPreferredMajors.length) {
      const restoredSelected = mapSelectedMajors(rawData, savedPreferredMajors as SelectedMajor[]);
      setSelectedMajors(restoredSelected);
      setIsRecommendationApplied(false);
      const allSelected = Object.values(restoredSelected).flat();
      setDisabledUnacceptableMajors(allSelected.map(m => m.majorSubId));
      const firstActiveMajor = Object.keys(restoredSelected)[0];
      if (firstActiveMajor) {
        setActiveMajor(firstActiveMajor);
      }
    }

    if (Array.isArray(savedValues?.unacceptableMajors)) {
      setUnacceptableMajors(savedValues.unacceptableMajors);
      setDisabledPreferredMajors(savedValues.unacceptableMajors.map((m: Major) => m.majorId));
    }

    if (savedValues?.acceptForeignSchool !== undefined) {
      setAcceptForeignSchool(Boolean(savedValues.acceptForeignSchool));
    } else {
      setAcceptForeignSchool(undefined);
    }

    if (savedValues?.tuitionRange) {
      const min = Number(savedValues.tuitionRange.min ?? savedValues.tuitionRange[0]);
      const max = Number(savedValues.tuitionRange.max ?? savedValues.tuitionRange[1]);
      if (!Number.isNaN(min) && !Number.isNaN(max)) {
        setTuitionRange([min, max]);
      }
    } else {
      const tuitionField = stepsData?.subSteps
        .find(item => item.subStepId === 'major_preference_step1')
        ?.formConfig?.fields?.find(f => f.fieldId === 'tuitionRange') as any;
      const min = tuitionField?.min ?? 0;
      const max = tuitionField?.max ?? 1000000;
      setTuitionRange([
        tuitionField?.defaultValue?.minValue ?? min,
        tuitionField?.defaultValue?.maxValue ?? max,
      ]);
    }

    setFormValues(buildRestoredDraftPayload());
    setShowSummary(true);
    setIsNextConfirmBtn(false);
  }, [stepsData, savedValues, paramsValues?.batch?.level]);

  const handleConfirm = (fields: any[]) => {
    console.log('fields', fields);
    // 根据字段 required 动态校验
    for (const field of fields) {
      if (field.required) {
        if (field.fieldId === 'preferredMajors') {
          const allSelectedMajors = Object.values(selectedMajors).flat();
          if (allSelectedMajors.length === 0) {
            scrollToRequiredField(field.fieldId);
            messageApi.error('请选择专业');
            return;
          }
        }
        if (field.fieldId === 'unacceptableMajors') {
          if (!unacceptableMajors?.length) {
            scrollToRequiredField(field.fieldId);
            messageApi.error('请选择不接受的专业');
            return;
          }
        }
        if (field.fieldId === 'acceptForeignSchool') {
          if (acceptForeignSchool !== true && acceptForeignSchool !== false) {
            scrollToRequiredField(field.fieldId);
            messageApi.error('请选择是否接受外国学校');
            return;
          }
        }
        if (field.fieldId === 'tuitionRange') {
          if (!tuitionRange || tuitionRange[0] === undefined || tuitionRange[1] === undefined) {
            scrollToRequiredField(field.fieldId);
            messageApi.error('请选择学费区间');
            return;
          }
        }
      }
    }
    onDraftChange?.(buildDraftPayload());
    setShowSummary(true);
  };

  useEffect(() => {
    if (showSummary) {
      scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [showSummary]);

  return (
    <div className={style.confirmGkInfoContainer}>
      {contextHolder}
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
                      marginLeft: 8,
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
          {item.formConfig && (
            <div className={style.confirmForm}>
              <div className={style.title}>{item.formConfig.title}</div>
              {item.formConfig?.fields?.map(field => {
                if (field.fieldId === 'preferredMajors') {
                  // 检查是否有系统推荐数据
                  const hasRecommendation = Object.keys(recommendedMajorsSnapshot).length > 0;
                  // 根据 batch.level 获取正确的 majors 数据源
                  const majors = getMajorsByBatchLevel(field);
                  
                  return (
                    <div
                      className="preferred-major"
                      key={field.fieldId}
                      ref={node => {
                        requiredFieldRefs.current[field.fieldId] = node;
                      }}
                    >
                      <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
                        <div className="title">{field.fieldName}</div>
                        {hasRecommendation && (
                          <Flex align="center" gap={8}>
                            <span style={{ fontSize: 12, color: '#666' }}>
                              {isRecommendationApplied ? '一键移除推荐' : '恢复推荐'}
                            </span>
                            <Switch
                              checked={isRecommendationApplied}
                              onChange={handleToggleRecommendation}
                              size="small"
                            />
                          </Flex>
                        )}
                      </Flex>
                          {field.helpConfig && field.helpConfig?.position === 'top' && (
                            <div className="subTitle" style={{ color: '#414455', fontSize: 12 }}>
                              {field.helpConfig?.helpText}
                            </div>
                          )}
                      <Row className="major-row">
                        <Col className="major-col-left">
                          {majors?.map((major: any) => (
                            <div
                              key={major.value}
                              className={[
                                'major-item',
                                activeMajor === major.value ? 'major-item-active' : '',
                              ].join(' ')}
                              onClick={() => {
                                handleMajorClick(major.value);
                              }}
                            >
                              <span>{major.label}</span>
                              {selectedMajors[major.value]?.length > 0 && (
                                <Badge count={selectedMajors[major.value]?.length}></Badge>
                              )}
                            </div>
                          ))}
                        </Col>
                        <Col className="major-col-right">
                          <div
                            className={[
                              'major-item',
                              selectedMajors[activeMajor]?.length === majorList?.length
                                ? 'major-item-active'
                                : '',
                            ].join(' ')}
                            onClick={() => {
                              handleSelectAll();
                            }}
                          >
                            <span>全选</span>
                            <Checkbox
                              checked={selectedMajors[activeMajor]?.length === majorList?.length}
                            />
                          </div>
                          {majorList?.map((major: any) => {
                            const isSelected = selectedMajors[activeMajor]?.some(
                              m => m.majorSubId === major.value
                            );
                            const isDisabled = disabledPreferredMajors.includes(major.value);

                            return (
                              <div
                                className={[
                                  'major-item',
                                  isSelected ? 'major-item-active' : '',
                                  isDisabled ? 'major-item-disabled' : '',
                                ].join(' ')}
                                key={major.value}
                                onClick={() => {
                                  // handleMajorSelect(major.value, major.label);
                                  if (!isDisabled) handleMajorSelect(major.value, major.label);
                                }}
                              >
                                <span> {major.label}</span>
                                {/* <Checkbox
                                  checked={selectedMajors[activeMajor]?.some(
                                    m => m.majorSubId === major.value
                                  )}
                                /> */}
                                <Checkbox checked={isSelected} disabled={isDisabled} />
                              </div>
                            );
                          })}
                        </Col>
                      </Row>

                        {field.helpConfig && !field.helpConfig?.position && (
                          <div style={{ margin: '8px 0' }}>
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
                              onClick={() => handleShowModal(field.helpConfig!.rich)}
                            >
                              {field.helpConfig.rich.title}
                            </span>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                }

                if (field.fieldId === 'unacceptableMajors') {
                  const unacceptableOptions = getUnacceptableOptionsByBatchLevel(field);
                  
                  // 计算可选项（排除被禁用的）
                  const availableOptions = unacceptableOptions.filter(
                    (item: any) => !disabledUnacceptableMajors.includes(item.value)
                  );
                  const availableIds = availableOptions.map((item: any) => item.value);
                  const isAllSelected = availableIds.length > 0 && 
                    availableIds.every((id: string) => unacceptableMajors.some(m => m.majorId === id));

                  return (
                    <div
                      className="unacceptable-major"
                      key={field.fieldId}
                      ref={node => {
                        requiredFieldRefs.current[field.fieldId] = node;
                      }}
                    >
                      <div className="title">{field.fieldName}</div>
                        {field.helpConfig && field.helpConfig?.position === 'top' && (
                          <div className="subTitle" style={{ color: '#414455', fontSize: 12 }}>
                            {field.helpConfig?.helpText}
                          </div>
                        )}
                      <Flex wrap gap={8} className="unacceptable-flex">
                        <Col
                          className={[
                            'unacceptable-item',
                            isAllSelected ? 'unacceptable-item-active' : '',
                          ].join(' ')}
                          onClick={() => {
                            handleUnacceptableSelectAll(unacceptableOptions);
                          }}
                          style={{
                            cursor: 'pointer',
                          }}
                        >
                          <span>全选</span>
                          <Checkbox checked={isAllSelected} />
                        </Col>
                        {unacceptableOptions?.map((item: any) => {
                          const isSelected = unacceptableMajors.some(m => m.majorId === item.value);
                          const isDisabled = disabledUnacceptableMajors.includes(item.value);

                          return (
                            <Col
                              className={[
                                'unacceptable-item',
                                isSelected ? 'unacceptable-item-active' : '',
                                isDisabled ? 'unacceptable-item-disabled' : '',
                              ].join(' ')}
                              key={item.value}
                              onClick={() => {
                                // handleUnacceptableMajorClick(item.value, item.label);
                                if (!isDisabled)
                                  handleUnacceptableMajorClick(item.value, item.label);
                              }}
                              style={{
                                cursor: isDisabled ? 'not-allowed' : 'pointer',
                                opacity: isDisabled ? 0.5 : 1,
                              }}
                            >
                              {item.label}
                            </Col>
                          );
                        })}
                      </Flex>

                      {field.helpConfig && !field.helpConfig?.position && (
                        <div style={{ margin: '8px 0' }}>
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
                              onClick={() => handleShowModal(field.helpConfig!.rich)}
                            >
                              {field.helpConfig.rich.title}
                            </span>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                }
                if (field.fieldId === 'acceptForeignSchool') {
                  return (
                    <div
                      className="accept-foreign-school"
                      key={field.fieldId}
                      ref={node => {
                        requiredFieldRefs.current[field.fieldId] = node;
                      }}
                    >
                      <div className="title">{field.fieldName}</div>
                {field.helpConfig && field.helpConfig?.position === 'top' && (
                  <div className="subTitle" style={{ color: '#414455', fontSize: 12 }}>
                    {field.helpConfig?.helpText}
                  </div>
                )}
                      <Flex justify="space-between">
                        <Col
                          span={12}
                          className={[
                            'unacceptable-item',
                            acceptForeignSchool === true ? 'unacceptable-item-active' : '',
                          ].join(' ')}
                          style={{ marginRight: 4 }}
                          onClick={() => setAcceptForeignSchool(true)}
                        >
                          能
                        </Col>
                        <Col
                          span={12}
                          className={[
                            'unacceptable-item',
                            acceptForeignSchool === false ? 'unacceptable-item-active' : '',
                          ].join(' ')}
                          style={{ marginLeft: 4 }}
                          onClick={() => setAcceptForeignSchool(false)}
                        >
                          不能
                        </Col>
                      </Flex>

                      {field.helpConfig && !field.helpConfig?.position && (
                        <div style={{ margin: '8px 0' }}>
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
                              onClick={() => handleShowModal(field.helpConfig!.rich)}
                            >
                              {field.helpConfig.rich.title}
                            </span>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                }
                if (field.fieldId === 'tuitionRange') {
                  // 从配置中获取区间参数，如果没有则使用默认值
                  const fieldConfig = field as any;
                  const min = fieldConfig.min ?? 0;
                  const max = fieldConfig.max ?? 1000000;
                  const step = fieldConfig.step ?? 10000;
                  const unit = fieldConfig.unit ?? '元/年';

                  // 格式化标记和展示文案
                  const formatMark = (value: number) => {
                    if (value >= 10000) {
                      return `${(value / 10000).toFixed(0)}万${unit}`;
                    }
                    return `${value}${unit}`;
                  };

                  const formatValue = (value: number) => {
                    if (value >= 10000) {
                      const wan = value / 10000;
                      // 大于等于 1 万时按“x.x万/年”显示，去掉多余的小数 0
                      const text = Number.isInteger(wan) ? wan.toFixed(0) : wan.toFixed(1);
                      return `${text}万${unit}`;
                    }
                    // 小于 1 万时展示具体数字并加千分位
                    return `${value.toLocaleString()}${unit}`;
                  };

                  return (
                    <div
                      className="tuitionRange"
                      key={field.fieldId}
                      ref={node => {
                        requiredFieldRefs.current[field.fieldId] = node;
                      }}
                    >
                      <div className="title">{field.fieldName}</div>
                      {field.helpConfig && field.helpConfig?.position === 'top' && (
                        <div className="subTitle">
                          {field.helpConfig?.helpText}
                        </div>
                      )}
                      <div className="sliderWrapper">
                        <Slider
                          range
                          min={min}
                          max={max}
                          step={step}
                          value={tuitionRange}
                          onChange={(value) => setTuitionRange(value as [number, number])}
                          marks={{
                            [min]: formatMark(min),
                            [max]: formatMark(max),
                          }}
                        />
                        <div className="selectedRange">
                          已选择：
                          <span className="rangeValue">
                            {formatValue(tuitionRange[0])} - {formatValue(tuitionRange[1])}
                          </span>
                        </div>
                      </div>

                      {field.helpConfig && !field.helpConfig?.position && (
                        <div style={{ margin: '8px 0' }}>
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
                              onClick={() => handleShowModal(field.helpConfig!.rich)}
                            >
                              {field.helpConfig.rich.title}
                            </span>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                }
              })}
              <Row justify="center" style={{ marginTop: 12 }}>
                <div className={style.formActions}>
                  {onBackStep && (
                    <Button className={style.backActionButton} onClick={onBackStep}>
                      上一步
                    </Button>
                  )}
                  <Button
                    className={style.submitActionButton}
                    onClick={() => handleConfirm(item.formConfig?.fields)}
                  >
                    确认提交
                  </Button>
                </div>
              </Row>
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
                    onClick={() => handleClickNextStep(btn)}
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

export default ClarifyMajorIntention;
