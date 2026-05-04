package com.ytell.zhiyuan.model.req;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import lombok.Data;

import java.util.List;

@Data
public class UnAcceptableMajorsReq {
    String educationLevel;
    String subjectType;
    List<CreateSessionReq.SubjectItem> subjectList;
}
