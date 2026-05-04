import aiohttp
import os
import random
from typing import Dict, Any, Optional, List, Union
from loguru import logger

class HttpClient:
    """HTTP 客户端，封装了 aiohttp 请求操作"""
    
    def __init__(self):
        # 从环境变量获取多个内部服务地址，用逗号分隔
        internal_service_urls = os.getenv("INTERNAL_SERVICE_URLS", "10.218.4.10:8090")
        self.base_urls = [url.strip() for url in internal_service_urls.split(",")]
        self.default_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    def _get_random_base_url(self) -> str:
        """随机选择一个基础URL"""
        url = random.choice(self.base_urls)
        # logger.info(f"随机选择的基础URL: {url}")
        return url
    
    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败"
    ) -> Dict[str, Any]:
        """
        发送 GET 请求
        
        Args:
            endpoint: API 端点路径（不包含 base_url）
            params: 查询参数
            headers: 请求头（如果提供，将与默认请求头合并）
            error_msg: 错误信息前缀
            
        Returns:
            Dict[str, Any]: 服务器返回的 JSON 响应
        """
        base_url = self._get_random_base_url()
        url = f"http://{base_url}{endpoint}"
        merged_headers = {**self.default_headers}
        if headers:
            merged_headers.update(headers)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=merged_headers) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error(f"{error_msg}: {response.status}, {result}")
                    return result
        except Exception as e:
            logger.error(f"{error_msg}异常: {e}")
            return {"error": str(e), "success": False, "data": {}}
    
    async def post(
        self,
        endpoint: str,
        json_data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        error_msg: str = "请求失败"
    ) -> Dict[str, Any]:
        """
        发送 POST 请求
        
        Args:
            endpoint: API 端点路径（不包含 base_url）
            json_data: 请求体数据，将被序列化为 JSON
            headers: 请求头（如果提供，将与默认请求头合并）
            error_msg: 错误信息前缀
            
        Returns:
            Dict[str, Any]: 服务器返回的 JSON 响应
        """
        base_url = self._get_random_base_url()
        url = f"http://{base_url}{endpoint}"
        merged_headers = {**self.default_headers}
        if headers:
            merged_headers.update(headers)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=json_data, headers=merged_headers) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.error(f"{error_msg}: {response.status}, {result}")
                    return result
        except Exception as e:
            logger.error(f"{error_msg}异常: {e}")
            return {"error": str(e), "success": False}

# 创建全局 HTTP 客户端实例
http_client = HttpClient()


async def get_all_messages(thread_id: str) -> Dict[str, Any]:
    """
    异步获取聊天会话的所有消息
    
    Args:
        thread_id: 会话ID
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据，包含所有消息
    """
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/chat/1/message/list-all",
        params={"chatSessionId": thread_id},
        error_msg="获取消息失败"
    )

