#!/usr/bin/env python3
"""Explicitly applied local synthetic HTTP+DB probe. Never validates real admission data."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import yaml

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/codex-local'
SOURCE_ROOT = LOCAL / 'tmp'
EVIDENCE_ROOT = ROOT / '.runtime/validation'
BUILDER = Path(__file__).with_name('build_synthetic_source_fixture.py')
CONTAINER = 'zhiyuan-codex-local-mysql-1'
DATABASE = 'zhiyuan_codex_local'
BASE = 'http://127.0.0.1:18290/gaotu-assistant-bot'
TOKEN = None
OUT = None
SESSION = None
USER = None
MARKER = None


def validate_local_config():
    config_path = LOCAL / 'application-codex-local.yml'
    check(config_path.is_file() and not config_path.is_symlink(), 'local Java config must be a real private file')
    config = yaml.safe_load(config_path.read_text())
    check(isinstance(config, dict), 'local Java config is not a mapping')
    spring = config.get('spring') or {}
    jdbc = (((spring.get('datasource') or {}).get('dynamic') or {}).get('datasource') or {}).get('master') or {}
    jdbc_url = jdbc.get('url') or ''
    check(re.fullmatch(r'jdbc:mysql://127\.0\.0\.1:13306/zhiyuan_codex_local\?.*', jdbc_url) is not None,
          'Java JDBC must target isolated local MySQL:13306/zhiyuan_codex_local')
    check(((config.get('volunteer') or {}).get('rank') or {}).get('url') == 'http://127.0.0.1:18292',
          'rank URL must be local port 18292')
    gaotu = ((config.get('gaotu') or {}).get('zhiyuan') or {})
    check(gaotu.get('temp-data-path') == str(SOURCE_ROOT), 'wrong isolated source path')
    for name in ('zhiyuan-url', 'program-data-url', 'user-url', 'risk-url'):
        check(gaotu.get(name) == 'https://127.0.0.1.invalid', 'Gaotu %s must be disabled' % name)
    oss = ((config.get('ali') or {}).get('oss') or {})
    check(oss.get('enabled') is False, 'OSS must be explicitly disabled in local Java config')
    check(oss.get('namespace') == 'codex-local', 'OSS namespace must be codex-local')
    return config_path


def validate_live_backend(log_path, config_path):
    log_path = log_path.resolve(strict=True)
    run_dir = log_path.parent.parent
    check(log_path.name == 'backend.log' and log_path.parent.name == 'logs'
          and run_dir.parent == (ROOT / '.runtime').resolve()
          and re.fullmatch(r'codex-local-[A-Za-z0-9_-]+', run_dir.name),
          'backend log must belong to an ignored codex-local runtime')
    pid = int((run_dir / 'pids/backend.pid').read_text().strip())
    check(pid > 0, 'invalid backend PID')
    os.kill(pid, 0)
    args = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
    check(str(run_dir / 'zhiyuan-server.jar').encode() in args, 'backend PID is not this runtime jar')
    check(('file:' + str(config_path)).encode() in b' '.join(args), 'backend does not use checked private config')
    check(b'--server.port=18290' in args and b'--server.address=127.0.0.1' in args,
          'backend endpoint is not isolated loopback:18290')
    rank_pid = int((run_dir / 'pids/rank.pid').read_text().strip())
    check(rank_pid > 0, 'invalid rank PID')
    os.kill(rank_pid, 0)
    rank_args = (Path('/proc') / str(rank_pid) / 'cmdline').read_bytes().split(b'\0')
    check(str(ROOT / 'zhiyuan-rank/.venv/bin/gunicorn').encode() in rank_args
          and b'127.0.0.1:18292' in rank_args,
          'Rank PID is not the isolated loopback:18292 service')
    log = log_path.read_text(errors='replace')
    check(re.search(r'INFO\s+' + str(pid) + r'\b[^\n]*AliOSSService[^\n]*OSS disabled for this environment', log),
          'current backend startup log lacks OSS disabled evidence')
    check(not re.search(r'INFO\s+' + str(pid) + r'\b[^\n]*AliOSSService[^\n]*OSS客户端初始化完成', log),
          'current backend initialized an OSS client')
    return log_path


def remote_bridge_lines(log_text):
    """Only count remote bridge activity; disabled skip messages are expected."""
    return [line for line in log_text.splitlines()
            if (('AliOSSService' in line and ('开始从OSS下载文件' in line or '开始上传文件到OSS' in line))
                or ('JsonHttpUtil' in line and '127.0.0.1.invalid' in line))]


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=120)
    check(result.returncode == 0, 'local subprocess failed (output suppressed to protect credentials)')
    return result.stdout.strip()


def sql(statement):
    return command(['docker', 'exec', '-i', CONTAINER, 'sh', '-c',
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -N -B -u root -D "$MYSQL_DATABASE"'], statement)


def save(name, value):
    with (OUT / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def http(path, body=None):
    headers = {'Content-Type': 'application/json', 'pf': 'WEB'}
    if TOKEN:
        headers['tk'] = TOKEN
    request = urllib.request.Request(BASE + path,
              data=None if body is None else json.dumps(body).encode(), headers=headers,
              method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.load(response)
    except Exception:
        raise RuntimeError('local HTTP request failed: ' + path.split('?')[0]) from None
    check(value.get('code') == 0, 'HTTP business failure code=%s path=%s' % (value.get('code'), path.split('?')[0]))
    return value.get('data')


def ownership():
    expected = '%d\t1\t1\t%s' % (USER, MARKER)
    actual = sql('SELECT user_id,tenant_id,bot_id,user_name FROM assistant_chat_session WHERE id=%d AND session_status IN (0,1);' % SESSION)
    check(actual == expected, 'test session ownership/tenant/status/marker mismatch')


def latest_metadata(key):
    check(key in ('planningState', 'planningCandidatePool', 'userScoreDetail', 'userprofile'), 'unapproved metadata key')
    raw = sql("SELECT HEX(data_value) FROM assistant_chat_session_extra_data WHERE chat_session_id=%d AND data_key='%s' ORDER BY data_version DESC,id DESC LIMIT 1;" % (SESSION,key))
    return json.loads(bytes.fromhex(raw).decode()) if raw else None


def ids(items):
    return [row['volunteerId'] for row in items]


def workspace():
    return http('/chat/1/planning/session/workspace-state?chatSessionId=%d' % SESSION)


def working_plan(document):
    value = document.get('workingPlanState')
    if isinstance(value, dict) and value.get('$ref') == '$.draftPlanState' and set(value) == {'$ref'}:
        value = document.get('draftPlanState')
    if value is None:
        value = document.get('draftPlanState')
    check(isinstance(value,dict) and isinstance(value.get('items'),list), 'working plan schema must have actual items or known draftPlanState root reference')
    return value


def resume(evidence, backend_log):
    global OUT, SESSION, MARKER
    check(evidence.is_dir() and not evidence.is_symlink(), 'resume evidence must be an existing real directory')
    manifest = json.loads((evidence/'manifest.json').read_text())
    check(manifest.get('synthetic') is True and manifest['owner']==USER and manifest['tenantId']==1,
          'resume fixture owner/tenant mismatch')
    SESSION = int(manifest['sessionId'])
    MARKER = manifest['marker']
    check(SESSION>0 and re.fullmatch(r'SYNTHETIC-chain-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}', MARKER), 'resume fixture marker invalid')
    ownership()
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    OUT = EVIDENCE_ROOT / ('resume-' + MARKER + '-' + secrets.token_hex(3))
    OUT.mkdir(mode=0o700, exist_ok=False)
    before_write = latest_metadata('planningState')
    before_pool = latest_metadata('planningCandidatePool')
    final = workspace()
    query = http('/chat/1/planning/session/candidate-pool/query?chatSessionId=%d' % SESSION, {'page':1,'pageSize':100})
    current = latest_metadata('planningState')
    pool = latest_metadata('planningCandidatePool')
    check(before_write==current and before_pool==pool, 'independent reads unexpectedly mutated planning documents')
    save('workspace-get.json',final)
    save('candidate-query.json',query)
    save('planning-state-sql.json',current)
    save('candidate-pool-sql.json',pool)
    source_metadata = json.loads((evidence/'source-placement.json').read_text())
    source_path = SOURCE_ROOT/('session_volunteer_%d.json'%SESSION)
    check(source_metadata['path']==str(source_path), 'resume source path mismatch')
    check(source_path.is_file() and not source_path.is_symlink(), 'resume source missing or symlink')
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    check(source_hash==source_metadata['sha256'], 'installed source bytes changed')
    fixture_source = evidence/'fixture'/source_path.name
    check(hashlib.sha256(fixture_source.read_bytes()).hexdigest()==source_hash, 'source differs from original synthetic fixture')
    raw_source = json.loads(source_path.read_text())
    check(len(raw_source['detailList'])==12 and raw_source['type']['code']=='OTOO', 'source12 OTOO mismatch')
    check({r['planSchoolDataId'] for r in raw_source['detailList']}=={'synthetic-%d-school-%02d'%(SESSION,i) for i in range(12)}, 'source IDs not exclusively synthetic session')
    score=latest_metadata('userScoreDetail')
    check(score['prepareType']['code']=='PREDICT' and score['volunteerCount']['majorCount']==10, 'resume score must remain PREDICT target10')
    candidates=query['items']
    check(query['total']==12 and len(candidates)==12, 'business failure: expected12 persisted candidates')
    check({c['planSchoolDataId'] for c in candidates}=={r['planSchoolDataId'] for r in raw_source['detailList']}, 'candidate/source identity mismatch')
    check(len(pool['items'])==12 and set(ids(pool['items']))==set(ids(candidates)), 'SQL candidate pool mismatch')
    draft=working_plan(final)
    sql_draft=working_plan(current)
    selected=ids(draft['items'])
    order=ids(final['orderedPlanState']['items'])
    check(len(selected)==10 and len(set(selected))==10 and set(selected)<=set(ids(candidates)), 'business failure: initial selection must be10 distinct source candidates')
    check(len(order)==10 and set(order)==set(selected), 'business failure: initial order must cover all selected10 exactly')
    check(selected==ids(sql_draft['items']) and order==ids(current['orderedPlanState']['items']), 'SQL/GET persisted draft or order mismatch')
    check([i['position'] for i in final['orderedPlanState']['items']]==list(range(1,11)), 'ordered positions must be1..10')
    check(draft['summary']['total']==10 and draft['summary']['targetCount']==10 and final['orderedPlanState']['summary']['total']==10, 'summary counts mismatch')
    check(all(i.get('source')=='initial_auto' for i in sql_draft['items']), 'draft must originate in actual initial generation')
    historical_before=json.loads((evidence/'01-before-get.json').read_text())
    historical_pool=json.loads((evidence/'03-pool-independent-get.json').read_text())
    check(not working_plan(historical_before)['items'] and not working_plan(historical_pool)['items'], 'historical state was not empty before initial generation')
    check(final['version']==current['version'] and final['version']>historical_pool['version']>historical_before['version'], 'pool/initial version progression mismatch')
    check(pool['sourceVersion']==historical_pool['version'], 'pool sourceVersion mismatch')
    schedule=sql('SELECT enabled,prepare_type FROM assistant_planning_data_freshness_schedule WHERE chat_session_id=%d;'%SESSION)
    check(schedule=='0\tPREDICT', 'freshness background must remain disabled')
    # Original failed before recording the end-of-run log observation. Reconstruct
    # the window from its stored creation time, and report that limitation.
    check(backend_log and backend_log.is_file(), 'resume needs active backend log')
    started=datetime.datetime.fromtimestamp(float(manifest['createdAt']))
    until=datetime.datetime.now()
    timestamp=re.compile(r'^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)')
    sampled=0
    remote_lines=[]
    skipped_oss=0
    session_lines=0
    for line in backend_log.read_text(errors='replace').splitlines():
        match=timestamp.match(line)
        if not match:
            continue
        when=datetime.datetime.strptime(' '.join(match.groups()),'%Y-%m-%d %H:%M:%S')
        if started-datetime.timedelta(seconds=1)<=when<=until:
            sampled+=1
            session_lines+=bool(re.search(r'(?:chatSessionId|sessionId)[=: ]+'+str(SESSION)+r'\b',line))
            remote_lines.extend(remote_bridge_lines(line))
            skipped_oss += 'OSS download skipped because OSS is disabled' in line
    check(sampled>0 and session_lines>0, 'backend log window lacks fixture session evidence')
    observation={'logPath':str(backend_log),'fromManifestCreatedAt':manifest['createdAt'],'until':time.time(),
                 'sampledTimestampedLines':sampled,'sessionLines':session_lines,
                 'remoteBridgeLogCount':len(remote_lines),'disabledOssSkipCount':skipped_oss,
                 'startupOssDisabled':True,
                 'qualification':'reconstructed log window; no original byte offset, packet capture, or proof for other workloads'}
    save('external-call-log-observation.json',observation)
    summary={'status':'SYNTHETIC_HTTP_DB_READBACK_PASSED' if not remote_lines else 'PERSISTENCE_PASSED_REMOTE_BRIDGE_LOGGED',
             'generationAndPersistencePassed':True,'remoteBridgeObservedInLog':bool(remote_lines),
             'realadmission':False,'confirm':False,'synthetic':True,'sessionId':SESSION,'candidateCount':12,
             'selectedCount':10,'orderedCount':10,'version':final['version'],
             'historicalVersions':[historical_before['version'],historical_pool['version'],final['version']],
             'sourceSha256':source_hash,'noGenerationOrInitializationRepeated':True,
             'planningDocumentsUnchangedByResume':True,'confirmed':False,'realAdmissionValidated':False}
    save('summary.json',summary)
    print(json.dumps(dict(summary,evidenceDirectory=str(OUT))))
    check(not remote_lines, 'persisted12/10/10 verified but a remote bridge logged activity in the observation window')


def main():
    global TOKEN, OUT, SESSION, USER, MARKER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--resume-evidence',type=Path,help='only independent reads of existing synthetic evidence/session')
    parser.add_argument('--backend-log', type=Path, help='active local backend log, required with --apply')
    arguments = parser.parse_args()
    if not arguments.apply:
        print('Dry run only. --apply creates one isolated SYNTHETIC draft session, metadata and a new ORIGINAL file, then checks 12 candidates and 10 selected/ordered items. No confirm/directapply.')
        return
    check(arguments.backend_log and arguments.backend_log.is_file(), '--apply requires an existing active --backend-log')
    config_path = validate_local_config()
    backend_log = validate_live_backend(arguments.backend_log, config_path)
    check(BUILDER.is_file() and BUILDER.parent == Path(__file__).resolve().parent,
          'repository fixture builder missing')
    log_stat = backend_log.stat()
    log_offset = log_stat.st_size
    os.umask(0o077)
    check(command(['docker','port',CONTAINER,'3306/tcp']) == '127.0.0.1:13306', 'wrong database port binding')
    command(['docker','exec',CONTAINER,'sh','-c','test "$MYSQL_DATABASE" = "zhiyuan_codex_local"'])
    with socket.create_connection(('127.0.0.1',18292), timeout=5):
        pass
    credentials = json.loads((LOCAL / 'browser-test-credentials.json').read_text())
    check(credentials['username'] == 'codex-test' and int(credentials['tenantId']) == 1, 'not local codex-test identity')
    USER = int(credentials['userId'])
    check(USER > 0, 'invalid fixture owner')
    # Prevent proxies/redirects from sending login/token to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()))
    result = http('/chat/user/login/by-pwd', {'userName':'codex-test','password':credentials['password']})
    TOKEN = result['loginToken']
    check(TOKEN and int(result['tenantId']) == 1, 'login tenant mismatch')
    # SQL proves the authenticated token belongs to the pre-existing fixture; token is HEX encoded, never logged.
    token_hex = TOKEN.encode().hex()
    check(sql("SELECT COUNT(*) FROM assistant_user_credential c JOIN assistant_user_base u ON u.id=c.user_id WHERE u.id=%d AND u.tenant_id=1 AND c.login_type=2 AND c.identifier='codex-test' AND BINARY c.login_token=CONVERT(0x%s USING utf8mb4);" % (USER, token_hex)) == '1', 'authenticated token owner mismatch')
    if arguments.resume_evidence:
        resume(arguments.resume_evidence,backend_log)
        return
    MARKER = 'SYNTHETIC-chain-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(4)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    OUT = EVIDENCE_ROOT / ('zhiyuan-' + MARKER)
    OUT.mkdir(mode=0o700, exist_ok=False)
    created = http('/chat/1/session/create', {'draft':True,'botId':1,'userName':MARKER,'prepareType':{'code':'PREDICT','desc':'合成模拟'}})
    SESSION = int(created['id'])
    check(SESSION > 0, 'invalid new session')
    ownership()
    save('manifest.json', {'sessionId':SESSION,'owner':USER,'tenantId':1,'marker':MARKER,'synthetic':True,'createdAt':time.time()})
    generated = OUT / 'fixture'
    command([sys.executable, str(BUILDER), '--apply', '--session-id',str(SESSION),'--output-dir',str(generated)])
    score = json.loads((generated/'score-detail.json').read_text())
    score['userName'] = MARKER
    # Write only the two allowed metadata keys on this brand-new session, guarded in a single transaction.
    score_hex = json.dumps(score, ensure_ascii=False).encode().hex()
    statement = '''START TRANSACTION;
SELECT id FROM assistant_chat_session WHERE id=%d AND user_id=%d AND tenant_id=1 AND bot_id=1 AND user_name='%s' AND session_status IN (0,1) FOR UPDATE;
SET @probe_guard=(SELECT COUNT(*) FROM assistant_chat_session WHERE id=%d AND user_id=%d AND tenant_id=1 AND bot_id=1 AND user_name='%s' AND session_status IN (0,1))=1 AND (SELECT COUNT(*) FROM assistant_chat_session_extra_data WHERE chat_session_id=%d AND data_key IN ('userScoreDetail','userprofile','planningState','planningCandidatePool'))=0;
INSERT INTO assistant_chat_session_extra_data(chat_session_id,data_key,data_type,data_value,data_version) SELECT %d,'userScoreDetail',5,CONVERT(0x%s USING utf8mb4),0 WHERE @probe_guard; SELECT ROW_COUNT();
INSERT INTO assistant_chat_session_extra_data(chat_session_id,data_key,data_type,data_value,data_version) SELECT %d,'userprofile',5,'{}',0 WHERE @probe_guard; SELECT ROW_COUNT();
COMMIT;''' % (SESSION,USER,MARKER,SESSION,USER,MARKER,SESSION,SESSION,score_hex,SESSION)
    check(sql(statement).splitlines() == [str(SESSION),'1','1'], 'metadata initialization guard rejected')
    check(latest_metadata('userScoreDetail') == score and latest_metadata('userprofile') == {}, 'metadata SQL readback mismatch')
    source = generated / ('session_volunteer_%d.json' % SESSION)
    check(SOURCE_ROOT.is_dir() and not SOURCE_ROOT.is_symlink(), 'source root must be existing real local directory')
    destination = SOURCE_ROOT / source.name
    descriptor = os.open(destination, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(source.read_bytes())
    source_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    save('source-placement.json', {'path':str(destination),'sha256':source_hash})
    before = workspace()
    save('01-before-get.json',before)
    check(not before.get('candidatePoolState',{}).get('items'), 'fresh session already has candidate items')
    ownership()
    pool_response = http('/chat/1/planning/session/candidate-pool/generate?chatSessionId=%d' % SESSION, {'forceRegenerate':True,'refreshSourceData':False})
    save('02-pool-response.json',pool_response)
    after_pool = workspace()
    save('03-pool-independent-get.json',after_pool)
    pool_sql_state = latest_metadata('planningState')
    pool_sql = latest_metadata('planningCandidatePool') or pool_sql_state.get('candidatePoolState')
    save('04-pool-sql-state.json',pool_sql_state)
    save('05-pool-sql-document.json',pool_sql)
    independent_query = http('/chat/1/planning/session/candidate-pool/query?chatSessionId=%d' % SESSION, {'page':1,'pageSize':100})
    save('03b-pool-independent-query.json',independent_query)
    candidates = independent_query['items']
    check(independent_query['total']==12, 'candidate query total must be12')
    expected = {'synthetic-%d-school-%02d' % (SESSION,i) for i in range(12)}
    check(len(candidates)==12 and {c['planSchoolDataId'] for c in candidates}==expected, 'expected all12 synthetic candidates')
    check(set(ids(pool_sql['items']))==set(ids(candidates)), 'candidate SQL/GET mismatch')
    check(after_pool['version'] > before['version'] and pool_sql_state['version']==after_pool['version'], 'pool version did not persist')
    check(not after_pool['staleFlags']['candidatePool'], 'candidate stale flag not cleared')
    ownership()
    initial = http('/chat/1/planning/session/initial-plan/generate?chatSessionId=%d' % SESSION, {'forceRegenerate':False,'regroupByTier':True,'overwriteExistingDraft':False})
    save('06-initial-response.json',initial)
    final = workspace()
    save('07-initial-independent-get.json',final)
    final_sql = latest_metadata('planningState')
    save('08-initial-sql-state.json',final_sql)
    draft = working_plan(final)
    ordered = final['orderedPlanState']
    selected = ids(draft['items'])
    order = ids(ordered['items'])
    check(len(selected)==10 and len(set(selected))==10 and set(selected)<=set(ids(candidates)), 'initial plan expected10 unique synthetic candidates')
    check(len(order)==10 and set(order)==set(selected), 'ordered plan must cover selected10 exactly')
    check(final['version']>after_pool['version'] and final_sql['version']==final['version'], 'initial version did not persist')
    sql_draft = working_plan(final_sql)
    check(ids(sql_draft['items'])==selected and ids(final_sql['orderedPlanState']['items'])==order, 'SQL independent selected/order mismatch')
    check(not (after_pool.get('workingPlanState') or after_pool.get('draftPlanState') or {}).get('items'), 'pool generation unexpectedly selected a draft')
    check(not after_pool.get('orderedPlanState',{}).get('items'), 'pool generation unexpectedly ordered a plan')
    check(hashlib.sha256(destination.read_bytes()).hexdigest()==source_hash, 'source mutated unexpectedly')
    schedule = sql('SELECT enabled,prepare_type FROM assistant_planning_data_freshness_schedule WHERE chat_session_id=%d;' % SESSION)
    check(schedule == '0\tPREDICT', 'test freshness schedule must stay disabled PREDICT')
    current_log_stat = backend_log.stat()
    check(current_log_stat.st_ino == log_stat.st_ino and current_log_stat.st_size >= log_offset,
          'backend log rotated/truncated; cannot verify external-call observation')
    with backend_log.open('rb') as log_stream:
        log_stream.seek(log_offset)
        interval_log = log_stream.read().decode(errors='replace')
    remote_lines = remote_bridge_lines(interval_log)
    skipped_oss = interval_log.count('OSS download skipped because OSS is disabled')
    save('09-external-call-log-observation.json', {'logPath':str(backend_log),'offsetStart':log_offset,
         'offsetEnd':current_log_stat.st_size,'remoteBridgeLogCount':len(remote_lines),
         'disabledOssSkipCount':skipped_oss,'startupOssDisabled':True,
         'qualification':'bounded backend log observation; not a packet capture or proof for other workloads'})
    check(not remote_lines, 'backend interval logged a remote bridge call; inspect privately')
    save('summary.json', {'synthetic':True,'sessionId':SESSION,'poolCount':len(candidates),'selectedCount':len(selected),'orderedCount':len(order),'beforeVersion':before['version'],'poolVersion':after_pool['version'],'finalVersion':final['version'],'schedule':schedule,'sourceSha256':source_hash,'confirmed':False,'realAdmissionValidated':False,'remoteBridgeObservedInLog':False})
    save('cleanup.json', {'synthetic':True,'database':DATABASE,'container':CONTAINER,
         'sessionId':SESSION,'tenantId':1,'userId':USER,'marker':MARKER,
         'sourcePath':str(destination),'evidenceDirectory':str(OUT),
         'sessionScopedTables':['assistant_chat_session','assistant_chat_session_extra_data',
                                'assistant_chat_message','assistant_planning_data_freshness_schedule',
                                'assistant_planning_behavior_event','assistant_planning_pending_command'],
         'instruction':'Recheck session owner/tenant/marker and dependent row IDs before any targeted cleanup; never delete by prefix.'})
    print(json.dumps({'status':'SYNTHETIC_HTTP_DB_CHAIN_PASSED','sessionId':SESSION,'evidenceDirectory':str(OUT),'poolCount':12,'selectedCount':10,'orderedCount':10,'confirmed':False,'realAdmissionValidated':False}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Probe stopped: %s; sessionId=%s; evidenceDirectory=%s' % (str(error),SESSION,OUT), file=sys.stderr)
        sys.exit(1)
