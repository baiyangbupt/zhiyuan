package com.ytell.zhiyuan.model.dto.planning;

import com.alibaba.fastjson.JSON;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;

class OrderedPlanGenerateReqTest {

    private static final String REQUEST =
            "{\"forceRegenerate\":true,\"allowExistingSpecialPlanConflicts\":true}";

    @Test
    void jacksonCannotEnableInternalRemovalExemption() throws Exception {
        OrderedPlanGenerateReq request = new ObjectMapper().readValue(REQUEST, OrderedPlanGenerateReq.class);

        assertFalse(Boolean.TRUE.equals(request.getAllowExistingSpecialPlanConflicts()));
    }

    @Test
    void fastjsonCannotEnableInternalRemovalExemption() {
        OrderedPlanGenerateReq request = JSON.parseObject(REQUEST, OrderedPlanGenerateReq.class);

        assertFalse(Boolean.TRUE.equals(request.getAllowExistingSpecialPlanConflicts()));
    }
}