async def save_user_profile(chat_session_id: int, data_value: Dict[str, Any]) -> Dict[str, Any]:
    """
    异步存储用户画像数据
    
    Args:
        chat_session_id: 会话ID
        data_value: 用户画像数据，例如 {"city_info": {"province": ["北京"]}}
    
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    payload = {
        "chatSessionId": chat_session_id,
        "dataKey": "userprofile",
        "dataType": "JSON_OBJECT",
        "dataValue": data_value
    }
    
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/session/add-extra-data",
        json_data=payload,
        error_msg="存储用户画像失败"
    )

async def get_user_profile(chat_session_id: Union[str, int]) -> Dict[str, Any]:
    """
    异步获取用户画像数据
    
    Args:
        chat_session_id: 会话ID
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据，包含用户画像数据
    """
    result = await get_extra_data(chat_session_id, "userprofile")
    return result

async def get_extra_data(chat_session_id: Union[str, int], key_list: Union[List[str], str]) -> Dict[str, Any]:
    """
    异步获取额外数据
    
    Args:
        chat_session_id: 会话ID
        key_list: 需要获取的数据键列表，可以是字符串列表或以逗号分隔的字符串
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据，包含请求的额外数据
    """
    # 如果key_list是列表，则转换为逗号分隔的字符串
    if isinstance(key_list, list):
        key_list_str = ",".join(key_list)
    else:
        key_list_str = key_list
    
    params = {
        "chatSessionId": chat_session_id,
        "keyList": key_list_str
    }
    
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/chat/1/session/get-extra-data",
        params=params,
        error_msg="获取额外数据失败"
    )

async def query_program(
    chat_session_id: Union[str, int],
    areas: Optional[List[str]] = None,
    cities: Optional[List[str]] = None,
    classify_list: Optional[List[str]] = None,
    major_id_list: Optional[List[str]] = None,
    min_tuition_fee_m: int = 0,
    max_tuition_fee_m: int = 0,
    nature_list: Optional[List[str]] = None,
    registration_condition_list: Optional[List[str]] = None,
    special_filter_list: Optional[List[str]] = None,
    include_school_list: Optional[List[str]] = None,
    exclude_school_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    异步查询专业项目
    
    Args:
        chat_session_id: 会话ID
        areas: 地区代码列表，例如 ["110000"]
        cities: 城市代码列表
        classify_list: 分类列表
        major_id_list: 专业ID列表
        min_tuition_fee_m: 最低学费（单位：万元）
        max_tuition_fee_m: 最高学费（单位：万元）
        nature_list: 性质列表
        registration_condition_list: 报名条件列表
        special_filter_list: 特殊筛选列表
        includeSchoolList: 正向院校筛选
        excludeSchoolList: 负向院校过滤
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    # 构建请求体
    payload = {
        "chatSessionId": chat_session_id,
        "areas": areas or [],
        "cities": cities or [],
        "classifyList": classify_list or [],
        "majorIdList": major_id_list or [],
        "minTuitionFeeM": min_tuition_fee_m,
        "maxTuitionFeeM": max_tuition_fee_m,
        "natureList": nature_list or [],
        "registrationConditionList": registration_condition_list or [],
        "specialFilterList": special_filter_list or [],
        "includeSchoolList": include_school_list or [],
        "excludeSchoolList": exclude_school_list or []
    }
    
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/program/countBySnap",
        json_data=payload,
        error_msg="查询专业项目失败"
    )

async def query_by_snap(
    chat_session_id: Union[str, int],
    areas: Optional[List[str]] = None,
    cities: Optional[List[str]] = None,
    classify_list: Optional[List[str]] = None,
    major_id_list: Optional[List[str]] = None,
    min_tuition_fee_m: int = 0,
    max_tuition_fee_m: int = 0,
    nature_list: Optional[List[str]] = None,
    registration_condition_list: Optional[List[str]] = None,
    special_filter_list: Optional[List[str]] = None,
    include_school_list: Optional[List[str]] = None,
    exclude_school_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    异步查询并保存专业项目
    
    Args:
        chat_session_id: 会话ID
        areas: 地区代码列表，例如 ["110000"]
        cities: 城市代码列表
        classify_list: 分类列表
        major_id_list: 专业ID列表
        min_tuition_fee_m: 最低学费（单位：万元）
        max_tuition_fee_m: 最高学费（单位：万元）
        nature_list: 性质列表
        registration_condition_list: 报名条件列表
        special_filter_list: 特殊筛选列表
        includeSchoolList: 正向院校筛选
        excludeSchoolList: 负向院校过滤
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    # 构建请求体
    payload = {
        "chatSessionId": chat_session_id,
        "areas": areas or [],
        "cities": cities or [],
        "classifyList": classify_list or [],
        "majorIdList": major_id_list or [],
        "minTuitionFeeM": min_tuition_fee_m,
        "maxTuitionFeeM": max_tuition_fee_m,
        "natureList": nature_list or [],
        "registrationConditionList": registration_condition_list or [],
        "specialFilterList": special_filter_list or [],
        "includeSchoolList": include_school_list or [],
        "excludeSchoolList": exclude_school_list or []
    }
    
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/program/queryBySnap",
        json_data=payload,
        error_msg="查询并保存专业项目失败"
    )

async def query_recommend_schools(
    chat_session_id: Union[str, int],
    areas: Optional[List[str]] = None,
    cities: Optional[List[str]] = None,
    classify_list: Optional[List[str]] = None,
    major_id_list: Optional[List[str]] = None,
    nature_list: Optional[List[str]] = None,
    registration_condition_list: Optional[List[str]] = None,
    special_filter_list: Optional[List[str]] = None,
    include_school_list: Optional[List[str]] = None,
    exclude_school_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    异步查询推荐院校
    
    Args:
        chat_session_id: 会话ID
        areas: 地区代码列表，例如 ["110000"]
        cities: 城市代码列表
        classify_list: 分类列表
        major_id_list: 专业ID列表
        nature_list: 性质列表
        registration_condition_list: 报名条件列表
        special_filter_list: 特殊筛选列表
        include_school_list: 正向院校筛选
        exclude_school_list: 负向院校过滤
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    # 构建请求体
    payload = {
        "chatSessionId": chat_session_id,
        "areas": areas or [],
        "cities": cities or [],
        "classifyList": classify_list or [],
        "majorIdList": major_id_list or [],
        "natureList": nature_list or [],
        "registrationConditionList": registration_condition_list or [],
        "specialFilterList": special_filter_list or [],
        "includeSchoolList": include_school_list or [],
        "excludeSchoolList": exclude_school_list or []
    }
    
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/program/recommendSchoolBySnap",
        json_data=payload,
        error_msg="查询推荐院校失败"
    )

async def query_recommend_schools_by_score(
    chat_session_id: Union[str, int],
    area_id: Optional[str] = None,
    prepare_type: Optional[str] = None,
    subjects: Optional[str] = None,
    score: Optional[int] = None,
    batch: Optional[str] = None,
    record_num_limit: Optional[int] = 10
) -> Dict[str, Any]:
    """
    异步查询推荐院校
    
    Args:
        chat_session_id: 会话ID
        area_id: 地区代码，例如 "110000"
        prepare_type: 填报类型, 例如 "PREDICT"、""
        subject_type: 选科类型, 例如 ""
        batch: 批次, 例如"01"
        record_num_limit: 返回数量, 例如10
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    # 构建请求体
    payload = {
        "chatSessionId": chat_session_id,
        "areaId": area_id or None,
        "prepareType": prepare_type or None,
        "subjects": subjects or None,
        "score": score or None,
        # "subject_type": "WL",
        "batch": batch,
        "recordNumLimit": record_num_limit or 10
    }
    print(payload)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/program/queryProgramByLimitNum",
        json_data=payload,
        error_msg="指定分数查询院校失败"
    )



