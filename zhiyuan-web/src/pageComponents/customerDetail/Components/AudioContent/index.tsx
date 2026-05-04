import { CheckCircleOutlined } from '@ant-design/icons';
import style from './style.module.scss';
import WaveSurferPlayer, { WavePlayerRef } from '@/pageComponents/customerDetail/Wave';
import { ISegments } from '@/interface/api/customerDetail';
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
interface IAudioProps {
  audioData: ISegments;
  onFinish?: () => void;
  onReady?: () => void;
}
const AudioContent = forwardRef<WavePlayerRef, IAudioProps>((props, ref) => {
  const { audioData, onFinish, onReady } = props;
  const playerRef = useRef<WavePlayerRef>(null);

  // 暴露给父组件
  useImperativeHandle(ref, () => ({
    play: () => playerRef.current?.play(),
    pause: () => playerRef.current?.pause(),
  }));

  return (
    <div className={style.audioContainer}>
      {audioData && (
        <>
          <div className={style.audioWrapper}>
            <WaveSurferPlayer
              url={audioData.materialUrl}
              duration={audioData.content.duration}
              ref={playerRef}
              onFinish={onFinish}
              onReady={onReady}
            />
          </div>
          <div className={style.audioText}>
            <div className={style.audioTitle}>{audioData.content.title}</div>
            <div className={style.audioMessage}> {audioData.content.message}</div>
          </div>
          <div className={style.audioEnd}>
            <CheckCircleOutlined />
            <span>语音转换完成</span>
          </div>
        </>
      )}
    </div>
  );
});
export default AudioContent;
