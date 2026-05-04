package com.ytell.zhiyuan.model.dto;

import com.ytell.zhiyuan.model.vo.MessageVo;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;

/**
 * SSE消息包装类 - 包含MessageVo和SSE特定的元数据
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class SseMessageWrapper {

    /**
     * SSE消息类型
     */
    private String messageType;

    /**
     * 消息内容 - 使用MessageVo
     */
    private MessageVo message;

    /**
     * 会议ID（用于SSE路由）
     */
    private String meetingId;

    /**
     * 会议号（用于SSE路由）
     */
    private String meetingCode;

    /**
     * SSE推送时间戳
     */
    private Date timestamp;

    /**
     * 系统消息内容（连接、断开、错误等）
     */
    private String systemMessage;

    /**
     * 创建ASR内容消息
     */
    public static SseMessageWrapper createAsrMessage(MessageVo messageVo, String meetingId, String meetingCode) {
        return SseMessageWrapper.builder()
                .messageType(MessageType.ASR_CONTENT)
                .message(messageVo)
                .meetingId(meetingId)
                .meetingCode(meetingCode)
                .timestamp(new Date())
                .build();
    }

    /**
     * 创建系统消息
     */
    public static SseMessageWrapper createSystemMessage(String messageType, Long chatSessionId, String systemMessage) {
        MessageVo messageVo = new MessageVo();
        messageVo.setChatSessionId(chatSessionId);

        return SseMessageWrapper.builder()
                .messageType(messageType)
                .message(messageVo)
                .systemMessage(systemMessage)
                .timestamp(new Date())
                .build();
    }

    /**
     * 创建心跳消息
     */
    public static SseMessageWrapper createHeartbeatMessage() {
        return SseMessageWrapper.builder()
                .messageType(MessageType.HEARTBEAT)
                .systemMessage("heartbeat")
                .timestamp(new Date())
                .build();
    }

    /**
     * SSE消息类型常量
     */
    public static class MessageType {
        /**
         * ASR转写内容
         */
        public static final String ASR_CONTENT = "asr_content";

        /**
         * 连接建立
         */
        public static final String CONNECTED = "connected";

        /**
         * 连接断开
         */
        public static final String DISCONNECTED = "disconnected";

        /**
         * 心跳
         */
        public static final String HEARTBEAT = "heartbeat";

        /**
         * 错误消息
         */
        public static final String ERROR = "error";

        /**
         * 系统消息
         */
        public static final String SYSTEM = "system";
    }
} 