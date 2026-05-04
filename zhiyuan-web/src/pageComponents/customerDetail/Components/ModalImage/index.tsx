import { Modal, Image } from 'antd';
import { useState } from 'react';

const ModalImage = (props: {
  imageUrl: string;
  isModalOpen: boolean;
  setIsModalOpen: (isModalOpen: boolean) => void;
}) => {
  const { imageUrl, isModalOpen, setIsModalOpen } = props;

  const handleOk = () => {
    setIsModalOpen(false);
  };

  const handleCancel = () => {
    setIsModalOpen(false);
  };
  return (
    <Modal title="图片查看" width={500} open={isModalOpen} onOk={handleOk} onCancel={handleCancel}>
      <Image src={imageUrl} />
    </Modal>
  );
};

export default ModalImage;
