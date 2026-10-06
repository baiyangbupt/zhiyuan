import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Spin, message } from 'antd';
import { BulbOutlined, EditOutlined } from '@ant-design/icons';
import {
  getBatchList,
  getProvinceLists,
  getSubjectPolicy,
  updateSessionScoreDetailApi,
} from '@/service/apis/sessionDetail';
import { getPositionRangeApi } from '@/service/apis/customerDetail';
import SubjectScores, { IRefParams } from '@/pageComponents/session/subjectScores';
import SelectOption from '@/pageComponents/session/selectOption';
import useForm from '@/pageComponents/session/ModalForm/useForm';
import { buildCreateSessionBatchPayload } from '@/utils/customerDetailSession';
import {
  HAINAN_PROVINCE_CODE,
  resolveTotalScoreLabel,
  validateHainanTotalScore,
} from '@/utils/scoreRules.mjs';
import type {
  IScoreDetailSubjectScore,
  IUpdateScoreDetailParams,
  IUpdateScoreDetailRes,
} from '@/interface/api/sessionDetail';
import styles from './style.module.scss';

/** 文理分科（01 政策）下固定计入的科目（与 ModalForm 口径一致）。 */
const LSubject = ['物理', '化学', '生物'];
const WSubject = ['政治', '历史', '地理'];
/** 语数外的 subject 编码与建会话 subjectScoreList 一致（08/10/11）。 */
const MAIN_SUBJECT_SCORES: IScoreDetailSubjectScore[] = [
  { subject: '08', subjectName: '语文', score: 0 },
  { subject: '10', subjectName: '数学', score: 0 },
  { subject: '11', subjectName: '英语', score: 0 },
];

export interface ScoreSupplementEntryProps {
  onOpen: () => void;
  disabled?: boolean;
}

/** 工作台上的空会话入口卡：缺成绩时展示，补录成功后由父组件隐藏。 */
export const ScoreSupplementEntry: React.FC<ScoreSupplementEntryProps> = ({ onOpen, disabled }) => (
  <div className={styles.entryCard}>
    <div className={styles.entryIcon}>
      <BulbOutlined />
    </div>
    <div className={styles.entryBody}>
      <div className={styles.entryTitle}>补充成绩，解锁推荐与方案</div>
      <div className={styles.entryDesc}>
        当前会话还没有成绩信息。补全高考省份、选科、各科成绩、总分与批次后，系统会为你刷新候选院校与志愿方案。
      </div>
    </div>
    <Button type="primary" icon={<EditOutlined />} onClick={onOpen} disabled={disabled}>
      补充成绩
    </Button>
  </div>
);

export interface ScoreSupplementModalProps {
  open: boolean;
  tenantId: string;
  chatSessionId: string;
  examYear?: number | string | null;
  prepareTypeCode?: string | null;
  prepareTypeDesc?: string;
  onCancel: () => void;
  onSuccess: (res: IUpdateScoreDetailRes) => void;
}

/**
 * 空会话「补充成绩」表单弹窗。
 *
 * 字段与联动复用建会话链路的现成资产：`ModalForm/useForm`（省份→选科政策→科目选择→批次）、
 * `session/subjectScores`（各科成绩输入与分值上限校验）、`session/selectOption`（科目选择器）。
 * 只保留端点必填的字段：省份、选科、各科成绩、总分、批次（位次可选，自动计算）。
 */
