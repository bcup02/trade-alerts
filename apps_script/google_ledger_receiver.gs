/**
 * Unified Google ledger receiver — reference source only.
 *
 * This is the CANONICAL source for the shared Apps Script Web App bound to the
 * "AI自動程式交易紀錄" spreadsheet. One deployment serves every project tab
 * (my-crypto-bot / ed-seykota / MarkMinervini / mexc-4h-momentum-trailing-stop);
 * the payload's sheet_name picks the tab. It handles two explicitly separated
 * protocols:
 *   1. legacy payloads without schema_version — SHARED_SECRET + append /
 *      update_by_trade_id / update_by_key / list_by_sheet (read-only);
 *   2. google-ledger-projection-v2 — per-source HMAC + provenance.
 *
 * Deployment, Script Properties, source registration, and any Google data
 * mutation require separate explicit approval. No actual secret belongs in this
 * source file, Git, command lines, logs, or an outbox.
 *
 * --- Legacy A~U column schema (all tabs share it) ---
 * A trade_id | B execution_mode | C symbol | D side | E entry_time |
 * F exit_time | G entry_price | H exit_price | I volume | J leverage |
 * K entry_fee | L exit_fee | M gross_pnl | N net_pnl | O return_on_margin |
 * P source | Q entry_order_id | R exit_order_id | S stop_plan_order_id |
 * T exit_anomaly | U notes
 * (2026-08-22: T and U were swapped across all tabs — T was notes, now it is
 * exit_anomaly. update_by_trade_id locates by column letter, not by semantics,
 * so callers just send the right letters.)
 * A cell value that is a purely-numeric string of 16+ digits (order ids) is
 * forced to text format so Sheets does not lose precision.
 *
 * --- Redeploy (manual, whole-endpoint) ---
 * Paste this whole file into the spreadsheet's Apps Script editor (Extensions ->
 * Apps Script) -> Manage deployments -> edit -> new version. The Web App URL is
 * unchanged. Affects all tabs. Script Properties: SHARED_SECRET (legacy) and
 * GOOGLE_LEDGER_V2_SOURCES (v2 registry) are unchanged.
 *
 * --- Caller transport caveat (legacy) ---
 * An Apps Script Web App answers a POST with a 302 to
 * script.googleusercontent.com/...; the redirect target is occasionally flaky
 * (404 / empty body) even on a healthy deployment. Legacy callers should follow
 * the redirect manually (POST with allow_redirects=False, then GET Location) AND
 * add a bounded exponential-backoff retry. Sheet sync is best-effort: a failure
 * is logged, never blocks trading.
 *
 * --- list_by_sheet contract (2026-08-31) ---
 * Read-only. Request:
 *   {"secret":"...", "sheet_name":"...", "action":"list_by_sheet",
 *    "trade_ids":["abc","def"]}   // trade_ids optional
 * Response:
 *   {"ok":true, "sheet":"...", "header":[<row 1>...],
 *    "rows":[{"row":14, "values":[<A>,<B>,...]}, ...], "row_count":N}
 * trade_ids: omit the key (or pass a non-array) -> no filter, all data rows;
 * a non-empty array -> only rows whose column-A value is in it; an EMPTY array
 * -> the empty set (rows:[], row_count:0; ok:true, not an error). No data rows
 * (header only / blank) -> rows:[], row_count:0.
 * Date-formatted cells come back as ISO 8601 UTC strings (getValues() -> JS Date
 * -> Date.toJSON() via JSON.stringify), not sheet-local text or a timestamp; the
 * caller parses + converts, the script does not normalize.
 */

