// f-45: put_health_v1 -- the A1 publisher writes the health table into ONE cell of its own tab.
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');

const healthSecret = 'health-test-secret';
const ledgerSecret = 'ledger-test-secret';
const healthSource = {hmac_secret: healthSecret, project_id: 'fleet-health', sheet_name: '維運健康', allowed_actions: ['put_health_v1']};
const ledgerSource = {hmac_secret: ledgerSecret, project_id: 'mexc-4h-momentum', sheet_name: 'trading-tab'};   // registered before put_health_v1: no allowed_actions
const misplacedHealthSource = {hmac_secret: 'misplaced-secret', project_id: 'fleet-health', sheet_name: 'trading-tab', allowed_actions: ['put_health_v1']};
const missingTabSource = {hmac_secret: 'missing-secret', project_id: 'fleet-health', sheet_name: '維運健康-不存在', allowed_actions: ['put_health_v1']};
const brokenSource = allowed => ({hmac_secret: 'broken-secret', project_id: 'fleet-health', sheet_name: '維運健康', allowed_actions: allowed});
const bothSource = {hmac_secret: 'both-secret', project_id: 'fleet-health', sheet_name: '維運健康', allowed_actions: ['put_health_v1', 'read_reconciliation_v2']};
const sources = {'health-a1': healthSource, 'ledger-a1': ledgerSource, 'misplaced': misplacedHealthSource, 'missing-tab': missingTabSource,
  'broken-empty': brokenSource([]), 'broken-string': brokenSource('put_health_v1'), 'broken-null': brokenSource(null),
  'broken-object': brokenSource({put_health_v1: true}), 'broken-number': brokenSource(1), 'both': bothSource};
const sheets = new Map();
const calls = [];

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
}
function bytesFromDigest(algorithm, text, key) {
  const output = key ? crypto.createHmac(algorithm, key).update(text, 'utf8').digest() : crypto.createHash(algorithm).update(text, 'utf8').digest();
  return Array.from(output).map(number => number > 127 ? number - 256 : number);
}
function createSheet(name, rows) {
  const sheet = {name, rows, getLastRow() { return this.rows.length; },
    getRange(row, column) {
      const target = this;
      return {
        setNumberFormat(format) { calls.push({sheet: name, op: 'setNumberFormat', row, column, format}); },
        setValue(value) {
          calls.push({sheet: name, op: 'setValue', row, column});
          while (target.rows.length < row) target.rows.push([]);
          while (target.rows[row - 1].length < column) target.rows[row - 1].push('');
          target.rows[row - 1][column - 1] = value;
        },
        getValues() { return [[(target.rows[row - 1] || [])[column - 1] || '']]; },
      };
    },
    appendRow(values) { calls.push({sheet: name, op: 'appendRow'}); this.rows.push(values); }};
  sheets.set(name, sheet);
  return sheet;
}
const healthTab = createSheet('維運健康', [['']]);
const tradingTab = createSheet('trading-tab', [['trade_id', 'symbol'], ['t-1', 'BTCUSDT']]);

