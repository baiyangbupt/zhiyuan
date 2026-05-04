package com.ytell.zhiyuan.model.req;

import com.ytell.zhiyuan.model.enums.SessionStatus;
import lombok.Data;

import java.util.Collections;
import java.util.List;

@Data
public class ChatSessionPageQuery {
    public Integer page = 1;
    public Integer pageSize = 20;
    private Long botId;
    private Long userId;
    private String searchWord;
    private List<SessionStatus> statusList;
    private List<OrderByWrapper> orderBy = Collections.singletonList(new OrderByWrapper(false, "id"));
}
