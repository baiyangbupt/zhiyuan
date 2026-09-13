package com.ytell.zhiyuan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ytell.zhiyuan.model.entity.biz.EvidenceSourceVersionEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Date;

@Mapper
public interface EvidenceSourceVersionMapper extends BaseMapper<EvidenceSourceVersionEntity> {

    /**
     * 记录该来源、该组查询参数最近一次观察到的数据版本。
     *
     * <p>键是 (source_system, params_digest)：版本值取自响应内容摘要，天然按参数分。</p>
     */
    @Insert("INSERT INTO evidence_source_version (source_system, params_digest, data_version, observed_at) "
            + "VALUES (#{sourceSystem}, #{paramsDigest}, #{dataVersion}, #{observedAt}) "
            + "ON DUPLICATE KEY UPDATE data_version = VALUES(data_version), observed_at = VALUES(observed_at)")
    int upsert(@Param("sourceSystem") String sourceSystem,
               @Param("paramsDigest") String paramsDigest,
               @Param("dataVersion") String dataVersion,
               @Param("observedAt") Date observedAt);

    /** 取该来源、该组查询参数最近一次观察到的版本；没有记录时返回 {@code null}。 */
    @Select("SELECT source_system, params_digest, data_version, observed_at, updated_at "
            + "FROM evidence_source_version "
            + "WHERE source_system = #{sourceSystem} AND params_digest = #{paramsDigest}")
    EvidenceSourceVersionEntity selectBySourceAndParams(@Param("sourceSystem") String sourceSystem,
                                                        @Param("paramsDigest") String paramsDigest);
}
