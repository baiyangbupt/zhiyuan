package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class OrderedUnitRemoveReq {
    private List<String> unitIds = Lists.newArrayList();
}