const V2_SCHEMA = 'google-ledger-projection-v2';
const V2_AUDIT_SHEET = 'Google_Provenance_Audit';
const OPEN_FIELDS = ['trade_id', 'execution_mode', 'symbol', 'side', 'entry_time', 'entry_price', 'volume', 'leverage', 'entry_fee', 'entry_order_id'];
const OPEN_REQUIRED_FIELDS = ['trade_id', 'execution_mode', 'symbol', 'side', 'entry_time', 'entry_price', 'volume', 'leverage', 'entry_fee'];
const CLOSE_FIELDS = ['trade_id', 'exit_time', 'entry_price', 'exit_price', 'entry_volume', 'exit_volume', 'leverage', 'entry_fee', 'exit_fee', 'gross_pnl', 'net_pnl', 'return_on_margin', 'source', 'exit_order_id', 'stop_plan_order_id', 'exit_anomaly', 'exit_price_is_confirmed'];
const CLOSE_REQUIRED_FIELDS = ['trade_id', 'exit_time', 'entry_price', 'exit_price', 'entry_volume', 'exit_volume', 'leverage', 'entry_fee', 'exit_fee', 'gross_pnl', 'net_pnl', 'return_on_margin', 'source'];
const OPEN_COLUMN_MAP = {trade_id: 'A', execution_mode: 'B', symbol: 'C', side: 'D', entry_time: 'E', entry_price: 'G', volume: 'I', leverage: 'J', entry_fee: 'K', entry_order_id: 'Q'};
const CLOSE_COLUMN_MAP = {exit_time: 'F', exit_price: 'H', entry_fee: 'K', exit_fee: 'L', gross_pnl: 'M', net_pnl: 'N', return_on_margin: 'O', source: 'P', exit_order_id: 'R', stop_plan_order_id: 'S', exit_anomaly: 'T'};
const NUMERIC_PROJECTION_FIELDS = new Set(['entry_price', 'exit_price', 'volume', 'entry_volume', 'exit_volume', 'leverage', 'entry_fee', 'exit_fee', 'gross_pnl', 'net_pnl', 'return_on_margin']);

function doPost(e) {
  try {
    return jsonOut(routeRequest(JSON.parse(e.postData.contents)));
  } catch (err) {
    return jsonOut({ok: false, error: 'malformed_request'});
  }
}

function routeRequest(data) {
  if (!data || typeof data !== 'object') return {ok: false, error: 'malformed_request'};
  if (data.schema_version === V2_SCHEMA) return handleV2(data);
  // A request claiming any other version must never be interpreted as legacy.
  if (Object.prototype.hasOwnProperty.call(data, 'schema_version')) return {ok: false, error: 'unsupported_schema'};
  return handleLegacy(data);
}

// ---- Legacy compatibility handler: preserve current behavior until retirement. ----

function handleLegacy(data) {
  const expectedRaw = PropertiesService.getScriptProperties().getProperty('SHARED_SECRET');
  const expected = expectedRaw ? expectedRaw.trim() : '';
  const received = (data.secret || '').trim();
  if (!expected || received !== expected) return {ok: false, error: 'unauthorized', debug: {expected_len: expected.length, received_len: received.length}};

  const sheetName = data.sheet_name;
  if (!sheetName) return {ok: false, error: 'missing sheet_name'};
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  if (!sheet) return {ok: false, error: 'sheet not found: ' + sheetName};

  if (data.action === 'update_by_trade_id') return handleLegacyUpdateByTradeId(sheet, sheetName, data);
  if (data.action === 'update_by_key') return handleLegacyUpdateByKey(sheet, sheetName, data);
  if (data.action === 'list_by_sheet') return handleLegacyListBySheet(sheet, sheetName, data);
  return handleLegacyAppend(sheet, sheetName, data);
}

// Read-only: return a tab's data rows so a three-way reconcile tool can compare
// the local JSONL ledger against the sheet. No writes, no new rows, no cell or
// format changes. Auth is the SHARED_SECRET check already done in handleLegacy.
// See the list_by_sheet contract in the file header.
function handleLegacyListBySheet(sheet, sheetName, data) {
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return {ok: true, sheet: sheetName, header: [], rows: [], row_count: 0};
  const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const dataValues = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
  let tradeIdFilter = null;
  if (Array.isArray(data.trade_ids)) {
    tradeIdFilter = {};
    data.trade_ids.forEach(id => { tradeIdFilter[String(id)] = true; });
  }
  const rows = [];
  for (let i = 0; i < dataValues.length; i++) {
    // Column A is stringified before comparison, matching the rest of this
    // endpoint's "do not trust the cell type" stance.
    if (tradeIdFilter && !tradeIdFilter[String(dataValues[i][0])]) continue;
    rows.push({row: i + 2, values: dataValues[i]});
  }
  return {ok: true, sheet: sheetName, header: header, rows: rows, row_count: rows.length};
}

