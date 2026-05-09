#!/usr/bin/env python3
"""Reset V2 planningState for one or more sessions.

The script is dry-run by default. It only deletes
assistant_chat_session_extra_data rows whose data_key is planningState and
data_version is 0 when --execute is provided.

Examples:
  python3 scripts/reset_planning_state.py --session-id 1002
  python3 scripts/reset_planning_state.py --session-id 1002 --execute
  MYSQL_HOST=127.0.0.1 MYSQL_USER=root MYSQL_PASSWORD=xxx MYSQL_DATABASE=sales_bot \
    python3 scripts/reset_planning_state.py --session-id 1002 --execute
"""

import argparse
import os
import shutil
import subprocess
import sys


PLANNING_STATE_KEY = "planningState"


def build_mysql_base_command(args):
    mysql = shutil.which("mysql")
    if not mysql:
        raise RuntimeError("mysql client not found in PATH")

    command = [mysql, "--batch", "--raw", "--skip-column-names"]
    host = args.host or os.getenv("MYSQL_HOST")
    port = args.port or os.getenv("MYSQL_PORT")
    user = args.user or os.getenv("MYSQL_USER")
    password = args.password if args.password is not None else os.getenv("MYSQL_PASSWORD")
    database = args.database or os.getenv("MYSQL_DATABASE")

    if host:
        command.extend(["--host", host])
    if port:
        command.extend(["--port", str(port)])
    if user:
        command.extend(["--user", user])
    if password:
        command.append(f"--password={password}")
    if database:
        command.append(database)
    return command


def quote_sql_string(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def run_mysql(command, sql, dry_run=False):
    if dry_run:
        print(sql.rstrip() + ";")
        return ""
    result = subprocess.run(
        command + ["--execute", sql],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mysql command failed")
    return result.stdout.strip()


def build_where_clause(session_id):
    return (
        f"chat_session_id = {int(session_id)} "
        f"and data_key = {quote_sql_string(PLANNING_STATE_KEY)} "
        "and data_version = 0"
    )


def inspect_session(command, session_id):
    sql = (
        "select id, chat_session_id, data_key, data_version, "
        "char_length(data_value), update_time "
        "from assistant_chat_session_extra_data "
        f"where {build_where_clause(session_id)};"
    )
    return run_mysql(command, sql)


def reset_session(command, session_id):
    sql = (
        "delete from assistant_chat_session_extra_data "
        f"where {build_where_clause(session_id)};"
    )
    run_mysql(command, sql)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", action="append", type=int, required=True,
                        help="chat session id. Repeat for multiple sessions.")
    parser.add_argument("--execute", action="store_true",
                        help="actually delete planningState rows. Default is dry-run.")
    parser.add_argument("--host", help="MySQL host, or MYSQL_HOST")
    parser.add_argument("--port", type=int, help="MySQL port, or MYSQL_PORT")
    parser.add_argument("--user", help="MySQL user, or MYSQL_USER")
    parser.add_argument("--password", help="MySQL password, or MYSQL_PASSWORD")
    parser.add_argument("--database", help="MySQL database, or MYSQL_DATABASE")
    return parser.parse_args()


def main():
    args = parse_args()
    command = build_mysql_base_command(args) if args.execute else None
    if not args.execute:
        print("Dry-run only. Add --execute to delete planningState rows.")
        print("")

    for session_id in args.session_id:
        if args.execute:
            before = inspect_session(command, session_id)
            print(f"session_id={session_id}")
            print("before=" + (before if before else "not_found"))
            if before:
                reset_session(command, session_id)
                after = inspect_session(command, session_id)
                print("after=" + (after if after else "deleted"))
            else:
                print("after=not_found")
        else:
            print(f"-- session_id={session_id}")
            print(
                "select id, chat_session_id, data_key, data_version, "
                "char_length(data_value), update_time "
                "from assistant_chat_session_extra_data "
                f"where {build_where_clause(session_id)};"
            )
            run_mysql(command, "delete from assistant_chat_session_extra_data "
                      f"where {build_where_clause(session_id)}", dry_run=True)
            print("")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
