package com.ytell.zhiyuan.model.dto.inner;


import lombok.Data;

import java.util.List;

@Data
public class MajorAnalysisReq {

    List<MajorItem> majorItemList;

    @Data
    public static class MajorItem {
        private String id;
        private String name;
        private Integer level;
    }
}
