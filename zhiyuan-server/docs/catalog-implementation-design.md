# Catalog 实现设计

## 1. 目标

本文档把 [catalog-api-contract.md](/Users/baiyang/git/zhiyuan/gaotu-assistant-backend/docs/catalog-api-contract.md) 进一步细化到 backend 可开发粒度，明确：

- controller 如何拆
- DTO 如何定义
- service 如何编排
- 复用哪些现有 manager / controller 能力
- 第一阶段先实现哪些接口

当前仍以“先补统一能力层，不改其他模块加载点”为前提。

## 2. 实现分层

建议新增以下分层：

### 2.1 Controller

新增：

- `CatalogController`

路径：

- `/gaotu-assistant-bot/inner/catalog`

职责：

- 接收 lookup / search / tree 三类请求
- 统一返回 `catalogVersion / schemaVersion / resultType / data`
- 不直接拼装底层 manager 输出

### 2.2 Service

新增：

- `CatalogService`

职责：

- 统一封装语义层查询
- 调用现有 `SchoolManager / MajorMappingManager / MajorProfileManager / MajorCategoryProfileManager / ProvinceCityManager / PlanningStateService`
- 对外输出统一 DTO

### 2.3 DTO

建议新增 DTO 包：

- `model/dto/catalog/`

建议最小 DTO：

- `CatalogResponseDTO<T>`
- `CatalogResultTypeEnum`
- `CatalogMatchTypeEnum`
- `CatalogSchoolLookupDTO`
- `CatalogMajorLookupDTO`
- `CatalogMajorCategoryLookupDTO`
- `CatalogMajorDisciplineLookupDTO`
- `CatalogProvinceLookupDTO`
- `CatalogCityLookupDTO`
- `CatalogSchoolSearchItemDTO`
- `CatalogMajorSearchItemDTO`
- `CatalogMajorTreeNodeDTO`
- `CatalogRegionTreeNodeDTO`
- `CatalogFilterTagsTreeDTO`

## 3. DTO 设计

### 3.1 通用返回 DTO

```java
public class CatalogResponseDTO<T> {
    private String catalogVersion;
    private String schemaVersion;
    private String resultType; // exact / multi / empty
    private T data;
}
```

### 3.2 lookup DTO

学校：

```java
public class CatalogSchoolLookupDTO {
    private String schoolId;
    private String schoolName;
    private String schoolUnitCode;
    private String provinceCode;
    private String provinceName;
    private String cityCode;
    private String cityName;
}
```

具体专业：

```java
public class CatalogMajorLookupDTO {
    private String majorId;
    private String majorName;
    private String majorUnitCode;
    private String subCategoryId;
    private String subCategoryName;
    private String categoryId;
    private String categoryName;
    private String educationLevel;
}
```

专业大类：

```java
public class CatalogMajorCategoryLookupDTO {
    private String subCategoryId;
    private String subCategoryName;
    private String categoryId;
    private String categoryName;
    private String educationLevel;
}
```

专业门类：

```java
public class CatalogMajorDisciplineLookupDTO {
    private String categoryId;
    private String categoryName;
    private String educationLevel;
}
```

地域：

```java
public class CatalogProvinceLookupDTO {
    private String provinceCode;
    private String provinceName;
}

public class CatalogCityLookupDTO {
    private String cityCode;
    private String cityName;
    private String provinceCode;
    private String provinceName;
}
```

### 3.3 search DTO

```java
public class CatalogSchoolSearchItemDTO {
    private String matchType; // exact / alias / fuzzy
    private String schoolId;
    private String schoolName;
}

public class CatalogMajorSearchItemDTO {
    private String matchType;
    private String majorId;
    private String majorName;
    private String subCategoryId;
    private String subCategoryName;
    private String categoryId;
    private String categoryName;
    private String educationLevel;
}
```

### 3.4 tree DTO

```java
public class CatalogMajorTreeNodeDTO {
    private String categoryId;
    private String categoryName;
    private List<CatalogMajorCategoryNodeDTO> children;
}

public class CatalogMajorCategoryNodeDTO {
    private String subCategoryId;
    private String subCategoryName;
}
```

```java
public class CatalogRegionTreeNodeDTO {
    private String provinceCode;
    private String provinceName;
    private List<CatalogRegionCityNodeDTO> children;
}

public class CatalogRegionCityNodeDTO {
    private String cityCode;
    private String cityName;
}
```

## 4. 现有能力复用关系

### 4.1 学校

现有可复用：

- `SchoolManager`
  - `getSchoolById`
  - `getSchoolByName`
  - `searchSchoolsByName`
- `SchoolProfileManager`
  - 如需补画像字段

结论：

