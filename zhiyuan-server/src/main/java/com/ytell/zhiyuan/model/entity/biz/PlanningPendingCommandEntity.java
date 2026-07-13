package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_planning_pending_command")
public class PlanningPendingCommandEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long chatSessionId;
    private String pendingId;
    private String operationId;
    private String commandType;
    private Integer expectedPlanVersion;
    private String requestDigest;
    private String status;
    private String resultJson;
    private Date createTime;
    private Date updateTime;
}
