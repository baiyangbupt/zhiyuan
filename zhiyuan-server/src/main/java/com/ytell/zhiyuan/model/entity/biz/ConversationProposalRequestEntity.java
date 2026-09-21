package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

/**
 * prepare 幂等记录。
 *
 * <p>刻意**不可覆盖**：Pending 表是每会话一行的状态，重试会把上一次的记录冲掉，
 * 于是"重试同一个 requestId"既看不出是重试、也可能被当成新请求再执行一次。
 * 这里按 (tenant, session, requestId) 唯一，保留每次 prepare 的结果。
 */
@Data
@TableName("assistant_conversation_proposal_request")
public class ConversationProposalRequestEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long chatSessionId;
    private String requestId;
    private String requestDigest;
    private String pendingId;
    private String operationId;
    private String resultJson;
    private String status;
    private Date createTime;
    private Date updateTime;
}
