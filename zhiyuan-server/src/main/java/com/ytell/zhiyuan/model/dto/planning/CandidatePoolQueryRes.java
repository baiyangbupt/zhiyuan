package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CandidatePoolQueryRes {
    private List<CandidateItemDTO> items = Lists.newArrayList();
    private Integer page;
    private Integer pageSize;
    private Integer total;
    private Integer totalUnitCount;
    private Integer loadedEntryCount;
    private Integer loadedUnitCount;
    private ViewSummary viewSummary;

    @Data
    public static class ViewSummary {
        private Integer poolEntryTotal;
        private Integer poolUnitTotal;
        private Integer viewEntryTotal;
        private Integer viewUnitTotal;
        private Integer loadedEntryCount;
        private Integer loadedUnitCount;
    }
}
