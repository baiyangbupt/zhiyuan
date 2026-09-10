# Codex Local Stack

`scripts/codex-local-infra.sh` prepares disposable MySQL/Redis containers first.
It uses `docker-compose.codex-local.yml`, the Compose project
`zhiyuan-codex-local`, named volumes `zhiyuan_codex_local_mysql_data` and
`zhiyuan_codex_local_redis_data`, and host ports `13306/16379`. It does not
reuse the root Compose file or its volumes.

```bash
bash scripts/codex-local-infra.sh start
export CODEX_LOCAL_SERVER_CONFIG="$PWD/.local/codex-local/application-codex-local.yml"
export CODEX_LOCAL_DATASET=private-resettable
export CODEX_LOCAL_CODEX_HOME=/absolute/path/to/isolated-codex-home
bash scripts/start-codex-local.sh
```

The command creates `.local/codex-local/infra.env` and
`.local/codex-local/application-codex-local.yml` with mode `0600`. The generated
Spring file points at the disposable database and Redis ports and contains
disabled external-service placeholders. It is the `CODEX_LOCAL_SERVER_CONFIG`
input for the application stack below. `stop` retains data; `reset` removes
only this project and its two named volumes.

`scripts/start-codex-local.sh` starts a fresh local validation stack on ports
`18290` (Java), `18291` (Agent), `18292` (Rank), and `3201` (Web). It is a
separate path from `scripts/start-all.sh`: it never adopts a listener, changes
an existing PID file, or uses the default shared local configuration.

The script accepts only a private, resettable Java configuration. Put that file
outside the repository, or below the ignored `.local/codex-local/` directory,
point it at an isolated MySQL/Redis dataset, and declare it explicitly:

```bash
export CODEX_LOCAL_SERVER_CONFIG=/absolute/path/application-codex-local.yml
export CODEX_LOCAL_DATASET=private-resettable
export CODEX_LOCAL_CODEX_HOME=/absolute/path/codex-home

bash scripts/start-codex-local.sh
```

`CODEX_LOCAL_CODEX_HOME` contains the intended Codex App Server authentication
and model catalog. It is intentionally explicit so the local validation stack
cannot silently use a developer's global Codex configuration. The command does
not print the contents of either private directory.

The Java configuration must contain the connection settings for a disposable
dataset. The launcher overrides only the per-run wiring below, so the four
processes always point to the same isolated port group:

```yaml
server:
  port: 18290
agent:
  zhiyuan:
    url: http://127.0.0.1:18291
volunteer:
  rank:
    url: http://127.0.0.1:18292
```

The actual database and Redis credentials remain in the private file. Do not
use any configuration below `zhiyuan-server/src/main/resources`, an online
configuration, or a shared test dataset as the input. The launcher rejects
repository defaults and tracked files, then fails before it builds or starts
anything when the required declaration is missing.

For a backend/Agent verification without Next.js:

```bash
bash scripts/start-codex-local.sh --skip-web
```

By default the script builds a current Java jar. Use `--skip-build` only after
building `zhiyuan-server` yourself. It writes logs, PID records, the binding
registry, and health responses to a fresh `.runtime/codex-local-*` directory.
The ready message prints that directory and the exact stop command:

```bash
bash scripts/stop-codex-local.sh /root/dev/zhiyuan/.runtime/codex-local-...
```

`stop-codex-local.sh` only signals PIDs that it recorded and whose command line
still matches this repository and carries the exact run-directory marker set
by the launcher. It does not search for or stop unrelated listeners.

Once the stack is ready, the direct WebSocket client can exercise a read-only
turn without the browser:

```bash
cd zhiyuan-agent
.venv/bin/python scripts/local_ws_client.py \
  --url ws://127.0.0.1:18291/ws/chat \
  --tenant-id 1 \
  --session-id 10001 \
  --user-id 10001 \
  --message "Explain the available candidates."
```

The script configures `GATEWAY_MODE=codex_readonly`, a per-run binding registry,
`INTERNAL_SERVICE_URL`, and `RANK_SERVICE_URL`. Codex starts the domain MCP
server as a child of the Agent process; no persistent MCP process is launched.
The preflight does not prove that a supplied database is resettable. That is an
operator-owned property represented by `CODEX_LOCAL_DATASET=private-resettable`.
Real Pending/CAS HTTP E2E must run only after that private dataset is prepared.
