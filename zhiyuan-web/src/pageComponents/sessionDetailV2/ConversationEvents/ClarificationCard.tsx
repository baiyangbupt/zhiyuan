import React, { useCallback, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Radio, Space, Tag, Typography } from 'antd';

/**
 * 澄清卡：把服务端的澄清请求渲染成一次作答。
 *
 * 三条来自服务端与产品约束的形状，写在这里是为了**渲染时就分对**，
 * 而不是等提交被拒才知道：
 * 1. `inputKind` 是判别式——choice 交 `answers`，form 交 `action + content`。
 *    混用的结果不是"格式错"，而是服务端把它当成另一种卡解析。
 * 2. 选项文案以**服务端给的**为准：本地不新增、不改写，自由输入只在题目
 *    声明了 `isOther` 时才出现（服务端同样会拒收清单外的值）。
 * 3. `clientRequestId` 在重试之间**保持不变**：服务端靠它把"重发"与
 *    "另一个请求"区分开，换 id 重试等于让同一次作答被执行两次。
 */

export interface ClarificationQuestionOption {
  label: string;
  description?: string;
}

export interface ClarificationQuestion {
  id: string;
  header?: string;
  question: string;
  isOther?: boolean;
  isSecret?: boolean;
  options?: ClarificationQuestionOption[];
}

export interface ClarificationSchemaProperty {
  type?: string;
  title?: string;
  enum?: string[];
  default?: unknown;
}

export interface ClarificationSchema {
  properties?: Record<string, ClarificationSchemaProperty>;
  required?: string[];
}

export interface ClarificationPayload {
  requestId: string;
  inputKind?: 'choice' | 'form';
  questions?: ClarificationQuestion[];
  requestedSchema?: ClarificationSchema;
  status?: 'pending' | 'answered' | 'resolved' | 'expired';
  expiresIn?: number;
}

export interface ClarificationCardProps {
  clarification: ClarificationPayload;
  onSubmit?: (answer: Record<string, unknown>, meta: { clientRequestId: string }) => void | Promise<void>;
  onDecline?: (action: 'decline' | 'cancel', meta: { clientRequestId: string }) => void | Promise<void>;
}

const OTHER_OPTION = '__other__';

const initialChoiceAnswers = (questions: ClarificationQuestion[]) =>
  Object.fromEntries(questions.map(question => [question.id, { choice: '', other: '' }]));

const initialFormValues = (schema?: ClarificationSchema) => {
  const values: Record<string, string | boolean | undefined> = {};
  Object.entries(schema?.properties || {}).forEach(([name, property]) => {
    if (property.default !== undefined) values[name] = property.default as string | boolean;
  });
  return values;
};

