package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

/** 每个取数来源最近一次观察到的上游数据版本，供失效判定比对。 */
@Data
@TableName("evidence_source_version")
public class EvidenceSourceVersionEntity {

    @TableId(value = "source_system", type = IdType.INPUT)
    private String sourceSystem;
    private String dataVersion;
    private Date observedAt;
    private Date updatedAt;
}
