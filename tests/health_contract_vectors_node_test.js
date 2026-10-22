// f-62: the page's table validation (scripts/health_panel_core.js validateTable) and the publisher's
// (trade_alerts.fleet_health.validate_health_table) must accept and refuse exactly the same tables.  Both sides read
// tests/golden/health_contract_vectors.json; tests/test_fleet_health.py runs the Python half.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const sandbox = {atob, Blob, DecompressionStream, TextDecoder, Uint8Array, Date, JSON, Object, Array, Math, Number, String, isNaN, console};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('scripts/health_panel_core.js', 'utf8'), sandbox, {filename: 'health_panel_core.js'});
const P = vm.runInContext('HealthPanel', sandbox);
const {cases, times} = JSON.parse(fs.readFileSync('tests/golden/health_contract_vectors.json', 'utf8'));

assert.ok(cases.length >= 30, 'the vector file should not shrink quietly');
assert.ok(cases.some(c => c.valid) && cases.some(c => !c.valid));
for (const c of cases) {
  const got = P.validateTable(c.table);
  assert.strictEqual(got.ok, c.valid, `${c.name}: page says ok=${got.ok} (${got.detail || ''}), vector says valid=${c.valid}`);
}
assert.ok(times.length >= 50 && times.some(t => t.valid) && times.some(t => !t.valid));
for (const t of times) {
  assert.strictEqual(!isNaN(P.parseIso(t.value)), t.valid, `time ${JSON.stringify(t.value)}: page disagrees with vector valid=${t.valid}`);
}
console.log(`health contract vectors: ${times.length} times and ${cases.length} cases agree with the page`);
