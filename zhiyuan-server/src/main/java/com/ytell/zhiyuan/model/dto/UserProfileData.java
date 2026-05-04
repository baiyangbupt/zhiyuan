package com.ytell.zhiyuan.model.dto;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 用户画像数据实体类
 * 对应 USER_PROFILE_KEY 返回的数据结构
 */
@Data
public class UserProfileData {

    /**
     * 正向专业意向
     */
    private MajorIntent major_intent = new MajorIntent();

    /**
     * 负向专业意向
     */
    private MajorIntent negative_major_intent = new MajorIntent();

    /**
     * 正向院校信息（新结构）
     */
    private CollegeInfo college_info = new CollegeInfo();

    /**
     * 负向院校信息（新结构）
     */
    private CollegeInfo negative_college_info = new CollegeInfo();

    /**
     * 标签信息（新结构）
     */
    private TagInfo tag_info = new TagInfo();

    /**
     * 负向标签信息（新结构）
     */
    private TagInfo negative_tag_info = new TagInfo();

    /**
     * 正向城市信息
     */
    private CityInfo city_info = new CityInfo();

    /**
     * 负向城市信息
     */
    private CityInfo negative_city_info = new CityInfo();

    /**
     * 优势学科信息
     */
    private StrengthSubjectInfo strength_subject_info = new StrengthSubjectInfo();

    /**
     * 专业意向数据结构
     */
    @Data
    public static class MajorIntent {
        /**
         * 一级专业名称列表
         */
        private List<String> level1 = Lists.newArrayList();

        /**
         * 一级专业情绪强度列表
         */
        private List<String> level1_emotion = Lists.newArrayList();

        /**
         * 二级专业名称列表
         */
        private List<String> level2 = Lists.newArrayList();

        /**
         * 二级专业情绪强度列表
         */
        private List<String> level2_emotion = Lists.newArrayList();

        /**
         * 三级专业名称列表
         */
        private List<String> level3 = Lists.newArrayList();

        /**
         * 三级专业情绪强度列表
         */
        private List<String> level3_emotion = Lists.newArrayList();

        /**
         * 一级专业代码列表
         */
        private List<String> level1_code = Lists.newArrayList();

        /**
         * 二级专业代码列表
         */
        private List<String> level2_code = Lists.newArrayList();

        /**
         * 三级专业代码列表
         */
        private List<String> level3_code = Lists.newArrayList();
    }

    /**
     * 院校信息数据结构（新）
     */
    @Data
    public static class CollegeInfo {
        /**
         * 院校名称列表
         */
        private List<String> values = Lists.newArrayList();

        /**
         * 院校情绪强度列表
         */
        private List<String> values_emotion = Lists.newArrayList();

        /**
         * 院校代码列表
         */
        private List<String> values_code = Lists.newArrayList();
    }

    /**
     * 标签信息数据结构（新）
     */
    @Data
    public static class TagInfo {
        /**
         * 标签名称列表
         */
        private List<String> values = Lists.newArrayList();

        /**
         * 标签情绪强度列表
         */
        private List<String> values_emotion = Lists.newArrayList();
    }

    /**
     * 城市信息数据结构
     */
    @Data
    public static class CityInfo {
        /**
         * 省份列表
         */
        private List<String> province = Lists.newArrayList();

        /**
         * 省份情绪强度列表
         */
        private List<String> province_emotion = Lists.newArrayList();

        /**
         * 城市列表
         */
        private List<String> city = Lists.newArrayList();

        /**
         * 城市情绪强度列表
         */
        private List<String> city_emotion = Lists.newArrayList();

        /**
         * 省份代码列表
         */
        private List<String> province_code = Lists.newArrayList();

        /**
         * 城市代码列表
         */
        private List<String> city_code = Lists.newArrayList();
    }

    /**
     * 优势学科信息数据结构
     */
    @Data
    public static class StrengthSubjectInfo {
        /**
         * 优势学科名称列表
         */
        private List<String> values = Lists.newArrayList();

        /**
         * 优势学科情绪强度列表
         */
        private List<String> values_emotion = Lists.newArrayList();

        /**
         * 优势学科代码列表
         */
        private List<String> values_code = Lists.newArrayList();
    }
}
