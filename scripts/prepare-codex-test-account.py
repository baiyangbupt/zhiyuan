#!/usr/bin/env python3
"""Prepare one reusable account in the isolated local Codex test database."""

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "zhiyuan-codex-local-mysql-1"
DATABASE = "zhiyuan_codex_local"
PRIVATE_DIR = ROOT / ".local/codex-local"
CREDENTIALS = PRIVATE_DIR / "browser-test-credentials.json"
USERNAME = "codex-test"


def configure_account(name):
    """Use separate identities and private files for parallel developers/tests."""
    global USERNAME, CREDENTIALS
    if len(name) > 64 or not re.fullmatch(r"codex-test(?:-[a-z0-9]+)*", name):
        raise ValueError("account name must be codex-test or codex-test-<lowercase suffix>")
    USERNAME = name
    filename = ("browser-test-credentials.json" if name == "codex-test"
                else "test-account-" + name + ".json")
    CREDENTIALS = PRIVATE_DIR / filename


def run(command, input_text=None):
    result = subprocess.run(command, input=input_text, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("local test account operation failed; credentials were not printed")
    return result.stdout.strip()


def sql(statement):
    return run([
        "docker", "exec", "-i", CONTAINER, "sh", "-c",
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -N -B -u root -D "$MYSQL_DATABASE"',
    ], statement)


def prepare():
    if run(["docker", "port", CONTAINER, "3306/tcp"]) != "127.0.0.1:13306":
        raise RuntimeError("refusing a database outside the isolated local container")
    config = (PRIVATE_DIR / "application-codex-local.yml").read_text()
    if "jdbc:mysql://127.0.0.1:13306/" + DATABASE not in config:
        raise RuntimeError("Java configuration does not target the isolated local database")
    run(["docker", "exec", CONTAINER, "sh", "-c",
         'test "$MYSQL_DATABASE" = "zhiyuan_codex_local"'])

    previous = json.loads(CREDENTIALS.read_text()) if CREDENTIALS.exists() else None
    password = previous["password"] if previous else secrets.token_urlsafe(32)
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", password):
        raise RuntimeError("unexpected private test credential format")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    encode = lambda value: base64.b64encode(value).decode().rstrip("=")
    encoded = "$pbkdf2-sha256$600000$" + encode(salt) + "$" + encode(digest)

    existing = sql("SELECT user_id FROM assistant_user_credential "
                   "WHERE login_type=2 AND identifier='%s';" % USERNAME)
    if existing and (previous is None or existing != str(int(previous["userId"]))):
        raise RuntimeError("refusing to overwrite an account not owned by this fixture")
    if previous:
        user_id = int(previous["userId"])
        old_name = previous["username"]
        legacy_fixture = (USERNAME == "codex-test"
                          and re.fullmatch(r"codex-browser-e2e-[0-9a-f]{16}", old_name))
        if old_name != USERNAME and not legacy_fixture:
            raise RuntimeError("refusing to modify a non-fixture account")
        credential = sql("SELECT credential_id FROM assistant_user_credential "
                         "WHERE user_id=%d AND login_type=2 AND identifier IN ('%s','%s');"
                         % (user_id, old_name, USERNAME))
        if not credential.isdigit():
            raise RuntimeError("fixture credential is missing or ambiguous")
        predicate = ("u.id=%d AND c.credential_id=%d AND c.login_type=2 "
                     "AND u.tenant_id=1 AND u.bot_id=1 AND u.channel='ytell' "
                     "AND u.is_customer=0 AND u.is_deleted=0 AND u.user_level='SUPER_VIP' "
                     "AND c.channel='ytell' AND u.user_name IN ('%s','%s') "
                     "AND c.identifier IN ('%s','%s')"
                     % (user_id, int(credential), old_name, USERNAME, old_name, USERNAME))
        join = "assistant_user_base u JOIN assistant_user_credential c ON c.user_id=u.id"
        if sql("SELECT COUNT(*) FROM " + join + " WHERE " + predicate + ";") != "1":
            raise RuntimeError("fixture user identity changed; refusing to overwrite the account")
        # One statement changes both rows and repeats the ownership predicate so a
        # concurrent account change cannot turn the fixture update into an overwrite.
        changed = sql("UPDATE " + join + " SET u.user_name='%s', "
                      "c.identifier='%s', c.password_hash='%s' WHERE %s; SELECT ROW_COUNT();"
                      % (USERNAME, USERNAME, encoded, predicate))
        if changed not in ("1", "2"):
            raise RuntimeError("fixture user changed concurrently; private credentials retained")
    else:
        result = sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ; START TRANSACTION; "
                     "SELECT credential_id FROM assistant_user_credential "
                     "WHERE login_type=2 AND identifier='%s' LIMIT 1 FOR UPDATE; "
                     "SET @fixture_new_allowed=(SELECT COUNT(*) FROM assistant_user_credential "
                     "WHERE login_type=2 AND identifier='%s')=0; "
                     "INSERT INTO assistant_user_base "
                     "(tenant_id,bot_id,user_name,is_customer,is_deleted,user_level,channel) "
                     "SELECT 1,1,'%s',0,0,'SUPER_VIP','ytell' WHERE @fixture_new_allowed; "
                     "SET @fixture_user_id=IF(@fixture_new_allowed,LAST_INSERT_ID(),NULL); "
                     "INSERT INTO assistant_user_credential "
                     "(user_id,login_type,login_token,channel,identifier,password_hash) "
                     "SELECT @fixture_user_id,2,'%s','ytell','%s','%s' WHERE @fixture_new_allowed; "
                     "COMMIT; SELECT IFNULL(@fixture_user_id,0);"
                     % (USERNAME, USERNAME, USERNAME, secrets.token_hex(32), USERNAME, encoded))
        user_id = int(result.splitlines()[-1])
        if user_id <= 0:
            raise RuntimeError("account was created concurrently; refusing to overwrite its credentials")
    data = {"username": USERNAME, "password": password, "tenantId": 1, "userId": user_id}
    temporary = PRIVATE_DIR / (".test-credentials-" + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream)
            stream.write("\n")
        os.replace(temporary, CREDENTIALS)
    finally:
        temporary.unlink(missing_ok=True)
    print("Prepared local account: " + USERNAME + "; private credentials: " + str(CREDENTIALS))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write only the isolated local fixture")
    parser.add_argument("--name", default="codex-test", help="distinct codex-test-<suffix> identity")
    arguments = parser.parse_args()
    try:
        configure_account(arguments.name)
    except ValueError as error:
        parser.error(str(error))
    if arguments.apply:
        descriptor = os.open(PRIVATE_DIR / ".test-account.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            prepare()
    else:
        print("Dry run: prepare " + USERNAME
              + " in zhiyuan-codex-local-mysql-1 on 127.0.0.1:13306. Use --apply.")
