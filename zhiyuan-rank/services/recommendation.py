# -*- coding: utf-8 -*-
import json
import pandas as pd
import numpy as np
import math
import os
import warnings
import re
from datetime import datetime
import logging
import traceback
import sys
from typing import List, Dict
from .data_loader import get_data_loader
warnings.filterwarnings("ignore")

"""
高考志愿推荐业务逻辑模块
"""
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)



def get_university_recommendations(student_score, preferences=None, location_preference=None, major_preference=None, limit=10):
    """获取大学推荐"""
    # 模拟一些大学数据
    universities = [
        {"name": "清华大学", "location": "北京", "type": "理工类", "min_score": 680},
        {"name": "北京大学", "location": "北京", "type": "综合类", "min_score": 675},
        {"name": "上海交通大学", "location": "上海", "type": "理工类", "min_score": 670},
        {"name": "复旦大学", "location": "上海", "type": "综合类", "min_score": 665},
        {"name": "浙江大学", "location": "杭州", "type": "综合类", "min_score": 660}
    ]
    
    # 简单筛选逻辑
    recommendations = []
    for uni in universities:
        # 分数匹配（允许低20分）
        if student_score >= uni["min_score"] - 20:
            # 类型匹配
            if not preferences or uni["type"] in preferences:
                # 地域匹配
                if not location_preference or uni["location"] == location_preference:
                    # 计算录取概率
                    if student_score >= uni["min_score"] + 10:
                        probability = "稳妥"
                    elif student_score >= uni["min_score"]:
                        probability = "保底"
                    else:
                        probability = "冲刺"
                    
                    recommendations.append({
                        "name": uni["name"],
                        "location": uni["location"],
                        "type": uni["type"],
                        "min_score": uni["min_score"],
                        "probability": probability
                    })
    
    return {
        "student_score": student_score,
        "recommendations": recommendations[:limit],
        "total_count": len(recommendations)
    }


def get_major_recommendations(university_id, student_score):
    """获取专业推荐"""
    # 模拟专业数据
    majors = [
        {"name": "计算机科学与技术", "min_score": 680, "hot_level": "热门"},
        {"name": "软件工程", "min_score": 675, "hot_level": "热门"},
        {"name": "电子信息工程", "min_score": 670, "hot_level": "较热门"}
    ]
    
    # 简单筛选
    suitable_majors = []
    for major in majors:
        if student_score >= major["min_score"] - 15:
            suitable_majors.append(major)
    
    return {
        "university_id": university_id,
        "student_score": student_score,
        "majors": suitable_majors
    }


# 熵权法
def entropy(input_data, target_name, method='linear'):
    input_data_p = input_data.copy()
    for col in input_data:
        sum_val = input_data[col].sum()
        input_data_p[col] = input_data[col].apply(lambda x: x / sum_val)
    input_data_e = (-1 / np.log(len(input_data))) * ((input_data_p * np.log(input_data_p)).sum())
    input_data_e = list(input_data_e.values)
    weight = [(1 - x) / (len(input_data_e) - sum(input_data_e)) for x in input_data_e]
    weight_dic = {input_data.columns[i]: round(float(weight[i]), 4) for i in range(len(weight))}
    if method == 'linear':
        score = pd.DataFrame((input_data * weight).sum(axis=1), columns=[target_name])
    elif method == 'geometric':
        score = pd.DataFrame((input_data ** weight).prod(axis=1), columns=[target_name])
    return score, weight_dic


def submajor_Recommand(studentinfo,topN):
    """二级专业推荐函数"""
    try:
        batch = studentinfo['batch']['level']  # 获取本科或专科批次
        logger.info('[submajor_Recommand] 函数开始执行, topN=%s, batch=%s', topN, batch)
        logger.info('[submajor_Recommand] 开始获取专业数据')
        # 使用预加载的专业数据
        if batch == '02':
            data = get_data_loader().get_major_02_data()
        else:
            data = get_data_loader().get_major_data()
        logger.info('[submajor_Recommand] 专业数据获取完成, 数据量: %d', len(data))
        data['sub1'] = data['sub1'].fillna('').astype(str)
        data = data[data['sub1'] == '']
        logger.info('[submajor_Recommand] 筛选sub1为空后, 数据量: %d', len(data))
        # 修改id代码为字符串形式
        data['major_code'] = data['major_code'].astype(str).replace('nan', '')
        data['major_id'] = data['major_id'].astype(str).replace('nan', '')
        data['id1'] = data['id1'].astype(str).replace('nan', '')
        data['id2'] = data['id2'].astype(str).replace('nan', '')
        # 筛选优势科目对应专业类
        logger.info('[submajor_Recommand] 开始筛选优势科目对应专业类')
        # 从strengthSubjectList数组中提取subjectName字段
        strengthSubjectList = [item['subjectName'] for item in studentinfo['strengthSubjectList']]
        subject = data['subject_list'].str.split(';')
        condition = subject.apply(lambda x: len(list(set(x) & set(strengthSubjectList))) > 0)  # 创建条件
        data_filtered = data[condition]  # ~condition 表示条件"取反"
        data_filtered = data_filtered.reset_index(drop=True)  # 重置索引
        logger.info('[submajor_Recommand] 筛选优势科目后, 数据量: %d', len(data_filtered))

        logger.info('[submajor_Recommand] 开始处理性别和选科类型')
        # 根据性别转化gender_index
        sex = studentinfo['sex']['code']
        if sex != 'male':
            data_filtered['gender_index'] = data_filtered['gender_index'].apply(lambda x: 100 - x)
        # 判断选科类型
        subjectList = studentinfo['subjectList']
        sublist = []  # 选科列表
        for sub in subjectList:
            sublist.append(sub['name'])
        type = studentinfo['subjectType']['desc']  # 物理组\历史组\综合
        if type == '物理' or ('物理' in sublist and '化学' in sublist):  # 物理组、物化组
            data_filtered['hot_index'] = data_filtered['li_hot_index'].apply(lambda x: x * 100)
        else:  # 其他都是历史组
            data_filtered['hot_index'] = data_filtered['wen_hot_index'].apply(lambda x: x * 100)
        logger.info('[submajor_Recommand] 学生类型: %s %s %s', sex, type, sublist)
        # 部分指标归一化处理
        logger.info('[submajor_Recommand] 开始归一化处理')
        for col in data_filtered.columns:
            if col == 'satisfy_index' or col == 'salary_avg':
                min_val_col = data_filtered[col].min()
                max_val_col = data_filtered[col].max()
                data_filtered[col] = data_filtered[col].apply(
                    lambda x: 10 + (x - min_val_col) / (max_val_col - min_val_col) * 90)

        logger.info('[submajor_Recommand] 开始计算熵权法得分')
        score, result = entropy(data_filtered[['gender_index', 'satisfy_index', 'salary_avg', 'hot_index']], 'score')
        logger.info('[submajor_Recommand] 二级专业推荐指标权重: %s', result)
        data_final = pd.concat([data_filtered, score], axis=1)
        logger.info('[submajor_Recommand] 数据合并完成, 数据量: %d', len(data_final))
        if batch == '02':
            data_final['hot_index'] = 0
        reconmandlist = []
        data_final = data_final.sort_values('score', ascending=False)
        #取特定数量的推荐专业大类
        if len(data_final) < topN:
            topN = len(data_final)
            logger.info('[submajor_Recommand] topN调整为实际数据量: %d', topN)
        data_final_topN = data_final.head(topN)
        logger.info('[submajor_Recommand] 开始构建推荐列表, topN=%d', topN)
        for index, row in data_final_topN.iterrows():
            try:
                majorinfo = {}
                majorinfo['major_id'] = str(row['major_id'])
                majorinfo['major'] = str(row['major'])
                majorinfo['score'] = float(row['score'])
                majorinfo['gender_index'] = float(row['gender_index'])
                majorinfo['satisfy_index'] = float(row['satisfy_index'])
                majorinfo['salary_avg'] = float(row['salary_avg'])
                majorinfo['hot_index'] = float(row['hot_index'])
                reconmandlist.append(majorinfo)
            except Exception as e:
                logger.error('[submajor_Recommand] 处理专业信息时出错, index=%s, row=%s, error=%s', index, row, str(e))
                logger.exception('[submajor_Recommand] 详细错误堆栈:')
                raise
        result['reconmandlist'] = reconmandlist
        logger.info('[submajor_Recommand] 推荐列表构建完成, 推荐数量: %d', len(reconmandlist))
        logger.info('[submajor_Recommand] 函数执行完成, 返回结果')
        return result
    except Exception as e:
        logger.error('[submajor_Recommand] 函数执行出错: %s', str(e))
        logger.exception('[submajor_Recommand] 详细错误堆栈:')
        raise


def major_Recommand(studentinfo):
    """专业推荐函数"""
    try:
        batch = studentinfo['batch']['level']  # 获取本科或专科批次
        logger.info('[major_Recommand] 函数开始执行')
        logger.info('[major_Recommand] 开始获取专业数据')
        # 使用预加载的专业数据
        if batch == '02':
            data = get_data_loader().get_major_02_data()
        else:
            data = get_data_loader().get_major_data()
        logger.info('[major_Recommand] 专业数据获取完成, 数据量: %d', len(data))
        # 修改id代码为字符串形式
        logger.info('[major_Recommand] 开始转换数据类型')
        data['major_code'] = data['major_code'].astype(str).replace('nan', '')
        data['major_id'] = data['major_id'].astype(str).replace('nan', '')
        data['id1'] = data['id1'].astype(str).replace('nan', '')
        data['id2'] = data['id2'].astype(str).replace('nan', '')
        logger.info('[major_Recommand] 开始处理性别和选科类型')
        # 根据性别转化gender_index
        sex = studentinfo['sex']['code']
        if sex != 'male':
            data['gender_index'] = data['gender_index'].apply(lambda x: 100 - x)
        subjectList = studentinfo['subjectList']
        sublist = []  # 选科列表
        for sub in subjectList:
            sublist.append(sub['name'])
        type = studentinfo['subjectType']['code']  # 物理组\历史组\综合
        if type == 'WL' or ('物理' in sublist and '化学' in sublist):  # 物理组、物化组
            data['hot_index'] = data['li_hot_index'].apply(lambda x: x * 100)
        else:  # 其他都是历史组
            data['hot_index'] = data['wen_hot_index'].apply(lambda x: x * 100)
        logger.info('[major_Recommand] 学生信息: sex=%s, type=%s, sublist=%s', sex, type, sublist)
        # 部分指标归一化处理
        logger.info('[major_Recommand] 开始归一化处理')
        for col in data.columns:
            if col == 'satisfy_index' or col == 'salary_avg':
                min_val_col = data[col].min()
                max_val_col = data[col].max()
                data[col] = data[col].apply(lambda x: 10 + (x - min_val_col) / (max_val_col - min_val_col) * 90)
        logger.info('[major_Recommand] 开始计算熵权法得分')
        score, result = entropy(data[['gender_index', 'satisfy_index', 'salary_avg', 'hot_index']], 'major_score')
        logger.info('[major_Recommand] 专业推荐指标权重: %s', result)
        data_final = pd.concat([data, score], axis=1)
        if batch == '02':
            data_final['hot_index'] = 0
        for col in data_final.columns:
            if col in ['wen_hot_index', 'li_hot_index']:
                del data_final[col]
        data_final = data_final.sort_values('major_score', ascending=False)
        logger.info('[major_Recommand] 函数执行完成, 返回数据量: %d', len(data_final))
        return data_final, result
    except Exception as e:
        logger.error('[major_Recommand] 函数执行出错: %s', str(e))
        logger.exception('[major_Recommand] 详细错误堆栈:')
        raise


