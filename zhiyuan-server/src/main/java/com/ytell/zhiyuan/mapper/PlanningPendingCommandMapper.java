package com.ytell.zhiyuan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;

@Mapper
public interface PlanningPendingCommandMapper extends BaseMapper<PlanningPendingCommandEntity> {

    @Delete("DELETE FROM assistant_planning_pending_command "
            + "WHERE status = 'succeeded' AND update_time < #{cutoff} "
            + "ORDER BY id LIMIT #{batchSize}")
    int deleteSucceededUpdatedBefore(@Param("cutoff") Date cutoff,
                                     @Param("batchSize") int batchSize);
}
