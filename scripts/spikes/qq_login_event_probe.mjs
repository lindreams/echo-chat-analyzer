// Research only: consume ONE already-delivered MSF response. No hooking,
// process discovery, packet capture, persistence or real QQ transport.
import {isUtf8} from 'node:buffer';
import {withAuthenticatedKey, KeySourceError} from './qq_key_source.mjs';

export const COMMAND = 'OidbSvcTrpcTcp.0xcde_2';
export const MAX_EVENT_BYTES = 8192;
const reject = code => { throw new KeySourceError(code); };

// Narrow protobuf wire reader, independently implemented from the public wire
// format. Only the supplied field schema is retained; no message/text decoder.
function fields(bytes, schema) {
  let at = 0, count = 0;
  const values = new Map();
  const integer = () => {
    let value = 0n;
    for (let n = 0; n < 10 && at < bytes.length; n++) {
      const octet = bytes[at++];
      if (n === 9 && octet > 1) reject('invalid_event_wire');
      value |= BigInt(octet & 127) << BigInt(n * 7);
      if (!(octet & 128)) return value;
    }
    reject('invalid_event_wire');
  };
  while (at < bytes.length) {
    if (++count > 64) reject('event_field_limit');
    const tag = integer();
    if (!tag || tag > 0xffffffffn || tag >> 3n === 0n) reject('invalid_event_wire');
    const number = Number(tag >> 3n), wire = Number(tag & 7n);
    let value;
    if (wire === 0) value = integer();
    else if (wire === 1 || wire === 5) {
      const end = at + (wire === 1 ? 8 : 4);
      if (end > bytes.length) reject('invalid_event_wire');
      value = bytes.subarray(at, end); at = end;
    } else if (wire === 2) {
      const length = integer();
      if (length > BigInt(bytes.length - at)) reject('invalid_event_wire');
      value = bytes.subarray(at, at + Number(length)); at += Number(length);
    } else reject('invalid_event_wire'); // No groups or format guessing.
    if (Object.hasOwn(schema, number)) {
      if (wire !== schema[number] || values.has(number)) reject('ambiguous_event_field');
      values.set(number, value);
    }
  }
  return values;
}

/** The caller must bind the transport to an owned, approved process/session.
 * A command name, version string or matching MAC does not attest provenance.
 * Non-target traffic is rejected before accessing its payload.
 * Result scope is one encrypted main page; no decrypted SQLite/messages.
 */
export function observeCdeResponse(event, request, control, consume) {
  if (event.command !== COMMAND || event.direction !== 'receive') return {state: 'ignored'};
  let material;
  try {
    if (event.error !== 0 || event.truncated !== false) reject('incomplete_event');
    if (!Buffer.isBuffer(event.payload) || event.payload.length > MAX_EVENT_BYTES ||
        event.originalLength !== event.payload.length) reject('event_size_refused');
    const envelope = fields(event.payload, {1: 0, 2: 0, 3: 0, 4: 2});
    if (envelope.get(1) !== 0xcden || envelope.get(2) !== 2n ||
        (envelope.get(3) ?? 0n) !== 0n || !envelope.has(4)) reject('unexpected_response');
    const body = fields(envelope.get(4), {2: 2});
    if (!body.has(2)) reject('passphrase_event_missing');
    const inner = fields(body.get(2), {1: 2});
    const value = inner.get(1);
    if (!value?.length || value.length > 4096 || !isUtf8(value)) reject('invalid_passphrase_event');
    material = Buffer.from(value);
    // Reuse last round's contract, without a new provider abstraction. This
    // event's transport binding is established by the caller, not by echoing
    // request metadata here. Only this one material is ever authenticated.
    const result = withAuthenticatedKey({
      acquire(binding) {
        return {kind: 'passphrase', material, binding, isCurrent: () => !control?.signal?.aborted};
      },
      close() { material.fill(0); return true; },
    }, request, consume, control);
    return {state: 'authenticated_event', authentication_scope: result.scope};
  } finally {
    material?.fill(0);
    if (Buffer.isBuffer(event.payload)) event.payload.fill(0); // Ownership transfers even on refusal.
  }
}
