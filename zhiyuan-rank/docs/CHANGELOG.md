# Changelog

## Unreleased

### Added

- 补充 rank 侧主数据/编码治理说明，明确 rank 当前仅消费统一化后的 `schoolId / majorId / categoryId / subCategoryId / province_code / city_code`；其内部 `xlsx/json` 字典和 `tag_major*.json` 仍属于打分实现细节，不再被视为对外统一主数据。
- 新增 rank 标签映射文档，明确 `tag_info / negative_tag_info`、院校原始属性、`subCategoryId` 与统一标签体系的边界，约束由 backend 作为唯一对外映射层。
- `tag-mapping.md` 补充 rank 侧后续统一接入方式：当前不改本地 `dict/` 加载方式，后续通过统一生成链路同步 rank 专用字典，并补 `majorId=0 / 非法 subCategoryId / schoolId 缺失` 的启动与 CI 校验。
- 新增 rank 单测，覆盖 `subCategoryId -> major.category` 命中 `tag_major`、`majorId=0` 的专业大类志愿兼容计算，以及院校 `category` 命中 `tag_info` 的院校侧加分逻辑。
- 扩充 rank 单测，补齐省市正负向意向、城市优先于省份的打分顺序、院校 `nature/tag/postgraduate` 命中历史标签时的加减分行为，作为 backend 到 rank 旧结构透传的回归保护。
