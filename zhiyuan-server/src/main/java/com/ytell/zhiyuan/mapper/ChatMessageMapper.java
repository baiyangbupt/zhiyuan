package com.ytell.zhiyuan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ytell.zhiyuan.model.entity.biz.ChatMessage;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface ChatMessageMapper extends BaseMapper<ChatMessage> {
}
