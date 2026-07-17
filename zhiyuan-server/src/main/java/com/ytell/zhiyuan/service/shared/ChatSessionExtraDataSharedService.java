package com.ytell.zhiyuan.service.shared;

import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.mapper.ChatSessionExtraDataMapper;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ChatSessionExtraDataSharedService extends ServiceImpl<ChatSessionExtraDataMapper, ChatSessionExtraData> {
    public List<ChatSessionExtraData> getBySessionId(Long sessionId) {
        QueryWrapper<ChatSessionExtraData> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(ChatSessionExtraData::getChatSessionId, sessionId);
        return this.list(queryWrapper);
    }

    public ChatSessionExtraData getBySessionIdAndDataKey(Long sessionId, String dataKey) {
        return this.getBySessionIdAndDataKeyAndVersion(sessionId, dataKey, 0);
    }

    public ChatSessionExtraData lockBySessionIdAndDataKey(Long sessionId, String dataKey) {
        QueryWrapper<ChatSessionExtraData> queryWrapper = new QueryWrapper<ChatSessionExtraData>();
        queryWrapper.lambda().eq(ChatSessionExtraData::getChatSessionId, sessionId);
        queryWrapper.lambda().eq(ChatSessionExtraData::getDataKey, dataKey);
        queryWrapper.lambda().eq(ChatSessionExtraData::getDataVersion, 0);
        queryWrapper.last("limit 1 for update");
        return this.getOne(queryWrapper);
    }

    public ChatSessionExtraData getBySessionIdAndDataKeyAndVersion(Long sessionId, String dataKey, Integer version) {
        QueryWrapper<ChatSessionExtraData> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(ChatSessionExtraData::getChatSessionId, sessionId);
        queryWrapper.lambda().eq(ChatSessionExtraData::getDataKey, dataKey);
        queryWrapper.lambda().eq(ChatSessionExtraData::getDataVersion, version);
        return this.getOne(queryWrapper);
    }

    public List<ChatSessionExtraData> getBySessionIdAndDataKeyAndVersionList(Long sessionId, String dataKey, List<Integer> versions) {
        QueryWrapper<ChatSessionExtraData> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(ChatSessionExtraData::getChatSessionId, sessionId);
        queryWrapper.lambda().eq(ChatSessionExtraData::getDataKey, dataKey);
        queryWrapper.lambda().in(ChatSessionExtraData::getDataVersion, versions);
        queryWrapper.lambda().orderByAsc(ChatSessionExtraData::getDataVersion);
        return this.list(queryWrapper);
    }

    public List<ChatSessionExtraData> getBySessionIdAndDataKeyList(Long sessionId, List<String> keyList, Integer version) {
        QueryWrapper<ChatSessionExtraData> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(ChatSessionExtraData::getChatSessionId, sessionId);
        queryWrapper.lambda().in(ChatSessionExtraData::getDataKey, keyList);
        queryWrapper.lambda().eq(ChatSessionExtraData::getDataVersion, version);
        return this.list(queryWrapper);
    }

    public ChatSessionExtraData getBySessionIdAndDataKeyLastVersion(Long sessionId, String key) {
        QueryWrapper<ChatSessionExtraData> queryWrapper = new QueryWrapper<>();
        queryWrapper.lambda().eq(ChatSessionExtraData::getChatSessionId, sessionId);
        queryWrapper.lambda().eq(ChatSessionExtraData::getDataKey, key);
        queryWrapper.lambda().orderByDesc(ChatSessionExtraData::getDataVersion);
        queryWrapper.lambda().last(" limit 1");
        return this.getOne(queryWrapper);
    }

    public void saveOrUpdateSessionStatus(Long chatSessionId, SessionStatus sessionStatus) {
        JSONObject job = new JSONObject();
        job.put("sessionStatus", sessionStatus);
        ChatSessionExtraData extraData = new ChatSessionExtraData();
        extraData.setChatSessionId(chatSessionId);
        extraData.setDataKey(ChatSessionExtraDataConstants.USER_SESSION_SITUATION_KEY);
        extraData.setDataType(DataType.JSON_OBJECT);
        extraData.setDataValue(job.toJSONString());
        ChatSessionExtraData extraDataDB = this.getBySessionIdAndDataKey(chatSessionId, extraData.getDataKey());
        if (extraDataDB == null) {
            this.save(extraData);
        } else {
            extraData.setId(extraDataDB.getId());
            this.updateById(extraData);
        }
    }
}
