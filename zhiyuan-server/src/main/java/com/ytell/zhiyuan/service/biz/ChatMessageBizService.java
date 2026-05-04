package com.ytell.zhiyuan.service.biz;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ytell.zhiyuan.common.base.BasePage;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.SaveMessageRes;
import com.ytell.zhiyuan.model.entity.biz.ChatMessage;
import com.ytell.zhiyuan.model.req.ChatMessagePageReq;
import com.ytell.zhiyuan.model.vo.MessageVo;
import com.ytell.zhiyuan.service.shared.ChatMessageSharedService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 聊天消息管理服务
 */
@Slf4j
@Service
public class ChatMessageBizService {

    @Autowired
    private ChatMessageSharedService chatMessageService;

    /**
     * 分页获取会话下的消息列表
     *
     * @param tenantId 租户ID
     * @param req      分页查询参数
     * @return 消息分页数据
     */
    public BasePage<MessageVo> pageMessage(Long tenantId, ChatMessagePageReq req) {
        Page<ChatMessage> chatMessagePage = chatMessageService.page(tenantId, req);
        List<MessageVo> messageVoList = chatMessagePage.getRecords().stream()
                .map(message -> {
                    MessageVo vo = MessageVo.fromEntity(message);
                    return vo;
                })
                .collect(Collectors.toList());

        return BasePage.wrapper(
                chatMessagePage.getCurrent(),
                chatMessagePage.getTotal(),
                messageVoList
        );
    }

    /**
     * 获取会话下的所有消息
     * 只返回文本类型的消息
     *
     * @param tenantId      租户ID
     * @param chatSessionId 会话ID
     * @return 消息列表
     */
    public List<MessageVo> listAll(Long tenantId, Long chatSessionId) {
        List<ChatMessage> chatMessageList = chatMessageService.listBySession(tenantId, chatSessionId);

        List<MessageVo> messageVoList = chatMessageList.stream()
                .map(message -> {
                    MessageVo vo = MessageVo.fromEntity(message);
                    return vo;
                })
                .collect(Collectors.toList());
        return messageVoList;
    }

    /**
     * 保存或更新会话消息
     *
     * @param tenantId  租户ID
     * @param messageVo 消息数据
     * @return 保存结果
     */
    public SaveMessageRes saveOrUpdate(Long tenantId, MessageVo messageVo) {
        ChatMessage message = chatMessageService.saveOrUpdate(tenantId, messageVo.toEntity());
        SaveMessageRes res = new SaveMessageRes();
        res.setId(message.getId());
        return res;
    }

    public MessageVo getMessageById(Long tenantId, Long messageId) {
        ChatMessage message = chatMessageService.getMessageById(tenantId, messageId);
        if (message != null) {
            MessageVo vo = MessageVo.fromEntity(message);

            return vo;
        }
        throw new BusinessException(110, "消息不存在");

    }

    /**
     * 更新消息反馈
     *
     * @param tenantId  租户ID
     * @param messageId 消息ID
     * @param feedback  反馈值（0:无反馈，1:正反馈，-1:负反馈）
     * @return 是否更新成功
     */
    public Boolean updateMessageFeedback(Long tenantId, Long messageId, Integer feedback) {
        ChatMessage message = chatMessageService.getMessageById(tenantId, messageId);
        if (message == null) {
            throw new BusinessException(110, "消息不存在");
        }
        
        // 验证反馈值
        if (feedback != null && feedback != 0 && feedback != 1 && feedback != -1) {
            throw new BusinessException(111, "反馈值只能是0、1或-1");
        }
        
        message.setFeedback(feedback);
        chatMessageService.saveOrUpdate(tenantId, message);
        return true;
    }


} 