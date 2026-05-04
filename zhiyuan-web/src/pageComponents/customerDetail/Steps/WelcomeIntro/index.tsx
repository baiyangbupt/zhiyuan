import AudioContent from '@/pageComponents/customerDetail/Components/AudioContent';
import style from './style.module.scss';
import { Button, Form, Select } from 'antd';
import { IActions, ICollectflowRes, ISegments, ISubSteps } from '@/interface/api/customerDetail';
import { getStorage } from '@/utils/tool';
import { useEffect, useRef, useState } from 'react';
import ReturnPng from '@/images/icons/return.png';
import ModalImage from '../../Components/ModalImage';
import { WavePlayerRef } from '../../Wave';

const { Option } = Select;

interface ICollectflowProps {
  stepsData: ICollectflowRes;
  onNextStep: (btn: IActions, formValues?: any) => void;
}
const WelcomeIntro = (props: ICollectflowProps) => {
  const { stepsData, onNextStep } = props;
  const [form] = Form.useForm();
  const [isNextConfirmBtn, setIsNextConfirmBtn] = useState(false);

  const [currentImageUrl, setCurrentImageUrl] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  const storedUserInfo: any = getStorage('userInfo') || '{}';
  const userInfo = JSON.parse(storedUserInfo);

  useEffect(() => {
    if (form) {
      form.setFieldValue('areaId', userInfo.province?.code);
    }
  }, [userInfo]);

  const areas = [
    { label: 'Beijing', value: 'Beijing' },
    { label: 'Shanghai', value: 'Shanghai' },
  ];

  const onFinish = (values: any) => {
    console.log('Success:', values);
  };

  const onFinishFailed = (errorInfo: any) => {
    console.log('Failed:', errorInfo);
  };

  const handleChange = () => {
    form.setFieldsValue({ sights: [] });
  };
  // 点击查看图片
  const handleShowModal = (rich: any) => {
    setCurrentImageUrl(rich.materialUrl);
    setIsModalOpen(true);
  };
  // 下一步
  const handleClickNextStep = (btn: IActions, item: ISubSteps) => {
    console.log('下一步', btn, item);
    setIsNextConfirmBtn(true);
    onNextStep(btn);
  };

  // const audioRefs = useRef<(WavePlayerRef | null)[]>([]);

  // const handleFinish = (index: number) => {
  //   const nextIndex = index + 1;
  //   if (audioRefs.current[nextIndex]) {
  //     audioRefs.current[nextIndex].play();
  //   }
  // };

  // const [refsReady, setRefsReady] = useState(false);

  // useEffect(() => {
  //   // 检查 refs 是否全部存在
  //   if (stepsData?.subSteps?.length && audioRefs.current.length === stepsData.subSteps.length) {
  //     const allRefsReady = audioRefs.current.every(ref => ref && ref.wavesurfer);
  //     if (allRefsReady) {
  //       setRefsReady(true);
  //     }
  //   }
  // }, [stepsData]);

  // useEffect(() => {
  //   if (refsReady) {
  //     console.log(audioRefs.current[0], 'audioRefs.current[0]');
  //     // 自动播放第一个音频
  //     audioRefs.current[0]?.play();
  //   }
  // }, [refsReady]);

  return (
    <div className={style.confirmGkInfoContainer}>
      {stepsData?.subSteps?.map((item, index) => {
        return (
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

            {/* 总结 */}
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
          </div>
        );
      })}
      <ModalImage
        imageUrl={currentImageUrl}
        isModalOpen={isModalOpen}
        setIsModalOpen={setIsModalOpen}
      />
    </div>
  );
};

export default WelcomeIntro;
