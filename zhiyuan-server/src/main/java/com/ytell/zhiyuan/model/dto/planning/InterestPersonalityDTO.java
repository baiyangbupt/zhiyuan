package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class InterestPersonalityDTO {
    private List<String> subjectInterests = Lists.newArrayList();
    private List<String> activityInterests = Lists.newArrayList();
    private List<String> hobbyTags = Lists.newArrayList();
    private List<String> personalityTraits = Lists.newArrayList();
    private List<String> workPreference = Lists.newArrayList();
}
