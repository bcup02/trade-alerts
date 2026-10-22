// f-45: the pure logic of the fleet-health panel (scripts/health_panel_core.js) -- parsing the cell and deciding what may be
// called healthy.  The page script and this test load the same file.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const zlib = require('zlib');

const sandbox = {atob, Blob, DecompressionStream, TextDecoder, Uint8Array, Date, JSON, Object, Array, Math, Number, String, isNaN, console};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('scripts/health_panel_core.js', 'utf8'), sandbox, {filename: 'health_panel_core.js'});
const P = vm.runInContext('HealthPanel', sandbox);
const golden = JSON.parse(fs.readFileSync('tests/golden/health_cell_real.json', 'utf8'));
const MIN = 60000;
const NOW = Date.parse('2026-10-22T07:55:00Z');

const gz = obj => 'HEALTHv1|' + zlib.gzipSync(Buffer.from(typeof obj === 'string' ? obj : JSON.stringify(obj)), {level: 9}).toString('base64') + '|HEALTHEND';
const row = (target, axis, value, severity, checkedAt) => ({target, axis, value, severity, checked_at: checkedAt});
const table = (over = {}) => ({schema: 'fleet-health-v1', generated_at: '2026-10-22T07:51:00Z', checked_at: '2026-10-22T07:50:05Z',
  readings: [row('momentum', 'ledger', 'RECONCILED', 'ok', '2026-10-22T07:45:14Z'), row('host', 'clock', 'OK', 'ok', '2026-10-22T07:50:00Z')], ...over});
const result = text => ({content: [{type: 'text', text}]});
const run = async (...fs_) => { for (const f of fs_) await f(); };
const plus = (iso, ms) => new Date(Date.parse(iso) + ms).toISOString().replace('.000Z', 'Z');

