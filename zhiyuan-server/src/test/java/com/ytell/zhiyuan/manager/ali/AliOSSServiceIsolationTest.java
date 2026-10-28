package com.ytell.zhiyuan.manager.ali;

import com.aliyun.oss.OSS;
import com.aliyun.oss.model.OSSObject;
import com.aliyun.oss.model.PutObjectResult;
import com.aliyun.oss.model.PolicyConditions;
import com.ytell.zhiyuan.common.ali.OssProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.net.URL;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class AliOSSServiceIsolationTest {
    @TempDir
    Path tempDir;

    private AliOSSService service(OssProperties properties, OSS client) {
        AliOSSService service = new AliOSSService();
        ReflectionTestUtils.setField(service, "ossProperties", properties);
        if (client != null) {
            ReflectionTestUtils.setField(service, "ossClient", client);
        }
        return service;
    }

    @Test
    void disabledOssSkipsClientInitializationAndAllRemoteOperations() {
        OssProperties properties = new OssProperties();
        properties.setEnabled(false);
        properties.setBucket("unused");
        OSS client = mock(OSS.class);
        AliOSSService service = service(properties, client);

        service.init();
        assertFalse(service.downloadFile("session_volunteer/1_final.json", tempDir.resolve("missing.json").toString()));
        assertThrows(AliOSSService.OssUnavailableException.class,
                () -> service.uploadFile("session_volunteer/1_final.json", new File("missing.json")));
        assertThrows(AliOSSService.OssUnavailableException.class,
                () -> service.getDownloadUrl("session_volunteer/1_final.json"));
        assertThrows(AliOSSService.OssUnavailableException.class,
                () -> service.getSignature("user/"));
        verifyNoInteractions(client);
        assertFalse(Files.exists(tempDir.resolve("missing.json")));
    }

    @Test
    void namespaceScopesBothReadAndWriteWithoutLegacyReadFallback() throws Exception {
        OssProperties properties = new OssProperties();
        properties.setBucket("isolated-test-bucket");
        properties.setNamespace("codex-local-a");
        OSS client = mock(OSS.class);
        OSSObject object = mock(OSSObject.class);
        when(object.getObjectContent()).thenReturn(new ByteArrayInputStream("{}".getBytes()));
        when(client.getObject("isolated-test-bucket", "codex-local-a/session_volunteer/1_final.json"))
                .thenReturn(object);
        PutObjectResult putResult = mock(PutObjectResult.class);
        when(putResult.getETag()).thenReturn("etag");
        when(client.putObject(eq("isolated-test-bucket"),
                eq("codex-local-a/session_volunteer/1_final.json"), any(File.class)))
                .thenReturn(putResult);
        when(client.generatePresignedUrl(eq("isolated-test-bucket"),
                eq("codex-local-a/session_volunteer/1_final.json"), any(java.util.Date.class)))
                .thenReturn(new URL("https://example.invalid/codex-local-a/session_volunteer/1_final.json?signature=test"));
        when(client.generatePostPolicy(any(java.util.Date.class), any(PolicyConditions.class))).thenReturn("policy");
        when(client.calculatePostSignature("policy")).thenReturn("signature");
        AliOSSService service = service(properties, client);
        Path target = tempDir.resolve("nested/final.json");

        assertTrue(service.downloadFile("session_volunteer/1_final.json", target.toString()));
        assertEquals("{}", new String(Files.readAllBytes(target), StandardCharsets.UTF_8));
        assertEquals("etag", service.uploadFile("session_volunteer/1_final.json", target.toFile()));
        assertEquals("https://example.invalid/codex-local-a/session_volunteer/1_final.json",
                service.getDownloadUrl("session_volunteer/1_final.json"));
        assertEquals("codex-local-a/user/", service.getSignature("user/").get("dir"));
        verify(client).getObject("isolated-test-bucket", "codex-local-a/session_volunteer/1_final.json");
        verify(client).putObject("isolated-test-bucket", "codex-local-a/session_volunteer/1_final.json", target.toFile());
        verify(client).generatePresignedUrl(eq("isolated-test-bucket"),
                eq("codex-local-a/session_volunteer/1_final.json"), any(java.util.Date.class));
        verify(client).generatePostPolicy(any(java.util.Date.class), any(PolicyConditions.class));
        verify(client).calculatePostSignature("policy");
        verifyNoMoreInteractions(client);
    }

    @Test
    void defaultConfigurationPreservesLegacyObjectKeys() throws Exception {
        OssProperties properties = new OssProperties();
        properties.setBucket("existing-bucket");
        OSS client = mock(OSS.class);
        OSSObject object = mock(OSSObject.class);
        when(object.getObjectContent()).thenReturn(new ByteArrayInputStream("{}".getBytes(StandardCharsets.UTF_8)));
        when(client.getObject("existing-bucket", "session_volunteer/1_final.json")).thenReturn(object);
        AliOSSService service = service(properties, client);

        assertTrue(properties.isEnabled());
        assertTrue(service.downloadFile("session_volunteer/1_final.json", tempDir.resolve("result.json").toString()));
        verify(client).getObject("existing-bucket", "session_volunteer/1_final.json");
    }

    @Test
    void invalidNamespaceFailsBeforeClientInitialization() {
        OssProperties properties = new OssProperties();
        properties.setEnabled(false);
        properties.setNamespace("../production");
        AliOSSService service = service(properties, null);
        assertThrows(IllegalArgumentException.class, service::init);
    }

    @Test
    void namespacedOperationsRejectNonRelativeKeysBeforeCallingSdk() {
        OssProperties properties = new OssProperties();
        properties.setNamespace("codex-local");
        OSS client = mock(OSS.class);
        AliOSSService service = service(properties, client);

        for (String invalid : Arrays.asList(null, "", "/absolute", "\\absolute", "a\\b",
                ".", "..", "a/./b", "a/../b", "a//b", "a/")) {
            assertThrows(IllegalArgumentException.class,
                    () -> service.uploadFile(invalid, new File("missing.json")), String.valueOf(invalid));
            assertThrows(IllegalArgumentException.class,
                    () -> service.downloadFile(invalid, tempDir.resolve("missing.json").toString()), String.valueOf(invalid));
            assertThrows(IllegalArgumentException.class,
                    () -> service.getDownloadUrl(invalid), String.valueOf(invalid));
        }
        for (String invalidDirectory : Arrays.asList(null, "", "/absolute", "a\\b",
                ".", "..", "a/./", "a/../", "a//b")) {
            assertThrows(IllegalArgumentException.class,
                    () -> service.getSignature(invalidDirectory), String.valueOf(invalidDirectory));
        }
        verifyNoInteractions(client);
    }
}
