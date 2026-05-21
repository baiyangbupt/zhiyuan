package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_planning_behavior_event")
public class PlanningBehaviorEventEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String eventId;
    private Long chatSessionId;
    private Long tenantId;
    private String eventType;
    private String mode;
    private Integer planVersion;
    private String generationMode;
    private String volunteerIdsJson;
    private String unitIdsJson;
    private String fromPositionsJson;
    private String toPositionsJson;
    private String tier;
    private Double admissionRatio;
    private String schoolName;
    private String majorName;
    private String sortKey;
    private Boolean positiveFeedback;
    private String snapshotDigest;
    private String eventPayloadJson;
    private Date createTime;
    private Date updateTime;
}
