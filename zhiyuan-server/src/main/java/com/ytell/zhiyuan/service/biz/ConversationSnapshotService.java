package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationTurnSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.ExplicitProfileDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.dto.planning.ProfileStateDTO;
import com.ytell.zhiyuan.model.dto.planning.SoftPreferencesDTO;
import com.ytell.zhiyuan.model.dto.planning.StudentPlanningSummaryDTO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class ConversationSnapshotService {

    @Autowired
    private PlanningStateService planningStateService;

    @Autowired
    private PendingConfirmationBizService pendingConfirmationBizService;

    public ConversationTurnSnapshotDTO getTurnSnapshot(Long tenantId, Long chatSessionId, String skill) {
        if (tenantId == null || chatSessionId == null) {
            throw new IllegalArgumentException("tenantId and chatSessionId are required");
        }
        PlanningWorkspaceStateRes workspace = planningStateService.getPlanningWorkspaceState(tenantId, chatSessionId);
        if (workspace == null || !chatSessionId.equals(workspace.getSessionId())) {
            throw new IllegalStateException("snapshot_session_mismatch");
        }

        ConversationTurnSnapshotDTO snapshot = new ConversationTurnSnapshotDTO();
        snapshot.setSnapshotVersion(workspace.getVersion() == null ? 0 : workspace.getVersion());
        snapshot.setSessionId(chatSessionId);
        snapshot.setAdmissionMode(canonicalAdmissionMode(workspace));
        snapshot.setPlanningStage(defaultString(workspace.getPhase()));
        fillScoreContext(snapshot.getScoreContext(), workspace.getStudentSummary());
        fillProfileAndConstraints(snapshot, workspace);
        fillMissingFacts(snapshot.getMissingFacts(), workspace.getStudentSummary());
        fillActiveProposal(snapshot, tenantId, chatSessionId);
        fillCapabilities(snapshot.getAllowedCapabilities(), skill);
        fillEvidence(snapshot.getEvidence(), workspace);
        return snapshot;
    }

    private String canonicalAdmissionMode(PlanningWorkspaceStateRes workspace) {
        String raw = workspace.getCandidatePoolState() == null
                ? null : workspace.getCandidatePoolState().getVolunteerModel();
        if (raw == null || raw.trim().isEmpty() || "major".equalsIgnoreCase(raw)) {
            return "major";
        }
        if ("majorGroup".equalsIgnoreCase(raw) || "major_group".equalsIgnoreCase(raw)) {
            return "major_group";
        }
        throw new IllegalStateException("unsupported_admission_mode");
    }

    private void fillScoreContext(Map<String, Object> target, StudentPlanningSummaryDTO summary) {
        if (summary == null) {
            return;
        }
        putIfPresent(target, "province", summary.getProvinceName());
        putIfPresent(target, "examYear", summary.getExamYear());
        putIfPresent(target, "score", summary.getScore());
        putIfPresent(target, "rank", summary.getRank());
        putIfPresent(target, "batch", summary.getBatchName());
        putIfPresent(target, "batchScore", summary.getBatchScore());
        if (summary.getSubjects() != null && !summary.getSubjects().isEmpty()) {
            target.put("subjects", new ArrayList<String>(summary.getSubjects()));
        }
        if (summary.getStrengthSubjects() != null && !summary.getStrengthSubjects().isEmpty()) {
            target.put("strengthSubjects", new ArrayList<String>(summary.getStrengthSubjects()));
        }
    }

    private void fillProfileAndConstraints(ConversationTurnSnapshotDTO snapshot,
                                           PlanningWorkspaceStateRes workspace) {
        ProfileStateDTO profile = workspace.getProfileState();
        if (profile != null && profile.getExplicitProfile() != null) {
            ExplicitProfileDTO explicit = profile.getExplicitProfile();
            putIfPresent(snapshot.getPreferences(), "major", explicit.getPositiveMajors());
            putIfPresent(snapshot.getPreferences(), "school", explicit.getPositiveSchools());
            putIfPresent(snapshot.getPreferences(), "region", explicit.getPositiveRegions());
            putIfPresent(snapshot.getConfirmedConstraints(), "excludedMajors", explicit.getNegativeMajors());
            putIfPresent(snapshot.getConfirmedConstraints(), "excludedSchools", explicit.getNegativeSchools());
            putIfPresent(snapshot.getConfirmedConstraints(), "excludedRegions", explicit.getNegativeRegions());
        }
        if (workspace.getConstraintState() != null) {
            HardConstraintsDTO hard = workspace.getConstraintState().getHardConstraints();
            SoftPreferencesDTO soft = workspace.getConstraintState().getSoftPreferences();
            if (hard != null) {
                snapshot.getConfirmedConstraints().put("hard", hard);
            }
            if (soft != null) {
                snapshot.getPreferences().put("soft", soft);
            }
        }
        if (workspace.getStaleFlags() != null) {
            snapshot.getConfirmedConstraints().put("staleFlags", workspace.getStaleFlags());
        }
        if (workspace.getCandidatePoolState() != null
                && workspace.getCandidatePoolState().getSummary() != null) {
            snapshot.getPreferences().put("candidateSummary", workspace.getCandidatePoolState().getSummary());
        }
        if (workspace.getReviewState() != null && workspace.getReviewState().getSummary() != null) {
            snapshot.getPreferences().put("reviewSummary", workspace.getReviewState().getSummary());
        }
        if (workspace.getWorkflowStatus() != null) {
            snapshot.getPreferences().put("workflow", workspace.getWorkflowStatus());
        }
    }

    private void fillMissingFacts(List<String> missing, StudentPlanningSummaryDTO summary) {
        if (summary == null || isBlank(summary.getProvinceName())) {
            missing.add("province");
        }
        if (summary == null || summary.getScore() == null) {
            missing.add("score");
        }
        if (summary == null || summary.getRank() == null) {
            missing.add("rank");
        }
    }

    private void fillActiveProposal(ConversationTurnSnapshotDTO snapshot, Long tenantId, Long chatSessionId) {
        PendingConfirmationRes pending = pendingConfirmationBizService.getCurrent(tenantId, chatSessionId);
        if (pending == null || !"active".equals(pending.getStatus())) {
            return;
        }
        Map<String, Object> proposal = new LinkedHashMap<String, Object>();
        // Keep the Gateway contract flat and explicit.  Consumers should not
        // need to inspect the serialized pending payload to find the identity,
        // revision, source version, or whether confirmation is required.
        proposal.put("proposalRef", pending.getPendingId());
        proposal.put("pendingId", pending.getPendingId());
        proposal.put("revision", pending.getRevision());
        proposal.put("kind", pending.getKind());
        proposal.put("actionFamily", pending.getActionFamily());
        proposal.put("status", pending.getStatus());
        proposal.put("requiresConfirmation", "active".equals(pending.getStatus()));
        Map<String, Object> dataValue = pending.getDataValue() == null
                ? new LinkedHashMap<String, Object>() : pending.getDataValue();
        Object sourceVersion = firstPresent(
                dataValue.get("sourceVersion"),
                dataValue.get("sourceBackendVersion"),
                dataValue.get("planningVersion"));
        if (sourceVersion != null) {
            proposal.put("sourceVersion", sourceVersion);
        }
        proposal.put("data", dataValue);
        snapshot.setActiveProposal(proposal);
    }

    private Object firstPresent(Object... values) {
        for (Object value : values) {
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private void fillCapabilities(List<String> capabilities, String skill) {
        capabilities.add("catalog_read");
        capabilities.add("admission_read");
        if (skill != null && skill.contains("review")) {
            capabilities.add("review_read");
        }
    }

    private void fillEvidence(List<ConversationEvidenceDTO> evidence, PlanningWorkspaceStateRes workspace) {
        // First phase exposes only evidence references already produced by the
        // authoritative backend.  The workspace DTO currently has no evidence
        // collection, so do not synthesize or infer references here.
    }

    private void putIfPresent(Map<String, Object> target, String key, Object value) {
        if (value instanceof List && ((List<?>) value).isEmpty()) {
            return;
        }
        if (value != null && !(value instanceof String && isBlank((String) value))) {
            target.put(key, value);
        }
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
