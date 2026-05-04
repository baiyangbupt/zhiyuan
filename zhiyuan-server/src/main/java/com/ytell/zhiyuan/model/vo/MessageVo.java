package com.ytell.zhiyuan.model.vo;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.model.entity.biz.ChatMessage;
import com.ytell.zhiyuan.model.enums.ContentType;
import lombok.Data;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;

@Data
public class MessageVo {

    /**
     * // 消息ID
     */
    private Long id;

    /**
     * // 会话Id
     */
    private Long chatSessionId;

    /**
     * // 发送方信息
     */

    private String messageFrom;
    /**
     * 发送方名字
     */
    private String messageFromUserName;
    /**
     * // 消息类型
     */
    private ContentType contentType;
    /**
     * // 消息内容
     */

    private Object content;
    /**
     * // 用户反馈（0:无反馈，1:正反馈，-1:负反馈）
     */
    private Integer feedback;
    /**
     * // 显示时间
     */
    private String displayTime;


    public static MessageVo fromEntity(ChatMessage message) {
        MessageVo vo = new MessageVo();
        vo.setId(message.getId());
        vo.setMessageFrom(message.getMessageFrom());
        vo.setMessageFromUserName(message.getMessageFromUserName());
        vo.setChatSessionId(message.getChatSessionId());
        vo.setContentType(message.getContentType());
        vo.setContent(message.getContent());
        vo.setFeedback(message.getFeedback());

        vo.setDisplayTime(formatDate(message.getCreateTime()));
        return vo;
    }

    private static String formatDate(Date date) {
        // 获取当前时间
        Calendar now = Calendar.getInstance();
        // 创建一个Calendar对象来存储输入的日期
        Calendar calendar = Calendar.getInstance();
        calendar.setTime(date);

        // 检查是否是同一天
        boolean isSameDay = (calendar.get(Calendar.YEAR) == now.get(Calendar.YEAR))
                && (calendar.get(Calendar.MONTH) == now.get(Calendar.MONTH))
                && (calendar.get(Calendar.DAY_OF_MONTH) == now.get(Calendar.DAY_OF_MONTH));

        // 检查是否是昨天
        Calendar yesterday = Calendar.getInstance();
        yesterday.add(Calendar.DAY_OF_MONTH, -1);
        boolean isYesterday = (calendar.get(Calendar.YEAR) == yesterday.get(Calendar.YEAR))
                && (calendar.get(Calendar.MONTH) == yesterday.get(Calendar.MONTH))
                && (calendar.get(Calendar.DAY_OF_MONTH) == yesterday.get(Calendar.DAY_OF_MONTH));

        SimpleDateFormat timeFormat = new SimpleDateFormat("HH:mm");
        SimpleDateFormat dateFormat = new SimpleDateFormat("MM月dd日 HH:mm");

        int hour = calendar.get(Calendar.HOUR_OF_DAY);
        String timeString = timeFormat.format(date);

        if (isSameDay) {
            //今天不展示
            return null;
        } else if (isYesterday) {
            // 昨天
            return "昨天 " + timeString;
        } else {
            // 更早的时间
            return dateFormat.format(date);
        }
    }

    public ChatMessage toEntity() {
        ChatMessage message = new ChatMessage();
        message.setId(this.id);
        message.setChatSessionId(this.chatSessionId);
        String content = "";
        if (contentType.equals(ContentType.CARD)) {
            content = JSONObject.toJSONString(this.content);
        } else {
            content = String.valueOf(this.content);
        }
        message.setContent(content);
        message.setContentType(this.contentType);
        message.setMessageFrom(this.messageFrom);
        message.setMessageFromUserName(this.messageFromUserName);
        message.setFeedback(this.feedback);
        return message;
    }
}

