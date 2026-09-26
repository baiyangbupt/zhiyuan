package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.RecommendationOverlayStateDTO;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * "区域按 ID"：候选身上带的区域 ID 必须一路带到计划单元与代表候选上。
 *
 * <p>背景（2026-09-26 探针）：组模式初始单元 `provinceId` **全为 null** ✗——单元不是没建，
 * 而是建它的代表候选在 `cloneCandidateItem` 那里把 ID 漏抄了 ✗（名字抄了 ✗、ID 没抄 ✗）。
 *
 * <p>三层各一条：候选 → 单元（4325）、候选 → 覆盖合并（7988，生产主路径 ✓）、单元 → 代表候选 ✓。
 * 名字（`provinceName`/`cityName`）在三条路上都一直是通的 ✓，所以这里只断言 ID ✓。
 */
public class PlanningStateServiceRegionIdCarryTest {

    private final PlanningStateService service = new PlanningStateService();

    @Test
    void shouldCarryRegionIdFromCandidatesToGroupPlanningUnit() {
        List<CandidateItemDTO> candidates = Lists.newArrayList(
                candidate("v1", "计算机科学与技术", "冲"),
                candidate("v2", "软件工程", "稳"));

        List<PlanningUnitDTO> units = ReflectionTestUtils.invokeMethod(service,
                "groupCandidatesToPlanningUnits", candidates, 2);

        assertEquals(1, units.size(), "同一所学校（同 planSchoolDataId）应归一为一个单元");
        assertEquals("110000", units.get(0).getProvinceId(), "单元的省份 ID 要来自候选");
        assertEquals("110100", units.get(0).getCityId(), "单元的城市 ID 要来自候选");
    }

    @Test
    void shouldCarryRegionIdThroughOverlayMerge() {
        RecommendationOverlayStateDTO overlay = new RecommendationOverlayStateDTO();
        RecommendationOverlayStateDTO.Item item = new RecommendationOverlayStateDTO.Item();
        item.setVolunteerId("v1");
        item.setFinalScore(88D);
        overlay.getItems().add(item);

        List<CandidateItemDTO> merged = ReflectionTestUtils.invokeMethod(service,
                "mergeOverlayIntoCandidates", Lists.newArrayList(candidate("v1", "计算机科学与技术", "冲")), overlay, null);

        assertEquals(1, merged.size());
        assertEquals("110000", merged.get(0).getProvinceId(), "覆盖合并后候选仍要带省份 ID");
        assertEquals("110100", merged.get(0).getCityId(), "覆盖合并后候选仍要带城市 ID");
    }

    @Test
    void shouldCarryRegionIdFromUnitToRepresentativeCandidate() {
        PlanningUnitDTO unit = new PlanningUnitDTO();
        unit.setUnitId("psd-1");
        unit.setPlanSchoolDataId("psd-1");
        unit.setSchoolName("测试大学");
        unit.setProvinceName("北京");
        unit.setCityName("北京");
        unit.setProvinceId("110000");
        unit.setCityId("110100");

        CandidateItemDTO representative = ReflectionTestUtils.invokeMethod(service,
                "toPlanningUnitRepresentativeCandidate", unit);

        assertEquals("110000", representative.getProvinceId(), "单元回代成代表候选时省份 ID 不能丢");
        assertEquals("110100", representative.getCityId(), "单元回代成代表候选时城市 ID 不能丢");
    }

    private static CandidateItemDTO candidate(String volunteerId, String majorName, String tier) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId("psd-1");
        candidate.setSchoolId("school-1");
        candidate.setSchoolName("测试大学");
        candidate.setProvinceName("北京");
        candidate.setCityName("北京");
        candidate.setProvinceId("110000");
        candidate.setCityId("110100");
        candidate.setMajorId("major-" + volunteerId);
        candidate.setMajorName(majorName);
        candidate.setTier(tier);
        candidate.setFinalScore(80D);
        candidate.setAdmissionRatio(0.5D);
        return candidate;
    }
}
