
# 高考志愿排序服务

一个基于Flask的高考志愿排序Web服务，提供志愿填报相关的排序和推荐功能。

## 项目结构

```
gaokao-volunteer-rank-service/
├── app.py              # Flask主应用文件
├── requirements.txt    # Python依赖包
└── README.md          # 项目说明文档
```

## 快速开始

### 1. 安装依赖

```bash
# 建议使用虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或者 venv\Scripts\activate  # Windows

# 安装依赖包
pip install -r requirements.txt
```

### 2. 运行服务

```bash
python app.py
```

服务启动后，默认运行在 `http://localhost:5001`

### 3. 测试接口

#### 测试接口
- **URL**: `GET /test`
- **说明**: 测试服务是否正常运行
- **响应示例**:
```json
{
    "status": "success",
    "message": "高考志愿排序服务运行正常",
    "timestamp": "2024-01-01 12:00:00",
    "service": "高考志愿排序服务",
    "version": "1.0.0"
}
```

#### 健康检查接口
- **URL**: `GET /health`
- **说明**: 服务健康状态检查
- **响应示例**:
```json
{
    "status": "healthy",
    "service": "高考志愿排序服务"
}
```

### 4. 运行单测

推荐使用项目内 Python 3.12 虚拟环境：

```bash
/Users/baiyang/git/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest tests.test_recommendation_mapping
```

## 开发环境

- Python 3.8+
- Flask 2.3.3
- 详细依赖请查看 `requirements.txt`

## 生产部署

使用gunicorn运行：

```bash
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

## API文档

### 响应格式

所有API响应都采用统一的JSON格式：

```json
{
    "status": "success|error",
    "message": "响应信息",
    "data": {}, // 可选，业务数据
    "timestamp": "2024-01-01 12:00:00" // 可选
}
```

## 贡献指南

1. Fork 本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request
