#!/usr/bin/env python3
"""Summarize legacy planning-state migration logs.

Usage:
  python3 scripts/analyze_legacy_migration_logs.py logs/server.log
  tail -10000 logs/server.log | python3 scripts/analyze_legacy_migration_logs.py -
"""

import argparse
import re
import sys
from collections import Counter


SUCCESS_RE = re.compile(
    r"legacyPlanImport success chatSessionId=(?P<session>\d+) "
    r"source=(?P<source>\S+) candidates=(?P<candidates>\d+) "
    r"preferred=(?P<preferred>\d+) ordered=(?P<ordered>\d+)"
)
SKIPPED_RE = re.compile(
    r"legacyPlanImport skipped chatSessionId=(?P<session>\d+) reason=(?P<reason>\S+)"
)
FAILED_RE = re.compile(
    r"legacyPlanImport failed chatSessionId=(?P<session>\d+) source=(?P<source>\S+)"
)
UNAVAILABLE_RE = re.compile(
    r"legacyPlanImport (?P<source>final|temp) plan unavailable "
    r"chatSessionId=(?P<session>\d+) reason=(?P<reason>.*)"
)
EMPTY_RE = re.compile(
    r"legacyPlanImport (?P<source>final|temp) plan empty chatSessionId=(?P<session>\d+)"
)


def iter_lines(paths):
    if not paths or paths == ["-"]:
        for line in sys.stdin:
            yield line
        return
    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                yield line


def summarize(lines):
    stats = Counter()
    success_sources = Counter()
    failed_sources = Counter()
    skipped_reasons = Counter()
    unavailable_sources = Counter()
    unavailable_reasons = Counter()
    empty_sources = Counter()
    sessions = set()
    successful_sessions = set()
    candidate_counts = []
    preferred_counts = []
    ordered_counts = []

    for line in lines:
        match = SUCCESS_RE.search(line)
        if match:
            stats["success"] += 1
            session = match.group("session")
            sessions.add(session)
            successful_sessions.add(session)
            source = match.group("source")
            success_sources[source] += 1
            candidate_counts.append(int(match.group("candidates")))
            preferred_counts.append(int(match.group("preferred")))
            ordered_counts.append(int(match.group("ordered")))
            continue

        match = SKIPPED_RE.search(line)
        if match:
            stats["skipped"] += 1
            sessions.add(match.group("session"))
            skipped_reasons[match.group("reason")] += 1
            continue

        match = FAILED_RE.search(line)
        if match:
            stats["failed"] += 1
            sessions.add(match.group("session"))
            failed_sources[match.group("source")] += 1
            continue

        match = UNAVAILABLE_RE.search(line)
        if match:
            stats["unavailable"] += 1
            sessions.add(match.group("session"))
            unavailable_sources[match.group("source")] += 1
            reason = match.group("reason").strip() or "unknown"
            unavailable_reasons[reason] += 1
            continue

        match = EMPTY_RE.search(line)
        if match:
            stats["empty"] += 1
            sessions.add(match.group("session"))
            empty_sources[match.group("source")] += 1

    return {
        "stats": stats,
        "success_sources": success_sources,
        "failed_sources": failed_sources,
        "skipped_reasons": skipped_reasons,
        "unavailable_sources": unavailable_sources,
        "unavailable_reasons": unavailable_reasons,
        "empty_sources": empty_sources,
        "sessions": sessions,
        "successful_sessions": successful_sessions,
        "candidate_counts": candidate_counts,
        "preferred_counts": preferred_counts,
        "ordered_counts": ordered_counts,
    }


def range_text(values):
    if not values:
        return "-"
    return f"min={min(values)}, max={max(values)}, avg={sum(values) / len(values):.1f}"


def counter_text(counter):
    if not counter:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in sorted(counter.items()))


def print_summary(result):
    stats = result["stats"]
    total_decisions = stats["success"] + stats["skipped"] + stats["failed"]
    failure_rate = 0.0 if total_decisions == 0 else stats["failed"] * 100.0 / total_decisions

    print("Legacy migration log summary")
    print("============================")
    print(f"sessions_seen={len(result['sessions'])}")
    print(f"successful_sessions={len(result['successful_sessions'])}")
    print(f"success={stats['success']}")
    print(f"skipped={stats['skipped']}")
    print(f"failed={stats['failed']}")
    print(f"failure_rate={failure_rate:.2f}%")
    print(f"unavailable_events={stats['unavailable']}")
    print(f"empty_events={stats['empty']}")
    print("")
    print(f"success_sources: {counter_text(result['success_sources'])}")
    print(f"failed_sources: {counter_text(result['failed_sources'])}")
    print(f"skipped_reasons: {counter_text(result['skipped_reasons'])}")
    print(f"unavailable_sources: {counter_text(result['unavailable_sources'])}")
    print(f"empty_sources: {counter_text(result['empty_sources'])}")
    print("")
    print(f"candidate_counts: {range_text(result['candidate_counts'])}")
    print(f"preferred_counts: {range_text(result['preferred_counts'])}")
    print(f"ordered_counts: {range_text(result['ordered_counts'])}")
    if result["unavailable_reasons"]:
        print("")
        print("top_unavailable_reasons:")
        for reason, count in result["unavailable_reasons"].most_common(10):
            print(f"  {count}  {reason}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="*", help="log file path(s), or '-' for stdin")
    args = parser.parse_args()
    print_summary(summarize(iter_lines(args.logs)))


if __name__ == "__main__":
    main()