def college_Recommand(batch='01'):
    """院校推荐函数"""
    try:
        logger.info('[college_Recommand] 函数开始执行')
        logger.info('[college_Recommand] 开始获取院校数据')
        # 使用预加载的院校数据
        if batch == '02':
            data = get_data_loader().get_school_02_data()
        else:
            data = get_data_loader().get_school_data()
        logger.info('[college_Recommand] 院校数据获取完成, 数据量: %d', len(data))
        # 修改id代码为字符串形式
        logger.info('[college_Recommand] 开始转换数据类型')
        data['school_id'] = data['school_id'].astype(str).replace('nan', '')
        data['province_code'] = data['province_code'].astype(str).replace('nan', '')
        data['city_code'] = data['city_code'].astype(str).replace('nan', '')
        # 将gaotu_rank转化为得分
        logger.info('[college_Recommand] 开始处理gaotu_rank')
        max = int(data['gaotu_rank'].max())
        min = int(data['gaotu_rank'].min())
        data['gaotu_rank'] = data['gaotu_rank'].apply(lambda x: max - int(x) + 1)
        data['gaotu_rank'] = data['gaotu_rank'].apply(lambda x: 10 + (int(x) - min) / (max - min) * 90)  # 对于数值列进行归一化
        # 部分指标归一化处理
        logger.info('[college_Recommand] 开始归一化处理')
        col_flag = []
        for col in data.columns:
            if col == 'province_gdp' or col == 'upgrade_ratio' or col == 'postgraduate_recommend_ratio':
                if col in ['upgrade_ratio', 'postgraduate_recommend_ratio']:
                    data[col] = data[col].apply(lambda x: float(x.strip('%')))
                min_val_col = data[col].min()
                max_val_col = data[col].max()
                if min_val_col == max_val_col:
                    data[col] = 100
                    col_flag.append(col)
                else:
                    data[col] = data[col].apply(lambda x: 10 + (x - min_val_col) / (max_val_col - min_val_col) * 90)
        logger.info('[college_Recommand] 开始计算熵权法得分')
        score, result = entropy(data[['province_gdp', 'city_level', 'upgrade_ratio', 'postgraduate_recommend_ratio','gaotu_rank', 'level_score']], 'college_score')
        logger.info('[college_Recommand] 院校推荐指标权重: %s', result)
        data_final = pd.concat([data, score], axis=1)
        if batch == '02':
            data_final['upgrade_ratio']=0
            data_final['postgraduate_recommend_ratio'] = 0
        data_final = data_final.sort_values('college_score', ascending=False)
        logger.info('[college_Recommand] 函数执行完成, 返回数据量: %d', len(data_final))
        return data_final, result
    except Exception as e:
        logger.error('[college_Recommand] 函数执行出错: %s', str(e))
        logger.exception('[college_Recommand] 详细错误堆栈:')
        raise

def emotion_process(taglist, emotionlist, flag):
    """情感处理函数"""
    try:
        logger.debug('[emotion_process] 函数开始执行, flag=%s, taglist长度=%s, emotionlist长度=%s', 
                    flag, len(taglist) if isinstance(taglist, list) else 'N/A', 
                    len(emotionlist) if isinstance(emotionlist, list) else 'N/A')
        # 确保 taglist 和 emotionlist 是列表类型
        if not isinstance(taglist, list):
            logger.warning('[emotion_process] taglist不是列表类型, 类型: %s, 值: %s', type(taglist), taglist)
            taglist = []
        if not isinstance(emotionlist, list):
            logger.warning('[emotion_process] emotionlist不是列表类型, 类型: %s, 值: %s', type(emotionlist), emotionlist)
            emotionlist = []
        
        if not taglist or not emotionlist:
            logger.debug('[emotion_process] taglist或emotionlist为空, 返回空字典')
            return {}
        # 将意愿情感转化为数值
        new_emotionlist=[]
        for each in emotionlist:
            if "Strong" == each:
                if "positive" == flag:
                    new_emotionlist.append(1)
                else:
                    new_emotionlist.append(0.01)
            elif "Neutral" == each:
                if "positive" == flag:
                    new_emotionlist.append(0.5)
                else:
                    new_emotionlist.append(0.1)
            elif "Weak" == each:
                if "positive" == flag:
                    new_emotionlist.append(0.1)
                else:
                    new_emotionlist.append(0.5)
            else:
                if "positive" == flag:
                    new_emotionlist.append(1)
                else:
                    new_emotionlist.append(0.01)
        # 确保两个列表长度一致
        if len(taglist) != len(new_emotionlist):
            logger.warning('[emotion_process] taglist和emotionlist长度不一致 (taglist: %d, emotionlist: %d)，截取较短的长度', 
                          len(taglist), len(new_emotionlist))
            min_len = min(len(taglist), len(new_emotionlist))
            taglist = taglist[:min_len]
            new_emotionlist = new_emotionlist[:min_len]
        
        # 使用 zip 函数将两个列表合并成字典
        tag_emotion_dict = dict(zip(taglist, new_emotionlist))
        logger.debug('[emotion_process] 函数执行完成, 返回字典长度: %d', len(tag_emotion_dict))
        return tag_emotion_dict
    except Exception as e:
        logger.error('[emotion_process] 函数执行出错: %s', str(e))
        logger.exception('[emotion_process] 详细错误堆栈:')
        raise

