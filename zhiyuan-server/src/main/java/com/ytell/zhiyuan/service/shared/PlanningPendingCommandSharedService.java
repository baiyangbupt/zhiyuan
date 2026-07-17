package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ytell.zhiyuan.mapper.PlanningPendingCommandMapper;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import org.springframework.stereotype.Service;

import java.util.Date;

@Service
public class PlanningPendingCommandSharedService
        extends ServiceImpl<PlanningPendingCommandMapper, PlanningPendingCommandEntity> {

    public PlanningPendingCommandEntity getByOperationId(String operationId) {
        QueryWrapper<PlanningPendingCommandEntity> query = new QueryWrapper<PlanningPendingCommandEntity>();
        query.lambda().eq(PlanningPendingCommandEntity::getOperationId, operationId).last("limit 1");
        return this.getOne(query);
    }

    public int deleteSucceededUpdatedBefore(Date cutoff, int batchSize) {
        if (cutoff == null) {
            throw new IllegalArgumentException("cutoff is required");
        }
        int boundedBatchSize = Math.max(1, Math.min(batchSize, 5000));
        return baseMapper.deleteSucceededUpdatedBefore(cutoff, boundedBatchSize);
    }
}