export const ClarificationCard: React.FC<ClarificationCardProps> = ({
  clarification,
  onSubmit,
  onDecline,
}) => {
  const inputKind = clarification.inputKind || 'choice';
  const questions = useMemo(() => clarification.questions || [], [clarification.questions]);
  const schema = clarification.requestedSchema;

  const [choices, setChoices] = useState(() => initialChoiceAnswers(questions));
  const [formValues, setFormValues] = useState(() => initialFormValues(schema));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // 一次作答一个 id，重试沿用：服务端据此把"重发"与"另一个请求"分开。
  const clientRequestId = useRef(
    `clarify-${clarification.requestId}-${Math.random().toString(36).slice(2, 10)}`,
  );

  const expired = clarification.status === 'expired';
  const settled = clarification.status === 'answered' || clarification.status === 'resolved';
  const locked = submitting || expired || settled;

  const buildChoiceAnswer = useCallback(() => {
    const answers: Record<string, { answers: string[] }> = {};
    for (const question of questions) {
      const picked = choices[question.id] || { choice: '', other: '' };
      const value = picked.choice === OTHER_OPTION ? picked.other.trim() : picked.choice;
      if (!value) return null;
      answers[question.id] = { answers: [value] };
    }
    return { inputKind: 'choice' as const, answers };
  }, [choices, questions]);

  const buildFormAnswer = useCallback(() => {
    const content: Record<string, string | boolean> = {};
    for (const [name, property] of Object.entries(schema?.properties || {})) {
      const value = formValues[name];
      if (value === undefined || value === '') return null;
      if (property.type === 'boolean' && typeof value !== 'boolean') return null;
      content[name] = value as string | boolean;
    }
    return { inputKind: 'form' as const, action: 'accept' as const, content };
  }, [formValues, schema]);

  const submit = useCallback(async () => {
    if (locked) return;
    const payload = inputKind === 'form' ? buildFormAnswer() : buildChoiceAnswer();
    if (!payload) {
      setError(inputKind === 'form' ? '请填完必填项' : '每一题都需要作答');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await onSubmit?.(payload, { clientRequestId: clientRequestId.current });
    } catch (submitError) {
      // 失败后**保留同一个 clientRequestId**：换新的会让服务端把重试
      // 当成第二次作答，而它本来是同一次。
      setError('提交没有成功，可以直接重试');
    } finally {
      setSubmitting(false);
    }
  }, [buildChoiceAnswer, buildFormAnswer, inputKind, locked, onSubmit]);

  const decline = useCallback(
    async (action: 'decline' | 'cancel') => {
      if (locked) return;
      setSubmitting(true);
      setError('');
      try {
        await onDecline?.(action, { clientRequestId: clientRequestId.current });
      } catch (declineError) {
        setError('操作没有成功，可以直接重试');
      } finally {
        setSubmitting(false);
      }
    },
    [locked, onDecline],
  );

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <div data-testid="clarification-card" data-request-id={clarification.requestId} data-input-kind={inputKind}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space>
          <Typography.Text strong>需要你确认一下</Typography.Text>
          {expired ? <Tag color="red">已过期</Tag> : null}
          {settled ? <Tag color="green">已作答</Tag> : null}
        </Space>

        {inputKind === 'form'
          ? Object.entries(schema?.properties || {}).map(([name, property]) => (
              <div key={name} data-testid={`clarification-field-${name}`}>
                <Typography.Text>{property.title || name}</Typography.Text>
                {property.type === 'boolean' ? (
                  <Radio.Group
                    disabled={locked}
                    value={formValues[name]}
                    onChange={event => setFormValues(prev => ({ ...prev, [name]: event.target.value }))}
                  >
                    <Radio value>是</Radio>
                    <Radio value={false}>否</Radio>
                  </Radio.Group>
                ) : property.enum ? (
                  <Radio.Group
                    disabled={locked}
                    value={formValues[name]}
                    onChange={event => setFormValues(prev => ({ ...prev, [name]: event.target.value }))}
                  >
                    {property.enum.map(option => (
                      <Radio key={option} value={option}>
                        {option}
                      </Radio>
                    ))}
                  </Radio.Group>
                ) : (
                  <Input
                    disabled={locked}
                    value={(formValues[name] as string) || ''}
                    onChange={event => setFormValues(prev => ({ ...prev, [name]: event.target.value }))}
                    onKeyDown={onKeyDown}
                    placeholder="请输入"
                  />
                )}
              </div>
            ))
          : questions.map(question => {
              const picked = choices[question.id] || { choice: '', other: '' };
              return (
                <div key={question.id} data-testid={`clarification-question-${question.id}`}>
                  <Typography.Text>{question.header || question.question}</Typography.Text>
                  <Radio.Group
                    disabled={locked}
                    value={picked.choice}
                    onChange={event =>
                      setChoices(prev => ({ ...prev, [question.id]: { ...picked, choice: event.target.value } }))
                    }
                  >
                    <Space direction="vertical">
                      {(question.options || []).map(option => (
                        <Radio key={option.label} value={option.label}>
                          {option.label}
                          {option.description ? (
                            <Typography.Text type="secondary"> {option.description}</Typography.Text>
                          ) : null}
                        </Radio>
                      ))}
                      {/* 自由输入只在题目声明了 isOther 时出现：服务端同样会拒收
                          清单外的值，这里提前挡住比提交后报错好。 */}
                      {question.isOther ? <Radio value={OTHER_OPTION}>其他（自己填）</Radio> : null}
                    </Space>
                  </Radio.Group>
                  {question.isOther ? (
                    <Input
                      disabled={locked}
                      maxLength={2000}
                      value={picked.other}
                      onChange={event =>
                        // **在框里打字就等于"自己填"** ✓：取值一并切到 OTHER_OPTION ✓——
                        // 否则会出现"有文本、但没选任何一项"这个中间态 ✗，
                        // 提交时被判成空答案 ✗（设计口径：choice 每题 **radio + 自由输入** ✓，
                        // 自由输入是**常显**的 ✓，不再藏在"其他"单选项后面 ✓）。
                        setChoices(prev => ({
                          ...prev,
                          [question.id]: { choice: OTHER_OPTION, other: event.target.value },
                        }))
                      }
                      onKeyDown={onKeyDown}
                      placeholder="请输入"
                    />
                  ) : null}
                </div>
              );
            })}

        {error ? <Alert type="error" showIcon message={error} /> : null}

        <Space>
          <Button
            type="primary"
            loading={submitting}
            disabled={locked}
            onClick={() => void submit()}
            data-testid="clarification-submit"
          >
            {settled ? '已提交' : '提交'}
          </Button>
          {inputKind === 'form' ? (
            <>
              <Button disabled={locked} onClick={() => void decline('decline')} data-testid="clarification-decline">
                暂不填写
              </Button>
              <Button disabled={locked} onClick={() => void decline('cancel')} data-testid="clarification-cancel">
                取消
              </Button>
            </>
          ) : null}
        </Space>
      </Space>
    </div>
  );
};

export default ClarificationCard;
