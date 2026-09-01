const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const legacySecret = 'legacy-test-secret';
const sheets = new Map();

// Minimal Sheet stub: getLastRow / getLastColumn / getRange().getValues() /
// setValue / setValues / getCell().setNumberFormat / appendRow. `rows` is a
// 2-D array (row 0 = header).
function createSheet(name, rows) {
  const sheet = {
    name,
    rows,
    getLastRow() { return this.rows.length; },
    getLastColumn() { return this.rows.reduce((max, r) => Math.max(max, r.length), 0); },
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
          while (target.rows.length < row) target.rows.push([]);
          while (target.rows[row - 1].length < column) target.rows[row - 1].push('');
          target.rows[row - 1][column - 1] = value;
        },
        setValues(values) {
          values.forEach((valuesRow, rowOffset) => {
            while (target.rows.length < row + rowOffset) target.rows.push([]);
            valuesRow.forEach((value, columnOffset) => {
              while (target.rows[row + rowOffset - 1].length < column + columnOffset) target.rows[row + rowOffset - 1].push('');
              target.rows[row + rowOffset - 1][column + columnOffset - 1] = value;
            });
          });
        },
        getCell() { return { setNumberFormat() {}, setValue() {} }; },
        setNumberFormat() {},
      };
    },
    appendRow(values) { this.rows.push(values); },
  };
  sheets.set(name, sheet);
  return sheet;
}

const HEADER = ['trade_id', 'execution_mode', 'symbol', 'side', 'entry_time', 'exit_time',
  'entry_price', 'exit_price', 'volume', 'leverage', 'entry_fee', 'exit_fee', 'gross_pnl',
  'net_pnl', 'return_on_margin', 'source', 'entry_order_id', 'exit_order_id',
  'stop_plan_order_id', 'exit_anomaly', 'notes'];

const tab = createSheet('my-crypto-bot', [
  HEADER.slice(),
  ['t-1', 'LIVE', 'BTC_USDT', 'long', '2026-08-09 18:29:37', '', 65191, 65196, 1, 3],
  ['t-2', 'LIVE', 'BTC_USDT', 'short', '2026-08-09 18:41:45', '', 65195.9, 65194.2, 1, 3],
  ['t-3', 'LIVE', 'BTC_USDT', 'short', '2026-08-09 18:45:42', '', 65194.1, 65188.1, 1, 3],
]);
createSheet('empty-tab', [HEADER.slice()]);

const context = {
  console, Date, JSON, Math, Object, String, Array, Number, Set, isNaN, isFinite,
  PropertiesService: { getScriptProperties: () => ({ getProperty: k => (k === 'SHARED_SECRET' ? legacySecret : null) }) },
  Utilities: {
    Charset: { UTF_8: 'UTF_8' }, DigestAlgorithm: { SHA_256: 'SHA_256' },
    computeHmacSha256Signature: () => [], computeDigest: () => [],
  },
  SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: name => sheets.get(name) || null, insertSheet: name => createSheet(name, []) }) },
  ContentService: { MimeType: { JSON: 'application/json' }, createTextOutput: text => ({ text, setMimeType() { return this; } }) },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps_script/google_ledger_receiver.gs', 'utf8'), context, { filename: 'google_ledger_receiver.gs' });

const route = payload => JSON.parse(JSON.stringify(context.routeRequest(payload)));
const call = (over = {}) => route(Object.assign({ secret: legacySecret, sheet_name: 'my-crypto-bot', action: 'list_by_sheet' }, over));

// --- auth ---
assert.deepEqual(route({ secret: 'wrong', sheet_name: 'my-crypto-bot', action: 'list_by_sheet' }),
  { ok: false, error: 'unauthorized', debug: { expected_len: legacySecret.length, received_len: 5 } });
assert.deepEqual(route({ secret: legacySecret, action: 'list_by_sheet' }), { ok: false, error: 'missing sheet_name' });
assert.deepEqual(call({ sheet_name: 'nope' }), { ok: false, error: 'sheet not found: nope' });

// --- no filter -> header + every data row, 1-based sheet row numbers ---
const all = call();
assert.equal(all.ok, true);
assert.equal(all.sheet, 'my-crypto-bot');
assert.deepEqual(all.header, HEADER);
assert.equal(all.row_count, 3);
assert.deepEqual(all.rows.map(r => r.row), [2, 3, 4]);
assert.equal(all.rows[0].values[0], 't-1');
assert.equal(all.rows[0].values.length, HEADER.length); // padded to lastCol
assert.equal(all.rows[2].values[0], 't-3');

// --- non-array trade_ids -> treated as "no filter" ---
assert.equal(call({ trade_ids: 'not-an-array' }).row_count, 3);
assert.equal(call({ trade_ids: null }).row_count, 3);

// --- non-empty trade_ids -> only matching column-A rows ---
const filtered = call({ trade_ids: ['t-3', 't-1', 'missing'] });
assert.equal(filtered.row_count, 2);
assert.deepEqual(filtered.rows.map(r => r.values[0]).sort(), ['t-1', 't-3']);
assert.deepEqual(filtered.rows.map(r => r.row).sort(), [2, 4]);

// --- EMPTY array -> the empty set (ok:true, not an error) ---
const none = call({ trade_ids: [] });
assert.deepEqual(none, { ok: true, sheet: 'my-crypto-bot', header: HEADER, rows: [], row_count: 0 });

// --- header-only tab -> rows:[], row_count:0 ---
assert.deepEqual(call({ sheet_name: 'empty-tab' }),
  { ok: true, sheet: 'empty-tab', header: [], rows: [], row_count: 0 });

// --- regression: append / update_by_trade_id / update_by_key still work, and
//     list_by_sheet never wrote anything ---
const before = JSON.stringify(tab.rows);
const appended = route({ secret: legacySecret, sheet_name: 'my-crypto-bot', common: { trade_id: 't-4', execution_mode: 'LIVE', symbol: 'BTC_USDT' } });
assert.deepEqual(appended, { ok: true, row: 5, sheet: 'my-crypto-bot' });
const upd = route({ secret: legacySecret, sheet_name: 'my-crypto-bot', action: 'update_by_trade_id', trade_id: 't-4', updates: { N: '1.23' } });
assert.deepEqual(upd, { ok: true, row: 5, sheet: 'my-crypto-bot', updated_columns: ['N'] });
assert.equal(tab.rows[4][13], '1.23');
const acct = createSheet('帳戶餘額總表', [['id', 'project'], ['', 'my-crypto-bot']]);
const keyUpd = route({ secret: legacySecret, sheet_name: '帳戶餘額總表', action: 'update_by_key', key_column: 'B', key_value: 'my-crypto-bot', updates: { G: '0.5' } });
assert.deepEqual(keyUpd, { ok: true, row: 2, sheet: '帳戶餘額總表', updated_columns: ['G'] });
assert.equal(acct.rows[1][6], '0.5');
// list_by_sheet did not mutate the first 4 rows
assert.equal(JSON.stringify(tab.rows.slice(0, 4)), before);

// --- doPost wraps it in a JSON text output ---
const wrapped = context.doPost({ postData: { contents: JSON.stringify({ secret: legacySecret, sheet_name: 'my-crypto-bot', action: 'list_by_sheet', trade_ids: ['t-2'] }) } });
assert.equal(JSON.parse(wrapped.text).row_count, 1);
assert.equal(JSON.parse(wrapped.text).rows[0].values[0], 't-2');

console.log('apps_script_legacy_list_by_sheet_node_test: passed');
