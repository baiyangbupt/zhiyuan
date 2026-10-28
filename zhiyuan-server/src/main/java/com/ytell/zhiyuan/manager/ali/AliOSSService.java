package com.ytell.zhiyuan.manager.ali;


import com.aliyun.oss.ClientBuilderConfiguration;
import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import com.aliyun.oss.common.auth.CredentialsProviderFactory;
import com.aliyun.oss.common.auth.DefaultCredentialProvider;
import com.aliyun.oss.common.comm.SignVersion;
import com.aliyun.oss.common.utils.BinaryUtil;
import com.aliyun.oss.model.MatchMode;
import com.aliyun.oss.model.OSSObject;
import com.aliyun.oss.model.PolicyConditions;
import com.aliyun.oss.model.PutObjectResult;
import com.ytell.zhiyuan.common.ali.OssProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

@Service
@Slf4j
@EnableConfigurationProperties(OssProperties.class)

public class AliOSSService {

    private static final Pattern NAMESPACE_PATTERN = Pattern.compile("[A-Za-z0-9][A-Za-z0-9_-]{0,63}");

    public static class OssUnavailableException extends IllegalStateException {
        public OssUnavailableException() {
            super("OSS is disabled for this environment");
        }
    }

    @Autowired
    private OssProperties ossProperties;
    private OSS ossClient;

    @PostConstruct
    public void init() {
        namespace();
        if (!ossProperties.isEnabled()) {
            log.info("OSS disabled for this environment");
            return;
        }
        log.info("初始化OSS客户端，endpoint: {}, region: {}, bucket: {}",
                ossProperties.getEndpoint(),
                ossProperties.getRegion(),
                ossProperties.getBucket());

        // 创建OSSClient实例。
        ClientBuilderConfiguration clientBuilderConfiguration = new ClientBuilderConfiguration();
        clientBuilderConfiguration.setSignatureVersion(SignVersion.V4);
        //
        DefaultCredentialProvider credentialsProvider = CredentialsProviderFactory.newDefaultCredentialProvider(ossProperties.getAccessKeyId(),ossProperties.getAccessKeySecret());

        OSS client = OSSClientBuilder.create()
                .endpoint(ossProperties.getEndpoint())
                .credentialsProvider(credentialsProvider)
                .clientConfiguration(clientBuilderConfiguration)
                .region(ossProperties.getRegion())
                .build();

        this.ossClient = client;

        log.info("OSS客户端初始化完成");
    }

    /**
     * 获取临时访问OSS签名
     * 前端-用签名的方式上传文件
     * 官方链接地址：https://help.aliyun.com/document_detail/31926.html?spm=a2c4g.11186623.6.1737.5f3e3bd36kleqs
     */
    public Map<String, String> getSignature(String dir) {
        requireEnabled();
        String scopedDir = scopedKey(dir, true);
        Map<String, String> respMap = new LinkedHashMap<>();
        //host的格式为 bucketName.endpoint
        String host = "https://" + ossProperties.getBucket() + "." + ossProperties.getEndpoint();
        try {
            //设置过期时间为半小时1800L
            long expireTime = 60 * 30;
            long expireEndTime = System.currentTimeMillis() + expireTime * 1000;
            Date expiration = new Date(expireEndTime);
            // PostObject请求最大可支持的文件大小为5 GB，即CONTENT_LENGTH_RANGE为5*1024*1024*1024。
            PolicyConditions policyConditions = new PolicyConditions();
            policyConditions.addConditionItem(PolicyConditions.COND_CONTENT_LENGTH_RANGE, 0, 200 * 1024 * 1024);
            policyConditions.addConditionItem(MatchMode.StartWith, PolicyConditions.COND_KEY, scopedDir);

            String postPolicy = ossClient.generatePostPolicy(expiration, policyConditions);
            byte[] binaryData = postPolicy.getBytes(StandardCharsets.UTF_8);
            String encodedPolicy = BinaryUtil.toBase64String(binaryData);
            String postSignature = ossClient.calculatePostSignature(postPolicy);

            respMap.put("accessid", ossProperties.getAccessKeyId());
            respMap.put("bucket", ossProperties.getBucket());
            respMap.put("policy", encodedPolicy);
            respMap.put("signature", postSignature);
            respMap.put("dir", scopedDir);
            respMap.put("host", host);
            respMap.put("expire", String.valueOf(expireEndTime / 1000));
        } catch (Exception e) {
            log.error("getSignature:error", e);
        }
        return respMap;
    }

