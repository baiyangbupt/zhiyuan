package com.ytell.zhiyuan.manager.lock;

import cn.hutool.core.date.DateUtil;
import com.google.common.base.Strings;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.Date;

@Service
public class WelcomeLock {
    private static final String WELCOME_KEY_FORMAT = "gaotu:zhiyuan:welcome:%s";
    @Autowired
    private StringRedisTemplate redisTemplate;

    public boolean lock(Long customerId) {

        String key = String.format(WELCOME_KEY_FORMAT, customerId);
        String value = redisTemplate.opsForValue().get(key);
        if (Strings.isNullOrEmpty(value)) {
            redisTemplate.opsForValue().set(key, "1");
            //今天最后时刻过期
            redisTemplate.boundValueOps(key).expireAt(DateUtil.endOfDay(new Date()));
            return true;
        }
        return false;
    }


}
