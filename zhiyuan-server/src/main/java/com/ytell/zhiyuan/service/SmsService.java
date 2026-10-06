package com.ytell.zhiyuan.service;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.ali.AliSmsService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.Random;
import java.util.concurrent.TimeUnit;

@Service
@Slf4j
public class SmsService {
    private static final String SMS_CODE_PREFIX = "gaokao-assistant.sms_code:";
    private static final int CODE_LENGTH = 6;
    private static final long CODE_EXPIRE_MINUTES = 5;
    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private AliSmsService aliSmsService;

    /**
     * 测试白名单：逗号分隔的手机号，命中者跳过验证码比对（任意 6 位内写法都视为通过）。
     * **默认空 = 关闭** ✓——只有明确配置了号码的环境（标准测试栈在私有 yml 里配）才会生效，
     * 生产/其它环境不带这个配置，行为与从前逐字一致。
     * 用途（2026-10-06）：标准测试环境短信通道是占位 AccessKey（发不出去），
     * 固定测试号靠这条放行，避免"每次登录都要人工往 Redis 塞一次性码"。
     */
    @Value("${sms.test-bypass-mobiles:}")
    private String testBypassMobiles;

    public void sendVerificationCode(String mobile) {
        String code = generateVerificationCode();
        log.info("向手机号 {} 发送验证码: {}", mobile, code);
        aliSmsService.sendVerifyCode(mobile, code);
        // 将验证码保存到Redis，设置5分钟过期
        String key = SMS_CODE_PREFIX + mobile;
        redisTemplate.opsForValue().set(key, code, CODE_EXPIRE_MINUTES, TimeUnit.MINUTES);
    }

    public void verifyCode(String mobile, String code) {
        if (isTestBypassMobile(mobile)) {
            // WARN 级别留痕：白名单放行必须看得见（测试环境的"任意码可登"是显式配置，不是漏洞静默生效）
            log.warn("测试白名单放行验证码校验: mobile={}", mobile);
            return;
        }
        String key = SMS_CODE_PREFIX + mobile;
        String savedCode = redisTemplate.opsForValue().get(key);

        if (savedCode == null) {
            throw new BusinessException(403, "验证码已过期");
        }

        if (!savedCode.equals(code)) {
            throw new BusinessException(403, "验证码错误");
        }

        // 验证成功后删除验证码
        redisTemplate.delete(key);
    }

    private boolean isTestBypassMobile(String mobile) {
        if (testBypassMobiles == null || testBypassMobiles.trim().isEmpty()) {
            return false;
        }
        for (String candidate : testBypassMobiles.split(",")) {
            if (candidate.trim().equals(mobile)) {
                return true;
            }
        }
        return false;
    }

    private String generateVerificationCode() {
        Random random = new Random();
        StringBuilder code = new StringBuilder();
        for (int i = 0; i < CODE_LENGTH; i++) {
            code.append(random.nextInt(10));
        }
        return code.toString();
    }
}