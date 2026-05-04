package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.util.List;

@Data
public class RecommendReq {
    private List<String>  provinceList;
    private List<String>  cityList;
    private List<String>  schoolList;
    private List<String> majorList;
    private List<String>  tagList;
    private  Double minEnrollRate;
    private  Double maxEnrollRate;
}
