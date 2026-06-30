# Volunteer Session Source Import Tool

## Purpose

This runbook is for single-session recovery when upstream `queryAllProgramData` can be exported manually but the normal create-session flow timed out or failed before the local `session_volunteer_{chatSessionId}.json` file was persisted.

It is not a batch migration tool. Run it for one session at a time in production.

## Tool

Script:

```bash
zhiyuan-server/scripts/import_volunteer_session_source.py
```

Default behavior is dry-run. It only writes the local volunteer source file when `--execute` is provided. It does not create a chat session, insert DB rows, delete `planningState`, or upload OSS files.

Supported targets:

- `--file-kind original`: `session_volunteer_{id}.json`, upstream source data from `queryAllProgramData`. This is the usual timeout-recovery target.
- `--file-kind temp`: `session_volunteer_{id}_temp.json`, temporary recommendation response.
- `--file-kind final`: `session_volunteer_{id}_final.json`, submitted final recommendation response.

Default temp-data path is read from `VOLUNTEER_TEMP_DATA_PATH` or `GAOTU_ZHIYUAN_TEMP_DATA_PATH`, then falls back to `/apps/volunnter-tmpdata`.

## Data Normalization

The import tool mirrors the server-side source-data persistence cleanup used by `VolunteerSourceDataSyncService`:

- Removes `enrollAdvice`, `converProcess`, `enrollMajorSubtitle`, `enrollMajorId`.
- Converts string `score` values such as `469.0000` to integer `469` when possible.
- Converts string percentage `enrollRatio` values such as `90%` to integer `90` when possible.

If the export wrapper is `{code, data}`, the tool writes `data`. If `data` itself is a JSON string, the tool parses it once.

## Mode Distinction

Do not mix 专业+院校 and 专业组 counts:

- `major` / 专业+院校 uses `CreateSessionReq.volunteerCount.majorCount` as the target count.
- `majorGroup` / 专业组 uses `CreateSessionReq.volunteerCount.schoolCount` as the target count.

Legacy source files contain candidate totals in `ProgramModel.majorTotalNum` and `ProgramModel.schoolTotalNum`; these are not the final target count. Runtime legacy conversion now uses the session `userScoreDetail` to set the target count and tier target map.

## convertLegacyVolunteerData Scope

`convertLegacyVolunteerData` is still in runtime use. The load order for missing `planningState` lazy import is:

1. `session_volunteer_{id}_final.json`
2. `session_volunteer_{id}_temp.json`
3. `session_volunteer_{id}.json`

When the file is already a modern `VolunteerRecommendListResponse` with `sprints/safes/protects`, it is returned as-is with missing session context filled where available. When the file is old source format with `detailList/model/type`, it is converted to the recommendation response shape.

The old bug was that source candidate totals could be copied into `baseData.need_count`. For example, a session targeting 96 志愿 could inherit thousands of candidate entries as the target. This has been fixed by deriving target count from stored session score detail.

## Safe Runbook

1. Validate without writing:

```bash
cd /root/dev/zhiyuan/zhiyuan-server
scripts/import_volunteer_session_source.py \
  --chat-session-id 6796 \
  --source-file /root/dev/zhiyuan/2248_aifill.json
```

2. Write the original source file:

```bash
cd /root/dev/zhiyuan/zhiyuan-server
scripts/import_volunteer_session_source.py \
  --chat-session-id 6796 \
  --source-file /root/dev/zhiyuan/2248_aifill.json \
  --execute
```

3. If a bad `planningState` was already created, remove only that session state first:

```bash
cd /root/dev/zhiyuan/zhiyuan-server
scripts/reset_planning_state.py --session-id 6796 --execute
```

4. Optional warm-up, one session only:

```bash
cd /root/dev/zhiyuan/zhiyuan-server
scripts/import_volunteer_session_source.py \
  --chat-session-id 6796 \
  --source-file /root/dev/zhiyuan/2248_aifill.json \
  --execute \
  --warm-up \
  --base-url http://127.0.0.1:8090
```

5. Verify the workspace state and candidate pool through existing planning APIs. Expected checks are target count, tier target counts, candidate total, ordered/working plan count, and data freshness status.

## Production Caution

Run this only for the affected session. Do not loop over many source files, and do not use `--warm-up` in batch. Warm-up may trigger legacy import and planning state normalization, so keep it single-session and inspect logs after each run.
