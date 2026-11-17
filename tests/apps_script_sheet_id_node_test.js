// Sheet-id registration: a source bound to a tab by its fixed id keeps working when the tab is renamed, a source bound by
// name keeps the exact-name rule, and the read-only list_by_sheet can name a PROJECT instead of a tab.
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');

const SHARED = 'shared-test-secret';
const idSecret = 'id-test-secret';
const nameSecret = 'name-test-secret';
const healthSecret = 'health-test-secret';

const sheets = [];                       // {id, name, rows}; the mock book
function addSheet(id, name, rows) { const sheet = {id, name, rows}; sheets.push(sheet); return sheet; }
const meteorTab = addSheet(111, 'tab-before-rename', [['trade_id', 'symbol'], ['TM-1', 'DOGEUSDT']]);
const oldTab = addSheet(222, 'old-trend', [['trade_id', 'symbol'], ['SEY-1', 'BTCUSDT']]);
const healthTab = addSheet(333, '維運健康', [['']]);
const calls = [];

function sheetApi(sheet) {
  return {
    getName: () => sheet.name,
    getSheetId: () => sheet.id,
    getLastRow: () => sheet.rows.length,
    getLastColumn: () => Math.max(...sheet.rows.map(r => r.length)),
    getRange: (row, column, height = 1, width = 1) => ({
      getValues: () => Array.from({length: height}, (_, i) => Array.from({length: width}, (_, j) => (sheet.rows[row - 1 + i] || [])[column - 1 + j] ?? '')),
      setNumberFormat: () => calls.push({sheet: sheet.name, op: 'setNumberFormat'}),
      setValue: value => { calls.push({sheet: sheet.name, op: 'setValue'}); while (sheet.rows.length < row) sheet.rows.push([]); sheet.rows[row - 1][column - 1] = value; },
    }),
  };
}

