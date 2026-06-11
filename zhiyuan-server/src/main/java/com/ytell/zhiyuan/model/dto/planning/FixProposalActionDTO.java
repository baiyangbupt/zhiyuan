package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class FixProposalActionDTO {
    private String actionType;
    private String level;
    private String sourceCheckCode;
    private String summary;
    private String detail;
    private List<String> unitIds = Lists.newArrayList();
    private List<String> volunteerIds = Lists.newArrayList();
    private List<String> removeUnitIds = Lists.newArrayList();
    private List<String> removeVolunteerIds = Lists.newArrayList();
    private List<String> candidateUnitIds = Lists.newArrayList();
    private List<String> candidateVolunteerIds = Lists.newArrayList();
    private List<ReplacementPairDTO> replacementPairs = Lists.newArrayList();
}
