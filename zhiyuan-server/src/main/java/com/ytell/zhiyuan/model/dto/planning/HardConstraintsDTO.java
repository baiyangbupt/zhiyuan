package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class HardConstraintsDTO {
    private List<String> mustIncludeRegions = Lists.newArrayList();
    private List<String> mustExcludeRegions = Lists.newArrayList();
    // 区域 ID（与名字并列 ✓）。两边都有 ID 时**以 ID 为准** ✓（权威身份 ✓）；
    // 任一边没有就回退名字 ✓（"名字只用于解析、解析结果落成 ID 再取数"在这层的落地 ✓）。
    private List<String> mustIncludeRegionIds = Lists.newArrayList();
    private List<String> mustExcludeRegionIds = Lists.newArrayList();
    private List<String> mustIncludeMajors = Lists.newArrayList();
    private List<String> mustExcludeMajors = Lists.newArrayList();
    // 专业 ID（与名字并列 ✓，规矩同区域 ID ✓）：两边都有 ID 时**以 ID 为准** ✓。
    // 候选 `majorId` 与目录 (`/catalog/lookup/major`) 的 `majorId` **同一套词汇表** ✓
    // （2026-09-26 真栈核对：临床医学 `774` ✓、低空技术与工程 `15223549801738240` ✓）。
    // `"0"`＝大类/试验班（没有单一专业身份 ✗）→ 按"缺 ID"处理 ✓，回退名字 ✓、不判死 ✗。
    private List<String> mustIncludeMajorIds = Lists.newArrayList();
    private List<String> mustExcludeMajorIds = Lists.newArrayList();
    private List<String> mustIncludeSchools = Lists.newArrayList();
    private List<String> mustExcludeSchools = Lists.newArrayList();
}
