import {createServer} from 'node:http';
import {randomBytes, timingSafeEqual} from 'node:crypto';

const MAX_REQUEST_BYTES = 4096;
const CREDENTIAL = /^[0-9a-f]{64}$/;
const BEARER = 'Bearer ';
const text = value => typeof value === 'string' ? value : '';
const identifier = value => typeof value === 'string' ? value : Number.isSafeInteger(value) ? String(value) : '';
const uin = value => /^[1-9][0-9]{4,19}$/.test(identifier(value)) ? identifier(value) : '';
const object = value => value !== null && typeof value === 'object';
const generation = value => typeof value === 'string' && value.length > 0 && value.length <= 128 &&
  value === value.trim() && value !== '.' && value !== '..' && !/[\\/\x00]/.test(value);

export async function startBridge(core, snapshot, {port = 40655, host = '127.0.0.1', runtimeId = null, token = null} = {}) {
  if (host !== '127.0.0.1' || !Number.isInteger(port) || port < 0 || port > 65535) throw new Error('invalid_bridge_address');
  if (!core?.apis) throw new Error('echo_core_unavailable');
  if (runtimeId !== null && (typeof runtimeId !== 'string' || !/^[0-9a-f]{64}$/.test(runtimeId))) {
    throw new Error('invalid_runtime_identity');
  }
  // Every RPC method requires the client credential Echo minted for this launch.
  // A bridge without a usable credential is never started: there is no mode in
  // which this server answers an unauthenticated call.
  if (typeof token !== 'string' || !CREDENTIAL.test(token)) throw new Error('invalid_bridge_credential');
  // Mint inside the actual bridge lifecycle, never in the parent environment:
  // a restarted Worker (or a reloaded bridge) cannot inherit the old generation.
  const bootId = randomBytes(32).toString('hex');
  const expected = Buffer.from(token, 'utf8');
  const authorized = req => {
    const header = req.headers.authorization;
    if (typeof header !== 'string' || !header.startsWith(BEARER)) return false;
    const presented = Buffer.from(header.slice(BEARER.length), 'utf8');
    return presented.length === expected.length && timingSafeEqual(presented, expected);
  };
  const status = () => ({
    rpc_auth: 'bearer-v1',
    boot_id: bootId,
    bridge_ready: true,
    qq_online: core.selfInfo?.online === true,
    self_info: {uin: uin(core.selfInfo?.uin), uid: text(core.selfInfo?.uid), nickname: text(core.selfInfo?.nick)},
    database_api_ready: typeof core.apis.DatabaseApi?.decryptDatabase === 'function',
    passphrase_ready: core.apis.DatabaseApi?.hasPassphrase?.() === true,
    snapshot_api_ready: ['acquire', 'cleanup', 'recover'].every(name => typeof snapshot?.[name] === 'function'),
    ...(runtimeId === null ? {} : {runtime_id: runtimeId})
  });
  const friends = async () => {
    const categories = await core.apis.FriendApi.getBuddyV2ExWithCate();
    if (!Array.isArray(categories)) throw new Error('invalid_metadata');
    return categories.flatMap(category => Array.isArray(category?.buddyList) ? category.buddyList : [])
      .filter(object).map(row => ({uin: uin(row.coreInfo?.uin) || uin(row.uin), uid: text(row.coreInfo?.uid) || text(row.uid),
        nickname: text(row.coreInfo?.nick) || text(row.nick), remark: text(row.coreInfo?.remark) || text(row.remark)}))
      .filter(row => row.uin || row.uid);
  };
  const groups = async () => {
    const rows = await core.apis.GroupApi.getGroups();
    if (!Array.isArray(rows)) throw new Error('invalid_metadata');
    return rows.filter(object).map(row => ({group_code: uin(row.groupCode), group_name: text(row.groupName),
      member_count: Number.isSafeInteger(row.memberCount) && row.memberCount >= 0 ? row.memberCount : null}))
      .filter(row => row.group_code);
  };
  const members = async group => {
    const result = await core.apis.GroupApi.getGroupMemberAll(group);
    const source = result?.result?.infos;
    if (!object(source)) throw new Error('invalid_metadata');
    const entries = source instanceof Map ? [...source.entries()] : Object.entries(source);
    // Preserve Map keys (UID) separately from UIN; only name-enrichment fields leave NapCat.
    const infos = Object.fromEntries(entries.filter(([, row]) => object(row)).map(([key, row]) => [text(key), {
      uid: text(row.uid) || text(key), uin: uin(row.uin), nick: text(row.nick), cardName: text(row.cardName)
    }]));
    return {result: {infos}};
  };
  const methods = new Map([
    ['Core.status', {count: 0, call: status}],
    ['EchoMetadata.listFriends', {count: 0, call: friends}],
    ['EchoMetadata.listGroups', {count: 0, call: groups}],
    ['GroupApi.getGroupMemberAll', {count: 1, valid: value => !!uin(value) && typeof value === 'string', call: members}],
    ['EchoSnapshotApi.acquire', {count: 0, call: () => snapshot.acquire()}],
    ['EchoSnapshotApi.cleanup', {count: 1, valid: generation, call: id => snapshot.cleanup(id)}],
    ['EchoSnapshotApi.recover', {count: 0, call: () => snapshot.recover()}]
  ]);
  const server = createServer((req, res) => {
    const send = (code, value) => {
      if (!res.writableEnded && !res.destroyed) res.writeHead(code, {'content-type': 'application/json', 'cache-control': 'no-store'}).end(JSON.stringify(value));
    };
    const failure = (code, error) => {
      const refused = () => send(code, {ok: false, error});
      const bytes = Number(req.headers['content-length'] ?? '0');
      // Reject before routing, but drain a bounded ordinary request before
      // closing its connection. Otherwise a separately arriving body can turn
      // the 401 into a Windows connection reset instead of an auth rejection.
      req.on('error', () => {});
      if (!req.complete && !req.headers['transfer-encoding'] &&
          Number.isSafeInteger(bytes) && bytes >= 0 && bytes <= MAX_REQUEST_BYTES) {
        req.once('end', refused);
      } else refused();
      req.resume();
    };
    const boundPort = server.address().port;
    if (req.headers.origin || ![`127.0.0.1:${boundPort}`, `localhost:${boundPort}`].includes(req.headers.host)) return failure(403, 'invalid_origin');
    // Authenticate before any routing detail is decided, so an unauthenticated
    // caller learns nothing about which routes or methods exist, and no method
    // is ever reached without a credential.
    if (!authorized(req)) return failure(401, 'invalid_credential');
    const boundRoute = runtimeId !== null && req.url === `/rpc/${runtimeId}`;
    if (req.method !== 'POST' || (req.url !== '/rpc' && !boundRoute)) return failure(404, 'invalid_route');
    if (req.headers['content-type']?.split(';')[0].trim() !== 'application/json') return failure(415, 'invalid_content_type');
    if (Number(req.headers['content-length']) > MAX_REQUEST_BYTES) return failure(413, 'request_too_large');
    let size = 0;
    const chunks = [];
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_REQUEST_BYTES) { chunks.length = 0; send(413, {ok: false, error: 'request_too_large'}); }
      else chunks.push(chunk);
    });
    req.on('error', () => send(400, {ok: false, error: 'invalid_request'}));
    req.on('end', async () => {
      if (res.writableEnded) return;
      let body;
      try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
      catch { return send(400, {ok: false, error: 'invalid_request'}); }
      if (!object(body) || Array.isArray(body) || typeof body.method !== 'string') return send(400, {ok: false, error: 'invalid_request'});
      // Every bound managed call checks workspace identity first. Only initial
      // authenticated status discovery can use the unbound route.
      const discovery = body.method === 'Core.status' && !Object.hasOwn(body, 'boot_id');
      if (runtimeId !== null && !discovery && !boundRoute) {
        return send(409, {ok: false, error: 'runtime_identity_mismatch'});
      }
      // Only the initial authenticated status discovery may omit boot_id.
      // Bound status polling and every operation are guarded before touching core.
      if ((body.method !== 'Core.status' || Object.hasOwn(body, 'boot_id')) &&
          (typeof body.boot_id !== 'string' || !CREDENTIAL.test(body.boot_id) || body.boot_id !== bootId)) {
        return send(409, {ok: false, error: 'worker_generation_mismatch'});
      }
      const method = methods.get(body.method);
      if (!method) return send(400, {ok: false, error: 'invalid_method'});
      const params = Object.hasOwn(body, 'params') ? body.params : [];
      if (!Array.isArray(params) || params.length !== method.count || (method.valid && !method.valid(params[0]))) return send(400, {ok: false, error: 'invalid_params'});
      const acquireBudget = body.timeout_ms ?? 65000;
      const acquiring = body.method === 'EchoSnapshotApi.acquire';
      if (acquiring && (!Number.isInteger(acquireBudget) || acquireBudget < 1 || acquireBudget > 65000)) {
        return send(400, {ok: false, error: 'invalid_params'});
      }
      const acquireDeadline = acquiring ? performance.now() + acquireBudget : 0;
      let result, cleanupStarted = false;
      const cleanupAbandoned = async () => {
        if (cleanupStarted || result?.ok !== true || result.status !== 'ready' || !generation(result.generation_id)) return;
        cleanupStarted = true;
        try {
          const cleaned = await snapshot.cleanup(result.generation_id);
          if (cleaned?.ok !== true && cleaned?.code !== 'generation_not_found') throw new Error();
        } catch {
          // Keep snapshot ownership/recovery fail-closed; never log payloads.
          console.error('[echo-snapshot] stage=abandoned_acquire_cleanup outcome=failed');
        }
      };
      if (acquiring) {
        res.once('close', () => { if (!res.writableFinished) void cleanupAbandoned(); });
      }
      try {
        result = await method.call(...params);
        if (acquiring && (res.destroyed || performance.now() >= acquireDeadline)) {
          await cleanupAbandoned();
          send(200, {ok: false, error: 'qq_runtime_operation_failed'});
          return;
        }
        send(200, {ok: true, result});
      }
      catch { send(200, {ok: false, error: 'qq_runtime_operation_failed'}); }
    });
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 10000;
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, host, resolve); });
  return {port: server.address().port, async stop() {
    await new Promise((resolve, reject) => {
      server.close(error => error ? reject(error) : resolve());
      server.closeAllConnections();
    });
  }};
}
