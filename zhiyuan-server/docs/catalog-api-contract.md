# Catalog 接口协议

## 1. 目标

本文档定义 backend 作为统一主数据语义源时，对 `agent / rank / frontend` 暴露的 `catalog` 内网接口协议。

目标：

- 固定“名称 -> 统一主键 / 标准标签域”的查询协议
- 固定“树形枚举 / 筛选树”的返回协议
- 固定“唯一命中 / 多候选 / 无结果”的状态语义
- 固定 `catalogVersion` 的版本透传方式

本文档不要求当前立刻改动各模块的本地文件加载点。

与静态生成物配套协议见：

- [catalog-build-contract.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-build-contract.md)

backend 侧实现拆解见：

- [catalog-implementation-design.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-implementation-design.md)

## 2. 总体约束

### 2.1 基础路径

统一建议挂在：

- `/gaotu-assistant-bot/inner/catalog/...`

### 2.2 主键约束

运行时只允许以下字段作为统一主键：

- `schoolId`
- `majorId`
- `categoryId`
- `subCategoryId`
- `provinceCode`
- `cityCode`

以下字段仅允许作为展示/导出 code：

- `schoolUnitCode`
- `majorUnitCode`

### 2.3 通用返回包装

所有 `catalog` 接口建议统一返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {}
}
```

字段定义：

- `catalogVersion`
  - 当前主数据版本
- `schemaVersion`
  - 接口协议版本
- `resultType`
  - `exact`
  - `multi`
  - `empty`
- `data`
  - 单对象、对象数组或树结构

### 2.4 错误与空结果语义

- 参数非法：返回 4xx
- 参数合法但无命中：`200 + resultType=empty + data=null/[]`
- 参数合法但多命中：`200 + resultType=multi + data=[...]`
- 参数合法且唯一命中：`200 + resultType=exact + data={...}`

禁止：

- 用“模糊命中某个候选”冒充唯一结果
- 在无结果时自动降级到别的层级
- 返回仅有展示 code、没有统一主键的对象

## 3. lookup 接口

lookup 用于“我已经有一个明确名称，希望映射到统一主键”。

### 3.1 学校

`GET /gaotu-assistant-bot/inner/catalog/lookup/school?name=北京大学`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {
    "schoolId": "1",
    "schoolName": "北京大学",
    "schoolUnitCode": "10001",
    "provinceCode": "110000",
    "provinceName": "北京",
    "cityCode": "110108",
    "cityName": "海淀"
  }
}
```

### 3.2 具体专业

`GET /gaotu-assistant-bot/inner/catalog/lookup/major?name=计算机科学与技术&educationLevel=本科`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {
    "majorId": "574",
    "majorName": "计算机科学与技术",
    "majorUnitCode": "080901",
    "subCategoryId": "39",
    "subCategoryName": "计算机类",
    "categoryId": "7",
    "categoryName": "工学",
    "educationLevel": "本科"
  }
}
```

### 3.3 专业大类

`GET /gaotu-assistant-bot/inner/catalog/lookup/major-category?name=计算机类&educationLevel=本科`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {
    "subCategoryId": "39",
    "subCategoryName": "计算机类",
    "categoryId": "7",
    "categoryName": "工学",
    "educationLevel": "本科"
  }
}
```

### 3.4 专业门类

`GET /gaotu-assistant-bot/inner/catalog/lookup/major-discipline?name=工学&educationLevel=本科`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {
    "categoryId": "7",
    "categoryName": "工学",
    "educationLevel": "本科"
  }
}
```

### 3.5 省份

`GET /gaotu-assistant-bot/inner/catalog/lookup/province?name=北京`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {
    "provinceCode": "110000",
    "provinceName": "北京"
  }
}
```

### 3.6 城市

