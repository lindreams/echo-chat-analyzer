import {createServer} from 'node:http';
import {randomBytes, timingSafeEqual} from 'node:crypto';
import {constants as fsConstants, promises as fs} from 'node:fs';
import {isAbsolute} from 'node:path';

const MAX_REQUEST_BYTES = 4096;
const CREDENTIAL = /^[0-9a-f]{64}$/;
const BEARER = 'Bearer ';
const text = value => typeof value === 'string' ? value : '';
const identifier = value => typeof value === 'string' ? value : Number.isSafeInteger(value) ? String(value) : '';
const uin = value => /^[1-9][0-9]{4,19}$/.test(identifier(value)) ? identifier(value) : '';
const object = value => value !== null && typeof value === 'object';
const generation = value => typeof value === 'string' && value.length > 0 && value.length <= 128 &&
  value === value.trim() && value !== '.' && value !== '..' && !/[\\/\x00]/.test(value);
const MAX_PROBE_CALLS = 8;
const PROBE_TIMEOUT_MS = 8000;
const DECIMAL_ID = /^[1-9][0-9]{0,19}$/;
const PEER_UID = /^u_[A-Za-z0-9_-]{10,64}$/;
const MD5 = /^[0-9a-f]{32}$/i;
const FILE_UUID = /^[A-Za-z0-9_.:+=\/-]{1,128}$/;
const PROBE_KEYS = new Set([
  'msgId', 'chatType', 'peerUid', 'expectedTime', 'expectedMd5',
  'expectedFileUuid', 'expectedSegmentId', 'expectedSelf',
]);
const GROUP_PROBE_KEYS = new Set([...PROBE_KEYS, 'expectedSenderUin', 'expectedSenderUid']);
const bounded = (promise, ms, timeoutError = () => new Error('probe_timeout')) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(timeoutError()), ms);
  Promise.resolve(promise).then(
    value => { clearTimeout(timer); resolve(value); },
    error => { clearTimeout(timer); reject(error); },
  );
});
// One fixed read-only request shape. It carries no path, URL, account or
// arbitrary method name, and cannot be widened by callers.
const probeRequest = value => {
  if (!object(value) || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  const allowed = value.chatType === 2 ? GROUP_PROBE_KEYS : PROBE_KEYS;
  if (keys.length !== allowed.size || !keys.every(key => allowed.has(key))) return false;
  if (typeof value.msgId !== 'string' || !DECIMAL_ID.test(value.msgId)) return false;
  if (value.chatType !== 1 && value.chatType !== 2) return false;
  if (typeof value.peerUid !== 'string') return false;
  if (value.chatType === 1 ? !PEER_UID.test(value.peerUid) : !uin(value.peerUid)) return false;
  if (value.chatType === 2 && (
      typeof value.expectedSenderUin !== 'string' || !uin(value.expectedSenderUin) ||
      (value.expectedSenderUid !== null && (typeof value.expectedSenderUid !== 'string' ||
        !PEER_UID.test(value.expectedSenderUid))) ||
      value.expectedFileUuid === null || value.expectedSegmentId === null)) return false;
  if (!Number.isSafeInteger(value.expectedTime) ||
      value.expectedTime < 1 || value.expectedTime > 99999999999) return false;
  if (typeof value.expectedMd5 !== 'string' || !MD5.test(value.expectedMd5)) return false;
  if (value.expectedFileUuid !== null && (
      typeof value.expectedFileUuid !== 'string' ||
      !FILE_UUID.test(value.expectedFileUuid) ||
      value.expectedFileUuid.includes('..') ||
      value.expectedFileUuid.startsWith('/'))) return false;
  if (value.expectedSegmentId !== null &&
      (typeof value.expectedSegmentId !== 'string' || !DECIMAL_ID.test(value.expectedSegmentId))) return false;
  return value.expectedSelf === null || typeof value.expectedSelf === 'boolean';
};

// One bounded media fetch per bridge lifetime window. The transport is a single
// base64 field under the client's 8 MiB response cap, so the file itself is
// capped and never streamed through a second channel.
const MAX_MEDIA_BYTES = 2 * 1024 * 1024;
const MAX_MEDIA_CALLS = 8;
const MEDIA_TIMEOUT_MS = 20000;
// Fixed, sanitised stage codes. Only these may cross the bridge; anything else
// is reported as the generic operation failure so no path or kernel message leaks.
const MEDIA_STAGES = new Set([
  'media_mapping_rejected', 'media_message_query_failed', 'media_api_unavailable',
  'media_busy', 'media_budget_exhausted', 'media_download_timeout',
  'media_download_failed', 'media_path_invalid', 'media_file_missing',
  'media_open_failed', 'media_file_type_rejected', 'media_file_identity_changed',
  'media_file_empty', 'media_file_too_large', 'media_read_incomplete',
  'media_file_changed', 'media_file_rejected',
]);
const mediaError = code => Object.assign(new Error(code), {code});
const MEDIA_KEYS = new Set([...PROBE_KEYS].filter(key => key !== 'expectedSegmentId').concat('elementId'));
const GROUP_MEDIA_KEYS = new Set([...MEDIA_KEYS, 'expectedSenderUin', 'expectedSenderUid']);
// Same fixed request shape as the probe, with the verified element ID in the
// place of the DB segment ID; both identify the same PIC element.
const mediaRequest = value => {
  if (!object(value) || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  const allowed = value.chatType === 2 ? GROUP_MEDIA_KEYS : MEDIA_KEYS;
  if (keys.length !== allowed.size || !keys.every(key => allowed.has(key))) return false;
  if (typeof value.elementId !== 'string' || !DECIMAL_ID.test(value.elementId)) return false;
  return probeRequest({
    msgId: value.msgId, chatType: value.chatType, peerUid: value.peerUid,
    expectedTime: value.expectedTime, expectedMd5: value.expectedMd5,
    expectedFileUuid: value.expectedFileUuid, expectedSegmentId: value.elementId,
    expectedSelf: value.expectedSelf,
    ...(value.chatType === 2 ? {expectedSenderUin: value.expectedSenderUin,
      expectedSenderUid: value.expectedSenderUid} : {}),
  });
};
// NapCat returns a local cache path. Treat it as opaque: absolute, regular,
// stable and bounded. The path never leaves this process.
//
// The opened handle is the single source of truth for the bytes returned. The
// path lookup is only used to reject links/special files and to prove the path
// still names the file that was opened; its size is never compared with the
// handle size, because QQ can still be finishing the write it just reported.
// Stability is proven around the read on that same handle instead.
const readBoundedMedia = async filePath => {
  if (typeof filePath !== 'string' || filePath.length === 0 || filePath.length > 4096 ||
      filePath.includes('\x00') || !isAbsolute(filePath)) throw mediaError('media_path_invalid');
  const openFailed = error => mediaError(error?.code === 'ENOENT' ? 'media_file_missing' : 'media_open_failed');
  let before;
  try {
    before = await fs.lstat(filePath, {bigint: true});
  } catch (error) {
    throw openFailed(error);
  }
  if (!before.isFile()) throw mediaError('media_file_type_rejected');
  let handle;
  try {
    handle = await fs.open(filePath, fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW ?? 0));
  } catch (error) {
    throw openFailed(error);
  }
  try {
    let opened;
    try {
      opened = await handle.stat({bigint: true});
    } catch (error) {
      throw openFailed(error);
    }
    if (!opened.isFile()) throw mediaError('media_file_type_rejected');
    // Windows Node versions can report different dev values for lstat/fstat.
    // Keep exact, nonzero file IDs across APIs, and compare dev only within
    // the same API on Windows. Other platforms also require cross-API dev.
    if (before.ino <= 0n || opened.ino !== before.ino ||
        (process.platform !== 'win32' && opened.dev !== before.dev)) {
      throw mediaError('media_file_identity_changed');
    }
    const checkPath = async () => {
      const named = await fs.lstat(filePath, {bigint: true});
      if (!named.isFile()) throw mediaError('media_file_type_rejected');
      if (named.ino !== before.ino || named.dev !== before.dev) {
        throw mediaError('media_file_identity_changed');
      }
    };
    await checkPath();
    if (opened.size <= 0n) throw mediaError('media_file_empty');
    if (opened.size > BigInt(MAX_MEDIA_BYTES)) throw mediaError('media_file_too_large');
    const raw = Buffer.alloc(Number(opened.size));
    let offset = 0;
    while (offset < raw.length) {
      const {bytesRead} = await handle.read(raw, offset, raw.length - offset, offset);
      if (bytesRead <= 0) throw mediaError('media_read_incomplete');
      offset += bytesRead;
    }
    const tail = Buffer.alloc(1);
    if ((await handle.read(tail, 0, 1, offset)).bytesRead !== 0) throw mediaError('media_file_changed');
    await checkPath();
    const after = await handle.stat({bigint: true});
    if (!after.isFile() || after.ino !== opened.ino || after.dev !== opened.dev ||
        after.size !== opened.size || after.mtimeNs !== opened.mtimeNs ||
        after.ctimeNs !== opened.ctimeNs) throw mediaError('media_file_changed');
    return raw;
  } catch (error) {
    throw MEDIA_STAGES.has(error?.code) ? error : mediaError('media_file_rejected');
  } finally {
    await handle.close();
  }
};

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
  // One shared read-only locator for the diagnostic probe and the media fetch.
  // It fetches exactly the requested message and returns only the fields each
  // caller may use; the caller never supplies an element independently.
  const inspectPicMessage = async value => {
    const msgApi = core.apis?.MsgApi;
    if (!msgApi || typeof msgApi.getMsgsByMsgId !== 'function') throw new Error('probe_api_unavailable');
    const peer = {guildId: '', chatType: value.chatType, peerUid: value.peerUid};
    const response = await bounded(msgApi.getMsgsByMsgId(peer, [value.msgId]), PROBE_TIMEOUT_MS);
    const messages = Array.isArray(response?.msgList) ? response.msgList : [];
    const empty = {
      found: messages.length > 0, unique: false, msg_id_matches: false,
      time_matches: false, peer_matches: false, sender_matches: null,
      pic_element_count: 0, matched_pic_count: 0, segment_id_matches: null,
      file_uuid_matches: null, md5_matches: false, match_basis: 'none', element: null,
    };
    if (messages.length !== 1) return empty;
    const message = messages[0];
    const msgIdMatches = text(message?.msgId) === value.msgId;
    const timeMatches = String(message?.msgTime ?? '') === String(value.expectedTime);
    const peerMatches = text(message?.peerUid) === value.peerUid &&
      (value.chatType !== 2 || (message.chatType === 2 &&
        (message.peerUin === undefined || message.peerUin === '' || text(message.peerUin) === value.peerUid)));
    const senderUid = text(message?.senderUid);
    let senderMatches = null;
    if (value.chatType === 2) {
      senderMatches = text(message.senderUin) === value.expectedSenderUin &&
        (value.expectedSenderUid === null || senderUid === value.expectedSenderUid);
      if (typeof value.expectedSelf === 'boolean') {
        const selfUin = uin(core.selfInfo?.uin);
        senderMatches = senderMatches && selfUin !== '' &&
          ((value.expectedSenderUin === selfUin) === value.expectedSelf);
        const selfUid = text(core.selfInfo?.uid);
        if (selfUid !== '') senderMatches = senderMatches && ((senderUid === selfUid) === value.expectedSelf);
      }
    } else if (typeof value.expectedSelf === 'boolean') {
      senderMatches = value.expectedSelf
        ? (text(core.selfInfo?.uid) !== '' && senderUid === text(core.selfInfo?.uid))
        : senderUid === value.peerUid;
    }
    const elements = Array.isArray(message?.elements) ? message.elements : [];
    const pics = elements.filter(element => object(element) && object(element.picElement) &&
      (value.chatType !== 2 || element.elementType === 2));
    const expectedMd5 = value.expectedMd5.toLowerCase();
    const candidates = pics.filter(element => {
      const pic = element.picElement;
      if (text(pic.md5HexStr).toLowerCase() !== expectedMd5) return false;
      return value.expectedFileUuid === null || text(pic.fileUuid) === value.expectedFileUuid;
    });
    const matched = candidates.length === 1 ? candidates[0] : null;
    const segmentId = value.expectedSegmentId ?? value.elementId ?? null;
    const segmentIdMatches = matched !== null && segmentId !== null
      ? text(matched.elementId) === segmentId : null;
    const fileUuidMatches = matched !== null && value.expectedFileUuid !== null
      ? text(matched.picElement?.fileUuid) === value.expectedFileUuid : null;
    const md5Matches = matched !== null &&
      text(matched.picElement?.md5HexStr).toLowerCase() === expectedMd5;
    const bases = [];
    if (segmentIdMatches === true) bases.push('segment_id');
    if (fileUuidMatches === true) bases.push('file_uuid');
    if (md5Matches) bases.push('md5');
    return {
      found: true, unique: true, msg_id_matches: msgIdMatches,
      time_matches: timeMatches, peer_matches: peerMatches,
      sender_matches: senderMatches, pic_element_count: pics.length,
      matched_pic_count: candidates.length, segment_id_matches: segmentIdMatches,
      file_uuid_matches: fileUuidMatches, md5_matches: md5Matches,
      match_basis: bases.length ? bases.join('+') : 'none', element: matched,
    };
  };
  let probeCalls = 0;
  const probePicMessage = async value => {
    if (probeCalls >= MAX_PROBE_CALLS) throw new Error('probe_budget_exhausted');
    probeCalls += 1;
    const {element, ...facts} = await inspectPicMessage(value);
    // Recompute the verdict instead of trusting the caller or a label.
    const passed = facts.unique && facts.msg_id_matches && facts.time_matches &&
      facts.peer_matches && facts.sender_matches !== false &&
      facts.matched_pic_count === 1 && facts.md5_matches &&
      (value.chatType !== 2 || (facts.sender_matches === true &&
        facts.segment_id_matches === true && facts.file_uuid_matches === true));
    return {...facts, passed};
  };
  let mediaCalls = 0;
  let mediaBusy = false;
  // The only media read path. It re-locates the same message and the one PIC
  // element matching the recorded element ID, digest and file UUID, then asks
  // QQ for that element only. Bytes leave bounded; the local path never does.
  const downloadPicMedia = async value => {
    if (mediaBusy) throw mediaError('media_busy');
    if (mediaCalls >= MAX_MEDIA_CALLS) throw mediaError('media_budget_exhausted');
    mediaBusy = true;
    try {
      mediaCalls += 1;
      let facts;
      try {
        facts = await inspectPicMessage(value);
      } catch (error) {
        throw MEDIA_STAGES.has(error?.code) ? error : mediaError('media_message_query_failed');
      }
      const element = facts.element;
      if (!facts.found || !facts.unique || !facts.msg_id_matches || !facts.time_matches ||
          !facts.peer_matches || facts.sender_matches === false ||
          facts.matched_pic_count !== 1 || !facts.md5_matches ||
          (value.chatType === 2 && (facts.sender_matches !== true ||
            facts.segment_id_matches !== true || facts.file_uuid_matches !== true)) ||
          element === null || text(element.elementId) !== value.elementId) {
        throw mediaError('media_mapping_rejected');
      }
      const fileApi = core.apis?.FileApi;
      if (!fileApi || typeof fileApi.downloadMedia !== 'function') throw mediaError('media_api_unavailable');
      let localPath;
      try {
        localPath = await bounded(
          fileApi.downloadMedia(value.msgId, value.chatType, value.peerUid, value.elementId,
            '', '', MEDIA_TIMEOUT_MS, false),
          MEDIA_TIMEOUT_MS, () => mediaError('media_download_timeout'));
      } catch (error) {
        throw MEDIA_STAGES.has(error?.code) ? error : mediaError('media_download_failed');
      }
      const raw = await readBoundedMedia(localPath);
      return {size: raw.length, base64: raw.toString('base64')};
    } finally {
      mediaBusy = false;
    }
  };
  const methods = new Map([
    ['Core.status', {count: 0, call: status}],
    ['EchoMetadata.listFriends', {count: 0, call: friends}],
    ['EchoMetadata.listGroups', {count: 0, call: groups}],
    ['GroupApi.getGroupMemberAll', {count: 1, valid: value => !!uin(value) && typeof value === 'string', call: members}],
    ['EchoMediaProbe.resolvePicMessage', {count: 1, valid: probeRequest, call: probePicMessage}],
    ['EchoMediaProbe.downloadPicMedia', {count: 1, valid: mediaRequest, call: downloadPicMedia}],
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
      catch (error) {
        // Media stages are a fixed whitelist; every other failure stays generic.
        send(200, {ok: false, error: MEDIA_STAGES.has(error?.code) ? error.code : 'qq_runtime_operation_failed'});
      }
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
