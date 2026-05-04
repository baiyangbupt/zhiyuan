package com.ytell.zhiyuan.model.vo;

import com.ytell.zhiyuan.model.entity.meta.Bot;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.beans.BeanUtils;

import java.util.Date;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class BotVo {

    private Long id;
    private Long tenantId;
    private String nickName;
    private String avatarUrl;
    private String introduce;
    private Date createTime;
    private Date updateTime;

    public static BotVo fromEntity(Bot bot) {
        if (bot == null) {
            return defaultInstance();
        }
        BotVo botVo = new BotVo();
        BeanUtils.copyProperties(bot, botVo);
        return botVo;
    }

    public static BotVo defaultInstance() {
        return BotVo.builder()
                .id(1L)
                .tenantId(1L)
                .nickName("智愿助手")
                .avatarUrl("")
                .introduce("AI 高考志愿填报助手")
                .build();
    }
}