const ScoreSupplementModal: React.FC<ScoreSupplementModalProps> = ({
  open,
  tenantId,
  chatSessionId,
  examYear,
  prepareTypeCode,
  prepareTypeDesc,
  onCancel,
  onSuccess,
}) => {
  const [form] = Form.useForm();
  const {
    memberScoreByType,
    subjectSelectConfig,
    getParams,
    setSubjectType,
    setSelectedArtsOrSciences,
    setSelectedFirstSubject,
    setSelectedSecondSubject,
  } = useForm(form);

  const [provinceList, setProvinceList] = useState<any[]>([]);
  const [batchOptions, setBatchOptions] = useState<any[]>([]);
  const [batchListRaw, setBatchListRaw] = useState<any[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);
  const [selectedSubjects, setSelectedSubjects] = useState<string[]>([]);
  const [scoreEntries, setScoreEntries] = useState<IScoreDetailSubjectScore[]>([]);
  const [subjectOpen, setSubjectOpen] = useState(false);
  const [scoreOpen, setScoreOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  const scoreFormRef = useRef<IRefParams>(null);
  const policyRef = useRef<any>(null);
  const paramsRef = useRef<any>(null);
  const subjectSignatureRef = useRef('');
  const lastPositionKeyRef = useRef('');

  const provinceValue = Form.useWatch('province', form);
  const batchValue = Form.useWatch('batch', form);
  const totalScoreValue = Form.useWatch('totalScore', form);
  const isHainanProvince = provinceValue === HAINAN_PROVINCE_CODE;
  const totalScoreReady =
    totalScoreValue !== undefined && totalScoreValue !== null && totalScoreValue !== '';

  const loadProvinceList = async () => {
    try {
      const { code, data } = await getProvinceLists();
      if (code === 0 && data) {
        setProvinceList(data);
      }
    } catch (error) {
      console.warn('获取省份列表失败', error);
    }
  };

  const clearScoreInputs = () => {
    setSelectedSubjects([]);
    setScoreEntries([]);
    scoreFormRef.current?.form.resetFields();
  };

  /** 省份变化后：重置下游所有字段（与建会话表单 clearSubject 同语义）。 */
  const resetDownstream = () => {
    setSubjectType(undefined);
    setSelectedArtsOrSciences([]);
    setSelectedFirstSubject([]);
    setSelectedSecondSubject([]);
    setBatchOptions([]);
    setBatchListRaw([]);
    paramsRef.current = null;
    subjectSignatureRef.current = '';
    lastPositionKeyRef.current = '';
    clearScoreInputs();
    form.setFieldsValue({
      subjects: undefined,
      scores: undefined,
      totalScore: undefined,
      batch: undefined,
      totalScorePos: undefined,
    });
  };

  const handleProvinceChange = async (areaId: string) => {
    setFormError('');
    resetDownstream();
    const { code, data } = await getSubjectPolicy(areaId);
    if (code === 0 && data) {
      policyRef.current = data;
      memberScoreByType(data);
    } else {
      message.error('获取该省份选科政策失败，请重试');
    }
  };

  const openSubjectModal = () => {
    if (!provinceValue) {
      message.error('请先选择高考省份');
      return;
    }
    setSubjectOpen(true);
  };

  const openScoreModal = () => {
    if (!selectedSubjects.length) {
      message.error('请先选择高考科目');
      return;
    }
    setScoreOpen(true);
  };

  const resolveSubjectNames = (p: any) => {
    if (p?.type === 'L') {
      return LSubject;
    }
    if (p?.type === 'W') {
      return WSubject;
    }
    const configGroups = subjectSelectConfig.flatMap(group => group.config.data as any[]);
    return (p?.subjectList || [])
      .map((item: any) => configGroups.find(config => config.value === item.subject)?.name)
      .filter(Boolean) as string[];
  };

  const fetchBatchOptions = async (subjectCode: string) => {
    const policyPrepareType = policyRef.current?.prepareType?.code;
    const effectivePrepareType = policyPrepareType || prepareTypeCode || '';
    if (!provinceValue || !effectivePrepareType) {
      message.error('未获取到填报类型，请重新选择省份');
      return;
    }
    setBatchLoading(true);
    try {
      const { code, data } = await getBatchList({
        areaId: provinceValue,
        prepareType: effectivePrepareType,
        subject: subjectCode,
      });
      if (code === 0 && data?.batchList) {
        setBatchListRaw(data.batchList);
        setBatchOptions(
          data.batchList.map((item: any) => ({
            value: item.batch,
            label:
              buildCreateSessionBatchPayload(item)?.name ||
              item.batchTitle ||
              String(item.batch),
          }))
        );
      } else {
        message.error('获取批次信息失败');
      }
    } catch (error) {
      message.error('获取批次信息异常，请稍后重试');
    } finally {
      setBatchLoading(false);
    }
  };

  const handleSubjectOk = () => {
    const p = getParams();
    if (!p?.type || !(p.subjectTypeObject as any)?.code) {
      message.warning('请完整选择高考科目');
      return;
    }
    paramsRef.current = p;
    setSubjectOpen(false);
    const names = resolveSubjectNames(p);
    setSelectedSubjects(names);
    form.setFieldsValue({ subjects: names.join('、') });

    const signature = JSON.stringify([
      p.type,
      ...(p.subjectList || []).map((item: any) => `${item.subject}:${item.isFirst}`),
    ]);
    if (subjectSignatureRef.current && subjectSignatureRef.current !== signature) {
      // 科目变更后旧成绩/批次不再可信，清空重填。
      clearScoreInputs();
      form.setFieldsValue({ scores: undefined, totalScore: undefined, batch: undefined, totalScorePos: undefined });
    }
    subjectSignatureRef.current = signature;
    fetchBatchOptions(p.type);
  };

  const handleScoreOk = async () => {
    const scoreForm = scoreFormRef.current?.form;
    if (!scoreForm) {
      return;
    }
    let values: any;
    try {
      values = await scoreForm.validateFields();
    } catch (error) {
      return;
    }
    const configGroups = subjectSelectConfig.flatMap(group => group.config.data as any[]);
    const entries: IScoreDetailSubjectScore[] = MAIN_SUBJECT_SCORES.map((item, index) => ({
      ...item,
      score: Number(values[`grades${index + 1}`]),
    }));
    selectedSubjects.forEach((name, index) => {
      const config = configGroups.find(item => item.name === name);
      if (config) {
        entries.push({
          subject: config.value,
          subjectName: name,
          score: Number(values[`grades${index + 4}`]),
        });
      }
    });
    setScoreEntries(entries);
    form.setFieldValue(
      'scores',
      entries.map(item => `${item.subjectName}${item.score}`).join('、')
    );
    if (!isHainanProvince) {
      const total = entries.reduce((acc, item) => acc + (item.score || 0), 0);
      form.setFieldValue('totalScore', total);
    }
    setScoreOpen(false);
  };

  // 位次自动计算（可选字段，失败不阻塞提交）。
  useEffect(() => {
    if (!open || !totalScoreReady || !batchValue || !provinceValue) {
      return;
    }
    const subjectCode = paramsRef.current?.type;
    if (!subjectCode) {
      return;
    }
    if (isHainanProvince) {
      const score = Number(totalScoreValue);
      if (Number.isNaN(score) || score < 100 || score > 900) {
        return;
      }
    }
    const dataLevel = batchOptions.find(item => item.value === batchValue)?.level;
    const requestKey = `${provinceValue}:${subjectCode}:${dataLevel || ''}:${totalScoreValue}`;
    if (lastPositionKeyRef.current === requestKey) {
      return;
    }
    lastPositionKeyRef.current = requestKey;
    getPositionRangeApi({
      areaId: provinceValue,
      subject: subjectCode,
      dataLevel,
      year: examYear ? String(examYear) : '',
      score: String(totalScoreValue),
    } as any)
      .then(({ code, data }) => {
        if (code === 0 && data) {
          form.setFieldValue('totalScorePos', data.lowestRank || undefined);
        }
      })
      .catch(() => {
        // 位次为可选项：计算失败留给用户手填。
      });
  }, [
    open,
    provinceValue,
    batchValue,
    batchOptions,
    totalScoreReady,
    totalScoreValue,
    isHainanProvince,
    examYear,
    form,
  ]);

  // 打开时重置，保证每次都是干净表单。
  useEffect(() => {
    if (!open) {
      return;
    }
    setFormError('');
    setSubmitting(false);
    form.resetFields();
    resetDownstream();
    if (!provinceList.length) {
      loadProvinceList();
    }
  }, [open]);

  const handleSubmit = async () => {
    setFormError('');
    try {
      await form.validateFields();
    } catch (error) {
      return;
    }
    const provinceOption = provinceList.find(item => item.code === provinceValue);
    if (!provinceOption) {
      setFormError('请选择高考省份');
      return;
    }
    const p = paramsRef.current;
    const subjectTypeObject = (p?.subjectTypeObject || {}) as { code?: string; desc?: string };
    if (!p?.type || !subjectTypeObject.code) {
      setFormError('请选择高考科目');
      return;
    }
    if (scoreEntries.length !== selectedSubjects.length + MAIN_SUBJECT_SCORES.length) {
      setFormError('请重新填写各科成绩');
      return;
    }
    const batchRaw = batchListRaw.find(item => item.batch === batchValue);
    const batchPayload = buildCreateSessionBatchPayload(batchRaw);
    if (!batchPayload?.code) {
      setFormError('请选择填报批次');
      return;
    }
    const totalScore = Number(form.getFieldValue('totalScore'));
    if (!Number.isFinite(totalScore)) {
      setFormError('请填写成绩');
      return;
    }
    const totalScorePosValue = form.getFieldValue('totalScorePos');
    const examYearValue = Number(examYear);
    const payload: IUpdateScoreDetailParams = {
      province: { code: provinceOption.code, name: provinceOption.label },
      batch: {
        code: batchPayload.code,
        name: batchPayload.name || batchRaw?.batchTitle || '',
        level: batchPayload.level || batchRaw?.level?.key || '',
        score: batchPayload.score,
      },
      subjectType: {
        code: subjectTypeObject.code,
        desc: subjectTypeObject.desc || prepareTypeDesc || '',
      },
      subjectScoreList: scoreEntries,
      totalScore,
      ...(totalScorePosValue !== undefined && totalScorePosValue !== null
        ? { totalScorePos: Number(totalScorePosValue) }
        : {}),
      ...(Number.isFinite(examYearValue) && examYearValue > 0 ? { examYear: examYearValue } : {}),
    };

    setSubmitting(true);
    try {
      const { code, data, msg } = await updateSessionScoreDetailApi(tenantId, chatSessionId, payload);
      if (code === 0 && data?.success) {
        message.success('成绩已补充，正在刷新推荐与方案');
        onSuccess(data);
        return;
      }
      if (code === 110) {
        setFormError(msg || '请检查填写信息后重试');
        return;
      }
      if (code === 84009 || code === -1) {
        message.error(`${msg || '补充成绩失败'}，请刷新页面后重试`);
        return;
      }
      message.error(msg || '补充成绩失败，请稍后重试');
    } catch (error) {
      // 403 等错误已由全局拦截器提示（不改全局错误处理）。
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="补充成绩"
      open={open}
      width={560}
      okText="提交"
      cancelText="取消"
      confirmLoading={submitting}
      onOk={handleSubmit}
      onCancel={onCancel}
      maskClosable={false}
    >
      <div className={styles.modalBody}>
        {formError ? (
          <Alert
            className={styles.formAlert}
            type="error"
            showIcon
            message={formError}
            closable
            onClose={() => setFormError('')}
          />
        ) : null}
        <div className={styles.modalHint}>
          补录后系统会按新成绩刷新候选与方案，原会话的意向等设置保持不变。
        </div>
        <Form form={form} labelCol={{ flex: '96px' }} labelAlign="right" labelWrap>
          <Form.Item
            key="province"
            label="高考省份"
            name="province"
            rules={[{ required: true, message: '请选择高考省份' }]}
          >
            <Select
              placeholder="请选择高考省份"
              fieldNames={{ label: 'label', value: 'code' }}
              options={provinceList}
              onChange={handleProvinceChange}
            />
          </Form.Item>
          <Form.Item
            key="subjects"
            label="高考科目"
            name="subjects"
            rules={[{ required: true, message: '请选择高考科目' }]}
          >
            <div onClick={openSubjectModal}>
              <Input
                readOnly
                placeholder="请选择高考科目"
                value={selectedSubjects.join('、')}
              />
            </div>
          </Form.Item>
          <Form.Item
            key="scores"
            label="各科成绩"
            name="scores"
            rules={[{ required: true, message: '请填写各科成绩' }]}
          >
            <div onClick={openScoreModal}>
              <Input
                readOnly
                placeholder="请填写各科成绩"
                value={scoreEntries
                  .map(item => `${item.subjectName}${item.score}`)
                  .join('、')}
              />
            </div>
          </Form.Item>
          <Form.Item
            key="totalScore"
            label={resolveTotalScoreLabel(provinceValue, '高考总成绩')}
            name="totalScore"
            rules={[
              { required: true, message: '请填写成绩' },
              {
                validator: (_, value) => {
                  if (!isHainanProvince) {
                    return Promise.resolve();
                  }
                  const error = validateHainanTotalScore(value);
                  return error ? Promise.reject(new Error(error)) : Promise.resolve();
                },
              },
            ]}
            extra={
              isHainanProvince
                ? '请填写转换/赋分后用于投档和查位次的最终总成绩，不是各科成绩相加。'
                : undefined
            }
          >
            <Input
              readOnly={!isHainanProvince}
              placeholder={isHainanProvince ? '请输入最终总分' : '由各科成绩自动计算'}
            />
          </Form.Item>
          <Form.Item
            key="batch"
            label="填报批次"
            name="batch"
            rules={[{ required: true, message: '请选择填报批次' }]}
          >
            <Select
              placeholder={batchLoading ? '批次加载中…' : '请选择填报批次'}
              options={batchOptions}
              notFoundContent={batchLoading ? <Spin size="small" /> : null}
            />
          </Form.Item>
          <Form.Item
            key="totalScorePos"
            label="成绩位次"
            name="totalScorePos"
            extra="自动按成绩计算，可手动修改；不知道可留空。"
          >
            <InputNumber
              style={{ width: '100%' }}
              min={1}
              precision={0}
              placeholder="自动计算（可留空）"
            />
          </Form.Item>
        </Form>
      </div>

      <Modal
        title="选择高考科目"
        open={subjectOpen}
        onCancel={() => setSubjectOpen(false)}
        onOk={handleSubjectOk}
        okText="确认"
        cancelText="取消"
        destroyOnClose
      >
        <SelectOption selectConfig={subjectSelectConfig} formDisabled={false} />
      </Modal>

      <Modal
        title="填写各科成绩"
        open={scoreOpen}
        onCancel={() => setScoreOpen(false)}
        onOk={handleScoreOk}
        okText="确认"
        cancelText="取消"
        destroyOnClose
      >
        <div className={styles.scoreModalBody}>
          <SubjectScores
            ref={scoreFormRef}
            selectedSubjects={selectedSubjects}
            areaId={provinceValue || ''}
          />
        </div>
      </Modal>
    </Modal>
  );
};

export default ScoreSupplementModal;
