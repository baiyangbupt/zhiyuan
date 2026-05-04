package com.ytell.zhiyuan.model.dto.inner;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class SchoolTagBean {
    private Long schoolId;
    private String name;
    private String province;
    private String city;
    private List<String> district;
    private List<String> authority;
    @JsonProperty("historic_authorities")
    private List<String> historicAuthorities;
    @JsonProperty("legacy_honor")
    private List<String> legacyHonor;
    private List<String> level;
    private List<String> nature;
    private List<String> category;
    private List<String> postGraduate;
    private String batch;
    @JsonProperty("goat_major")
    private List<String> goatMajor;
    @JsonProperty("legacy_strong_side")
    private List<String> legacyStrongSide;
    @JsonProperty("legacy_strong_major")
    private List<String> legacyStrongMajor;
    @JsonProperty("double_first_major")
    private List<String> doubleFirstMajor;
    @JsonProperty("fourth_evaluate_roll")
    private List<String> fourthEvaluateRoll;
    @JsonProperty("district_flourishing_industry")
    private List<String> districtFlourishingIndustry;
    @JsonProperty("city_flourishing_industry")
    private List<String> cityFlourishingIndustry;
    @JsonProperty("recruitment_policy")
    private List<String> recruitmentPolicy;
} 