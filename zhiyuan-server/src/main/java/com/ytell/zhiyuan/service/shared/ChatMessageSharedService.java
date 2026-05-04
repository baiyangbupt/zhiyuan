package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ytell.zhiyuan.mapper.ChatMessageMapper;
import com.ytell.zhiyuan.model.entity.biz.ChatMessage;
import com.ytell.zhiyuan.model.req.ChatMessagePageReq;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ChatMessageSharedService {

    @Autowired
    private ChatMessageMapper chatMessageMapper;

    public ChatMessage saveOrUpdate(Long tenantId, ChatMessage chatMessage) {
        chatMessage.setTenantId(tenantId);
        if (chatMessage.getId() != null) {
            chatMessageMapper.updateById(chatMessage);
        } else {
            chatMessageMapper.insert(chatMessage);
        }
        return chatMessageMapper.selectById(chatMessage.getId());
    }

    public ChatMessage addMessage(ChatMessage chatMessage) {
        chatMessageMapper.insert(chatMessage);
        return chatMessage;
    }

    public List<ChatMessage> listBySession(Long tenantId, Long chatSessionId) {
        QueryWrapper<ChatMessage> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(ChatMessage::getChatSessionId, chatSessionId);

        return chatMessageMapper.selectList(queryWrapper);

    }

    public Page<ChatMessage> page(Long tenantId, ChatMessagePageReq req) {
        QueryWrapper<ChatMessage> queryWrapper = new QueryWrapper<>();
        if (req.getChatSessionId() != null) {
            queryWrapper.lambda().eq(ChatMessage::getChatSessionId, req.getChatSessionId());
        }
        if (req.getOrderBy() != null) {
            req.getOrderBy().forEach(one -> {
                if (one.getIsAsc()) {
                    queryWrapper.orderByAsc(one.getOrderBy());
                } else {
                    queryWrapper.orderByDesc(one.getOrderBy());
                }
            });
        }

        return chatMessageMapper.selectPage(new Page<>(req.getPage(), req.getPageSize()), queryWrapper);
    }

    public ChatMessage getMessageById(Long tenantId, Long messageId) {
        return chatMessageMapper.selectById(messageId);
    }

    /**
     * 根据消息id获取这个chatsession下这条信息前面的n条消息
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @param messageId     消息ID
     * @param limit         查询条数
     * @return 消息列表（按消息ID排序）
     */
    public List<ChatMessage> listPreviousMessages(Long tenantId, Long chatSessionId, Long messageId, Integer limit) {
        QueryWrapper<ChatMessage> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda()
                .eq(ChatMessage::getChatSessionId, chatSessionId)
                .lt(ChatMessage::getId, messageId)
                .orderByDesc(ChatMessage::getId)
                .last("LIMIT " + limit);

        List<ChatMessage> messages = chatMessageMapper.selectList(queryWrapper);
        // 结果需要按消息ID正序排列
        messages.sort((a, b) -> a.getId().compareTo(b.getId()));
        return messages;
    }

}