function handleLegacyAppend(sheet, sheetName, data) {
  const common = data.common || {};
  if (common.trade_id) {
    const existing = findTradeRows(sheet, common.trade_id);
    // Legacy protocol compatibility: the deployed receiver treats the first
    // matching row as the original successful append, even if historic data
    // already contains duplicates. Only v2 is allowed to fail closed here.
    if (existing.length >= 1) {
      return {ok: true, row: existing[0], sheet: sheetName, note: 'duplicate trade_id on append, treated as an idempotent retry — no new row written'};
    }
  }
  const values = [
    common.trade_id, common.execution_mode, common.symbol, common.side,
    common.entry_time, common.exit_time, common.entry_price, common.exit_price,
    common.volume, common.leverage, common.entry_fee, common.exit_fee,
    common.gross_pnl, common.net_pnl, common.return_on_margin, common.source,
    common.entry_order_id, common.exit_order_id, common.stop_plan_order_id,
    common.exit_anomaly, common.notes,
  ].concat(Array.isArray(data.extra) ? data.extra : []).map(value => value === undefined || value === null ? '' : value);
  const row = sheet.getLastRow() + 1;
  const range = sheet.getRange(row, 1, 1, values.length);
  values.forEach((value, index) => {
    if (typeof value === 'string' && /^[0-9]{16,}$/.test(value)) range.getCell(1, index + 1).setNumberFormat('@');
  });
  range.setValues([values]);
  return {ok: true, row: row, sheet: sheetName};
}

function handleLegacyUpdateByTradeId(sheet, sheetName, data) {
  const tradeId = data.trade_id;
  if (!tradeId) return {ok: false, error: 'missing trade_id'};
  const updates = data.updates || {};
  const keys = Object.keys(updates);
  if (keys.length === 0) return {ok: false, error: 'empty updates'};
  const last = sheet.getLastRow();
  if (last < 2) return {ok: false, error: 'trade_id not found (sheet has no data rows): ' + tradeId};
  // Legacy protocol compatibility: update the first matching historic row.
  const matches = findTradeRows(sheet, tradeId);
  if (matches.length === 0) return {ok: false, error: 'trade_id not found: ' + tradeId, sheet: sheetName};
  const row = matches[0];
  const updatedColumns = [];
  keys.forEach(letter => {
    const column = columnIndex(letter);
    if (!column) return;
    const value = updates[letter];
    const cell = sheet.getRange(row, column);
    cell.setValue(value === undefined || value === null ? '' : value);
    if (typeof value === 'string' && /^[0-9]{16,}$/.test(value)) cell.setNumberFormat('@');
    updatedColumns.push(letter);
  });
  return {ok: true, row: row, sheet: sheetName, updated_columns: updatedColumns};
}