    /***
     * 上传文件
     * @param fileName 文件名
     * @param file 文件
     */
    public String uploadFile(String fileName, File file) {
        requireEnabled();
        String objectKey = scopedKey(fileName);
        log.info("开始上传文件到OSS，bucket: {}, fileName: {}, fileSize: {} bytes",
                ossProperties.getBucket(), objectKey, file.length());

        // 上传文件
        PutObjectResult putObjectResult = ossClient.putObject(ossProperties.getBucket(), objectKey, file);

        log.info("文件上传成功，ETag: {}", putObjectResult.getETag());
        return putObjectResult.getETag();
    }


    /***
     * 获取下载地址
     */
    public String getDownloadUrl(String fileName) {
        requireEnabled();
        // 设置URL过期时间为10年
        Date expiration = new Date(System.currentTimeMillis() + 3600L * 1000 * 24 * 20 * 365);
        // 生成URL
        URL url = ossClient.generatePresignedUrl(ossProperties.getBucket(), scopedKey(fileName), expiration);
        String s = url.toString().substring(0, url.toString().indexOf("?"));
        //生产环境中，OSS地址为内网地址，在此处转成外网地址
        if (s.contains("-internal")) {
            s = s.replace("-internal", "");
        }
        return s;
    }

    /***
     * 下载文件到本地
     * @param fileName OSS文件名
     * @param localFilePath 本地文件路径
     * @return 是否下载成功
     */
    public boolean downloadFile(String fileName, String localFilePath) {
        if (!ossProperties.isEnabled()) {
            log.info("OSS download skipped because OSS is disabled");
            return false;
        }
        String objectKey = scopedKey(fileName);
        log.info("开始从OSS下载文件，bucket: {}, fileName: {}, localFilePath: {}",
                ossProperties.getBucket(), objectKey, localFilePath);

        try {
            // 获取OSS对象
            OSSObject ossObject = ossClient.getObject(ossProperties.getBucket(), objectKey);

            // 创建本地文件目录
            File localFile = new File(localFilePath);
            File parentDir = localFile.getParentFile();
            if (!parentDir.exists()) {
                parentDir.mkdirs();
            }

            // 下载文件到本地
            try (InputStream inputStream = ossObject.getObjectContent();
                 FileOutputStream outputStream = new FileOutputStream(localFile)) {

                byte[] buffer = new byte[1024];
                int bytesRead;
                while ((bytesRead = inputStream.read(buffer)) != -1) {
                    outputStream.write(buffer, 0, bytesRead);
                }
            }

            log.info("文件下载成功，本地路径: {}, 文件大小: {} bytes", localFilePath, localFile.length());
            return true;

        } catch (Exception e) {
            log.error("从OSS下载文件失败，fileName: {}, localFilePath: {}", fileName, localFilePath, e);
            return false;
        }
    }

    private void requireEnabled() {
        if (!ossProperties.isEnabled()) {
            throw new OssUnavailableException();
        }
    }

    private String scopedKey(String key) {
        return scopedKey(key, false);
    }

    private String scopedKey(String key, boolean directory) {
        String namespace = namespace();
        if (namespace == null) {
            return key;
        }
        if (key == null || key.trim().isEmpty() || key.startsWith("/") || key.indexOf('\\') >= 0) {
            throw new IllegalArgumentException("OSS key must be relative within ali.oss.namespace");
        }
        String[] segments = key.split("/", -1);
        for (int i = 0; i < segments.length; i++) {
            String segment = segments[i];
            if (segment.isEmpty() && directory && i == segments.length - 1) {
                continue;
            }
            if (segment.isEmpty() || ".".equals(segment) || "..".equals(segment)) {
                throw new IllegalArgumentException("OSS key must be relative within ali.oss.namespace");
            }
        }
        return namespace + "/" + key;
    }

    private String namespace() {
        String value = ossProperties.getNamespace();
        if (value == null || value.isEmpty()) {
            return null;
        }
        if (!NAMESPACE_PATTERN.matcher(value).matches()) {
            throw new IllegalArgumentException("ali.oss.namespace must be one safe path segment");
        }
        return value;
    }


}
