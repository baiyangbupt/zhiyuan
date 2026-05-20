#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高考志愿排序服务
Flask Web应用主文件
"""

import os

from flask import Flask, jsonify, request
from datetime import datetime
import logging
from services.recommendation import get_university_recommendations, get_major_recommendations, submajor_Recommand,volunteer_Recommand,weight_Query
from services.data_loader import initialize_data

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建Flask应用实例
app = Flask(__name__)

# 应用配置
app.config['JSON_AS_ASCII'] = False  # 支持中文字符
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True  # JSON格式化输出

# 在应用启动时初始化数据加载器
logger.info("开始初始化数据加载器...")
try:
    initialize_data()
    logger.info("数据加载器初始化完成")
except Exception as e:
    logger.error("数据加载器初始化失败: %s", str(e))
    logger.exception("详细错误堆栈:")
    raise


@app.route('/gaokao-volunteer-rank/recommend', methods=['GET'])
def recommend():
    """
    推荐接口 - 调用推荐业务逻辑
    """
    try:
        # 使用测试数据调用推荐逻辑
        test_score = 650
        test_preferences = ["理工类"]
        test_location = "北京"
        
        # 调用大学推荐
        recommendations = get_university_recommendations(
            student_score=test_score,
            preferences=test_preferences,
            location_preference=test_location,
            limit=3
        )
        
        response_data = {
            'status': 'success',
            'message': '高考志愿推荐服务运行正常',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'service': '高考志愿排序服务',
            'test_data': {
                'student_score': test_score,
                'preferences': test_preferences,
                'location_preference': test_location
            },
            'recommendations': recommendations
        }
        logger.info("推荐接口被调用，返回推荐结果")
        return jsonify(response_data), 200
    except Exception as e:
        logger.error("推荐接口错误: %s", str(e))
        logger.exception("详细错误堆栈:")
        return jsonify({
            'status': 'error',
            'message': '服务异常',
            'error': str(e)
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """
    健康检查接口
    """
    return jsonify({
        'status': 'healthy',
        'service': '高考志愿排序服务'
    }), 200


@app.errorhandler(404)
def not_found(error):
    """404错误处理"""
    return jsonify({
        'status': 'error',
        'message': '接口不存在',
        'error': 'Not Found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """500错误处理"""
    return jsonify({
        'status': 'error',
        'message': '服务器内部错误',
        'error': 'Internal Server Error'
    }), 500


@app.route('/gaokao-volunteer-rank/recommend_submajor', methods=['POST'])
def recommend_submajor():
    """
    推荐专业大类接口
    """
    try:
        logger.info("submajor_Recommand推荐开始调用")
        # 1. 从请求体中获取 JSON 数据
        json_data = request.get_json()
        logger.info("submajor_Recommand推荐请求体: %s", json_data)
        if not json_data:
            return jsonify({
                'status': 'error',
                'message': '请求体为空或非 JSON 格式'
            }), 400

        # 2. 提取 studentinfo、topN
        studentinfo = json_data.get('studentinfo')
        topN = json_data.get('topN')
        if not studentinfo:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: studentinfo'
            }), 400
        elif not topN:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: topN'
            }), 400
        # 3. 调用专业大类推荐
        response_data = submajor_Recommand(studentinfo=studentinfo,topN=int(topN))
        logger.info("submajor_Recommand推荐接口被调用，返回推荐结果")
        return jsonify(response_data), 200
    except Exception as e:
        logger.error("submajor_Recommand推荐接口错误: %s", str(e))
        logger.exception("详细错误堆栈:")
        return jsonify({
            'status': 'error',
            'message': '服务异常',
            'error': str(e)
        }), 500

@app.route('/gaokao-volunteer-rank/recommend_volunteer', methods=['POST'])
def recommend_volunteer():
    """
    推荐志愿接口
    """
    try:
        # 1. 从请求体中获取 JSON 数据
        json_data = request.get_json()
        logger.info("volunteer_Recommand推荐开始调用")
        if not json_data:
            return jsonify({
                'status': 'error',
                'message': '请求体为空或非 JSON 格式'
            }), 400

        # 2. 提取 studentinfo, volunteerinfo, profileinfo
        studentinfo = json_data.get('studentinfo')
        volunteerinfo = json_data.get('volunteerinfo')
        profileinfo = json_data.get('profileinfo')
        if not studentinfo:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: studentinfo'
            }), 400
        elif not volunteerinfo:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: volunteerinfo'
            }), 400
        elif not profileinfo:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: profileinfo'
            }), 400

        # 3. 调用志愿推荐
        response_data = volunteer_Recommand(studentinfo=studentinfo,volunteerinfo=volunteerinfo,profileinfo=profileinfo)
        logger.info("volunteer_Recommand推荐接口被调用，返回推荐结果")
        return jsonify(response_data), 200
    except Exception as e:
        logger.error("volunteer_Recommand推荐接口错误: %s", str(e))
        logger.exception("详细错误堆栈:")
        return jsonify({
            'status': 'error',
            'message': '服务异常',
            'error': str(e)
        }), 500

@app.route('/gaokao-volunteer-rank/query_weight', methods=['POST'])
def query_weight():
    """
    查询专业、院校权重得分功能接口
    """
    try:
        # 1. 从请求体中获取 JSON 数据
        json_data = request.get_json()
        logger.info("查询权重得分功能开始调用")
        if not json_data:
            return jsonify({
                'status': 'error',
                'message': '请求体为空或非 JSON 格式'
            }), 400

        # 2. 提取 studentinfo, queryinfo, profileinfo
        studentinfo = json_data.get('studentinfo')
        queryinfo = json_data.get('queryinfo')
        profileinfo = json_data.get('profileinfo')
        if not studentinfo:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: studentinfo'
            }), 400
        elif not queryinfo:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: queryinfo'
            }), 400
        elif not profileinfo:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: profileinfo'
            }), 400

        # 3. 调用对比功能
        response_data = weight_Query(studentinfo=studentinfo,queryinfo=queryinfo,profileinfo=profileinfo)
        logger.info("weight_Query接口被调用，返回对比结果")
        return jsonify(response_data), 200
    except Exception as e:
        logger.error("weight_Query接口错误: %s", str(e))
        logger.exception("详细错误堆栈:")
        return jsonify({
            'status': 'error',
            'message': '服务异常',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    logger.info("启动高考志愿排序服务...")
    bind_host = os.getenv('RANK_BIND_HOST', '127.0.0.1')
    bind_port = int(os.getenv('RANK_BIND_PORT', '5001'))
    app.run(
        host=bind_host,
        port=bind_port,
        debug=True
    )