const context = {console, Date, JSON, Math, Object, String, Array, Number, Set, isNaN, isFinite,
  PropertiesService: {getScriptProperties: () => ({getProperty: key => key === 'GOOGLE_LEDGER_V2_SOURCES' ? JSON.stringify(sources) : null})},
  Utilities: {Charset: {UTF_8: 'UTF_8'}, DigestAlgorithm: {SHA_256: 'SHA_256'},
    computeHmacSha256Signature: (text, key) => bytesFromDigest('sha256', text, key),
    computeDigest: (algorithm, text) => bytesFromDigest('sha256', text)},
  SpreadsheetApp: {getActiveSpreadsheet: () => ({getSheetByName: name => sheets.get(name) || null, insertSheet: name => { calls.push({op: 'insertSheet', name}); return createSheet(name, []); }})},
  ContentService: {MimeType: {JSON: 'application/json'}, createTextOutput: text => ({text, setMimeType() { return this; }})}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps_script/google_ledger_receiver.gs', 'utf8'), context, {filename: 'google_ledger_receiver.gs'});

const route = payload => JSON.parse(JSON.stringify(context.routeRequest(payload)));
let seq = 0;
const nextId = () => `00000000-0000-4000-8000-${String(++seq).padStart(12, '0')}`;

function signed(body, secret) {
  return {...body, signature: crypto.createHmac('sha256', secret).update(canonicalJson(body), 'utf8').digest('hex')};
}
function healthRequest({sourceId = 'health-a1', secret = healthSecret, project = 'fleet-health', sheet = '維運健康', action = 'put_health_v1',
                        b64 = 'H4sIAAAAAAAAA6tWSs5IzcnJV6oFAEvJF0kPAAAA', generatedAt = new Date().toISOString(), issuedAt = new Date().toISOString(), health} = {}) {
  return signed({schema_version: 'google-ledger-projection-v2', action, source_id: sourceId, project_id: project, sheet_name: sheet,
    request_id: nextId(), issued_at: issuedAt, health: health === undefined ? {b64, generated_at: generatedAt} : health}, secret);
}
function untouched() {
  assert.deepEqual(tradingTab.rows, [['trade_id', 'symbol'], ['t-1', 'BTCUSDT']]);
  assert.equal(calls.filter(c => c.op === 'appendRow' || c.op === 'insertSheet').length, 0);
}

// a good write: A1 of the health tab only, text format first, the fixed marker shape, nothing else touched
const good = route(healthRequest());
assert.equal(good.ok, true);
assert.equal(good.cell_chars, 'HEALTHv1|H4sIAAAAAAAAA6tWSs5IzcnJV6oFAEvJF0kPAAAA|HEALTHEND'.length);
assert.equal(healthTab.rows[0][0], 'HEALTHv1|H4sIAAAAAAAAA6tWSs5IzcnJV6oFAEvJF0kPAAAA|HEALTHEND');
assert.deepEqual(calls.map(c => [c.sheet, c.op, c.row, c.column]), [['維運健康', 'setNumberFormat', 1, 1], ['維運健康', 'setValue', 1, 1]]);
assert.equal(calls[0].format, '@');
assert.equal(healthTab.rows.length, 1);
untouched();

// the next run overwrites the same cell (one latest table, not a log)
assert.equal(route(healthRequest({b64: 'AAAA'})).ok, true);
assert.equal(healthTab.rows[0][0], 'HEALTHv1|AAAA|HEALTHEND');
assert.equal(healthTab.rows.length, 1);

// the size cap: exactly the cap is written, one more character is refused and the previous table stays
const cap = vm.runInContext('HEALTH_MAX_B64_CHARS', context);     // top-level const: not a property of the context object
assert.equal(cap, 9000);
const atCap = 'A'.repeat(cap);
assert.equal(route(healthRequest({b64: atCap})).ok, true);
assert.equal(healthTab.rows[0][0].length, 'HEALTHv1|'.length + 9000 + '|HEALTHEND'.length);
assert.deepEqual(route(healthRequest({b64: atCap + 'A'})), {ok: false, error: 'health_too_large'});
assert.equal(healthTab.rows[0][0].length, 'HEALTHv1|'.length + 9000 + '|HEALTHEND'.length);

// payload shape: base64 characters only, exactly the two members, a recent generated_at
const before = healthTab.rows[0][0];
for (const bad of [
  {b64: ''}, {b64: 'has space'}, {b64: 'pipe|inside'}, {b64: 'new\nline'}, {b64: 'AAAA=A'}, {b64: 123},
  {generatedAt: 'not a date'}, {generatedAt: new Date(Date.now() - 3600 * 1000).toISOString()},
  {health: null}, {health: []}, {health: {b64: 'AAAA'}}, {health: {generated_at: new Date().toISOString()}},
  {health: {b64: 'AAAA', generated_at: new Date().toISOString(), extra: 'x'}},
]) {
  assert.deepEqual(route(healthRequest(bad)), {ok: false, error: 'health_payload_invalid'}, JSON.stringify(bad));
}
assert.equal(healthTab.rows[0][0], before);

// authentication: the same gates as every v2 action
const wrongSecret = healthRequest({secret: 'not-the-secret'});
assert.deepEqual(route(wrongSecret), {ok: false, error: 'signature_invalid'});
assert.deepEqual(route(healthRequest({issuedAt: new Date(Date.now() - 3600 * 1000).toISOString()})), {ok: false, error: 'request_not_fresh'});
assert.deepEqual(route(healthRequest({project: 'mexc-4h-momentum'})), {ok: false, error: 'source_not_allowed'});
assert.deepEqual(route(healthRequest({sheet: 'trading-tab'})), {ok: false, error: 'source_not_allowed'});
assert.deepEqual(route(healthRequest({sourceId: 'unknown-source'})), {ok: false, error: 'source_not_allowed'});
const tampered = healthRequest();
tampered.health.b64 = 'BBBB';
assert.deepEqual(route(tampered), {ok: false, error: 'signature_invalid'});
assert.equal(healthTab.rows[0][0], before);

// the health source may call put_health_v1 and nothing else
const asOpen = signed({schema_version: 'google-ledger-projection-v2', action: 'append_open_v2', source_id: 'health-a1', project_id: 'fleet-health', sheet_name: '維運健康',
  request_id: nextId(), issued_at: new Date().toISOString(), projection: {trade_id: 'x'}}, healthSecret);
assert.deepEqual(route(asOpen), {ok: false, error: 'action_not_allowed'});
const asRead = signed({schema_version: 'google-ledger-projection-v2', action: 'read_reconciliation_v2', source_id: 'health-a1', project_id: 'fleet-health', sheet_name: '維運健康',
  request_id: nextId(), issued_at: new Date().toISOString(), query: {kind: 'source_projection_inventory_v1'}}, healthSecret);
assert.deepEqual(route(asRead), {ok: false, error: 'action_not_allowed'});
assert.equal(healthTab.rows[0][0], before);

// a source registered before put_health_v1 (no allowed_actions) can never write the health cell, on any tab
assert.deepEqual(route(healthRequest({sourceId: 'ledger-a1', secret: ledgerSecret, project: 'mexc-4h-momentum', sheet: 'trading-tab'})), {ok: false, error: 'action_not_allowed'});
untouched();

// a mis-registered health source pointing at a trading tab cannot overwrite that tab's A1
assert.deepEqual(route(healthRequest({sourceId: 'misplaced', secret: 'misplaced-secret', sheet: 'trading-tab'})), {ok: false, error: 'health_sheet_not_allowed'});
untouched();

// the receiver never creates the tab: the operator makes it
assert.deepEqual(route(healthRequest({sourceId: 'missing-tab', secret: 'missing-secret', sheet: '維運健康-不存在'})), {ok: false, error: 'health_sheet_not_allowed'});
sources['missing-tab'].sheet_name = '維運健康';
sheets.delete('維運健康');
assert.deepEqual(route(healthRequest({sourceId: 'missing-tab', secret: 'missing-secret'})), {ok: false, error: 'sheet_not_found'});
assert.equal(calls.filter(c => c.op === 'insertSheet').length, 0);

// review of #250 (B1): allowed_actions present but not an array allows NOTHING -- it never falls back to the wide rule
const rawSecret = {'broken-empty': 'broken-secret', 'broken-string': 'broken-secret', 'broken-null': 'broken-secret', 'broken-object': 'broken-secret', 'broken-number': 'broken-secret'};
for (const [sourceId, secret] of Object.entries(rawSecret)) {
  const src = sources[sourceId];
  assert.equal(context.actionAllowedForSource(src, 'append_open_v2'), false, sourceId);
  assert.equal(context.actionAllowedForSource(src, 'put_health_v1'), false, sourceId);
  assert.deepEqual(route(healthRequest({sourceId, secret})), {ok: false, error: 'action_not_allowed'}, sourceId);
  const openAttempt = signed({schema_version: 'google-ledger-projection-v2', action: 'append_open_v2', source_id: sourceId, project_id: 'fleet-health', sheet_name: '維運健康',
    request_id: nextId(), issued_at: new Date().toISOString(), projection: {trade_id: 'x'}}, secret);
  assert.deepEqual(route(openAttempt), {ok: false, error: 'action_not_allowed'}, sourceId);
}
// a source with both actions listed gets exactly those two
sheets.set('維運健康', healthTab);
assert.equal(route(healthRequest({sourceId: 'both', secret: 'both-secret'})).ok, true);
assert.equal(context.actionAllowedForSource(sources.both, 'read_reconciliation_v2'), true);
assert.equal(context.actionAllowedForSource(sources.both, 'append_open_v2'), false);
// and a source with no allowed_actions at all is the old wide rule minus the health write
assert.equal(context.actionAllowedForSource(ledgerSource, 'append_open_v2'), true);
assert.equal(context.actionAllowedForSource(ledgerSource, 'put_health_v1'), false);

console.log('apps_script_put_health_node_test: passed');
