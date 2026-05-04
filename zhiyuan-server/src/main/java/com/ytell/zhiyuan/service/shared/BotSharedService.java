package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ytell.zhiyuan.mapper.BotMapper;
import com.ytell.zhiyuan.model.entity.meta.Bot;
import org.springframework.stereotype.Service;

@Service
public class BotSharedService extends ServiceImpl<BotMapper, Bot> {

    public Bot getBotById(Long botId) {

        return getById(botId);
    }

}
