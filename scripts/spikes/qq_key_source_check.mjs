// Fiction only: sources are in-memory objects owned by this one process.
import assert from 'node:assert/strict';
import {randomBytes, pbkdf2Sync} from 'node:crypto';
import {encode} from './qq_independent_codec.mjs';
import {PROFILE, KeySourceError, withAuthenticatedKey} from './qq_key_source.mjs';

const password = randomBytes(24), salt = randomBytes(16);
const key = pbkdf2Sync(password, salt, 4000, 32, 'sha512');
const plain = Buffer.alloc(4096);
plain.write('SQLite format 3\0'); plain.writeUInt16BE(4096, 16); plain[20] = 48;
const firstPage = encode(plain, key, salt);
const request = {version: '9.9.37-54395', sessionGeneration: 'fictional-session-1', profile: PROFILE, firstPage};
const checks = [];
function fixture({kind = 'raw', secret = key, bind = b => b, current = () => true,
  acquire = () => {}, close = () => true} = {}) {
  const material = Buffer.from(secret);
  return {material, acquired: 0, closed: 0,
    acquire(binding, control) {
      this.acquired++;
      acquire(control);
      return {kind, material, binding: bind(binding), isCurrent: current};
    },
    close() { this.closed++; material.fill(0); return close(); },
  };
}
function rejected(code, source, action = () => withAuthenticatedKey(source, request,
  () => { assert.fail('unverified key reached consumer'); })) {
  assert.throws(action, error => error instanceof KeySourceError && error.code === code);
  if (source) {
    assert.equal(source.closed, 1);
    assert.ok(source.material.every(b => b === 0));
  }
}
try {
  rejected('trusted_source_unavailable', null);
  checks.push('missing_source_fails_closed');
  for (const [kind, secret] of [['raw', key], ['passphrase', password]]) {
    const source = fixture({kind, secret});
    let borrowed, consumed = 0;
    const result = withAuthenticatedKey(source, request, raw => {
      assert.ok(raw.equals(key)); borrowed = raw; consumed++;
      // Reentry cannot close/displace the current owner.
      assert.throws(() => withAuthenticatedKey(source, request),
        error => error.code === 'source_already_used');
      assert.equal(source.closed, 0);
    });
    assert.deepEqual(result, {state: 'authenticated', scope: 'first_page_only', source_released: true});
    assert.equal(consumed, 1); assert.equal(source.closed, 1);
    assert.ok(source.material.every(b => b === 0) && borrowed.every(b => b === 0));
    assert.throws(() => withAuthenticatedKey(source, request), error => error.code === 'source_already_used');
  }
  checks.push('typed_source_authentication_scoped_consumption_and_release');
  rejected('key_not_authenticated', fixture({secret: randomBytes(32)}));
  for (const field of ['version', 'sessionGeneration', 'profile', 'databaseFingerprint']) {
    rejected('source_binding_mismatch', fixture({bind: b => ({...b, [field]: 'different'})}));
  }
  checks.push('wrong_key_and_wrong_binding_never_consumed');
  rejected('source_expired', fixture({current: () => false}));
  let observations = 0;
  rejected('source_expired', fixture({current: () => ++observations === 1}));
  checks.push('expired_or_rotated_source_released');
  const controller = new AbortController();
  const cancelled = fixture({acquire: () => controller.abort()});
  rejected('cancelled', cancelled, () => withAuthenticatedKey(cancelled, request, undefined, {signal: controller.signal}));
  let tick = 0;
  const timed = fixture({acquire: () => { tick = 2; }});
  rejected('deadline_reached', timed, () => withAuthenticatedKey(timed, request, undefined, {now: () => tick, deadline: 1}));
  checks.push('cancel_and_deadline_release_acquired_material');
  rejected('key_source_failed', fixture({acquire: () => { throw Error('private fixture detail'); }}));
  const failedConsumer = fixture();
  rejected('key_source_failed', failedConsumer, () => withAuthenticatedKey(failedConsumer, request,
    () => { throw Error('private fixture detail'); }));
  rejected('source_cleanup_failed', fixture({close: () => false}));
  checks.push('partial_acquisition_consumer_failure_and_cleanup_failure');
  console.log(JSON.stringify({checks, real_qq_accessed: false, key_material_persisted: false,
    qq_54395_key_acquisition: 'not_implemented'}, null, 2));
} finally {
  password.fill(0); key.fill(0); salt.fill(0); firstPage.fill(0); plain.fill(0);
}