(async () => {
  // ---------- the cell ---------------------------------------------------------------------------------------------
  const cell = golden.real.cell;
  const b64 = cell.slice('HEALTHv1|'.length, -'|HEALTHEND'.length);
  assert.deepEqual(P.extractCell(cell), {ok: true, b64});
  assert.deepEqual(P.extractCell('| A1 | ' + cell + ' |\\n| B1 | other |'), {ok: true, b64});                      // inside a table view
  assert.deepEqual(P.extractCell(cell.replace(/\|/g, '\\|')), {ok: true, b64});                                 // the view escapes | [ ] _
  assert.deepEqual(P.extractCell('x HEALTHv1\\|' + b64 + '\\|HEALTHEND y'), {ok: true, b64});
  assert.deepEqual(P.extractCell('HEALTHv1|' + b64.slice(0, 100) + '\n  ' + b64.slice(100) + '|HEALTHEND'), {ok: true, b64});   // wrapped
  assert.equal(P.extractCell('nothing here').code, 'no_start');
  assert.equal(P.extractCell('HEALTHv1|' + b64.slice(0, 200) + '...').code, 'cut_off');                             // the connector cut the cell
  assert.equal(P.extractCell(cell.slice(0, -4)).code, 'cut_off');
  assert.equal(P.extractCell('HEALTHv1||HEALTHEND').code, 'empty');
  assert.equal(P.extractCell('HEALTHv1|' + 'A'.repeat(9000) + '|HEALTHEND').ok, true);
  assert.equal(P.extractCell('HEALTHv1|' + 'A'.repeat(9001) + '|HEALTHEND').code, 'too_large');
  assert.equal(P.extractCell('HEALTHv1|not base64!|HEALTHEND').code, 'not_base64');
  assert.equal(P.extractCell('HEALTHv1|ab=c|HEALTHEND').code, 'not_base64');
  for (const v of [null, undefined, '', 5, {}]) assert.equal(P.extractCell(v).code, 'no_text');
  // the first start and the first end after it win
  assert.equal(P.extractCell('HEALTHv1|AAAA|HEALTHEND HEALTHv1|BBBB|HEALTHEND').b64, 'AAAA');

  // textOfResult
  assert.equal(P.textOfResult({content: [{type: 'text', text: 'a'}, {type: 'image', data: 'x'}, {type: 'text', text: 'b'}]}), 'ab');
  assert.equal(P.textOfResult({content: [], payload: 'only payload'}), 'only payload');
  assert.equal(P.textOfResult({payload: {not: 'a string'}}), '');
  for (const v of [null, undefined, {}, {content: 'nope'}]) assert.equal(P.textOfResult(v), '');

  // ---------- decoding the golden cells (made by the Python publisher contract) ----------------------------------
  const real = await P.decodeTable(b64);
  assert.equal(real.ok, true);
  assert.equal(real.table.readings.length, 20);
  assert.equal(real.table.generatedAt, golden.generated_at);
  assert.equal(real.table.checkedAt, golden.poll_checked_at);
  assert.deepEqual(real.table.readings.map(r => [r.target, r.axis, r.value, r.severity, r.checkedAt]),
    golden.real.table.readings.map(r => [r.target, r.axis, r.value, r.severity, r.checked_at]));
  assert.ok(real.table.readings.every(r => r.checkedAtMs === Date.parse(r.checkedAt)));
  const withNull = await P.readResult(result('HEALTHv1 intro text ' + golden.with_null_time.cell + ' trailing'));
  assert.equal(withNull.ok, true);
  const nulls = withNull.table.readings.filter(r => r.checkedAt === null);
  assert.equal(nulls.length, 1);
  assert.deepEqual([nulls[0].target, nulls[0].axis, nulls[0].value, nulls[0].checkedAtMs], ['momentum', 'ledger', 'UNAVAILABLE', null]);

  // ---------- decoding failures ----------------------------------------------------------------------------------
  assert.equal((await P.readResult(result('HEALTHv1|' + Buffer.from('plain text, not gzip').toString('base64') + '|HEALTHEND'))).code, 'bad_gzip');
  assert.equal((await P.readResult(result(gz('this is not json')))).code, 'bad_json');
  assert.equal((await P.readResult(result(gz('[]')))).code, 'bad_schema');
  assert.equal((await P.readResult(result('HEALTHv1|' + zlib.gzipSync(Buffer.alloc(300000, 0x20)).toString('base64') + '|HEALTHEND'))).code, 'too_big');   // a gzip bomb
  assert.equal((await P.readResult(result(gz(Buffer.from([0xff, 0xfe, 0xfd]).toString('latin1'))))).ok, false);                    // not valid text
  assert.equal((await P.readResult(result(''))).code, 'no_text');
  assert.equal((await P.readResult(null)).code, 'no_text');
  const truncatedGzip = 'HEALTHv1|' + b64.slice(0, b64.length - 40) + '|HEALTHEND';                                    // cell cut inside the data
  assert.equal((await P.readResult(result(truncatedGzip))).ok, false);

  // ---------- validating the table ------------------------------------------------------------------------------
  assert.equal(P.validateTable(table()).ok, true);
  assert.equal(P.validateTable(table({readings: [row('a', 'b', 'c', 'ok', null)]})).ok, true);                        // null reading time (f-62)
  const invalid = {
    'extra member': {...table(), extra: 1},
    'missing member': (() => { const t = table(); delete t.checked_at; return t; })(),
    'wrong schema': table({schema: 'fleet-health-v2'}),
    'generated_at without zone': table({generated_at: '2026-10-22T07:51:00'}),
    'generated_at as a date only': table({generated_at: '2026-10-22'}),
    'generated_at not a string': table({generated_at: 1792655460}),
    'impossible calendar day': table({generated_at: '2026-02-30T00:00:00Z'}),
    'impossible month': table({checked_at: '2026-13-01T00:00:00Z'}),
    'readings empty': table({readings: []}),
    'readings not a list': table({readings: {}}),
    'too many readings': table({readings: Array.from({length: 101}, (_, i) => row('t' + i, 'a', 'v', 'ok', null))}),
    'reading with an extra member': table({readings: [{...row('a', 'b', 'c', 'ok', null), extra: 1}]}),
    'reading missing a member': table({readings: [{target: 'a', axis: 'b', value: 'c', severity: 'ok'}]}),
    'empty value': table({readings: [row('a', 'b', '', 'ok', null)]}),
    'numeric value': table({readings: [row('a', 'b', 3, 'ok', null)]}),
    'control character': table({readings: [row('a', 'b', 'x\u0007y', 'ok', null)]}),
    'line separator': table({readings: [row('a', 'b', 'x\u2028y', 'ok', null)]}),
    'too long text': table({readings: [row('a', 'b', 'v'.repeat(201), 'ok', null)]}),
    'reading time as a number': table({readings: [row('a', 'b', 'c', 'ok', 5)]}),
    'reading time not a time': table({readings: [row('a', 'b', 'c', 'ok', 'yesterday')]}),
    'reading time without zone': table({readings: [row('a', 'b', 'c', 'ok', '2026-10-22T07:45:14')]}),
    'a row that is not an object': table({readings: ['x']}),
    'not an object': [],
  };
  for (const [name, t] of Object.entries(invalid)) assert.equal(P.validateTable(t).ok, false, name);
  assert.equal(P.validateTable(null).ok, false);
  const exact200 = P.validateTable(table({readings: [row('a', 'b', 'v'.repeat(200), 'ok', null)]}));
  assert.equal(exact200.ok, true);
  const hostile = '<img src=x onerror=alert(1)>';
  const kept = P.validateTable(table({readings: [row('a', 'b', hostile, 'ok', null)]}));
  assert.equal(kept.ok, true);
  assert.equal(kept.table.readings[0].value, hostile);                                                              // data stays text, never altered
  const proto = P.validateTable(JSON.parse('{"__proto__": {"x": 1}, "schema": "fleet-health-v1", "generated_at": "2026-10-22T07:51:00Z", "checked_at": "2026-10-22T07:50:05Z", "readings": []}'));
  assert.equal(proto.ok, false);

  // ---------- what may be called healthy -----------------------------------------------------------------------
  const norm = async t => (await P.decodeTable(zlib.gzipSync(Buffer.from(JSON.stringify(t))).toString('base64'))).table;
  const at = (generated, checked, readings) => norm(table({generated_at: generated, checked_at: checked, readings}));
  const fresh = [row('momentum', 'ledger', 'RECONCILED', 'ok', '2026-10-22T07:45:14Z'), row('host', 'clock', 'OK', 'ok', '2026-10-22T07:50:00Z')];

  let a = P.assess(await at('2026-10-22T07:51:00Z', '2026-10-22T07:50:05Z', fresh), NOW);
  assert.equal(a.level, 'ok');
  assert.deepEqual(a.rows.map(r => r.display), ['ok', 'ok']);
  assert.equal(a.publishAgeMs, 4 * MIN);
  assert.equal(a.pollAgeMs, NOW - Date.parse('2026-10-22T07:50:05Z'));
  assert.equal(a.rows[0].ageMs, 9 * MIN + 46000);

  // one alert, one warn, an unknown severity counts as warn
  a = P.assess(await at('2026-10-22T07:51:00Z', '2026-10-22T07:50:05Z', [...fresh, row('seykota', 'ledger', 'DIVERGED', 'alert', '2026-10-22T07:45:15Z')]), NOW);
  assert.equal(a.level, 'alert'); assert.equal(a.counts.alert, 1);
  a = P.assess(await at('2026-10-22T07:51:00Z', '2026-10-22T07:50:05Z', [...fresh, row('seykota', 'ledger', 'PENDING', 'warn', '2026-10-22T07:45:15Z')]), NOW);
  assert.equal(a.level, 'warn');
  a = P.assess(await at('2026-10-22T07:51:00Z', '2026-10-22T07:50:05Z', [...fresh, row('x', 'y', 'MYSTERY', 'weird', '2026-10-22T07:45:15Z')]), NOW);
  assert.equal(a.level, 'warn'); assert.equal(P.severityClass('weird'), 'warn');

  // publisher stopped: generated_at older than 25 minutes -- strictly more
  const allOk = fresh;
  const generatedAgo = ms => plus('2026-10-22T07:55:00Z', -ms);
  assert.equal(P.assess(await at(generatedAgo(25 * MIN), '2026-10-22T07:50:05Z', allOk), NOW).level, 'ok');
  a = P.assess(await at(generatedAgo(25 * MIN + 1000), '2026-10-22T07:50:05Z', allOk), NOW);
  assert.equal(a.level, 'publish_stale');
  assert.deepEqual(a.rows.map(r => r.display), ['stale', 'stale']);                                               // all-green rows are greyed, never green
  assert.equal(a.publishStale, true); assert.equal(a.tableStale, true);
  // even with an alert inside, a stale table reports the staleness first and greys every row
  a = P.assess(await at(generatedAgo(60 * MIN), '2026-10-22T07:50:05Z', [...allOk, row('seykota', 'ledger', 'DIVERGED', 'alert', '2026-10-22T07:45:15Z')]), NOW);
  assert.equal(a.level, 'publish_stale'); assert.ok(a.rows.every(r => r.display === 'stale'));

  // poller stopped: publisher fine, checked_at older than 45 minutes
  const checkedAgo = ms => plus('2026-10-22T07:55:00Z', -ms);
  assert.equal(P.assess(await at(generatedAgo(MIN), checkedAgo(45 * MIN), allOk), NOW).level, 'ok');
  a = P.assess(await at(generatedAgo(MIN), checkedAgo(45 * MIN + 1000), allOk), NOW);
  assert.equal(a.level, 'poll_stale'); assert.ok(a.rows.every(r => r.display === 'stale'));
  // both stale: the publisher is reported (it is the more basic failure)
  assert.equal(P.assess(await at(generatedAgo(40 * MIN), checkedAgo(60 * MIN), allOk), NOW).level, 'publish_stale');

  // one reading older than 45 minutes while the table is fresh
  a = P.assess(await at(generatedAgo(MIN), checkedAgo(MIN), [row('a', 'b', 'OK', 'ok', checkedAgo(45 * MIN)), row('c', 'd', 'OK', 'ok', checkedAgo(45 * MIN + 1000))]), NOW);
  assert.deepEqual(a.rows.map(r => r.display), ['ok', 'stale']);
  assert.equal(a.level, 'warn'); assert.equal(a.counts.stale, 1);

  // clock: a table from the future (more than 5 minutes) cannot be judged
  assert.equal(P.assess(await at(plus('2026-10-22T07:55:00Z', 5 * MIN), '2026-10-22T07:50:05Z', allOk), NOW).level, 'ok');
  a = P.assess(await at(plus('2026-10-22T07:55:00Z', 5 * MIN + 1000), '2026-10-22T07:50:05Z', allOk), NOW);
  assert.equal(a.level, 'clock'); assert.ok(a.rows.every(r => r.display === 'stale'));
  assert.equal(P.assess(await at('2026-10-22T07:51:00Z', plus('2026-10-22T07:55:00Z', 6 * MIN), allOk), NOW).level, 'clock');
  assert.equal(P.assess(await at(plus('2026-10-22T07:55:00Z', 6 * MIN), generatedAgo(40 * MIN), allOk), NOW).level, 'clock');   // clock before staleness

  // no reading time (f-62): never green, never "stale" either
  a = P.assess(await at(generatedAgo(MIN), checkedAgo(MIN), [row('a', 'b', 'UNAVAILABLE', 'warn', null), ...allOk]), NOW);
  assert.deepEqual(a.rows.map(r => r.display), ['notime', 'ok', 'ok']);
  assert.equal(a.rows[0].noTime, true); assert.equal(a.rows[0].ageMs, null); assert.equal(a.level, 'warn'); assert.equal(a.counts.notime, 1);
  a = P.assess(await at(generatedAgo(MIN), checkedAgo(MIN), [row('a', 'b', 'OK', 'ok', null)]), NOW);          // even an "ok" value without a time is not green
  assert.equal(a.level, 'warn'); assert.equal(a.rows[0].display, 'notime');
  a = P.assess(await at(generatedAgo(MIN), checkedAgo(MIN), [row('a', 'b', 'UNAVAILABLE', 'warn', null), row('c', 'd', 'DIVERGED', 'alert', checkedAgo(MIN))]), NOW);
  assert.equal(a.level, 'alert');

  // custom limits
  a = P.assess(await at(generatedAgo(10 * MIN), checkedAgo(MIN), allOk), NOW, {publishStaleMs: 5 * MIN});
  assert.equal(a.level, 'publish_stale');
  assert.equal(P.assess(await at(generatedAgo(10 * MIN), checkedAgo(MIN), allOk), NOW, {publishStaleMs: 'x'}).level, 'ok');   // a bad option falls back to the default

  // the golden snapshots, end to end, at three moments
  const goldenAt = async (cellText, nowIso) => P.assess((await P.readResult(result(cellText))).table, Date.parse(nowIso));
  a = await goldenAt(golden.real.cell, '2026-10-22T07:55:00Z');
  assert.equal(a.level, 'alert'); assert.equal(a.counts.alert, 2);                                               // seykota ledger, btc-competition google
  assert.equal(a.rows.filter(r => r.axis === 'units').length, 3);
  a = await goldenAt(golden.real.cell, '2026-10-22T08:20:00Z');                                                   // 29 minutes after generated_at
  assert.equal(a.level, 'publish_stale'); assert.ok(a.rows.every(r => r.display === 'stale'));
  a = await goldenAt(golden.with_null_time.cell, '2026-10-22T07:55:00Z');
  assert.equal(a.counts.notime, 1); assert.equal(a.level, 'alert');

  // ---------- words ---------------------------------------------------------------------------------------------
  assert.equal(P.formatAge(0), '剛剛'); assert.equal(P.formatAge(59000), '剛剛'); assert.equal(P.formatAge(-5 * MIN), '剛剛');
  assert.equal(P.formatAge(MIN), '1 分鐘前'); assert.equal(P.formatAge(59 * MIN + 59000), '59 分鐘前');
  assert.equal(P.formatAge(60 * MIN), '1 小時前'); assert.equal(P.formatAge(95 * MIN), '1 小時 35 分鐘前');
  assert.equal(P.formatAge(47 * 60 * MIN + 59 * MIN), '47 小時 59 分鐘前'); assert.equal(P.formatAge(48 * 60 * MIN), '2 天前');
  assert.equal(P.formatAge(null), '不明'); assert.equal(P.formatAge(NaN), '不明'); assert.equal(P.ageWithoutAgo(30 * MIN), '30 分鐘');
  assert.equal(P.formatTaipei(Date.parse('2026-10-22T07:45:14Z')), '10/22 15:45');
  assert.equal(P.formatTaipei(Date.parse('2026-12-31T17:00:00Z')), '01/01 01:00');                                 // Taipei is already tomorrow
  assert.equal(P.formatTaipei(Date.parse('2026-10-22T15:59:59Z')), '10/22 23:59');
  assert.equal(P.formatTaipei(Date.parse('2026-10-22T16:00:00Z')), '10/23 00:00');

  const text = level => P.describeLevel({level, counts: {ok: 1, warn: 2, alert: 1, stale: 3, notime: 1}, publishAgeMs: 30 * MIN, pollAgeMs: 50 * MIN, limits: P.DEFAULTS});
  assert.equal(text('ok').title, '全部正常'); assert.ok(text('ok').detail.includes('沒有異常'));
  assert.ok(text('publish_stale').detail.includes('30 分鐘前') && text('publish_stale').detail.includes('發布單元'));
  assert.ok(text('poll_stale').detail.includes('50 分鐘前') && text('poll_stale').detail.includes('輪詢'));
  assert.ok(text('clock').detail.includes('5 分鐘') && !text('clock').title.includes('正常'));
  assert.ok(text('alert').detail.startsWith('1 項異常')); assert.ok(text('warn').detail.includes('2 項要注意'));
  for (const lvl of ['publish_stale', 'poll_stale', 'clock', 'alert', 'warn']) assert.ok(!text(lvl).title.includes('全部正常'), lvl);

  // ---------- connector failures ---------------------------------------------------------------------------------
  const kinds = {approval_required: 'approval', not_in_manifest: 'denied', consent_required: 'denied', server_not_connected: 'reconnect',
    needs_reauth: 'reconnect', selection_required: 'reconnect', blocked_by_policy: 'denied', not_granted: 'no_mcp', capability_disabled: 'no_mcp',
    capability_removed: 'no_mcp', server_unavailable: 'transient', upstream_error: 'transient', rate_limited: 'transient', tool_error: 'tool'};
  for (const [code, kind] of Object.entries(kinds)) assert.equal(P.classifyError({code}).kind, kind, code);
  assert.equal(P.classifyError({code: 'approval_required'}).button, '允許並讀取');
  assert.equal(P.classifyError({code: 'approval_required'}).retract, true);
  assert.equal(P.classifyError({code: 'server_unavailable'}).retract, false);                                    // transient: keep the last good table
  assert.equal(P.classifyError({code: 'needs_reauth'}).retract, true);                                          // a denial: drop what was shown
  assert.equal(P.classifyError({code: 'tool_error', message: 'm'.repeat(500)}).text.length < 260, true);
  assert.equal(P.classifyError({code: 'tool_error'}).text.includes('沒有說明'), true);
  for (const v of [undefined, null, {}, {code: 'brand_new_code'}, 'oops']) assert.equal(P.classifyError(v).kind, 'other');
  assert.equal(P.classifyError({code: 'brand_new_code'}).text, '讀取失敗（brand_new_code）。');
  for (const code of ['no_text', 'no_start', 'cut_off', 'empty', 'too_large', 'not_base64', 'no_gzip', 'bad_gzip', 'too_big', 'bad_json', 'bad_schema']) {
    assert.ok(P.describeFailure({code}).text.length > 5, code);
  }
  assert.equal(P.describeFailure({code: 'bad_schema', detail: 'members'}).detail, 'members');
  assert.equal(P.describeFailure(null).text, '讀數格讀不出來。');

  // ---------- which sources load -----------------------------------------------------------------------------------
  const id = 'a'.repeat(33);
  assert.equal(P.planSource({file_id: null}, true), 'unconfigured');
  assert.equal(P.planSource({}, true), 'unconfigured');
  assert.equal(P.planSource(null, true), 'unconfigured');
  assert.equal(P.planSource({file_id: 'short'}, true), 'unconfigured');
  assert.equal(P.planSource({file_id: 'has space ' + 'a'.repeat(30)}, true), 'unconfigured');
  assert.equal(P.planSource({file_id: id}, false), 'no_mcp');
  assert.equal(P.planSource({file_id: id}, true), 'load');

  console.log('health_panel_node_test ok');
})().catch(err => { console.error(err); process.exit(1); });
