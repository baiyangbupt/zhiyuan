package com.ytell.zhiyuan.manager.cache;

import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.concurrent.TimeUnit;

@Service
public class ThirdChannelSessionKeyCache {

    private final static String SESSION_KEY_CACHE_TEMPLATE = "real-relax.session:key:cache:%s:%s";
    @Autowired
    private StringRedisTemplate redisTemplate;

    public void saveOrUpdate(AuthTypeEnum channel, String openId, String sessionKey) {
        String key = String.format(SESSION_KEY_CACHE_TEMPLATE, channel.toString(), openId);
        redisTemplate.boundValueOps(key).set(sessionKey, 18, TimeUnit.HOURS);

    }

    public String get(AuthTypeEnum channel, String openId) {
        String key = String.format(SESSION_KEY_CACHE_TEMPLATE, channel.toString(), openId);
        return redisTemplate.boundValueOps(key).get();
    }
}
