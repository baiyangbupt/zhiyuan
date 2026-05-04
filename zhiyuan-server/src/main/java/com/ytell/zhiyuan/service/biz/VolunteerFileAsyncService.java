package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.manager.ali.AliOSSService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.File;

@Slf4j
@Service
public class VolunteerFileAsyncService {

    @Autowired
    private AliOSSService aliOSSService;

    @Async
    public void uploadVolunteerFileToOss(Long tenantId, Long chatSessionId, String ossFileName, String filePath) {
        long start = System.currentTimeMillis();
        try {
            File file = new File(filePath);
            if (!file.exists()) {
                log.warn("async upload skipped because local file missing, tenantId={}, chatSessionId={}, filePath={}",
                        tenantId, chatSessionId, filePath);
                return;
            }
            String etag = aliOSSService.uploadFile(ossFileName, file);
            log.info("async upload volunteer file success, tenantId={}, chatSessionId={}, ossFileName={}, etag={}, costMs={}",
                    tenantId, chatSessionId, ossFileName, etag, System.currentTimeMillis() - start);
        } catch (Exception e) {
            log.error("async upload volunteer file failed, tenantId={}, chatSessionId={}, ossFileName={}, filePath={}, costMs={}",
                    tenantId, chatSessionId, ossFileName, filePath, System.currentTimeMillis() - start, e);
        }
    }
}
