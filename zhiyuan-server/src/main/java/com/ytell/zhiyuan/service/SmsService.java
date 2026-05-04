package com.ytell.zhiyuan.service;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.ali.AliSmsService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
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

    public void sendVerificationCode(String mobile) {
        String code = generateVerificationCode();
        log.info("向手机号 {} 发送验证码: {}", mobile, code);
        aliSmsService.sendVerifyCode(mobile, code);
        // 将验证码保存到Redis，设置5分钟过期
        String key = SMS_CODE_PREFIX + mobile;
        redisTemplate.opsForValue().set(key, code, CODE_EXPIRE_MINUTES, TimeUnit.MINUTES);
    }

    public void verifyCode(String mobile, String code) {
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

    private String generateVerificationCode() {
        Random random = new Random();
        StringBuilder code = new StringBuilder();
        for (int i = 0; i < CODE_LENGTH; i++) {
            code.append(random.nextInt(10));
        }
        return code.toString();
    }
}