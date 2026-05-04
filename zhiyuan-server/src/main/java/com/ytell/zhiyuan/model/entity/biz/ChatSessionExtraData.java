package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.ytell.zhiyuan.model.enums.DataType;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@TableName("assistant_chat_session_extra_data")
public class ChatSessionExtraData {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long chatSessionId;
    private String dataKey;
    private Integer dataVersion;
    private DataType dataType;
    private String dataValue;
    private Date createTime;
    private Date updateTime;
}
