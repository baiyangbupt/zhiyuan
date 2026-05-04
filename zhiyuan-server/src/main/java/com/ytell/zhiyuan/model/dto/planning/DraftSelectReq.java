package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class DraftSelectReq {
    private List<String> volunteerIds = Lists.newArrayList();
    private String source = "user_ui";
}
