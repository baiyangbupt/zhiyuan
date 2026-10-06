package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.io.Serializable;
import java.util.List;

/**
 * 选科策略（上游 `/hl-wish/ci/selectSubjectPolicy/noToken/subjectPolicy`）。
 *
 * <p>这是**编码字典的权威来源**：补录成绩时 `subjectScoreList[].subject` 必须用这里的
 * `subjectList[].subject`（01 物理 / 05 化学 …），用科目名（"物理"）或自造码（"wuli"）
 * 都会在下游组查询串时炸掉（2026-10-06 的真事故：模型只给了分数没给科目编码）。</p>
 *
 * <p>注意两件事：① 上游只回**选考科目**，语文/数学/英语（08/10/11）不在其中——它们由
 * 业务侧补全（见 `ScoreCatalogService`）；② `subjectTypeList` 才是批次线查询要的
 * "科类"（浙江=N 综合、江苏=WL/LS），与 `subjectList[].subject` 不是一套编码。</p>
 */
@Data
@ApiModel("SubjectPolicyResponseDTO")
public class SubjectPolicyResponseDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "年份")
    private String year;

    @ApiModelProperty(value = "填报方式（批次线查询的 prepareType 就取这里的 code）")
    private BatchDataResponseDTO.TypeInfo prepareType;

    @ApiModelProperty(value = "政策类型")
    private String policy;

    @ApiModelProperty(value = "首选科目数量")
    private Integer firstNum;

    @ApiModelProperty(value = "再选科目数量")
    private Integer secondNum;

    @ApiModelProperty(value = "科类列表（批次线查询的 subject 参数取值）")
    private List<SubjectTypeOption> subjectTypeList;

    @ApiModelProperty(value = "选考科目列表（含编码与名称）")
    private List<SubjectOption> subjectList;

    @ApiModelProperty(value = "修改次数上限")
    private Integer limitTimes;

    @Data
    public static class SubjectTypeOption implements Serializable {
        @ApiModelProperty(value = "科类编码（如 N/WL/LS）")
        private String code;

        @ApiModelProperty(value = "科类名称（如 综合/物理/历史）")
        private String desc;
    }

    @Data
    public static class SubjectOption implements Serializable {
        @ApiModelProperty(value = "是否首选科目")
        private Integer isFirst;

        @ApiModelProperty(value = "科目编码（补录成绩的 subject 取值）")
        private String subject;

        @ApiModelProperty(value = "科目名称")
        private String subjectName;

        @ApiModelProperty(value = "该科目适用的科类（部分省份才有，如江苏物理=WL）")
        private String subjectType;
    }
}
