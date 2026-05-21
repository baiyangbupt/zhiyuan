package com.ytell.zhiyuan.service.shared;

import com.alibaba.fastjson.JSONObject;
import com.alibaba.fastjson.TypeReference;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.mapper.PlanningBehaviorEventMapper;
import com.ytell.zhiyuan.model.dto.planning.PlanningBehaviorEventDTO;
import com.ytell.zhiyuan.model.entity.biz.PlanningBehaviorEventEntity;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Slf4j
@Service
public class PlanningBehaviorEventSharedService extends ServiceImpl<PlanningBehaviorEventMapper, PlanningBehaviorEventEntity> {

    public boolean saveBehaviorEvent(PlanningBehaviorEventDTO event) {
        if (event == null) {
            return false;
        }
        try {
            return this.save(convertToEntity(event));
        } catch (Exception ex) {
            log.warn("saveBehaviorEvent failed eventType={} chatSessionId={} eventId={}",
                    event.getEventType(), event.getChatSessionId(), event.getEventId(), ex);
            return false;
        }
    }

    public List<PlanningBehaviorEventDTO> listBySessionId(Long chatSessionId) {
        QueryWrapper<PlanningBehaviorEventEntity> queryWrapper = new QueryWrapper<PlanningBehaviorEventEntity>();
        queryWrapper.lambda().eq(PlanningBehaviorEventEntity::getChatSessionId, chatSessionId);
        queryWrapper.lambda()
                .orderByAsc(PlanningBehaviorEventEntity::getCreateTime)
                .orderByAsc(PlanningBehaviorEventEntity::getId);
        List<PlanningBehaviorEventDTO> result = Lists.newArrayList();
        for (PlanningBehaviorEventEntity entity : this.list(queryWrapper)) {
            result.add(convertToDto(entity));
        }
        return result;
    }

    public PlanningBehaviorEventDTO getLatestBySessionIdAndEventType(Long chatSessionId, String eventType) {
        QueryWrapper<PlanningBehaviorEventEntity> queryWrapper = new QueryWrapper<PlanningBehaviorEventEntity>();
        queryWrapper.lambda().eq(PlanningBehaviorEventEntity::getChatSessionId, chatSessionId);
        queryWrapper.lambda().eq(PlanningBehaviorEventEntity::getEventType, eventType);
        queryWrapper.lambda()
                .orderByDesc(PlanningBehaviorEventEntity::getCreateTime)
                .orderByDesc(PlanningBehaviorEventEntity::getId);
        queryWrapper.lambda().last(" limit 1");
        PlanningBehaviorEventEntity entity = this.getOne(queryWrapper);
        return convertToDto(entity);
    }

    private PlanningBehaviorEventEntity convertToEntity(PlanningBehaviorEventDTO event) {
        PlanningBehaviorEventEntity entity = new PlanningBehaviorEventEntity();
        entity.setEventId(Strings.isNullOrEmpty(event.getEventId()) ? UUID.randomUUID().toString() : event.getEventId());
        entity.setChatSessionId(event.getChatSessionId());
        entity.setTenantId(event.getTenantId());
        entity.setEventType(event.getEventType());
        entity.setMode(event.getMode());
        entity.setPlanVersion(event.getPlanVersion());
        entity.setGenerationMode(event.getGenerationMode());
        entity.setVolunteerIdsJson(JSONObject.toJSONString(defaultList(event.getVolunteerIds())));
        entity.setUnitIdsJson(JSONObject.toJSONString(defaultList(event.getUnitIds())));
        entity.setFromPositionsJson(JSONObject.toJSONString(defaultMap(event.getFromPositions())));
        entity.setToPositionsJson(JSONObject.toJSONString(defaultMap(event.getToPositions())));
        entity.setTier(event.getTier());
        entity.setAdmissionRatio(event.getAdmissionRatio());
        entity.setSchoolName(event.getSchoolName());
        entity.setMajorName(event.getMajorName());
        entity.setSortKey(event.getSortKey());
        entity.setPositiveFeedback(Boolean.TRUE.equals(event.getPositiveFeedback()));
        entity.setSnapshotDigest(event.getSnapshotDigest());
        entity.setEventPayloadJson(event.getEventPayloadJson());
        entity.setCreateTime(parseCreatedAt(event.getCreatedAt()));
        return entity;
    }

    private PlanningBehaviorEventDTO convertToDto(PlanningBehaviorEventEntity entity) {
        if (entity == null) {
            return null;
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(entity.getEventId());
        event.setChatSessionId(entity.getChatSessionId());
        event.setTenantId(entity.getTenantId());
        event.setEventType(entity.getEventType());
        event.setMode(entity.getMode());
        event.setPlanVersion(entity.getPlanVersion());
        event.setGenerationMode(entity.getGenerationMode());
        event.setVolunteerIds(parseList(entity.getVolunteerIdsJson()));
        event.setUnitIds(parseList(entity.getUnitIdsJson()));
        event.setFromPositions(parseMap(entity.getFromPositionsJson()));
        event.setToPositions(parseMap(entity.getToPositionsJson()));
        event.setTier(entity.getTier());
        event.setAdmissionRatio(entity.getAdmissionRatio());
        event.setSchoolName(entity.getSchoolName());
        event.setMajorName(entity.getMajorName());
        event.setSortKey(entity.getSortKey());
        event.setPositiveFeedback(entity.getPositiveFeedback());
        event.setSnapshotDigest(entity.getSnapshotDigest());
        event.setEventPayloadJson(entity.getEventPayloadJson());
        event.setCreatedAt(formatCreatedAt(entity.getCreateTime()));
        return event;
    }

    private List<String> parseList(String json) {
        if (Strings.isNullOrEmpty(json)) {
            return Lists.newArrayList();
        }
        try {
            List<String> values = JSONObject.parseArray(json, String.class);
            return values == null ? Lists.newArrayList() : values;
        } catch (Exception ex) {
            log.warn("parse behavior event list failed json={}", json, ex);
            return Lists.newArrayList();
        }
    }

    private Map<String, Integer> parseMap(String json) {
        if (Strings.isNullOrEmpty(json)) {
            return com.google.common.collect.Maps.newHashMap();
        }
        try {
            Map<String, Integer> values = JSONObject.parseObject(json, new TypeReference<Map<String, Integer>>() {
            });
            return values == null ? com.google.common.collect.Maps.newHashMap() : values;
        } catch (Exception ex) {
            log.warn("parse behavior event map failed json={}", json, ex);
            return com.google.common.collect.Maps.newHashMap();
        }
    }

    private List<String> defaultList(List<String> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private Map<String, Integer> defaultMap(Map<String, Integer> values) {
        return values == null ? com.google.common.collect.Maps.newHashMap() : values;
    }

    private Date parseCreatedAt(String createdAt) {
        if (Strings.isNullOrEmpty(createdAt)) {
            return null;
        }
        try {
            return Date.from(OffsetDateTime.parse(createdAt).toInstant());
        } catch (Exception ex) {
            log.warn("parseCreatedAt failed createdAt={}", createdAt, ex);
            return null;
        }
    }

    private String formatCreatedAt(Date createTime) {
        if (createTime == null) {
            return OffsetDateTime.now(ZoneId.systemDefault()).toString();
        }
        return OffsetDateTime.ofInstant(createTime.toInstant(), ZoneId.systemDefault()).toString();
    }
}
