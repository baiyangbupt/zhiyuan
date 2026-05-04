import { PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { useWavesurfer } from '@wavesurfer/react';
import {
  useMemo,
  useRef,
  useState,
  useCallback,
  forwardRef,
  useImperativeHandle,
  useEffect,
} from 'react';
import style from './style.module.scss';

interface WavePlayerProps {
  url: string;
  duration: number;
  onFinish?: () => void;
  onReady?: () => void;
}

export interface WavePlayerRef {
  wavesurfer?: ReturnType<typeof useWavesurfer>['wavesurfer'] | null;
  play: () => void;
  pause: () => void;
  isReady?: boolean;
}

const WavePlayer = forwardRef<WavePlayerRef, WavePlayerProps>(
  ({ url, duration, onFinish, onReady }, ref) => {
    const containerRef = useRef(null);
    const [isPlay, setIsPlay] = useState(false);
    const { wavesurfer, isPlaying, currentTime, isReady } = useWavesurfer({
      container: containerRef,
      height: 35,
      url: url,
      // url: 'https://wavesurfer.xyz/wavesurfer-code/examples/audio/audio.wav',
      waveColor: '#ebebef',
      progressColor: '#ff5750',
      cursorColor: '#ebebef',
      cursorWidth: 1,
      barWidth: 4,
      barGap: 5,
      barRadius: 2,
      barHeight: 1,
      // plugins: useMemo(() => [Timeline.create()], []),
    });

    useEffect(() => {
      if (!wavesurfer) return;

      const handleReady = () => {
        onReady?.();
      };

      const handleFinish = () => {
        setIsPlay(false);
        onFinish?.();
      };
      wavesurfer.on('ready', handleReady);
      wavesurfer.on('finish', handleFinish);

      return () => {
        wavesurfer.un('ready', handleReady);
        wavesurfer.un('finish', handleFinish);
      };
    }, [wavesurfer, onFinish, onReady]);

    const handlePlay = () => {
      setIsPlay(true);
      wavesurfer && wavesurfer.play();
    };

    const handlePause = () => {
      setIsPlay(false);
      wavesurfer && wavesurfer.pause();
    };

    // 暴露给父组件
    useImperativeHandle(
      ref,
      () => ({
        wavesurfer,
        play: () => {
          if (wavesurfer && isReady) {
            handlePlay();
          }
        },
        pause: () => {
          handlePause();
        },
        isReady,
      }),
      [wavesurfer, isReady]
    );

    return (
      <div className={style.audioMain}>
        <div ref={containerRef} className={style.audioLeft} />
        <div className={style.audioRight}>
          <span>{duration}</span>
          {isPlay ? (
            <PauseCircleOutlined onClick={handlePause} style={{ fontSize: 24 }} />
          ) : (
            <PlayCircleOutlined onClick={handlePlay} style={{ fontSize: 24 }} />
          )}
        </div>
      </div>
    );
  }
);

export default WavePlayer;
