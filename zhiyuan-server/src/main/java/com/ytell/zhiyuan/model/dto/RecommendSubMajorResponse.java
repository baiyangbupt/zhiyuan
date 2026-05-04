package com.ytell.zhiyuan.model.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * 热门专业推荐响应数据结构
 */
@Data
public class RecommendSubMajorResponse {
    
    /**
     * 性别指数权重
     */
    @JsonProperty("gender_index")
    private Double genderIndex;
    
    /**
     * 专业满意度指数权重
     */
    @JsonProperty("satisfy_index")
    private Double satisfyIndex;
    
    /**
     * 平均薪酬指数权重
     */
    @JsonProperty("salary_avg")
    private Double salaryAvg;
    
    /**
     * 专业热度指数权重
     */
    @JsonProperty("hot_index")
    private Double hotIndex;
    
    /**
     * 推荐专业列表
     */
    private List<MajorRecommendItem> reconmandlist;
    
    @Data
    public static class MajorRecommendItem {
        
        /**
         * 专业ID
         */
        @JsonProperty("major_id")
        private String majorId;
        
        /**
         * 专业名称
         */
        @JsonProperty("major")
        private String major;
        
        /**
         * 专业推荐得分
         */
        @JsonProperty("score")
        private Double score;
        
        /**
         * 性别指数得分
         */
        @JsonProperty("gender_index")
        private Double genderIndex;
        
        /**
         * 专业满意度指数得分
         */
        @JsonProperty("satisfy_index")
        private Double satisfyIndex;
        
        /**
         * 平均薪酬指数得分
         */
        @JsonProperty("salary_avg")
        private Double salaryAvg;
        
        /**
         * 专业热度指数得分
         */
        @JsonProperty("hot_index")
        private Double hotIndex;
    }

}
