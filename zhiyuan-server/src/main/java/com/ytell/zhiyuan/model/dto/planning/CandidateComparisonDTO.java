package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class CandidateComparisonDTO {
    private List<ComparisonEntityDTO> entities = new ArrayList<ComparisonEntityDTO>();
    private List<String> dimensions = new ArrayList<String>();
    private List<ComparisonCellDTO> cells = new ArrayList<ComparisonCellDTO>();
    /** 因为口径不一致而**整列不可比**的维度。 */
    private List<String> unavailableDimensions = new ArrayList<String>();
    private List<String> limitations = new ArrayList<String>();
}