- `lookup/school` 直接复用 `SchoolManager`
- `search/school` 第一阶段直接复用 `searchSchoolsByName`

缺口：

- `SchoolVO` 当前没有 `schoolUnitCode`
- 若要符合接口协议，需要补充统一来源字段，或第一阶段先允许该字段为空

### 4.2 专业

现有可复用：

- `MajorMappingManager`
  - `getMajorInfo`
  - `getSecondLevelIdByThirdLevelId`
  - `getThirdLevelIdAndSecondLevelId`
  - `getFirstLevelIdByName`
  - `getSecondLevelIdByName`
- `MajorProfileManager`
  - `getMajorProfileById`
  - `getMajorProfileByName`
- `MajorCategoryProfileManager`
  - `getMajorCategoryProfile(name, id)`

结论：

- `lookup/major` 第一阶段主走 `MajorMappingManager`
- `lookup/major-category` 主走 `MajorMappingManager + MajorInfo`
- `lookup/major-discipline` 需要补一个“按一级门类名称查 categoryId”的 service 封装

缺口：

- `MajorMappingManager` 目前没有显式暴露“根据二级专业 ID 反查一级名称”和“根据一级专业名称精确返回一级节点对象”的统一 DTO
- 第一阶段建议先在 `CatalogService` 内部封装，不急着新增太多 manager 接口

### 4.3 地域

现有可复用：

- `ProvinceCityManager`
  - `getProvinceById`
  - `getProvinceByLabel`
  - `getCityById`
  - `getCityByLabel`
  - `getProvinceByCityId`
  - `getProvinceByCityLabel`
  - `getAllProvinces`

结论：

- `lookup/province`
- `lookup/city`
- `tree/region`
  第一阶段都可以直接复用

### 4.4 筛选树

现有可复用：

- `PlanningStateController`
  - `/session/candidate-pool/filter-options`

结论：

- `tree/filter-tags` 第一阶段不建议重写逻辑
- 建议由 `CatalogService` 统一封装并桥接现有 filter-options 返回
- 当前若直接面向统一主数据输出，`major.category` 建议直接返回“门类 -> 大类”树，避免消费方再次自行拼父子关系。

缺口：

- 当前 `candidate-pool/filter-options` 是“会话态 + 候选集相关”接口
- `catalog/tree/filter-tags` 应该是“统一主数据枚举”接口
- 两者短期可以桥接，但中期应拆开

## 5. Controller 设计

建议第一阶段只开放最小集合：

### Phase A

- `GET /lookup/school`
- `GET /lookup/major`
- `GET /lookup/major-category`
- `GET /lookup/province`
- `GET /lookup/city`
- `GET /search/school`
- `GET /search/major`
- `GET /tree/major`
- `GET /tree/region`

### Phase B

- `GET /lookup/major-discipline`
- `GET /tree/filter-tags`

原因：

- Phase A 先覆盖 agent 补码、对话抽取后映射、frontend 树形筛选
- Phase B 再处理更复杂的统一标签树

## 6. CatalogService 实现建议

建议统一写一个 `CatalogService`，内部包含以下方法：

- `lookupSchool(String name)`
- `lookupMajor(String name, String educationLevel)`
- `lookupMajorCategory(String name, String educationLevel)`
- `lookupMajorDiscipline(String name, String educationLevel)`
- `lookupProvince(String name)`
- `lookupCity(String name)`
- `searchSchools(String keyword)`
- `searchMajors(String keyword, String educationLevel)`
- `getMajorTree(String educationLevel)`
- `getRegionTree()`
- `getFilterTagsTree()`

统一由 service 决定：

- `resultType`
- 空结果
- 多候选
- `catalogVersion`

不建议把这部分判断散落在 controller 里。

## 7. catalogVersion 来源

第一阶段建议先由 backend 本地固定生成：

- 从配置项读取
- 或从 `catalog_meta.json` 读取
- 若尚未引入 `catalog build`，可先临时定义为 application property

建议新增配置：

- `catalog.version`
- `catalog.schema-version`

这样在接口尚未完全接入统一生成物之前，也能先把版本字段协议固定下来。

## 8. 第一阶段落地顺序

建议按以下顺序实现：

1. DTO
2. `CatalogService`
3. `CatalogController`
4. lookup 接口单测
5. search 接口单测
6. tree 接口单测

优先级最高的接口：

1. `lookup/major`
2. `lookup/school`
3. `lookup/province`
4. `lookup/city`
5. `tree/major`
6. `tree/region`

## 9. 非目标

当前不在这一轮实现设计中处理：

- 直接修改 agent/rank/frontend 的消费代码
- 直接替换各模块本地文件
- 立刻重构 `candidate-pool/filter-options`
