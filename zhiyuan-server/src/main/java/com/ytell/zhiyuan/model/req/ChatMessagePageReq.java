package com.ytell.zhiyuan.model.req;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
public class ChatMessagePageReq {
    public Integer page = 1;
    public Integer pageSize = 20;
    private Long chatSessionId;
    private List<OrderByWrapper> orderBy = OrderByWrapper.defaultOrder;
}
