// f-56: column P (出場原因) is written in Chinese; the one-time conversion of existing rows is idempotent and conservative.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const glossary = JSON.parse(fs.readFileSync('src/trade_alerts/catalog/fleet-glossary.json', 'utf8'));
const expectedCorrection = {};
glossary.entries.filter(e => e.category === '帳本更正原因代碼').forEach(e => e.en.forEach(code => { expectedCorrection[code] = e.zh; }));
const expected = {};
glossary.entries.filter(e => e.category === '帳本來源代碼').forEach(e => e.en.forEach(code => { expected[code] = e.zh; }));

const sheets = [];
const formulaAt = {};   // 'sheet:row:column' -> formula text; the cell's computed value sits in data
const writes = [];     // every single-cell write, in order
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
        getFormulas() { return data.slice(row - 1, row - 1 + height).map((r, i) => [(formulaAt[`${name}:${row + i}:${column}`]) || '']); },
        setValue(value) { while (data.length < row) data.push([]); while (data[row - 1].length < column) data[row - 1].push(''); data[row - 1][column - 1] = value; delete formulaAt[`${name}:${row}:${column}`]; writes.push([row, column]); },
        setValues(values) {
          assert.fail('setValues must not be used: it would overwrite formula cells with their values'); values.forEach((r, i) => r.forEach((v, j) => { while (data[row - 1 + i].length < column + j) data[row - 1 + i].push(''); data[row - 1 + i][column - 1 + j] = v; })); },
      };
    },
  };
  sheets.push(sheet);
  return sheet;
}
const header = Array(21).fill('');
header[15] = '出場原因';
const row = code => { const r = Array(21).fill(''); r[0] = 't'; r[15] = code; return r; };
const project = makeSheet('project', header, [row('atr_trailing_stop'), row('現貨成交'), row('something_new'), row(''), row('spot_fill'), row('native_stop')]);
formulaAt['project:7:16'] = '=IF(A7="","","native_stop")';   // P7 shows a known code but is a formula: must survive
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
assert.equal(context.sheetValue('source', 'native_stop_reconciled'), '停損觸發或手動平倉（事後補記）');
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
assert.deepEqual(project.data.slice(1).map(r => r[15]), ['ATR 移動停損出場', '現貨成交', 'something_new', '', '現貨成交', 'native_stop']);
assert.deepEqual(writes, [[2, 16], [6, 16]]);                       // only the two matching plain cells were written
assert.equal(formulaAt['project:7:16'], '=IF(A7="","","native_stop")');   // the formula cell is untouched
assert.equal(other.data[1][1], 'native_stop');
assert.equal(audit.data[1][15], 'trend_reversal');
assert.deepEqual(JSON.parse(JSON.stringify(context.convertExitReasonsToChinese())), [{sheet: 'project', cells_changed: 0}]);   // idempotent


// ---- f-57: old correction notes in column U
assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('CORRECTION_REASON_ZH', context))), expectedCorrection);
const oldNote = '帳本更正 DUPLICATE_ENTRY_UNRECORDED：策略重複送單：訂單 28620601433 與帳本已記的訂單 28620601405 用同一個自訂編號 sk-6024ab7cfe0d4f668696ef271974109f，帳本漏記；以交易所成交重述整筆交易（一併納入同時段未記的訂單 28620601845）。（淨損益 -0.3272079900000262 → -0.436298870000035，數量 0.003 → 0.004）';
assert.equal(context.correctionNoteLabel(oldNote),
  '已更正（重複送單，帳本漏記）：策略重複送單：訂單 28620601433 與帳本已記的訂單 28620601405 用同一個自訂編號 sk-6024ab7cfe0d4f668696ef271974109f，帳本漏記；以交易所成交重述整筆交易（一併納入同時段未記的訂單 28620601845）。淨損益 -0.33 → -0.44 USDT；數量 0.003 → 0.004。');
assert.equal(context.correctionNoteLabel('帳本更正 UNRECORDED_FILL：x（淨損益 None → 1.005，數量 0.1 → 0.30000000000000004）'), '已更正（成交帳本沒記）：x。淨損益 未知 → 1.00 USDT；數量 0.1 → 0.3。');
const newNote = '已更正（成交帳本沒記）：x。淨損益 1.00 → 2.00 USDT；數量 0.1 → 0.2。';
assert.equal(context.correctionNoteLabel(newNote), newNote);                                  // already converted: unchanged
assert.equal(context.correctionNoteLabel('帳本更正 SOMETHING_NEW：x（淨損益 1 → 2，數量 3 → 4）'), '帳本更正 SOMETHING_NEW：x（淨損益 1 → 2，數量 3 → 4）');   // unknown code
assert.equal(context.correctionNoteLabel('手動備註'), '手動備註');
assert.equal(context.correctionNoteLabel(5), 5);

const noteHeader = Array(21).fill(''); noteHeader[20] = '備註';
const noteRow = text => { const r = Array(21).fill(''); r[0] = 't'; r[20] = text; return r; };
const notes = makeSheet('notes', noteHeader, [noteRow(oldNote), noteRow('手動備註'), noteRow('帳本更正 UNRECORDED_FILL：y（淨損益 1 → 2，數量 3 → 4）')]);
formulaAt['notes:4:21'] = '=IF(A4="","","帳本更正 UNRECORDED_FILL：y（淨損益 1 → 2，數量 3 → 4）")';   // a formula that evaluates to an old note: untouched
writes.length = 0;
const notesBefore = JSON.stringify(notes.data);
assert.deepEqual(JSON.parse(JSON.stringify(context.previewCorrectionNoteConversion())), [{sheet: 'notes', cells_changed: 1}]);
assert.equal(JSON.stringify(notes.data), notesBefore);
assert.deepEqual(JSON.parse(JSON.stringify(context.convertCorrectionNotesToChinese())), [{sheet: 'notes', cells_changed: 1}]);
assert.deepEqual(writes, [[2, 21]]);
assert.ok(notes.data[1][20].startsWith('已更正（重複送單，帳本漏記）：'));
assert.equal(notes.data[2][20], '手動備註');
assert.equal(formulaAt['notes:4:21'].startsWith('=IF('), true);
assert.deepEqual(JSON.parse(JSON.stringify(context.convertCorrectionNotesToChinese())), [{sheet: 'notes', cells_changed: 0}]);   // idempotent

console.log('apps_script_exit_reason_node_test: passed');
