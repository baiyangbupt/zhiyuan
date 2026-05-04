# Catalog 生成物协议

## 1. 目标

本文档定义统一主数据生成链路 `catalog build` 的产物协议。

目标：

- 固定各消费方生成物的文件命名与目录结构
- 固定 `meta` 元数据字段
- 固定 agent / rank / frontend 各自消费的最小 schema
- 固定版本同步和 CI 校验规则

本文档与 [catalog-api-contract.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-api-contract.md) 分工如下：

- `catalog-api-contract`
  - 解决运行时映射和树查询
- `catalog-build-contract`
  - 解决本地静态副本如何统一生成和发布

统一治理总文档见：

- [entity-catalog-governance.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/entity-catalog-governance.md)

backend 侧实现拆解见：

- [catalog-implementation-design.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-implementation-design.md)

## 2. 输入源

`catalog build` 的唯一输入源来自 backend 当前主数据：

- `src/main/resources/bizdata/major_bachelor.json`
- `src/main/resources/bizdata/major_associate.json`
- `src/main/resources/bizdata/school_info.csv`
- `src/main/resources/bizdata/province_city.json`
- `src/main/resources/bizdata/major_extra_data.csv`

约束：

- 不允许从 agent / rank / frontend 的本地副本反向生成
- 不允许多个模块分别拥有独立的“生成源”

## 3. 产物目录约定

建议统一构建输出到一个中间产物目录，例如：

- `build/catalog/`

按消费方拆子目录：

- `build/catalog/common/`
- `build/catalog/agent/`
- `build/catalog/rank/`
- `build/catalog/frontend/`

示例：

```text
build/catalog/
  common/
    catalog_meta.json
    catalog_province_city.json
  agent/
    catalog_major_bachelor.json
    catalog_major_associate.json
    catalog_school_bachelor.csv
    catalog_school_associate.csv
  rank/
    catalog_rank_major.xlsx
    catalog_rank_school.xlsx
    catalog_rank_major_02.xlsx
    catalog_rank_school_02.xlsx
  frontend/
    catalog_frontend_major_tree.json
    catalog_frontend_region_tree.json
    catalog_frontend_filter_tags.json
```

## 4. 元数据协议

所有生成物必须带统一元数据。

### 4.1 通用元数据文件

`build/catalog/common/catalog_meta.json`

```json
{
  "catalogVersion": "2026.04.24.1",
  "schemaVersion": "1.0",
  "generatedAt": "2026-04-24T12:00:00+08:00",
  "sourceCommit": "backend-git-sha",
  "sourceFiles": [
    "major_bachelor.json",
    "major_associate.json",
    "school_info.csv",
    "province_city.json",
    "major_extra_data.csv"
  ]
}
```

### 4.2 嵌入式元数据

对于 JSON 生成物，建议直接内嵌：

```json
{
  "meta": {
    "catalogVersion": "2026.04.24.1",
    "schemaVersion": "1.0"
  },
  "data": []
}
```

对于 CSV/XLSX：

- 至少要求与 `catalog_meta.json` 同版本发布
- 后续若格式允许，可额外写入隐藏 sheet / 注释元数据

## 5. agent 生成物协议

### 5.1 专业树

文件：

- `build/catalog/agent/catalog_major_bachelor.json`
- `build/catalog/agent/catalog_major_associate.json`

schema：

```json
{
  "meta": {},
  "data": [
    {
      "id": "categoryId",
      "label": "工学",
      "children": [
        {
          "id": "subCategoryId",
          "label": "计算机类",
          "children": [
            {
              "id": "majorId",
              "label": "计算机科学与技术",
              "majorCode": "080901"
            }
          ]
        }
      ]
    }
  ]
}
```

约束：

- 一级节点 `id = categoryId`
- 二级节点 `id = subCategoryId`
- 三级节点 `id = majorId`
- `majorCode` 可以保留，但仅作为展示 code

