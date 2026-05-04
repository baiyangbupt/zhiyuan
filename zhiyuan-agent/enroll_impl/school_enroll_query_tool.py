import re
import traceback
from data.province_city_data import get_province_label_id_map
from tools.base import Tool
from loguru import logger
from util.internal_client import query_school_enroll, query_school_major_score_line
from data.school_option_data import school_to_id_associate, school_to_id_bachelor, bachelor_schools, associate_schools
from data.batch_subject_mapping import SUBJECT_CODE, SUBJECT_TITLE, area_year_subjects, area_year_batches
from util.school_major_functions import get_major_level3_infos_from_major_name, get_school_infos_from_name, resolve_batch_title, resolve_select_type

class SchoolEnrollQueryTool(Tool):
    """获取目标院校的预计录取情况"""

    def __init__(self):
        super().__init__(
            name="school_enroll_query_tool",
            description="根据学生想要咨询的院校，获取该院校的录取分数或者能否录取的预期情况以及预期能够录取的专业, 例如能不能进大连理工大学、沈阳工业大学机械工程(专业)2024年分数",
            parameters={
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "descriptioin": "学生想要咨询的学生省份"
                    },
                    "school": {
                        "type": "string",
                        "description": "学生想要咨询的院校名称, 确保输入的是与学生锁定的院校全称"
                    },
                    "major": {
                        "type": "string",
                        "description": "学生想要咨询的专业名称, 确保输入的是与学生锁定的专业全称"
                    },
                    "score": {
                        "type": "number",
                        "description": "学生咨询时带进去的分数"
                    },
                    "year": {
                        "type": "number",
                        "description": "待查询的年份"
                    },
                    "subject_type": {
                        "type": "string",
                        "description": "查询的分科,文科、理科、物理、历史"
                    },
                    "batch_name": {
                        "type": "string",
                        "description": "查询的批次,本科、专科、特招、一段、二段"
                    }
                },
                "required": ["school"]
            }
        )

    def execute(self, **kwargs) -> str:
        return ""
    
    def _get_major_info_from_name(self, batch_info, major_name):
        if not major_name:
            return []
        # 封装为三级专业信息
        major_data = dict(level1=[],level2=[],level3=[major_name])
        major_info = []
        for (_, batch_code) in batch_info:
            t_major = get_major_level3_infos_from_major_name(major_data, batch_code)
            major_info.extend(t_major)
        return major_info

    async def _get_school_enroll_data(self, thread_id_int, school_name, full_matched_schools):
        logger.debug(f"Quering :{','.join([ name for (name, id) in full_matched_schools ])}...")
        school_query_results = [
            (school, await query_school_enroll(chat_session_id=thread_id_int, school_id=school_id)) for (school, school_id) in full_matched_schools
        ]
        enroll_school_set = set()
        wrap_result = []
        for (school, result) in school_query_results:
            if result.get("code") == 0 and "data" in result and "sprintMajorList" in result["data"] and result['data']['sprintMajorList'] and result['data']['sprintMajorList'] != []:
                wrap_result.append(f"冲击报考{school}的{'、'.join([ major['majorName'] for major in result['data']['sprintMajorList']])}这几个专业")
                enroll_school_set.add(school)
            if result.get("code") == 0 and "data" in result and "safeMajorList" in result["data"] and result['data']['safeMajorList'] and result['data']['safeMajorList'] != []:
                wrap_result.append(f"稳妥报考{school}的{'、'.join([ major['majorName'] for major in result['data']['safeMajorList']])}这几个专业")
                enroll_school_set.add(school)
            if result.get("code") == 0 and "data" in result and "protectMajorList" in result["data"] and result['data']['protectMajorList'] and result['data']['protectMajorList'] != []:
                wrap_result.append(f"保底报考{school}的{'、'.join([ major['majorName'] for major in result['data']['protectMajorList']])}这几个专业")
                enroll_school_set.add(school)
        if len(enroll_school_set) == 0:
            logger.info(f"当前录取分数,按照往年录取分数线分析,不太能报{school_name}相关学校.")
            return f"通过当前用户当前分数选科信息,按照往年录取分数线分析,不太能报{school_name}相关学校."
        else:
            logger.info(f"与{school_name}相关的可以{', '.join(wrap_result)}")
            return f"查询到与{school_name}相关的报考院校信息,按照往年录取分数线分析,可以{', '.join(wrap_result)}."
        
    async def _get_school_major_score_line(self, area_info, full_matched_major, full_matched_school, batch_info, subject_info, year, query_score):
        # 如果没有获取到有效的专业, 则用空字符代替
        logger.debug(f"Quering scoreline :{','.join([ name for (name, id) in full_matched_school ])}...")
        full_matched_major = [('','')] if full_matched_major == [] else full_matched_major
        result = ''
        area_id, area_name = area_info[0], area_info[1]
        for (s_title, s_type) in subject_info:
            for (b_name, codes) in batch_info:
                for b_code in codes:
                    for (school, school_id) in full_matched_school:
                        for (major, major_id) in full_matched_major:
                            logger.info(f"查询院校分数线: {school}, 专业{major}, 批次{b_name}, 分科{s_title}, 省份{area_name}, 年份{year}")
                            score_data = await query_school_major_score_line(school_id=school_id,area_id=area_id,batch=b_code,subject_type=s_type,major_id=major_id,year=year)
                            if score_data.get("code") == 0 and 'data' in score_data and score_data['data'] != []:
                                # 对于同一个学校多个招生计划,按照位次找到不同招生组里面的最低分数,获取分数、位次、组名和选科要求
                                min_score = min(score_data['data'], key=lambda x: x['minPos'])
                                score, pos, name, select = min_score['minScore'], min_score['minPos'], min_score['name'], min_score['selectInfo']
                                # 无关过滤: 正则匹配可能匹配出不在同一个层次的学校如匹配出分院南通大学杏林学院, 上下50分作为参考范围
                                # # todo: 使用换算等效分
                                # if abs(query_score-int(score))>50:
                                #     logger.info(f"待查询分数:{query_score},与匹配的学校{name}分数:{score}区间不匹配,跳过")
                                #     continue
                                result += f',{school}{b_name}批次选科{s_title}{"的"+major+"专业" if major != "" else ""}{year}年在{area_name}{"最低位次是"+pos+"," if pos != None and pos != "0" else ""}{"录取分数是"+score+"," if score != None and score != "0" else ""}{"对应招生组"+name+"," if name != None else ""}{"要求选科是"+select+"." if select != None else ""}'
        return result
            
    async def aexecute(self, **kwargs) -> str:
        result=''
        # 获取ChatContext对象
        chatContext = kwargs.get("chat_context")
        if not chatContext:
            logger.error("Missing chat_context in QuerySchoolEnrollTool.aexecute")
            return "错误：缺少聊天上下文信息"
        # 处理省份, 没有传使用当前用户的省份
        if not kwargs.get('area'):
            logger.info("使用当前用户的省份查询录取情况")
            result += "使用当前用户的省份查询,"
            area_id = chatContext.user_score_info['areaId']
            area_name = chatContext.user_score_info['areaName']
            area_info = (area_id, area_name)
        else:
            province_name = kwargs.get('area')
            province_to_id = get_province_label_id_map()
            if province_name not in province_to_id:
                logger.error(f"Unknown province in SchoolRecommendWithScoreTool.aexecute: {province_name}")
                return "输入的省份有误"
            area_id = province_to_id[province_name]
            area_info = (area_id, province_name)
        # 处理分数, 没有传入的话使用当前用户的分数
        if not kwargs.get('score'):
            logger.info("使用当前用户的分数查询录取情况,")
            result += "使用当前用户的分数查询"
            score = int(float(chatContext.user_score_info["score"]))
        else:
            score = kwargs.get('score')

        # 处理年份, 没有传入使用2024年
        year = 2024 if not kwargs.get('year') else kwargs.get('year')
        s_year = str(year)

        # 处理分科信息, 没有传入遍历所有分科       
        if not kwargs.get('subject_type'):
            logger.info("没有指定分科,查询所有可能分科")
            subject_type = area_year_subjects[area_id][s_year]
            subject_title = [ SUBJECT_TITLE[i] for i in subject_type]
            subject_info = zip(subject_title, subject_type)
        else:
            subject_title = kwargs.get('subject_type')
            t_subject_info = resolve_select_type(area_id=area_id, select=subject_title)
            subject_info = [t_subject_info]
        
        # 处理批次, 没有传入的话遍历所有的批次编码
        if not kwargs.get('batch'):
            batch_info = [(batch_title, batches) for batch_title, batches in area_year_batches[area_id][s_year].items()]
            logger.info(f"未指定批次,查询所有批次:{batch_info}")
        else:
            batch_title = resolve_batch_title(kwargs.get('batch'))
            batch_info = [(batch_title, area_year_batches[area_id][s_year][batch_title])]
        
        
        school_name = kwargs['school']
        major_name = kwargs.get("major")
        
        thread_id = chatContext.thread_id
        thread_id_int = int(thread_id) if thread_id.isdigit() else 0
        
        try:
            school_infos = get_school_infos_from_name(school_name)
            if school_infos == []:
                logger.warning(f"No school matched for input school:{school_name}")
                return f'没有找到{school_name}相关的学校'
            enroll_data = await self._get_school_enroll_data(thread_id_int, full_matched_schools=school_infos, school_name=school_name)
            major_infos = self._get_major_info_from_name(batch_info, major_name)
            school_major_scoreline = await self._get_school_major_score_line(
                area_info=area_info, full_matched_major=major_infos, full_matched_school=school_infos, batch_info=batch_info, subject_info=subject_info, year=year, query_score=score)
            return f'{"分数线情况:"+school_major_scoreline+"." if school_major_scoreline != "" else ""}\n{enroll_data}'
            
        except Exception as e:
            logger.error(f"Error in SchoolQueryEnrollTool.aexecute: {traceback.format_exc()}")
            return f""
    
