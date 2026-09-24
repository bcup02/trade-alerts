const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');

const legacySecret = 'legacy-test-secret';
const v2Secret = 'v2-test-secret';
const source = {hmac_secret: v2Secret, project_id: 'mexc-4h-momentum', sheet_name: 'mexc-4h-momentum-trailing-stop'};
const sheets = new Map();

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
}

function bytesFromDigest(algorithm, text, key) {
  const output = key ? crypto.createHmac(algorithm, key).update(text, 'utf8').digest() : crypto.createHash(algorithm).update(text, 'utf8').digest();
  return Array.from(output).map(number => number > 127 ? number - 256 : number);
}

const callLog = [];   // {op:'setValue'|'setNumberFormat', row, column} in call order

function createSheet(name, rows) {
  const sheet = {
    name,
    rows,
    getLastRow() { return this.rows.length; },
    getRange(row, column, height = 1, width = 1) {
      const target = this;
      return {
        getValues() {
          return target.rows.slice(row - 1, row - 1 + height).map(current => {
            const copy = current.slice(column - 1, column - 1 + width);
            while (copy.length < width) copy.push('');
            return copy;
          });
        },
        setValue(value) {
          callLog.push({op: 'setValue', row, column});
          while (target.rows.length < row) target.rows.push([]);
          while (target.rows[row - 1].length < column) target.rows[row - 1].push('');
          target.rows[row - 1][column - 1] = value;
        },
        setNumberFormat() { callLog.push({op: 'setNumberFormat', row, column}); },
        setValues(values) {
          values.forEach((valuesRow, rowOffset) => {
            while (target.rows.length < row + rowOffset) target.rows.push([]);
            valuesRow.forEach((value, columnOffset) => {
              while (target.rows[row + rowOffset - 1].length < column + columnOffset) target.rows[row + rowOffset - 1].push('');
              target.rows[row + rowOffset - 1][column + columnOffset - 1] = value;
            });
          });
        },
        getCell(rowOffset, columnOffset) {
          return {
            setNumberFormat() {},
            setValue(value) {
              const targetRow = row + rowOffset - 1;
              const targetColumn = column + columnOffset - 1;
              while (target.rows.length < targetRow) target.rows.push([]);
              while (target.rows[targetRow - 1].length < targetColumn) target.rows[targetRow - 1].push('');
              target.rows[targetRow - 1][targetColumn - 1] = value;
            },
          };
        },
      };
    },
    appendRow(values) { this.rows.push(values); },
  };
  sheets.set(name, sheet);
  return sheet;
}

