package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class UpdatePhysicalConstraintsReq {
    private PhysicalConstraintsDTO.VisionDTO vision;
    private java.util.List<String> colorVision;
    private String height;
    private java.util.List<String> specialLimits;
}
