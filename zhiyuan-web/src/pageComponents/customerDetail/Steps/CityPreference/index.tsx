import AudioContent from '@/pageComponents/customerDetail/Components/AudioContent';
import style from './style.module.scss';
import { Badge, Button, Checkbox, Col, Flex, Form, message, Radio, Row, Select } from 'antd';
import { IActions, ICollectflowRes, ISegments, ISubSteps } from '@/interface/api/customerDetail';
import { getStorage } from '@/utils/tool';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReturnPng from '@/images/icons/return.png';
import { LinkOutlined } from '@ant-design/icons';
import ModalImage from '../../Components/ModalImage';

interface ICollectflowProps {
  stepsData: ICollectflowRes;
  onNextStep: (btn: IActions, formValues?: any) => void;
  onDraftChange?: (formValues?: any) => void;
  onBackStep?: () => void;
  savedValues?: any;
}

interface RegionSub {
  provinceId: string;
  provinceName: string;
}

const CityPreference = (props: ICollectflowProps) => {
  const { stepsData, onNextStep, onDraftChange, onBackStep, savedValues } = props;
  const [isNextConfirmBtn, setIsNextConfirmBtn] = useState(false);
  const [showSummary, setShowSummary] = useState(false); // 控制总结信息的显示

  const [currentImageUrl, setCurrentImageUrl] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const regionContainerRef = useRef<HTMLDivElement>(null);

  // 点击查看图片
  const handleShowModal = (rich: any) => {
    setCurrentImageUrl(rich.materialUrl);
    setIsModalOpen(true);
  };
  // 下一步
  const handleClickNextStep = (btn: IActions) => {
    setIsNextConfirmBtn(true);
    onNextStep(btn, { preferredRegions });
  };

  const [preferredRegions, setPreferredRegions] = useState<RegionSub[]>([]);

  useEffect(() => {
    if (!Array.isArray(savedValues?.preferredRegions)) return;
    setPreferredRegions(savedValues.preferredRegions);
  }, [savedValues]);

  const handleToggleRegion = (provinces: { code: string; name: string }[]) => {
    if (!provinces?.length) return;
    const allSelected = provinces.every(province =>
      preferredRegions.some(m => m.provinceId === province.code)
    );
    if (allSelected) {
      setPreferredRegions(prev =>
        prev.filter(m => !provinces.some(province => province.code === m.provinceId))
      );
      return;
    }
    const nextRegions = [...preferredRegions];
    provinces.forEach(province => {
      if (!nextRegions.some(m => m.provinceId === province.code)) {
        nextRegions.push({ provinceId: province.code, provinceName: province.name });
      }
    });
    setPreferredRegions(nextRegions);
  };

  const handleProvinceClick = (code: string, name: string) => {
    if (preferredRegions.some(m => m.provinceId === code)) {
      setPreferredRegions(preferredRegions.filter(m => m.provinceId !== code));
      return;
    }
    setPreferredRegions([...preferredRegions, { provinceId: code, provinceName: name }]);
  };

  const [messageApi, contextHolder] = message.useMessage();

  const handleConfirm = () => {
    if (!preferredRegions.length) {
      regionContainerRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
        inline: 'nearest',
      });
      messageApi.error('请选择意向区域');
      return;
    }
    onDraftChange?.({ preferredRegions });
    setShowSummary(true);
    // setTimeout(() => {
    //   scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
    // }, 100);
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
                return field?.regions?.map(region => {
                  const regionProvinces = region.provinces ?? [];
                  const regionSelectedCount = regionProvinces.filter(province =>
                    preferredRegions.some(m => m.provinceId === province.code)
                  ).length;
                  const isAllSelected =
                    regionProvinces.length > 0 && regionSelectedCount === regionProvinces.length;
                  const isPartSelected =
                    regionSelectedCount > 0 && regionSelectedCount < regionProvinces.length;
                  return (
                    <div className="region-major" key={region.regionId} ref={regionContainerRef}>
                      <div className="title">
                        <span>{region.regionName}</span>
                        <Checkbox
                          style={{ marginLeft: 12 }}
                          checked={isAllSelected}
                          indeterminate={isPartSelected}
                          onChange={() => handleToggleRegion(regionProvinces)}
                        >
                          全选
                        </Checkbox>
                      </div>
                      <Flex wrap gap={8} className="region-flex">
                        {region.provinces?.map(province => (
                        <Col
                          className={[
                            'region-item',
                              preferredRegions.some(m => m.provinceId === province.code)
                              ? 'region-item-active'
                              : '',
                          ].join(' ')}
                          key={province.code}
                          onClick={() => {
                            handleProvinceClick(province.code, province.name);
                          }}
                        >
                          {province.name}
                        </Col>
                        ))}
                      </Flex>
                    </div>
                  );
                });
              })}
              <Row justify="center" style={{ marginTop: 12 }}>
                <div className={style.formActions}>
                  {onBackStep && (
                    <Button className={style.backActionButton} onClick={onBackStep}>
                      上一步
                    </Button>
                  )}
                  <Button className={style.submitActionButton} onClick={handleConfirm}>
                    确认提交
                  </Button>
                </div>
              </Row>
            </div>
          )}
          {/* 确认信息 - 在表单提交后显示 */}
          {showSummary && (
            <div className={style.rightAnswer}>
              <div className={style.answerBtn}>
                {preferredRegions.map(m => m.provinceName).join('、')}
              </div>
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

export default CityPreference;
