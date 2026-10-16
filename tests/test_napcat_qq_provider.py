"""Fictional NapCat core over the real Echo HTTP bridge; no QQ/account state.

The bridge requires a client credential for every RPC method.  These tests use
fictional in-memory values only and a marker file written by the fictional core,
so "the request was refused" can be proven to mean "nothing was executed".
"""
import importlib
import http.client
import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts/qq_napcat_plugin/bridge.mjs"

TOKEN = "0123456789abcdef" * 4
WRONG_TOKEN = "fedcba9876543210" * 4
RUNTIME_ID = "ab" * 32

SERVER = """
import {startBridge} from './bridge.mjs';
import fs from 'node:fs';
const config = JSON.parse(process.argv[2]);
const mark = name => { if (config.marker) fs.appendFileSync(config.marker, name + '\\n'); };
const info = fields => new Proxy(fields, {get(target, key) { mark('Core.status'); return target[key]; }});
const core={dbPassphrase:'PRIVATE',selfInfo:info({uin:'12345678',uid:'u_self',nick:'Self',online:true,secret:'PRIVATE'}),apis:{
 DatabaseApi:{hasPassphrase:()=>true,decryptDatabase(){mark('decryptDatabase')}},
 FriendApi:{getBuddyV2ExWithCate:async()=>{mark('listFriends');return [{buddyList:[{uin:'23456789',uid:'u_friend',coreInfo:{uin:'23456789',uid:'u_friend',nick:'Nick',remark:'Remark',secret:'PRIVATE'},secret:'PRIVATE'},{uid:'u_only'},{uin:'34567890'}]}]}},
 GroupApi:{getGroups:async()=>{mark('listGroups');return [{groupCode:'45678901',groupName:'Group',memberCount:3},{groupCode:'56789012'}]},getGroupMemberAll:async()=>{mark('getGroupMemberAll');return {result:{infos:new Map([['u_member',{uid:'u_member',uin:'23456789',nick:'Nick',cardName:'Card',secret:'PRIVATE'}]])}}}}
}};
let snapshot={
 acquire:async()=>{mark('acquire');return {ok:true,status:'ready',generation_id:'test-generation'}},
 cleanup:async()=>{mark('cleanup');return {ok:true,status:'cleaned'}},
 recover:async()=>{mark('recover');return {ok:true,status:'recovered'}}};
if(config.mode==='slow-acquire') snapshot.acquire=async()=>{
  mark('acquire'); await new Promise(resolve=>setTimeout(resolve,200));
  mark('ready'); return {ok:true,status:'ready',generation_id:'test-generation'};
};
if(config.mode==='blocked-acquire') snapshot.acquire=async()=>{
  mark('acquire'); const until=performance.now()+100;
  while(performance.now()<until) {} // A synchronous capture cannot receive socket-close events.
  mark('ready');return {ok:true,status:'ready',generation_id:'test-generation'};
};
if(config.mode==='direct-db') {
  const {createEchoSnapshotApi}=await import(config.snapshotModule);
  const path=await import('node:path');let mutated=false;
  core.apis.DatabaseApi.getNtDbDir=()=>config.sourceDirectory;
  core.apis.DatabaseApi.decryptDatabase=async(_input,target)=>{
    if(config.decryptDelay) await new Promise(resolve=>setTimeout(resolve,config.decryptDelay));
    fs.copyFileSync(config.plaintext,target);mark('direct-decrypted');return true;
  };
  snapshot=createEchoSnapshotApi(core,{rootDirectory:config.snapshotRoot,onCapturePhase:phase=>{
    if(phase!=='main_baseline_read') return;
    mark('capture');
    if(config.transientMain && !mutated) {
      mutated=true;const main=path.join(config.sourceDirectory,'nt_msg.db');
      const bytes=fs.readFileSync(main);bytes[100]^=1;fs.writeFileSync(main,bytes);
    }
  }});
}
if(config.mode==='offline'){core.selfInfo=info({online:false});core.apis.DatabaseApi={};}
if(config.mode==='empty'){core.apis.FriendApi.getBuddyV2ExWithCate=async()=>{mark('listFriends');return []};core.apis.GroupApi.getGroups=async()=>{mark('listGroups');return []};}
if(config.mode==='failure'){core.apis.FriendApi.getBuddyV2ExWithCate=async()=>{mark('listFriends');throw Error('PRIVATE passphrase token path')};}
const bridge=await startBridge(core,snapshot,{port:config.port ?? 0,token:config.token,runtimeId:config.runtimeId ?? null});
console.log(JSON.stringify({port:bridge.port}));
process.stdin.resume();process.stdin.on('end',async()=>{await bridge.stop();});
"""


