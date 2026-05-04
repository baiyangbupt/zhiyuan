package com.ytell.zhiyuan.model.vo;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.List;

@Data
public class ChatSessionExtraSummaryVo {
    private String infoSummary;
    private List<CollectProgressItem> collectProgress;

    @Data
    @AllArgsConstructor
    public static class CollectProgressItem {
        private String key;
        private int value;
    }
}
