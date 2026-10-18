package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/** J5.1 最小候选快照：同一会话/版本内，所有选择动作共用的事实来源。 */
@Data
public class CandidateSnapshotDTO {
    private String snapshotVersion = "candidate-snapshot-v1";
    private Integer sourceVersion;
    private String dataVersion;
    private String volunteerModel;
    private String countMode;
    private String sourceProvince;
    private String normalizationDigest;
    private List<CandidateFactDTO> facts = Lists.newArrayList();
}
