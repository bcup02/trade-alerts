// f-56: column P (出場原因) is written in Chinese; the one-time conversion of existing rows is idempotent and conservative.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const glossary = JSON.parse(fs.readFileSync('src/trade_alerts/catalog/fleet-glossary.json', 'utf8'));
const expected = {};
glossary.entries.filter(e => e.category === '帳本來源代碼').forEach(e => e.en.forEach(code => { expected[code] = e.zh; }));

const sheets = [];
function makeSheet(name, header, rows) {
  const data = [header, ...rows];
  const sheet = {
    name, data,
    getName() { return name; },
    getLastRow() { return data.length; },
    getRange(row, column, height = 1, width = 1) {
      return {
        getValue() { return (data[row - 1] || [])[column - 1] ?? ''; },
        getValues() { return data.slice(row - 1, row - 1 + height).map(r => { const c = r.slice(column - 1, column - 1 + width); while (c.length < width) c.push(''); return c; }); },
        setValues(values) { values.forEach((r, i) => r.forEach((v, j) => { while (data[row - 1 + i].length < column + j) data[row - 1 + i].push(''); data[row - 1 + i][column - 1 + j] = v; })); },
      };
    },
  };
  sheets.push(sheet);
  return sheet;
}
const header = Array(21).fill('');
header[15] = '出場原因';
const row = code => { const r = Array(21).fill(''); r[0] = 't'; r[15] = code; return r; };
const project = makeSheet('project', header, [row('atr_trailing_stop'), row('現貨成交'), row('something_new'), row(''), row('spot_fill')]);
const other = makeSheet('帳戶餘額總表', ['id', 'project'], [['', 'native_stop']]);
const audit = makeSheet('Google_Provenance_Audit', header, [row('trend_reversal')]);

const context = {
  console, Date, JSON, Math, Object, String, Array, Number, Set, isNaN, isFinite,
  Logger: {log() {}},
  SpreadsheetApp: {getActiveSpreadsheet: () => ({getSheets: () => sheets})},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('apps_script/google_ledger_receiver.gs', 'utf8'), context, {filename: 'google_ledger_receiver.gs'});

// the labels equal the glossary, code for code
assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('EXIT_REASON_ZH', context))), expected);
assert.equal(context.exitReasonLabel('atr_trailing_stop'), 'ATR 移動停損出場');
assert.equal(context.exitReasonLabel('spot_fill'), '現貨成交');
assert.equal(context.exitReasonLabel('something_new'), 'something_new');   // unknown code: written unchanged
assert.equal(context.exitReasonLabel(''), '');
assert.equal(context.exitReasonLabel(7), 7);
assert.equal(context.exitReasonLabel('toString'), 'toString');             // no prototype lookups
assert.equal(context.sheetValue('source', 'native_stop_reconciled'), '交易所停損觸發（事後補記）');
assert.equal(context.sheetValue('source', null), '');
assert.equal(context.sheetValue('notes', 'native_stop'), 'native_stop');   // only the source column is translated

// preview changes nothing
const before = JSON.stringify(sheets.map(s => s.data));
const preview = JSON.parse(JSON.stringify(context.previewExitReasonConversion()));
assert.deepEqual(preview, [{sheet: 'project', cells_changed: 2}]);          // atr_trailing_stop and spot_fill; the other tab and the audit sheet are skipped
assert.equal(JSON.stringify(sheets.map(s => s.data)), before);

// apply converts exactly the known English codes, once
const applied = JSON.parse(JSON.stringify(context.convertExitReasonsToChinese()));
assert.deepEqual(applied, [{sheet: 'project', cells_changed: 2}]);
assert.deepEqual(project.data.slice(1).map(r => r[15]), ['ATR 移動停損出場', '現貨成交', 'something_new', '', '現貨成交']);
assert.equal(other.data[1][1], 'native_stop');
assert.equal(audit.data[1][15], 'trend_reversal');
assert.deepEqual(JSON.parse(JSON.stringify(context.convertExitReasonsToChinese())), [{sheet: 'project', cells_changed: 0}]);   // idempotent

console.log('apps_script_exit_reason_node_test: passed');
