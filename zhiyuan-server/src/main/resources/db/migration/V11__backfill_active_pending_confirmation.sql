INSERT INTO assistant_chat_session_pending_confirmation
    (tenant_id, chat_session_id, pending_id, revision, kind, action_family, status, data_value)
SELECT session.tenant_id,
       extra.chat_session_id,
       JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.pendingId')),
       1,
       JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.kind')),
       COALESCE(
           NULLIF(JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.actionFamily')), ''),
           JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.action_family'))
       ),
       JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.status')),
       JSON_REMOVE(
           JSON_SET(extra.data_value, '$.revision', 1),
           '$._pendingRevision',
           '$._pendingLegacySnapshot',
           '$._extraDataVersion',
           '$.dataVersion',
           '$._pendingClaimToken',
           '$._pendingClaimExpiresAt'
       )
FROM assistant_chat_session_extra_data extra
JOIN assistant_chat_session session ON session.id = extra.chat_session_id
WHERE extra.data_key = 'pendingConfirmation'
  AND NOT EXISTS (
      SELECT 1
      FROM assistant_chat_session_extra_data newer
      WHERE newer.chat_session_id = extra.chat_session_id
        AND newer.data_key = extra.data_key
        AND (
            newer.data_version > extra.data_version
            OR (newer.data_version = extra.data_version AND newer.id > extra.id)
        )
  )
  AND JSON_VALID(extra.data_value) = 1
  AND JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.status')) IN ('active', 'applying')
  AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.pendingId')), '') <> ''
  AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.kind')), '') <> ''
  AND COALESCE(
          NULLIF(JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.actionFamily')), ''),
          JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.action_family')),
          ''
      ) <> ''
  AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.pendingId'))) <= 64
  AND CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.kind'))) <= 32
  AND CHAR_LENGTH(COALESCE(
          NULLIF(JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.actionFamily')), ''),
          JSON_UNQUOTE(JSON_EXTRACT(extra.data_value, '$.action_family'))
      )) <= 64
  AND NOT EXISTS (
      SELECT 1
      FROM assistant_chat_session_pending_confirmation current_pending
      WHERE current_pending.tenant_id = session.tenant_id
        AND current_pending.chat_session_id = extra.chat_session_id
  );
