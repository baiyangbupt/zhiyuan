package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.manager.MajorExtraDataManager;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolRefDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.service.shared.PlanningBehaviorEventSharedService;
import com.ytell.zhiyuan.service.shared.PlanningDataFreshnessScheduleSharedService;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;

import java.io.Serializable;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 池状态瘦身·切片1（review §五-54）：
 * {@code candidatePoolState} 从 {@code planningState} 行拆到独立 {@code planningCandidatePool} 行。
 *
 * <p>覆盖四个必测面：①legacy 双读（旧内联格式照读，池行无涉）；②拆分后读回填 shape 一致
 * （items 全量回归、/session/state 对外 JSON 形状不变）；③写路径同事务语义（先 CAS 池行、
 * 再写小行；池行输=整体不写连小行都不碰，小行输=池行同事务补偿还原/删除）；④回滚开关
 * （{@code planning.candidate-pool.split.enabled=false} 回落内联整文档写）。另钉懒迁移、
 * "池未变不重写池行"、读回填 CAS 扩到池行、降级（池行缺失）几条行为。</p>
 *
 * <p>夹具：多行替身存储（按 data_key 存 planningState / planningCandidatePool 两行），CAS 语义
 * 与真库一致（id 匹配 + 期望值逐字节相等才写）；每次 CAS **尝试**与 insert/delete 记进
 * {@link #writes}（"先池后小"、"小行压根没碰"这类顺序断言用它）。</p>
 */
public class PlanningStateServiceCandidatePoolSplitTest {

    private static final Long SESSION_ID = 1L;
    private static final String STATE_KEY = ChatSessionExtraDataConstants.PLANNING_STATE_KEY;
    private static final String POOL_KEY = ChatSessionExtraDataConstants.PLANNING_CANDIDATE_POOL_KEY;

    private PlanningStateService planningStateService;
    private ChatSessionExtraDataSharedService shared;
    /** 替身存储：data_key → 行。 */
    private Map<String, ChatSessionExtraData> rows;
    /** 落盘轨迹：insert:<key> / cas_try:<key> / delete:<key>（按发生顺序）。 */
    private List<String> writes;
    private AtomicLong idGenerator;

    @BeforeEach
    void setUp() {
        planningStateService = new PlanningStateService();
        rows = new HashMap<String, ChatSessionExtraData>();
        writes = new ArrayList<String>();
        idGenerator = new AtomicLong(1000L);
        shared = Mockito.mock(ChatSessionExtraDataSharedService.class);

        when(shared.getBySessionIdAndDataKey(eq(SESSION_ID), anyString()))
                .thenAnswer(invocation -> rows.get(invocation.getArgument(1)));
        when(shared.save(any(ChatSessionExtraData.class))).thenAnswer(invocation -> {
            ChatSessionExtraData data = invocation.getArgument(0);
            if (rows.containsKey(data.getDataKey())) {
                // 唯一键 uk_chat_session_id_data_key_data_version（并发首建防线）
                throw new DuplicateKeyException("duplicate " + data.getDataKey());
            }
            ChatSessionExtraData stored = copyRow(data);
            stored.setId(idGenerator.getAndIncrement());
            data.setId(stored.getId());
            rows.put(stored.getDataKey(), stored);
            writes.add("insert:" + stored.getDataKey());
            return true;
        });
        Mockito.doAnswer(invocation -> {
            Serializable id = invocation.getArgument(0);
            ChatSessionExtraData removed = null;
            for (ChatSessionExtraData row : rows.values()) {
                if (row.getId() != null && row.getId().equals(Long.valueOf(String.valueOf(id)))) {
                    removed = row;
                    break;
                }
            }
            if (removed != null) {
                rows.remove(removed.getDataKey());
                writes.add("delete:" + removed.getDataKey());
            }
            return true;
        }).when(shared).removeById(any(Serializable.class));
        when(shared.updateDataValueIfUnchanged(any(ChatSessionExtraData.class), any(), any()))
                .thenAnswer(invocation -> {
                    ChatSessionExtraData current = invocation.getArgument(0);
                    String expected = invocation.getArgument(1);
                    String newValue = invocation.getArgument(2);
                    if (current == null) {
                        return false;
                    }
                    writes.add("cas_try:" + current.getDataKey());
                    ChatSessionExtraData stored = rows.get(current.getDataKey());
                    if (stored == null || stored.getId() == null || current.getId() == null
                            || !stored.getId().equals(current.getId())) {
                        return false;
                    }
                    boolean sameValue = expected == null
                            ? stored.getDataValue() == null
                            : expected.equals(stored.getDataValue());
                    if (!sameValue) {
                        return false;
                    }
                    stored.setDataValue(newValue);
                    return true;
                });

        MajorExtraDataManager majorExtraDataManager = new MajorExtraDataManager();
        majorExtraDataManager.init();
        ReflectionTestUtils.setField(planningStateService, "chatSessionExtraDataSharedService", shared);
        ReflectionTestUtils.setField(planningStateService, "chatSessionSharedService",
                Mockito.mock(ChatSessionSharedService.class));
        ReflectionTestUtils.setField(planningStateService, "planningBehaviorEventSharedService",
                Mockito.mock(PlanningBehaviorEventSharedService.class));
        ReflectionTestUtils.setField(planningStateService, "volunteerDataProvider",
                Mockito.mock(VolunteerDataProvider.class));
        ReflectionTestUtils.setField(planningStateService, "planningExcelExportBuilder", new PlanningExcelExportBuilder());
        ReflectionTestUtils.setField(planningStateService, "volunteerBizService", Mockito.mock(VolunteerBizService.class));
        ReflectionTestUtils.setField(planningStateService, "volunteerSourceDataSyncService",
                Mockito.mock(VolunteerSourceDataSyncService.class));
        ReflectionTestUtils.setField(planningStateService, "planningDataFreshnessScheduleSharedService",
                Mockito.mock(PlanningDataFreshnessScheduleSharedService.class));
        ReflectionTestUtils.setField(planningStateService, "volunteerIntervalService", new VolunteerIntervalService());
        ReflectionTestUtils.setField(planningStateService, "majorExtraDataManager", majorExtraDataManager);
        ReflectionTestUtils.setField(planningStateService, "schoolManager", Mockito.mock(SchoolManager.class));
        // 拆分开关：Spring @Value 默认 true；new 构造的字段初值 false（既有单测走内联），
        // 本用例显式置 true 测拆分路径，回滚开关用例再置回 false
        ReflectionTestUtils.setField(planningStateService, "candidatePoolSplitEnabled", true);
    }

    // ------------------------------------------------------------------ ①legacy 双读

    @Test
    void shouldReadLegacyInlineStateWithoutTouchingPoolRow() {
        PlanningStateDTO legacy = new PlanningStateDTO();
        legacy.setCandidatePoolState(poolWith("v1", "v2"));
        legacy.getDataFreshnessState().setDataHash("hash-legacy");
        seedRow(STATE_KEY, JSONObject.toJSONString(legacy));

        PlanningStateDTO state = planningStateService.getPlanningState(SESSION_ID);

        assertEquals(2, state.getCandidatePoolState().getItems().size());
        assertNull(state.getCandidatePoolRef());
        // 旧内联格式照读：根本不读池行（双读语义的"内联不动池行"半边）
        verify(shared, never()).getBySessionIdAndDataKey(any(Long.class), eq(POOL_KEY));
    }

    @Test
    void shouldPreferInlineItemsWhenLegacyInlineAndPoolRowBothPresent() {
        // 回滚窗口/旧 jar 写回：小行里内联 items 又回来了、池行也还在——内联优先（双读）
        PlanningStateDTO legacy = new PlanningStateDTO();
        legacy.setCandidatePoolState(poolWith("inline-1"));
        legacy.getDataFreshnessState().setDataHash("hash-legacy");
        seedRow(STATE_KEY, JSONObject.toJSONString(legacy));
        seedRow(POOL_KEY, JSONObject.toJSONString(poolWith("pool-1", "pool-2")));

        PlanningStateDTO state = planningStateService.getPlanningState(SESSION_ID);

        assertEquals(1, state.getCandidatePoolState().getItems().size());
        assertEquals("inline-1", state.getCandidatePoolState().getItems().get(0).getVolunteerId());
        verify(shared, never()).getBySessionIdAndDataKey(any(Long.class), eq(POOL_KEY));
    }

    // ------------------------------------------------------------------ ②拆分后读回填（shape 一致）

    @Test
    void shouldBackfillItemsAndPoolBaselineFromSplitRowOnRead() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        String poolValue = seedSplitState(splitState);

        PlanningStateDTO state = planningStateService.getPlanningState(SESSION_ID);

        // items 全量回归（≈40 个下游读点零改动的前提）
        assertEquals(2, state.getCandidatePoolState().getItems().size());
        // meta/summary 形状照旧
        assertEquals("2026-10-16T10:00:00+08:00", state.getCandidatePoolState().getGeneratedAt());
        assertEquals(Integer.valueOf(612), state.getCandidatePoolState().getUserScore());
        assertEquals(Integer.valueOf(2), state.getCandidatePoolState().getSummary().getEntryTotal());
        // 池行基线三件套（写路径"先 CAS 池行"的期望值载体）
        assertEquals(rows.get(POOL_KEY).getId(), state.getBaselinePoolRowId());
        assertEquals(Integer.valueOf(0), state.getBaselinePoolDataVersion());
        assertEquals(poolValue, state.getBaselinePoolDataValue());
        // 小行里的 ref 与池行内容对得上（len/md5 与 MySQL LENGTH/MD5 同口径）
        CandidatePoolRefDTO ref = state.getCandidatePoolRef();
        assertNotNull(ref);
        assertEquals(Long.valueOf(poolValue.getBytes(StandardCharsets.UTF_8).length), ref.getLen());
        assertEquals(ChatSessionExtraDataSharedService.md5Hex(poolValue.getBytes(StandardCharsets.UTF_8)), ref.getMd5());
        assertEquals(poolValue, rows.get(POOL_KEY).getDataValue());
    }

    @Test
    void shouldKeepSessionStateResponseShapeUnchangedForSplitState() throws Exception {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);

        PlanningStateDTO state = planningStateService.getPlanningState(SESSION_ID);

        // /session/state 走 Jackson：全量 items 必须在，ref/池行基线不能作为键漏出去
        // （baselineDataValue 是拆分前就有的键，其字符串值里含 "candidatePoolRef" 字面量，
        //  属既有形状；这里按解析后的顶层键断言，不按子串）
        String jackson = new ObjectMapper().writeValueAsString(state);
        JSONObject response = JSONObject.parseObject(jackson);
        assertFalse(response.containsKey("candidatePoolRef"), jackson);
        assertFalse(response.containsKey("baselinePoolRowId"), jackson);
        assertFalse(response.containsKey("baselinePoolDataVersion"), jackson);
        assertFalse(response.containsKey("baselinePoolDataValue"), jackson);
        assertEquals(2, response.getJSONObject("candidatePoolState").getJSONArray("items").size());
        assertEquals("v1", response.getJSONObject("candidatePoolState").getJSONArray("items")
                .getJSONObject(0).getString("volunteerId"));
        // fastjson（行内/导出）同样不带 ref、但带全量 items
        String fastjson = JSONObject.toJSONString(state);
        assertTrue(fastjson.contains("v1") && fastjson.contains("v2"), fastjson);
        assertFalse(fastjson.contains("candidatePoolRef"), fastjson);
    }

    @Test
    void shouldRoundTripPoolRefThroughPlanningStateRowJson() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        String poolValue = seedSplitState(splitState);

        // 小行落盘 JSON：瘦池（candidatePoolState 里没有 items）+ 顶层 candidatePoolRef，
        // 且 parseObject 能原样反解（手工拼接不破坏 JSON）
        String rowValue = rows.get(STATE_KEY).getDataValue();
        JSONObject rowJson = JSONObject.parseObject(rowValue);
        assertFalse(rowJson.getJSONObject("candidatePoolState").containsKey("items"), rowValue);
        assertTrue(rowJson.containsKey("candidatePoolRef"), rowValue);
        PlanningStateDTO parsed = JSONObject.parseObject(rowValue, PlanningStateDTO.class);
        assertNotNull(parsed.getCandidatePoolRef());
        assertEquals(Long.valueOf(poolValue.getBytes(StandardCharsets.UTF_8).length), parsed.getCandidatePoolRef().getLen());
        assertEquals(ChatSessionExtraDataSharedService.md5Hex(poolValue.getBytes(StandardCharsets.UTF_8)),
                parsed.getCandidatePoolRef().getMd5());
        // 瘦池的 meta 照抄
        assertEquals(Integer.valueOf(7), parsed.getCandidatePoolState().getSourceVersion());
        assertEquals("候选池已生成", parsed.getCandidatePoolState().getStatusMessage());
    }

    // ------------------------------------------------------------------ ③写路径：先池后小 / 同事务语义

    @Test
    void shouldSkipPoolRowWriteWhenPoolContentUnchanged() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);
        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);
        String poolValueBefore = rows.get(POOL_KEY).getDataValue();
        writes.clear();

        boolean saved = save(loaded, "unit_test");

        assertTrue(saved);
        // 池真内容没变：整个跳过池行写（"其余写点不再重写 38MB"的判定点）
        assertWrites("cas_try:" + STATE_KEY);
        assertEquals(poolValueBefore, rows.get(POOL_KEY).getDataValue());
    }

    @Test
    void shouldCasPoolRowBeforeSmallRowWhenPoolChanged() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);
        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);
        writes.clear();

        loaded.getCandidatePoolState().getItems().add(candidate("v3"));
        boolean saved = save(loaded, "unit_test");

        assertTrue(saved);
        // 写序：先 CAS 池行，再写小行
        assertWrites("cas_try:" + POOL_KEY, "cas_try:" + STATE_KEY);
        // 池行拿到新内容
        CandidatePoolStateDTO storedPool = JSONObject.parseObject(
                rows.get(POOL_KEY).getDataValue(), CandidatePoolStateDTO.class);
        assertEquals(3, storedPool.getItems().size());
        // 小行仍是"瘦池+新 ref"：候选池 items 不在行里，ref 指向新池行内容
        String rowValue = rows.get(STATE_KEY).getDataValue();
        JSONObject rowJson = JSONObject.parseObject(rowValue);
        assertFalse(rowJson.getJSONObject("candidatePoolState").containsKey("items"), rowValue);
        String storedPoolValue = rows.get(POOL_KEY).getDataValue();
        assertEquals(Long.valueOf(storedPoolValue.getBytes(StandardCharsets.UTF_8).length),
                rowJson.getJSONObject("candidatePoolRef").getLong("len"));
        assertEquals(ChatSessionExtraDataSharedService.md5Hex(storedPoolValue.getBytes(StandardCharsets.UTF_8)),
                rowJson.getJSONObject("candidatePoolRef").getString("md5"));
        // 内存态拿回完整池（serializePlanningStateRowValue 的 finally 换回同引用）
        assertEquals(3, loaded.getCandidatePoolState().getItems().size());
        assertEquals(storedPoolValue, loaded.getBaselinePoolDataValue());
    }

    @Test
    void shouldNotWriteSmallRowWhenPoolRowCasLoses() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);
        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);
        String smallRowBefore = rows.get(STATE_KEY).getDataValue();
        // 并发写者先动了池行（内容变、小行没变）——手里基线对应的池行已不是库里那份
        rows.get(POOL_KEY).setDataValue(JSONObject.toJSONString(poolWith("other-1")));
        writes.clear();

        loaded.getCandidatePoolState().getItems().add(candidate("v3"));
        boolean saved = save(loaded, "unit_test");

        assertFalse(saved);
        // 池行 CAS 输 = 整体不写：小行连 CAS 都没试过（必测③"整体回滚"）
        assertWrites("cas_try:" + POOL_KEY);
        assertEquals(smallRowBefore, rows.get(STATE_KEY).getDataValue());
    }

    @Test
    void shouldCompensatePoolRowWhenSmallRowCasLoses() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);
        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);
        String poolValueBefore = rows.get(POOL_KEY).getDataValue();
        String refMd5Before = loaded.getCandidatePoolRef().getMd5();
        String poolBaselineBefore = loaded.getBaselinePoolDataValue();
        // 并发写者动了小行（池行没动）：池行 CAS 会赢、小行 CAS 会输 → 池行必须被补偿还原
        rows.get(STATE_KEY).setDataValue("{\"concurrentWriter\":true}");
        writes.clear();

        loaded.getCandidatePoolState().getItems().add(candidate("v3"));
        boolean saved = save(loaded, "unit_test");

        assertFalse(saved);
        // 池行先写赢 → 小行输 → 池行补偿还原（同事务语义：不留"池行变了、小行没变"的错位）
        assertWrites("cas_try:" + POOL_KEY, "cas_try:" + STATE_KEY, "cas_try:" + POOL_KEY);
        assertEquals(poolValueBefore, rows.get(POOL_KEY).getDataValue());
        // 内存基线退回写前那份，调用方重放时以旧池行基线再来
        assertEquals(refMd5Before, loaded.getCandidatePoolRef().getMd5());
        assertEquals(poolBaselineBefore, loaded.getBaselinePoolDataValue());
        // 小行保持并发赢家那份（不覆盖）
        assertEquals("{\"concurrentWriter\":true}", rows.get(STATE_KEY).getDataValue());
    }

    @Test
    void shouldDeleteLazilyCreatedPoolRowWhenSmallRowCasLoses() {
        // 懒迁移首建池行后小行 CAS 输 → 本次首建的池行要删掉（不留孤儿池行）
        PlanningStateDTO legacy = new PlanningStateDTO();
        legacy.setCandidatePoolState(poolWith("v1"));
        legacy.getDataFreshnessState().setDataHash("hash-legacy");
        seedRow(STATE_KEY, JSONObject.toJSONString(legacy));
        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);
        rows.get(STATE_KEY).setDataValue("{\"concurrentWriter\":true}");
        writes.clear();

        boolean saved = save(loaded, "unit_test");

        assertFalse(saved);
        assertWrites("insert:" + POOL_KEY, "cas_try:" + STATE_KEY, "delete:" + POOL_KEY);
        assertFalse(rows.containsKey(POOL_KEY));
        assertEquals("{\"concurrentWriter\":true}", rows.get(STATE_KEY).getDataValue());
    }

    @Test
    void shouldWrapSplitSaveInTransactionWhenAmbientTransactionMissing() {
        PlatformTransactionManager transactionManager = Mockito.mock(PlatformTransactionManager.class);
        when(transactionManager.getTransaction(any())).thenReturn(Mockito.mock(TransactionStatus.class));
        ReflectionTestUtils.setField(planningStateService, "transactionManager", transactionManager);
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);
        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);

        boolean saved = save(loaded, "unit_test");

        assertTrue(saved);
        // 站点无环境事务时由 saveSplitPlanningState 自己开事务（池行与小行同事务）
        verify(transactionManager).getTransaction(any());
    }

    // ------------------------------------------------------------------ 懒迁移

    @Test
    void shouldLazilyMigrateLegacyInlineStateOnWritePathOnly() {
        PlanningStateDTO legacy = new PlanningStateDTO();
        legacy.setCandidatePoolState(poolWith("v1", "v2"));
        legacy.getDataFreshnessState().setDataHash("hash-legacy");
        seedRow(STATE_KEY, JSONObject.toJSONString(legacy));

        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);
        // 读路径不迁移：不首建池行
        assertFalse(rows.containsKey(POOL_KEY));
        assertEquals(2, loaded.getCandidatePoolState().getItems().size());
        writes.clear();

        boolean saved = save(loaded, "unit_test");

        assertTrue(saved);
        assertWrites("insert:" + POOL_KEY, "cas_try:" + STATE_KEY);
        CandidatePoolStateDTO storedPool = JSONObject.parseObject(
                rows.get(POOL_KEY).getDataValue(), CandidatePoolStateDTO.class);
        assertEquals(2, storedPool.getItems().size());
        // 迁移后的小行=瘦池+ref
        JSONObject rowJson = JSONObject.parseObject(rows.get(STATE_KEY).getDataValue());
        assertFalse(rowJson.getJSONObject("candidatePoolState").containsKey("items"));
        assertTrue(rowJson.containsKey("candidatePoolRef"));
    }

    @Test
    void shouldNotCreatePoolRowForEmptyPool() {
        PlanningStateDTO fresh = planningStateService.getPlanningState(SESSION_ID);
        assertTrue(fresh.getCandidatePoolState().getItems().isEmpty());
        writes.clear();

        boolean saved = save(fresh, "unit_test");

        assertTrue(saved);
        assertFalse(rows.containsKey(POOL_KEY));
        assertWrites("insert:" + STATE_KEY);
    }

    // ------------------------------------------------------------------ ④回滚开关

    @Test
    void shouldFallBackToInlineWriteWhenSplitSwitchOff() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);
        String poolValueBefore = rows.get(POOL_KEY).getDataValue();
        ReflectionTestUtils.setField(planningStateService, "candidatePoolSplitEnabled", false);

        // 读闸口与开关无关：拆分行照样回填出全量 items
        PlanningStateDTO loaded = planningStateService.getPlanningState(SESSION_ID);
        assertEquals(2, loaded.getCandidatePoolState().getItems().size());
        writes.clear();

        loaded.getCandidatePoolState().getItems().add(candidate("v3"));
        boolean saved = save(loaded, "unit_test");

        assertTrue(saved);
        // 回落内联：整文档单行写，池行一字不动
        assertWrites("cas_try:" + STATE_KEY);
        assertEquals(poolValueBefore, rows.get(POOL_KEY).getDataValue());
        // 行里 items 回来了、没有 ref（=拆分前形状，回滚位）
        String rowValue = rows.get(STATE_KEY).getDataValue();
        JSONObject rowJson = JSONObject.parseObject(rowValue);
        assertEquals(3, rowJson.getJSONObject("candidatePoolState").getJSONArray("items").size());
        assertFalse(rowJson.containsKey("candidatePoolRef"));
        // 再读一次：内联 items 非空 → legacy 优先，池行被无视
        PlanningStateDTO reread = planningStateService.getPlanningState(SESSION_ID);
        assertEquals(3, reread.getCandidatePoolState().getItems().size());
    }

    // ------------------------------------------------------------------ 读回填 CAS / 降级

    @Test
    void shouldWriteReadBackfillSmallRowKeepingPoolRowWhenPoolUnchanged() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        // dataHash 为空 → 读路径补写 data_freshness 快照（read_backfill），走拆分态 CAS
        seedSplitState(splitState);
        String poolValueBefore = rows.get(POOL_KEY).getDataValue();
        writes.clear();

        PlanningStateDTO state = planningStateService.getPlanningState(SESSION_ID);

        assertEquals(2, state.getCandidatePoolState().getItems().size());
        // 池行没动、小行补写成功；小行补写后仍是瘦池+ref
        assertWrites("cas_try:" + STATE_KEY);
        assertEquals(poolValueBefore, rows.get(POOL_KEY).getDataValue());
        JSONObject rowJson = JSONObject.parseObject(rows.get(STATE_KEY).getDataValue());
        assertFalse(rowJson.getJSONObject("candidatePoolState").containsKey("items"));
        assertTrue(rowJson.containsKey("candidatePoolRef"));
        assertNotNull(rowJson.getJSONObject("dataFreshnessState").getString("dataHash"));
    }

    @Test
    void shouldSkipReadBackfillWriteWhenPoolRowMovedUnderIt() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        String poolValueBefore = seedSplitState(splitState);
        // 读回填的 CAS 扩到池行：加载后池行被并发改（内容变），手里也要有池改动才会走到池行 CAS
        rows.get(POOL_KEY).setDataValue(JSONObject.toJSONString(poolWith("other-1")));
        writes.clear();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setCandidatePoolState(poolWith("v1", "v2", "v3"));
        state.setCandidatePoolRef(buildRef(poolValueBefore));
        state.setBaselinePoolRowId(rows.get(POOL_KEY).getId());
        state.setBaselinePoolDataVersion(0);
        state.setBaselinePoolDataValue(poolValueBefore);
        Boolean updated = ReflectionTestUtils.invokeMethod(planningStateService,
                "savePlanningStateIfUnchanged", SESSION_ID, rows.get(STATE_KEY), state, "read_backfill");

        assertEquals(Boolean.FALSE, updated);
        // 池行被并发改了：整体不写（补写幂等，下次读重放）
        assertWrites("cas_try:" + POOL_KEY);
    }

    @Test
    void shouldDegradeWhenPoolRowMissingButRefPresent() {
        PlanningStateDTO splitState = new PlanningStateDTO();
        splitState.setCandidatePoolState(poolWith("v1", "v2"));
        splitState.getDataFreshnessState().setDataHash("hash-split");
        seedSplitState(splitState);
        rows.remove(POOL_KEY);

        // 读不进异常：响亮 WARN 后降级保留瘦池（宁可少 items 也不把读接口打挂）
        PlanningStateDTO state = planningStateService.getPlanningState(SESSION_ID);
        assertTrue(state.getCandidatePoolState().getItems().isEmpty());
        assertNull(state.getBaselinePoolRowId());
        assertNotNull(state.getCandidatePoolRef());

        // 降级态写：池行基线未知 + 手里没 items → 不碰池行（写回会抹掉池内容），小行照写
        writes.clear();
        boolean saved = save(state, "unit_test");

        assertTrue(saved);
        assertWrites("cas_try:" + STATE_KEY);
        assertFalse(rows.containsKey(POOL_KEY));
    }

    // ------------------------------------------------------------------ helpers

    private void assertWrites(String... expected) {
        assertEquals(java.util.Arrays.asList(expected), writes, writes.toString());
    }

    private CandidateItemDTO candidate(String volunteerId) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId(volunteerId);
        item.setPlanSchoolDataId(volunteerId);
        item.setSchoolName("学校-" + volunteerId);
        item.setMajorName("专业-" + volunteerId);
        item.setTier("稳");
        return item;
    }

    private CandidatePoolStateDTO poolWith(String... volunteerIds) {
        CandidatePoolStateDTO pool = new CandidatePoolStateDTO();
        pool.setGeneratedAt("2026-10-16T10:00:00+08:00");
        pool.setSourceVersion(7);
        pool.setStatusCode("generated");
        pool.setStatusMessage("候选池已生成");
        pool.setUserScore(612);
        pool.setSourceProvinceName("海南");
        pool.setVolunteerModel("major");
        for (String volunteerId : volunteerIds) {
            pool.getItems().add(candidate(volunteerId));
        }
        pool.getSummary().setEntryTotal(volunteerIds.length);
        pool.getSummary().setTotal(volunteerIds.length);
        return pool;
    }

    private void seedRow(String dataKey, String dataValue) {
        ChatSessionExtraData row = new ChatSessionExtraData();
        row.setId(idGenerator.getAndIncrement());
        row.setChatSessionId(SESSION_ID);
        row.setDataKey(dataKey);
        row.setDataVersion(0);
        row.setDataValue(dataValue);
        rows.put(dataKey, row);
    }

    /** 拆分态：池行（整池）+ 小行（瘦池+poolRef，用生产的序列化器生成），返回池行 data_value。 */
    private String seedSplitState(PlanningStateDTO state) {
        String poolValue = JSONObject.toJSONString(state.getCandidatePoolState());
        seedRow(POOL_KEY, poolValue);
        state.setCandidatePoolRef(buildRef(poolValue));
        String rowValue = serializePlanningStateRowValue(state);
        state.setCandidatePoolRef(null);
        seedRow(STATE_KEY, rowValue);
        return poolValue;
    }

    private CandidatePoolRefDTO buildRef(String poolValue) {
        return ReflectionTestUtils.invokeMethod(planningStateService, "buildCandidatePoolRef", poolValue);
    }

    private String serializePlanningStateRowValue(PlanningStateDTO state) {
        return ReflectionTestUtils.invokeMethod(planningStateService, "serializePlanningStateRowValue", state);
    }

    private boolean save(PlanningStateDTO state, String scene) {
        Boolean saved = ReflectionTestUtils.invokeMethod(planningStateService, "savePlanningState", SESSION_ID, state, scene);
        return Boolean.TRUE.equals(saved);
    }

    private ChatSessionExtraData copyRow(ChatSessionExtraData data) {
        ChatSessionExtraData stored = new ChatSessionExtraData();
        stored.setChatSessionId(data.getChatSessionId());
        stored.setDataKey(data.getDataKey());
        stored.setDataVersion(data.getDataVersion() == null ? 0 : data.getDataVersion());
        stored.setDataType(data.getDataType());
        stored.setDataValue(data.getDataValue());
        return stored;
    }
}