def volunteer_Recommand(studentinfo, volunteerinfo, profileinfo):
    """志愿推荐函数"""
    try:
        logger.info('[volunteer_Recommand] 函数开始执行')
        # 获取数据加载器实例，用于快速查找
        loader = get_data_loader()
        logger.info('[volunteer_Recommand] 数据加载器获取完成')

        # 验证volunteerinfo类型，确保它是列表
        logger.info('[volunteer_Recommand] 开始验证volunteerinfo类型, 当前类型: %s', type(volunteerinfo))
        if not isinstance(volunteerinfo, list):
            if isinstance(volunteerinfo, dict):
                # 如果volunteerinfo是字典，尝试获取列表字段
                if 'list' in volunteerinfo:
                    volunteerinfo = volunteerinfo['list']
                elif 'volunteerList' in volunteerinfo:
                    volunteerinfo = volunteerinfo['volunteerList']
                elif 'data' in volunteerinfo:
                    volunteerinfo = volunteerinfo['data']
                else:
                    # 如果字典中没有列表字段，尝试获取所有值中的第一个列表
                    for value in volunteerinfo.values():
                        if isinstance(value, list):
                            volunteerinfo = value
                            break
                    else:
                        logger.error('[volunteer_Recommand] volunteerinfo必须是列表，但收到了%s类型: %s', type(volunteerinfo), volunteerinfo)
                        raise ValueError(f"volunteerinfo必须是列表，但收到了{type(volunteerinfo)}类型: {volunteerinfo}")
            else:
                logger.error('[volunteer_Recommand] volunteerinfo必须是列表，但收到了%s类型: %s', type(volunteerinfo), volunteerinfo)
                raise ValueError(f"volunteerinfo必须是列表，但收到了{type(volunteerinfo)}类型: {volunteerinfo}")
        logger.info('[volunteer_Recommand] volunteerinfo验证完成, 志愿数量: %d', len(volunteerinfo))

        batch = studentinfo['batch']['level']# studentinfo['batch']['level']:'01'本科
        # 1.计算专业得分
        logger.info('[volunteer_Recommand] 步骤1: 开始计算专业得分, batch=%s', batch)
        major_score, major_weight = major_Recommand(studentinfo)
        logger.info('[volunteer_Recommand] 步骤1: 专业得分计算完成, 专业数量: %d', len(major_score))
        major_dict = major_score.set_index('major_id').to_dict('index')
        major_score_avg = float(major_score['major_score'].mean())
        logger.info('[volunteer_Recommand] 步骤1: 专业平均得分: %.2f', major_score_avg)

        # 2.计算院校得分
        logger.info('[volunteer_Recommand] 步骤2: 开始计算院校得分, batch=%s', batch)
        college_score, college_weight = college_Recommand(batch)
        logger.info('[volunteer_Recommand] 步骤2: 院校得分计算完成, 院校数量: %d', len(college_score))
        college_dict = college_score.set_index('school_id').to_dict('index')
        college_score_avg = float(college_score['college_score'].mean())
        logger.info('[volunteer_Recommand] 步骤2: 院校平均得分: %.2f', college_score_avg)

        # 3.获取专业Tag
        logger.info('[volunteer_Recommand] 步骤3: 开始获取专业Tag')
        if batch != '02':
            tag_major = loader.get_tag_major()
        else:
            tag_major = loader.get_tag_major_02()
        # 验证tag_major是字典类型
        if not isinstance(tag_major, dict):
            logger.error('[volunteer_Recommand] tag_major不是字典类型，实际类型: %s', type(tag_major))
            raise TypeError(f"tag_major必须是字典类型，但收到 {type(tag_major)} 类型")
        logger.info('[volunteer_Recommand] 步骤3: 专业Tag获取完成, Tag数量: %d', len(tag_major))

        # 4.获取用户意愿
        logger.info('[volunteer_Recommand] 步骤4: 开始获取用户意愿')
        '''从profileinfo获取院校意向'''
        negative_schoollist = profileinfo.get('negative_college_info', {}).get('values_code', [])
        negative_school_emotion = profileinfo.get('negative_college_info', {}).get('values_emotion', [])
        logger.info('[volunteer_Recommand] 步骤4: 负向院校数量: %d', len(negative_schoollist))
        negative_school_dict = emotion_process(negative_schoollist, negative_school_emotion,"negative")
        positive_schoollist = profileinfo.get('college_info', {}).get('values_code', [])
        positive_school_emotion = profileinfo.get('college_info', {}).get('values_emotion', [])
        logger.info('[volunteer_Recommand] 步骤4: 正向院校数量: %d', len(positive_schoollist))
        positive_school_dict = emotion_process(positive_schoollist, positive_school_emotion,"positive")

        '''从profileinfo获取专业意向'''
        # 获取正向专业
        positive_major2 = profileinfo.get('major_intent', {}).get('level2_code', [])
        positive_major2_emotion = profileinfo.get('major_intent', {}).get('level2_emotion', [])
        positive_major3 = profileinfo.get('major_intent', {}).get('level3_code', [])
        positive_major3_emotion = profileinfo.get('major_intent', {}).get('level3_emotion', [])
        positive_major2_emotion.extend(positive_major3_emotion)
        positive_major2.extend(positive_major3)
        positive_majorlist = positive_major2
        positive_major_dict = emotion_process(positive_majorlist, positive_major2_emotion,"positive")

        # 获取负向专业
        negative_major2 = profileinfo.get('negative_major_intent', {}).get('level2_code', [])
        negative_major2_emotion = profileinfo.get('negative_major_intent', {}).get('level2_emotion', [])
        negative_major3 = profileinfo.get('negative_major_intent', {}).get('level3_code', [])
        negative_major3_emotion = profileinfo.get('negative_major_intent', {}).get('level3_emotion', [])
        negative_major2.extend(negative_major3)
        negative_major2_emotion.extend(negative_major3_emotion)
        negative_majorlist = negative_major2
        negative_major_dict = emotion_process(negative_majorlist, negative_major2_emotion,"negative")

        '''从profileinfo获取地域意向'''
        positive_citylist = profileinfo.get('city_info', {}).get('city_code', [])
        positive_city_emotion = profileinfo.get('city_info', {}).get('city_emotion', [])
        positive_city_dict = emotion_process(positive_citylist, positive_city_emotion,"positive")
        negative_citylist = profileinfo.get('negative_city_info', {}).get('city_code', [])
        negative_city_emotion = profileinfo.get('negative_city_info', {}).get('city_emotion', [])
        negative_city_dict = emotion_process(negative_citylist, negative_city_emotion,"negative")
        positive_provincelist = profileinfo.get('city_info', {}).get('province_code', [])
        positive_province_emotion = profileinfo.get('city_info', {}).get('province_emotion', [])
        positive_province_dict = emotion_process(positive_provincelist, positive_province_emotion,"positive")
        negative_provincelist = profileinfo.get('negative_city_info', {}).get('province_code', [])
        negative_province_emotion = profileinfo.get('negative_city_info', {}).get('province_emotion', [])
        negative_province_dict = emotion_process(negative_provincelist, negative_province_emotion,"negative")

        '''从profileinfo获取tag意向'''
        positive_taglist = profileinfo.get('tag_info', {}).get('values', [])
        positive_tag_emotion = profileinfo.get('tag_info', {}).get('values_emotion', [])
        positive_tag_dict = emotion_process(positive_taglist, positive_tag_emotion,"positive")
        negative_taglist = profileinfo.get('negative_tag_info', {}).get('values', [])
        negative_tag_emotion = profileinfo.get('negative_tag_info', {}).get('values_emotion', [])
        negative_tag_dict = emotion_process(negative_taglist, negative_tag_emotion,"negative")

        # 5.计算志愿得分
        logger.info('[volunteer_Recommand] 步骤5: 开始计算志愿得分, 志愿数量: %d', len(volunteerinfo))
        filterType = studentinfo['filterType']
        logger.info('[volunteer_Recommand] 步骤5: filterType=%s', filterType)
        # 遍历志愿表，计算志愿得分
        for idx, plan in enumerate(volunteerinfo):
            try:
                logger.debug('[volunteer_Recommand] 步骤5: 开始处理志愿项 %d/%d', idx+1, len(volunteerinfo))
                # 验证plan是字典类型
                if not isinstance(plan, dict):
                    logger.error('[volunteer_Recommand] 志愿项 %d 不是字典类型，实际类型: %s, 内容: %s', idx, type(plan), plan)
                    raise TypeError(f"志愿项必须是字典类型，但收到 {type(plan)} 类型")
                
                # print(plan)
                '''从college_score获取对应院校得分'''
                #logger.info("5.1 计算志愿中的院校得分")
                province_gdp = 0
                city_level = 0
                upgrade_ratio = 0
                postgraduate_recommend_ratio = 0
                gaotu_rank = 0
                level_score = 0
                college_score_old = college_score_avg
                college_score_new = college_score_old
                college_remark = ''
                college_factors = []
                school_flag = []
                
                # 验证college_dict是字典类型
                if not isinstance(college_dict, dict):
                    logger.error('[volunteer_Recommand] college_dict不是字典类型，实际类型: %s', type(college_dict))
                    raise TypeError(f"college_dict必须是字典类型，但收到 {type(college_dict)} 类型")
                
                #if plan['schoolId'] in college_score['school_id'].values:
                school_id = plan.get('schoolId')
                logger.debug('[volunteer_Recommand] 步骤5: 志愿项 %d, schoolId=%s', idx, school_id)
                if school_id and school_id in college_dict:
                    indexdict = college_dict[school_id]
                    # 验证indexdict是字典类型
                    if not isinstance(indexdict, dict):
                        logger.error('[volunteer_Recommand] college_dict[%s]不是字典类型，实际类型: %s, 值: %s', 
                                    school_id, type(indexdict), indexdict)
                        raise TypeError(f"college_dict中的值必须是字典类型，但收到 {type(indexdict)} 类型")
                    province_gdp = float(indexdict['province_gdp'])
                    city_level = float(indexdict['city_level'])
                    upgrade_ratio = float(indexdict['upgrade_ratio'])
                    postgraduate_recommend_ratio = float(indexdict['postgraduate_recommend_ratio'])
                    gaotu_rank = float(indexdict['gaotu_rank'])
                    level_score = float(indexdict['level_score'])
                    college_score_old = float(indexdict['college_score'])
                    category = str(indexdict.get('category', '')) if indexdict.get('category') is not None else ''
                    nature = str(indexdict.get('nature', '')) if indexdict.get('nature') is not None else ''
                    postgraduate = str(indexdict.get('postgraduate', '')) if indexdict.get('postgraduate') is not None else ''
                    levellist = str(indexdict.get('tag', '')).split('、') if indexdict.get('tag') is not None else []

                    college_score_new = college_score_old
                    school_id = plan.get('schoolId')
                    if school_id and school_id in negative_schoollist:
                        school_value = negative_school_dict.get(school_id, 0.01)
                        _cf_before = college_score_new
                        college_score_new = college_score_new * 0.1 * school_value
                        college_remark = '院校负向减分;'
                        _record_factor(college_factors, "院校负向减分", _cf_before, college_score_new)
                        school_flag.append(-1)
                    elif school_id and school_id in positive_schoollist:
                        school_value = positive_school_dict.get(school_id, 1)
                        _cf_before = college_score_new
                        college_score_new += (100 - college_score_new) * (college_score_new / 100) * 1 * school_value
                        college_remark = '院校正向加分;'
                        _record_factor(college_factors, "院校正向加分", _cf_before, college_score_new)
                        school_flag.append(1)
                    else:
                        city_id = plan.get('cityId')
                        if city_id and city_id in negative_citylist:
                            city_value = negative_city_dict.get(city_id, 0.01)
                            _cf_before = college_score_new
                            college_score_new = college_score_new * 0.3 * city_value
                            college_remark = '城市负向减分;'
                            _record_factor(college_factors, "城市负向减分", _cf_before, college_score_new)
                            school_flag.append(-2)
                        elif city_id and city_id in positive_citylist:
                            city_value = positive_city_dict.get(city_id, 1)
                            _cf_before = college_score_new
                            college_score_new += (100 - college_score_new) * (college_score_new / 100) * 0.8 * city_value
                            college_remark = '城市正向加分;'
                            _record_factor(college_factors, "城市正向加分", _cf_before, college_score_new)
                            school_flag.append(2)
                        else:
                            province_id = plan.get('provinceId')
                            if province_id and province_id in negative_provincelist:
                                province_value = negative_province_dict.get(province_id, 0.01)
                                _cf_before = college_score_new
                                college_score_new = college_score_new * 0.5 * province_value
                                college_remark = '省份负向减分;'
                                _record_factor(college_factors, "省份负向减分", _cf_before, college_score_new)
                                school_flag.append(-2)
                            elif province_id and province_id in positive_provincelist:
                                province_value = positive_province_dict.get(province_id, 1)
                                _cf_before = college_score_new
                                college_score_new += (100 - college_score_new) * (college_score_new / 100) * 0.5 * province_value
                                college_remark = '省份正向加分;'
                                _record_factor(college_factors, "省份正向加分", _cf_before, college_score_new)
                                school_flag.append(2)

                    '''额外分数调整：院校tag信息'''
                    if len(levellist)>0 and (len(negative_taglist)>0 or len(positive_taglist)>0):
                        if len(list(set(levellist) & set(['985','强基'])))>0:
                            for level in ['985','强基']:
                                tag_key = level + '院校'
                                if tag_key in negative_taglist and 1 not in school_flag:
                                    tag_value = negative_tag_dict.get(tag_key, 0.01)
                                    _cf_before = college_score_new
                                    college_score_new = college_score_new * 0.95 * tag_value
                                    college_remark += '院校层次负向减分;'
                                    _record_factor(college_factors, "院校层次负向减分", _cf_before, college_score_new)
                                    school_flag.append(-3)
                                elif tag_key in positive_taglist and -1 not in school_flag:
                                    tag_value = positive_tag_dict.get(tag_key, 1)
                                    _cf_before = college_score_new
                                    college_score_new += 8 * tag_value
                                    college_remark += '院校层次正向加分;'
                                    _record_factor(college_factors, "院校层次正向加分", _cf_before, college_score_new)
                                    school_flag.append(3)
                        elif len(list(set(levellist) & set(['211','双一流','国重点','国家级示范','国家级骨干','双高计划'])))>0:
                            for level in ['211','双一流','国重点','国家级示范','国家级骨干','双高计划']:
                                tag_key = level + '院校'
                                if tag_key in negative_taglist and 1 not in school_flag:
                                    tag_value = negative_tag_dict.get(tag_key, 0.01)
                                    _cf_before = college_score_new
                                    college_score_new = college_score_new * 0.9 * tag_value
                                    college_remark += '院校层次负向减分;'
                                    _record_factor(college_factors, "院校层次负向减分", _cf_before, college_score_new)
                                    school_flag.append(-3)
                                elif tag_key in positive_taglist and -1 not in school_flag:
                                    tag_value = positive_tag_dict.get(tag_key, 1)
                                    _cf_before = college_score_new
                                    college_score_new += 7 * tag_value
                                    college_remark += '院校层次正向加分;'
                                    _record_factor(college_factors, "院校层次正向加分", _cf_before, college_score_new)
                                    school_flag.append(3)
                        elif len(list(set(levellist) & set(['保研', '省重点'])))>0:
                            for level in ['保研', '省重点']:
                                tag_key = level + '院校'
                                if tag_key in negative_taglist and 1 not in school_flag:
                                    tag_value = negative_tag_dict.get(tag_key, 0.01)
                                    _cf_before = college_score_new
                                    college_score_new = college_score_new * 0.85 * tag_value
                                    college_remark += '院校层次负向减分;'
                                    _record_factor(college_factors, "院校层次负向减分", _cf_before, college_score_new)
                                    school_flag.append(-3)
                                elif tag_key in positive_taglist and -1 not in school_flag:
                                    tag_value = positive_tag_dict.get(tag_key, 1)
                                    _cf_before = college_score_new
                                    college_score_new += 6 * tag_value
                                    college_remark += '院校层次正向加分;'
                                    _record_factor(college_factors, "院校层次正向加分", _cf_before, college_score_new)
                                    school_flag.append(3)
                        else:
                            for level in levellist:
                                tag_key = level + '院校'
                                if tag_key in negative_taglist and 1 not in school_flag:
                                    tag_value = negative_tag_dict.get(tag_key, 0.01)
                                    _cf_before = college_score_new
                                    college_score_new = college_score_new * 0.8 * tag_value
                                    college_remark += '院校层次负向减分;'
                                    _record_factor(college_factors, "院校层次负向减分", _cf_before, college_score_new)
                                    school_flag.append(-3)
                                elif tag_key in positive_taglist and -1 not in school_flag:
                                    tag_value = positive_tag_dict.get(tag_key, 1)
                                    _cf_before = college_score_new
                                    college_score_new += 2 * tag_value
                                    college_remark += '院校层次正向加分;'
                                    _record_factor(college_factors, "院校层次正向加分", _cf_before, college_score_new)
                                    school_flag.append(3)

                    if postgraduate:
                        tag_key = postgraduate + '院校'
                        if tag_key in negative_taglist and 1 not in school_flag:
                            tag_value = negative_tag_dict.get(tag_key, 0.01)
                            _cf_before = college_score_new
                            college_score_new = college_score_new * 0.6 * tag_value
                            college_remark += '院校硕博点负向减分;'
                            _record_factor(college_factors, "院校硕博点负向减分", _cf_before, college_score_new)
                            school_flag.append(-3)
                        elif tag_key in positive_taglist and -1 not in school_flag:
                            tag_value = positive_tag_dict.get(tag_key, 1)
                            _cf_before = college_score_new
                            college_score_new += 6 * tag_value
                            college_remark += '院校硕博点正向加分;'
                            _record_factor(college_factors, "院校硕博点正向加分", _cf_before, college_score_new)
                            school_flag.append(3)

                    if category:
                        tag_key = category + '院校'
                        if tag_key in negative_taglist and 1 not in school_flag:
                            tag_value = negative_tag_dict.get(tag_key, 0.01)
                            _cf_before = college_score_new
                            college_score_new = college_score_new * 0.5 * tag_value
                            college_remark += '院校类型负向减分;'
                            _record_factor(college_factors, "院校类型负向减分", _cf_before, college_score_new)
                            school_flag.append(-3)
                        elif tag_key in positive_taglist and -1 not in school_flag:
                            tag_value = positive_tag_dict.get(tag_key, 1)
                            _cf_before = college_score_new
                            college_score_new += 5 * tag_value
                            college_remark += '院校类型正向加分;'
                            _record_factor(college_factors, "院校类型正向加分", _cf_before, college_score_new)
                            school_flag.append(3)

                    if nature:
                        tag_key = nature + '院校'
                        if tag_key in negative_taglist and 1 not in school_flag:
                            tag_value = negative_tag_dict.get(tag_key, 0.01)
                            _cf_before = college_score_new
                            college_score_new = college_score_new * 0.3 * tag_value
                            college_remark += '院校性质负向减分;'
                            _record_factor(college_factors, "院校性质负向减分", _cf_before, college_score_new)
                            school_flag.append(-3)
                        elif tag_key in positive_taglist and -1 not in school_flag:
                            tag_value = positive_tag_dict.get(tag_key, 1)
                            _cf_before = college_score_new
                            college_score_new += 1 * tag_value
                            college_remark += '院校性质正向加分;'
                            _record_factor(college_factors, "院校性质正向加分", _cf_before, college_score_new)
                            school_flag.append(3)

                    #无任何意向的院校得分处理
                    if len(school_flag) == 0:
                        _cf_before = college_score_new
                        college_score_new = college_score_new * 0.6
                        college_remark = '院校无意向减分;'
                        _record_factor(college_factors, "院校无意向减分", _cf_before, college_score_new)
                else:
                    #未知的院校得分处理
                    _cf_before = college_score_new
                    college_score_new = college_score_new * 0.6
                    college_remark = '未知院校减分;'
                    _record_factor(college_factors, "未知院校减分", _cf_before, college_score_new)

                # 在volunteerinfo的每个plan中新增院校指标得分
                plan['province_gdp'] = province_gdp
                plan['city_level'] = city_level
                plan['upgrade_ratio'] = upgrade_ratio
                plan['postgraduate_recommend_ratio'] = postgraduate_recommend_ratio
                plan['gaotu_rank'] = gaotu_rank
                plan['level_score'] = level_score
                plan['college_score_old'] = college_score_old
                plan['college_score_new'] = college_score_new
                plan['college_factors'] = college_factors
                plan['college_remark'] = college_remark.strip(';')

                majorList = plan.get('majorList', [])
                # 验证majorList是列表类型
                if not isinstance(majorList, list):
                    logger.error('[volunteer_Recommand] 志愿项 %d, plan中的majorList不是列表类型，实际类型: %s, plan: %s', 
                                idx, type(majorList), plan)
                    raise TypeError(f"majorList必须是列表类型，但收到 {type(majorList)} 类型")
                total_major_num = len(majorList)
                logger.debug('[volunteer_Recommand] 步骤5: 志愿项 %d, 专业数量: %d', idx, total_major_num)
                positive_major_num = 0
                negative_major_num = 0
                major_score_final = 0
                #logger.info("5.2 计算志愿中的专业（组）得分")
                for majordict_idx, majordict in enumerate(majorList):
                    try:
                        # 验证majordict是字典类型
                        if not isinstance(majordict, dict):
                            logger.warning('[volunteer_Recommand] 志愿项 %d, 专业 %d, majorList中的元素不是字典类型，跳过: %s', 
                                          idx, majordict_idx, type(majordict))
                            continue
                        majorid = majordict.get('majorId')
                        submajorid = majordict.get('subCategoryId')
                        logger.debug('[volunteer_Recommand] 步骤5: 志愿项 %d, 专业 %d, majorId=%s, subCategoryId=%s', 
                                    idx, majordict_idx, majorid, submajorid)
                        if majorid == '0':majorid = submajorid # majorId=='0'：一是专业大类，取'subCategoryId'；二是实验班类型，暂不处理
                        planMoney = majordict.get('planMoney')#学费
                        # 提取其中的数字部分，例如 "5000元/年" -> 5000
                        try:
                            if planMoney is None or planMoney == '':
                                planMoney = 0
                            else:
                                # 提取字符串中的所有数字部分，去掉非数字字符
                                planMoneyStr = str(planMoney)
                                digits = re.sub(r'[^0-9]', '', planMoneyStr)
                                if not digits:
                                    planMoney = 0
                                else:
                                    planMoney = int(digits)
                        except (ValueError, TypeError):
                            planMoney = 0  # 解析失败则不进行学费过滤
                        '''从major_score获取对应专业（类）得分'''
                        gender_index = 0
                        satisfy_index = 0
                        salary_avg = 0
                        hot_index = 0
                        major_score_old = major_score_avg
                        major_score_new = major_score_old
                        evaluate_score = 0
                        special_score = 0
                        degree_score = 0
                        degree = 'null'
                        major_level = 'null'
                        major_remark = ''
                        major_factors = []
                        major_flag = []
                        #if majorid in major_score['major_id'].values:
                        if majorid in major_dict:
                            indexdict = major_dict[majorid]
                            gender_index = float(indexdict['gender_index'])
                            satisfy_index = float(indexdict['satisfy_index'])
                            salary_avg = float(indexdict['salary_avg'])
                            hot_index = float(indexdict['hot_index'])
                            major_score_old = float(indexdict['major_score'])
                            major_score_new = major_score_old
                            evaluate_score = 0
                            special_score = 0

                            if majorid in negative_majorlist:
                                major_value = negative_major_dict.get(majorid, 0.01)
                                _mf_before = major_score_new
                                major_score_new = major_score_new * 0.1 * major_value
                                major_remark += '专业负向减分;'
                                _record_factor(major_factors, "专业负向减分", _mf_before, major_score_new)
                                negative_major_num += 1
                                major_flag.append(-1)
                            elif submajorid in negative_majorlist:
                                major_value = negative_major_dict.get(submajorid, 0.01)
                                _mf_before = major_score_new
                                major_score_new = major_score_new * 0.3 * major_value
                                major_remark += '专业（类）负向减分;'
                                _record_factor(major_factors, "专业（类）负向减分", _mf_before, major_score_new)
                                negative_major_num += 1
                                major_flag.append(-1)
                            elif majorid in positive_majorlist:
                                major_value = positive_major_dict.get(majorid, 1)
                                _mf_before = major_score_new
                                major_score_new += (100 - major_score_new) * (major_score_new / 100) * 1 * major_value
                                major_remark += '专业正向加分;'
                                _record_factor(major_factors, "专业正向加分", _mf_before, major_score_new)
                                positive_major_num += 1
                                major_flag.append(1)
                            elif submajorid in positive_majorlist:
                                major_value = positive_major_dict.get(majorid, 1)
                                _mf_before = major_score_new
                                major_score_new += (100 - major_score_new) * (major_score_new / 100) * 0.8 * major_value
                                major_remark += '专业（类）正向加分;'
                                _record_factor(major_factors, "专业（类）正向加分", _mf_before, major_score_new)
                                positive_major_num += 1
                                major_flag.append(1)

                            '''额外分数调整：专业tag信息'''
                            add_count=0
                            for tag in tag_major:
                                try:
                                    tag_data = tag_major[tag]
                                    # 验证tag_data是字典类型，且包含'id'字段
                                    if not isinstance(tag_data, dict):
                                        logger.warning('[volunteer_Recommand] 志愿项 %d, 专业 %d, tag_major[%s]不是字典类型，跳过: %s', 
                                                      idx, majordict_idx, tag, type(tag_data))
                                        continue
                                    if 'id' not in tag_data:
                                        logger.warning('[volunteer_Recommand] 志愿项 %d, 专业 %d, tag_major[%s]中缺少id字段，跳过', 
                                                      idx, majordict_idx, tag)
                                        continue
                                    if majorid in tag_data['id'] or submajorid in tag_data['id']:
                                        if tag in negative_taglist:
                                            tag_value = negative_tag_dict.get(tag, 0.01)
                                            if majorid in tag_data['id'] and 1 not in major_flag:
                                                _mf_before = major_score_new
                                                major_score_new = major_score_new * 0.1 * tag_value
                                                _segment = tag + '标签负向减分;'
                                                major_remark += _segment
                                                _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                                major_flag.append(-2)
                                            elif submajorid in tag_data['id'] and 1 not in major_flag:
                                                _mf_before = major_score_new
                                                major_score_new = major_score_new * 0.3 * tag_value
                                                _segment = tag + '（类）标签负向减分;'
                                                major_remark += _segment
                                                _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                                major_flag.append(-2)
                                        elif tag in positive_taglist:
                                            tag_value = positive_tag_dict.get(tag, 1)
                                            if majorid in tag_data['id'] and -1 not in major_flag:
                                                if add_count < 1:
                                                    _mf_before = major_score_new
                                                    major_score_new += 8 * tag_value
                                                    add_count += 1
                                                    _segment = tag + '标签正向加分;'
                                                    major_remark += _segment
                                                    _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                                    major_flag.append(2)
                                            elif submajorid in tag_data['id'] and -1 not in major_flag:
                                                if add_count < 2:
                                                    _mf_before = major_score_new
                                                    major_score_new += 4 * tag_value
                                                    add_count += 1
                                                    _segment = tag + '（类）标签正向加分;'
                                                    major_remark += _segment
                                                    _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                                    major_flag.append(2)
                                except Exception as e:
                                    logger.error('[volunteer_Recommand] 志愿项 %d, 专业 %d, 处理tag %s时出错: %s', 
                                                idx, majordict_idx, tag, str(e))
                                    logger.exception('[volunteer_Recommand] 详细错误堆栈:')
                                    raise
                            #学费标签处理
                            if '高学费专业' in negative_taglist:
                                tag_value = negative_tag_dict.get('高学费专业', 0.01)
                                MoneyFlag = 1
                                if 10000 <= planMoney:
                                    MoneyFlag = 0.1
                                elif 5500 <= planMoney < 10000:
                                    MoneyFlag = 0.5
                                elif 4500 < planMoney < 5500:
                                    MoneyFlag = 0.7
                                if MoneyFlag != 1:
                                    _mf_before = major_score_new
                                    major_score_new = major_score_new * MoneyFlag * tag_value
                                    major_remark += '高学费专业标签负向减分;'
                                    _record_factor(major_factors, "高学费专业标签负向减分", _mf_before, major_score_new)
                                    major_flag.append(-2)
                                else:
                                    _mf_before = major_score_new
                                    major_score_new += 2
                                    major_remark += '低学费专业标签正向加分;'
                                    _record_factor(major_factors, "低学费专业标签正向加分", _mf_before, major_score_new)
                                    major_flag.append(2)
                            elif '低学费专业' in positive_taglist:
                                tag_value = positive_tag_dict.get('低学费专业', 1)
                                MoneyFlag = 1
                                if 10000 <= planMoney:
                                    MoneyFlag = 0.1
                                elif 5500 <= planMoney < 10000:
                                    MoneyFlag = 0.5
                                elif 4500 < planMoney < 5500:
                                    MoneyFlag = 0.7
                                if MoneyFlag != 1:
                                    _mf_before = major_score_new
                                    major_score_new = major_score_new * MoneyFlag
                                    major_remark += '高学费专业标签负向减分;'
                                    _record_factor(major_factors, "高学费专业标签负向减分", _mf_before, major_score_new)
                                    major_flag.append(-2)
                                else:
                                    _mf_before = major_score_new
                                    major_score_new += 2 * tag_value
                                    major_remark += '低学费专业标签正向加分;'
                                    _record_factor(major_factors, "低学费专业标签正向加分", _mf_before, major_score_new)
                                    major_flag.append(2)

                            '''从data_evaluate获取专业评估信息'''
                            if batch == '01':
                                #本科专业：学科评估
                                evaluate_data = loader.lookup_evaluate_data(plan['schoolId'], majorid, submajorid)
                            else:
                                #专科专业：双高计划评估
                                evaluate_data = loader.lookup_evaluate_02_data(plan['schoolId'], majorid, submajorid)
                            if evaluate_data:
                                major_level = evaluate_data['level']
                                if -1 not in major_flag and plan['schoolId'] not in negative_schoollist:
                                    evaluate_score = evaluate_data['evaluate_score']
                                    _mf_before = major_score_new
                                    major_score_new += evaluate_score * 0.05
                                    major_remark += '专业评估加分;'
                                    _record_factor(major_factors, "专业评估加分", _mf_before, major_score_new)

                            '''从data_special获取特色专业信息'''
                            is_special = loader.lookup_special_data(plan['schoolId'], majorid, submajorid)
                            if is_special:
                                if -1 not in major_flag and plan['schoolId'] not in negative_schoollist:
                                    special_score = 100
                                    _mf_before = major_score_new
                                    major_score_new += special_score * 0.03
                                    major_remark += '特色专业加分;'
                                    _record_factor(major_factors, "特色专业加分", _mf_before, major_score_new)

                            '''从data_degree获取硕博点信息'''
                            degree_data = loader.lookup_degree_data(plan['schoolId'], majorid, submajorid)
                            if degree_data:
                                degree = degree_data['degree']
                                if -1 not in major_flag and plan['schoolId'] not in negative_schoollist:
                                    degree_score = degree_data['score']
                                    _mf_before = major_score_new
                                    major_score_new += degree_score * 0.02
                                    major_remark += '硕博点加分;'
                                    _record_factor(major_factors, "硕博点加分", _mf_before, major_score_new)

                            # 无任何意向的专业得分处理
                            if len(major_flag) == 0:
                                _mf_before = major_score_new
                                major_score_new = major_score_new * 0.6
                                major_remark = '专业无意向减分;'
                                _record_factor(major_factors, "专业无意向减分", _mf_before, major_score_new)
                        else:
                            # 未知的专业得分处理
                            _mf_before = major_score_new
                            major_score_new = major_score_new * 0.6
                            major_remark = '未知专业减分;'
                            _record_factor(major_factors, "未知专业减分", _mf_before, major_score_new)

                        # 在plan的majorlist中的每一个major新增专业指标得分
                        majordict['gender_index'] = gender_index
                        majordict['satisfy_index'] = satisfy_index
                        majordict['salary_avg'] = salary_avg
                        majordict['hot_index'] = hot_index
                        majordict['evaluate_score'] = evaluate_score
                        majordict['special_score'] = special_score
                        majordict['degree_score'] = degree_score
                        majordict['degree'] = degree
                        majordict['major_level'] = major_level
                        majordict['major_score'] = major_score_old
                        majordict['major_score_new'] = major_score_new
                        majordict['major_factors'] = major_factors
                        majordict['major_remark'] = major_remark.strip(';')
                        major_score_final += major_score_new
                    except Exception as e:
                        logger.error('[volunteer_Recommand] 志愿项 %d, 处理专业 %d时出错: %s', idx, majordict_idx, str(e))
                        logger.exception('[volunteer_Recommand] 详细错误堆栈:')
                        raise
                '''排序专业列表'''
                plan['majorList'] = sorted(plan['majorList'], key=lambda x: x['major_score_new'], reverse=True)
                '''根据filterType获取专业（组）偏好'''
                rato = 1.0 # 专业（组）得分系数，用于调整专业（组）最终得分
                weight = 1.0 # 志愿得分系数，用于调整志愿最终得分
                eps = 1e-5 # 防止除零
                if filterType == '3':  # 仅正向专业
                    if total_major_num == 1:
                        if negative_major_num == 1:
                            rato = 0.01
                            weight = 0.01
                        elif positive_major_num != 1:
                            rato = 0.1
                            weight = 0.1
                    else:
                        if negative_major_num > 0:
                            rato = 0.01
                            weight = 0.01
                        elif positive_major_num != total_major_num:
                            rato = (positive_major_num / total_major_num) if positive_major_num > 0 else (0.1 / total_major_num)
                            weight = 0.1
                elif filterType == '2':  # 非负向专业
                    if total_major_num == 1:
                        if negative_major_num == 1:
                            rato = 0.01
                            weight = 0.01
                    else:
                        if negative_major_num > 0:
                            rato = (total_major_num - negative_major_num + eps) * 0.1 / total_major_num
                            weight = 0.01
                major_score_final = (major_score_final * rato) / total_major_num
                plan['major_score'] = float(major_score_final)
                # 计算最终志愿得分
                harmonic_score = 2 * college_score_new * major_score_final / (college_score_new + major_score_final + eps)# 调和平均：强调"不能有短板"
                plan['volunteer_score'] = float(harmonic_score * weight)
                logger.debug('[volunteer_Recommand] 步骤5: 志愿项 %d 处理完成, volunteer_score=%.2f', idx, plan['volunteer_score'])
            except Exception as e:
                logger.error('[volunteer_Recommand] 处理志愿项 %d 时出错: %s', idx, str(e))
                logger.exception('[volunteer_Recommand] 详细错误堆栈:')
                raise
        logger.info('[volunteer_Recommand] 步骤6: 开始排序志愿表')
        volunteerinfo_sorted = sorted(volunteerinfo, key=lambda x: x['volunteer_score'], reverse=True)
        logger.info('[volunteer_Recommand] 步骤6: 志愿表排序完成')
        logger.info('[volunteer_Recommand] 函数执行完成, 返回志愿数量: %d', len(volunteerinfo_sorted))
        return volunteerinfo_sorted
    except Exception as e:
        logger.error('[volunteer_Recommand] 函数执行出错: %s', str(e))
        logger.exception('[volunteer_Recommand] 详细错误堆栈:')
        raise


