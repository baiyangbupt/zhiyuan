package com.ytell.zhiyuan.model.dto.volunteer;

import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import lombok.Data;

import java.util.List;

/**
 * 区间划分请求
 */
@Data
public class VolunteerDivideRequest {
    private List<ProgramPageDTO.SchoolDetail> schoolDetails;
    private String applyType;
    private int totalCount;
    private boolean useNineIntervals;

    private boolean needExtraAdd;
}

