package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class ConstraintDeriveRes {
    private Integer version;
    private DerivedPreferencesDTO derivedPreferences = new DerivedPreferencesDTO();
    private StaleFlagsDTO staleFlags = new StaleFlagsDTO();
}
