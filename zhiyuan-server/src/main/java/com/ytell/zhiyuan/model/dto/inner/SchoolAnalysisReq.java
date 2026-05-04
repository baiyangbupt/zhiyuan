package com.ytell.zhiyuan.model.dto.inner;


import lombok.Data;

import java.util.List;

@Data
public class SchoolAnalysisReq {

    List<SchoolItem> schoolItemList;

    @Data
    public static class SchoolItem{
        private String id;
        private String name;

    }
}
