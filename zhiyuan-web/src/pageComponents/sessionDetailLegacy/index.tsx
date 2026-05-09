import React, { useState, useEffect, useRef, useCallback } from 'react';
import type { ColumnsType } from 'antd/es/table';

import {
  Button,
  message,
  Spin,
  Typography,
  Divider,
  Tag,
  Collapse,
  Modal,
  Space,
  Table,
  Empty,
  FloatButton,
} from 'antd';
import { DownOutlined, StarOutlined, FileTextOutlined, CheckCircleOutlined, LockOutlined } from '@ant-design/icons';
import {
  CollapseContentProps,
  CollapseHeaderProps,
  DataType,
  DialogueProps,
  FilterType,
  HistoryScore,
} from '@/interface/api/volunteer';
import {
  getVolunteerExportApi,
  getVolunteerRecommendListApi,
} from '@/service/apis/sessionDetail';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import style from './style.module.scss';
const { Panel } = Collapse;

const Volunteer: React.FC<DialogueProps> = ({
  routerParams,
  setScrollEleIndex,
  entityCardList,
  fetchFlag,
  sessionStatus,
  fetchSessionDetail,
}) => {
  const isMobile = useMediaQuery(768);
  const [isLoading, setIsLoading] = useState(false);
  const [volunteerData, setVolunteerData] = useState<any>({});
  const [activeFilter, setActiveFilter] = useState<FilterType>('sprints'); // 默认选中院校优先
  const hasUserSwitchedTabRef = useRef<boolean>(false); // 标记用户是否手动切换过tab
  const [volunteerCounts, setVolunteerCounts] = useState({
    sprints: { preferred: 0, alternative: 0 },
    safes: { preferred: 0, alternative: 0 },
    protects: { preferred: 0, alternative: 0 },
  });
  const [collapsedSections, setCollapsedSections] = useState<
    Record<string, Record<string, boolean>>
  >({});
  const [tuitionRange, setTuitionRange] = useState<[number, number] | null>(null);
  const [displayTuitionRange, setDisplayTuitionRange] = useState<[number, number] | null>(null);

  // 分页加载相关状态
  const [loadedCounts, setLoadedCounts] = useState<Record<string, Record<string, number>>>({});
  const [isLoadingMore, setIsLoadingMore] = useState<Record<string, Record<string, boolean>>>({});
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const observerTargetsRef = useRef<Record<string, HTMLDivElement | null>>({});
  const hasScrolledRef = useRef<boolean>(false); // 标记用户是否已经滚动过

  // 查找滚动容器（用于回顶部）
  const findScrollContainer = useCallback((): HTMLElement | null => {
    const el = scrollContainerRef.current || panelRef.current;
    if (!el) return null;
    let current: HTMLElement | null = el.parentElement;
    while (current) {
      const style = window.getComputedStyle(current);
      if (style.overflow === 'auto' || style.overflow === 'scroll' || style.overflowY === 'auto' || style.overflowY === 'scroll') {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }, []);

  // 每次加载的数量
  const PAGE_SIZE = 50;

  // 学费区间展示格式化
  const formatTuitionValue = (value: number) => {
    if (value >= 10000) {
      const wan = value / 10000;
      const text = Number.isInteger(wan) ? wan.toFixed(0) : wan.toFixed(1);
      return `${text}万/年`;
    }
    return `${value.toLocaleString()}元/年`;
  };

  const CollapseHeader: React.FC<CollapseHeaderProps> = ({
    index,
    tabActive,
    schoolName,
    schoolRank,
    basicTagList,
    rankTagList,
    historyScoreList,
    enrollRatio,
    baoyanRatio,
    majors,
    advantages,
    masterCount,
    doctoralCount,
    popTagList,
  }) => {
    const [isHistoryScoreModalOpen, setIsHistoryScoreModalOpen] = useState(false);
    const [columns, setColumns] = useState<ColumnsType<DataType>>([]);
    const [data, setData] = useState<DataType[]>([]);

    // 转换数据格式
    const types = [
      { type: '录取人数', key: '1' },
      { type: '最低分数', key: '2' },
      { type: '最低位次', key: '3' },
    ];

    // 为每个专业创建三种数据类型
    const generateData = () => {
      const newData: DataType[] = [];
      types.forEach(typeInfo => {
        newData.push({
          key: typeInfo.key,
          major_name: '',
          planTagList: [],
          enroll_ratio: '',
          rankTagList: [],
          history_score_list: historyScoreList,
          type: typeInfo.type,
        });
      });
      setData(newData);
    };

    // 获取所有不重复的年份（从所有专业的历史数据中提取）
    const getAllYears = (): number[] => {
      const yearsSet = new Set<number>();
      historyScoreList.forEach(score => {
        yearsSet.add(score.year);
      });
      return Array.from(yearsSet).sort((a, b) => b - a); // 按年份降序排列
    };

    // 动态生成年份列
    const generateYearColumns = (): ColumnsType<DataType> => {
      const years = getAllYears();
      return years.map(year => ({
        title: year.toString(),
        dataIndex: 'history_score_list',
        render: (historyList: HistoryScore[], record: DataType) => {
          const yearData = historyList.find(item => item.year === year);
          if (!yearData) return '-';

          // 根据类型选择返回数据
          switch (record.type) {
            case '录取人数':
              return yearData.enrollNum && yearData.enrollNum > 0 ? yearData.enrollNum : '-';
            case '最低分数':
              return yearData.score > 0 ? yearData.score : '-';
            case '最低位次':
              return yearData.pos && yearData.pos > 0 ? yearData.pos : '-';
            default:
              return '-';
          }
        },
      }));
    };

    // 表格列定义
    const getColumns = (): ColumnsType<DataType> => {
      const yearColumns = generateYearColumns();
      return [
        {
          title: '数据类型',
          width: 100,
          dataIndex: 'type',
        },
        ...yearColumns, // 动态添加年份列
      ];
    };

    // 打开历史分数模态框
    const handleOpenHistoryScoreList = () => {
      generateData(); // 生成数据
      setColumns(getColumns()); // 设置columns
      setIsHistoryScoreModalOpen(true); // 打开Modal
    };

    return (
      <div className={style.collapseHeader}>
        <div className={style.leftContent}>
          <div className={style.title}>
            <span>
              {index}、{schoolName}
            </span>
            <div className={style.rankTagList}>
              {rankTagList?.map((tag: string) => (
                <Tag color="volcano" key={tag}>
                  {tag}
                </Tag>
              ))}
            </div>
          </div>
          <div className={style.basicTag}>
            <Space split={<Divider type="vertical" />}>
              {basicTagList?.map((tag: string) => (
                <span key={tag}>{tag}</span>
              ))}
            </Space>
          </div>
          {historyScoreList.length > 0 && (
            <div className={style.historyScore} onClick={handleOpenHistoryScoreList}>
              历年录取分数线
            </div>
          )}
        </div>
        <div className={style.rightContent}>
          <div
            className={`${style.countContainer} ${
              activeFilter === 'sprints'
                ? style.countSprints
                : activeFilter === 'safes'
                ? style.countSafes
                : activeFilter === 'protects'
                ? style.countProtects
                : ''
            }`}
          >
            <div className={style.ratio}>
              <span>{enrollRatio ? `${enrollRatio}% ` : '未知'}</span>
              <span>{tabActive === 'sprints' ? '冲' : tabActive === 'safes' ? '稳' : '保'}</span>
            </div>
            <div className={style.major}>专业 {majors.length}</div>
          </div>
        </div>

        {/* 历年录取分数线模态框 */}
        <Modal
          width={isMobile ? 'calc(100vw - 32px)' : 800}
          title="历年录取分数线"
          open={isHistoryScoreModalOpen}
          footer={null}
          onOk={() => setIsHistoryScoreModalOpen(false)}
          onCancel={() => setIsHistoryScoreModalOpen(false)}
        >
          <div className={style.modalContent}>
            <div className={style.title}>{schoolName}</div>
            <div className={style.basicTag}>
              <Space split={<Divider type="vertical" />}>
                {basicTagList?.map((tag: string) => (
                  <span key={tag}>{tag}</span>
                ))}
              </Space>
            </div>
            <div className={style.rankList}>
              {/* {schoolRank && <Tag color="gold">院校排名 {schoolRank}</Tag>}
              {enrollRatio && <Tag color="geekblue">录取率 {enrollRatio}%</Tag>}
              {baoyanRatio && <Tag>保研率 {baoyanRatio}%</Tag>} */}
              {popTagList?.map((tag: string) => (
                <Tag color="magenta" key={tag}>
                  {tag}
                </Tag>
              ))}
            </div>
            <Table
              columns={columns}
              dataSource={data}
              bordered
              pagination={false}
              scroll={{ x: isMobile ? 'max-content' : 600 }}
            />
          </div>
        </Modal>
      </div>
    );
  };

  const CollapseContent: React.FC<CollapseContentProps> = ({
    majors,
    tabActive,
    volunteerModel,
    volunteerCount,
    isMobile: contentIsMobile = false,
  }) => {
    // 折叠状态管理
    const [isPreferredCollapsed, setIsPreferredCollapsed] = useState(false);
    const [isAlternativeCollapsed, setIsAlternativeCollapsed] = useState(false);

    // 判断是否需要分组
    const needGrouping =
      volunteerModel === 'majorGroup' &&
      volunteerCount?.majorCount &&
      majors.length > volunteerCount.majorCount;

    // 转换数据格式的辅助函数
    const convertMajorsToData = (majorList: typeof majors): DataType[] => {
      const result: DataType[] = [];
      majorList.forEach((item, index) => {
        const baseKey = (index + 1).toString();
        // 为每个专业创建三种数据类型
        const types = [
          { type: '录取人数', key: baseKey + '-1' },
          { type: '最低分数', key: baseKey + '-2' },
          { type: '最低位次', key: baseKey + '-3' },
        ];

        types.forEach(typeInfo => {
          result.push({
            key: typeInfo.key,
            major_name: item.major_name,
            planTagList: item.planTagList,
            rankTagList: item.rankTagList,
            enroll_ratio: item.enroll_ratio,
            history_score_list: item.history_score_list,
            type: typeInfo.type,
          });
        });
      });
      return result;
    };

    const renderMajorName = (majorName: string) => {
      const trimmed = (majorName ?? '').trim();
      if (!trimmed) {
        return null;
      }
      const firstParenIndex = trimmed.indexOf('(');
      const hasExtra = firstParenIndex > -1;
      const mainName = (hasExtra ? trimmed.slice(0, firstParenIndex) : trimmed).trim();
      const extra = hasExtra ? trimmed.slice(firstParenIndex).trim() : '';

      return (
        <span className={style.majorName}>
          <span className={style.majorNameMain}>{mainName}</span>
          {extra && <span className={style.majorNameExtra}>{extra}</span>}
        </span>
      );
    };

    // 获取所有不重复的年份（从所有专业的历史数据中提取）
    const getAllYears = (majorList: typeof majors): number[] => {
      const yearsSet = new Set<number>();
      majorList.forEach(item => {
        item.history_score_list.forEach(score => {
          yearsSet.add(score.year);
        });
      });
      // 按年份降序排列（最新的年份在前面）
      return Array.from(yearsSet).sort((a, b) => b - a);
    };

    // 获取最新的年份（用于招生计划列标题）
    const getLatestYear = (majorList: typeof majors): number => {
      const years = getAllYears(majorList);
      return years.length > 0 ? years[0] : new Date().getFullYear(); // 如果没有数据，返回当前年份
    };

    // 动态生成年份列
    const generateYearColumns = (
      majorList: typeof majors,
      yearColWidth = 60
    ): ColumnsType<DataType> => {
      const years = getAllYears(majorList); // 获取所有年份

      return years.map(year => ({
        title: year.toString(),
        dataIndex: 'history_score_list',
        width: yearColWidth,
        render: (historyList: HistoryScore[], record: DataType) => {
          const yearData = historyList.find(item => item.year === year);
          if (!yearData) return '-';

          switch (record.type) {
            case '录取人数':
              return yearData.enrollNum && yearData.enrollNum > 0 ? yearData.enrollNum : '-';
            case '最低分数':
              return yearData.score > 0 ? yearData.score : '-';
            case '最低位次':
              return yearData.pos && yearData.pos > 0 ? yearData.pos : '-';
            default:
              return '-';
          }
        },
      }));
    };

    // 表格列定义（需要传入对应的 data 数组）
    const getColumns = (tableData: DataType[], majorList: typeof majors): ColumnsType<DataType> => {
      const latestYear = getLatestYear(majorList);
      const colWidths = contentIsMobile
        ? { major: 180, plan: 100, type: 70, year: 50, ratio: 55 }
        : { major: 300, plan: 140, type: 100, year: 60, ratio: 60 };
      const yearColumns = generateYearColumns(majorList, colWidths.year);

      return [
        {
          title: '专业',
          dataIndex: 'major_name',
          width: colWidths.major,
          render: (text: string, record: DataType, index: number) => {
            const isFirstRow = index === 0 || tableData[index - 1].major_name !== record.major_name;
            return isFirstRow ? (
              <div>
                <div>{renderMajorName(text)}</div>
                <div>
                  {record.rankTagList?.map(tag => (
                    <Tag color="volcano" key={tag}>
                      {tag}
                    </Tag>
                  ))}
                </div>
              </div>
            ) : null;
          },
          onCell: (record: DataType, index?: number) => {
            if (index === undefined) {
              return {};
            }
            const rowSpan = tableData.filter(item => item.major_name === record.major_name).length;
            const isFirstRow = index === 0 || tableData[index - 1].major_name !== record.major_name;
            return {
              rowSpan: isFirstRow ? rowSpan : 0,
            };
          },
        },
        {
          title: `${latestYear}招生计划`,
          dataIndex: 'planTagList',
          width: colWidths.plan,
          render: (tags: string[], record: DataType, index: number) => {
            const isFirstRow = index === 0 || tableData[index - 1].major_name !== record.major_name;
            return isFirstRow ? (
              <div>
                {tags.map((tag, i) => (
                  <div key={i}>{tag}</div>
                ))}
              </div>
            ) : null;
          },
          onCell: (record: DataType, index?: number) => {
            if (index === undefined) {
              return {};
            }
            const rowSpan = tableData.filter(item => item.major_name === record.major_name).length;
            const isFirstRow = index === 0 || tableData[index - 1].major_name !== record.major_name;
            return {
              rowSpan: isFirstRow ? rowSpan : 0,
            };
          },
        },
        {
          title: '数据类型',
          width: colWidths.type,
          dataIndex: 'type',
        },
        ...yearColumns, // 动态添加年份列
        {
          title: '录取率',
          dataIndex: 'enroll_ratio',
          width: colWidths.ratio,
          render: (ratio: string, record: DataType, index: number) => {
            const isFirstRow = index === 0 || tableData[index - 1].major_name !== record.major_name;
            return isFirstRow ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: '1px solid transparent',
                  borderColor:
                    activeFilter === 'sprints'
                      ? '#FF958A'
                      : activeFilter === 'safes'
                      ? '#FFBE85'
                      : activeFilter === 'protects'
                      ? '#6CE0AA'
                      : '',
                  borderRadius: 8,
                  color:
                    activeFilter === 'sprints'
                      ? '#FF958A'
                      : activeFilter === 'safes'
                      ? '#FFBE85'
                      : activeFilter === 'protects'
                      ? '#6CE0AA'
                      : '',
                  width: 40,
                  flexDirection: 'column',
                }}
              >
                <span>{ratio ? `${ratio}% ` : '未知'}</span>
                <span>{tabActive === 'sprints' ? '冲' : tabActive === 'safes' ? '稳' : '保'}</span>
              </div>
            ) : null;
          },
          onCell: (record: DataType, index?: number) => {
            if (index === undefined) {
              return {};
            }
            const rowSpan = tableData.filter(item => item.major_name === record.major_name).length;
            const isFirstRow = index === 0 || tableData[index - 1].major_name !== record.major_name;
            return {
              rowSpan: isFirstRow ? rowSpan : 0,
            };
          },
        },
      ];
    };

    // 如果需要分组
    if (needGrouping && volunteerCount?.majorCount) {
      const preferredMajors = majors.slice(0, volunteerCount.majorCount);
      const alternativeMajors = majors.slice(volunteerCount.majorCount);

      const preferredData = convertMajorsToData(preferredMajors);
      const alternativeData = convertMajorsToData(alternativeMajors);

      const preferredColumns = getColumns(preferredData, preferredMajors);
      const alternativeColumns = getColumns(alternativeData, alternativeMajors);

      return (
        <div className={style.collapseContent}>
          {/* 优报专业 */}
          <div
            style={{
              marginBottom: 16,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <Typography.Text strong style={{ fontSize: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
              <StarOutlined style={{ color: '#ff443d', fontSize: 16 }} />
              优报专业({preferredMajors.length})
            </Typography.Text>
            <div className={style.volunteerToggle} onClick={() => setIsPreferredCollapsed(!isPreferredCollapsed)}>
              <span>{isPreferredCollapsed ? '展开' : '收起'}</span>
              <DownOutlined
                className={`${style.toggleIcon} ${isPreferredCollapsed ? style.toggleIconCollapsed : ''}`}
              />
            </div>
          </div>
          {!isPreferredCollapsed && (
            <Table
              columns={preferredColumns}
              dataSource={preferredData}
              bordered
              pagination={false}
              scroll={contentIsMobile ? { x: 'max-content' } : undefined}
            />
          )}
          <Divider style={{ margin: '24px 0' }} />
          {/* 备选专业 */}
          <div
            style={{
              marginBottom: 16,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <Typography.Text strong style={{ fontSize: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
              <FileTextOutlined style={{ color: '#8b8fa1', fontSize: 16 }} />
              备选专业({alternativeMajors.length})
            </Typography.Text>
            <div className={style.volunteerToggle} onClick={() => setIsAlternativeCollapsed(!isAlternativeCollapsed)}>
              <span>{isAlternativeCollapsed ? '展开' : '收起'}</span>
              <DownOutlined
                className={`${style.toggleIcon} ${isAlternativeCollapsed ? style.toggleIconCollapsed : ''}`}
              />
            </div>
          </div>
          {!isAlternativeCollapsed && (
            <Table
              columns={alternativeColumns}
              dataSource={alternativeData}
              bordered
              pagination={false}
              scroll={contentIsMobile ? { x: 'max-content' } : undefined}
            />
          )}
        </div>
      );
    }

    // 不需要分组，使用原有逻辑
    const data = convertMajorsToData(majors);
    const columns = getColumns(data, majors);

    return (
      <div className={style.collapseContent}>
        <Table
          columns={columns}
          dataSource={data}
          bordered
          pagination={false}
          scroll={contentIsMobile ? { x: 'max-content' } : undefined}
        />
      </div>
    );
  };

  const fetchVolunteerRecommendList = async () => {
    if (isLoading) {
      console.log('Volunteer: 正在加载中，跳过请求');
      return;
    }
    console.log('Volunteer: 开始请求志愿列表接口');
    setIsLoading(true);
    const { data, code } = await getVolunteerRecommendListApi(
      routerParams.tenantId,
      routerParams.chatSessionId
    );

    if (code === 0 && data) {
      console.log('志愿列表信息', data);
      const targetCountMap = data?.baseData?.three_target_count_map || {};

      const calcPreferredAndAlternative = (list: any[], preferredCount: number) => {
        const safePreferred = Math.min(preferredCount, list.length);
        const alternative = Math.max(0, list.length - safePreferred);
        return { preferred: safePreferred, alternative };
      };

      const sprintsList = data.sprints || [];
      const sprintsCount = calcPreferredAndAlternative(
        sprintsList,
        targetCountMap.sprints_count || sprintsList.length
      );

      const safesList = data.safes || [];
      const safesCount = calcPreferredAndAlternative(
        safesList,
        targetCountMap.safes_count || safesList.length
      );

      const protectsList = data.protects || [];
      const protectsCount = calcPreferredAndAlternative(
        protectsList,
        targetCountMap.protects_count || protectsList.length
      );

      // ✅ 一次性更新三组数量
      setVolunteerCounts({
        sprints: sprintsCount,
        safes: safesCount,
        protects: protectsCount,
      });

      setVolunteerData(data);
      setCollapsedSections({});
      // 重置加载数量，初始加载第一页
      setLoadedCounts({});
      // 重置滚动标记
      hasScrolledRef.current = false;

      // 根据数据自动选择默认tab（仅在首次加载或用户未手动切换时）
      if (!hasUserSwitchedTabRef.current) {
        const baseData = data?.baseData || {};
        const sprintsCount = baseData.sprints_count || 0;
        const safesCount = baseData.safes_count || 0;
        const protectsCount = baseData.protects_count || 0;

        // 按照冲稳保优先级，选择第一个有数据的tab
        if (sprintsCount > 0) {
          setActiveFilter('sprints');
        } else if (safesCount > 0) {
          setActiveFilter('safes');
        } else if (protectsCount > 0) {
          setActiveFilter('protects');
        }
      }
    } else {
      message.error('获取志愿列表失败');
    }
    setIsLoading(false);
  };

  // 志愿列表返回后，同步学费区间数据
  useEffect(() => {
    const range = volunteerData?.baseData?.tuitionRange;
    if (range && typeof range.min === 'number' && typeof range.max === 'number') {
      const newRange: [number, number] = [range.min, range.max];
      setTuitionRange(newRange);
      setDisplayTuitionRange(prev => {
        // 如果之前没有值，或者之前值与新值不一致，则更新
        if (!prev || prev[0] !== newRange[0] || prev[1] !== newRange[1]) {
          return newRange;
        }
        return prev;
      });
    }
  }, [volunteerData?.baseData?.tuitionRange]);

  useEffect(() => {
    console.log('Volunteer: fetchFlag 变化，当前值:', fetchFlag);
    // 数据刷新时，重置用户切换标记，允许自动选择tab
    hasUserSwitchedTabRef.current = false;
    fetchVolunteerRecommendList();
  }, [fetchFlag]);

  const onChange = (key: string | string[]) => {
    console.log(key);
  };

  // 导出志愿表
  const handleExport = async () => {
    try {
      // 调用API获取响应对象（包含 headers）
      const response: any = await getVolunteerExportApi(
        routerParams.tenantId,
        routerParams.chatSessionId
      );

      // 从响应头中提取文件名
      let fileName = `志愿表_${new Date().toLocaleDateString()}.xlsx`; // 默认文件名
      const contentDisposition = response.headers?.['content-disposition'] || response.headers?.['Content-Disposition'];

      if (contentDisposition) {
        // 解析 Content-Disposition 头，支持 UTF-8 编码的文件名
        // 格式可能是: attachment; filename*=UTF-8''encodedFileName 或 attachment; filename="fileName"
        const utf8FileNameMatch = contentDisposition.match(/filename\*=UTF-8''(.+)/i);
        const regularFileNameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);

        if (utf8FileNameMatch) {
          // 解码 UTF-8 编码的文件名
          fileName = decodeURIComponent(utf8FileNameMatch[1]);
        } else if (regularFileNameMatch) {
          fileName = regularFileNameMatch[1];
        }
      }

      // 创建下载链接
      const downloadUrl = window.URL.createObjectURL(response.data);

      // 创建临时链接并触发下载
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = fileName; // 使用从响应头解析的文件名
      document.body.appendChild(a);
      a.click();

      // 清理
      document.body.removeChild(a);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      message.error('导出志愿表失败，请稍后重试');
      console.error('导出失败:', error);
    }
  };

  // 处理Tag点击事件
  const handleFilterClick = (filterType: FilterType) => {
    // 标记用户已手动切换过tab
    hasUserSwitchedTabRef.current = true;
    setActiveFilter(filterType);
    // 切换筛选类型时，重置已加载数量，清理 observer targets
    setLoadedCounts({});
    observerTargetsRef.current = {};
  };

  // 根据选中的筛选类型获取数据
  const getDisplayData = () => {
    // 获取 three_target_count_map 数据，如果不存在则使用默认值
    const targetCountMap = volunteerData?.baseData?.three_target_count_map || {};

    // 根据筛选类型获取原始数据
    let originalData: any[] = [];
    let preferredCount = 0;

    switch (activeFilter) {
      case 'sprints':
        originalData = volunteerData?.sprints || [];
        preferredCount = targetCountMap.sprints_count || originalData.length;
        break;
      case 'safes':
        originalData = volunteerData?.safes || [];
        preferredCount = targetCountMap.safes_count || originalData.length;
        break;
      case 'protects':
        originalData = volunteerData?.protects || [];
        preferredCount = targetCountMap.protects_count || originalData.length;
        break;
      default:
        originalData = volunteerData?.sprints || [];
        preferredCount = targetCountMap.sprints_count || originalData.length;
    }

    // 检查是否完全没有数据
    if (originalData.length === 0) {
      return {
        isEmpty: true,
        tabActive: activeFilter,
      };
    }

    // 将数据分为优选和候选两部分
    const preferredData = originalData.slice(0, preferredCount);
    const alternativeData = originalData.slice(preferredCount);

    return {
      isEmpty: false,
      data: [
        {
          type: 'preferred',
          title: '优报志愿',
          tabActive: activeFilter,
          data: preferredData,
          totalCount: preferredData.length,
        },
        {
          type: 'alternative',
          title: alternativeData.length === 0 ? '暂无候补志愿' : '候补志愿',
          tabActive: activeFilter,
          data: alternativeData,
          totalCount: alternativeData.length,
        },
      ],
    };
  };

  // 获取当前应该显示的数据（根据已加载数量）
  // 优报志愿（preferred）不需要分页，候补志愿（alternative）需要分页
  const getVisibleData = (sectionKey: string, type: string, allData: any[]) => {
    // 优报志愿直接返回全部数据
    if (type === 'preferred') {
      return allData;
    }
    // 候补志愿才进行分页加载
    const loadedCount = loadedCounts[sectionKey]?.[type] ?? PAGE_SIZE;
    return allData.slice(0, loadedCount);
  };

  // 加载更多数据
  const loadMore = useCallback((sectionKey: string, type: string, totalCount: number) => {
    const key = `${sectionKey}-${type}`;
    const isLoading = isLoadingMore[sectionKey]?.[type] ?? false;

    if (isLoading) return;

    const currentLoaded = loadedCounts[sectionKey]?.[type] ?? PAGE_SIZE;

    if (currentLoaded >= totalCount) {
      // 已经加载全部数据
      return;
    }

    setIsLoadingMore(prev => ({
      ...prev,
      [sectionKey]: {
        ...prev[sectionKey],
        [type]: true,
      },
    }));

    // 使用 requestAnimationFrame 来确保状态更新后立即加载
    requestAnimationFrame(() => {
      setLoadedCounts(prev => ({
        ...prev,
        [sectionKey]: {
          ...prev[sectionKey],
          [type]: Math.min((prev[sectionKey]?.[type] ?? PAGE_SIZE) + PAGE_SIZE, totalCount),
        },
      }));
      setIsLoadingMore(prev => ({
        ...prev,
        [sectionKey]: {
          ...prev[sectionKey],
          [type]: false,
        },
      }));
    });
  }, [isLoadingMore, loadedCounts]);

  const displayData = getDisplayData();

  // 监听滚动事件，标记用户已滚动
  useEffect(() => {
    const handleScroll = () => {
      hasScrolledRef.current = true;
    };

    const scrollContainer = findScrollContainer();

    // 监听 window 滚动
    window.addEventListener('scroll', handleScroll, { passive: true });

    if (scrollContainer) {
      scrollContainer.addEventListener('scroll', handleScroll, { passive: true });
    }

    return () => {
      window.removeEventListener('scroll', handleScroll);
      if (scrollContainer) {
        scrollContainer.removeEventListener('scroll', handleScroll);
      }
    };
  }, [findScrollContainer, isLoading]);

  // 使用 Intersection Observer 监听滚动到底部
  useEffect(() => {
    const observers: IntersectionObserver[] = [];
    let loadingTimer: NodeJS.Timeout | null = null;

    // 延迟一下，确保 DOM 已经渲染
    const timer = setTimeout(() => {
      // 为每个 section 创建独立的 observer
      Object.keys(observerTargetsRef.current).forEach(key => {
        const target = observerTargetsRef.current[key];
        if (!target) return;

        const observer = new IntersectionObserver(
          entries => {
            const entry = entries[0];
            // 只有当元素真正进入视口时才触发，并且用户已经滚动过
            if (entry.isIntersecting && entry.intersectionRatio > 0 && hasScrolledRef.current) {
              // 从 key 中解析 sectionKey 和 type
              const [sectionKey, type] = key.split('-');
              // 只有候补志愿才需要加载更多
              if (type === 'alternative' && !displayData.isEmpty && displayData.data) {
                const item = displayData.data.find(
                  (d: any) => d.tabActive === sectionKey && d.type === type
                );
                if (item) {
                  const visibleData = getVisibleData(sectionKey, type, item.data);
                  const currentLoaded = visibleData.length;
                  const isLoading = isLoadingMore[sectionKey]?.[type] ?? false;

                  // 只有在未加载全部数据且当前未在加载时才触发
                  if (currentLoaded < item.totalCount && !isLoading) {
                    // 清除之前的定时器，防止重复触发
                    if (loadingTimer) {
                      clearTimeout(loadingTimer);
                    }
                    // 添加小延迟，避免快速连续触发
                    loadingTimer = setTimeout(() => {
                      loadMore(sectionKey, type, item.totalCount);
                    }, 200);
                  }
                }
              }
            }
          },
          {
            // 使用 null 表示使用最近的滚动容器（window 或最近的 overflow 容器）
            root: null,
            // 只在距离底部100px时触发
            rootMargin: '0px 0px 100px 0px',
            // 当元素至少50%可见时才触发，避免元素刚进入视口就触发
            threshold: 0.5,
          }
        );

        observer.observe(target);
        observers.push(observer);
      });
    }, 100);

    return () => {
      clearTimeout(timer);
      if (loadingTimer) {
        clearTimeout(loadingTimer);
      }
      observers.forEach(observer => observer.disconnect());
    };
  }, [displayData, loadMore, activeFilter, isLoadingMore]);

  return (
    <div ref={panelRef} className={`${style.volunteerPanel} ${isMobile ? style.mobile : ''}`}>
      <div className={style.volunteerTarget}>
        <div className={style.header}>
          <div className={style.leftContent}>
            <div className={style.title}>
              <span>{volunteerData.baseData?.reportName || '我的志愿表'}</span>
              {sessionStatus === 'FINISHED' && (
                <span style={{ marginLeft: 12, display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 14, color: '#52c41a' }}>
                  <CheckCircleOutlined />
                  <span>已提交</span>
                  <LockOutlined style={{ marginLeft: 4, fontSize: 12, color: '#8b8fa1' }} />
                  <span style={{ color: '#8b8fa1', fontSize: 12, marginLeft: 4 }}>不可修改</span>
                </span>
              )}
              {volunteerData.baseData?.prepareType?.desc && (
                <Tag color="blue" style={{ marginLeft: 12, verticalAlign: 'middle', display: 'inline-flex', alignItems: 'center' }}>
                  {volunteerData.baseData.prepareType.desc}
                </Tag>
              )}
            </div>
            <div className={style.subTitle}>{volunteerData.baseData?.userInfoSummary}</div>
            {tuitionRange && (
              <div className={style.tuitionBar}>
                <div className={style.tuitionLabel}>
                  学费区间：
                  <span className={style.tuitionValue}>
                    {formatTuitionValue(displayTuitionRange?.[0] ?? tuitionRange[0])} -{' '}
                    {formatTuitionValue(displayTuitionRange?.[1] ?? tuitionRange[1])}
                  </span>
                </div>
              </div>
            )}
          </div>
          <div className={style.rightContent}>
            <Button onClick={handleExport} disabled={!routerParams.chatSessionId}>
              导出
            </Button>
          </div>
        </div>
        <div className={style.volunteerMain}>
          <div
            className={`${style.tabs} ${
              activeFilter === 'sprints'
                ? style.tabsSprints
                : activeFilter === 'safes'
                ? style.tabsSafes
                : activeFilter === 'protects'
                ? style.tabsProtects
                : ''
            }`}
          >
            <div
              className={`${style.tabsItem} ${
                activeFilter === 'sprints' ? style.activeSprints : ''
              }`}
              onClick={() => handleFilterClick('sprints')}
            >
              <div className={style.itemTitle}>
                {isMobile ? '冲' : '可冲击'} {volunteerData?.baseData?.sprints_count || 0}
              </div>
              <div className={style.itemSubTitle}>
                <span>{isMobile ? '优' : '优报'} {volunteerCounts.sprints.preferred}</span>
                {!isMobile && <i>|</i>}
                <span>{isMobile ? '候' : '候补'} {volunteerCounts.sprints.alternative}</span>
              </div>
            </div>
            <div
              className={`${style.tabsItem} ${activeFilter === 'safes' ? style.activeSafes : ''}`}
              onClick={() => handleFilterClick('safes')}
            >
              <div className={style.itemTitle}>
                {isMobile ? '稳' : '较稳妥'} {volunteerData?.baseData?.safes_count || 0}
              </div>
              <div className={style.itemSubTitle}>
                <span>{isMobile ? '优' : '优报'} {volunteerCounts.safes.preferred}</span>
                {!isMobile && <i>|</i>}
                <span>{isMobile ? '候' : '候补'} {volunteerCounts.safes.alternative}</span>
              </div>
            </div>
            <div
              className={`${style.tabsItem} ${
                activeFilter === 'protects' ? style.activeProtects : ''
              }`}
              onClick={() => handleFilterClick('protects')}
            >
              <div className={style.itemTitle}>
                {isMobile ? '保' : '较保险'} {volunteerData?.baseData?.protects_count || 0}
              </div>
              <div className={style.itemSubTitle}>
                <span>{isMobile ? '优' : '优报'} {volunteerCounts.protects.preferred}</span>
                {!isMobile && <i>|</i>}
                <span>{isMobile ? '候' : '候补'} {volunteerCounts.protects.alternative}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className={style.volunteerCollopse} ref={scrollContainerRef}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '40px' }}>
            <Spin size="large" />
          </div>
        ) : displayData.isEmpty ? (
          <div style={{
            textAlign: 'center',
            padding: '80px 20px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span style={{ color: '#8b8fa1', fontSize: '14px' }}>
                  {activeFilter === 'sprints'
                    ? '冲'
                    : activeFilter === 'safes'
                    ? '稳'
                    : '保'}区间暂无合适的志愿
                </span>
              }
            />
          </div>
        ) : (
          <>
            {displayData.data?.map((item: any) => {
              const sectionKey = item.tabActive;
              const isCollapsed = collapsedSections[sectionKey]?.[item.type] ?? false;
              const handleToggleSection = () => {
                setCollapsedSections(prev => ({
                  ...prev,
                  [sectionKey]: {
                    ...prev[sectionKey],
                    [item.type]: !isCollapsed,
                  },
                }));
              };

              // 获取当前可见的数据
              const visibleData = getVisibleData(sectionKey, item.type, item.data);
              const currentLoaded = visibleData.length;
              // 只有候补志愿才需要分页加载
              const hasMore = item.type === 'alternative' && currentLoaded < item.totalCount;

              return (
                <div className={style.volunteerSection} key={`${sectionKey}-${item.type}`}>
                  <div
                    className={`${style.volunteerTitle} ${
                      isCollapsed ? style.volunteerTitleCollapsed : ''
                    }`}
                  >
                    <span>
                      {item.title}
                      {/* 显示总数：优报志愿显示总数，候补志愿显示加载进度 */}
                      {item.totalCount > 0 && (
                        <span style={{ marginLeft: 8, fontSize: 12, color: '#8b8fa1', fontWeight: 'normal' }}>
                          {item.type === 'preferred'
                            ? `(${item.totalCount})`
                            : `(${currentLoaded}/${item.totalCount})`
                          }
                        </span>
                      )}
                    </span>
                    <div className={style.volunteerToggle} onClick={handleToggleSection}>
                      <span>{isCollapsed ? '展开' : '收起'}</span>
                      <DownOutlined
                        className={`${style.toggleIcon} ${
                          isCollapsed ? style.toggleIconCollapsed : ''
                        }`}
                      />
                    </div>
                  </div>
                  {!isCollapsed && (
                    <>
                      <Collapse
                        defaultActiveKey={['0']}
                        onChange={onChange}
                        key={`${sectionKey}-${item.type}`}
                      >
                        {visibleData?.map((school: any, index: number) => (
                          <Panel
                            key={index}
                            showArrow={false}
                            header={
                              <CollapseHeader
                                tabActive={item.tabActive}
                                schoolName={school.school_name}
                                schoolRank={school.school_rank}
                                basicTagList={school.basicTagList}
                                rankTagList={school.rankTagList}
                                historyScoreList={school.history_score_list}
                                enrollRatio={school.enroll_ratio}
                                baoyanRatio={school.baoyan_ratio}
                                majors={school.majors}
                                advantages={school.strong_major}
                                masterCount={school.master_count}
                                doctoralCount={school.doctor_count}
                                popTagList={school.popTagList}
                                recommendationRate={school.baoyan_ratio}
                                admissionRate={school.enroll_ratio}
                                index={index + 1}
                              />
                            }
                          >
                            <CollapseContent
                              majors={school.majors}
                              tabActive={item.tabActive}
                              volunteerModel={volunteerData?.baseData?.volunteerModel}
                              volunteerCount={volunteerData?.baseData?.volunteerCount}
                              isMobile={isMobile}
                            />
                          </Panel>
                        ))}
                      </Collapse>
                      {/* 只有候补志愿才显示加载更多提示 */}
                      {item.type === 'alternative' && hasMore && (
                        <div
                          ref={(el) => {
                            const key = `${sectionKey}-${item.type}`;
                            observerTargetsRef.current[key] = el;
                          }}
                          style={{
                            textAlign: 'center',
                            padding: '16px',
                            color: '#8b8fa1',
                            fontSize: 12,
                          }}
                        >
                          {isLoadingMore[sectionKey]?.[item.type] ? (
                            <Spin size="small" />
                          ) : (
                            <span>滚动加载更多...</span>
                          )}
                        </div>
                      )}
                      {item.type === 'alternative' && !hasMore && item.totalCount > 0 && (
                        <div
                          style={{
                            textAlign: 'center',
                            padding: '16px',
                            color: '#8b8fa1',
                            fontSize: 12,
                          }}
                        >
                          已加载全部数据
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </>
        )}
      </div>

      {isMobile && (
        <FloatButton.BackTop
          tooltip="回顶部"
          target={() => findScrollContainer() || document.documentElement}
          visibilityHeight={200}
          style={{ right: 16, bottom: 80 }}
        />
      )}
    </div>
  );
};

export default Volunteer;
