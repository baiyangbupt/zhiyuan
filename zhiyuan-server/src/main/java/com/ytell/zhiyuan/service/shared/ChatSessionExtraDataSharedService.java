package com.ytell.zhiyuan.service.shared;

import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
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

    /**
     * 条件更新（CAS）：**只有那行内容仍是我们读到的那份**（{@code expectedDataValue}）才写入新值。
     *
     * <p>用途：读路径/缓存回填路径发起的落盘——legacy 懒导入、推荐 overlay 刷新。它们手里的
     * 规划状态快照可能已经被并发写（页面自举 {@code initial-plan/generate}、确认链）改新了，
     * 无条件 {@code updateById} 就是"拿旧快照整文档覆盖新行"，会把自举结果打回候选池态
     * （phase 卡 {@code candidate_generated}，见
     * {@code docs/superpowers/reviews/2026-10-06-test-www-chain-recovery.md} §六）。
     * 这里把"读到的那份还在不在"下推到 SQL 比较里，输的一方不落盘。</p>
     *
     * @param current            调用方读到的那行（用 id/chatSessionId/dataKey/dataVersion 定位）
     * @param expectedDataValue  调用方读到的 data_value；{@code null} 表示读到的是空
     * @param newDataValue       要写入的新 data_value
     * @return true=写入成功（我们赢）；false=行已被并发写过（对方赢），调用方应重读后再决定
     */
    public boolean updateDataValueIfUnchanged(ChatSessionExtraData current,
                                              String expectedDataValue,
                                              String newDataValue) {
        if (current == null || current.getId() == null) {
            return false;
        }
        UpdateWrapper<ChatSessionExtraData> updateWrapper = new UpdateWrapper<>();
        updateWrapper.lambda()
                .eq(ChatSessionExtraData::getId, current.getId())
                .eq(ChatSessionExtraData::getChatSessionId, current.getChatSessionId())
                .eq(ChatSessionExtraData::getDataKey, current.getDataKey())
                .eq(ChatSessionExtraData::getDataVersion, current.getDataVersion() == null ? 0 : current.getDataVersion());
        if (expectedDataValue == null) {
            updateWrapper.lambda().isNull(ChatSessionExtraData::getDataValue);
        } else {
            updateWrapper.lambda().eq(ChatSessionExtraData::getDataValue, expectedDataValue);
        }
        ChatSessionExtraData patch = new ChatSessionExtraData();
        patch.setDataType(DataType.JSON_OBJECT);
        patch.setDataValue(newDataValue);
        return this.update(patch, updateWrapper);
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
