package com.ytell.zhiyuan.common.config;

import lombok.Data;
import org.springframework.stereotype.Component;

/**
 * 志愿分析配置
 */
@Data
@Component
public class VolunteerAnalysisConfig {
    
    /**
     * 冲刺区间最大志愿数量
     */
    private int sprintMaxCount = 5;
    
    /**
     * 稳妥区间最大志愿数量
     */
    private int safeMaxCount = 5;
    
    /**
     * 保底区间最大志愿数量
     */
    private int protectMaxCount = 5;
    
    /**
     * 是否启用截取功能
     */
    private boolean enableTruncation = true;
}
