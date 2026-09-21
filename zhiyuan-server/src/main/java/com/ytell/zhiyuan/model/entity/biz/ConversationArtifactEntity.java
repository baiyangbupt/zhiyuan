package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

/**
 * 会话产物：候选表、对比、冻结方案这类"模型只拿一份引用"的大对象。
 *
 * <p>不可原地修改。同一 artifactId 的内容一旦写入就不再变——下游按
 * {@code payloadDigest} 判断自己手上那份还是不是同一份，改了摘要就失去意义。
 */
@Data
@TableName("assistant_conversation_artifact")
public class ConversationArtifactEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String artifactId;
    private Long tenantId;
    private Long chatSessionId;
    private String kind;
    private String payloadJson;
    private String payloadDigest;
    private String dependenciesJson;
    private Date expiresAt;
    private Date createTime;
    private Date updateTime;
}
