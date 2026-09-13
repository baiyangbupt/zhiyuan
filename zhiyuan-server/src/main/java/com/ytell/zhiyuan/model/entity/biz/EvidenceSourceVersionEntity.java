package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

/**
 * 每个取数来源、每组查询参数最近一次观察到的数据版本，供失效判定比对。
 *
 * <p>主键是 (source_system, params_digest) 复合键，因此没有单个 {@code @TableId}；
 * 读写走 {@code EvidenceSourceVersionMapper} 上显式声明的方法，不要用 {@code selectById}。</p>
 */
@Data
@TableName("evidence_source_version")
public class EvidenceSourceVersionEntity {

    private String sourceSystem;
    private String paramsDigest;
    private String dataVersion;
    private Date observedAt;
    private Date updatedAt;
}
