

import re
from typing import Any, Dict, List, Optional, Set
from data.school_option_data import ALL_SCHOOLS, school_to_id_associate, school_to_id_bachelor,school_to_id, bachelor_schools, associate_schools
from data.major_data import major_bachelor_data, major_associate_data
from data.batch_subject_mapping import *
from loguru import logger

def get_school_infos_from_name(school_name):
    '''输入 学校名称, 输出正则匹配出的(name,id)列表, 如(“01”,“南大”)->[(“南京大学”,“10”),(“南通大学”,“297”),..]
    '''
    # 学校名称全名往往带着大学或者学院
    if '大学' in school_name or '学院' in school_name:
        if school_name not in school_to_id:
            logger.warning(f"No school matched for input school:{school_name}")
            return []
        return [(school_name, school_to_id[school_name])]
    
    # 字符串匹配学校, 全体院校名称中筛选出按序包含的, 如“北语”扩展“北.*语”可以在“北京语言大学”和“北京语言大学(珠海)”匹配出, 在“北京地质大学”匹配不出
    full_matched_schools = [ (school, school_to_id[school]) for school in ALL_SCHOOLS if re.search('.*'.join(school_name), school)]
    
    if full_matched_schools == []:
        logger.warning(f"No school matched for input school:{school_name}")
        return []
    return full_matched_schools

def get_major_level3_infos_from_major_name(major_name: Dict[str,Any], batch: str) -> List[str]:
    """
    从专业名称获取专业对应的level3 name, level3 ID列表
    
    Args:
        major_name: 带层级专业名称, 参考user_profile中major相关结构体,major_intent
        
    Returns:
        level3专业ID列表,[(level3name,level3id)]
    """
    # 存储level3专业ID的列表
    major_level3_ids = []
    major_info = major_name if major_name is not None else {}
    
    if batch == None or batch == "" or batch == "01":
        # 从学生资料中获取专业意向信息
        major_intent = major_info
        level1 = major_intent.get("level1")
        level2 = major_intent.get("level2")
        level3 = major_intent.get("level3")
        
        # 确保各级专业是列表形式
        if level1 and not isinstance(level1, list):
            level1 = [level1]
        if level2 and not isinstance(level2, list):
            level2 = [level2]
        if level3 and not isinstance(level3, list):
            level3 = [level3]
        
        # 使用本科专业数据（也可以根据需要选择专科专业数据）
        major_data = major_bachelor_data
        # 如果学生直接指定了level3专业
        if level3:
            for major_name in level3:
                if not major_name:
                    continue
                if major_name in major_data['major_level3_id_map']:
                    major_level3_ids.append((major_name, major_data['major_level3_id_map'][major_name]))
    if batch == None or batch == "" or batch == "02":
        # 从学生资料中获取专业意向信息
        major_data = major_associate_data
        major_intent = major_info
        level1 = major_intent.get("level1")
        level2 = major_intent.get("level2")
        level3 = major_intent.get("level3")
        if level1 and not isinstance(level1, list):
            level1 = [level1]
        if level2 and not isinstance(level2, list):
            level2 = [level2]
        if level3 and not isinstance(level3, list):
            level3 = [level3]

        if level3:
            for major_name in level3:
                if not major_name:
                    continue
                if major_name in major_data['major_level3_id_map']:
                    major_level3_ids.append((major_name, major_data['major_level3_id_map'][major_name]))
        
        if level2 and not level3:
            for major_name in level2:
                if not major_name:
                    continue
                if major_name in major_data['level2_to_level3']:
                    level3_majors = major_data['level2_to_level3'][major_name]
                    for level3_major in level3_majors:
                        if level3_major in major_data['major_level3_id_map']:
                            major_level3_ids.append((level3_major, major_data['major_level3_id_map'][level3_major]))
    
    # if test_report:
    #     for major_name in test_report:
    #         if not major_name:
    #             continue
    #         if major_name in major_data['level2_to_level3']:
    #             level3_majors = major_data['level2_to_level3'][major_name]
    #             for level3_major in level3_majors:
    #                 if level3_major in major_data['major_level3_id_map']:
    #                     major_level3_ids.add(major_data['major_level3_id_map'][level3_major])
    
    # 只有当level2和level3都没有数据时，才使用level1数据获取id
    # if not level2 and not level3 and level1:
    #     for major_name in level1:
    #         if not major_name:
    #             continue
    #         if major_name in major_data['level1_to_level2']:
    #             level2_majors = major_data['level1_to_level2'][major_name]
    #             for level2_major in level2_majors:
    #                 if level2_major in major_data['level2_to_level3']:
    #                     level3_majors = major_data['level2_to_level3'][level2_major]
    #                     for level3_major in level3_majors:
    #                         if level3_major in major_data['major_level3_id_map']:
    #                             major_level3_ids.add(major_data['major_level3_id_map'][level3_major])
    
    # 将集合转换为列表并返回
    return major_level3_ids

def resolve_select_type(select, area_id, year:Optional[str] = '2024'):
    # 解除常见的理科-物理,文科-历史,所有-综合的歧义,方便后续转换为系统编码
    select_type_options = area_year_subjects[area_id][year]
    if 'N' in select_type_options:
        return (SUBJECT_TITLE['N'],'N')
    if ('理' in select or '' in select) and 'WL' in select_type_options:
        return (SUBJECT_TITLE['WL'], 'WL')
    if ('理' in select or '' in select) and 'L' in select_type_options:
        return (SUBJECT_TITLE['L'], 'L')
    if ('文' in select or '史' in select) and 'W' in select_type_options:
        return (SUBJECT_TITLE['W'], 'W')
    if ('文' in select or '史' in select) and 'LS' in select_type_options:
        return (SUBJECT_TITLE['LS', 'LS'])
    logger.warning(f"Unknown select title: {select}, fall back to most popular WL")
    return (SUBJECT_TITLE['WL'], 'WL')

def resolve_batch_title(batch_title, area, year:Optional[str] = '2024'):
    # 解除常见的本科-一段,专科-二段,特招的歧义,方便后续转换为系统编码
    batch_title_option = list(area_year_batches[area][year].keys())
    if batch_title in batch_title_option:
        return batch_title
    if '段' in batch_title and batch_title not in batch_title_option:
        return '本科' if batch_title == '一段' else '专科'
    if '科' in batch_title and batch_title not in batch_title_option:
        return '一段' if batch_title == '本科' else '二段'
    logger.warning(f"Unknown batch title: {batch_title} for area{area}, fallback to {batch_title_option[0]}")
    return batch_title_option[0]

        
def resolve_select_info(select):
    # 将选科信息转化为数据库查询时候的编码, 物理-01、历史-02、政治-03、地理-04、化学-05、生物-06、技术-07
    # 按照数字顺序,排列对应选科科目编码, 如"物化生" -> 010506
    res = ''
    if "物" in select:
        res += '01'
    if '历' in select or '史' in select:
        res += '02'
    if '政' in select:
        res += '03'
    if '地' in select:
        res += '04'
    if '化' in select:
        res += '05'
    if '生' in select:
        res += '06'
    if '技' in select:
        res += '07'
        
    return res