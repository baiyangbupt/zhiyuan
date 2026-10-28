package com.ytell.zhiyuan.service.biz;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.ytell.zhiyuan.common.util.PasswordHashing;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.UserCredentialMapper;
import com.ytell.zhiyuan.mapper.UserMapper;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.enums.LoginType;
import com.ytell.zhiyuan.model.req.UserLoginRequest;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class UserPasswordLoginTest {
    private UserBizService service;
    private UserCredentialMapper credentials;
    private UserMapper users;

    @BeforeEach
    void setUp() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), UserCredential.class);
        service = new UserBizService();
        credentials = mock(UserCredentialMapper.class);
        users = mock(UserMapper.class);
        ReflectionTestUtils.setField(service, "userCredentialMapper", credentials);
        ReflectionTestUtils.setField(service, "userMapper", users);
        User user = new User();
        user.setId(7L);
        when(users.selectById(7L)).thenReturn(user);
    }

    private UserCredential stored(String password) {
        UserCredential credential = new UserCredential();
        credential.setCredentialId(9L);
        credential.setUserId(7L);
        credential.setIdentifier("tester");
        credential.setLoginType(LoginType.USERNAME);
        credential.setPasswordHash(password);
        credential.setLoginToken("existing-login-token");
        when(credentials.selectList(any())).thenReturn(java.util.Collections.singletonList(credential));
        return credential;
    }

    private UserLoginRequest login(String password) {
        UserLoginRequest request = new UserLoginRequest();
        request.setUserName("tester");
        request.setPassword(password);
        return request;
    }

    @Test
    void wrongPasswordIsCheckedAfterIdentifierLookup() {
        stored("correct-password");
        BusinessException failure = assertThrows(BusinessException.class, () -> service.login(login("wrong-password")));
        assertEquals(404, failure.getStatus());
        assertEquals("用户名或者密码错误", failure.getMessage());
        verify(credentials, never()).update(any(), any());
    }

    @Test
    void passwordIsNotUsedInTheDatabaseLookup() {
        stored("old-password");
        when(credentials.update(any(), any())).thenReturn(1);
        service.login(login("old-password"));
        ArgumentCaptor<Wrapper<UserCredential>> captor = ArgumentCaptor.forClass(Wrapper.class);
        verify(credentials).selectList(captor.capture());
        String sql = captor.getValue().getSqlSegment();
        assertTrue(sql.contains("identifier"));
        assertTrue(sql.contains("login_type"));
        assertFalse(sql.contains("password_hash"));
        assertTrue(sql.contains("LIMIT 2"));
    }

    @Test
    void malformedHashCannotBeSubmittedAsThePassword() {
        String malformed = "$pbkdf2-sha256$600000$bad-salt$bad-hash";
        stored(malformed);
        assertThrows(BusinessException.class, () -> service.login(login(malformed)));
    }

    @Test
    void hashedPasswordAuthenticatesWithoutRewritingOtherCredentialFields() {
        UserCredential credential = stored(PasswordHashing.hash("hashed-password"));
        assertEquals(credential.getLoginToken(), service.login(login("hashed-password")).getLoginToken());
        verify(credentials, never()).update(any(), any());
        assertThrows(BusinessException.class, () -> service.login(login(credential.getPasswordHash())));
    }

    @Test
    void legacyUpgradeSetsOnlyPasswordAndUsesAByteExactCredentialCas() {
        stored("Old-Password");
        when(credentials.update(any(), any())).thenReturn(1);
        assertEquals("existing-login-token", service.login(login("Old-Password")).getLoginToken());
        ArgumentCaptor<Wrapper<UserCredential>> capture = ArgumentCaptor.forClass(Wrapper.class);
        verify(credentials).update(isNull(), capture.capture());
        UpdateWrapper<UserCredential> update = (UpdateWrapper<UserCredential>) capture.getValue();
        String predicate = update.getSqlSegment();
        assertTrue(predicate.contains("credential_id"));
        assertTrue(predicate.contains("login_type"));
        assertTrue(predicate.contains("BINARY password_hash"), "MySQL's default case-insensitive collation is not a password CAS");
        assertTrue(update.getParamNameValuePairs().containsValue(9L));
        assertTrue(update.getParamNameValuePairs().containsValue(LoginType.USERNAME.getCode()));
        assertTrue(update.getParamNameValuePairs().containsValue("Old-Password"));
        assertTrue(update.getSqlSet().startsWith("password_hash="));
        assertFalse(update.getSqlSet().contains(","), "upgrade must not overwrite token, user or identifier");
        String encoded = update.getParamNameValuePairs().values().stream()
                .filter(value -> value instanceof String && ((String) value).startsWith("$pbkdf2-sha256$"))
                .map(value -> (String) value).findFirst().orElseThrow(AssertionError::new);
        assertTrue(PasswordHashing.matches("Old-Password", encoded));
        verify(credentials, never()).updateById(any(UserCredential.class));
    }

    @Test
    void concurrentPasswordChangeWinsOverLegacyUpgrade() {
        stored("old-password");
        UserCredential current = new UserCredential();
        current.setCredentialId(9L);
        current.setUserId(7L);
        current.setIdentifier("tester");
        current.setLoginType(LoginType.USERNAME);
        current.setPasswordHash(PasswordHashing.hash("changed-password"));
        when(credentials.update(any(), any())).thenReturn(0);
        when(credentials.selectById(9L)).thenReturn(current);
        BusinessException failure = assertThrows(BusinessException.class, () -> service.login(login("old-password")));
        assertEquals("用户名或者密码错误", failure.getMessage());
        verify(credentials, times(1)).update(any(), any());
        verify(users, never()).selectById(any());
    }

    @Test
    void concurrentIdenticalUpgradeCanAuthenticateWithTheCurrentToken() {
        stored("old-password");
        UserCredential current = new UserCredential();
        current.setCredentialId(9L);
        current.setUserId(7L);
        current.setIdentifier("tester");
        current.setLoginType(LoginType.USERNAME);
        current.setPasswordHash(PasswordHashing.hash("old-password"));
        current.setLoginToken("current-login-token");
        when(credentials.update(any(), any())).thenReturn(0);
        when(credentials.selectById(9L)).thenReturn(current);
        assertEquals("current-login-token", service.login(login("old-password")).getLoginToken());
        verify(credentials, times(1)).update(any(), any());
    }

    @Test
    void failedUpgradeCannotLeaveAnUnchangedLegacyPasswordAuthenticated() {
        UserCredential current = stored("old-password");
        when(credentials.update(any(), any())).thenReturn(0);
        when(credentials.selectById(9L)).thenReturn(current);
        assertThrows(BusinessException.class, () -> service.login(login("old-password")));
    }

    @Test
    void nullOrEmptyCredentialsFailBeforeQueryAndUnknownUserHasTheSameFailure() {
        for (String password : new String[] {null, "", " "}) {
            BusinessException failure = assertThrows(BusinessException.class, () -> service.login(login(password)));
            assertEquals(404, failure.getStatus());
            assertEquals("用户名或者密码错误", failure.getMessage());
        }
        UserLoginRequest missingName = login("password");
        missingName.setUserName(null);
        assertThrows(BusinessException.class, () -> service.login(missingName));
        assertThrows(BusinessException.class, () -> service.login(null));
        verifyNoInteractions(credentials);
        BusinessException missing = assertThrows(BusinessException.class, () -> service.login(login("password")));
        assertEquals(404, missing.getStatus());
        assertEquals("用户名或者密码错误", missing.getMessage());
    }


    @Test
    void historicalDuplicateNamesWithDifferentPasswordsRemainDistinguishable() {
        UserCredential first = stored(PasswordHashing.hash("first-password"));
        UserCredential second = stored(PasswordHashing.hash("second-password"));
        second.setCredentialId(10L);
        second.setUserId(8L);
        second.setLoginToken("second-user-token");
        User secondUser = new User();
        secondUser.setId(8L);
        when(users.selectById(8L)).thenReturn(secondUser);
        when(credentials.selectList(any())).thenReturn(java.util.Arrays.asList(first, second));
        when(credentials.selectCount(any())).thenReturn(2L);
        assertEquals("second-user-token", service.login(login("second-password")).getLoginToken());
        verify(users, never()).selectById(7L);
        verify(credentials, never()).update(any(), any());
    }

    @Test
    void sameNameAndPasswordAcrossAccountsIsAnAmbiguousLoginFailure() {
        UserCredential first = stored("same-password");
        UserCredential second = stored("same-password");
        second.setCredentialId(10L);
        second.setUserId(8L);
        when(credentials.selectList(any())).thenReturn(java.util.Arrays.asList(first, second));
        when(credentials.selectCount(any())).thenReturn(2L);
        BusinessException failure = assertThrows(BusinessException.class, () -> service.login(login("same-password")));
        assertEquals(404, failure.getStatus());
        assertEquals("用户名或者密码错误", failure.getMessage());
        verify(credentials, never()).update(any(), any());
        verifyNoInteractions(users);
    }

    @Test
    void moreThanTwoHistoricalDuplicatesFailWithoutAuthenticatingATruncatedSet() {
        UserCredential first = stored("match-password");
        UserCredential second = stored("other-password");
        when(credentials.selectList(any())).thenReturn(java.util.Arrays.asList(first, second));
        when(credentials.selectCount(any())).thenReturn(3L);
        assertThrows(BusinessException.class, () -> service.login(login("match-password")));
        verifyNoInteractions(users);
        verify(credentials, never()).update(any(), any());
    }

}