function handleLegacyUpdateByKey(sheet, sheetName, data) {
  const keyColumnLetter = data.key_column;
  if (!keyColumnLetter) return {ok: false, error: 'missing key_column'};
  const column = columnIndex(keyColumnLetter);
  if (!column) return {ok: false, error: 'invalid key_column: ' + keyColumnLetter};
  if (data.key_value === undefined || data.key_value === null || data.key_value === '') return {ok: false, error: 'missing key_value'};
  const updates = data.updates || {};
  const keys = Object.keys(updates);
  if (keys.length === 0) return {ok: false, error: 'empty updates'};
  const last = sheet.getLastRow();
  if (last < 2) return {ok: false, error: 'key_value not found (sheet has no data rows): ' + data.key_value};
  const values = sheet.getRange(2, column, last - 1, 1).getValues();
  const index = values.findIndex(value => String(value[0]) === String(data.key_value));
  if (index < 0) return {ok: false, error: 'key_value not found: ' + data.key_value};
  const row = index + 2;
  const updatedColumns = [];
  keys.forEach(letter => {
    const updateColumn = columnIndex(letter);
    if (!updateColumn) return;
    const value = updates[letter];
    const cell = sheet.getRange(row, updateColumn);
    cell.setValue(value === undefined || value === null ? '' : value);
    if (typeof value === 'string' && /^[0-9]{16,}$/.test(value)) cell.setNumberFormat('@');
    updatedColumns.push(letter);
  });
  return {ok: true, row: row, sheet: sheetName, updated_columns: updatedColumns};
}

// ---- V2 handler: ledger-backed, source-scoped, and fail-closed. ----

function handleV2(data) {
  if (!['append_open_v2', 'update_close_v2', 'read_audit_v2', 'read_reconciliation_v2', 'quarantine_v2'].includes(data.action)) return {ok: false, error: 'unsupported_action'};
  const source = sourceRegistration(data.source_id);
  if (!source || data.project_id !== source.project_id || data.sheet_name !== source.sheet_name) return {ok: false, error: 'source_not_allowed'};
  if (!verifySignature(data, source.hmac_secret)) return {ok: false, error: 'signature_invalid'};
  if (!isRecentIso(data.issued_at) || !isUuid(data.request_id)) return {ok: false, error: 'request_not_fresh'};
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(source.sheet_name);
  if (!sheet) return {ok: false, error: 'sheet_not_found'};
  if (data.action === 'read_reconciliation_v2') return readReconciliationInventory(sheet, data);
  if (!validProvenance(data.provenance, data)) return {ok: false, error: 'provenance_invalid'};
  const projection = data.projection || {};
  if (data.action === 'append_open_v2') return appendOpen(sheet, data, projection);
  if (data.action === 'update_close_v2') return updateClose(sheet, data, projection);
  if (data.action === 'read_audit_v2') return readAudit(data);
  return quarantineOnlyWithExplicitDeploymentFlag(data);
}

function sourceRegistration(sourceId) {
  if (typeof sourceId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(sourceId)) return null;
  const raw = PropertiesService.getScriptProperties().getProperty('GOOGLE_LEDGER_V2_SOURCES');
  if (!raw) return null;
  try {
    const registry = JSON.parse(raw);
    const source = registry[sourceId];
    return source && typeof source.hmac_secret === 'string' && source.hmac_secret && source.project_id && source.sheet_name ? source : null;
  } catch (err) {
    return null;
  }
}

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
}

function hmacHex(text, secret) {
  const bytes = Utilities.computeHmacSha256Signature(text, secret, Utilities.Charset.UTF_8);
  return bytes.map(byte => ('0' + (byte & 0xff).toString(16)).slice(-2)).join('');
}

function verifySignature(data, secret) {
  if (typeof data.signature !== 'string' || !/^[0-9a-f]{64}$/.test(data.signature)) return false;
  const unsigned = Object.assign({}, data);
  delete unsigned.signature;
  return constantTimeEqual(hmacHex(canonicalJson(unsigned), secret), data.signature);
}

function constantTimeEqual(left, right) {
  if (left.length !== right.length) return false;
  let result = 0;
  for (let i = 0; i < left.length; i++) result |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return result === 0;
}

