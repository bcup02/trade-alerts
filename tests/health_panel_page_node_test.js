// f-45: the health panel as it runs inside the generated rollout register page, driven through a minimal fake DOM and a fake
// `claude.use("mcp")`.  Checks the whole path (watch -> cell -> table -> cells on screen), the failure states, and that
// hostile sheet text only ever becomes text.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync('docs/guides/fleet-rollout-register.html', 'utf8');
const dataJson = /<script type="application\/json" id="data">\n([\s\S]*?)\n<\/script>/.exec(html)[1];
const script = /<\/script>\n<script>\n([\s\S]*?)\n<\/script>\s*$/.exec(html)[1];
const golden = JSON.parse(fs.readFileSync('tests/golden/health_cell_real.json', 'utf8'));
const FILE_ID = 'f'.repeat(33);
const MIN = 60000;

class Node_ {
  constructor(tag) { this.tagName = tag; this.children = []; this.className = ''; this.id = ''; this.attrs = {}; this.listeners = {}; this._text = null; this.hidden = false; }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); return c; }
  get firstChild() { return this.children[0] || null; }
  append(...cs) { cs.forEach(c => this.appendChild(c)); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  click() { (this.listeners.click || []).forEach(fn => fn({preventDefault() {}})); }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return (this._text === null ? '' : this._text) + this.children.map(c => c.textContent).join(''); }
  get classList() { const n = this; return {toggle() {}, add() {}, remove() {}, contains: c => n.className.split(' ').includes(c)}; }
  getBoundingClientRect() { return {bottom: 0, top: 0}; }
  scrollIntoView() {} focus() {}
  get offsetWidth() { return 0; }
  set innerHTML(v) { throw new Error('innerHTML is forbidden on this page'); }
  set outerHTML(v) { throw new Error('outerHTML is forbidden on this page'); }
  insertAdjacentHTML() { throw new Error('insertAdjacentHTML is forbidden on this page'); }
  find(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.find && c.find(pred, out)); return out; }
}
class Text_ { constructor(t) { this.data = String(t); } get textContent() { return this.data; } }

function boot({fileId, mcp, noClaude, nowMs}) {
  const created = [];
  const byId = {};
  const document = {
    createElement: tag => { created.push(tag); return new Node_(tag); },
    createTextNode: t => new Text_(t),
    getElementById: id => {
      if (id === 'data') { const d = JSON.parse(dataJson); d.health.sources[0].file_id = fileId; return {textContent: JSON.stringify(d)}; }
      return byId[id] || (byId[id] = Object.assign(new Node_('div'), {id}));
    },
    querySelectorAll: () => [], querySelector: () => null,
  };
  const timers = [];
  const calls = {use: 0};
  const sandbox = {document, window: {addEventListener() {}, scrollTo() {}}, console, JSON, Math, Object, Array, Number, String, Promise, isNaN,
    atob, Blob, DecompressionStream, TextDecoder, Uint8Array, parseInt, setTimeout: fn => timers.push(fn), setInterval: fn => timers.push(fn)};
  sandbox.Date = class extends Date { static now() { return nowMs; } };
  if (!noClaude) {
    sandbox.claude = {use: async name => { calls.use += 1; assert.equal(name, 'mcp'); return typeof mcp === 'function' ? mcp() : mcp; }};
  }
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox, {filename: 'rollout-page-script'});
  return {byId, created, calls, timers, panel: byId.healthSources};
}

const settle = () => new Promise(r => setTimeout(r, 25));
const cellResult = text => ({content: [{type: 'text', text}]});
const NOW = Date.parse('2026-10-22T07:55:00Z');
const texts = n => n.textContent;

function fakeMcp(deliver) {
  const m = {watches: [], callTools: [],
    watchTool(server, tool, input, handler, options) { m.watches.push({server, tool, input, options}); Promise.resolve().then(() => deliver(handler, m)); return () => {}; },
    callTool(server, tool, input, options) { m.callTools.push({server, tool, input, options}); return m.nextCall ? m.nextCall() : Promise.resolve(cellResult(golden.real.cell)); }};
  return m;
}