def _record_factor(factors, tag, before, after):
    """把一次打分调整记成结构化因子（P1d 步骤 1）。

    `delta` 一律是**差值**（调整后 - 调整前）——原实现里正向是加、负向是乘，
    两种写法都要用同一个口径表达"它对分数做了什么"，否则下游没法把因子加回总分。

    标签取 remark 那段的原文：**同一处文本**，避免"备注说加了 5 分、
    结构化说加了 3 分"这种双源漂移。
    """
    factors.append({"tag": tag, "delta": after - before})


def weight_Query(studentinfo, queryinfo, profileinfo):
    """权重查询函数"""
    logger.info('[weight_Query] 函数开始执行')
    # 获取数据加载器实例，用于快速查找
    loader = get_data_loader()
    logger.info('[weight_Query] 步骤1: 准备原始数据')
    batch = studentinfo['batch']['level']
    sex = studentinfo['sex']['code']
    if sex == 'male':
        queryinfo['gender_flag'] = '男生'
    else:
        queryinfo['gender_flag'] = '女生'
    type = queryinfo['type']
    if type in ['major', 'majorschool']:
        logger.info("[weight_Query] 计算专业得分")
        major_score, major_weight = major_Recommand(studentinfo)
        major_dict = major_score.set_index('major_id').to_dict('index')
        logger.info("[weight_Query] 获取专业意向")
        '''从profileinfo获取专业意向'''
        # 获取正向专业
        positive_major2 = profileinfo.get('major_intent', {}).get('level2_code', [])
        positive_major2_emotion = profileinfo.get('major_intent', {}).get('level2_emotion', [])
        positive_major3 = profileinfo.get('major_intent', {}).get('level3_code', [])
        positive_major3_emotion = profileinfo.get('major_intent', {}).get('level3_emotion', [])
        positive_major2_emotion.extend(positive_major3_emotion)
        positive_major2.extend(positive_major3)
        positive_majorlist = positive_major2
        positive_major_dict = emotion_process(positive_majorlist, positive_major2_emotion, "positive")

        # 获取负向专业
        negative_major2 = profileinfo.get('negative_major_intent', {}).get('level2_code', [])
        negative_major2_emotion = profileinfo.get('negative_major_intent', {}).get('level2_emotion', [])
        negative_major3 = profileinfo.get('negative_major_intent', {}).get('level3_code', [])
        negative_major3_emotion = profileinfo.get('negative_major_intent', {}).get('level3_emotion', [])
        negative_major2.extend(negative_major3)
        negative_major2_emotion.extend(negative_major3_emotion)
        negative_majorlist = negative_major2
        negative_major_dict = emotion_process(negative_majorlist, negative_major2_emotion, "negative")

    if type in ['school', 'majorschool']:
        logger.info("[weight_Query] 计算院校得分")
        college_score, college_weight = college_Recommand(batch)
        college_dict = college_score.set_index('school_id').to_dict('index')

        logger.info("[weight_Query] 获取院校意向")
        '''从profileinfo获取院校意向'''
        negative_schoollist = profileinfo.get('negative_college_info', {}).get('values_code', [])
        negative_school_emotion = profileinfo.get('negative_college_info', {}).get('values_emotion', [])
        negative_school_dict = emotion_process(negative_schoollist, negative_school_emotion, "negative")
        positive_schoollist = profileinfo.get('college_info', {}).get('values_code', [])
        positive_school_emotion = profileinfo.get('college_info', {}).get('values_emotion', [])
        positive_school_dict = emotion_process(positive_schoollist, positive_school_emotion, "positive")

        logger.info("[weight_Query] 获取地域意向")
        '''从profileinfo获取地域意向'''
        positive_citylist = profileinfo.get('city_info', {}).get('city_code', [])
        positive_city_emotion = profileinfo.get('city_info', {}).get('city_emotion', [])
        positive_city_dict = emotion_process(positive_citylist, positive_city_emotion, "positive")
        negative_citylist = profileinfo.get('negative_city_info', {}).get('city_code', [])
        negative_city_emotion = profileinfo.get('negative_city_info', {}).get('city_emotion', [])
        negative_city_dict = emotion_process(negative_citylist, negative_city_emotion, "negative")
        positive_provincelist = profileinfo.get('city_info', {}).get('province_code', [])
        positive_province_emotion = profileinfo.get('city_info', {}).get('province_emotion', [])
        positive_province_dict = emotion_process(positive_provincelist, positive_province_emotion, "positive")
        negative_provincelist = profileinfo.get('negative_city_info', {}).get('province_code', [])
        negative_province_emotion = profileinfo.get('negative_city_info', {}).get('province_emotion', [])
        negative_province_dict = emotion_process(negative_provincelist, negative_province_emotion, "negative")

    if batch != '02':
        tag_major = loader.get_tag_major()
    else:
        tag_major = loader.get_tag_major_02()
    logger.info("[weight_Query] 获取Tag意向")
    '''从profileinfo获取tag意向'''
    positive_taglist = profileinfo.get('tag_info', {}).get('values', [])
    positive_tag_emotion = profileinfo.get('tag_info', {}).get('values_emotion', [])
    positive_tag_dict = emotion_process(positive_taglist, positive_tag_emotion, "positive")
    negative_taglist = profileinfo.get('negative_tag_info', {}).get('values', [])
    negative_tag_emotion = profileinfo.get('negative_tag_info', {}).get('values_emotion', [])
    negative_tag_dict = emotion_process(negative_taglist, negative_tag_emotion, "negative")

    logger.info("[weight_Query] 步骤2: 计算数据得分")
    if type == 'major':
        queryinfo = {**major_weight, **queryinfo}
        querylist = queryinfo['querylist']
        for major in querylist:
            gender_index = 0
            satisfy_index = 0
            salary_avg = 0
            hot_index = 0
            major_score = 0
            major_score_new = 0
            major_remark = ''
            major_factors = []
            major_flag = []
            majorid = major['major_id']
            '''从major_score获取对应专业（类）得分'''
            if majorid in major_dict:
                indexdict = major_dict[majorid]
                submajorid = indexdict['id2']
                gender_index = float(indexdict['gender_index'])
                satisfy_index = float(indexdict['satisfy_index'])
                salary_avg = float(indexdict['salary_avg'])
                hot_index = float(indexdict['hot_index'])
                major_score = float(indexdict['major_score'])
                major_score_new = major_score

                if majorid in negative_majorlist:
                    major_value = negative_major_dict.get(majorid, 0.01)
                    _mf_before = major_score_new
                    major_score_new = major_score_new * 0.1 * major_value
                    major_remark = '非意向专业;'
                    _record_factor(major_factors, "非意向专业", _mf_before, major_score_new)
                    major_flag.append(-1)
                elif submajorid in negative_majorlist:
                    major_value = negative_major_dict.get(submajorid, 0.01)
                    _mf_before = major_score_new
                    major_score_new = major_score_new * 0.3 * major_value
                    major_remark = '非意向专业类;'
                    _record_factor(major_factors, "非意向专业类", _mf_before, major_score_new)
                    major_flag.append(-1)
                elif majorid in positive_majorlist:
                    major_value = positive_major_dict.get(majorid, 1)
                    _mf_before = major_score_new
                    major_score_new += (100 - major_score_new) * (major_score_new / 100) * 1 * major_value
                    major_remark = '意向专业;'
                    _record_factor(major_factors, "意向专业", _mf_before, major_score_new)
                    major_flag.append(1)
                elif submajorid in positive_majorlist:
                    major_value = positive_major_dict.get(majorid, 1)
                    _mf_before = major_score_new
                    major_score_new += (100 - major_score_new) * (major_score_new / 100) * 0.8 * major_value
                    major_remark = '意向专业类;'
                    _record_factor(major_factors, "意向专业类", _mf_before, major_score_new)
                    major_flag.append(1)

                '''额外分数调整：专业tag信息'''
                add_count = 0
                for tag in tag_major:
                    tag_data = tag_major[tag]
                    if majorid in tag_data['id'] or submajorid in tag_data['id']:
                        if tag in negative_taglist:
                            tag_value = negative_tag_dict.get(tag, 0.01)
                            if majorid in tag_data['id'] and 1 not in major_flag:
                                _mf_before = major_score_new
                                major_score_new = major_score_new * 0.1 * tag_value
                                _segment = tag + '非意向标签'
                                major_remark += _segment
                                _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                major_flag.append(-2)
                            elif submajorid in tag_data['id'] and 1 not in major_flag:
                                _mf_before = major_score_new
                                major_score_new = major_score_new * 0.3 * tag_value
                                _segment = tag + '类非意向标签'
                                major_remark += _segment
                                _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                major_flag.append(-2)
                        elif tag in positive_taglist:
                            tag_value = positive_tag_dict.get(tag, 1)
                            if majorid in tag_data['id'] and -1 not in major_flag:
                                if add_count < 1:
                                    _mf_before = major_score_new
                                    major_score_new += 10 * tag_value
                                    _segment = tag + '意向标签'
                                    major_remark += _segment
                                    _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                    major_flag.append(2)
                            elif submajorid in tag_data['id'] and -1 not in major_flag:
                                if add_count < 2:
                                    _mf_before = major_score_new
                                    major_score_new += 5 * tag_value
                                    add_count += 1
                                    _segment = tag + '类意向标签'
                                    major_remark += _segment
                                    _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                    major_flag.append(2)

            # 在querylist中的每一个major新增专业指标得分
            major['gender_index'] = gender_index
            major['satisfy_index'] = satisfy_index
            major['salary_avg'] = salary_avg
            major['hot_index'] = hot_index
            major['major_score'] = major_score
            major['major_score_new'] = major_score_new
            major['major_factors'] = major_factors
            major['major_remark'] = major_remark
    elif type in ['school', 'majorschool']:
        queryinfo = {**college_weight, **queryinfo}
        querylist = queryinfo['querylist']
        for school in querylist:
            province_gdp = 0
            city_level = 0
            upgrade_ratio = 0
            postgraduate_recommend_ratio = 0
            gaotu_rank = 0
            level_score = 0
            college_score = 0
            college_score_new = 0
            college_remark = ''
            college_factors = []
            school_flag = []
            school_id = school['school_id']
            if school_id in college_dict:
                indexdict = college_dict[school_id]
                province_id = indexdict['province_code']
                city_id = indexdict['city_code'] if len(indexdict['city_code'])>0 else province_id
                province_gdp = float(indexdict['province_gdp'])
                city_level = float(indexdict['city_level'])
                upgrade_ratio = float(indexdict['upgrade_ratio'])
                postgraduate_recommend_ratio = float(indexdict['postgraduate_recommend_ratio'])
                gaotu_rank = float(indexdict['gaotu_rank'])
                level_score = float(indexdict['level_score'])
                category = str(indexdict.get('category', '')) if indexdict.get('category') is not None else ''
                nature = str(indexdict.get('nature', '')) if indexdict.get('nature') is not None else ''
                postgraduate = str(indexdict.get('postgraduate', '')) if indexdict.get('postgraduate') is not None else ''
                levellist = str(indexdict.get('tag', '')).split('、') if indexdict.get('tag') is not None else []
                college_score = float(indexdict['college_score'])
                college_score_new = college_score

                if school_id and school_id in negative_schoollist:
                    school_value = negative_school_dict.get(school_id, 0.01)
                    _cf_before = college_score_new
                    college_score_new = college_score_new * 0.1 * school_value
                    college_remark = '非意向院校;'
                    _record_factor(college_factors, "非意向院校", _cf_before, college_score_new)
                    school_flag.append(-1)
                elif school_id and school_id in positive_schoollist:
                    school_value = positive_school_dict.get(school_id, 1)
                    _cf_before = college_score_new
                    college_score_new += (100 - college_score_new) * (college_score_new / 100) * 1 * school_value
                    college_remark = '意向院校;'
                    _record_factor(college_factors, "意向院校", _cf_before, college_score_new)
                    school_flag.append(1)
                else:
                    if city_id and city_id in negative_citylist:
                        city_value = negative_city_dict.get(city_id, 0.01)
                        _cf_before = college_score_new
                        college_score_new = college_score_new * 0.3 * city_value
                        college_remark = '非意向城市;'
                        _record_factor(college_factors, "非意向城市", _cf_before, college_score_new)
                        school_flag.append(-2)
                    elif city_id and city_id in positive_citylist:
                        city_value = positive_city_dict.get(city_id, 1)
                        _cf_before = college_score_new
                        college_score_new += (100 - college_score_new) * (college_score_new / 100) * 0.8 * city_value
                        college_remark = '意向城市;'
                        _record_factor(college_factors, "意向城市", _cf_before, college_score_new)
                        school_flag.append(2)
                    else:
                        if province_id and province_id in negative_provincelist:
                            province_value = negative_province_dict.get(province_id, 0.01)
                            _cf_before = college_score_new
                            college_score_new = college_score_new * 0.5 * province_value
                            college_remark = '非意向省份;'
                            _record_factor(college_factors, "非意向省份", _cf_before, college_score_new)
                            school_flag.append(-2)
                        elif province_id and province_id in positive_provincelist:
                            province_value = positive_province_dict.get(province_id, 1)
                            _cf_before = college_score_new
                            college_score_new += (100 - college_score_new) * (college_score_new / 100) * 0.5 * province_value
                            college_remark = '意向省份;'
                            _record_factor(college_factors, "意向省份", _cf_before, college_score_new)
                            school_flag.append(2)

                '''额外分数调整：院校tag信息'''
                if len(levellist) > 0 and (len(negative_taglist) > 0 or len(positive_taglist) > 0):
                    if len(list(set(levellist) & set(['985', '强基']))) > 0:
                        for level in ['985', '强基']:
                            tag_key = level + '院校'
                            if tag_key in negative_taglist and 1 not in school_flag:
                                tag_value = negative_tag_dict.get(tag_key, 0.01)
                                _cf_before = college_score_new
                                college_score_new = college_score_new * 0.95 * tag_value
                                _segment = tag_key + '非意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(-3)
                            elif tag_key in positive_taglist and -1 not in school_flag:
                                tag_value = positive_tag_dict.get(tag_key, 1)
                                _cf_before = college_score_new
                                college_score_new += 8 * tag_value
                                _segment = tag_key + '意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(3)
                    elif len(list(set(levellist) & set(['211', '双一流', '国重点', '国家级示范', '国家级骨干', '双高计划']))) > 0:
                        for level in ['211', '双一流', '国重点', '国家级示范', '国家级骨干', '双高计划']:
                            tag_key = level + '院校'
                            if tag_key in negative_taglist and 1 not in school_flag:
                                tag_value = negative_tag_dict.get(tag_key, 0.01)
                                _cf_before = college_score_new
                                college_score_new = college_score_new * 0.9 * tag_value
                                _segment = tag_key + '非意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(-3)
                            elif tag_key in positive_taglist and -1 not in school_flag:
                                tag_value = positive_tag_dict.get(tag_key, 1)
                                _cf_before = college_score_new
                                college_score_new += 7 * tag_value
                                _segment = tag_key + '意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(3)
                    elif len(list(set(levellist) & set(['保研', '省重点']))) > 0:
                        for level in ['保研', '省重点']:
                            tag_key = level + '院校'
                            if tag_key in negative_taglist and 1 not in school_flag:
                                tag_value = negative_tag_dict.get(tag_key, 0.01)
                                _cf_before = college_score_new
                                college_score_new = college_score_new * 0.85 * tag_value
                                _segment = tag_key + '非意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(-3)
                            elif tag_key in positive_taglist and -1 not in school_flag:
                                tag_value = positive_tag_dict.get(tag_key, 1)
                                _cf_before = college_score_new
                                college_score_new += 6 * tag_value
                                _segment = tag_key + '意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(3)
                    else:
                        for level in levellist:
                            tag_key = level + '院校'
                            if tag_key in negative_taglist and 1 not in school_flag:
                                tag_value = negative_tag_dict.get(tag_key, 0.01)
                                _cf_before = college_score_new
                                college_score_new = college_score_new * 0.8 * tag_value
                                _segment = tag_key + '非意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(-3)
                            elif tag_key in positive_taglist and -1 not in school_flag:
                                tag_value = positive_tag_dict.get(tag_key, 1)
                                _cf_before = college_score_new
                                college_score_new += 2 * tag_value
                                _segment = tag_key + '意向标签;'
                                college_remark += _segment
                                _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                                school_flag.append(3)

                if postgraduate:
                    tag_key = postgraduate + '院校'
                    if tag_key in negative_taglist and 1 not in school_flag:
                        tag_value = negative_tag_dict.get(tag_key, 0.01)
                        _cf_before = college_score_new
                        college_score_new = college_score_new * 0.6 * tag_value
                        _segment = tag_key + '非意向标签;'
                        college_remark += _segment
                        _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                        school_flag.append(-3)
                    elif tag_key in positive_taglist and -1 not in school_flag:
                        tag_value = positive_tag_dict.get(tag_key, 1)
                        _cf_before = college_score_new
                        college_score_new += 6 * tag_value
                        _segment = tag_key + '意向标签;'
                        college_remark += _segment
                        _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                        school_flag.append(3)

                if category:
                    tag_key = category + '院校'
                    if tag_key in negative_taglist and 1 not in school_flag:
                        tag_value = negative_tag_dict.get(tag_key, 0.01)
                        _cf_before = college_score_new
                        college_score_new = college_score_new * 0.5 * tag_value
                        _segment = tag_key + '非意向标签;'
                        college_remark += _segment
                        _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                        school_flag.append(-3)
                    elif tag_key in positive_taglist and -1 not in school_flag:
                        tag_value = positive_tag_dict.get(tag_key, 1)
                        _cf_before = college_score_new
                        college_score_new += 5 * tag_value
                        _segment = tag_key + '意向标签;'
                        college_remark += _segment
                        _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                        school_flag.append(3)

                if nature:
                    tag_key = nature + '院校'
                    if tag_key in negative_taglist and 1 not in school_flag:
                        tag_value = negative_tag_dict.get(tag_key, 0.01)
                        _cf_before = college_score_new
                        college_score_new = college_score_new * 0.3 * tag_value
                        _segment = tag_key + '非意向标签;'
                        college_remark += _segment
                        _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                        school_flag.append(-3)
                    elif tag_key in positive_taglist and -1 not in school_flag:
                        tag_value = positive_tag_dict.get(tag_key, 1)
                        _cf_before = college_score_new
                        college_score_new += 1 * tag_value
                        _segment = tag_key + '意向标签;'
                        college_remark += _segment
                        _record_factor(college_factors, _segment.rstrip(";"), _cf_before, college_score_new)
                        school_flag.append(3)

            # 在querylist中的每一个school新增院校指标得分
            school['province_gdp'] = province_gdp
            school['city_level'] = city_level
            school['upgrade_ratio'] = upgrade_ratio
            school['postgraduate_recommend_ratio'] = postgraduate_recommend_ratio
            school['gaotu_rank'] = gaotu_rank
            school['level_score'] = level_score
            school['college_score'] = college_score
            school['college_score_new'] = college_score_new
            school['college_factors'] = college_factors
            school['college_remark'] = college_remark
            if type == 'majorschool':
                queryinfo = {**major_weight, **queryinfo}
                majors = school['majors']
                for major in majors:
                    gender_index = 0
                    satisfy_index = 0
                    salary_avg = 0
                    hot_index = 0
                    major_score = 0
                    major_score_new = 0
                    major_score_final = 0
                    evaluate_score = 0
                    special_score = 0
                    degree_score = 0
                    score_extra = 0
                    score_final = 0
                    major_level = ''
                    degree = ''
                    major_remark = ''
                    major_factors = []
                    remark_extra = ''
                    major_flag = []
                    majorid = major['major_id']
                    '''从major_score获取对应专业（类）得分'''
                    if majorid in major_dict:
                        indexdict = major_dict[majorid]
                        submajorid = indexdict['id2']
                        gender_index = float(indexdict['gender_index'])
                        satisfy_index = float(indexdict['satisfy_index'])
                        salary_avg = float(indexdict['salary_avg'])
                        hot_index = float(indexdict['hot_index'])
                        major_score = float(indexdict['major_score'])
                        major_score_new = major_score

                        if majorid in negative_majorlist:
                            major_value = negative_major_dict.get(majorid, 0.01)
                            _mf_before = major_score_new
                            major_score_new = major_score_new * 0.1 * major_value
                            major_remark = '非意向专业;'
                            _record_factor(major_factors, "非意向专业", _mf_before, major_score_new)
                            major_flag.append(-1)
                        elif submajorid in negative_majorlist:
                            major_value = negative_major_dict.get(submajorid, 0.01)
                            _mf_before = major_score_new
                            major_score_new = major_score_new * 0.3 * major_value
                            major_remark = '非意向专业类;'
                            _record_factor(major_factors, "非意向专业类", _mf_before, major_score_new)
                            major_flag.append(-1)
                        elif majorid in positive_majorlist:
                            major_value = positive_major_dict.get(majorid, 1)
                            _mf_before = major_score_new
                            major_score_new += (100 - major_score_new) * (major_score_new / 100) * 1 * major_value
                            major_remark = '意向专业;'
                            _record_factor(major_factors, "意向专业", _mf_before, major_score_new)
                            major_flag.append(1)
                        elif submajorid in positive_majorlist:
                            major_value = positive_major_dict.get(majorid, 1)
                            _mf_before = major_score_new
                            major_score_new += (100 - major_score_new) * (major_score_new / 100) * 0.8 * major_value
                            major_remark = '意向专业类;'
                            _record_factor(major_factors, "意向专业类", _mf_before, major_score_new)
                            major_flag.append(1)

                        '''额外分数调整：专业tag信息'''
                        add_count = 0
                        for tag in tag_major:
                            tag_data = tag_major[tag]
                            if majorid in tag_data['id'] or submajorid in tag_data['id']:
                                if tag in negative_taglist:
                                    tag_value = negative_tag_dict.get(tag, 0.01)
                                    if majorid in tag_data['id'] and 1 not in major_flag:
                                        _mf_before = major_score_new
                                        major_score_new = major_score_new * 0.1 * tag_value
                                        _segment = tag + '非意向标签'
                                        major_remark += _segment
                                        _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                        major_flag.append(-1)
                                    elif submajorid in tag_data['id'] and 1 not in major_flag:
                                        _mf_before = major_score_new
                                        major_score_new = major_score_new * 0.3 * tag_value
                                        _segment = tag + '类非意向标签'
                                        major_remark += _segment
                                        _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                        major_flag.append(-1)
                                elif tag in positive_taglist:
                                    tag_value = positive_tag_dict.get(tag, 1)
                                    if majorid in tag_data['id'] and -1 not in major_flag:
                                        if add_count < 1:
                                            _mf_before = major_score_new
                                            major_score_new += 10 * tag_value
                                            _segment = tag + '意向标签'
                                            major_remark += _segment
                                            _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                            major_flag.append(1)
                                    elif submajorid in tag_data['id'] and -1 not in major_flag:
                                        if add_count < 2:
                                            _mf_before = major_score_new
                                            major_score_new += 5 * tag_value
                                            add_count += 1
                                            _segment = tag + '类意向标签'
                                            major_remark += _segment
                                            _record_factor(major_factors, _segment.rstrip(";"), _mf_before, major_score_new)
                                            major_flag.append(1)

                        '''从data_evaluate获取专业评估信息'''
                        if batch == '01':
                            # 本科专业：学科评估
                            evaluate_data = loader.lookup_evaluate_data(school_id, majorid, submajorid)
                        else:
                            # 专科专业：双高计划评估
                            evaluate_data = loader.lookup_evaluate_02_data(school_id, majorid, submajorid)
                        if evaluate_data:
                            major_level = evaluate_data['level']
                            if -1 not in major_flag and school_id not in negative_schoollist:
                                evaluate_score = evaluate_data['evaluate_score']
                                score_extra += evaluate_score * 0.05
                                remark_extra += '专业评估加分;'

                        '''从data_special获取特色专业信息'''
                        is_special = loader.lookup_special_data(school_id, majorid, submajorid)
                        if is_special:
                            if -1 not in major_flag and school_id not in negative_schoollist:
                                special_score = 100
                                score_extra += special_score * 0.03
                                remark_extra += '特色专业加分;'

                        '''从data_degree获取硕博点信息'''
                        degree_data = loader.lookup_degree_data(school_id, majorid, submajorid)
                        if degree_data:
                            degree = degree_data['degree']
                            if -1 not in major_flag and school_id not in negative_schoollist:
                                degree_score = degree_data['score']
                                score_extra += degree_score * 0.02
                                remark_extra += '硕博点加分;'

                        # 计算最终院校+专业（类）得分
                        eps = 1e-5  # 防止除零
                        major_score_final = major_score_new + score_extra
                        score_final = 2 * college_score_new * major_score_final / (college_score_new + major_score_final + eps)  # 调和平均：强调“不能有短板”

                    # 在majors中的每一个major新增专业指标得分
                    major['gender_index'] = gender_index
                    major['satisfy_index'] = satisfy_index
                    major['salary_avg'] = salary_avg
                    major['hot_index'] = hot_index
                    major['major_score'] = major_score
                    major['major_score_new'] = major_score_new
                    major['major_factors'] = major_factors
                    major['major_score_final'] = major_score_final
                    major['major_remark'] = major_remark
                    major['evaluate_score'] = evaluate_score
                    major['special_score'] = special_score
                    major['degree_score'] = degree_score
                    major['degree'] = degree
                    major['major_level'] = major_level
                    major['score_extra'] = score_extra
                    major['remark_extra'] = remark_extra
                    major['score_final'] = score_final

    logger.info('[weight_Query] 步骤3: 返回对比数据')
    logger.info('[weight_Query] 函数执行完成')
    return queryinfo

