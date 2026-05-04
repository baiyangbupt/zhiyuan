package com.ytell.zhiyuan.manager.rank;

import com.alibaba.fastjson.TypeReference;
import com.google.common.base.Strings;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.config.VolunteerRankProperties;
import com.ytell.zhiyuan.common.util.JsonHttpUtil;
import com.ytell.zhiyuan.model.dto.*;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * 志愿排名服务客户端
 */
@Slf4j
@Component
@EnableConfigurationProperties(VolunteerRankProperties.class)
public class VolunteerRankClient {

    private static final String RECOMMEND_SUBMAJOR_PATH = "/gaokao-volunteer-rank/recommend_submajor";
    private static final String RECOMMEND_VOLUNTEER_PATH = "/gaokao-volunteer-rank/recommend_volunteer";
    private static final String QUERY_WEIGHT_PATH = "/gaokao-volunteer-rank/query_weight";

    @Autowired
    private VolunteerRankProperties volunteerRankProperties;

    /**
     * 获取请求头
     *
     * @return 请求头
     */
    public Map<String, String> getHeader() {
        Map<String, String> headers = Maps.newHashMap();
        if (!Strings.isNullOrEmpty(volunteerRankProperties.getEnv())) {
            headers.put("traffic-env", volunteerRankProperties.getEnv());
        }
        headers.put("content-type", "application/json");
        return headers;
    }

    /**
     * 获取热门专业推荐
     *
     * @param req 用户信息请求参数，使用CreateSessionReq数据结构
     * @return 热门专业推荐响应
     */
    public RecommendSubMajorResponse getRecommendSubMajor(RecommendSubMajorRequest req) {
        String url = volunteerRankProperties.getUrl() + RECOMMEND_SUBMAJOR_PATH;
        log.info("调用热门专业推荐接口, url: {}, req: {}", url, req);
        
        try {
            RecommendSubMajorResponse response = JsonHttpUtil.post(url, req, getHeader(), new TypeReference<RecommendSubMajorResponse>() {
            });
            log.info("热门专业推荐接口调用成功, response: {}", response);
            return response;
        } catch (Exception e) {
            log.error("调用热门专业推荐接口失败, url: {}, req: {}", url, req, e);
            throw e;
        }
    }

    /**
     * 志愿排序
     *
     * @param req 志愿排序请求参数，包含学生信息、志愿信息和用户画像信息
     * @return 排序后的志愿列表
     */
    public List<VolunteerSchoolGroup> getRecommendVolunteer(RecommendVolunteerRequest req) {
        String url = volunteerRankProperties.getUrl() + RECOMMEND_VOLUNTEER_PATH;
        log.info("调用志愿排序接口, url: {},", url);
        log.info("调用志愿排序接口, userInfo: {},", req.getStudentinfo());
        log.info("调用志愿排序接口, userProfile: {},", req.getProfileinfo());
        log.info("调用志愿排序接口, Volunteerinfo:size: {},",req.getVolunteerinfo().size());

        try {
            List<VolunteerSchoolGroup> response = JsonHttpUtil.post(url, req, getHeader(), new TypeReference<List<VolunteerSchoolGroup>>() {
            });
            log.info("志愿排序接口调用成功, response size: {}", response != null ? response.size() : 0);
            return response;
        } catch (Exception e) {
            log.error("调用志愿排序接口失败, url: {}", url, e);
            throw e;
        }
    }
    /**
     * 查询专业、学校权重
     *
     * @param queryWeightRequest 权重查询请求参数，包含用户信息、用户画像信息和查询信息
     * @return 权重查询响应
     */
    public QueryWeightResponse queryWeight(QueryWeightRequest queryWeightRequest) {
        String url = volunteerRankProperties.getUrl() + QUERY_WEIGHT_PATH;
        log.info("调用权重查询接口, url: {}, req: {}", url, queryWeightRequest);
        
        try {
            QueryWeightResponse response = JsonHttpUtil.post(url, queryWeightRequest, getHeader(), new TypeReference<QueryWeightResponse>() {
            });
            log.info("权重查询接口调用成功, response: {}", response);
            return response;
        } catch (Exception e) {
            log.error("调用权重查询接口失败, url: {}, req: {}", url, queryWeightRequest, e);
            throw e;
        }
    }
}
