package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Joiner;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.JsonDataCleanUtil;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil.VolunteerFileType;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.ProgramPageReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerSourceDataSnapshot;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.io.FileUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Service
public class VolunteerSourceDataSyncService {

    private static final List<String> REMOVE_FIELD_LIST = Lists.newArrayList(
            "enrollAdvice",
            "converProcess",
            "enrollMajorSubtitle",
            "enrollMajorId"
    );
    private static final Map<String, JsonDataCleanUtil.StringProcessor> STRING_PROCESSORS = Maps.newHashMap();

    static {
        STRING_PROCESSORS.put("score", JsonDataCleanUtil.FLOAT_TO_INT_PROCESSOR);
        STRING_PROCESSORS.put("enrollRatio", JsonDataCleanUtil.PERCENTAGE_PROCESSOR);
    }

    @Autowired
    private ChatSessionSharedService chatSessionSharedService;
    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    @Autowired
    private GaotuService gaotuService;
    @Autowired
    private VolunteerFilePathUtil volunteerFilePathUtil;
    @Autowired
    private VolunteerFileAsyncService volunteerFileAsyncService;

    public VolunteerSourceDataSnapshot fetchLatestSourceData(Long tenantId,
                                                             Long chatSessionId,
                                                             boolean persist) {
        ChatSession chatSession = chatSessionSharedService.getById(chatSessionId);
        if (chatSession == null) {
            throw new BusinessException(404, "会话不存在");
        }
        CreateSessionReq scoreDetail = loadSessionScoreDetail(chatSessionId);
        ProgramPageReq programPageReq = toProgramQuery(chatSession, scoreDetail);

        long queryStart = System.currentTimeMillis();
        JSONObject fullData = gaotuService.queryAllProgramData(programPageReq);
        log.info("fetchLatestVolunteerSourceData step=queryAllProgramData tenantId={} chatSessionId={} persist={} costMs={}",
                tenantId, chatSessionId, persist, System.currentTimeMillis() - queryStart);

        Object cleanData = JsonDataCleanUtil.cleanJsonDataWithStringProcessing(
                fullData,
                REMOVE_FIELD_LIST,
                null,
                STRING_PROCESSORS
        );
        String dataJson = JSON.toJSONString(cleanData);
        VolunteerDataDTO volunteerData = JSONObject.parseObject(dataJson, VolunteerDataDTO.class);
        if (volunteerData == null || volunteerData.getDetailList() == null) {
            throw new BusinessException(110, "加载最新志愿数据失败");
        }

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setChatSessionId(chatSessionId);
        snapshot.setFetchedAt(OffsetDateTime.now().toString());
        snapshot.setSourceDataHash(buildDigest(dataJson));
        snapshot.setVolunteerData(volunteerData);

        String localFilePath = volunteerFilePathUtil.getLocalFilePath(chatSessionId, VolunteerFileType.ORIGINAL);
        String ossFileName = volunteerFilePathUtil.getOssFilePath(chatSessionId, VolunteerFileType.ORIGINAL);
        snapshot.setLocalFilePath(localFilePath);
        snapshot.setOssFileName(ossFileName);
        if (persist) {
            persistSourceData(tenantId, chatSessionId, localFilePath, ossFileName, dataJson);
        }
        return snapshot;
    }

    private CreateSessionReq loadSessionScoreDetail(Long chatSessionId) {
        ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId,
                ChatSessionExtraDataConstants.USER_SCORE_KEY
        );
        if (extraData == null || Strings.isNullOrEmpty(extraData.getDataValue())) {
            throw new BusinessException(404, "用户分数信息不存在");
        }
        return JSONObject.parseObject(extraData.getDataValue(), CreateSessionReq.class);
    }

    private ProgramPageReq toProgramQuery(ChatSession chatSession, CreateSessionReq createSessionReq) {
        ProgramPageReq req = new ProgramPageReq();
        req.setMemberId(Long.valueOf(chatSession.getUserId()));
        req.setBatch(createSessionReq.getBatch().getCode());
        req.setAreaId(createSessionReq.getProvince().getCode());
        req.setScore(createSessionReq.getTotalScore());
        req.setYear(String.valueOf(createSessionReq.getExamYear()));

        List<String> subjectForbiddenList = Lists.newArrayList("08", "10", "11");
        List<String> subjectCodeList = createSessionReq.getSubjectScoreList().stream()
                .filter(one -> !subjectForbiddenList.contains(one.getSubject()))
                .map(CreateSessionReq.SubjectScore::getSubject)
                .sorted()
                .collect(Collectors.toList());
        req.setSubjects(Joiner.on("").join(subjectCodeList));
        req.setSubjectType(createSessionReq.getSubjectType().getCode());
        req.setPrepareType(createSessionReq.getPrepareType() != null
                ? createSessionReq.getPrepareType().getCode()
                : "PREDICT");
        req.setSortEnum("1");
        req.setTabType(1);
        return req;
    }

    private void persistSourceData(Long tenantId,
                                   Long chatSessionId,
                                   String localFilePath,
                                   String ossFileName,
                                   String dataJson) {
        try {
            FileUtils.writeStringToFile(new File(localFilePath), dataJson, StandardCharsets.UTF_8);
            volunteerFileAsyncService.uploadVolunteerFileToOss(tenantId, chatSessionId, ossFileName, localFilePath);
            log.info("persistLatestVolunteerSourceData success tenantId={} chatSessionId={} localFilePath={} ossFileName={}",
                    tenantId, chatSessionId, localFilePath, ossFileName);
        } catch (IOException e) {
            log.error("保存最新志愿数据失败，chatSessionId={}, localFilePath={}", chatSessionId, localFilePath, e);
            throw new BusinessException(110, "保存最新志愿数据失败");
        }
    }

    private String buildDigest(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest((value == null ? "" : value).getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder();
            for (byte b : hash) {
                builder.append(String.format("%02x", b));
            }
            return builder.toString();
        } catch (Exception e) {
            throw new BusinessException(500, "生成志愿数据摘要失败");
        }
    }
}
