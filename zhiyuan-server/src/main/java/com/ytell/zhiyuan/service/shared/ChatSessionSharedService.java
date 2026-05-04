package com.ytell.zhiyuan.service.shared;

import cn.hutool.core.collection.CollectionUtil;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.mapper.ChatSessionMapper;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.req.ChatSessionPageQuery;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class ChatSessionSharedService extends ServiceImpl<ChatSessionMapper, ChatSession> {

    @Autowired
    private ChatSessionMapper chatSessionMapper;

    public ChatSession getById(Long id) {
        return chatSessionMapper.selectById(id);
    }


    public ChatSession saveSession(ChatSession chatSession) {
        chatSessionMapper.insert(chatSession);
        return chatSession;
    }

    public Page<ChatSession> pageSession(Long tenantId, ChatSessionPageQuery req) {
        QueryWrapper<ChatSession> queryWrapper = new QueryWrapper<>();
        if (tenantId != null) {
            queryWrapper.lambda().eq(ChatSession::getTenantId, tenantId);
        }
        if (req.getBotId() != null) {
            queryWrapper.lambda().eq(ChatSession::getBotId, req.getBotId());
        }
        if (req.getUserId() != null) {
            queryWrapper.lambda().eq(ChatSession::getUserId, req.getUserId());
        }

        if (CollectionUtil.isNotEmpty(req.getStatusList())) {
            queryWrapper.lambda().in(ChatSession::getSessionStatus, req.getStatusList());
        }

        if (!Strings.isNullOrEmpty(req.getSearchWord())) {
            queryWrapper.lambda().and(qw -> qw.like(ChatSession::getMobile, req.getSearchWord())
                    .or().like(ChatSession::getUserName, req.getSearchWord()));
        }

        req.getOrderBy().forEach(one -> {
            if (one.getIsAsc()) {
                queryWrapper.orderByAsc(one.getOrderBy());
            } else {
                queryWrapper.orderByDesc(one.getOrderBy());
            }
        });

        return chatSessionMapper.selectPage(new Page<>(req.getPage(), req.getPageSize()), queryWrapper);
    }


}