function validProvenance(provenance, data) {
  if (!provenance || typeof provenance !== 'object') return false;
  const required = ['project_id', 'trade_id', 'event_type', 'ledger_event_digest', 'payload_digest', 'request_id', 'issued_at', 'source_id', 'schema_version'];
  if (required.some(key => typeof provenance[key] !== 'string' || provenance[key] === '')) return false;
  if (provenance.project_id !== data.project_id || provenance.source_id !== data.source_id || provenance.request_id !== data.request_id || provenance.issued_at !== data.issued_at || provenance.schema_version !== V2_SCHEMA) return false;
  if (!['trade_open', 'trade_close'].includes(provenance.event_type)) return false;
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(provenance.trade_id)) return false;
  if (!/^[0-9a-f]{64}$/.test(provenance.ledger_event_digest) || !/^[0-9a-f]{64}$/.test(provenance.payload_digest)) return false;
  if (sha256Hex(canonicalJson(data.projection || {})) !== provenance.payload_digest) return false;
  return true;
}

function sha256Hex(text) {
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8);
  return bytes.map(byte => ('0' + (byte & 0xff).toString(16)).slice(-2)).join('');
}

function isRecentIso(value) {
  const parsed = new Date(value);
  return typeof value === 'string' && !isNaN(parsed.getTime()) && Math.abs(Date.now() - parsed.getTime()) <= 5 * 60 * 1000;
}

function isUuid(value) {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function validateProjection(projection, allowed, required, tradeId) {
  if (!projection || typeof projection !== 'object') return false;
  if (projection.trade_id !== tradeId) return false;
  if (!required.every(key => Object.prototype.hasOwnProperty.call(projection, key))) return false;
  return Object.keys(projection).every(key => allowed.includes(key));
}

function appendOpen(sheet, data, projection) {
  if (data.provenance.event_type !== 'trade_open' || !validateProjection(projection, OPEN_FIELDS, OPEN_REQUIRED_FIELDS, data.provenance.trade_id)) return rejectAndAudit(data, 'open_projection_invalid');
  const existing = findTradeRows(sheet, data.provenance.trade_id);
  if (existing.length > 1) return rejectAndAudit(data, 'duplicate_trade_id');
  if (existing.length === 1) {
    const prior = auditByTradeId(data.project_id, data.provenance.trade_id, 'trade_open');
    if (prior.length === 1 && prior[0].payload_digest === data.provenance.payload_digest) return {ok: true, row: existing[0], idempotent: true};
    return rejectAndAudit(data, 'trade_id_conflict');
  }
  const row = sheet.getLastRow() + 1;
  writeProjection(sheet, row, projection, OPEN_COLUMN_MAP);
  writeAudit(data, row, 'CONFIRMED');
  return {ok: true, row: row, provenance_status: 'CONFIRMED'};
}

function updateClose(sheet, data, projection) {
  if (data.provenance.event_type !== 'trade_close' || !validateProjection(projection, CLOSE_FIELDS, CLOSE_REQUIRED_FIELDS, data.provenance.trade_id)) return rejectAndAudit(data, 'close_projection_invalid');
  const existing = findTradeRows(sheet, data.provenance.trade_id);
  if (existing.length !== 1) return rejectAndAudit(data, existing.length === 0 ? 'trade_id_not_found' : 'duplicate_trade_id');
  const prior = auditByTradeId(data.project_id, data.provenance.trade_id, 'trade_close');
  if (prior.length === 1 && prior[0].payload_digest === data.provenance.payload_digest) return {ok: true, row: existing[0], idempotent: true};
  if (prior.length > 0) return rejectAndAudit(data, 'trade_close_conflict');
  writeProjection(sheet, existing[0], projection, CLOSE_COLUMN_MAP);
  writeAudit(data, existing[0], 'CONFIRMED');
  return {ok: true, row: existing[0], provenance_status: 'CONFIRMED'};
}

function findTradeRows(sheet, tradeId) {
  const last = sheet.getLastRow();
  if (last < 2) return [];
  const values = sheet.getRange(2, 1, last - 1, 1).getValues();
  const result = [];
  values.forEach((row, index) => { if (String(row[0]) === String(tradeId)) result.push(index + 2); });
  return result;
}

function writeProjection(sheet, row, projection, mapping) {
  Object.keys(mapping).forEach(key => {
    if (Object.prototype.hasOwnProperty.call(projection, key)) {
      const cell = sheet.getRange(row, columnIndex(mapping[key]));
      const value = sheetValue(key, projection[key]);
      if (typeof value === 'string' && /^[0-9]{16,}$/.test(value)) cell.setNumberFormat('@');
      cell.setValue(value);
    }
  });
}

function sheetValue(key, value) {
  if (value === null) return '';
  if (!NUMERIC_PROJECTION_FIELDS.has(key)) return value;
  if (typeof value !== 'string' || !/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value)) throw new Error('invalid_numeric_projection');
  const numeric = Number(value);
  if (!isFinite(numeric)) throw new Error('invalid_numeric_projection');
  return numeric;
}

