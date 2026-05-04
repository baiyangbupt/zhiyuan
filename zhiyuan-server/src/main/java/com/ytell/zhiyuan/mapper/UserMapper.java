package com.ytell.zhiyuan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ytell.zhiyuan.model.entity.biz.User;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface UserMapper extends BaseMapper<User> {
} 