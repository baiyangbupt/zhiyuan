# -*- coding: utf-8 -*-
"""
数据加载器模块
在应用启动时预加载所有Excel等文件数据到内存，避免重复IO操作
"""

import pandas as pd
import os
import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DataLoader:
    """数据加载器单例类"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataLoader, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.data_major: Optional[pd.DataFrame] = None
            self.data_school: Optional[pd.DataFrame] = None
            self.data_degree: Optional[pd.DataFrame] = None
            self.data_evaluate: Optional[pd.DataFrame] = None
            self.data_evaluate_02: Optional[pd.DataFrame] = None
            self.data_special: Optional[pd.DataFrame] = None
            self.tag_major: Optional[Dict] = None
            self.data_major_02: Optional[pd.DataFrame] = None
            self.data_school_02: Optional[pd.DataFrame] = None
            self.tag_major_02: Optional[Dict] = None

            # 新增：预构建的查找索引
            self.evaluate_index: Optional[Dict] = None
            self.evaluate_02_index: Optional[Dict] = None
            self.special_index: Optional[Dict] = None
            self.degree_index: Optional[Dict] = None

            self._initialized = True

    def load_all_data(self):
        """加载所有Excel等数据文件到内存"""
        try:
            dict_path = os.path.join('services', 'dict')
            logger.info("开始加载静态数据文件...")

            # 加载本科专业数据
            major_file = os.path.join(dict_path, 'data_major.xlsx')
            logger.info(f"正在加载本科专业数据: {major_file}")
            self.data_major = pd.read_excel(major_file)
            logger.info(f"本科专业数据加载完成，共 {len(self.data_major)} 条记录")

            # 加载本科院校数据
            school_file = os.path.join(dict_path, 'data_school.xlsx')
            logger.info(f"正在加载本科院校数据: {school_file}")
            self.data_school = pd.read_excel(school_file)
            logger.info(f"本科院校数据加载完成，共 {len(self.data_school)} 条记录")

            # 加载学位数据
            degree_file = os.path.join(dict_path, 'data_degree.xlsx')
            logger.info(f"正在加载学位数据: {degree_file}")
            self.data_degree = pd.read_excel(degree_file)
            logger.info(f"学位数据加载完成，共 {len(self.data_degree)} 条记录")

            # 加载本科专业评估数据
            evaluate_file = os.path.join(dict_path, 'data_evaluate.xlsx')
            logger.info(f"正在加载本科专业评估数据: {evaluate_file}")
            self.data_evaluate = pd.read_excel(evaluate_file)
            logger.info(f"本科专业评估数据加载完成，共 {len(self.data_evaluate)} 条记录")

            # 加载特色专业数据
            special_file = os.path.join(dict_path, 'data_special.xlsx')
            logger.info(f"正在加载特色专业数据: {special_file}")
            self.data_special = pd.read_excel(special_file)
            logger.info(f"特色专业数据加载完成，共 {len(self.data_special)} 条记录")

            # 加载本科专业标签数据
            tag_major_file = os.path.join(dict_path, 'tag_major.json')
            logger.info(f"正在加载本科专业标签数据: {tag_major_file}")
            with open(tag_major_file, 'r', encoding='utf8') as file:
                self.tag_major = json.load(file)
            logger.info("本科专业标签数据加载完成")

            # 加载专科专业数据
            major_file_02 = os.path.join(dict_path, 'data_major_02.xlsx')
            logger.info(f"正在加载专科专业数据: {major_file_02}")
            self.data_major_02 = pd.read_excel(major_file_02)
            logger.info(f"专科专业数据加载完成，共 {len(self.data_major_02)} 条记录")

            # 加载专科院校数据
            school_file_02 = os.path.join(dict_path, 'data_school_02.xlsx')
            logger.info(f"正在加载专科院校数据: {school_file_02}")
            self.data_school_02 = pd.read_excel(school_file_02)
            logger.info(f"专科院校数据加载完成，共 {len(self.data_school_02)} 条记录")

            # 加载专科专业标签数据
            tag_major_file_02 = os.path.join(dict_path, 'tag_major_02.json')
            logger.info(f"正在加载专科专业标签数据: {tag_major_file_02}")
            with open(tag_major_file_02, 'r', encoding='utf8') as file:
                self.tag_major_02 = json.load(file)
            logger.info("专科专业标签数据加载完成")

            # 加载专科专业评估数据
            evaluate_file_02 = os.path.join(dict_path, 'data_evaluate_02.xlsx')
            logger.info(f"正在加载专科专业评估数据: {evaluate_file_02}")
            self.data_evaluate_02 = pd.read_excel(evaluate_file_02)
            logger.info(f"专科专业评估数据加载完成，共 {len(self.data_evaluate_02)} 条记录")

            logger.info("所有静态数据文件加载完成！")

            # 构建查找索引以提升查询性能
            logger.info("开始构建查找索引...")
            self._build_lookup_indexes()
            logger.info("查找索引构建完成！")

        except Exception as e:
            logger.error(f"数据加载失败: {str(e)}")
            raise

    def get_major_data(self) -> pd.DataFrame:
        """获取本科专业数据副本"""
        if self.data_major is None:
            raise RuntimeError("本科专业数据未加载，请先调用load_all_data()")
        return self.data_major.copy()

    def get_school_data(self) -> pd.DataFrame:
        """获取本科院校数据副本"""
        if self.data_school is None:
            raise RuntimeError("本科院校数据未加载，请先调用load_all_data()")
        return self.data_school.copy()

    def get_degree_data(self) -> pd.DataFrame:
        """获取学位数据副本"""
        if self.data_degree is None:
            raise RuntimeError("学位数据未加载，请先调用load_all_data()")
        return self.data_degree.copy()

    def get_evaluate_data(self) -> pd.DataFrame:
        """获取本科专业评估数据副本"""
        if self.data_evaluate is None:
            raise RuntimeError("本科专业评估数据未加载，请先调用load_all_data()")
        return self.data_evaluate.copy()

    def get_special_data(self) -> pd.DataFrame:
        """获取特色专业数据副本"""
        if self.data_special is None:
            raise RuntimeError("特色专业数据未加载，请先调用load_all_data()")
        return self.data_special.copy()

    def get_tag_major(self) -> Dict:
        """获取本科专业标签数据"""
        if self.tag_major is None:
            raise RuntimeError("本科专业标签数据未加载，请先调用load_all_data()")
        return self.tag_major

    def get_major_02_data(self) -> pd.DataFrame:
        """获取专科专业数据副本"""
        if self.data_major_02 is None:
            raise RuntimeError("专科专业数据未加载，请先调用load_all_data()")
        return self.data_major_02.copy()

    def get_school_02_data(self) -> pd.DataFrame:
        """获取专科院校数据副本"""
        if self.data_school_02 is None:
            raise RuntimeError("专科院校数据未加载，请先调用load_all_data()")
        return self.data_school_02.copy()

    def get_tag_major_02(self) -> Dict:
        """获取专科专业标签数据"""
        if self.tag_major_02 is None:
            raise RuntimeError("专科专业标签数据未加载，请先调用load_all_data()")
        return self.tag_major_02

    def get_evaluate_data(self) -> pd.DataFrame:
        """获取专科专业评估数据副本"""
        if self.data_evaluate_02 is None:
            raise RuntimeError("专科专业评估数据未加载，请先调用load_all_data()")
        return self.data_evaluate_02.copy()

    def is_loaded(self) -> bool:
        """检查数据是否已加载"""
        return all([
            self.data_major is not None,
            self.data_school is not None,
            self.data_degree is not None,
            self.data_evaluate is not None,
            self.data_evaluate_02 is not None,
            self.data_special is not None,
            self.tag_major is not None,
            self.data_major_02 is not None,
            self.data_school_02 is not None,
            self.tag_major_02 is not None
        ])

    def _build_lookup_indexes(self):
        """构建快速查找索引"""
        # 构建本科专业评估数据索引：{school_id: {major_id: row_data}}
        self.evaluate_index = {}
        for _, row in self.data_evaluate.iterrows():
            school_id = str(row['school_id'])
            major_id = str(row['major_id'])

            if school_id not in self.evaluate_index:
                self.evaluate_index[school_id] = {}
            self.evaluate_index[school_id][major_id] = {
                'level': str(row['level']),
                'evaluate_score': float(row['evaluate_score'])
            }

        # 构建专科专业评估数据索引：{school_id: {major_id: row_data}}
        self.evaluate_02_index = {}
        for _, row in self.data_evaluate_02.iterrows():
            school_id = str(row['school_id'])
            major_id = str(row['major_id'])

            if school_id not in self.evaluate_02_index:
                self.evaluate_02_index[school_id] = {}
            self.evaluate_02_index[school_id][major_id] = {
                'level': str(row['level']),
                'evaluate_score': float(row['evaluate_score'])
            }

        # 构建特色专业索引：{school_id: {major_id: True}}
        self.special_index = {}
        for _, row in self.data_special.iterrows():
            school_id = str(row['school_id'])
            major_id = str(row['major_id'])

            if school_id not in self.special_index:
                self.special_index[school_id] = {}
            self.special_index[school_id][major_id] = True

        # 构建学位数据索引：{school_id: {major_id: row_data}}
        self.degree_index = {}
        for _, row in self.data_degree.iterrows():
            school_id = str(row['school_id'])
            major_id = str(row['major_id'])

            if school_id not in self.degree_index:
                self.degree_index[school_id] = {}
            self.degree_index[school_id][major_id] = {
                'degree': str(row['degree']),
                'score': float(row['score'])
            }

    def lookup_evaluate_data(self, school_id: str, major_id: str, submajor_id: str = None) -> Optional[Dict]:
        """快速查找本科专业评估数据"""
        if self.evaluate_index is None:
            return None

        school_data = self.evaluate_index.get(school_id, {})

        # 优先查找major_id，如果没有则查找submajor_id
        if major_id in school_data:
            return school_data[major_id]
        elif submajor_id and submajor_id in school_data:
            return school_data[submajor_id]

        return None

    def lookup_evaluate_02_data(self, school_id: str, major_id: str, submajor_id: str = None) -> Optional[Dict]:
        """快速查找专科专业评估数据"""
        if self.evaluate_02_index is None:
            return None

        school_data = self.evaluate_02_index.get(school_id, {})

        # 优先查找major_id，如果没有则查找submajor_id
        if major_id in school_data:
            return school_data[major_id]
        elif submajor_id and submajor_id in school_data:
            return school_data[submajor_id]

        return None

    def lookup_special_data(self, school_id: str, major_id: str, submajor_id: str = None) -> bool:
        """快速查找特色专业数据"""
        if self.special_index is None:
            return False

        school_data = self.special_index.get(school_id, {})

        # 检查major_id或submajor_id是否为特色专业
        return (major_id in school_data) or (submajor_id and submajor_id in school_data)

    def lookup_degree_data(self, school_id: str, major_id: str, submajor_id: str = None) -> Optional[Dict]:
        """快速查找学位数据"""
        if self.degree_index is None:
            return None

        school_data = self.degree_index.get(school_id, {})

        # 优先查找major_id，如果没有则查找submajor_id
        if major_id in school_data:
            return school_data[major_id]
        elif submajor_id and submajor_id in school_data:
            return school_data[submajor_id]

        return None


# 全局数据加载器实例
data_loader = DataLoader()


def get_data_loader() -> DataLoader:
    """获取数据加载器实例"""
    return data_loader


def initialize_data():
    """初始化数据加载器"""
    data_loader.load_all_data()
