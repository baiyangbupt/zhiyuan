import {useState, useEffect, useRef} from 'react';
import {getValueFromUrlBykey} from '@/utils/tool';
import {ESessionStatus} from '@/interface/api/assistant';
import {updateUrlParameter} from '@/utils/router'

interface ParamsType<T> {
  listApi: (tenantId: string, params: any) => Promise<{ code: number; data: T; [key: string]: any }>;
  otherParams?: Record<string, any>;
  preParams?: Record<string, any>;
  tableConfig?: [string, string];
  pageConfig?: [string, string];
  defaultSearchBar?: Record<string, any>;
  beforeRefreshData?: (data: T) => T;
  tenantId?: string;
}

const useList = (params: ParamsType<Record<string, any>>) => {
    const initialPage = parseInt(getValueFromUrlBykey('page') as string) || 1;
    const initialPageSize =
        parseInt(getValueFromUrlBykey('pageSize') as string) || 20;
    const {
        listApi, otherParams = {},
        preParams = {},
        tableConfig = ['records', 'total'],
        pageConfig = ['page', 'pageSize'],
        defaultSearchBar, beforeRefreshData,
        tenantId: propTenantId,
    } = params;

    const [combinedData, setCombinedData] = useState<{ records: any[]; total: number; otherData: Record<string, any> }>({records: [], total: 0, otherData: {}});
    const searchBar = useRef<Record<string, any>>(defaultSearchBar || {});
    const [searchLoading, setSearchLoading] = useState<boolean>(false);
    const pagination = useRef({ page: initialPage, pageSize: initialPageSize });

    const initSearchBar = () => {
        if (defaultSearchBar && typeof defaultSearchBar === 'object') {
            searchBar.current = defaultSearchBar;
        }
        else {
            searchBar.current = {};
        }
    };

    const tableDataList = (result: any) => {
        const [list, total] = tableConfig;
        const tableRecords = result?.[list] || result || [];
        const tableTotal = result?.[total] || 0;
        const {[list]: reaultList, [total]: reaultTotal, ...otherData} = result;

        setCombinedData({records: tableRecords, total: tableTotal, otherData});
    };

    const transformPage = () => {
        const pageParams: Record<string, number> = {};
        const {page, pageSize} = pagination.current;
        const [pageKey, sizeKey] = pageConfig;
        pageParams[pageKey] = page;
        pageParams[sizeKey] = pageSize;
        return pageParams;
    };

    const refresh = async () => {
        try {
            setSearchLoading(true);
            let dataParams = {...otherParams, ...preParams, ...searchBar.current};
            if (beforeRefreshData && typeof beforeRefreshData === 'function') {
                const transformedDataParams = beforeRefreshData(dataParams);
                dataParams = {...dataParams, ...transformedDataParams};
            }
            const tenantId = propTenantId || getValueFromUrlBykey('tenantId') || '';
            const {code, data} = await listApi(tenantId, {...dataParams, ...transformPage()});
            if (code === 0 && data) {
                tableDataList(data);
            }
        }
        catch (e) {
            console.error(e);
        }
        finally {
            setSearchLoading(false);
        }
    };

    const reset = () => {
        initSearchBar();
        pagination.current.page = 1;
        refresh();
    };

    const handleSearchbar = (form: any) => {
        searchBar.current = form;
    };

    useEffect(() => {
        refresh();
    }, []);

    const handlePageChange = (val: number) => {
        pagination.current.page = val;
        refresh();
        updateUrlParameter({page: String(val)})
    };

    const handleSizeChange = (val: number) => {
        pagination.current.page = 1;
        pagination.current.pageSize = val;
        refresh();
        updateUrlParameter({ page: '1', pageSize: String(val) });
    };

    const search = (form: any) => {
        searchBar.current = form;
        pagination.current.page = 1;
        refresh();
    };

    const searchOptions = {
        sessionStatus: [
            {label: '初始化', value: ESessionStatus.WAIT},
            {label: '服务中', value: ESessionStatus.GOING},
            {label: '已提交', value: ESessionStatus.FINISHED}
        ]
    };

    const configSearch = [
        {
            type: 'select',
            formItem: {
                label: '状态',
                name: 'sessionStatus',
            }
        },
        {
            type: 'input',
            formItem: {
                label: '关键词',
                name: 'infoSummary',
            }
        },
    ];

    return {
        combinedData,
        pagination: pagination.current,
        searchLoading,
        handleSearchbar,
        search,
        reset,
        refresh,
        handlePageChange,
        handleSizeChange,
        searchOptions,
        configSearch,
    };
};

export default useList;
