package com.ytell.zhiyuan.model.dto.volunteer;

import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import lombok.Data;

import java.util.List;

/**
 * 志愿排序请求
 */
@Data
public class VolunteerSortRequest {
    private List<ProgramPageDTO.SchoolDetail> schoolDetails;
    private String applyType; // 报考类型
    private Long chatSessionId;
}

