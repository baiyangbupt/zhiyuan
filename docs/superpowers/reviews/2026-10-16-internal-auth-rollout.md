# Internal HTTP authentication rollout review — 2026-10-16

## Scope and contract

This change is workspace-only. No commit, branch, worktree, deployment, service
restart, live dotenv update, or private Spring configuration update is included.
The existing architecture-hardening plan and concurrent work are left untouched.

Files changed by this workline:

- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/web/interceptor/InternalServiceAuthInterceptor.java` (new)
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/common/config/WebConfig.java`
- `zhiyuan-server/src/main/resources/application-internal-auth.example.yml` (new)
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/web/interceptor/InternalServiceAuthMvcTest.java` (new)
- `zhiyuan-agent/app/config.py`
- `zhiyuan-agent/app/util/internal_client.py`
- `zhiyuan-agent/app/gateway/composition.py`
- `zhiyuan-agent/.env.example`
- `zhiyuan-agent/tests/unit/test_internal_service_auth.py` (new)
- `zhiyuan-agent/tests/unit/test_mcp_internal_auth_config.py` (new)
- `zhiyuan-agent/tests/unit/test_ops_internal_auth.py` (new)
- `zhiyuan-agent/tests/unit/test_ops_release_smoke.py`
- `ops/healthcheck.sh`
- `ops/release-smoke.sh`
- `scripts/start-codex-local.sh`
- `docs/superpowers/reviews/2026-10-16-internal-auth-rollout.md` (new)

- Runtime credential key: `INTERNAL_SERVICE_TOKEN`, shared by Java, Agent, MCP,
  and trusted operational probes. Provision a strong, randomly generated,
  environment-specific secret using the deployment's secret management system.
- Java property alias: `internal.service.token`. The interceptor reads this
  property with an environment-variable fallback. The new
  `zhiyuan-server/src/main/resources/application-internal-auth.example.yml` is an
  illustrative configuration file, not an automatically activated profile.
- Only accepted credential transport: the `X-Internal-Service-Token` HTTP header.
  Query parameters, browser `tk`/`pf` credentials, and cookies are not substitutes.
  Do not put this credential into browser code or publicly accessible proxies.
- Protected MVC patterns: `/**/inner/**`, `/**/admin/**`, `/**/debug/**`, and
  `/**/internal/**`. These include `/gaotu-assistant-bot/inner/ops/health` and
  `/internal/evidence/**`, including namespace roots. The same patterns are
  excluded from user login because service authentication now owns them.
- Missing/blank server configuration or a missing/blank request credential returns
  real HTTP 401. An incorrect, padded, or duplicated credential returns real HTTP
  403. Comparison uses `MessageDigest.isEqual` on UTF-8 credential bytes. Denials
  write a generic JSON response directly, rather than passing through the
  existing exception handler that maps ordinary exceptions to HTTP 200.
- Existing public login, WeChat callback, base-data, documentation, and error
  exclusions remain public. A service credential does not bypass user login or
  conversation authorization on public application endpoints. Internal OPTIONS
  requests are not an authentication bypass.

## Agent and MCP

`InternalServiceConfig.url` now defaults to `http://127.0.0.1:8090`, not a production
host. Import-time HTTP-client construction remains possible without a configured
token. With no token the client sends no credential, and protected Java requests
are denied. Existing explicit backend URLs and comma-separated URL lists are
preserved. An existing live dotenv URL is still explicit configuration; this
change deliberately does not overwrite it.

The token is a Pydantic `SecretStr`, so normal configuration representation and
JSON serialization redact it. All five internal-client HTTP verbs attach the
configured header, preserve unrelated caller headers, reject caller overrides of
the credential header regardless of case, and disable automatic redirects so a
backend redirect cannot forward the credential to another origin. Configure the
final trusted backend URL directly; every address in a configured URL list must
be trusted to receive the token.

The Codex MCP environment allowlist now includes `INTERNAL_SERVICE_TOKEN` alongside
`INTERNAL_SERVICE_URL`, `INTERNAL_SERVICE_TIMEOUT_SECONDS`, and `MCP_MODE`. Only key
names enter the generated MCP command/configuration, not credential values.
Export the credential and URL into the actual Agent/Codex process environment.
Do not rely solely on Agent dotenv loading: the MCP child is a separate process
and may have a different working directory or dotenv configuration. Never log
the environment or enable shell tracing while credentials are in scope.

## Operational probes and compatibility

The following additional script paths were announced before editing:

- `ops/healthcheck.sh`
- `ops/release-smoke.sh`
- `scripts/start-codex-local.sh`

Their backend-internal probes require the same runtime key and send the header
through escaped curl configuration on stdin using `curl -q --config -`, not
`--header @-`. The host's curl 7.29.0 treats `@-` as a literal header; it does not
read the credential from stdin. Backslashes and double quotes are escaped inside
the quoted `header` directive. Missing, whitespace-only, and CR/LF-bearing
credentials fail locally before curl runs. No credential value enters curl's
arguments or a generated configuration file. The first `-q` disables default
curlrc settings, including unexpected tracing, redirect following, or insecure
TLS options. Authenticated requests allow only HTTP/HTTPS, do not follow redirects,
and keep TLS verification enabled. All three authenticated probes explicitly
require transport success and an HTTP 2xx status; `curl -f` alone accepts 3xx.

Authenticated curl stderr is discarded and replaced with fixed failure messages,
not copied into reports or temporary error files. Healthcheck and launcher discard
authenticated response bodies; release smoke checks its expected response marker
in memory without body/error files. The launcher consequently no longer writes
`backend-health.json`; public service health artifacts remain unchanged. This also
prevents an echoed credential from entering probe artifacts. Public probes never
receive the token and retain their existing behavior, including release smoke's
public-only `-k -L` and the existing acceptance of public 3xx responses.

The launcher checks the token after its existing read-only preflight and before
creating its run directory or starting processes. The token is not added to its
`stack.env` artifact. Bash 4.2 compatibility is preserved, including avoiding
empty-array expansion under `set -u`.

One-off/remote production flow tools initially deferred, migrated in the follow-up batch:

- `scripts/collect_production_flow_assets.py`
- `scripts/verify_production_flow_capabilities.py`
- `scripts/replay_production_dialog_flow_local.py`

These now share `scripts/internal_http.py`. Export `INTERNAL_SERVICE_TOKEN` into
the local invoking process through secret management; SSH sends escaped curl
configuration over stdin, not remote command arguments. Remote hosts need curl
and SSH access but do not need the token copied into shell profiles. Direct HTTP
and remote curl reject redirects and non-2xx statuses. Missing/invalid credentials
are rejected before output directories, asset reads, or replay execution. The
offline-only capability mode (`--skip-production-proposal`) needs no token.
Do not embed tokens in SSH command strings, curl arguments, URLs, saved artifacts,
or repository files. The replay tool can mutate state and was not executed.
Full follow-up evidence is in `2026-10-16-release-readiness-handoff.md`.
Existing public-proxy negative
checks in `scripts/smoke-codex-public.sh` and
`scripts/smoke-standardtest-hardening.sh` intentionally continue to expect internal
paths to be unreachable through the browser-facing proxy; no credential belongs
in those checks.

## RED evidence

Commands below use each named working directory. Test credentials are synthetic;
no runtime secret values were inspected or printed.

From `zhiyuan-agent`:

```bash
./.venv/bin/python -m pytest tests/unit/test_internal_service_auth.py tests/unit/test_mcp_internal_auth_config.py tests/unit/test_ops_internal_auth.py -q --tb=short
```

Before production edits: **20 failed, 2 passed**. Failures demonstrated the
production URL default, missing token configuration/HTTP headers/MCP inheritance,
and unauthenticated probe behavior. Output was captured in
`/tmp/zhiyuan-internal-auth-python-red.log`.

From `zhiyuan-server`:

```bash
mvn -o -q -Dtest=InternalServiceAuthMvcTest test
```

Before Java production edits, after correcting the standalone fixture to use
real timing/trace interceptors: **33 run, 21 failed, 0 errors**. Protected routes
returned HTTP 200 instead of 401/403; public/login controls passed. Output was
captured in `/tmp/zhiyuan-internal-auth-java-red.log`.

An initial Python invocation from the repository root failed collection because
`app` was not importable there; the recorded RED run uses the Agent directory.
The first Java fixture used Mockito interceptors whose default false return
short-circuited MVC execution; it was corrected before recording meaningful RED.

## GREEN and offline regression evidence

From `zhiyuan-agent`, the same new-test command: **22 passed**. It uses isolated
configuration, mocked aiohttp transports, and extracted shell probe functions
with a fake curl executable. The launcher itself is not executed. An intermediate
GREEN attempt exposed the host's Bash 4.2 empty-array issue; the corrected probes
pass. Output: `/tmp/zhiyuan-internal-auth-python-green.log`.

From `zhiyuan-server`, the same standalone MVC command: **33 passed**, no database
or Spring Boot application startup. Tests install the actual `WebConfig`
interceptor registrations in standalone MockMvc, include the actual global
exception advice, and assert transport status, successful dispatch, duplicate
headers, blank configuration, namespace roots, and public/login controls.
Output: `/tmp/zhiyuan-internal-auth-java-green.log`.

Existing Python/config/client/MCP/evidence/composition regression command, from
`zhiyuan-agent`:

```bash
INTERNAL_SERVICE_TOKEN=offline-regression-credential ./.venv/bin/python -m pytest tests/unit/test_config.py tests/unit/test_extract_config.py tests/unit/test_internal_client_timeout.py tests/unit/test_internal_client_city_filters.py tests/unit/test_pending_confirmation_client.py tests/unit/test_ops_release_smoke.py tests/unit/test_domain_mcp_tools.py tests/unit/test_mcp_trusted_context.py tests/unit/test_evidence_verification.py tests/integration/test_gateway_composition.py tests/integration/test_evidence_roundtrip.py tests/integration/test_request_context_integration.py -q --tb=short
```

Result: **170 passed, 1 skipped, 4 warnings**. The skip is the composition test at
`tests/integration/test_gateway_composition.py:153`: the fixed Codex App Server
binary is not installed. Existing warnings concern a
synchronous test carrying an asyncio marker and deprecated `AgentRun.usage()`
calls. The synthetic environment credential allows existing mocked smoke tests
to exercise successful internal probes without changing those test files.
Output: `/tmp/zhiyuan-internal-auth-python-regression.log`.

The skip was confirmed separately from `zhiyuan-agent`:

```bash
./.venv/bin/python -m pytest tests/integration/test_gateway_composition.py -q -rs --tb=short
```

Result: **9 passed, 1 skipped**, with the explicit missing-binary reason. Output:
`/tmp/zhiyuan-internal-auth-composition.log`.

Existing Java controller/login regression command, from `zhiyuan-server`:

```bash
mvn -o -q -Dtest=InternalServiceAuthMvcTest,LoginInterceptorTest,OpsHealthControllerTest,CatalogControllerTest,CodexConversationControllerTest,PlanningFacadeControllerTest,IntegrationSessionControllerTest,UserAdminControllerTest test
```

Result: **69 passed, 0 failures, 0 errors, 0 skipped** across eight standalone/unit
test classes. Maven is offline; these tests do not start the server or connect to
a database. Output: `/tmp/zhiyuan-internal-auth-java-regression.log`.

From the repository root, shell syntax and patch whitespace checks:

```bash
for script in ops/healthcheck.sh ops/release-smoke.sh scripts/start-codex-local.sh; do bash -n "$script" || exit; done
git diff --check
```

No live probes, service restarts, deployment checks, database tests, or unrelated
Node commands are part of this validation.

## Ops review repair: curl 7.29 compatibility and strict status checks

This follow-up edits only the three operational scripts, the new
`tests/unit/test_ops_internal_auth.py`, the existing
`tests/unit/test_ops_release_smoke.py`, and this review document. The additional
existing test path was announced before editing. The smoke fake now supports
curl's in-memory body/status output and supplies a synthetic credential; no live
configuration is consulted for its credential. The architecture plan and the
concurrent gateway/request-admission work are not changed.

Host versions: curl **7.29.0** and GNU Bash **4.2.46**. This offline reproduction
uses only the file protocol and a synthetic header:

```bash
printf 'X-Internal-Service-Token: offline-curl-proof\n' | curl -q --silent --show-error --header @- --proto '=file' --libcurl /dev/stdout file:///dev/null | rg 'curl_slist_append|CURLOPT_HTTPHEADER'
```

Observed output includes `curl_slist_append(slist1, "@-")`, confirming that the old
transport does not create the intended header. The generated C is streamed, not
saved to a configuration/artifact file. Six new file-protocol tests compile the
actual scripts' stdin configurations with host curl and verify exact header
round-tripping for both plain and quote/backslash-bearing synthetic credentials.
Generated C stays in test memory; no HTTP requests or sockets are used.

### RED

From `zhiyuan-agent`, before any script repair:

```bash
set -o pipefail
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_ops_internal_auth.py -q --tb=short 2>&1 | tee /tmp/zhiyuan-ops-curl-red.log
```

Result: **21 failed, 16 passed**. Failures demonstrate unsupported header delivery,
healthcheck/launcher accepting HTTP 302, authenticated stderr copied into reports,
and the host curl failing to compile the intended header.

After extending the RED cases to include reflected-body artifact protection and
public redirect controls, still before script repair:

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_ops_internal_auth.py -q --tb=short 2>&1 | tee /tmp/zhiyuan-ops-curl-expanded-red.log
```

Result: **27 failed, 25 passed**. Additional failures expose the launcher's saved
authenticated response body. All credentials used in these tests are synthetic.

### GREEN

From `zhiyuan-agent`, after the script repairs, with `pipefail` enabled:

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_ops_internal_auth.py -q --tb=short 2>&1 | tee /tmp/zhiyuan-ops-curl-green.log
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_ops_internal_auth.py tests/unit/test_ops_release_smoke.py tests/unit/test_codex_local_stack_scripts.py -q --tb=short 2>&1 | tee /tmp/zhiyuan-ops-curl-regression.log
```

Results: **52 passed**, then **67 passed**, with no skips. The 52 auth-probe cases
include fake curl 200/302/401/timeout outcomes for every script, echoed credentials
in responses and stderr, missing/blank/CRLF credentials, quoted/backslash header
escaping, public 302 behavior, and seven real host-curl file-only checks. The other
15 regression cases cover existing mocked release smoke and safe launcher
syntax/early-rejection/access-environment paths. Only extracted launcher probe
functions, syntax checks, and non-launching guard/print modes run; no service is
started or restarted. Validation reports the host's existing unavailable-locale
warnings; the tests themselves pass.

From the repository root, syntax and scoped whitespace checks also pass:

```bash
for script in ops/healthcheck.sh ops/release-smoke.sh scripts/start-codex-local.sh; do bash -n "$script" || exit; done
git diff --check -- ops/healthcheck.sh ops/release-smoke.sh scripts/start-codex-local.sh zhiyuan-agent/tests/unit/test_ops_internal_auth.py zhiyuan-agent/tests/unit/test_ops_release_smoke.py docs/superpowers/reviews/2026-10-16-internal-auth-rollout.md
```

This follow-up does not re-run the earlier Java/client/config verification; those
results remain historical evidence above. No live probes, network calls,
production/test databases, deployments, service restarts, or Node commands run.
Authenticated diagnostics are deliberately limited; a 3xx health route must be
replaced with its final trusted URL, not made to follow redirects. Operators must
keep credentials out of shell tracing and explicitly provision the shared token
before any later, separately authorized rollout.

## Coordinated rollout requirements

1. Inventory all direct consumers of the protected namespaces, including admin
   integrations, monitoring, remote asset collection, and replay tooling. Migrate
   remaining consumers before enabling this code in a shared environment.
2. Provision the same nonempty secret in Java, Agent, the environment inherited by
   Codex/MCP, and trusted probes. Set `INTERNAL_SERVICE_URL` explicitly to the final
   trusted backend. Ensure no private Spring property overrides the intended
   environment credential with a different or blank value.
3. Schedule coordinated activation: clients can send the new header to an old
   backend, but the protected backend immediately denies old/missing credentials.
   This patch intentionally has no permissive migration switch. A blank token is
   a fail-closed outage, not an emergency authentication bypass.
4. In an authorized isolated environment, verify no/malformed token yields 401,
   a wrong token yields 403, the correct token reaches representative read-only
   internal/evidence/health routes, and public login/base-data/user-auth semantics
   remain unchanged. Run authenticated probes without tracing or secret output.
5. Keep TLS verification, private network controls, and browser-proxy denial in
   place. A shared credential authenticates a trusted service, not an individual
   end user; it is not tenant authorization, mTLS, or per-service least privilege.
   Do not expose the internal surface or distribute its credential to browsers.
6. Plan credential rotation across all processes together. Java and the
   import-constructed Python client load credentials at startup; this patch does
   not hot-reload them and accepts no overlapping old/new-token grace window.
   No restart or rotation has been performed here.
