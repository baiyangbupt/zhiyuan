#!/usr/bin/env bash
set -uo pipefail

LINES="${ZHIYUAN_MIGRATION_LOG_LINES:-10000}"
LOG_FILE="${1:-${ZHIYUAN_SERVER_LOG:-/root/work/zhiyuan-server/logs/server.log}}"
ANALYZER="${ZHIYUAN_MIGRATION_ANALYZER:-zhiyuan-server/scripts/analyze_legacy_migration_logs.py}"

if [ ! -f "$ANALYZER" ]; then
  echo "Analyzer not found: $ANALYZER" >&2
  exit 2
fi

if [ "$LOG_FILE" = "-" ]; then
  python3 "$ANALYZER" -
  exit $?
fi

if [ ! -f "$LOG_FILE" ]; then
  echo "Log file not found: $LOG_FILE" >&2
  exit 2
fi

tail -n "$LINES" "$LOG_FILE" | python3 "$ANALYZER" -
