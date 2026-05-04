package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.util.List;

@Data
public class QueryWeightDto {
    /**
     * 查询类型：major、school、schoolmajor
     */
    private String type;

    /**
     * 查询列表
     */
    private List<QueryItem> querylist;

    @Data
    public static class QueryItem {
        /**
         * 学校ID（school和schoolmajor类型时使用）
         */
        private String school_id;

        /**
         * 学校名称（school和schoolmajor类型时使用）
         */
        private String school_name;

        /**
         * 专业ID（major和schoolmajor类型时使用）
         */
        private String major_id;

        /**
         * 专业名称（major和schoolmajor类型时使用）
         */
        private String major_name;

        private Integer major_level = 3;

        /**
         * 专业列表（schoolmajor类型时使用）
         */
        private List<Item> majors;

        @Data
        public static class Item {
            private String major_id;
            private String major_name;
            private Integer major_level = 3;
        }
    }
}
