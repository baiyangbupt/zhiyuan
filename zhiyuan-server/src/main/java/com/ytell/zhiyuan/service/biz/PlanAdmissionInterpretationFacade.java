package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationReq;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.InterpretationEntryDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 录取解读门面（J2b）：只读加载方案 → 组输入条目 → 调纯函数。
 *
 * <p>身份只从受信参数（tenantId/chatSessionId）来；不接收模型传入的会话号。
 * 版本不符直接 `stale_interpretation`，避免拿旧方案解释新状态。</p>
 */
@Service
public class PlanAdmissionInterpretationFacade {

    public static final String STALE_INTERPRETATION = "stale_interpretation";
    public static final String PLAN_VERSION_REQUIRED = "plan_version_required";

    @Autowired
    private PlanningStateService planningStateService;

    private final PlanAdmissionInterpretationService interpretationService =
            new PlanAdmissionInterpretationService();

    public AdmissionInterpretationRes interpret(Long tenantId, Long chatSessionId,
                                                AdmissionInterpretationReq req) {
        if (req == null || req.getPlanVersion() == null) {
            throw new BusinessException(400, PLAN_VERSION_REQUIRED);
        }
        PlanningStateDTO state = planningStateService.loadPlanningStateReadOnly(chatSessionId);
        if (state == null) {
            throw new BusinessException(404, "session_not_found");
        }
        int currentVersion = state.getVersion() == null ? 0 : state.getVersion();
        if (!req.getPlanVersion().equals(currentVersion)) {
            throw new BusinessException(409, STALE_INTERPRETATION);
        }
        boolean groupMode = isMajorGroupMode(state);
        if (Strings.isNullOrEmpty(req.getAdmissionMode())) {
            req.setAdmissionMode(groupMode ? "major_group" : "major");
        }
        // J5.2：解读消费统一评价 findings（drivers/caveats）；没有评价时退回纯结构解读。
        java.util.List<com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO> findings =
                state.getReviewState() == null || state.getReviewState().getFindings() == null
                        ? java.util.Collections
                        .<com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO>emptyList()
                        : state.getReviewState().getFindings();
        return interpretationService.interpret(req, buildEntries(state, groupMode), findings);
    }

    static List<InterpretationEntryDTO> buildEntries(PlanningStateDTO state, boolean groupMode) {
        List<InterpretationEntryDTO> entries = new ArrayList<InterpretationEntryDTO>();
        if (state == null || state.getOrderedPlanState() == null) {
            return entries;
        }
        Map<String, CandidateItemDTO> byVolunteer = new HashMap<String, CandidateItemDTO>();
        if (state.getCandidatePoolState() != null
                && state.getCandidatePoolState().getItems() != null) {
            for (CandidateItemDTO candidate : state.getCandidatePoolState().getItems()) {
                if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                    byVolunteer.put(candidate.getVolunteerId(), candidate);
                }
            }
        }
        if (groupMode) {
            List<OrderedUnitDTO> units = state.getOrderedPlanState().getUnits() == null
                    ? new ArrayList<OrderedUnitDTO>()
                    : state.getOrderedPlanState().getUnits();
            for (OrderedUnitDTO unit : units) {
                if (unit == null) {
                    continue;
                }
                InterpretationEntryDTO entry = new InterpretationEntryDTO();
                entry.setLevel(InterpretationEntryDTO.LEVEL_UNIT);
                entry.setId(unit.getUnitId());
                entry.setPosition(unit.getPosition());
                entry.setSchoolName(unit.getSchoolName());
                entry.setPathTier(unit.getTier());
                entry.setSchoolRatio(unit.getSchoolEnrollRatio());
                entry.setMajorRatio(unit.getAdmissionRatio());
                if (entry.getSchoolRatio() == null || entry.getMajorRatio() == null) {
                    for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                        CandidateItemDTO candidate = byVolunteer.get(major.getVolunteerId());
                        if (candidate == null) {
                            continue;
                        }
                        if (entry.getSchoolRatio() == null) {
                            entry.setSchoolRatio(candidate.getSchoolEnrollRatio());
                        }
                        if (entry.getMajorRatio() == null) {
                            entry.setMajorRatio(candidate.getAdmissionRatio());
                        }
                    }
                }
                entries.add(entry);
            }
        } else {
            List<OrderedItemDTO> items = state.getOrderedPlanState().getItems() == null
                    ? new ArrayList<OrderedItemDTO>()
                    : state.getOrderedPlanState().getItems();
            for (OrderedItemDTO item : items) {
                if (item == null) {
                    continue;
                }
                CandidateItemDTO candidate = byVolunteer.get(item.getVolunteerId());
                InterpretationEntryDTO entry = new InterpretationEntryDTO();
                entry.setLevel(InterpretationEntryDTO.LEVEL_VOLUNTEER);
                entry.setId(item.getVolunteerId());
                entry.setPosition(item.getPosition());
                entry.setSchoolName(item.getSchoolName());
                entry.setMajorName(item.getMajorName());
                entry.setPathTier(item.getTier());
                if (candidate != null) {
                    entry.setSchoolRatio(candidate.getSchoolEnrollRatio());
                    entry.setMajorRatio(candidate.getAdmissionRatio());
                }
                entries.add(entry);
            }
        }
        return entries;
    }

    static boolean isMajorGroupMode(PlanningStateDTO state) {
        if (state == null || state.getCandidatePoolState() == null) {
            return false;
        }
        String model = state.getCandidatePoolState().getVolunteerModel();
        // 与快照 canonicalAdmissionMode 对齐：两种拼写都算组模式，避免
        // journey 说“可解读”、facade 却按 major 取 items 返回 no_plan。
        return "majorGroup".equalsIgnoreCase(model) || "major_group".equalsIgnoreCase(model);
    }

    private static <T> List<T> defaultList(List<T> value) {
        return value == null ? new ArrayList<T>() : value;
    }
}
