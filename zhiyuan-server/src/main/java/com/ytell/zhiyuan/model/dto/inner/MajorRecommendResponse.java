package com.ytell.zhiyuan.model.dto.inner;

import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import io.swagger.annotations.ApiModel;
import lombok.Data;

import java.util.List;

@Data
@ApiModel("专业推荐列表响应")
public class MajorRecommendResponse {
    List<RecommendSubMajorResponse.MajorRecommendItem>  majorList;
}
