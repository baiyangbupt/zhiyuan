package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/** 录取解读请求。MVP 反事实只支持 removeEntryRefs。 */
@Data
public class AdmissionInterpretationReq {

    private Integer planVersion;
    private String admissionMode;
    private CounterfactualDTO counterfactual;

    @Data
    public static class CounterfactualDTO {
        private List<EntryRefDTO> removeEntryRefs = new ArrayList<EntryRefDTO>();
    }

    @Data
    public static class EntryRefDTO {
        private String level;
        private String id;
    }
}
