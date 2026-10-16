package com.ytell.zhiyuan.web.interceptor;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.servlet.HandlerInterceptor;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Enumeration;

@Component
public class InternalServiceAuthInterceptor implements HandlerInterceptor {
    public static final String HEADER_NAME = "X-Internal-Service-Token";

    private final byte[] expectedToken;

    public InternalServiceAuthInterceptor(
            @Value("${internal.service.token:${INTERNAL_SERVICE_TOKEN:}}") String token) {
        this.expectedToken = StringUtils.hasText(token) ? token.getBytes(StandardCharsets.UTF_8) : new byte[0];
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws IOException {
        Enumeration<String> credentials = request.getHeaders(HEADER_NAME);
        if (expectedToken.length == 0 || credentials == null || !credentials.hasMoreElements()) {
            return deny(response, HttpServletResponse.SC_UNAUTHORIZED);
        }
        String suppliedToken = credentials.nextElement();
        if (!StringUtils.hasText(suppliedToken)) {
            return deny(response, HttpServletResponse.SC_UNAUTHORIZED);
        }
        if (credentials.hasMoreElements()
                || !MessageDigest.isEqual(expectedToken, suppliedToken.getBytes(StandardCharsets.UTF_8))) {
            return deny(response, HttpServletResponse.SC_FORBIDDEN);
        }
        return true;
    }

    private boolean deny(HttpServletResponse response, int status) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getWriter().write("{\"code\":" + status + ",\"msg\":\"internal service authentication required\"}");
        return false;
    }
}
