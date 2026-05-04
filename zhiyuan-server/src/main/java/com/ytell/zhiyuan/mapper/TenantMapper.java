package com.ytell.zhiyuan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ytell.zhiyuan.model.entity.meta.Tenant;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface TenantMapper extends BaseMapper<Tenant> {
}
