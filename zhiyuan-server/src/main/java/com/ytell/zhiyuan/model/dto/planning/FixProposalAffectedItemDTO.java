package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 提案卡上的逐条明细（点名加入时由 Java 从候选行生成，模型/网关不自行拼展示字段）。
 */
@Data
public class FixProposalAffectedItemDTO {
    private String volunteerId;
    private String unitId;
    private String schoolName;
    private String majorName;
    private String tier;
    private Integer planNum;
    private Integer tuitionPerYear;
}