async def query_school_enroll(
    chat_session_id: Union[str, int],
    school_id:str
) -> Dict[str, Any]:
    """
    异步查询院校录取概率
    
    Args:
        chat_session_id: 会话ID
        school_id: 学校ID
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
        {
            "data": {
                "canJoin": true,
                "sprintMajorList": [],
                "safeMajorList": [],
                "protectMajorList": [
                    {
                        "majorId": "258",
                        "majorName": "国际经济与贸易",
                        "majorEnrollRatio": "86",
                        "majorPlanNum": 2
                    },
                    {
                        "majorId": "843",
                        "majorName": "财务管理",
                        "majorEnrollRatio": "86",
                        "majorPlanNum": 2
                    },
                    {
                        "majorId": "881",
                        "majorName": "电子商务",
                        "majorEnrollRatio": "86",
                        "majorPlanNum": 2
                    }
                ]
            },
            "code": 0,
            "msg": "success"
        }
    """
    
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/chat/1/program/detailSchoolBySnap",
        params=dict(sessionId=chat_session_id,schoolId=school_id),
        error_msg="查询院校录取概率失败"
    )

async def query_school_major_score_line(
    school_id:str,
    area_id: str,
    batch: str,
    subject_type: str,
    major_id: Optional[str] = None,
    year: Optional[int] = 2024,
) -> Dict[str, Any]:
    """
    异步查询院校录取概率
    
    Args:
        chat_session_id: 会话ID
        school_id: 学校ID
        area_id: 省份ID
        batch: 批次
        major_id: 专业ID
        subject_type: 文理分科
        year: 年份
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
        {
        "data": [
            {
                "year": 2024,
                "name": "北京大学第03组(国家专项)",
                "batch": "01",
                "batchTitle": "本科批",
                "enrollNum": "6",
                "maxScore": "0",
                "minScore": "650",
                "averageScore": "0",
                "volunteerLevel": null,
                "minPos": "97",
                "maxPos": "0",
                "selectInfo": "历"
            },
            {
                "year": 2024,
                "name": "北京大学第02组",
                "batch": "01",
                "batchTitle": "本科批",
                "enrollNum": "23",
                "maxScore": "0",
                "minScore": "661",
                "averageScore": "0",
                "volunteerLevel": null,
                "minPos": "30",
                "maxPos": "0",
                "selectInfo": "历"
            },
            {
                "year": 2024,
                "name": "北京大学第06组(国家专项)",
                "batch": "01",
                "batchTitle": "本科批",
                "enrollNum": "9",
                "maxScore": "0",
                "minScore": "677",
                "averageScore": "0",
                "volunteerLevel": null,
                "minPos": "412",
                "maxPos": "0",
                "selectInfo": "物和化"
            },
            {
                "year": 2024,
                "name": "北京大学第04组(国家专项)",
                "batch": "01",
                "batchTitle": "本科批",
                "enrollNum": "1",
                "maxScore": "0",
                "minScore": "679",
                "averageScore": "0",
                "volunteerLevel": null,
                "minPos": "332",
                "maxPos": "0",
                "selectInfo": "物"
            },
            {
                "year": 2024,
                "name": "北京大学第05组",
                "batch": "01",
                "batchTitle": "本科批",
                "enrollNum": "30",
                "maxScore": "0",
                "minScore": "691",
                "averageScore": "0",
                "volunteerLevel": null,
                "minPos": "83",
                "maxPos": "0",
                "selectInfo": "物和化"
            }
        ],
        "code": 0,
        "msg": "success"
        }
    """
    payload = {
        "schoolId": school_id,
        "areaId": area_id,
        "batch": batch,
        "subjectType": subject_type,
        "year" : year,
        "majorId": major_id
    }
    print(payload)
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/program/querySchoolMajorScoreLine",
        error_msg="查询院校专业分数线失败",
        json_data=payload
    )

