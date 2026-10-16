package com.ytell.zhiyuan.web.interceptor;

import com.ytell.zhiyuan.common.config.GlobalExceptionHandler;
import com.ytell.zhiyuan.common.config.WebConfig;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;

import java.lang.reflect.Field;
import java.util.List;

import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup;

class InternalServiceAuthMvcTest {
    private static final String HEADER = "X-Internal-Service-Token";
    private static final String TOKEN = "standalone-test-credential";
    private static final String INNER = "/gaotu-assistant-bot/inner/ops/health";

    @ParameterizedTest
    @ValueSource(strings = {
            INNER, "/gaotu-assistant-bot/admin/user/list", "/gaotu-assistant-bot/debug/probe",
            "/internal/evidence/verify", "/internal/other", "/gaotu-assistant-bot/internal/probe",
            "/inner", "/admin", "/debug", "/internal", "/internal/evidence"
    })
    void excludedInternalRoutesRequireAServiceCredential(String path) throws Exception {
        mvc(TOKEN).perform(get(path)).andExpect(status().isUnauthorized());
    }

    @ParameterizedTest
    @ValueSource(strings = {INNER, "/gaotu-assistant-bot/admin/user/list", "/debug/probe", "/internal/evidence/verify"})
    void wrongCredentialsReturnAReal403(String path) throws Exception {
        mvc(TOKEN).perform(post(path).header(HEADER, "wrong-credential"))
                .andExpect(status().isForbidden())
                .andExpect(content().string(not(containsString(TOKEN))))
                .andExpect(content().string(not(containsString("wrong-credential"))));
    }

    @ParameterizedTest
    @ValueSource(strings = {INNER, "/gaotu-assistant-bot/admin/user/list", "/debug/probe", "/internal/evidence/verify", "/internal/other"})
    void correctCredentialsReachTheControllerWithoutUserLogin(String path) throws Exception {
        mvc(TOKEN).perform(post(path).header(HEADER.toLowerCase(), TOKEN))
                .andExpect(status().isOk()).andExpect(content().string("reached"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"", " ", "\t"})
    void missingServerConfigurationFailsClosed(String configuredToken) throws Exception {
        mvc(configuredToken).perform(get(INNER).header(HEADER, TOKEN))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void blankQueryAndUserCredentialsCannotReplaceTheHeader() throws Exception {
        MockMvc mvc = mvc(TOKEN);
        mvc.perform(get(INNER).header(HEADER, " ")).andExpect(status().isUnauthorized());
        mvc.perform(get(INNER).param("token", TOKEN).header("tk", TOKEN).header("pf", "WECHAT_MP"))
                .andExpect(status().isUnauthorized());
        mvc.perform(options(INNER)).andExpect(status().isUnauthorized());
    }

    @Test
    void duplicateAndPaddedCredentialsAreRejected() throws Exception {
        MockMvc mvc = mvc(TOKEN);
        mvc.perform(get(INNER).header(HEADER, TOKEN, "wrong-credential"))
                .andExpect(status().isForbidden());
        mvc.perform(get(INNER).header(HEADER, " " + TOKEN + " "))
                .andExpect(status().isForbidden());
    }

    @ParameterizedTest
    @ValueSource(strings = {"/gaotu-assistant-bot/user/login/code", "/gaotu-assistant-bot/base-data/province-city",
            "/gaotu-assistant-bot/wx/callback", "/doc.html", "/v2/api-docs", "/error"})
    void publicRoutesRemainPublic(String path) throws Exception {
        mvc("").perform(get(path)).andExpect(status().isOk()).andExpect(content().string("reached"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"/gaotu-assistant-bot/chat/1/planning/session/workspace-state",
            "/gaotu-assistant-bot/conversation/ws-ticket"})
    void serviceCredentialsDoNotBypassUserAuthentication(String path) throws Exception {
        mvc(TOKEN).perform(get(path).header(HEADER, TOKEN)).andExpect(status().isUnauthorized());
    }

    private MockMvc mvc(String configuredToken) throws Exception {
        WebConfig config = new WebConfig();
        for (Field field : WebConfig.class.getDeclaredFields()) {
            field.setAccessible(true);
            if (field.getType() == LoginInterceptor.class) {
                field.set(config, new LoginInterceptor());
            } else if (field.getType().getSimpleName().equals("InternalServiceAuthInterceptor")) {
                field.set(config, field.getType().getConstructor(String.class).newInstance(configuredToken));
            } else {
                field.set(config, field.getType().getConstructor().newInstance());
            }
        }
        RegisteredInterceptors registry = new RegisteredInterceptors();
        config.addInterceptors(registry);
        return standaloneSetup(new ProbeController())
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomHandlerMapping(() -> {
                    RequestMappingHandlerMapping mapping = new RequestMappingHandlerMapping();
                    mapping.setInterceptors(registry.registered().toArray());
                    return mapping;
                }).build();
    }

    private static class RegisteredInterceptors extends InterceptorRegistry {
        List<Object> registered() {
            return getInterceptors();
        }
    }

    @RestController
    private static class ProbeController {
        @RequestMapping("/**")
        String probe() {
            return "reached";
        }
    }
}
