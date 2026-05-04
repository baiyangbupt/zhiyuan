package com.ytell.zhiyuan.model.dto.volunteer;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 简化的历史录取记录数据结构
 * 用于替代复杂的 ProgramPageDTO.SubVO，只保留最终需要的核心信息
 */
@Data
@ApiModel("历史录取记录")
public class HistoryRecordDTO {
    
    @ApiModelProperty("年份")
    private String year;
    
    @ApiModelProperty("录取分数")
    private String score;
    
    @ApiModelProperty("录取位次")
    private String pos;
    
    @ApiModelProperty("计划数量")
    private String planNum;
    
    @ApiModelProperty("录取数量") 
    private String enrollNum;
    
    /**
     * 从 ProgramPageDTO.SubVO 转换为 HistoryRecordDTO
     */
    public static HistoryRecordDTO fromSubVO(com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO.SubVO subVO) {
        if (subVO == null) {
            return null;
        }
        
        HistoryRecordDTO dto = new HistoryRecordDTO();
        dto.setYear(subVO.getYear());
        
        // 优先使用 enrollScore，如果为空则使用 enrollScoreDb
        if (subVO.getEnrollScore() != null && !subVO.getEnrollScore().trim().isEmpty()) {
            dto.setScore(subVO.getEnrollScore());
        } else if (subVO.getEnrollScoreDb() != null && !subVO.getEnrollScoreDb().trim().isEmpty()) {
            dto.setScore(subVO.getEnrollScoreDb());
        }
        
        // 优先使用 enrollPos，如果为空则使用其他位次字段
        if (subVO.getEnrollPos() != null && !subVO.getEnrollPos().trim().isEmpty()) {
            dto.setPos(subVO.getEnrollPos());
        } else if (subVO.getEnrollAvgPos() != null && !subVO.getEnrollAvgPos().trim().isEmpty()) {
            dto.setPos(subVO.getEnrollAvgPos());
        }
        
        dto.setPlanNum(subVO.getPlanNum());
        dto.setEnrollNum(subVO.getEnrollNum());
        
        return dto;
    }
}