const projectSheet = createSheet(source.sheet_name, [['trade_id']]);
let auditSheetCreated = 0;
const context = {
  console,
  Date,
  JSON,
  Math,
  Object,
  String,
  Array,
  Number,
  Set,
  isNaN,
  isFinite,
  PropertiesService: {getScriptProperties: () => ({getProperty: key => {
    if (key === 'SHARED_SECRET') return legacySecret;
    if (key === 'GOOGLE_LEDGER_V2_SOURCES') return JSON.stringify({'momentum-wsl-prod': source});
    return null;
  }})},
  Utilities: {
    Charset: {UTF_8: 'UTF_8'},
    DigestAlgorithm: {SHA_256: 'SHA_256'},
    computeHmacSha256Signature: (text, key) => bytesFromDigest('sha256', text, key),
    computeDigest: (algorithm, text) => bytesFromDigest('sha256', text),
    // Stub for the one call shape the receiver uses: Asia/Taipei (UTC+8, no
    // DST) with 'yyyy-MM-dd H:mm:ss' -- hour unpadded, minute/second padded.
    formatDate: (date, tz, fmt) => {
      assert.equal(tz, 'Asia/Taipei');
      assert.equal(fmt, 'yyyy-MM-dd H:mm:ss');
      const t = new Date(date.getTime() + 8 * 3600 * 1000);
      const p = n => String(n).padStart(2, '0');
      return `${t.getUTCFullYear()}-${p(t.getUTCMonth() + 1)}-${p(t.getUTCDate())} ${t.getUTCHours()}:${p(t.getUTCMinutes())}:${p(t.getUTCSeconds())}`;
    },
  },
  SpreadsheetApp: {getActiveSpreadsheet: () => ({
    getSheetByName: name => sheets.get(name) || null,
    insertSheet: name => {
      auditSheetCreated += 1;
      return createSheet(name, []);
    },
  })},
  ContentService: {MimeType: {JSON: 'application/json'}, createTextOutput: text => ({text, setMimeType() { return this; }})},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps_script/google_ledger_receiver.gs', 'utf8'), context, {filename: 'google_ledger_receiver.gs'});

function route(payload) {
  return JSON.parse(JSON.stringify(context.routeRequest(payload)));
}
function v2Inventory(query = {kind: 'source_projection_inventory_v1'}) {
  const body = {
    schema_version: 'google-ledger-projection-v2', action: 'read_reconciliation_v2',
    source_id: 'momentum-wsl-prod', project_id: source.project_id, sheet_name: source.sheet_name,
    request_id: '00000000-0000-4000-8000-000000000010', issued_at: new Date().toISOString(), query,
  };
  return {...body, signature: crypto.createHmac('sha256', v2Secret).update(canonicalJson(body), 'utf8').digest('hex')};
}

function v2Write({action, eventType, tradeId, projection, requestId}) {
  const provenance = {
    project_id: source.project_id, trade_id: tradeId, event_type: eventType,
    ledger_event_digest: 'a'.repeat(64),
    payload_digest: crypto.createHash('sha256').update(canonicalJson(projection), 'utf8').digest('hex'),
    request_id: requestId, issued_at: new Date().toISOString(), source_id: 'momentum-wsl-prod', schema_version: 'google-ledger-projection-v2',
  };
  const body = {
    schema_version: 'google-ledger-projection-v2', action, source_id: 'momentum-wsl-prod',
    project_id: source.project_id, sheet_name: source.sheet_name, request_id: provenance.request_id,
    issued_at: provenance.issued_at, provenance, projection,
  };
  return {...body, signature: crypto.createHmac('sha256', v2Secret).update(canonicalJson(body), 'utf8').digest('hex')};
}

const legacyOpen = {
  secret: legacySecret, sheet_name: source.sheet_name,
  common: {trade_id: 'legacy-trade-1', execution_mode: 'LIVE', symbol: 'TEST_USDT', side: 'long', entry_time: '2026-08-26 12:00:00', entry_price: 1, volume: 2, leverage: 3, entry_fee: 0.1},
};
const firstAppend = route(legacyOpen);
assert.deepEqual(firstAppend, {ok: true, row: 2, sheet: source.sheet_name});
assert.equal(projectSheet.rows.length, 2);
assert.equal(projectSheet.rows[1][0], 'legacy-trade-1');

const retryAppend = route(legacyOpen);
assert.deepEqual(retryAppend, {ok: true, row: 2, sheet: source.sheet_name, note: 'duplicate trade_id on append, treated as an idempotent retry — no new row written'});
assert.equal(projectSheet.rows.length, 2);

// Deployed legacy behavior is intentionally preserved for historical duplicate rows.
projectSheet.rows.push(['legacy-trade-1']);
const duplicateAppend = route(legacyOpen);
assert.deepEqual(duplicateAppend, {ok: true, row: 2, sheet: source.sheet_name, note: 'duplicate trade_id on append, treated as an idempotent retry — no new row written'});
callLog.length = 0;
const legacyClose = route({secret: legacySecret, sheet_name: source.sheet_name, action: 'update_by_trade_id', trade_id: 'legacy-trade-1', updates: {F: '2026-08-26 13:00:00', N: '-0.1'}});
assert.deepEqual(legacyClose, {ok: true, row: 2, sheet: source.sheet_name, updated_columns: ['F', 'N']});
assert.equal(projectSheet.rows[1][5], '2026-08-26 13:00:00');
assert.equal(projectSheet.rows[1][13], '-0.1');
assert.equal(projectSheet.rows[2][5], undefined);
// column F (=6) holds a datetime-shaped string -> @ format MUST be set before
// setValue, or Sheets parses the string to a Date and the '@' only freezes the
// re-formatted (seconds-dropped) display string.
const fCalls = callLog.filter(c => c.column === 6).map(c => c.op);
assert.deepEqual(fCalls, ['setNumberFormat', 'setValue']);
// column N (=14) '-0.1' is not datetime-shaped -> setValue only, no @.
assert.deepEqual(callLog.filter(c => c.column === 14).map(c => c.op), ['setValue']);

const accountSheet = createSheet('帳戶餘額總表', [['id', 'project'], ['', 'my-crypto-bot']]);
callLog.length = 0;
const legacyKeyUpdate = route({secret: legacySecret, sheet_name: '帳戶餘額總表', action: 'update_by_key', key_column: 'B', key_value: 'my-crypto-bot', updates: {G: '0.0234', F: '2026-08-26 0:00:49'}});
assert.deepEqual(legacyKeyUpdate, {ok: true, row: 2, sheet: '帳戶餘額總表', updated_columns: ['G', 'F']});
assert.equal(accountSheet.rows[1][6], '0.0234');
assert.equal(accountSheet.rows[1][5], '2026-08-26 0:00:49');
assert.deepEqual(callLog.filter(c => c.column === 6).map(c => c.op), ['setNumberFormat', 'setValue']);  // F, datetime-shaped

const v2OpenProjection = {trade_id: 'v2-trade-1', execution_mode: 'LIVE', symbol: 'TEST_USDT', side: 'long', entry_time: '2026-08-26T00:00:00Z', entry_price: '1', volume: '2', leverage: '3', entry_fee: '0.01', entry_order_id: '123456789012345678'};
const v2Open = v2Write({action: 'append_open_v2', eventType: 'trade_open', tradeId: 'v2-trade-1', projection: v2OpenProjection, requestId: '00000000-0000-4000-8000-000000000012'});
const v2OpenFirst = route(v2Open);
assert.deepEqual(v2OpenFirst, {ok: true, row: 4, provenance_status: 'CONFIRMED'});
assert.deepEqual(route(v2Open), {ok: true, row: 4, idempotent: true});
// entry_time (col E, index 4) is projected as UTC ISO but stored as Taipei
// local text, matching the pre-v2 rows: 2026-08-26T00:00:00Z -> +08:00.
assert.equal(projectSheet.rows[3][4], '2026-08-26 8:00:00');
const v2CloseProjection = {trade_id: 'v2-trade-1', exit_time: '2026-08-26T01:00:00Z', entry_price: '1', exit_price: '0.9', entry_volume: '2', exit_volume: '2', leverage: '3', entry_fee: '0.01', exit_fee: '0.01', gross_pnl: '-0.2', net_pnl: '-0.22', return_on_margin: '-10', source: 'test_close'};
const v2Close = v2Write({action: 'update_close_v2', eventType: 'trade_close', tradeId: 'v2-trade-1', projection: v2CloseProjection, requestId: '00000000-0000-4000-8000-000000000013'});
assert.deepEqual(route(v2Close), {ok: true, row: 4, provenance_status: 'CONFIRMED'});
assert.deepEqual(route(v2Close), {ok: true, row: 4, idempotent: true});
// exit_time (col F, index 5): 2026-08-26T01:00:00Z -> Taipei text.
assert.equal(projectSheet.rows[3][5], '2026-08-26 9:00:00');
// correct_close_v2 (h4): a ledger trade_correction may only supersede the
// projection in force -- the confirmed close, then the latest confirmed
// correction -- and it also rewrites the entry price / volume and notes.
const digestOf = projection => crypto.createHash('sha256').update(canonicalJson(projection), 'utf8').digest('hex');
const closeDigest = digestOf(v2CloseProjection);
const correction1 = {...v2CloseProjection, entry_price: '1.05', entry_volume: '3', exit_volume: '3', entry_fee: '0.02', gross_pnl: '-0.45', net_pnl: '-0.48', return_on_margin: '-9', exit_order_id: '223456789012345678', reason_code: 'DUPLICATE_ENTRY_UNRECORDED', notes: 'trade_correction: duplicate entry restated from exchange fills', corrects_payload_digest: 'b'.repeat(64)};
const badBase = v2Write({action: 'correct_close_v2', eventType: 'trade_correction', tradeId: 'v2-trade-1', projection: correction1, requestId: '00000000-0000-4000-8000-000000000020'});
assert.deepEqual(route(badBase), {ok: false, error: 'correction_base_mismatch'});
assert.equal(projectSheet.rows[3][13], -0.22);  // net_pnl (N) untouched
const goodCorrection1 = {...correction1, corrects_payload_digest: closeDigest};
const correct1 = v2Write({action: 'correct_close_v2', eventType: 'trade_correction', tradeId: 'v2-trade-1', projection: goodCorrection1, requestId: '00000000-0000-4000-8000-000000000021'});
assert.deepEqual(route(correct1), {ok: true, row: 4, provenance_status: 'CONFIRMED'});
assert.deepEqual(route(correct1), {ok: true, row: 4, idempotent: true});
assert.equal(projectSheet.rows[3][13], -0.48);   // N net_pnl
assert.equal(projectSheet.rows[3][6], 1.05);     // G entry_price (whole trade)
assert.equal(projectSheet.rows[3][8], 3);        // I volume (whole trade)
assert.equal(projectSheet.rows[3][17], '223456789012345678');  // R exit_order_id
assert.equal(projectSheet.rows[3][20], 'trade_correction: duplicate entry restated from exchange fills');  // U notes
// A second correction must name the first correction, not the original close.
const correction2 = {...goodCorrection1, net_pnl: '-0.5', notes: 'fee restated'};
const staleSecond = v2Write({action: 'correct_close_v2', eventType: 'trade_correction', tradeId: 'v2-trade-1', projection: correction2, requestId: '00000000-0000-4000-8000-000000000022'});
assert.deepEqual(route(staleSecond), {ok: false, error: 'correction_base_mismatch'});
const chainedSecond = v2Write({action: 'correct_close_v2', eventType: 'trade_correction', tradeId: 'v2-trade-1', projection: {...correction2, corrects_payload_digest: digestOf(goodCorrection1)}, requestId: '00000000-0000-4000-8000-000000000023'});
assert.deepEqual(route(chainedSecond), {ok: true, row: 4, provenance_status: 'CONFIRMED'});
assert.equal(projectSheet.rows[3][13], -0.5);
// Wrong event type, or a correction without its reason notes, is refused.
const asClose = v2Write({action: 'correct_close_v2', eventType: 'trade_close', tradeId: 'v2-trade-1', projection: {...correction2, net_pnl: '-0.6'}, requestId: '00000000-0000-4000-8000-000000000024'});
assert.deepEqual(route(asClose), {ok: false, error: 'correction_projection_invalid'});
const noNotes = {...correction2, net_pnl: '-0.6'};
delete noNotes.notes;
const withoutNotes = v2Write({action: 'correct_close_v2', eventType: 'trade_correction', tradeId: 'v2-trade-1', projection: noNotes, requestId: '00000000-0000-4000-8000-000000000025'});
assert.deepEqual(route(withoutNotes), {ok: false, error: 'correction_projection_invalid'});
// No confirmed close to correct.
const orphanCorrection = v2Write({action: 'correct_close_v2', eventType: 'trade_correction', tradeId: 'legacy-trade-1', projection: {...goodCorrection1, trade_id: 'legacy-trade-1'}, requestId: '00000000-0000-4000-8000-000000000026'});
assert.deepEqual(route(orphanCorrection), {ok: false, error: 'duplicate_trade_id'});
assert.equal(projectSheet.rows[3][13], -0.5);
// formatSheetTime passes an already-Taipei-text value through unchanged and
// never throws on an unparseable one (unit-level guard for the rewrite tool).
assert.equal(context.formatSheetTime('2026-08-27 0:30:05'), '2026-08-27 0:30:05');
assert.equal(context.formatSheetTime(''), '');
assert.equal(context.formatSheetTime('not-a-date'), 'not-a-date');
const rejectedOpen = v2Write({action: 'append_open_v2', eventType: 'trade_open', tradeId: 'v2-rejected-1', projection: {...v2OpenProjection, trade_id: 'v2-rejected-1', unexpected: 'field'}, requestId: '00000000-0000-4000-8000-000000000014'});
assert.deepEqual(route(rejectedOpen), {ok: false, error: 'open_projection_invalid'});
const auditSheet = sheets.get('Google_Provenance_Audit');
assert.ok(auditSheet);
assert.equal(auditSheet.rows[auditSheet.rows.length - 1][9], 'REJECTED');

const unknownSchema = route({...legacyOpen, schema_version: 'v999'});
assert.deepEqual(unknownSchema, {ok: false, error: 'unsupported_schema'});
assert.equal(projectSheet.rows.length, 4);

const v2Read = route(v2Inventory());
assert.equal(v2Read.ok, true);
assert.equal(v2Read.items.length, 3);
const legacyInventory = v2Read.items.find(item => item.trade_id === 'legacy-trade-1');
assert.equal(legacyInventory.google_row_count, 2);
const rejectedInventory = v2Read.items.find(item => item.trade_id === 'v2-rejected-1');
assert.equal(rejectedInventory.audit[0].status, 'REJECTED');
assert.equal(auditSheetCreated, 1);

const wrongSecretV2 = v2Inventory();
wrongSecretV2.signature = crypto.createHmac('sha256', legacySecret).update(canonicalJson(Object.fromEntries(Object.entries(wrongSecretV2).filter(([key]) => key !== 'signature'))), 'utf8').digest('hex');
assert.deepEqual(route(wrongSecretV2), {ok: false, error: 'signature_invalid'});
assert.equal(auditSheetCreated, 1);

const doPostResult = context.doPost({postData: {contents: JSON.stringify(v2Inventory())}});
assert.equal(JSON.parse(doPostResult.text).ok, true);

console.log('apps_script_unified_receiver_node_test: passed');
