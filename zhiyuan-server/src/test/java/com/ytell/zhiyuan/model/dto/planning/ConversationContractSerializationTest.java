package com.ytell.zhiyuan.model.dto.planning;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class ConversationContractSerializationTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void shouldSerializeSnapshotWithCamelCaseAndEmptyCollections() throws Exception {
        ConversationTurnSnapshotDTO snapshot = new ConversationTurnSnapshotDTO();
        snapshot.setSnapshotVersion(42);
        snapshot.setSessionId(1001L);
        snapshot.setPlanningStage("candidate_exploration");

        JsonNode json = objectMapper.readTree(objectMapper.writeValueAsString(snapshot));

        assertEquals(42, json.get("snapshotVersion").asInt());
        assertEquals(1001L, json.get("sessionId").asLong());
        assertTrue(json.get("missingFacts").isArray());
        assertTrue(json.get("allowedCapabilities").isArray());
        assertTrue(json.get("evidence").isArray());
        assertEquals("major", json.get("admissionMode").asText());
        assertTrue(json.get("admissionFacts").isArray());
    }

    @Test
    void shouldSerializePatchWithCamelCase() throws Exception {
        ConversationStatePatchDTO patch = new ConversationStatePatchDTO();
        patch.setBaseVersion(41);
        patch.setTargetVersion(42);

        JsonNode json = objectMapper.readTree(objectMapper.writeValueAsString(patch));

        assertEquals(41, json.get("baseVersion").asInt());
        assertEquals(42, json.get("targetVersion").asInt());
        assertTrue(json.get("changes").isArray());
        assertTrue(json.get("invalidations").isArray());
    }
}