`GET /gaotu-assistant-bot/inner/catalog/lookup/city?name=海淀`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {
    "cityCode": "110108",
    "cityName": "海淀",
    "provinceCode": "110000",
    "provinceName": "北京"
  }
}
```

## 4. search 接口

search 用于“我只有关键词，需要拿候选列表，不做唯一判定”。

### 4.1 学校

`GET /gaotu-assistant-bot/inner/catalog/search/school?keyword=北京`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "multi",
  "data": [
    {
      "matchType": "exact",
      "schoolId": "1",
      "schoolName": "北京大学"
    },
    {
      "matchType": "fuzzy",
      "schoolId": "12",
      "schoolName": "北京工业大学"
    }
  ]
}
```

### 4.2 专业

`GET /gaotu-assistant-bot/inner/catalog/search/major?keyword=计算机&educationLevel=本科`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "multi",
  "data": [
    {
      "matchType": "fuzzy",
      "majorId": "574",
      "majorName": "计算机科学与技术",
      "subCategoryId": "39",
      "subCategoryName": "计算机类",
      "categoryId": "7",
      "categoryName": "工学"
    }
  ]
}
```

约束：

- search 的元素必须带统一主键
- 必须带 `matchType`
- `matchType` 建议固定：
  - `exact`
  - `alias`
  - `fuzzy`

## 5. tree 接口

tree 用于前端筛选、agent 展示和本地生成物对齐。

### 5.1 专业树

`GET /gaotu-assistant-bot/inner/catalog/tree/major?educationLevel=本科`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": [
    {
      "categoryId": "7",
      "categoryName": "工学",
      "children": [
        {
          "subCategoryId": "39",
          "subCategoryName": "计算机类"
        }
      ]
    }
  ]
}
```

### 5.2 地域树

`GET /gaotu-assistant-bot/inner/catalog/tree/region`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": [
    {
      "provinceCode": "110000",
      "provinceName": "北京",
      "children": [
        {
          "cityCode": "110108",
          "cityName": "海淀"
        }
      ]
    }
  ]
}
```

### 5.3 统一筛选标签树

`GET /gaotu-assistant-bot/inner/catalog/tree/filter-tags`

返回：

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "resultType": "exact",
  "data": {
    "school": {
      "category": [],
      "nature": [],
      "feature": [],
      "level": []
    },
    "major": {
      "discipline": ["工学"],
      "category": [
        {
          "categoryId": "7",
          "categoryName": "工学",
          "children": [
            {
              "subCategoryId": "39",
              "subCategoryName": "计算机类"
            }
          ]
        }
      ]
    },
    "admission": {
      "type": ["普通类"]
    },
    "constraint": {
      "limit": ["语种要求"]
    }
  }
}
```

## 6. 与现有接口的关系

当前 backend 已有部分内网接口可复用：

- 学校
  - `/inner/school/id`
  - `/inner/school/name`
  - `/inner/school/search/name`
  - `/inner/school/getSchoolProfileByName`
- 专业
  - `/inner/major/getMajorInfo`
  - `/inner/major/getThirdLevelIdAndSecondLevelId`
  - `/inner/major/getMajorProfile`
  - `/inner/major-category/getMajorCategoryProfile`
- 地域
  - `/inner/province-city/...`
- 候选筛选树
  - `/inner/planning/{tenantId}/session/candidate-pool/filter-options`

但这些接口当前还存在三个问题：

1. 命名不统一
2. 返回结构不统一
3. 没有统一的 `catalogVersion / resultType / matchType`

因此 `catalog` 接口层的目标不是推翻现有实现，而是对这些能力做统一封装。

## 7. 消费方接入建议

agent：

- `code_enrichment`
- `student_info_mappings`
- 对话抽取后的名称补码

rank：

- 启动前校验输入字典与 `catalogVersion`
- 明确 `majorId=0` 的兼容样本粒度

frontend：

- 专业筛选树
- 地域筛选树
- 标签筛选枚举

## 8. 非目标

当前不在本阶段处理：

- 各模块本地文件的立即替换
- rank 内部全部历史标签字典的重构
- frontend 展示文案层优化