if __name__ == "__main__":
    # 学生基本信息
    studentinfo = {
        "batch": {
            "code": "01",
            "level": "02",
            "name": "本科批(批次线459分)",
            "pos": 224230,
            "score": 459
        },
        "bonusPolicy": False,
        "bonusScore": 0,
        "botId": 1,
        "colorBlindness": True,
        "examYear": 2026,
        "minority": True,
        "prepareType": {
            "code": "PREDICT",
            "desc": "模拟填报"
        },
        "province": {
            "code": "130000",
            "name": "河北"
        },
        "sex": {
            "code": "male",
            "name": "男"
        },
        "specialPlan": True,
        "subjectList": [
            {
                "isFirst": 1,
                "name": "物理",
                "subjectType": "WL",
                "value": "01"
            },
            {
                "isFirst": 0,
                "name": "生物",
                "value": "06"
            },
            {
                "isFirst": 0,
                "name": "地理",
                "value": "04"
            }
        ],
        "subjectScoreList": [
            {
                "score": 102,
                "subject": "08",
                "subjectName": "语文"
            },
            {
                "score": 140,
                "subject": "10",
                "subjectName": "数学"
            },
            {
                "score": 139,
                "subject": "11",
                "subjectName": "英语"
            },
            {
                "score": 89,
                "subject": "01",
                "subjectName": "物理"
            },
            {
                "score": 70,
                "subject": "06",
                "subjectName": "生物"
            },
            {
                "score": 88,
                "subject": "04",
                "subjectName": "地理"
            }
        ],
        "subjectType": {
            "code": "WL",
            "desc": "物理"
        },
        "volunteerModel": "majorGroup",  # major: 院校 + 专业 majorGroup: 专业组
        "strengthSubjectList": [
            {
                "subject": "10",
                "subjectName": "数学"
            },
            {
                "subject": "11", 
                "subjectName": "英语"
            },
            {
                "subject": "01",
                "subjectName": "物理"
            }
        ],
        "targetType": "SCHOOL_FIRST",
        "filterType": "2",  # 1:专业不限 2:非负向专业 3:正向专业
        "totalScore": 628,
        "userName": "胡七筒",
        "volunteerCount": {
            "majorCount": 96,
            "schoolCount": 0
        }
    }
    # 志愿初始信息
    with open(os.path.join('data', 'volunteerinfo_major.json'), 'r', encoding='utf8') as file:
        volunteerinfo_major = json.load(file)
    with open(os.path.join('data', 'volunteerinfo_majorgroup.json'), 'r', encoding='utf8') as file:
        volunteerinfo_majorgroup = json.load(file)
    # 动态画像信息
    profileinfo = {
        "major_intent": {
            "level1": [],
            "level2": [],
            "level3": [],
            "level1_code": [],
            "level2_code": [],
            "level3_code": [],
            "level1_emotion": [],
            "level2_emotion": [],
            "level3_emotion": []
        },
        "negative_major_intent": {
            "level1_code": [],
            "level2_code": ["20","56"],
            "level3_code": ["711"],
            "level1_emotion": [],
            "level2_emotion": ["Strong", "Weak"],
            "level3_emotion": ["Strong"]
        },
        "college_info": {
            "values": [],
            "values_code": [],
            "values_emotion": []
        },
        "negative_college_info": {
            "values": [],
            "values_code": ["146","163"],
            "values_emotion": ["Strong", "Neutral"]
        },
        "city_info": {
            "province": ["江苏","浙江","上海","重庆","北京"],
            "city_code": ["610100000000"],
            "city_emotion": ["Strong"],
            "province_code": ["320000","330000","310000","500000","110000"],
            "province_emotion": ["Strong", "Strong", "Strong", "Strong", "Neutral"]
        },
        "negative_city_info": {
            "city_code": ["371000000000"],
            "city_emotion": ["Strong"],
            "province_code": ["230000","220000","210000"],
            "province_emotion": ["Strong", "Strong", "Strong"]
        },
        "tag_info": {
            "values": ['省重点院校','大厂相关专业'],
            "values_emotion": ["Strong", "Strong"]
        },
        "negative_tag_info": {
            "values": ['文科相关专业'],
            "values_emotion": ["Strong"]
        }
    }
    # 专业、院校对比信息
    queryinfo_major = {
      "type": "major",
      "querylist": [
         {
           "major_id": "56",
           "major_name": "交通运输类"
         },
         {
           "major_id": "47",
           "major_name": "计算机类"
         }
      ]
    }
    queryinfo_school = {
        "type": "school",
        "querylist": [
            {
                "school_id": "204"
            },
            {
                "school_id": "159"
            }
        ]
    }
    queryinfo_majorschool = {
        "type": "majorschool",
        "querylist": [
            {
                "school_id": "204",
                "majors":[
                    {
                        "major_id": "56"
                    }
                ]
            },
            {
                "school_id": "159",
                "majors":[
                    {
                        "major_id": "47"
                    }
                ]
            }
        ]
    }

    # 在调用任何推荐函数前，先加载数据
    get_data_loader().load_all_data()

    ###二级专业推荐###
    # submajor_score = submajor_Recommand(studentinfo,8)
    ###志愿推荐###
    volunteerinfo = volunteerinfo_majorgroup
    # volunteer_Recommand(studentinfo, volunteerinfo, profileinfo)
    ###查询权重得分###
    weight_Query(studentinfo, queryinfo_majorschool, profileinfo)