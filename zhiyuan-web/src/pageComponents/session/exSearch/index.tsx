import React, { useRef, ReactNode, useEffect } from 'react';
import { Form, Input, Select, DatePicker, Button, Row, Col } from 'antd';
import classNames from 'classnames';
import styles from './style.module.scss';

interface IPropsType {
  configSearch: any[];
  isLoading?: boolean;
  searchOptions: Record<string, any>;
  searchRemote?: Record<string, any>;
  defaultSearchBar?: Record<string, any>;
  search: (params: unknown) => void;
  reset: (params: unknown) => void;
  children?: ReactNode;
}

const { RangePicker } = DatePicker;

const FinSearchWrapper: React.FC<IPropsType> = ({
  configSearch,
  search,
  reset,
  isLoading,
  searchOptions,
  defaultSearchBar,
  children,
}) => {
  const [form] = Form.useForm();
  const dates = useRef<Record<string, string>>({});

  const onSearch = () => {
    search({ ...form.getFieldsValue(true), ...dates.current });
  };

  const onReset = () => {
    form.resetFields();
    form.setFieldsValue({ ...defaultSearchBar });
    dates.current = {};
    reset({ ...form.getFieldsValue(true) });
  };

  const inputChange = (item: any) => {
    if (item.input) {
      item.input(form);
    }
  };

  const onDateChange = (
    dateStrings: [string, string],
    formItemName: string,
    keys: [string, string]
  ) => {
    dates.current = { ...dates.current, [keys[0]]: dateStrings[0], [keys[1]]: dateStrings[1] };
  };
  useEffect(() => {
    defaultSearchBar && form.setFieldsValue(defaultSearchBar);
  }, []);

  return (
    <Form form={form} onFinish={onSearch} className={styles.searchForm}>
      <div className={styles.searchContainer}>
        <div className={styles.searchFields}>
          {configSearch.map(item => (
            <div key={item.formItem.name} className={styles.searchFieldItem}>
              <Form.Item label={item.formItem.label} name={item.formItem.name}>
                {item.type === 'input' && (
                  <Input
                    {...item.formItem}
                    autoComplete="off"
                    allowClear
                    placeholder="请输入"
                    onChange={() => inputChange(item)}
                  />
                )}
                {item.type === 'select' && (
                  <Select
                    {...item.formItem}
                    allowClear
                    placeholder="请选择"
                    options={searchOptions[item.formItem.name] || []}
                  />
                )}
                {item.type === 'rangePicker' && (
                  <RangePicker
                    {...item.formItem}
                    format="YYYY-MM-DD"
                    onChange={(_, dateStrings) =>
                      onDateChange(dateStrings, item.formItem.name, item.key as [string, string])
                    }
                  />
                )}
              </Form.Item>
            </div>
          ))}
        </div>
        <div className={styles.searchActions}>
          <Button className={styles.firstBtn} type="primary" htmlType="submit" loading={isLoading}>
            查询
          </Button>
          <Button
            className={styles.seconBtn}
            htmlType="button"
            onClick={onReset}
            loading={isLoading}
          >
            重置
          </Button>
          {children}
        </div>
      </div>
    </Form>
  );
};

export default FinSearchWrapper;
