package com.ytell.zhiyuan.model.dto.inner;

import io.swagger.annotations.ApiModel;
import lombok.Data;

import java.util.List;

@Data
@ApiModel("院校推荐列表响应")
public class SchoolRecommendResponse {
    private List<SchoolInfo> schoolList;

    @Data
    public static class SchoolInfo {
        private String schoolId;
        private String schoolName;
        private List<String> majorList;
    }
}
