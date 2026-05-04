package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.io.Serializable;
import java.util.List;

@Data
@ApiModel(value = "ListReportInfoRpcVO", description = "获取测评报告列表响应参数")
public class ListReportInfoDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "报告信息列表")
    private List<ReportInfoVO> reportInfoList;

    @Data
    @ApiModel(value = "ReportInfoVO", description = "报告信息")
    public static class ReportInfoVO implements Serializable {

        private static final long serialVersionUID = 1L;

        @ApiModelProperty(value = "报告ID", name = "reportId")
        private Long reportId;

        @ApiModelProperty(value = "提交记录ID", name = "submitRecordId")
        private Long submitRecordId;

        @ApiModelProperty(value = "问卷名称", name = "paperName")
        private String paperName;

        @ApiModelProperty(value = "问卷ID", name = "paperId")
        private Long paperId;

        @ApiModelProperty(value = "创建报告的时间", name = "createTime")
        private String createTime;

        @ApiModelProperty(value = "创建报告的时间", name = "createTimestamp")
        private Long createTimestamp;
    }
}