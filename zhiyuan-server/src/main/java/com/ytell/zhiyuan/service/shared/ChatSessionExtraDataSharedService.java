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

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
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
     * <p><b>2026-10-16 治本（review §五-42）：WHERE 不再绑整值</b>。planningState 行最大 38.4MB，
     * 旧的 {@code data_value = ?} 让 MySQL 参数包变成"旧值(WHERE)+新值(SET)"两倍 76.9MB，
     * 撞过 {@code max_allowed_packet} 64MB（PacketTooBigException→code -1）。现在 WHERE 侧改成
     * <b>字节级摘要</b> {@code LENGTH(data_value)=? AND MD5(data_value)=?}（参数 ~36B），SET 侧照旧只带
     * 新值：单包 ≈ 38.4MB，且在 64MB 上限内。判据仍是"读到的那份还在不在"——MD5 是对列字节
     * （utf8mb4 存储字节）取摘要，与整值相等<b>同义且更严</b>：{@code =} 受列 collation
     * {@code utf8mb4_0900_ai_ci} 影响大小写不敏感（"PREDICT"/"predict" 会被当成"没变过"），
     * 摘要比较是字节级的，这个口径随之收紧为正确语义（见 CAS 真库用例 ⑤）。</p>
     *
     * <p><b>data_version 槽位</b>：该列在本库是"行槽位"（uk 含 data_version，恒为 0；所有读路径
     * {@code getBySessionIdAndDataKey} 都按 version=0 取行），<b>不能当每次写自增的乐观锁用</b>——
     * 一 bump 行就对所有读者失明。所以这里保留 {@code data_version = ?} 谓词（槽位定位），
     * 并发防线由上面的字节级摘要承担。兜底：{@code current.dataVersion} 为空的历史行路径
     * （列可空）不走摘要，退回按旧值精确比较。</p>
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
                .eq(ChatSessionExtraData::getDataKey, current.getDataKey());
        if (current.getDataVersion() != null) {
            updateWrapper.lambda().eq(ChatSessionExtraData::getDataVersion, current.getDataVersion());
        }
        if (expectedDataValue == null) {
            updateWrapper.lambda().isNull(ChatSessionExtraData::getDataValue);
        } else if (current.getDataVersion() == null) {
            // 兜底：data_version 为空的历史行（列可空）槽位不可用 → 按旧值精确比较
            updateWrapper.lambda().eq(ChatSessionExtraData::getDataValue, expectedDataValue);
        } else {
            // 字节级 CAS：长度 + MD5 摘要，不整值往返（38.4MB → ~36B 参数）
            byte[] expectedBytes = expectedDataValue.getBytes(StandardCharsets.UTF_8);
            updateWrapper.apply("LENGTH(data_value) = {0} AND MD5(data_value) = {1}",
                    expectedBytes.length, md5Hex(expectedBytes));
        }
        ChatSessionExtraData patch = new ChatSessionExtraData();
        patch.setDataType(DataType.JSON_OBJECT);
        patch.setDataValue(newDataValue);
        return this.update(patch, updateWrapper);
    }

    /** 与 MySQL {@code MD5()} 对齐的小写十六进制（对列存储字节取摘要，见 {@link #updateDataValueIfUnchanged}）。 */
    private static String md5Hex(byte[] bytes) {
        try {
            byte[] digest = MessageDigest.getInstance("MD5").digest(bytes);
            char[] hex = new char[digest.length * 2];
            for (int i = 0; i < digest.length; i++) {
                int value = digest[i] & 0xFF;
                hex[i * 2] = HEX_DIGITS[value >>> 4];
                hex[i * 2 + 1] = HEX_DIGITS[value & 0x0F];
            }
            return new String(hex);
        } catch (NoSuchAlgorithmException e) {
            // MD5 是 Java 平台必备算法，到不了这里
            throw new IllegalStateException("MD5 algorithm unavailable", e);
        }
    }

    private static final char[] HEX_DIGITS = "0123456789abcdef".toCharArray();

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
