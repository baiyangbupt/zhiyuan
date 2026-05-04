package com.ytell.zhiyuan.model.req;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Collections;
import java.util.List;

@Data
@AllArgsConstructor
@NoArgsConstructor
public class OrderByWrapper {
    public static List<OrderByWrapper> defaultOrder = Collections.singletonList(new OrderByWrapper());
    private Boolean isAsc = false;
    private String orderBy = "create_time";
}