class _Credential:
    """Stand-in for the real session: exposes the current credential only."""

    def __init__(self, value=TOKEN):
        self._value = value

    def credential(self):
        return self._value


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    assert BRIDGE.is_file(), "Echo bridge missing"
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for real bridge transport contract")
    directory = tmp_path_factory.mktemp("echo-bridge")
    shutil.copy2(BRIDGE, directory / "bridge.mjs")
    (directory / "server.mjs").write_text(SERVER, encoding="utf-8")
    processes = []
    by_base = {}

    def start(mode="ready", *, token=TOKEN, runtime_id=None, marker=None, port=0, **snapshot_options):
        config = {
            "mode": mode,
            "token": token,
            "runtimeId": runtime_id,
            "marker": str(marker) if marker is not None else "",
            "port": port,
            **snapshot_options,
        }
        process = subprocess.Popen(
            [node, str(directory / "server.mjs"), json.dumps(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        base = "http://127.0.0.1:" + str(json.loads(process.stdout.readline())["port"])
        by_base[base] = process
        return base

    def restart(base, **kwargs):
        process = by_base[base]
        process.stdin.close()
        process.wait(timeout=10)
        assert process.returncode == 0, process.stderr.read()
        return start(port=urllib.parse.urlsplit(base).port, **kwargs)

    start.restart = restart

    yield start
    for process in processes:
        if not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        assert process.returncode == 0, process.stderr.read()


def provider(base, credential=TOKEN):
    module = importlib.import_module("qq_chat_analyzer.providers.napcat_qq_provider")
    source = None if credential is None else _Credential(credential)
    return module.NapCatQQProvider(base, credential=source)


def test_abandoned_acquire_cleans_late_generation(runtime, tmp_path):
    import time
    marker = tmp_path / "fictional-operations.txt"
    base = runtime("slow-acquire", marker=marker)
    client = provider(base)
    boot = client.status().boot_id
    parsed = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    connection.request("POST", "/rpc", json.dumps({
        "method": "EchoSnapshotApi.acquire", "params": [], "boot_id": boot,
    }), headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        deadline = time.monotonic() + 3
        while "acquire" not in marker.read_text():
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        connection.close()
    deadline = time.monotonic() + 3
    while "cleanup" not in marker.read_text() and time.monotonic() < deadline:
        time.sleep(0.01)
    operations = marker.read_text().splitlines()
    assert operations.count("ready") == 1
    assert operations.count("cleanup") == 1


def test_optional_rpc_budget_includes_initial_status_handshake(monkeypatch):
    module = importlib.import_module('qq_chat_analyzer.providers.napcat_qq_provider')
    clock = [1000.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    timeouts = []
    def transport(url, body, timeout):
        method = json.loads(body)['method']
        timeouts.append(timeout)
        if method == 'Core.status':
            clock[0] += 3
            result = {'rpc_auth': 'bearer-v1', 'boot_id': 'b' * 64,
                      'bridge_ready': True, 'qq_online': True, 'self_info': {},
                      'database_api_ready': True, 'passphrase_ready': True, 'snapshot_api_ready': True}
        else:
            result = []
        return 200, json.dumps({'ok': True, 'result': result})
    client = module.NapCatQQProvider(credential=_Credential(), transport=transport)
    assert client.list_groups(timeout=5) == []
    assert timeouts == [5, 2]


def test_expired_acquire_budget_discards_ready_result_even_while_socket_is_open(runtime, tmp_path):
    marker = tmp_path / 'fictional-deadline.txt'
    base = runtime('blocked-acquire', marker=marker)
    boot = provider(base).status().boot_id
    status, payload = request(base, raw=json.dumps({
        'method': 'EchoSnapshotApi.acquire', 'params': [], 'boot_id': boot, 'timeout_ms': 50,
    }).encode())
    assert status == 200 and payload == {'ok': False, 'error': 'qq_runtime_operation_failed'}
    assert marker.read_text().splitlines().count('cleanup') == 1


@pytest.mark.parametrize('budget', [0, -1, 65001, 'PRIVATE_BUDGET', True])
def test_invalid_acquire_budget_cannot_start_capture(runtime, tmp_path, budget):
    marker = tmp_path / 'fictional-invalid-budget.txt'
    base = runtime(marker=marker)
    boot = provider(base).status().boot_id
    status, payload = request(base, raw=json.dumps({
        'method': 'EchoSnapshotApi.acquire', 'params': [], 'boot_id': boot, 'timeout_ms': budget,
    }).encode())
    assert status == 400 and payload == {'ok': False, 'error': 'invalid_params'}
    assert 'acquire' not in marker.read_text().splitlines()


@pytest.mark.slow_integration
@pytest.mark.parametrize("scenario", ['ready', 'abandon', 'transient_main'])
def test_real_bridge_snapshot_to_facade_and_abandoned_cleanup(runtime, tmp_path, monkeypatch, scenario):
    import sqlite3
    import time
    from contextlib import closing
    from types import SimpleNamespace
    from test_qq_direct_main_wal_poc import _reserve_48_bytes, _run
    from test_qq_direct_snapshot_workspace import _run as run_workspace
    from test_qq_direct_database_facade import _create_plaintext_snapshot
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource, FacadeError
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
        QQDirectDatabaseImportService,
    )
    plain = tmp_path / 'fictional.db'
    selected = tmp_path / 'selected.db'
    source = tmp_path / 'source'
    source.mkdir()
    _reserve_48_bytes(plain)
    _create_plaintext_snapshot(plain)
    with closing(sqlite3.connect(plain)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE group_msg_table SET "40050"="40050"+1')
        writer.commit()
        with closing(sqlite3.connect(selected)) as backup:
            writer.backup(backup)
        _run('fixture', plain, Path(f'{plain}-wal'), source / 'nt_msg.db', source / 'nt_msg.db-wal')
    root = tmp_path / 'workspace'
    marker = tmp_path / 'operations.txt'
    base = runtime('direct-db', marker=marker,
                   snapshotModule=(ROOT / 'scripts/qq_direct_db_snapshot/snapshot.mjs').as_uri(),
                   snapshotRoot=str(root), sourceDirectory=str(source), plaintext=str(selected),
                   decryptDelay=200 if scenario == 'abandon' else 0,
                   transientMain=scenario == 'transient_main')
    metadata = provider(base)
    metadata.status()
    client = metadata.snapshot_client(root)
    service = QQDirectDatabaseImportService(runtime_client=client,
                                           provider_factory=SimpleNamespace(create=lambda: metadata))
    service.start()
    if scenario == 'abandon':
        monkeypatch.setattr(client, '_acquire_timeout', 0.05)
    try:
        facade = ChatAnalyzerFacade(qq_service=service)
        if scenario == 'abandon':
            with pytest.raises(FacadeError) as caught:
                facade.list_sessions(ChatSource.QQ)
            assert caught.value.code == 'qq_direct_snapshot_acquire_failed'
        else:
            assert {s.session_type for s in facade.list_sessions(ChatSource.QQ)} == {'group', 'private'}
        deadline = time.monotonic() + 5
        while (not marker.exists() or 'direct-decrypted' not in marker.read_text() or
               (root / 'staging').exists() or any((root / 'generations').glob('*'))):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert run_workspace(root, 'workspace.recover();')['ok']
        assert marker.read_text().splitlines().count('capture') == (2 if scenario == 'transient_main' else 1)
    finally:
        client.recover()


def request(base, method="Core.status", params=None, *, raw=None, headers=None,
            credential=TOKEN, path="/rpc"):
    payload = {"method": method, "params": params or []}
    if raw is None and method != "Core.status" and credential == TOKEN:
        payload["boot_id"] = request(base)[1]["result"]["boot_id"]
    body = raw if raw is not None else json.dumps(payload).encode()
    authorization = {} if credential is None else {"Authorization": f"Bearer {credential}"}
    req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json", **authorization, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def executed(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.mark.parametrize("method,params", [
    ("EchoMetadata.listFriends", []),
    ("EchoSnapshotApi.cleanup", ["old-generation"]),
])
@pytest.mark.parametrize("boot", [None, "a" * 64])
def test_worker_generation_gate_prevents_all_operations(runtime, tmp_path, method, params, boot):
    calls = tmp_path / "calls.txt"
    base = runtime(runtime_id=RUNTIME_ID, marker=calls)
    body = {"method": method, "params": params}
    if boot is not None:
        body["boot_id"] = boot
    code, value = request(base, raw=json.dumps(body).encode(), path=f"/rpc/{RUNTIME_ID}")
    assert (code, value) == (409, {"ok": False, "error": "worker_generation_mismatch"})
    assert executed(calls) == ""


def test_worker_boot_is_fresh_and_same_generation_operates(runtime):
    base = runtime()
    boot = request(base)[1]["result"]["boot_id"]
    assert len(boot) == 64 and all(c in "0123456789abcdef" for c in boot)
    assert request(base)[1]["result"]["boot_id"] == boot
    assert request(runtime())[1]["result"]["boot_id"] != boot
    body = {"method": "EchoSnapshotApi.recover", "params": [], "boot_id": boot}
    assert request(base, raw=json.dumps(body).encode())[1]["result"]["ok"] is True


def test_auth_then_workspace_then_worker_generation(runtime, tmp_path):
    calls = tmp_path / "calls.txt"
    base = runtime(runtime_id=RUNTIME_ID, marker=calls)
    body = json.dumps({"method": "EchoSnapshotApi.acquire", "boot_id": "a" * 64}).encode()
    assert request(base, raw=body, credential=WRONG_TOKEN) == (
        401, {"ok": False, "error": "invalid_credential"})
    assert request(base, raw=body) == (
        409, {"ok": False, "error": "runtime_identity_mismatch"})
    assert request(base, raw=body, path=f"/rpc/{RUNTIME_ID}") == (
        409, {"ok": False, "error": "worker_generation_mismatch"})
    assert executed(calls) == ""


@pytest.mark.parametrize("method,params", [("EchoSnapshotApi.acquire", [])])
def test_managed_bound_calls_check_workspace_before_generation(runtime, tmp_path, method, params):
    calls = tmp_path / "calls.txt"
    base = runtime(runtime_id=RUNTIME_ID, marker=calls)
    boot = request(base)[1]["result"]["boot_id"]
    before = executed(calls)
    for presented in (boot, "a" * 64):
        body = json.dumps({"method": method, "params": params, "boot_id": presented}).encode()
        assert request(base, raw=body) == (409, {"ok": False, "error": "runtime_identity_mismatch"})
    assert executed(calls) == before


@pytest.mark.slow_integration
def test_same_endpoint_worker_restart_refuses_old_provider_and_snapshot(runtime, tmp_path):
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQWorkerGenerationChanged
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotWorkerGenerationChanged
    base = runtime(runtime_id=RUNTIME_ID)
    old = provider(base)
    boot = old.status().boot_id
    snapshot = old.snapshot_client(tmp_path)
    generation = snapshot.acquire()
    calls = tmp_path / "new-worker-calls.txt"
    assert runtime.restart(base, runtime_id=RUNTIME_ID, marker=calls) == base
    with pytest.raises(QQSnapshotWorkerGenerationChanged):
        snapshot.cleanup(generation)
    with pytest.raises(NapCatQQWorkerGenerationChanged):
        old.status()
    assert executed(calls) == ""  # Even stale status was stopped before selfInfo access.
    fresh = provider(base)
    assert fresh.status().boot_id != boot
    fresh.snapshot_client(tmp_path).recover()
    assert "recover" in executed(calls)


# ------------------------------------------------------------------ happy path


def test_status_readiness_and_no_passphrase(runtime):
    base=runtime()
    status=provider(base).status()
    assert status.bridge_ready and status.qq_online and status.database_api_ready and status.passphrase_ready
    assert status.self_info == {"uin":"12345678","uid":"u_self","nickname":"Self"}
    assert status.snapshot_api_ready and status.ready
    assert "PRIVATE" not in json.dumps(request(base)[1])
    offline=provider(runtime("offline")).status()
    assert offline.bridge_ready and not offline.qq_online and not offline.passphrase_ready and not offline.ready


def test_friends_identity_names_and_missing_field_fallback(runtime):
    friends=provider(runtime()).list_friends()
    assert [(f.uid,f.uin,f.nickname,f.remark,f.display_name) for f in friends] == [
        ("u_friend","23456789","Nick","Remark","Remark"),("u_only","","","","u_only"),("","34567890","","","34567890")]
    assert provider(runtime("empty")).list_friends() == []


def test_groups_mapping_and_empty(runtime):
    groups=provider(runtime()).list_groups()
    assert [(g.group_code,g.group_name,g.member_count) for g in groups] == [("45678901","Group",3),("56789012","",None)]
    assert provider(runtime("empty")).list_groups() == []


def test_members_map_identity_and_existing_snapshot_contract(runtime,tmp_path):
    qq=provider(runtime())
    client=qq.snapshot_client(tmp_path)
    assert qq.get_group_member_all("45678901") == client.get_group_member_all("45678901")
    member=client.get_group_member_all("45678901")["result"]["infos"]["u_member"]
    assert member == {"uid":"u_member","uin":"23456789","nick":"Nick","cardName":"Card"}
    client.recover()
    generation=client.acquire()
    assert generation == "test-generation"
    client.cleanup(generation)
    client.recover()


# ------------------------------------------------------------- unified credential


def test_unauthenticated_core_status_is_refused_and_executes_nothing(runtime, tmp_path):
    calls = tmp_path / "calls.txt"
    base = runtime(marker=calls)
    code, value = request(base, credential=None)
    assert (code, value) == (401, {"ok": False, "error": "invalid_credential"})
    assert executed(calls) == ""


@pytest.mark.parametrize("method,params", [
    ("EchoMetadata.listFriends", []),
    ("EchoSnapshotApi.cleanup", ["fictional-generation"]),
])
def test_unauthenticated_rpc_is_refused_without_executing_the_method(runtime, tmp_path, method, params):
    calls = tmp_path / "calls.txt"
    base = runtime(marker=calls)
    code, value = request(base, method, params, credential=None)
    assert code == 401 and value == {"ok": False, "error": "invalid_credential"}
    assert executed(calls) == ""


@pytest.mark.parametrize("method", ["Core.status"])
def test_wrong_credential_is_refused_without_executing_the_method(runtime, tmp_path, method):
    calls = tmp_path / "calls.txt"
    base = runtime(marker=calls)
    code, value = request(base, method, credential=WRONG_TOKEN)
    assert code == 401 and value == {"ok": False, "error": "invalid_credential"}
    assert executed(calls) == ""


def test_malformed_or_absent_authorization_header_is_refused(runtime, tmp_path, monkeypatch):
    import time
    send = http.client.HTTPConnection.send

    def separated_body(connection, data):
        # urllib sends headers and body separately. An early refusal must not
        # close the socket while a small, rejected request is still arriving.
        if isinstance(data, bytes) and data.startswith(b'{'):
            time.sleep(0.025)
        return send(connection, data)

    monkeypatch.setattr(http.client.HTTPConnection, 'send', separated_body)
    calls = tmp_path / "calls.txt"
    base = runtime(marker=calls)
    for headers in ({}, {"Authorization": "fictional"}, {"Authorization": f"Basic {TOKEN}"},
                    {"Authorization": TOKEN}, {"Authorization": f"Bearer {WRONG_TOKEN}"}):
        code, value = request(base, headers=headers, credential=None)
        assert code == 401 and value == {"ok": False, "error": "invalid_credential"}
    assert executed(calls) == ""


def test_managed_bound_route_requires_the_credential_too(runtime, tmp_path):
    calls = tmp_path / "calls.txt"
    base = runtime(runtime_id=RUNTIME_ID, marker=calls)
    bound = f"/rpc/{RUNTIME_ID}"
    code, value = request(base, "EchoSnapshotApi.recover", credential=None, path=bound)
    assert code == 401 and value == {"ok": False, "error": "invalid_credential"}
    assert executed(calls) == ""
    # The credential and the runtime binding are two independent defenses.
    code, value = request(base, "EchoSnapshotApi.recover", credential=TOKEN, path=bound)
    assert code == 200 and value == {"ok": True, "result": {"ok": True, "status": "recovered"}}
    assert "recover" in executed(calls)


def test_authentication_response_never_echoes_the_credential(runtime):
    base = runtime()
    body = json.dumps(request(base, credential=WRONG_TOKEN)[1])
    assert WRONG_TOKEN not in body
    assert WRONG_TOKEN[:8] not in body
    assert len(body) < 200


def test_authorized_boundary_cases_are_unchanged(runtime):
    base=runtime()
    assert request(base,raw=b"{")[0] == 400
    assert request(base,raw=b"x"*4097)[0] == 413
    assert request(base,headers={"Origin":"https://outside.example"})[0] == 403
    assert request(base,headers={"Host":"outside.example"})[0] == 403
    assert request(base,raw=b'{"method":"Core.status","params":null}')[0] == 400
    assert request(base,headers={"Content-Type":"text/plain"})[0] == 415


@pytest.mark.parametrize("method,params",[("DatabaseApi.decryptDatabase",[]),("__proto__.pollute",[]),("EchoSnapshotApi.cleanup",["../outside"])])
def test_fixed_dispatch_and_parameter_rejection(runtime,method,params):
    code,value=request(runtime(),method,params)
    assert code == 400 and value["ok"] is False
    assert "PRIVATE" not in json.dumps(value)


def test_http_boundary_and_safe_errors(runtime):
    base=runtime()
    value=request(runtime("failure"),"EchoMetadata.listFriends")[1]
    assert value == {"ok":False,"error":"qq_runtime_operation_failed"}
    module=importlib.import_module("qq_chat_analyzer.providers.napcat_qq_provider")
    with pytest.raises(module.NapCatQQError) as error:
        provider(runtime("failure")).list_friends()
    assert "PRIVATE" not in str(error.value)


def test_streamed_body_limit_and_http_route(runtime):
    base=runtime()
    parsed=urllib.parse.urlsplit(base)
    connection=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=5)
    connection.request('POST','/rpc',body=iter([b'x'*2000,b'x'*3000]),headers={'Content-Type':'application/json','Authorization':f'Bearer {TOKEN}'},encode_chunked=True)
    response=connection.getresponse()
    assert response.status == 413
    assert json.loads(response.read()) == {'ok':False,'error':'request_too_large'}
    connection.close()
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(urllib.request.Request(base+'/rpc',headers={'Authorization':f'Bearer {TOKEN}'}),timeout=5)
    assert error.value.code == 404
    error.value.close()


def test_single_fetch_and_invalid_response_errors():
    module=importlib.import_module("qq_chat_analyzer.providers.napcat_qq_provider")
    calls=[]
    def transport(url,body,timeout):
        calls.append(json.loads(body))
        if json.loads(body)['method'] == 'Core.status':
            return 200,json.dumps({'ok':True,'result':{'rpc_auth':'bearer-v1',
                'boot_id':'b'*64,
                'bridge_ready':True,'qq_online':True,'self_info':{},
                'database_api_ready':True,'passphrase_ready':True,'snapshot_api_ready':True}})
        return 200,json.dumps({"ok":True,"result":[]})
    client=module.NapCatQQProvider(transport=transport,credential=_Credential())
    assert client.list_friends() == [] and client.list_groups() == []
    assert [c['method'] for c in calls] == ['Core.status','EchoMetadata.listFriends','EchoMetadata.listGroups']
    for body in ['PRIVATE',json.dumps({'ok':False,'error':'PRIVATE'}),json.dumps({'ok':True,'result':{}})]:
        client=module.NapCatQQProvider(transport=lambda *args:(200,body),credential=_Credential())
        with pytest.raises(module.NapCatQQError) as error: client.list_friends()
        assert 'PRIVATE' not in str(error.value)


def test_snapshot_transport_errors_keep_existing_error_family(tmp_path):
    module=importlib.import_module("qq_chat_analyzer.providers.napcat_qq_provider")
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeUnavailable
    def failing(*args): raise module.NapCatQQError()
    client=module.NapCatQQProvider(transport=failing,credential=_Credential()).snapshot_client(tmp_path)
    with pytest.raises(QQSnapshotRuntimeUnavailable): client.acquire()


@pytest.mark.parametrize("url",["http://127.0.0.1.evil.example:40655","http://user:secret@127.0.0.1:40655","http://192.168.1.1:40655","http://127.0.0.1:40655/path"])
def test_provider_rejects_non_loopback_or_ambiguous_urls(url):
    module=importlib.import_module("qq_chat_analyzer.providers.napcat_qq_provider")
    with pytest.raises(module.NapCatQQError):
        module.NapCatQQProvider(url)


def test_bridge_cannot_bind_external_address():
    assert BRIDGE.is_file()
    node=shutil.which("node")
    if not node: pytest.skip("Node unavailable")
    script=f"import {{startBridge}} from {json.dumps(BRIDGE.as_uri())}; try {{ await startBridge({{apis:{{}}}},{{}},{{host:'0.0.0.0',port:0,token:'{TOKEN}'}}); process.exit(1); }} catch {{ process.exit(0); }}"
    result=subprocess.run([node,"--input-type=module","-e",script],capture_output=True,timeout=10)
    assert result.returncode == 0


def test_bridge_refuses_an_absent_or_malformed_credential():
    assert BRIDGE.is_file()
    node=shutil.which("node")
    if not node: pytest.skip("Node unavailable")
    script = (
        f"import {{startBridge}} from {json.dumps(BRIDGE.as_uri())};"
        "const core={apis:{}}; const snapshot={};"
        "for (const token of [undefined, null, '', 'fictional', 'A'.repeat(64), 'f'.repeat(63), 'f'.repeat(65)]) {"
        "  try { await startBridge(core, snapshot, {port:0, token}); process.exit(3); }"
        "  catch (error) { if (error.message !== 'invalid_bridge_credential') throw error; }"
        "} process.exit(0);"
    )
    result=subprocess.run([node,"--input-type=module","-e",script],capture_output=True,timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
