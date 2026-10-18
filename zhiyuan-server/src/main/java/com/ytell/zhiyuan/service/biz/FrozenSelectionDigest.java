package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * S0b selection-scoped digest。
 *
 * <p>只覆盖“用户看到的选择 + 当前方案 + 硬目标/策略”，不覆盖整池版本、
 * 未选中候选顺序或软权重；候选池正常刷新不应让 pending 失效。</p>
 */
final class FrozenSelectionDigest {

    private FrozenSelectionDigest() {
    }

    static String compute(PlanningStateDTO state,
                          List<CandidateItemDTO> effectiveCandidates,
                          FixProposalDTO proposal) {
        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(state, effectiveCandidates);
        Map<String, CandidateFactDTO> facts = new LinkedHashMap<String, CandidateFactDTO>();
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            if (fact != null && !Strings.isNullOrEmpty(fact.getEntityId())) {
                facts.put(fact.getEntityId(), fact);
            }
        }
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("strategy", proposal == null ? null : proposal.getStrategy());
        payload.put("objectiveDigest", proposal == null ? null : proposal.getCanonicalObjectiveDigest());
        payload.put("targetCountAfter", proposal == null ? null : proposal.getTargetCountAfter());
        List<String> selected = new ArrayList<String>();
        List<String> selectedIds = proposal == null || proposal.getSolverResult() == null
                ? Collections.<String>emptyList() : proposal.getSolverResult().getSelectedEntityIds();
        for (String id : selectedIds) {
            CandidateFactDTO fact = facts.get(id);
            selected.add(selectedFact(fact, id));
        }
        payload.put("selected", selected);
        List<String> current = new ArrayList<String>();
        for (CandidateFactDTO fact : facts.values()) {
            if (Boolean.TRUE.equals(fact.getCurrent())) {
                current.add(currentFact(fact));
            }
        }
        Collections.sort(current);
        payload.put("current", current);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return toHex(digest.digest(JSON.toJSONString(payload).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    /**
     * 预览请求指纹：apply 时会用请求里的 requirements/scope/target 写会话约束，
     * 只冻结 proposal 不够——同一 proposalId 换一份 request 仍会被执行。
     * sourceVersionGuard 在 apply 时才补，指纹里统一排除。
     */
    static String requestDigest(UserGoalFixProposalReq request) {
        if (request == null) {
            return null;
        }
        Integer guard = request.getSourceVersionGuard();
        request.setSourceVersionGuard(null);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return toHex(digest.digest(JSON.toJSONString(request)
                    .getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        } finally {
            request.setSourceVersionGuard(guard);
        }
    }

    private static String selectedFact(CandidateFactDTO fact, String id) {
        if (fact == null) {
            return id + "|missing";
        }
        // admissionRatio 是软数据，overlay 刷新会更新它，不应让预览失效；
        // 学费/生源省/档位是硬事实，变化必须重新预览。
        return fact.getEntityId() + "|" + fact.getTier() + "|" + fact.getEligible()
                + "|" + fact.getCurrent() + "|" + fact.getLocked() + "|" + fact.getPinned()
                + "|" + fact.getProvinceName() + "|" + fact.getTuitionPerYear()
                + "|" + sorted(fact.getVolunteerIds());
    }

    private static String currentFact(CandidateFactDTO fact) {
        return fact.getEntityId() + "|" + fact.getTier() + "|" + fact.getEligible()
                + "|" + fact.getLocked() + "|" + fact.getPinned();
    }

    private static String sorted(List<String> values) {
        if (values == null) {
            return "";
        }
        List<String> copy = new ArrayList<String>(values);
        Collections.sort(copy);
        return String.join(",", copy);
    }

    private static String toHex(byte[] values) {
        StringBuilder result = new StringBuilder(values.length * 2);
        for (byte value : values) {
            result.append(String.format("%02x", value & 0xff));
        }
        return result.toString();
    }
}
