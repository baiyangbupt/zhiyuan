package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_planning_data_freshness_schedule")
public class PlanningDataFreshnessScheduleEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long chatSessionId;
    private Long tenantId;
    private String prepareType;
    private String provinceCode;
    private String provinceName;
    private Integer examYear;
    private String sessionStatus;
    private Date sessionCreateTime;
    private Date lastAccessedAt;
    private Date lastCheckedAt;
    private Date nextCheckAt;
    private Integer checkIntervalMinutes;
    private String lastCheckSource;
    private String lastCheckStatus;
    private String sourceDataHash;
    private String latestSourceDataHash;
    private Integer failCount;
    private String lastError;
    private Date lastFailedAt;
    private Boolean enabled;
    private Date createTime;
    private Date updateTime;
}
