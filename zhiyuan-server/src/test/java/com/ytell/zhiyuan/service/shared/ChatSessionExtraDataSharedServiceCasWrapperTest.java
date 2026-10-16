package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.ytell.zhiyuan.mapper.ChatSessionExtraDataMapper;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collection;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * CAS（{@code updateDataValueIfUnchanged}）的 **SQL 形状钉子**（2026-10-16 治本批，review §五-42）。
 *
 * <p>背景：38.4MB 的 planningState 写走旧 SQL 时，WHERE 绑旧值 + SET 绑新值 = 76.9MB 参数包，
 * 撞过 {@code max_allowed_packet} 64MB（PacketTooBigException → code -1）。治本后 WHERE 侧只带
 * 字节级摘要（LENGTH + MD5，参数 ~36B）。这里在 wrapper 层把"旧值不再出现在绑定参数里"钉死，
 * 以免哪天被改回整值比较还不自知（真库行为由
 * {@link ChatSessionExtraDataCasSqlBehaviorIntegrationTest} 钉）。</p>
 *
 * <p>不连库：只看送进 mapper 的 {@code UpdateWrapper} 与 patch 实体（判据全部在 wrapper 里）。</p>
 */
class ChatSessionExtraDataSharedServiceCasWrapperTest {

    /** 含中文，钉 UTF-8 编码下的 MySQL 口径：md5/LENGTH 常量由 shell 独立算好写死。 */
    private static final String EXPECTED = "{\"city\":\"杭州\"}";
    private static final String EXPECTED_MD5 = "1cb621ed6940b210f292ee4de78d26b1";
    private static final int EXPECTED_BYTES = 17;

    private ChatSessionExtraDataSharedService service;
    private ChatSessionExtraDataMapper mapper;

    @BeforeEach
    void setUp() {
        // 无 Spring 容器时 MyBatis-Plus 的 lambda 列解析需要表信息（否则 lambda cache 为空）
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                ChatSessionExtraData.class);
        service = new ChatSessionExtraDataSharedService();
        mapper = Mockito.mock(ChatSessionExtraDataMapper.class);
        ReflectionTestUtils.setField(service, "baseMapper", mapper);
        when(mapper.update(any(ChatSessionExtraData.class), any())).thenReturn(1);
    }

    // ① 版本匹配（槽位 0 的现实口径）→ 写入；WHERE 是 LENGTH+MD5 摘要，不许再绑整值。
    @Test
    @SuppressWarnings("unchecked")
    void casWhereUsesByteDigestInsteadOfFullValue() {
        ChatSessionExtraData row = row(0);
        boolean won = service.updateDataValueIfUnchanged(row, EXPECTED, "{\"city\":\"宁波\"}");

        assertTrue(won);
        ArgumentCaptor<ChatSessionExtraData> entity = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        ArgumentCaptor<AbstractWrapper> wrapper = ArgumentCaptor.forClass(AbstractWrapper.class);
        verify(mapper).update(entity.capture(), wrapper.capture());

        assertEquals("{\"city\":\"宁波\"}", entity.getValue().getDataValue(), "SET 侧照旧只带新值");
        String sql = wrapper.getValue().getSqlSegment();
        assertTrue(sql.contains("MD5(data_value) = "), sql);
        assertTrue(sql.contains("LENGTH(data_value) = "), sql);
        assertTrue(sql.contains("data_version"), "槽位谓词（data_version=?）保留: " + sql);

        Collection<Object> params = wrapper.getValue().getParamNameValuePairs().values();
        assertTrue(params.contains(EXPECTED_MD5), "必须绑定 MD5 摘要: " + params);
        assertTrue(params.contains(EXPECTED_BYTES), "必须绑定字节长度: " + params);
        assertFalse(params.contains(EXPECTED), "WHERE 不许再绑整值（去整包往返的钉子）: " + params);
    }

    // ② 版本过期拒写：wrapper 把读到的版本绑进 WHERE（版本列哪天开始动，CAS 立即生效）。
    @Test
    @SuppressWarnings("unchecked")
    void casBindsTheVersionWeReadSoAStaleVersionCannotMatch() {
        when(mapper.update(any(ChatSessionExtraData.class), any())).thenReturn(0);
        boolean won = service.updateDataValueIfUnchanged(row(3), EXPECTED, "{\"city\":\"宁波\"}");

        assertFalse(won, "0 行匹配（版本/摘要任一不符）= 输");
        ArgumentCaptor<AbstractWrapper> wrapper = ArgumentCaptor.forClass(AbstractWrapper.class);
        verify(mapper).update(any(ChatSessionExtraData.class), wrapper.capture());
        String sql = wrapper.getValue().getSqlSegment();
        assertTrue(sql.contains("data_version"), sql);
        assertTrue(wrapper.getValue().getParamNameValuePairs().containsValue(3),
                "读到的 data_version=3 必须进 WHERE: " + wrapper.getValue().getParamNameValuePairs());
    }

    // ③ 期望值为 null（空壳行补值）→ 照旧 IS NULL 分支，不产生摘要参数。
    @Test
    @SuppressWarnings("unchecked")
    void casWithNullExpectationUsesIsNullBranch() {
        boolean won = service.updateDataValueIfUnchanged(row(0), null, "{\"phase\":\"imported\"}");

        assertTrue(won);
        ArgumentCaptor<AbstractWrapper> wrapper = ArgumentCaptor.forClass(AbstractWrapper.class);
        verify(mapper).update(any(ChatSessionExtraData.class), wrapper.capture());
        String sql = wrapper.getValue().getSqlSegment();
        assertTrue(sql.contains("data_value IS NULL"), sql);
        assertFalse(sql.contains("MD5(data_value)"), sql);
    }

    // ④ 兜底：data_version 为空的历史行（列可空）→ 退回按旧值精确比较，且不绑版本谓词。
    @Test
    @SuppressWarnings("unchecked")
    void casFallsBackToExactValueCompareWhenDataVersionIsNull() {
        ChatSessionExtraData row = row(null);
        boolean won = service.updateDataValueIfUnchanged(row, EXPECTED, "{\"city\":\"宁波\"}");

        assertTrue(won);
        ArgumentCaptor<AbstractWrapper> wrapper = ArgumentCaptor.forClass(AbstractWrapper.class);
        verify(mapper).update(any(ChatSessionExtraData.class), wrapper.capture());
        String sql = wrapper.getValue().getSqlSegment();
        assertTrue(sql.contains("data_value = "), "兜底分支必须按旧值比较: " + sql);
        assertFalse(sql.contains("MD5(data_value)"), sql);
        assertFalse(sql.contains("data_version"), "version 为空时槽位谓词不可用: " + sql);
        assertTrue(wrapper.getValue().getParamNameValuePairs().containsValue(EXPECTED));
    }

    private ChatSessionExtraData row(Integer version) {
        ChatSessionExtraData row = new ChatSessionExtraData();
        row.setId(42L);
        row.setChatSessionId(7L);
        row.setDataKey("planningState");
        row.setDataVersion(version);
        row.setDataValue(EXPECTED);
        return row;
    }
}
