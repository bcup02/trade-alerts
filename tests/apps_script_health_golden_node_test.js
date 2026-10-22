// f-45: the Python publisher (trade_alerts.fleet_health) and the Apps Script receiver agree on one golden put_health_v1 request.
// The request's issued_at is fixed in the past, so freshness is not tested here (apps_script_put_health_node_test.js does that);
// this pins the parts that must match byte for byte across runtimes: canonical JSON, the HMAC and the gzip + base64 payload.
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');
const zlib = require('zlib');

const golden = JSON.parse(fs.readFileSync('tests/golden/health_request.json', 'utf8'));
function bytesFromDigest(algorithm, text, key) {
  const output = key ? crypto.createHmac(algorithm, key).update(text, 'utf8').digest() : crypto.createHash(algorithm).update(text, 'utf8').digest();
  return Array.from(output).map(number => number > 127 ? number - 256 : number);
}
const context = {console, Date, JSON, Math, Object, String, Array, Number, Set, isNaN, isFinite,
  Utilities: {Charset: {UTF_8: 'UTF_8'}, DigestAlgorithm: {SHA_256: 'SHA_256'},
    computeHmacSha256Signature: (text, key) => bytesFromDigest('sha256', text, key),
    computeDigest: (algorithm, text) => bytesFromDigest('sha256', text)}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps_script/google_ledger_receiver.gs', 'utf8'), context, {filename: 'google_ledger_receiver.gs'});

// the receiver's own signature check accepts the Python-signed request, and rejects it with one character changed
assert.equal(context.verifySignature(golden.request, golden.secret), true);
const tampered = JSON.parse(JSON.stringify(golden.request));
tampered.health.generated_at = '2026-10-22T04:00:11Z';
assert.equal(context.verifySignature(tampered, golden.secret), false);
assert.equal(context.verifySignature(golden.request, 'another-secret'), false);

// the payload the receiver would store unpacks to exactly the golden table (gzip + base64, canonical JSON)
const unpacked = JSON.parse(zlib.gunzipSync(Buffer.from(golden.request.health.b64, 'base64')).toString('utf8'));
assert.deepEqual(unpacked, golden.table);
assert.ok(golden.request.health.b64.length <= vm.runInContext('HEALTH_MAX_B64_CHARS', context));
console.log('apps_script_health_golden_node_test ok');
