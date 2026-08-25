const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');

const secret = 'test-only-secret';
const source = {hmac_secret: secret, project_id: 'mexc-4h-momentum', sheet_name: 'mexc-4h-momentum-trailing-stop'};
const projectRows = [['trade_id'], ['historical-dry-run']];
let auditSheetCreated = 0;

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
}
function hmacBytes(text) { return Array.from(crypto.createHmac('sha256', secret).update(text, 'utf8').digest()).map(n => n > 127 ? n - 256 : n); }
function digestBytes(text) { return Array.from(crypto.createHash('sha256').update(text, 'utf8').digest()).map(n => n > 127 ? n - 256 : n); }
function rangeFor(values) { return { getValues: () => values, setValue: () => { throw new Error('unexpected write'); }, setNumberFormat: () => {} }; }
const projectSheet = {
  getLastRow: () => projectRows.length,
  getRange: (row, column, height) => rangeFor(projectRows.slice(row - 1, row - 1 + height).map(r => r.slice(column - 1))),
};
const context = {
  console,
  Date,
  JSON,
  Math,
  Object,
  String,
  Array,
  Number,
  isNaN,
  isFinite,
  PropertiesService: { getScriptProperties: () => ({ getProperty: key => key === 'GOOGLE_LEDGER_V2_SOURCES' ? JSON.stringify({'momentum-wsl-prod': source}) : null }) },
  Utilities: {
    Charset: { UTF_8: 'UTF_8' },
    DigestAlgorithm: { SHA_256: 'SHA_256' },
    computeHmacSha256Signature: text => hmacBytes(text),
    computeDigest: (algorithm, text) => digestBytes(text),
  },
  SpreadsheetApp: { getActiveSpreadsheet: () => ({
    getSheetByName: name => name === source.sheet_name ? projectSheet : null,
    insertSheet: () => { auditSheetCreated += 1; throw new Error('read-only call must not create an audit sheet'); },
  }) },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps_script/google_ledger_receiver_v2.gs', 'utf8'), context, {filename: 'google_ledger_receiver_v2.gs'});

function request(query = {kind: 'source_projection_inventory_v1'}) {
  const body = {
    schema_version: 'google-ledger-projection-v2', action: 'read_reconciliation_v2',
    source_id: 'momentum-wsl-prod', project_id: source.project_id, sheet_name: source.sheet_name,
    request_id: '00000000-0000-4000-8000-000000000010', issued_at: new Date().toISOString(), query,
  };
  return {...body, signature: crypto.createHmac('sha256', secret).update(canonicalJson(body), 'utf8').digest('hex')};
}

const good = context.handleV2(request());
assert.equal(good.ok, true);
assert.deepEqual(JSON.parse(JSON.stringify(good.items)), [{trade_id: 'historical-dry-run', audit: [], google_row_count: 1}]);
assert.equal(auditSheetCreated, 0);

const invalidQuery = context.handleV2(request({kind: 'arbitrary'}));
assert.deepEqual(JSON.parse(JSON.stringify(invalidQuery)), {ok: false, error: 'reconciliation_query_invalid'});
assert.equal(auditSheetCreated, 0);

const tampered = request();
tampered.query = {kind: 'arbitrary'};
const invalidSignature = context.handleV2(tampered);
assert.deepEqual(JSON.parse(JSON.stringify(invalidSignature)), {ok: false, error: 'signature_invalid'});
assert.equal(auditSheetCreated, 0);

console.log('apps_script_receiver_v2_node_test: passed');
