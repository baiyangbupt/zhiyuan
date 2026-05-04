# PlanQueryTool SQL查询指南

## 概述

`PlanQueryTool` 提供了强大的SQL查询功能，可以使用标准SQL语法查询打平后的方案数据。

## 安装依赖

```bash
pip install duckdb>=0.9.0
```

## 使用方法

### 1. 基本流程

```python
from tools.plan_query_tool import PlanQueryTool

# 创建工具实例
tool = PlanQueryTool()

# 读取并打平数据
plan_content = await tool.get_plan_content(chat_session_id)
flattened_data = tool.flatten_plan_content(plan_content)

# 使用SQL查询
results = tool.query_plan_content(flattened_data, "SELECT * FROM plan_data WHERE school_name = '三峡大学'")
```

### 2. 数据结构

打平后的数据包含以下主要字段：

#### 学校字段
- `school_name` - 学校名称
- `school_rank` - 学校排名
- `city_name` - 城市名称
- `province_name` - 省份名称
- `level` - 学校层次（PROTECT/SAFE等）

#### 专业字段
- `major_name` - 专业名称
- `major_level` - 专业层次
- `major_enroll_ratio` - 专业录取率
- `planNum` - 计划招生人数
- `planMoney` - 学费
- `must_subject` - 必选科目（数组）

#### 历史分数字段（按年份）
- `score_2025`, `score_2024`, `score_2023` - 各年分数
- `pos_2025`, `pos_2024`, `pos_2023` - 各年位次
- `enrollNum_2025`, `enrollNum_2024`, `enrollNum_2023` - 各年录取人数
- `planNum_2025`, `planNum_2024`, `planNum_2023` - 各年计划人数

## SQL查询示例

### 示例1：基础查询

查询所有数据：
```sql
SELECT school_name, major_name, major_level, planNum FROM plan_data
```

### 示例2：条件查询

查询特定学校：
```sql
SELECT * FROM plan_data WHERE school_name = '三峡大学'
```

查询特定省份：
```sql
SELECT * FROM plan_data WHERE province_name = '湖北'
```

### 示例3：模糊查询

查询包含"电气"的专业：
```sql
SELECT school_name, major_name FROM plan_data WHERE major_name LIKE '%电气%'
```

### 示例4：分数范围查询

查询2025年分数在600分以上的专业：
```sql
SELECT school_name, major_name, score_2025, pos_2025 
FROM plan_data 
WHERE score_2025 >= 600 
ORDER BY score_2025 DESC
```

查询分数在590-610之间的：
```sql
SELECT school_name, major_name, score_2025 
FROM plan_data 
WHERE score_2025 BETWEEN 590 AND 610
```

### 示例5：多条件组合

查询江苏省且分数>=605的专业：
```sql
SELECT school_name, city_name, major_name, score_2025 
FROM plan_data 
WHERE province_name = '江苏' AND score_2025 >= 605
```

查询SAFE层次且计划数>=10的：
```sql
SELECT school_name, major_name, major_level, planNum 
FROM plan_data 
WHERE major_level = 'SAFE' AND planNum >= 10
```

### 示例6：排序查询

按分数降序排列：
```sql
SELECT school_name, major_name, score_2025 
FROM plan_data 
ORDER BY score_2025 DESC
```

获取前N条：
```sql
SELECT school_name, major_name, score_2025 
FROM plan_data 
ORDER BY score_2025 DESC 
LIMIT 10
```

### 示例7：聚合查询

统计各省份的专业数量：
```sql
SELECT province_name, COUNT(*) as count 
FROM plan_data 
GROUP BY province_name 
ORDER BY count DESC
```

计算平均分数：
```sql
SELECT province_name, AVG(score_2025) as avg_score 
FROM plan_data 
GROUP BY province_name
```

统计计划数：
```sql
SELECT 
    SUM(planNum) as total,
    AVG(planNum) as avg,
    MAX(planNum) as max,
    MIN(planNum) as min 
FROM plan_data
```

### 示例8：分组过滤

查询专业数量>=2的省份：
```sql
SELECT province_name, COUNT(*) as count 
FROM plan_data 
GROUP BY province_name 
HAVING count >= 2
```

### 示例9：多年分数对比

查询分数逐年上升的专业：
```sql
SELECT school_name, major_name, score_2023, score_2024, score_2025 
FROM plan_data 
WHERE score_2025 > score_2024 AND score_2024 > score_2023
```

### 示例10：IN查询

查询多个指定省份：
```sql
SELECT school_name, province_name, major_name 
FROM plan_data 
WHERE province_name IN ('湖北', '江苏', '江西')
```

### 示例11：复杂统计

按学校层次统计平均分和专业数：
```sql
SELECT 
    level,
    COUNT(*) as major_count,
    AVG(score_2025) as avg_score,
    MIN(score_2025) as min_score,
    MAX(score_2025) as max_score
FROM plan_data 
GROUP BY level
ORDER BY avg_score DESC
```

## 高级用法

### 1. 子查询

查询分数高于平均分的专业：
```sql
SELECT school_name, major_name, score_2025 
FROM plan_data 
WHERE score_2025 > (SELECT AVG(score_2025) FROM plan_data)
```

### 2. CASE表达式

根据分数分级：
```sql
SELECT 
    school_name, 
    major_name, 
    score_2025,
    CASE 
        WHEN score_2025 >= 610 THEN '高分'
        WHEN score_2025 >= 600 THEN '中分'
        ELSE '低分'
    END as score_level
FROM plan_data
```

### 3. 字符串函数

提取专业关键词：
```sql
SELECT 
    school_name,
    major_name,
    SUBSTRING(major_name, 1, 4) as major_category
FROM plan_data
WHERE major_name LIKE '%工程%'
```

### 4. 排名查询

使用ROW_NUMBER：
```sql
SELECT 
    ROW_NUMBER() OVER (ORDER BY score_2025 DESC) as rank,
    school_name,
    major_name,
    score_2025
FROM plan_data
```

## 注意事项

1. **表名固定**：SQL中的表名必须使用 `plan_data`
2. **字段名区分大小写**：字段名需要精确匹配
3. **数组字段**：`must_subject` 是数组类型，查询时需要特殊处理
4. **NULL值处理**：某些字段可能为NULL，查询时注意处理
5. **性能**：DuckDB性能优秀，但对于超大数据集仍需注意优化

## 测试示例

运行测试查看更多示例：

```bash
python test_sql_query.py
```

## 技术说明

- 使用 **DuckDB** 作为查询引擎
- 支持完整的 SQL 标准语法
- 内存数据库，无需持久化
- 可以直接查询 Python 字典列表
- 高性能，适合中小规模数据集（百万级）

## 常见查询场景

| 场景 | SQL示例 |
|------|---------|
| 查找某学校所有专业 | `WHERE school_name = '学校名'` |
| 查找某专业所有学校 | `WHERE major_name LIKE '%专业名%'` |
| 按分数筛选 | `WHERE score_2025 >= 600` |
| 按省份筛选 | `WHERE province_name = '省份'` |
| 按计划数筛选 | `WHERE planNum >= 10` |
| 统计各省份数量 | `GROUP BY province_name` |
| 分数排名 | `ORDER BY score_2025 DESC` |
| 前N名 | `LIMIT N` |

