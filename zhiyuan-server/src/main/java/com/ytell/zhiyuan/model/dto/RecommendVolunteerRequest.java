package com.ytell.zhiyuan.model.dto;

import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import lombok.Data;

import java.util.List;

/**
 * 志愿排序请求数据结构
 */
@Data
public class RecommendVolunteerRequest {
    
    /**
     * 学生信息
     */
    private CreateSessionReq studentinfo;
    
    /**
     * 志愿信息
     */
    private List<VolunteerSchoolGroup> volunteerinfo;
    
    /**
     * 用户画像信息
     */
    private UserProfileData profileinfo;
}
