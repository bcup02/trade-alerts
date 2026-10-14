"""f-40: the risk register page's script -- the error-number dropdown and the per-block tier badge.

The page is generated (scripts/render_guides.py) and its behaviour lives in JavaScript, which nothing else runs.  This
test executes the page's own script in QuickJS against a minimal DOM stand-in (just enough for that script) and drives
the dropdown the way a person would.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from trade_alerts import load_error_catalog

quickjs = pytest.importorskip("quickjs")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "guides" / "fleet-risk-register.html"

SHIM = r"""
var __log = {scroll: [], replace: [], timers: []};
function Node(tag){ this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null; this.dataset = {};
  this._style = {}; this.style = {setProperty: function(k, v){ this._style[k] = v; }.bind(this)}; this._attrs = {};
  this._l = {}; this.className = ""; this.textContent = ""; this.hidden = false; this.id = ""; this.value = ""; this.open = false;
  var self = this;
  this.classList = {add: function(c){ if(!self.classList.contains(c)) self.className = (self.className + " " + c).trim(); },
    remove: function(c){ self.className = self.className.split(/\s+/).filter(function(x){return x && x !== c;}).join(" "); },
    contains: function(c){ return self.className.split(/\s+/).indexOf(c) >= 0; },
    toggle: function(c, on){ if(on) self.classList.add(c); else self.classList.remove(c); }}; }
Node.prototype.appendChild = function(n){ n.parentNode = this; this.children.push(n); return n; };
Node.prototype.insertBefore = function(n, ref){ n.parentNode = this; var i = this.children.indexOf(ref); this.children.splice(i < 0 ? this.children.length : i, 0, n); return n; };
Object.defineProperty(Node.prototype, "firstChild", {get: function(){ return this.children[0] || null; }});
Node.prototype.setAttribute = function(k, v){ this._attrs[k] = String(v); };
Node.prototype.getAttribute = function(k){ return this._attrs[k]; };
Node.prototype.addEventListener = function(t, f){ (this._l[t] = this._l[t] || []).push(f); };
Node.prototype.dispatch = function(t){ (this._l[t] || []).forEach(function(f){ f({target: this}); }, this); };
Node.prototype.click = function(){ this.dispatch("click"); };
Node.prototype.scrollIntoView = function(o){ __log.scroll.push(this.id); };
Node.prototype.getBoundingClientRect = function(){ return {bottom: 0}; };
Node.prototype.focus = function(){};
function walk(n, f){ f(n); n.children.forEach(function(c){ walk(c, f); }); }
function matches(n, sel){ if(sel.charAt(0) === "#") return n.id === sel.slice(1); if(sel.charAt(0) === ".") return n.classList.contains(sel.slice(1)); return n.tagName === sel.toUpperCase(); }
Node.prototype.querySelectorAll = function(sel){ var parts = sel.split(/\s+/), out = [], root = this;
  walk(root, function(n){ if(n === root) return; if(matches(n, parts[parts.length - 1])){
    if(parts.length === 1) { out.push(n); return; }
    var a = n.parentNode, ok = false; while(a){ if(matches(a, parts[0])) { ok = true; break; } a = a.parentNode; } if(ok) out.push(n); } });
  return out; };
