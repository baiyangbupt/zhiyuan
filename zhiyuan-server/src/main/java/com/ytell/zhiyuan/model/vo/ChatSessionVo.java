package com.ytell.zhiyuan.model.vo;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.beans.BeanUtils;

import java.util.Date;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ChatSessionVo {
    private long id;
    private Long userId;
    private String userName;
    private BotVo botVo;
    private String infoSummary;
    private SessionStatus sessionStatus;
    private String mobile;
    private Date startTime;
    private Date endTime;
    private Date createTime;
    private Date updateTime;
    private CreateSessionReq.PrepareType prepareType;

    public static ChatSessionVo fromEntity(ChatSession chatSession, BotVo botVo, String infoSummary) {
        ChatSessionVo vo = new ChatSessionVo();
        BeanUtils.copyProperties(chatSession, vo);
        vo.setInfoSummary(infoSummary);
        vo.setBotVo(botVo);
        return vo;
    }

    public static ChatSessionVo fromEntity(ChatSession chatSession, BotVo botVo, String infoSummary, CreateSessionReq.PrepareType prepareType) {
        ChatSessionVo vo = new ChatSessionVo();
        BeanUtils.copyProperties(chatSession, vo);
        vo.setInfoSummary(infoSummary);
        vo.setBotVo(botVo);
        vo.setPrepareType(prepareType);
        return vo;
    }

}