async def get_latest_major_test_result(chat_session_id: Union[str, int]) -> Dict[str, Any]:
    """
    异步获取最新的报告测试
    
    Args:
        chat_session_id: 会话ID
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    return await http_client.get(
        endpoint="/gaotu-assistant-bot/chat/1/report/last",
        params={"chatSessionId": chat_session_id},
        error_msg="获取最新报告测试失败"
    )

async def add_do_report_count(chat_session_id: Union[str, int]) -> Dict[str, Any]:
    """
    异步增加 do_report_count 中的 count 值
    
    Args:
        chat_session_id: 会话ID
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    # 获取当前的 do_report_count 数据
    result = await get_extra_data(chat_session_id, "chatvariables")
    
    # 从响应中提取数据值
    data = {}

    if "data" in result and result["data"]:
        # 从后端数据创建用户信息
        data = result["data"].get("chatvariables", {})
    
    # 如果 count 不存在或不是数字，初始化为 0
    if "doReportCount" not in data or not isinstance(data["doReportCount"], int):
        data["doReportCount"] = 0
    
    # count 加 1
    data["doReportCount"] += 1
    
    # 构建请求体并通过 add-extra-data 接口存储
    payload = {
        "chatSessionId": chat_session_id,
        "dataKey": "chatvariables",
        "dataType": "JSON_OBJECT",
        "dataValue": data
    }
    
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/session/add-extra-data",
        json_data=payload,
        error_msg="更新 do_report_count 失败"
    )


    
async def get_user_program_major3_summary(thread_id: str) -> Dict[str, Any]:
    """
    获取用户填报方案中level3专业的总结
    """
    result = await get_extra_data(thread_id, "userProgram3MajorSummary")
    return result

async def get_user_program_area_summary(thread_id: str) -> Dict[str, Any]:
    """
    获取用户填报方案中地区的总结
    """
    result = await get_extra_data(thread_id, "userProgramAreaSummary")
    return result

async def create_session(bot_id: int, form_id: int, member_id: int) -> Dict[str, Any]:
    """
    异步创建聊天会话
    
    Args:
        bot_id: 机器人ID
        form_id: 表单ID
        member_id: 用户ID
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    payload = {
        "botId": bot_id,
        "formId": form_id,
        "memberId": member_id
    }
    
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/session/create",
        json_data=payload,
        error_msg="创建会话失败"
    )

async def save_message(
    chat_session_id: Union[str, int], 
    content: str, 
    message_from: str, 
    content_type: str = "TEXT", 
    meeting_id: int = 1
) -> Dict[str, Any]:
    """
    异步保存聊天消息
    
    Args:
        chat_session_id: 会话ID
        content: 消息内容
        message_from: 消息来源，如 "1"
        content_type: 消息类型，默认为 "TEXT"
        meeting_id: 会议ID，默认为 0
        
    Returns:
        Dict[str, Any]: 服务器返回的JSON响应数据
    """
    payload = {
        "chatSessionId": chat_session_id,
        "content": content,
        "contentType": content_type,
        "meetingId": meeting_id,
        "messageFrom": message_from
    }
    
    return await http_client.post(
        endpoint="/gaotu-assistant-bot/chat/1/message/save",
        json_data=payload,
        error_msg="保存消息失败"
    )



