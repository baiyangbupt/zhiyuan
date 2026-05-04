package com.ytell.zhiyuan.common.util;

import com.ytell.zhiyuan.common.config.GaotuProperties;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
 * 志愿文件路径工具类
 * 统一管理志愿相关文件的本地路径和OSS路径
 */
@Slf4j
@Component
public class VolunteerFilePathUtil {

    @Autowired
    private GaotuProperties gaotuProperties;

    /**
     * 默认临时数据路径
     */
    private static final String DEFAULT_TEMP_DATA_PATH = "/tmpdata";

    /**
     * OSS志愿文件目录
     */
    private static final String OSS_VOLUNTEER_DIR = "session_volunteer/";

    /**
     * 本地文件名前缀
     */
    private static final String LOCAL_FILE_PREFIX = "session_volunteer_";

    /**
     * 志愿文件类型枚举
     */
    @Getter
    @AllArgsConstructor
    public enum VolunteerFileType {
        /**
         * 原始志愿数据（从高途接口获取的原始数据）
         */
        ORIGINAL("", "原始志愿数据"),

        /**
         * 最终提交数据（用户提交确认后的最终方案）
         */
        FINAL("_final", "最终提交数据"),

        /**
         * 临时推荐数据（查询推荐结果的临时数据）
         */
        TEMP_RECOMMEND("_temp", "临时推荐数据"),

        /**
         * 临时推荐摘要（轻量级元信息）
         */
        TEMP_SUMMARY("_temp_summary", "临时推荐摘要"),

        /**
         * 最终提交摘要
         */
        FINAL_SUMMARY("_final_summary", "最终提交摘要");

        /**
         * 文件名后缀
         */
        private final String suffix;

        /**
         * 描述
         */
        private final String description;
    }

    /**
     * 获取临时数据根路径
     *
     * @return 临时数据根路径
     */
    private String getTempDataPath() {
        String tempDataPath = gaotuProperties.getTempDataPath();
        if (tempDataPath == null || tempDataPath.trim().isEmpty()) {
            tempDataPath = DEFAULT_TEMP_DATA_PATH;
        }
        return tempDataPath;
    }

    /**
     * 获取志愿文件的本地路径（通用方法）
     *
     * @param chatSessionId 会话ID
     * @param fileType      文件类型
     * @return 本地文件路径，格式：/tmpdata/session_volunteer_{chatSessionId}{suffix}.json
     */
    public String getLocalFilePath(Long chatSessionId, VolunteerFileType fileType) {
        return getTempDataPath() + "/" + LOCAL_FILE_PREFIX + chatSessionId + fileType.getSuffix() + ".json";
    }

    /**
     * 获取志愿文件的OSS路径（通用方法）
     *
     * @param chatSessionId 会话ID
     * @param fileType      文件类型
     * @return OSS文件路径，格式：session_volunteer/{chatSessionId}{suffix}.json
     */
    public String getOssFilePath(Long chatSessionId, VolunteerFileType fileType) {
        return OSS_VOLUNTEER_DIR + chatSessionId + fileType.getSuffix() + ".json";
    }
}

