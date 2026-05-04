import React, { useEffect, useState } from 'react';
import { Table, Tooltip } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import classNames from 'classnames';
import styles from './style.module.scss';
import emptyPng from '@/images/icons/empty.png';

interface IPropsType {
  configTable: any[];
  rightRender?: () => React.ReactNode;
  leftRender?: () => React.ReactNode;
  combinedData: any;
  isLoading?: boolean;
  pagination?: any;
  pageChange: (val: number) => void;
  sizeChange: (val: number) => void;
}

const FinTableWrapper = (props: IPropsType) => {
  const {
    configTable,
    combinedData,
    isLoading,
    pagination,
    pageChange,
    sizeChange,
    leftRender,
    rightRender,
  } = props;
  const [scrollY, setScrollY] = useState<number>(0);
  const [tableScroll, setTableScroll] = useState<any>(undefined);

  useEffect(() => {
    setTableScroll({ x: 800, y: scrollY });
  }, [scrollY]);

  const handleSizeChange = (_: number, val: number) => {
    sizeChange(val);
  };

  const handleCurrentChange = (val: number) => {
    pageChange(val);
  };

  const getTableScroll = () => {
    const height = document.querySelector(`.${styles.searchTable}`)!.clientHeight;
    console.log(height, 'height');
    let titleHeight = 0;
    if (document.querySelector(`.${styles.title}`)) {
      titleHeight = document.querySelector(`.${styles.title}`)!.clientHeight + 16;
    }
    console.log(titleHeight, 'titleHeight');

    return height - titleHeight - 144 || 330;
  };
  // 页面加载完成后才能获取到对应的元素及其位置
  useEffect(() => {
    setScrollY(getTableScroll());
  }, []);

  return (
    <div className={styles.searchTable}>
      <div className={styles.title}>
        <div className={styles.desc}>
          {leftRender ? (
            leftRender()
          ) : (
            // <div className={styles.localTotal}>
            //     共
            //     {combinedData.total}
            //     条数据
            // </div>
            <div style={{ fontSize: '18px', color: '#2C2E40' }}>会话列表</div>
          )}
        </div>
        {rightRender ? rightRender() : null}
      </div>
      {combinedData?.records ? (
        <Table
          dataSource={combinedData?.records}
          rowKey="id"
          loading={isLoading}
          // scroll={{ x: 800, y: scrollY }}
          scroll={tableScroll}
          pagination={{
            current: pagination?.page,
            pageSize: pagination?.pageSize,
            total: combinedData?.total,
            onChange: handleCurrentChange,
            onShowSizeChange: handleSizeChange,
            pageSizeOptions: ['10', '20', '50', '100'],
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: total => `共 ${total} 条数据`,
          }}
          locale={{
            emptyText: (
              <div style={{ textAlign: 'center' }}>
                <img
                  src={emptyPng.src}
                  alt="暂无会话记录"
                  style={{ width: 120, marginBottom: 16 }}
                />
                <p>暂无会话记录</p>
              </div>
            ),
          }}
        >
          {configTable.map(item => (
            <Table.Column
              align="left"
              key={item.label}
              className={classNames(
                styles.tableColumn,
                item.classNamesTitle && { [item.classNamesTitle]: true }
              )}
              title={
                item.tips ? (
                  <div style={{ display: 'flex' }}>
                    <div style={{ marginRight: 4 }}>{item.label}</div>
                    <Tooltip
                      title={item.tips}
                      placement="top"
                      overlayStyle={{ maxWidth: '300px', width: 'auto' }}
                    >
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </div>
                ) : (
                  item.label
                )
              }
              dataIndex={item.prop}
              width={item.width || 110}
              fixed={item.fixed}
              ellipsis={{
                showTitle: false,
              }}
              // 根据配置项调用自定义渲染函数或默认渲染方式
              render={(text, record: Record<string, any>) =>
                item.render
                  ? item.render(text, record) ?? '-'
                  : text === null || text === undefined || text === ''
                  ? '-'
                  : text
              }
            />
          ))}
        </Table>
      ) : (
        <div className={styles.empty}>
          <img src={emptyPng.src} />
          <span>暂无会话记录</span>
        </div>
      )}
    </div>
  );
};

export default FinTableWrapper;
