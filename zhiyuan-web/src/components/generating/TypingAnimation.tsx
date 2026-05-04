import React, { useState, useEffect } from 'react';
import style from './style.module.scss';

interface TypingAnimationProps {
  text?: string;
  speed?: number;
  className?: string;
}

const TypingAnimation: React.FC<TypingAnimationProps> = ({
  text = 'AI正在思考中',
  speed = 80,
  className = '',
}) => {
  const [displayText, setDisplayText] = useState('');
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    if (currentIndex < text.length) {
      const timer = setTimeout(() => {
        setDisplayText(prev => prev + text[currentIndex]);
        setCurrentIndex(prev => prev + 1);
      }, speed);

      return () => clearTimeout(timer);
    }
  }, [currentIndex, text, speed]);

  // 重置动画当text改变时
  useEffect(() => {
    setDisplayText('');
    setCurrentIndex(0);
  }, [text]);

  const isTypingComplete = displayText.length === text.length;

  return (
    <div className={`${style.generatingContainer} ${className}`}>
      <span className={style.generatingText}>
        {displayText}
        <span className={style.cursor}>|</span>
      </span>
      {isTypingComplete && (
        <div className={style.dotsAnimation}>
          <span className={style.dot}></span>
          <span className={style.dot}></span>
          <span className={style.dot}></span>
        </div>
      )}
    </div>
  );
};

export default TypingAnimation;
