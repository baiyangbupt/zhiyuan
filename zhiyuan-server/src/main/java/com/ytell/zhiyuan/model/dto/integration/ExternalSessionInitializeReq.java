package com.ytell.zhiyuan.model.dto.integration;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import lombok.Data;

@Data
public class ExternalSessionInitializeReq {
    private String externalRequestId;
    private CreateSessionReq createSession;
    private ExternalGenerationOptionsDTO generationOptions = new ExternalGenerationOptionsDTO();
    private ExternalReturnOptionsDTO returnOptions = new ExternalReturnOptionsDTO();
}
