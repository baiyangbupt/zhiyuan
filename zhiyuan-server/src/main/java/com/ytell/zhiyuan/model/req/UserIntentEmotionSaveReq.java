package com.ytell.zhiyuan.model.req;

import lombok.Data;

import java.util.List;

/**
 * 用户意向情绪全量保存请求
 */
@Data
public class UserIntentEmotionSaveReq {

    /**
     * 会话ID
     */
    private Long chatSessionId;

    /**
     * 情绪条目列表
     */
    private List<IntentEmotionItem> intents;

    @Data
    public static class IntentEmotionItem {
        /**
         * 维度编码
         */
        private String dimension;
        /**
         * 正负向，取值：POSITIVE/NEGATIVE
         */
        private String polarity;
        /**
         * 展示名称
         */
        private String label;
        /**
         * 对应编码（可为空）
         */
        private String code;
        /**
         * 情绪值，取值参考 UserIntentEmotionLevel
         */
        private String emotion;

        /**
         * 是否删除该意向（true 表示删除，忽略 emotion）
         */
        private Boolean deleted;

        /**
         * 是否删除该正/负向维度下所有意向
         */
        private Boolean deleteAll;
    }
}

