package com.ytell.zhiyuan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ytell.zhiyuan.model.entity.biz.EvidenceSourceVersionEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;

@Mapper
public interface EvidenceSourceVersionMapper extends BaseMapper<EvidenceSourceVersionEntity> {

    /** 记录该来源最近一次观察到的上游数据版本。 */
    @Insert("INSERT INTO evidence_source_version (source_system, data_version, observed_at) "
            + "VALUES (#{sourceSystem}, #{dataVersion}, #{observedAt}) "
            + "ON DUPLICATE KEY UPDATE data_version = VALUES(data_version), observed_at = VALUES(observed_at)")
    int upsert(@Param("sourceSystem") String sourceSystem,
               @Param("dataVersion") String dataVersion,
               @Param("observedAt") Date observedAt);
}
