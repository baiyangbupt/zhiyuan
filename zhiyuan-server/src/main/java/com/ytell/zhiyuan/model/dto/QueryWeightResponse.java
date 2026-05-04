package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.util.List;

@Data
public class QueryWeightResponse {
    /**
     * 查询类型：major、school、schoolmajor
     */
    private String type;
    
    /**
     * 学校相关权重（school和schoolmajor类型时使用）
     */
    private Double province_gdp;
    private Double city_level;
    private Double upgrade_ratio;
    private Double postgraduate_recommend_ratio;
    private Double gaotu_rank;
    private Double level_score;
    
    /**
     * 专业相关权重（major和schoolmajor类型时使用）
     */
    private Double gender_index;
    private Double satisfy_index;
    private Double salary_avg;
    private Double hot_index;
    private String gender_flag;
    
    /**
     * 查询结果列表
     */
    private List<QueryResultItem> querylist;
    
    @Data
    public static class QueryResultItem {
        /**
         * 学校ID
         */
        private String school_id;
        
        /**
         * 学校名称
         */
        private String school_name;
        
        /**
         * 学校相关得分
         */
        private Double college_score;
        private Double college_score_new;
        private Double province_gdp;
        private Double city_level;
        private Double upgrade_ratio;
        private Double postgraduate_recommend_ratio;
        private Double gaotu_rank;
        private Double level_score;
        private String college_remark;
        
        /**
         * 专业相关得分
         */
        private Double major_score;
        private Double major_score_new;
        private Double major_score_final;
        private Double gender_index;
        private Double satisfy_index;
        private Double salary_avg;
        private Double hot_index;
        private String major_remark;
        private Double evaluate_score;
        private Double special_score;
        private Double degree_score;
        private String degree;
        private String major_level;
        private String remark_extra;
        private Double score_final;
        
        /**
         * 专业列表（schoolmajor类型时使用）
         */
        private List<MajorResultItem> majors;
        
        @Data
        public static class MajorResultItem {
            private String major_id;
            private String major_name;
            private Double major_score;
            private Double major_score_new;
            private Double major_score_final;
            private Double gender_index;
            private Double satisfy_index;
            private Double salary_avg;
            private Double hot_index;
            private String major_remark;
            private Double evaluate_score;
            private Double special_score;
            private Double degree_score;
            private String degree;
            private String major_level;
            private String remark_extra;
            private Double score_final;
        }
    }
}
