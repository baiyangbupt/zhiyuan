package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.util.List;
@Data
public class UserScoreBase {
    private CreateSessionReq.Province province; // 高考省份
    private Integer examYear; // 高考年份
    private CreateSessionReq.Sex sex; // 性别
    private List<CreateSessionReq.SubjectItem> subjectList; // 科目列表
    private CreateSessionReq.SubjectType subjectType; // 科目类型

}