const sources = {
  'meteor-id': {hmac_secret: idSecret, project_id: 'trend-meteor', sheet_id: 111, sheet_name: 'label-only'},
  'meteor-id-nolabel': {hmac_secret: idSecret, project_id: 'trend-meteor-b', sheet_id: 111},
  'old-name': {hmac_secret: nameSecret, project_id: 'ed-seykota', sheet_name: 'old-trend'},
  'health-id': {hmac_secret: healthSecret, project_id: 'fleet-health', sheet_id: 333, allowed_actions: ['put_health_v1']},
  'health-id-wrongtab': {hmac_secret: healthSecret, project_id: 'fleet-health-x', sheet_id: 111, allowed_actions: ['put_health_v1']},
  'gone-id': {hmac_secret: idSecret, project_id: 'gone-project', sheet_id: 999},
};
const propsFor = {GOOGLE_LEDGER_V2_SOURCES: () => JSON.stringify(sources), SHARED_SECRET: () => SHARED};

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
}
function bytesFromDigest(algorithm, text, key) {
  const output = key ? crypto.createHmac(algorithm, key).update(text, 'utf8').digest() : crypto.createHash(algorithm).update(text, 'utf8').digest();
  return Array.from(output).map(number => number > 127 ? number - 256 : number);
}
const context = {console, Date, JSON, Math, Object, String, Array, Number, Set, isNaN, isFinite,
  Logger: {log: () => {}},
  PropertiesService: {getScriptProperties: () => ({getProperty: key => propsFor[key] ? propsFor[key]() : null})},
  Utilities: {Charset: {UTF_8: 'UTF_8'}, DigestAlgorithm: {SHA_256: 'SHA_256'},
    computeHmacSha256Signature: (text, key) => bytesFromDigest('sha256', text, key),
    computeDigest: (algorithm, text) => bytesFromDigest('sha256', text)},
  SpreadsheetApp: {getActiveSpreadsheet: () => ({
    getSheetByName: name => { const s = sheets.find(x => x.name === name); return s ? sheetApi(s) : null; },
    getSheets: () => sheets.map(sheetApi),
    insertSheet: name => { calls.push({op: 'insertSheet', name}); throw new Error('the receiver never creates a tab here'); },
  })},
  ContentService: {MimeType: {JSON: 'application/json'}, createTextOutput: text => ({text, setMimeType() { return this; }})}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps_script/google_ledger_receiver.gs', 'utf8'), context, {filename: 'google_ledger_receiver.gs'});

const route = payload => JSON.parse(JSON.stringify(context.routeRequest(payload)));
let seq = 0;
const nextId = () => `00000000-0000-4000-8000-${String(++seq).padStart(12, '0')}`;
const signed = (body, secret) => ({...body, signature: crypto.createHmac('sha256', secret).update(canonicalJson(body), 'utf8').digest('hex')});
function inventory({sourceId = 'meteor-id', secret = idSecret, project = 'trend-meteor', sheetName} = {}) {
  const body = {schema_version: 'google-ledger-projection-v2', action: 'read_reconciliation_v2', source_id: sourceId, project_id: project,
    request_id: nextId(), issued_at: new Date().toISOString(), query: {kind: 'source_projection_inventory_v1'}};
  if (sheetName !== undefined) body.sheet_name = sheetName;
  return signed(body, secret);
}
function healthWrite({sourceId = 'health-id', project = 'fleet-health', sheetName} = {}) {
  const body = {schema_version: 'google-ledger-projection-v2', action: 'put_health_v1', source_id: sourceId, project_id: project,
    request_id: nextId(), issued_at: new Date().toISOString(), health: {b64: 'AAAA', generated_at: new Date().toISOString()}};
  if (sheetName !== undefined) body.sheet_name = sheetName;
  return signed(body, healthSecret);
}
const ids = result => result.items.map(item => item.trade_id);

// 1. a sheet_id source reaches its tab whatever sheet_name the request carries, and after the tab is renamed
let answer = route(inventory({sheetName: 'label-only'}));
assert.equal(answer.ok, true); assert.deepEqual(ids(answer), ['TM-1']);
answer = route(inventory());                                      // no sheet_name at all
assert.equal(answer.ok, true); assert.deepEqual(ids(answer), ['TM-1']);
answer = route(inventory({sheetName: 'something-completely-different'}));
assert.equal(answer.ok, true); assert.deepEqual(ids(answer), ['TM-1']);
meteorTab.name = '競賽策略・流星版';                               // the rename: no release, no registry edit
answer = route(inventory({sheetName: 'tab-before-rename'}));
assert.equal(answer.ok, true); assert.deepEqual(ids(answer), ['TM-1']);
answer = route(inventory());
assert.equal(answer.ok, true); assert.deepEqual(ids(answer), ['TM-1']);

// 2. the other gates still apply to a sheet_id source
assert.deepEqual(route(inventory({project: 'ed-seykota'})), {ok: false, error: 'source_not_allowed'});
assert.deepEqual(route(inventory({secret: 'wrong-secret'})), {ok: false, error: 'signature_invalid'});
assert.deepEqual(route(inventory({sourceId: 'not-registered'})), {ok: false, error: 'source_not_allowed'});
assert.deepEqual(route(inventory({sourceId: 'gone-id', project: 'gone-project'})), {ok: false, error: 'sheet_not_found'});

// 3. a source registered by NAME keeps the exact-name rule, and renaming its tab breaks it (as before)
answer = route(inventory({sourceId: 'old-name', secret: nameSecret, project: 'ed-seykota', sheetName: 'old-trend'}));
assert.equal(answer.ok, true); assert.deepEqual(ids(answer), ['SEY-1']);
assert.deepEqual(route(inventory({sourceId: 'old-name', secret: nameSecret, project: 'ed-seykota', sheetName: 'renamed-old'})), {ok: false, error: 'source_not_allowed'});
assert.deepEqual(route(inventory({sourceId: 'old-name', secret: nameSecret, project: 'ed-seykota'})), {ok: false, error: 'source_not_allowed'});

// 4. sheet_id present but not a non-negative whole number allows nothing (never falls back to the name)
// (undefined is not a JSON value: the key would vanish and the entry would become a plain name registration)
for (const bad of ['111', null, -1, 1.5, NaN, Infinity, 2 ** 60, [111], {id: 111}, true]) {
  sources['bad-id'] = {hmac_secret: idSecret, project_id: 'bad-project', sheet_id: bad, sheet_name: 'old-trend'};
  const label = String(bad);
  assert.deepEqual(route(inventory({sourceId: 'bad-id', project: 'bad-project', sheetName: 'old-trend'})), {ok: false, error: 'source_not_allowed'}, label);
  assert.equal(context.validRegistration(sources['bad-id']), false, label);
}
sources['bad-label'] = {hmac_secret: idSecret, project_id: 'bad-project', sheet_id: 111, sheet_name: 5};
assert.equal(context.validRegistration(sources['bad-label']), false);
delete sources['bad-id']; delete sources['bad-label'];
assert.equal(context.validRegistration(sources['meteor-id']), true);
assert.equal(context.validRegistration(sources['meteor-id-nolabel']), true);
assert.equal(context.validRegistration({hmac_secret: 'x', project_id: 'p'}), false);                // neither id nor name
assert.equal(context.validRegistration({hmac_secret: 'x', project_id: 'p', sheet_id: 0}), true);    // id 0 is a real tab id

// 5. put_health_v1 through a sheet_id source: only a tab whose CURRENT name is 維運健康
answer = route(healthWrite());
assert.equal(answer.ok, true); assert.equal(healthTab.rows[0][0], 'HEALTHv1|AAAA|HEALTHEND');
healthTab.name = '維運健康-改名';
assert.deepEqual(route(healthWrite()), {ok: false, error: 'health_sheet_not_allowed'});
healthTab.name = '維運健康';
const tradingBefore = JSON.stringify(meteorTab.rows);
assert.deepEqual(route(healthWrite({sourceId: 'health-id-wrongtab', project: 'fleet-health-x'})), {ok: false, error: 'health_sheet_not_allowed'});
assert.equal(JSON.stringify(meteorTab.rows), tradingBefore);

// 6. legacy list_by_sheet: by name unchanged; by project through the registry
const legacy = extra => route({secret: SHARED, action: 'list_by_sheet', ...extra});
answer = legacy({sheet_name: 'old-trend'});
assert.equal(answer.ok, true); assert.equal(answer.sheet, 'old-trend'); assert.equal(answer.row_count, 1);
answer = legacy({project_id: 'trend-meteor'});
assert.equal(answer.ok, true); assert.equal(answer.sheet, '競賽策略・流星版'); assert.deepEqual(answer.rows.map(r => r.values[0]), ['TM-1']);
answer = legacy({project_id: 'ed-seykota'});                                  // registered by name
assert.equal(answer.ok, true); assert.equal(answer.sheet, 'old-trend');
assert.deepEqual(legacy({project_id: 'nobody'}), {ok: false, error: 'project_not_registered'});
assert.deepEqual(legacy({project_id: 123}), {ok: false, error: 'project_not_registered'});
assert.deepEqual(legacy({project_id: '../x'}), {ok: false, error: 'project_not_registered'});
assert.deepEqual(legacy({project_id: 'gone-project'}), {ok: false, error: 'sheet_not_found'});
assert.deepEqual(legacy({project_id: 'trend-meteor', sheet_name: 'old-trend'}), {ok: false, error: 'ambiguous_sheet_selector'});
assert.deepEqual(route({secret: 'wrong', action: 'list_by_sheet', project_id: 'trend-meteor'}).error, 'unauthorized');
// two registrations of one project that name different tabs: the receiver does not guess
sources['twin-a'] = {hmac_secret: 'a', project_id: 'twin', sheet_id: 111};
sources['twin-b'] = {hmac_secret: 'b', project_id: 'twin', sheet_id: 222};
assert.deepEqual(legacy({project_id: 'twin'}), {ok: false, error: 'project_ambiguous'});
sources['twin-b'] = {hmac_secret: 'b', project_id: 'twin', sheet_id: 111, sheet_name: 'other label'};   // same tab again: fine
assert.equal(legacy({project_id: 'twin'}).ok, true);
delete sources['twin-a']; delete sources['twin-b'];
// review of #372: one tab registered BOTH by name and by id is the same tab, not ambiguous (migration from name to id)
sources['mix-name'] = {hmac_secret: 'a', project_id: 'mix', sheet_name: '競賽策略・流星版'};
sources['mix-id'] = {hmac_secret: 'b', project_id: 'mix', sheet_id: 111};
answer = legacy({project_id: 'mix'});
assert.equal(answer.ok, true); assert.equal(answer.sheet, '競賽策略・流星版'); assert.deepEqual(answer.rows.map(r => r.values[0]), ['TM-1']);
// the same two registrations, but the id names a DIFFERENT tab: ambiguous
sources['mix-id'] = {hmac_secret: 'b', project_id: 'mix', sheet_id: 222};
assert.deepEqual(legacy({project_id: 'mix'}), {ok: false, error: 'project_ambiguous'});
// a name registration for a tab that no longer exists (renamed) next to a good id registration: disagree, fail closed
sources['mix-name'] = {hmac_secret: 'a', project_id: 'mix', sheet_name: 'stale-old-name'};
sources['mix-id'] = {hmac_secret: 'b', project_id: 'mix', sheet_id: 111};
assert.deepEqual(legacy({project_id: 'mix'}), {ok: false, error: 'project_ambiguous'});
// two registrations that both resolve to nothing, the same way: still "tab not found", not ambiguous
sources['mix-name'] = {hmac_secret: 'a', project_id: 'mix', sheet_name: 'stale-old-name'};
sources['mix-id'] = {hmac_secret: 'b', project_id: 'mix', sheet_name: 'stale-old-name', allowed_actions: []};
assert.deepEqual(legacy({project_id: 'mix'}), {ok: false, error: 'sheet_not_found'});
delete sources['mix-name']; delete sources['mix-id'];
// an invalid registration never counts toward a project
sources['broken'] = {hmac_secret: 'a', project_id: 'broken-project', sheet_id: '111'};
assert.deepEqual(legacy({project_id: 'broken-project'}), {ok: false, error: 'project_not_registered'});
delete sources['broken'];

// 7. project_id is read-only: no legacy write action takes it
const before = JSON.stringify(sheets.map(s => s.rows));
for (const action of ['update_by_trade_id', 'update_by_key', 'append', undefined]) {
  const payload = {secret: SHARED, project_id: 'trend-meteor', trade_id: 'TM-1', updates: {B: 'x'}};
  if (action) payload.action = action;
  assert.deepEqual(route(payload), {ok: false, error: 'project_id_not_supported_for_action'}, String(action));
}
assert.equal(JSON.stringify(sheets.map(s => s.rows)), before);
assert.equal(calls.filter(c => c.op === 'insertSheet').length, 0);

// 8. the legacy name path with no project_id is exactly as before
assert.deepEqual(route({secret: SHARED, action: 'list_by_sheet'}), {ok: false, error: 'missing sheet_name'});
assert.deepEqual(route({secret: SHARED, action: 'list_by_sheet', sheet_name: 'no-such-tab'}), {ok: false, error: 'sheet not found: no-such-tab'});

// 9. the editor helper lists names and ids, and changes nothing
assert.deepEqual(JSON.parse(JSON.stringify(context.listSheetIdsForRegistration())), sheets.map(s => ({name: s.name, sheet_id: s.id})));

console.log('apps_script_sheet_id_node_test: passed');
