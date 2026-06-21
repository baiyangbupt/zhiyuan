import { ISubjectTypeAndExamObject } from '@/interface/api/updateBaseInfo';
import { resolveSubjectScoreMax } from '@/utils/scoreRules.mjs';
import {Form, FormInstance, Input} from 'antd';
import {forwardRef, useImperativeHandle} from 'react';

export interface IRefParams {
  form: FormInstance<any>;
  getSaveParamsData: () => {
    prepareType: ISubjectTypeAndExamObject;
    subjectType: string;
    memberSubjectList: any[];
    subjectScoreList: any[];
  };
  getDealParamsData: () => {
    [key:string]: any;
  };
}

const SubjectScores = forwardRef<IRefParams, ISubjectScoresProps>((props: ISubjectScoresProps,
    ref: any) => {
    const {selectedSubjects, areaId} = props;
    const [form] = Form.useForm();
    const mainSubjectMax = resolveSubjectScoreMax(areaId, 'main');
    const electiveSubjectMax = resolveSubjectScoreMax(areaId, 'elective');

    const gradesRules = (max: any) => [
        {
            validator(rule: any, value: any) {
                if (value >= 0 && value <= max) {
                    return Promise.resolve();
                }
                return Promise.reject(new Error(`只能输入0-${max}`));
            },
        }
    ];

    useImperativeHandle(ref, () => ({
        form,
    }));


    return (
        <Form form={form}>
            <Form.Item
                name={`grades${1}`}
                label="语文"
                rules={[
                    {required: true, message: '请填写'},
                    ...gradesRules(mainSubjectMax)
                ]}
            >
                <Input
                    placeholder="请填写"
                />
            </Form.Item>
            <Form.Item
                name={`grades${2}`}
                label="数学"
                rules={[
                    {required: true, message: '请填写'},
                    ...gradesRules(mainSubjectMax)
                ]}
            >
                <Input placeholder="请填写" />
            </Form.Item>
            <Form.Item
                name={`grades${3}`}
                label="英语"
                rules={[
                    {required: true, message: '请填写'},
                    ...gradesRules(mainSubjectMax)
                ]}
            >
                <Input placeholder="请填写" />
            </Form.Item>
            {
                selectedSubjects.map((subject, index) => (
                    <Form.Item
                        key={subject}
                        name={`grades${index + 4}`}
                        label={subject}
                        rules={[
                            {required: true, message: '请填写'},
                            ...gradesRules(electiveSubjectMax)
                        ]}
                    >
                        <Input placeholder="请填写" />
                    </Form.Item>
                ))
            }
        </Form>
    );
});

export default SubjectScores;
