package com.ytell.zhiyuan.model.vo;

import com.ytell.zhiyuan.model.dto.EmploymentRateDTO;
import com.ytell.zhiyuan.model.dto.SubjectPriorityDTO;
import lombok.Data;

import java.util.List;

/**
 * 专业补充数据VO
 * 对应major_extra_data.csv文件中的数据结构
 */
@Data
public class MajorExtraDataVO {

    /**
     * 一级分类id
     */
    private Integer firstCategoryId;

    /**
     * 一级分类
     */
    private String firstCategory;

    /**
     * 二级分类id
     */
    private Integer secondCategoryId;

    /**
     * 二级分类
     */
    private String secondCategory;

    /**
     * 文理报考情况（文、理）
     */
    private List<String> artsScience;

    /**
     * 学科优先级
     */
    private List<SubjectPriorityDTO> subjectPriority;

    /**
     * 备注
     */
    private String remark;

    /**
     * 就业率信息
     */
    private List<EmploymentRateDTO> employmentRate;

    /**
     * 优势地域
     */
    private List<String> advantageRegions;
}
