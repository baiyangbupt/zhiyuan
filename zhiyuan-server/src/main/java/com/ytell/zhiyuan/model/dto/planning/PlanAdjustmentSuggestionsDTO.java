package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanAdjustmentSuggestionsDTO {
    private List<AddSuggestionDTO> addSuggestions = Lists.newArrayList();
    private List<ReorderSuggestionDTO> reorderSuggestions = Lists.newArrayList();
    private List<ReplaceSuggestionDTO> replaceSuggestions = Lists.newArrayList();
    private List<RemoveSuggestionDTO> removeSuggestions = Lists.newArrayList();
}
