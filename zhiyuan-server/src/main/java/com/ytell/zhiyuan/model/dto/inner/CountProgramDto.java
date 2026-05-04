package com.ytell.zhiyuan.model.dto.inner;


import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
public class CountProgramDto {

    private RecommendNumResponse recommendNum;
    private StatisticData programPageDTO;

    @Data
    public static class StatisticData {
        @ApiModelProperty("方案模型")
        private ProgramPageDTO.ProgramModel model;
        @ApiModelProperty("数据类型")
        private ProgramPageDTO.Type type;
    }

}
