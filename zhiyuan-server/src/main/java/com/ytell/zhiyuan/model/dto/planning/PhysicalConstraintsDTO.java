package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PhysicalConstraintsDTO {
    private VisionDTO vision = new VisionDTO();
    private List<String> colorVision = Lists.newArrayList();
    private String height;
    private List<String> specialLimits = Lists.newArrayList();

    @Data
    public static class VisionDTO {
        private String left;
        private String right;
    }
}
