package com.ytell.zhiyuan.model.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@AllArgsConstructor
@NoArgsConstructor
public class ProfileKVDto {

    private String name;
    private List<Object> value;

    /**
     * 正向值明细（包含情绪）
     */
    @JsonProperty("pDetails")
    private List<UserIntentValueDetail> pDetails;

    /**
     * 负向值明细（包含情绪）
     */
    @JsonProperty("nDetails")
    private List<UserIntentValueDetail> nDetails;

    // 构造函数，用于基本信息
    public ProfileKVDto(String name, List<Object> value) {
        this.name = name;
        this.value = value;
    }

}