Node.prototype.querySelector = function(sel){ return this.querySelectorAll(sel)[0] || null; };
var document = new Node("document"); var body = document.appendChild(new Node("body"));
document.createElement = function(t){ return new Node(t); };
document.createTextNode = function(t){ var n = new Node("#text"); n.textContent = t; return n; };
document.getElementById = function(id){ var f = null; walk(document, function(n){ if(!f && n.id === id) f = n; }); return f; };
function mk(id, tag){ var n = new Node(tag || "div"); n.id = id; body.appendChild(n); return n; }
var wrap = body.appendChild(new Node("div")); wrap.appendChild(Object.assign(new Node("h1"), {textContent: "t"}));
var filters = new Node("div"); filters.id = "filters"; wrap.appendChild(filters);
var registerEl = new Node("div"); registerEl.id = "register"; wrap.appendChild(registerEl);
var dataEl = mk("data", "script"); var totop = mk("totop", "button");
var window = {addEventListener: function(){}, scrollTo: function(){}};
var history = {replaceState: function(a, b, u){ __log.replace.push(u); }};
var location = {hash: ""};
function setTimeout(f, ms){ __log.timers.push({f: f, ms: ms}); return __log.timers.length; }
"""

DRIVER = r"""
function chips(host){ return host.children; }
function rowsOf(){ return registerEl.querySelectorAll(".row"); }
function info(){
  var rows = rowsOf();
  return {rows: rows.length, hidden: rows.filter(function(r){ return r.hidden; }).length,
          ids: rows.map(function(r){ return r.id; })};
}
"""


def _script(html: str) -> tuple[str, str]:
    data = re.search(r'<script type="application/json" id="data">\n(.*?)\n</script>', html, re.S).group(1)
    scripts = re.findall(r"<script>\n(.*?)\n</script>", html, re.S)
    assert len(scripts) == 1
    return data.replace("<\\/", "</"), scripts[0]


def boot(hash_: str = "", html: str | None = None):
    html = html if html is not None else PAGE.read_text(encoding="utf-8")
    data, script = _script(html)
    ctx = quickjs.Context()
    ctx.eval(SHIM + DRIVER)
    ctx.eval("dataEl.textContent = " + json.dumps(data) + "; location.hash = " + json.dumps(hash_) + ";")
    ctx.eval(script)
    return ctx, json.loads(data)


def run(ctx, code):
    return json.loads(ctx.eval("JSON.stringify(" + code + ")"))


def test_the_page_builds_one_row_per_error_with_an_id_and_a_tier_badge():
    ctx, data = boot()
    entries = data["entries"]
    assert run(ctx, "info().rows") == len(entries) == len(load_error_catalog()["entries"])
    ids = run(ctx, "info().ids")
    assert sorted(ids) == sorted(e["error_id"] for e in entries) and len(set(ids)) == len(ids)
    for e in entries:
        badge = run(ctx, f"(function(){{var r=document.getElementById({json.dumps(e['error_id'])});"
                         "var b=r.querySelector('.row-tier');var s=r.querySelector('.row-bot');"
                         "return {tier:b.textContent,title:b.title,color:b._style['--tc'],bot:s.textContent};})()")
        assert badge["tier"] == e["tier"] and badge["bot"] == e["bot_label"]       # the tier AND the strategy name are on the block
        assert badge["color"] == f"var(--{e['tier']})" and badge["title"].startswith(e["tier"])


def test_the_dropdown_lists_every_error_number_in_order_with_tier_strategy_and_title():
    ctx, data = boot()
    options = run(ctx, "jumpSel.children.map(function(o){return {v:o.value,t:o.textContent};})")
    assert options[0] == {"v": "", "t": "選擇錯誤編號…"}
    assert [o["v"] for o in options[1:]] == sorted(e["error_id"] for e in data["entries"])
    e044 = next(e for e in data["entries"] if e["error_id"] == "ERR-044")
    assert next(o["t"] for o in options if o["v"] == "ERR-044") == f"ERR-044｜{e044['tier']}｜{e044['bot_label']}｜{e044['title']}"
    assert run(ctx, "document.getElementById('jump') === jumpSel && jumpLabel.htmlFor === 'jump'")


def test_choosing_an_error_scrolls_to_its_block_opens_its_steps_highlights_it_and_sets_the_hash():
    ctx, _ = boot()
    ctx.eval("jumpSel.value='ERR-044'; jumpSel.dispatch('change');")
    assert run(ctx, "__log.scroll") == ["ERR-044"]
    assert run(ctx, "document.getElementById('ERR-044').querySelector('details').open") is True
    assert run(ctx, "document.getElementById('ERR-044').classList.contains('flash')") is True
    assert run(ctx, "__log.replace") == ["#ERR-044"]
    ctx.eval("__log.timers.forEach(function(t){t.f();})")                    # the highlight goes away by itself
    assert run(ctx, "document.getElementById('ERR-044').classList.contains('flash')") is False


def test_a_filter_that_hides_the_block_is_cleared_before_jumping():
    ctx, _ = boot()
    ctx.eval("chips(tierHost)[1].click();")                                    # R3 only: ERR-044 is R2 and disappears
    assert run(ctx, "document.getElementById('ERR-044').hidden") is True
    ctx.eval("jumpSel.value='ERR-044'; jumpSel.dispatch('change');")
    assert run(ctx, "document.getElementById('ERR-044').hidden") is False
    assert run(ctx, "info().hidden") == 0 and run(ctx, "__log.scroll") == ["ERR-044"]
    assert run(ctx, "chips(tierHost)[0].getAttribute('aria-pressed')") == "true"        # the chips show "all" again


def test_a_block_that_a_bot_filter_hides_is_found_too():
    ctx, _ = boot()
    ctx.eval("chips(botHost)[1].click();")                                     # one strategy only
    hidden = run(ctx, "info().hidden")
    assert hidden > 0
    target = run(ctx, "(function(){var h=rowsOf().filter(function(r){return r.hidden;})[0];return h.id;})()")
    ctx.eval(f"jumpSel.value={json.dumps(target)}; jumpSel.dispatch('change');")
    assert run(ctx, "info().hidden") == 0 and run(ctx, "__log.scroll[0]") == target


def test_a_link_with_an_error_number_in_the_hash_jumps_on_load():
    ctx, _ = boot(hash_="#ERR-061")
    assert run(ctx, "__log.scroll") == ["ERR-061"] and run(ctx, "__log.replace") == []
    assert run(ctx, "jumpSel.value") == "ERR-061"


@pytest.mark.parametrize("hash_", ["#ERR-999", "#nonsense", "#ERR-04x", "ERR-044", "#ERR-044<img>", ""])
def test_a_bad_or_unknown_hash_does_nothing_and_does_not_break_the_page(hash_):
    ctx, _ = boot(hash_=hash_)
    assert run(ctx, "__log.scroll") == [] and run(ctx, "info().rows") == len(load_error_catalog()["entries"])


def test_the_empty_choice_does_nothing():
    ctx, _ = boot()
    ctx.eval("jumpSel.value=''; jumpSel.dispatch('change');")
    assert run(ctx, "__log.scroll") == [] and run(ctx, "__log.replace") == []


def test_the_shim_would_notice_a_page_whose_script_is_broken():
    html = PAGE.read_text(encoding="utf-8").replace("row.id=e.error_id;", "")
    ctx, _ = boot(html=html)
    with pytest.raises(Exception):
        ctx.eval("jumpSel.value='ERR-044'; jumpSel.dispatch('change'); if(__log.scroll.length!==1) throw new Error('no jump');")
