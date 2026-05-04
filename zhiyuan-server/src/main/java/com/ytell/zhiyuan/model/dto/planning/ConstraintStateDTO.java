package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class ConstraintStateDTO {
    private HardConstraintsDTO hardConstraints = new HardConstraintsDTO();
    private SoftPreferencesDTO softPreferences = new SoftPreferencesDTO();
    private DerivedPreferencesDTO derivedPreferences = new DerivedPreferencesDTO();
}
