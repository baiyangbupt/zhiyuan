package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Data
public class FixProposalDryRunResultDTO {
    private String status = "ready";
    private String message;
    private Integer beforeUnitTotal = 0;
    private Integer afterUnitTotal = 0;
    private Integer beforeVolunteerTotal = 0;
    private Integer afterVolunteerTotal = 0;
    private Map<String, Integer> beforeUnitTierCounts = new LinkedHashMap<String, Integer>();
    private Map<String, Integer> afterUnitTierCounts = new LinkedHashMap<String, Integer>();
    private Map<String, Integer> beforeVolunteerTierCounts = new LinkedHashMap<String, Integer>();
    private Map<String, Integer> afterVolunteerTierCounts = new LinkedHashMap<String, Integer>();
    private Set<String> beforeUnitIds = new LinkedHashSet<String>();
    private Set<String> afterUnitIds = new LinkedHashSet<String>();
    private Set<String> beforeVolunteerIds = new LinkedHashSet<String>();
    private Set<String> afterVolunteerIds = new LinkedHashSet<String>();
    private Double beforeAverageFinalScore;
    private Double afterAverageFinalScore;
    private Double beforeAverageHotIndex;
    private Double afterAverageHotIndex;
    private Double beforeAverageSchoolRank;
    private Double afterAverageSchoolRank;
    private Integer affectedUnitCount = 0;
    private Integer affectedVolunteerCount = 0;
    private Integer addUnitCount = 0;
    private Integer addVolunteerCount = 0;
    private Integer removeUnitCount = 0;
    private Integer removeVolunteerCount = 0;
    private Integer priorityMatchedCount = 0;
    private Integer priorityBeforeInversionCount = 0;
    private Integer priorityAfterInversionCount = 0;
    private Integer priorityMovedTargetCount = 0;
    private List<String> warnings = Lists.newArrayList();
}