function columnIndex(letter) {
  if (typeof letter !== 'string' || !/^[A-Z]+$/.test(letter)) return null;
  return letter.split('').reduce((result, character) => result * 26 + character.charCodeAt(0) - 64, 0);
}

function auditSheet(createIfMissing) {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = book.getSheetByName(V2_AUDIT_SHEET);
  if (!sheet && createIfMissing) {
    sheet = book.insertSheet(V2_AUDIT_SHEET);
    sheet.appendRow(['recorded_at', 'project_id', 'trade_id', 'event_type', 'request_id', 'ledger_event_digest', 'payload_digest', 'source_id', 'row', 'status', 'reason']);
  }
  return sheet;
}

function writeAudit(data, row, status, reason) {
  auditSheet(true).appendRow([new Date().toISOString(), data.project_id, data.provenance.trade_id, data.provenance.event_type, data.request_id, data.provenance.ledger_event_digest, data.provenance.payload_digest, data.source_id, row || '', status, reason || '']);
}

function auditByTradeId(projectId, tradeId, eventType) {
  const sheet = auditSheet(false);
  if (!sheet || sheet.getLastRow() < 2) return [];
  return sheet.getRange(2, 1, sheet.getLastRow() - 1, 11).getValues().filter(row => row[1] === projectId && row[2] === tradeId && row[3] === eventType).map(row => ({payload_digest: row[6], status: row[9], reason: row[10]}));
}

function readAudit(data) {
  const rows = auditByTradeId(data.project_id, data.provenance.trade_id, data.provenance.event_type);
  return {ok: true, audit: rows};
}

function readReconciliationInventory(sheet, data) {
  if (!data.query || data.query.kind !== 'source_projection_inventory_v1') return {ok: false, error: 'reconciliation_query_invalid'};
  const last = sheet.getLastRow();
  const rows = last < 2 ? [] : sheet.getRange(2, 1, last - 1, 1).getValues();
  const audit = auditSheet(false);
  const auditRows = !audit || audit.getLastRow() < 2 ? [] : audit.getRange(2, 1, audit.getLastRow() - 1, 11).getValues();
  const byTrade = {};
  auditRows.forEach(row => {
    if (row[1] !== data.project_id || row[7] !== data.source_id) return;
    const tradeId = String(row[2]);
    if (!byTrade[tradeId]) byTrade[tradeId] = {trade_id: tradeId, audit: []};
    byTrade[tradeId].audit.push({event_type: row[3], payload_digest: row[6], status: row[9], reason: row[10]});
  });
  rows.forEach(row => {
    const tradeId = String(row[0]);
    if (!tradeId) return;
    if (!byTrade[tradeId]) byTrade[tradeId] = {trade_id: tradeId, audit: []};
    byTrade[tradeId].google_row_count = (byTrade[tradeId].google_row_count || 0) + 1;
  });
  return {ok: true, items: Object.keys(byTrade).sort().map(key => byTrade[key])};
}

function rejectAndAudit(data, reason) {
  writeAudit(data, null, 'REJECTED', reason);
  return {ok: false, error: reason};
}

function quarantineOnlyWithExplicitDeploymentFlag(data) {
  writeAudit(data, null, 'REJECTED', 'quarantine_not_enabled');
  return {ok: false, error: 'quarantine_not_enabled'};
}

function jsonOut(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}
