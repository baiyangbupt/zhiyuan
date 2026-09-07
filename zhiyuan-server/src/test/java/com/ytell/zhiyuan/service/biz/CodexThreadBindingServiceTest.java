package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.mapper.CodexThreadBindingMapper;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingReq;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingContextRes;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingResolveReq;
import com.ytell.zhiyuan.model.entity.biz.CodexThreadBindingEntity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.OffsetDateTime;
import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.verify;

public class CodexThreadBindingServiceTest {

    private CodexThreadBindingService service;
    private CodexThreadBindingMapper mapper;

    @BeforeEach
    void setUp() {
        service = new CodexThreadBindingService();
        mapper = Mockito.mock(CodexThreadBindingMapper.class);
        ReflectionTestUtils.setField(service, "bindingMapper", mapper);
    }

    @Test
    void shouldRegisterBindingWithHashedHandleAndCapabilities() {
        CodexThreadBindingReq req = request();
        doReturn(1).when(mapper).insert(any(CodexThreadBindingEntity.class));

        String handle = service.register(1L, req);

        assertEquals(64, handle.length());
        verify(mapper).insert(any(CodexThreadBindingEntity.class));
    }

    @Test
    void shouldRejectMissingIdentity() {
        CodexThreadBindingReq req = request();
        req.setThreadId("");

        assertThrows(IllegalArgumentException.class, () -> service.register(1L, req));
    }

    @Test
    void shouldRejectExpiredBinding() {
        CodexThreadBindingEntity entity = entity();
        entity.setExpiresAt(java.util.Date.from(java.time.Instant.now().minusSeconds(1)));
        doReturn(entity).when(mapper).selectOne(any());

        assertThrows(IllegalStateException.class,
                () -> service.resolve(1L, 101L, "thr_test", "handle", "catalog.search_schools"));
    }

    @Test
    void shouldRejectDuplicateThreadBindingBeforeInsert() {
        CodexThreadBindingEntity existing = entity();
        doReturn(existing).when(mapper).selectOne(any());
        CodexThreadBindingReq req = request();
        req.setUserId(303L);

        assertThrows(IllegalStateException.class,
                () -> service.register(1L, req));
    }

    @Test
    void shouldRejectRegistrationWithPastExpiry() {
        CodexThreadBindingReq req = request();
        req.setExpiresAt(OffsetDateTime.now().minusMinutes(1).toString());

        assertThrows(IllegalArgumentException.class,
                () -> service.register(1L, req));
    }

    @Test
    void shouldRejectRevokedBinding() {
        CodexThreadBindingEntity entity = entity();
        entity.setRevokedAt(new java.util.Date());
        doReturn(entity).when(mapper).selectOne(any());

        IllegalStateException error = assertThrows(IllegalStateException.class,
                () -> service.resolve(1L, 101L, "thr_test", "opaque-handle", "catalog.search_schools"));
        assertEquals("binding_revoked", error.getMessage());
    }

    @Test
    void shouldRejectCapabilityOutsideAllowlist() {
        CodexThreadBindingEntity entity = entity();
        doReturn(entity).when(mapper).selectOne(any());

        IllegalStateException error = assertThrows(IllegalStateException.class,
                () -> service.resolve(1L, 101L, "thr_test", "opaque-handle", "plan.propose_changes"));
        assertEquals("capability_denied", error.getMessage());
    }

    @Test
    void shouldRejectTenantOrSessionMismatch() {
        doReturn(null).when(mapper).selectOne(any());

        IllegalStateException error = assertThrows(IllegalStateException.class,
                () -> service.resolve(9L, 999L, "thr_test", "opaque-handle", "catalog.search_schools"));

        assertEquals("binding_not_found", error.getMessage());
    }

    @Test
    void shouldResolveTrustedContextWithoutReturningHandle() {
        CodexThreadBindingEntity entity = entity();
        doReturn(entity).when(mapper).selectOne(any());
        CodexThreadBindingResolveReq req = new CodexThreadBindingResolveReq();
        req.setChatSessionId(101L);
        req.setThreadId("thr_test");
        req.setHandle("opaque-handle");
        req.setCapability("catalog.search_schools");

        CodexThreadBindingContextRes response = service.resolveResponse(1L, req);

        assertEquals(101L, response.getChatSessionId());
        assertEquals(202L, response.getUserId());
        assertEquals("thr_test", response.getThreadId());
        assertEquals(Arrays.asList("catalog.search_schools"), response.getAllowedCapabilities());
    }

    private CodexThreadBindingReq request() {
        CodexThreadBindingReq req = new CodexThreadBindingReq();
        req.setChatSessionId(101L);
        req.setUserId(202L);
        req.setThreadId("thr_test");
        req.setHandle("opaque-handle");
        req.setAllowedCapabilities(Arrays.asList("catalog.search_schools"));
        req.setExpiresAt(OffsetDateTime.now().plusMinutes(5).toString());
        return req;
    }

    private CodexThreadBindingEntity entity() {
        CodexThreadBindingEntity entity = new CodexThreadBindingEntity();
        entity.setTenantId(1L);
        entity.setChatSessionId(101L);
        entity.setUserId(202L);
        entity.setThreadId("thr_test");
        entity.setHandleHash(service.hashHandle("opaque-handle"));
        entity.setAllowedCapabilities("catalog.search_schools");
        entity.setExpiresAt(java.util.Date.from(java.time.Instant.now().plusSeconds(300)));
        return entity;
    }
}