(async () => {
  // 1. not configured: says so, never touches the connector
  let page = boot({fileId: null, noClaude: true, nowMs: NOW});
  await settle();
  assert.ok(texts(page.panel).includes('還沒設定讀數來源'));
  assert.ok(texts(page.panel).includes('A1 正式機（新）'));              // the glossary's name for the host
  assert.equal(page.calls.use, 0);
  page = boot({fileId: null, mcp: () => { throw new Error('must not be asked'); }, nowMs: NOW});
  await settle();
  assert.equal(page.calls.use, 0);
  assert.equal(page.timers.length, 0);                                // nothing to refresh

  // 2. configured, watch delivers the real cell
  let mcp = fakeMcp((handler) => handler({type: 'data', result: cellResult(golden.real.cell)}));
  page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
  await settle();
  assert.equal(mcp.watches.length, 1);
  assert.deepEqual([mcp.watches[0].server, mcp.watches[0].tool, mcp.watches[0].input], ['Google Drive', 'read_file_content', {fileId: FILE_ID}]);
  assert.equal(mcp.watches[0].options.refetchInterval, 60000);
  let text = texts(page.panel);
  for (const label of ['動能策略', '加密策略', '趨勢策略', '競賽策略', '主機', '帳本軸', 'Google 表軸', '運行狀態軸', '服務單元軸', '匯出檔軸', '時鐘軸']) assert.ok(text.includes(label), label);
  assert.ok(text.includes('DIVERGED') && text.includes('RECONCILED') && text.includes('HEALTHY'));
  assert.ok(text.includes('有項目異常'));                              // two DIVERGED readings
  assert.ok(text.includes('讀數產生 10/22 15:51') && text.includes('最後一次輪詢 10/22 15:50'));
  assert.ok(text.includes('發布停 25 分鐘') && text.includes('輪詢停 45 分鐘'));
  const chips = page.panel.find(n => /\bhv-/.test(n.className) && n.tagName === 'span' && !/hv-age|hv-none/.test(n.className));
  assert.equal(chips.length, 20);
  assert.equal(chips.filter(n => n.className.includes('hv-alert')).length, 2);
  assert.equal(chips.filter(n => n.className.includes('hv-stale') || n.className.includes('hv-notime')).length, 0);
  assert.ok(page.timers.length >= 1);                                 // the 30-second age refresh is armed
  // the viewer can always re-read: one click = one uncached call (never on load, never on a timer)
  const refresh = page.panel.find(n => n.tagName === 'button' && n.textContent === '重新讀取');
  assert.equal(refresh.length, 1);
  assert.equal(mcp.callTools.length, 0);
  refresh[0].click();
  await settle();
  assert.equal(mcp.callTools.length, 1);
  assert.deepEqual([mcp.callTools[0].server, mcp.callTools[0].tool, mcp.callTools[0].input, mcp.callTools[0].options], ['Google Drive', 'read_file_content', {fileId: FILE_ID}, {cache: false}]);
  assert.ok(!page.created.some(t => ['img', 'script', 'iframe', 'object', 'embed', 'style'].includes(t)));

  // 3. the same table, but the viewer opens the page 29 minutes after it was generated: nothing is green
  mcp = fakeMcp((handler) => handler({type: 'data', result: cellResult(golden.real.cell)}));
  page = boot({fileId: FILE_ID, mcp, nowMs: Date.parse('2026-10-22T08:20:00Z')});
  await settle();
  text = texts(page.panel);
  assert.ok(text.includes('讀數過期（發布停了）') && text.includes('只供參考'));
  const stale = page.panel.find(n => n.tagName === 'span' && /\bhv-/.test(n.className) && !/hv-age|hv-none/.test(n.className));
  assert.ok(stale.length === 20 && stale.every(n => n.className.includes('hv-stale')));
  assert.ok(!text.includes('全部正常'));

  // 4. a reading without a time (f-62 shape)
  mcp = fakeMcp((handler) => handler({type: 'data', result: cellResult(golden.with_null_time.cell)}));
  page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
  await settle();
  text = texts(page.panel);
  assert.ok(text.includes('無讀取時間'));
  assert.equal(page.panel.find(n => n.className.includes('hv-notime')).length, 1);

  // 5. hostile text from the sheet is only ever text
  const hostile = '<img src=x onerror=alert(1)>';
  const zlib = require('zlib');
  const evil = JSON.parse(JSON.stringify(golden.real.table));
  evil.readings[0].value = hostile;
  const evilCell = 'HEALTHv1|' + zlib.gzipSync(Buffer.from(JSON.stringify(evil))).toString('base64') + '|HEALTHEND';
  mcp = fakeMcp((handler) => handler({type: 'data', result: cellResult(evilCell)}));
  page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
  await settle();
  assert.ok(texts(page.panel).includes(hostile));
  assert.ok(!page.created.includes('img'));

  // 6. a damaged cell: say so, show no table
  for (const [name, res, expect] of [
    ['cut off', cellResult(golden.real.cell.slice(0, 200)), '截斷'],
    ['no cell', cellResult('| A1 | something else |'), '找不到讀數格'],
    ['not gzip', cellResult('HEALTHv1|' + Buffer.from('plain').toString('base64') + '|HEALTHEND'), '損壞'],
    ['wrong shape', cellResult('HEALTHv1|' + zlib.gzipSync(Buffer.from('[]')).toString('base64') + '|HEALTHEND'), '結構不符合'],
  ]) {
    mcp = fakeMcp((handler) => handler({type: 'data', result: res}));
    page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
    await settle();
    assert.ok(texts(page.panel).includes(expect), name);
    assert.equal(page.panel.find(n => n.tagName === 'table').length, 0, name);
  }

  // 7. connector errors: each code its own words; consent needs a viewer click
  mcp = fakeMcp((handler) => handler({type: 'error', error: {code: 'approval_required', message: 'x'}}));
  mcp.nextCall = () => Promise.resolve(cellResult(golden.real.cell));
  page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
  await settle();
  assert.ok(texts(page.panel).includes('要你同意這個頁面使用 Google Drive 連接器'));
  assert.equal(mcp.callTools.length, 0);                              // nothing is called until the viewer clicks
  const allow = page.panel.find(n => n.tagName === 'button' && n.textContent === '允許並讀取');
  assert.equal(allow.length, 1);
  allow[0].click();
  await settle();
  assert.equal(mcp.callTools.length, 1);
  assert.deepEqual([mcp.callTools[0].server, mcp.callTools[0].tool, mcp.callTools[0].input, mcp.callTools[0].options], ['Google Drive', 'read_file_content', {fileId: FILE_ID}, {cache: false}]);
  assert.ok(texts(page.panel).includes('有項目異常'));                // the table is there after the click
  assert.ok(!texts(page.panel).includes('要你同意'));

  for (const [code, expect] of [['needs_reauth', '重新登入'], ['server_not_connected', '新增'], ['not_in_manifest', '沒有被允許'], ['tool_error', 'Google Drive 回報錯誤'], ['weird', '讀取失敗（weird）']]) {
    mcp = fakeMcp((handler) => handler({type: 'error', error: {code, message: 'boom'}}));
    page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
    await settle();
    assert.ok(texts(page.panel).includes(expect), code);
    assert.equal(page.panel.find(n => n.tagName === 'table').length, 0, code);
  }

  // a transient error keeps the last good table (its own times still say how old it is); a denial drops it
  mcp = fakeMcp((handler) => { handler({type: 'data', result: cellResult(golden.real.cell)}); setTimeout(() => handler({type: 'error', error: {code: 'server_unavailable'}}), 5); });
  page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
  await new Promise(r => setTimeout(r, 60));
  assert.ok(texts(page.panel).includes('暫時讀不到 Google Drive'));
  assert.equal(page.panel.find(n => n.tagName === 'table').length, 1);
  mcp = fakeMcp((handler) => { handler({type: 'data', result: cellResult(golden.real.cell)}); setTimeout(() => handler({type: 'error', error: {code: 'needs_reauth'}}), 5); });
  page = boot({fileId: FILE_ID, mcp, nowMs: NOW});
  await new Promise(r => setTimeout(r, 60));
  assert.equal(page.panel.find(n => n.tagName === 'table').length, 0);

  // 8. no connector in this view at all
  page = boot({fileId: FILE_ID, mcp: null, nowMs: NOW});
  await settle();
  assert.ok(texts(page.panel).includes('要在 claude.ai 裡開這個頁面'));
  page = boot({fileId: FILE_ID, noClaude: true, nowMs: NOW});
  await settle();
  assert.ok(texts(page.panel).includes('要在 claude.ai 裡開這個頁面'));

  // 9. the rest of the page still renders (the panel must not break the register)
  assert.ok(texts(page.byId.pending).length > 0 || texts(page.byId.done).length > 0);

  console.log('health_panel_page_node_test ok');
})().catch(err => { console.error(err); process.exit(1); });
