package com.ytell.zhiyuan.model.dto.inner;


import com.ytell.zhiyuan.model.dto.gaotu.ProgramPageDTO;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import lombok.Data;

@Data
public class QueryProgramDetailDto {

    private RecommendNumResponse recommendNum;
    private ProgramPageDTO programPageDTO;

}
