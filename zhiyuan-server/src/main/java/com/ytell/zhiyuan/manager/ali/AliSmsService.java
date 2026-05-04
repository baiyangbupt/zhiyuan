package com.ytell.zhiyuan.manager.ali;

import com.alibaba.fastjson.JSONObject;
import com.aliyun.dysmsapi20170525.Client;
import com.aliyun.dysmsapi20170525.models.SendSmsRequest;
import com.aliyun.dysmsapi20170525.models.SendSmsResponse;
import com.aliyun.dysmsapi20170525.models.SendSmsResponseBody;
import com.aliyun.tea.TeaException;
import com.aliyun.teaopenapi.models.Config;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.ali.AliSmsProperties;
import com.ytell.zhiyuan.common.exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;
import java.util.Map;

@Service
@Slf4j
@EnableConfigurationProperties(AliSmsProperties.class)
public class AliSmsService {
    @Autowired
    private AliSmsProperties smsProperties;

    private Client smsClient;

    @PostConstruct
    public void init() throws Exception {
        Config config = new Config()
                // 配置 AccessKey ID
                .setAccessKeyId(smsProperties.accessKeyId)
                // 配置 AccessKey Secret
                .setAccessKeySecret(smsProperties.accessKeySecret);
        // 配置 Endpoint。中国站请使用dysmsapi.aliyuncs.com
        config.endpoint = smsProperties.endpoint;
        smsClient = new Client(config);
        log.info("AliSms initialized, endpoint={}, signName={}, template={}",
                smsProperties.endpoint, smsProperties.signName, smsProperties.template);
    }

    public void sendVerifyCode(String phoneNumber, String code) {
        try {
            Map<String, String> param = Maps.newHashMap();
            param.put("code", code);

            SendSmsRequest sendSmsRequest = new SendSmsRequest()
                    .setPhoneNumbers(phoneNumber)
                    .setSignName(smsProperties.signName)
                    .setTemplateCode(smsProperties.template)
                    .setTemplateParam(JSONObject.toJSONString(param));

            // 获取响应对象
            SendSmsResponse sendSmsResponse = smsClient.sendSms(sendSmsRequest);
            SendSmsResponseBody body = sendSmsResponse.getBody();

            log.info("sendSms response, phone={}, response={}",
                    phoneNumber, JSONObject.toJSONString(sendSmsResponse));

            if (body != null && body.getCode() != null && !"OK".equalsIgnoreCase(body.getCode())) {
                log.error("sendSms failed, phone={}, code={}, message={}, requestId={}",
                        phoneNumber, body.getCode(), body.getMessage(), body.getRequestId());
                throw new BusinessException(404, "短信验证码发送失败: " + body.getMessage());
            }
        } catch (TeaException e) {
            log.error("sendSms tea exception, phone={}, message={}, data={}",
                    phoneNumber, e.getMessage(), JSONObject.toJSONString(e.getData()), e);
            throw new BusinessException(404, "短信验证码发送失败，稍后重试");
        } catch (Exception e) {
            log.error("sendSms unexpected exception, phone={}", phoneNumber, e);
            throw new BusinessException(404, "短信验证码发送失败，稍后重试");
        }
    }

}