### 5.2 院校表

文件：

- `build/catalog/agent/catalog_school_bachelor.csv`
- `build/catalog/agent/catalog_school_associate.csv`

列名固定：

```csv
标准院校id,标准院校名称,院校省份,院校城市,学校隶属,学校类型,学校标签,公办民办,本科专科
```

约束：

- `标准院校id -> schoolId`
- 不新增与 backend 主语义冲突的别名列

### 5.3 省市树

文件：

- `build/catalog/common/catalog_province_city.json`

约束：

- agent 和 frontend 统一消费同一份地域生成物

## 6. rank 生成物协议

### 6.1 学校字典

文件：

- `build/catalog/rank/catalog_rank_school.xlsx`
- `build/catalog/rank/catalog_rank_school_02.xlsx`

最小字段：

- `schoolId`
- `schoolName`
- `provinceCode`
- `cityCode`
- `schoolCategory`
- `schoolNature`
- `educationLevel`

### 6.2 专业字典

文件：

- `build/catalog/rank/catalog_rank_major.xlsx`
- `build/catalog/rank/catalog_rank_major_02.xlsx`

最小字段：

- `majorId`
- `majorName`
- `subCategoryId`
- `subCategoryName`
- `categoryId`
- `categoryName`
- `educationLevel`
- `granularity`

`granularity` 约束：

- `major`
  - 正常三级专业
- `category`
  - 历史兼容样本，`majorId=0`

要求：

- 后续 rank 启动时必须检查 `majorId=0` 的样本是否显式标注了 `granularity=category`

## 7. frontend 生成物协议

### 7.1 专业筛选树

文件：

- `build/catalog/frontend/catalog_frontend_major_tree.json`

schema：

```json
{
  "meta": {},
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

### 7.2 地域筛选树

文件：

- `build/catalog/frontend/catalog_frontend_region_tree.json`

schema：

```json
{
  "meta": {},
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

### 7.3 统一标签枚举

文件：

- `build/catalog/frontend/catalog_frontend_filter_tags.json`

schema：

```json
{
  "meta": {},
  "data": {
    "school": {
      "category": [],
      "nature": [],
      "feature": [],
      "level": []
    },
    "major": {
      "discipline": [],
      "category": []
    },
    "admission": {
      "type": []
    },
    "constraint": {
      "limit": []
    }
  }
}
```

## 8. 同步与发布规则

最小流程：

1. backend 主数据更新
2. 触发 `catalog build`
3. 产出版本化生成物
4. 各消费方仓库同步对应目录中的文件
5. CI 比对消费方本地副本与 `catalogVersion`

建议同步方式：

- 单独发布物仓库
- 或 monorepo 下统一脚本同步
- 或 CI 产物下载后写回各仓

不要求当前就决定具体同步工具，但必须固定：

- 同步来源唯一
- 版本号唯一
- 可追溯到 backend `sourceCommit`

## 9. 校验规则

### 9.1 结构校验

- 文件是否存在
- JSON/CSV/XLSX 是否能正常解析
- 必填列/字段是否齐全

### 9.2 主键校验

- `schoolId` 唯一
- `categoryId/subCategoryId/majorId` 层级关系闭合
- `provinceCode/cityCode` 能互相映射

### 9.3 语义校验

- agent 专业树：
  - 一级一定是 `categoryId`
  - 二级一定是 `subCategoryId`
  - 三级一定是 `majorId`
- frontend 专业树：
  - 只能展示 `discipline -> category`
- rank 字典：
  - `majorId=0` 必须显式为 `granularity=category`

### 9.4 版本校验

- 所有消费方生成物必须能关联到同一份 `catalog_meta.json`
- 若发现 `catalogVersion` 不一致，CI 直接失败

## 10. 非目标

当前不在本协议中处理：

- 各消费方运行时代码如何读取这些文件
- rank 内部所有旧字典的字段重构
- frontend 展示文案和 UI 排布
