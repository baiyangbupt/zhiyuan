package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class DraftLockReq {
    private List<String> volunteerIds = Lists.newArrayList();
    private Boolean locked = true;
}
