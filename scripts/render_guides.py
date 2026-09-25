"""Generate the two human-readable guide pages from their JSON sources.

    python scripts/render_guides.py          # rewrite docs/guides/*.html
    python scripts/render_guides.py --check  # exit 1 if either page is stale

``fleet-risk-register.html`` comes from the error catalog (plus the rollout
registry's per-strategy status); ``fleet-rollout-register.html`` from the
rollout registry.  Neither page may be edited by hand: a test re-renders both
and fails if the committed file differs -- the v1 risk register drifted to 30
of 33 conditions precisely because it was a second, hand-written copy.

Output is deterministic (sorted JSON, no timestamps beyond the sources' own).
All text reaches the page through ``textContent``, never ``innerHTML``.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trade_alerts.fleet_event_log import load_error_catalog  # noqa: E402
from trade_alerts.glossary import load_glossary  # noqa: E402
from trade_alerts.rollout_registry import STRATEGY_PROJECTS, load_rollout_registry, owners  # noqa: E402

GUIDES = ROOT / "docs" / "guides"
RISK_PAGE = GUIDES / "fleet-risk-register.html"
ROLLOUT_PAGE = GUIDES / "fleet-rollout-register.html"

TIERS = [
    {"id": "R3", "title": "一定要人處理", "sub": "系統絕不自己動手，會一直提醒到有人處理"},
    {"id": "R2", "title": "系統先自己試，試不起來才找你", "sub": "連續失敗 3 次才通知一次，附給 AI 的追查指令"},
    {"id": "R1", "title": "自動處理，不通知", "sub": "沒有第二個選項，做完留紀錄"},
    {"id": "R0", "title": "只是記一筆", "sub": "不需要處理，不通知任何人"},
]
BOT_LABEL_FLEET = "全機隊"

_CSS = """
  :root{
    --paper:#F1F3EC; --paper-raised:#FAFBF6; --line:#DBE0D0;
    --ink:#1F2A22; --ink-soft:#57604E; --ink-faint:#8A9080;
    --accent:#5B3A5C; --accent-bg:#EDE3EC; --accent-line:#C9AECB;
    --R3:#963025; --R3-bg:#F4E1DD;
    --R2:#8C6317; --R2-bg:#F1E6C9;
    --R1:#357357; --R1-bg:#DEEAE3;
    --R0:#6B7566; --R0-bg:#E7EAE0;
    --done:#357357; --done-bg:#DEEAE3;
    --pending:#8C6317; --pending-bg:#F1E6C9;
    --na:#6B7566; --na-bg:#E7EAE0;
    --recent:#A6800A; --recent-bg:#FFF3B0;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      --paper:#18150F; --paper-raised:#211D16; --line:#332D22;
      --ink:#EDE6D8; --ink-soft:#B7AF9C; --ink-faint:#847C6C;
      --accent:#C6A0C8; --accent-bg:#302733; --accent-line:#5A455C;
      --R3:#E58A7C; --R3-bg:#3A241F; --R2:#D9B364; --R2-bg:#382D18;
      --R1:#7FC6A2; --R1-bg:#1D3227; --R0:#A6AD97; --R0-bg:#292B21;
      --done:#7FC6A2; --done-bg:#1D3227; --pending:#D9B364; --pending-bg:#382D18; --na:#A6AD97; --na-bg:#292B21;
      --recent:#FFE066; --recent-bg:#4A3B05;
    }
  }
  :root[data-theme="dark"]{
    --paper:#18150F; --paper-raised:#211D16; --line:#332D22;
    --ink:#EDE6D8; --ink-soft:#B7AF9C; --ink-faint:#847C6C;
    --accent:#C6A0C8; --accent-bg:#302733; --accent-line:#5A455C;
    --R3:#E58A7C; --R3-bg:#3A241F; --R2:#D9B364; --R2-bg:#382D18;
    --R1:#7FC6A2; --R1-bg:#1D3227; --R0:#A6AD97; --R0-bg:#292B21;
    --done:#7FC6A2; --done-bg:#1D3227; --pending:#D9B364; --pending-bg:#382D18; --na:#A6AD97; --na-bg:#292B21;
    --recent:#FFE066; --recent-bg:#4A3B05;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Sans TC","IBM Plex Mono",sans-serif;padding:40px 20px 64px;}
  .wrap{max-width:860px;margin-inline:auto;}
  .eyebrow{font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);}
  h1{font-family:"Noto Serif TC",serif;font-weight:900;font-size:clamp(28px,5vw,40px);line-height:1.25;margin:6px 0 12px;}
  h2{font-family:"Noto Serif TC",serif;font-weight:700;font-size:20px;margin:36px 0 12px;}
  .lede{font-size:15.5px;line-height:1.75;color:var(--ink-soft);max-width:60ch;margin:0 0 24px;}
  .lede b{color:var(--ink);}
  .legend{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden;margin-bottom:24px;}
  .legend-item{background:var(--paper-raised);padding:14px 12px 12px;display:flex;flex-direction:column;gap:6px;}
  .legend-code{font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-weight:600;font-size:12px;}
  .legend-name{font-size:13px;font-weight:700;line-height:1.3;}
  .legend-sub{font-size:11.5px;color:var(--ink-faint);line-height:1.5;}
  .filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;}
  .chip{font:inherit;font-size:13px;padding:7px 14px;border-radius:999px;border:1px solid var(--line);background:var(--paper-raised);color:var(--ink-soft);cursor:pointer;}
  .chip[aria-pressed="true"]{background:var(--accent-bg);border-color:var(--accent-line);color:var(--accent);font-weight:700;}
  .chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  .chip .n{font-family:"IBM Plex Mono","Noto Sans TC",monospace;opacity:.75;margin-inline-start:4px;}
  .tier-head{display:flex;align-items:baseline;gap:12px;padding:14px 16px;border-radius:3px 3px 0 0;border-inline-start:4px solid var(--edge);background:var(--bg);margin-top:20px;}
  .tier-code{font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-weight:600;font-size:13px;color:var(--edge);}
  .tier-title{font-family:"Noto Serif TC",serif;font-weight:700;font-size:17px;}
  .tier-count{font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-size:12px;color:var(--ink-faint);margin-inline-start:auto;}
  .rows{border-inline-start:4px solid var(--line);border-block-end:1px solid var(--line);}
  .row{display:grid;grid-template-columns:104px 1fr;gap:16px;padding:14px 16px;border-block-start:1px solid var(--line);}
  .row-bot{font-size:11.5px;font-weight:700;color:var(--ink-soft);padding:3px 8px;border:1px solid var(--line);border-radius:999px;background:var(--paper-raised);text-align:center;align-self:start;white-space:nowrap;}
  .row-body p{margin:0;font-size:14.5px;line-height:1.7;}
  .row-title{font-weight:700;}
  .row-what{color:var(--ink);margin-top:2px !important;}
  .row-how{color:var(--ink-soft);margin-top:5px !important;}
  .code{font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-size:11.5px;color:var(--ink-faint);}
  .card p.desc{margin-top:2px;}
  .status{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}
  .st{font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px;color:var(--c);background:var(--cb);}
  .st-done{--c:var(--done);--cb:var(--done-bg);} .st-pending{--c:var(--pending);--cb:var(--pending-bg);} .st-na{--c:var(--na);--cb:var(--na-bg);}
  .note{font-size:13px;color:var(--ink-soft);margin-top:6px !important;line-height:1.6;}
  details{margin-top:8px;font-size:13.5px;}
  details summary{cursor:pointer;color:var(--accent);font-weight:700;}
  details ol{margin:6px 0 0;padding-inline-start:22px;line-height:1.7;}
  details pre{white-space:pre-wrap;background:var(--paper-raised);border:1px solid var(--line);border-radius:3px;padding:10px;font-size:12.5px;line-height:1.6;}
  .card{border:1px solid var(--line);border-radius:3px;background:var(--paper-raised);padding:14px 16px;margin-bottom:12px;}
  .card h3{margin:0 0 4px;font-size:15.5px;}
  .card p{margin:0;font-size:13.5px;color:var(--ink-soft);line-height:1.6;}
  .grid{display:grid;grid-template-columns:110px 1fr;gap:6px 12px;margin-top:10px;font-size:13.5px;line-height:1.6;}
  .grid .who{font-weight:700;color:var(--ink-soft);}
  .summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:8px;}
  .summary div{border:1px solid var(--line);border-radius:3px;background:var(--paper-raised);padding:10px 12px;font-size:13px;line-height:1.7;}
  .summary b{display:block;font-size:14px;}
  [hidden]{display:none !important;}
  @media (max-width:560px){
    .legend,.summary{grid-template-columns:1fr 1fr;}
    .row{grid-template-columns:1fr;} .row-bot{justify-self:start;}
    .grid{grid-template-columns:1fr;}
    body{padding-inline:16px;}
  }
  .foot{margin-top:36px;font-size:12px;color:var(--ink-faint);line-height:1.7;border-block-start:1px solid var(--line);padding-top:16px;}
"""

_FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@700;900'
          '&family=Noto+Sans+TC:wght@400;500;700&family=IBM+Plex+Mono:wght@500;600&display=swap">')


def _page(title: str, body: str, data: dict[str, Any], script: str, css: str = "") -> str:
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1).replace("</", "<\\/")
    return (f"<title>{title}</title>\n{_FONTS}\n<style>{_CSS}{css}</style>\n\n{body}\n\n"
            f'<script type="application/json" id="data">\n{blob}\n</script>\n'
            f"<script>\n{script}\n</script>\n")


_JS_HELPERS = r"""
var DATA = JSON.parse(document.getElementById("data").textContent);
function el(tag, cls, text){ var n=document.createElement(tag); if(cls) n.className=cls; if(text!==undefined) n.textContent=text; return n; }
var STATE_LABEL = {"done":"已做","pending":"未做","n/a":"不適用"};
var STATE_CLASS = {"done":"st-done","pending":"st-pending","n/a":"st-na"};
function chipGroup(host, values, onPick){
  var buttons=[];
  values.forEach(function(v){
    var b=el("button","chip"); b.type="button"; b.setAttribute("aria-pressed", v.id==="all"?"true":"false");
    b.appendChild(document.createTextNode(v.label)); b.appendChild(el("span","n",String(v.n)));
    b.addEventListener("click", function(){ buttons.forEach(function(x){x.setAttribute("aria-pressed","false");}); b.setAttribute("aria-pressed","true"); onPick(v.id); });
    buttons.push(b); host.appendChild(b);
  });
}
"""

_RISK_JS = _JS_HELPERS + r"""
var register=document.getElementById("register"), filters=document.getElementById("filters");
var pick={tier:"all",bot:"all",open:"all"};
var rows=[];
DATA.tiers.forEach(function(t){
  var entries=DATA.entries.filter(function(e){return e.tier===t.id;});
  var section=el("section"); section.dataset.tier=t.id;
  var head=el("div","tier-head"); head.style.setProperty("--edge","var(--"+t.id+")"); head.style.setProperty("--bg","var(--"+t.id+"-bg)");
  head.appendChild(el("span","tier-code",t.id)); head.appendChild(el("span","tier-title",t.title)); head.appendChild(el("span","tier-count",entries.length+" 種"));
  section.appendChild(head);
  var box=el("div","rows");
  entries.forEach(function(e){
    var row=el("div","row"); row.dataset.bot=e.bot; row.dataset.open=e.open?"yes":"no";
    row.appendChild(el("span","row-bot",e.bot_label));
    var body=el("div","row-body");
    body.appendChild(el("p","row-title",e.title));
    body.appendChild(el("p","code",e.code));
    body.appendChild(el("p","row-what",e.what));
    body.appendChild(el("p","row-how",e.direction));
    var st=el("div","status");
    [["行為",e.behaviour],["寫進事件日誌",e.emits_event]].forEach(function(pair){
      var s=el("span","st "+STATE_CLASS[pair[1].state],pair[0]+"："+STATE_LABEL[pair[1].state]); st.appendChild(s);
    });
    body.appendChild(st);
    e.notes.forEach(function(n){ body.appendChild(el("p","note",n)); });
    if(e.steps.length){
      var d=el("details"); d.appendChild(el("summary",null,"處理步驟"+(e.ai_prompt?"與給 AI 的追查指令":"")));
      var ol=el("ol"); e.steps.forEach(function(s){ ol.appendChild(el("li",null,s)); }); d.appendChild(ol);
      if(e.ai_prompt){ d.appendChild(el("p","note","給 AI 的追查指令（實際通知會再附上當次的錯誤碼、事件編號與事件資料）：")); d.appendChild(el("pre",null,e.ai_prompt)); }
      body.appendChild(d);
    }
    row.appendChild(body); box.appendChild(row); rows.push(row);
  });
  section.appendChild(box); register.appendChild(section);
});
function apply(){
  rows.forEach(function(r){
    var okBot=pick.bot==="all"||r.dataset.bot===pick.bot, okOpen=pick.open==="all"||r.dataset.open==="yes";
    var okTier=pick.tier==="all"||r.parentNode.parentNode.dataset.tier===pick.tier;
    r.hidden=!(okBot&&okOpen&&okTier);
  });
  document.querySelectorAll("#register section").forEach(function(s){
    s.hidden=!Array.prototype.some.call(s.querySelectorAll(".row"),function(r){return !r.hidden;});
  });
}
function count(f){return DATA.entries.filter(f).length;}
var tierHost=el("div","filters"), botHost=el("div","filters"), openHost=el("div","filters");
filters.appendChild(tierHost); filters.appendChild(botHost); filters.appendChild(openHost);
chipGroup(tierHost,[{id:"all",label:"全部等級",n:DATA.entries.length}].concat(DATA.tiers.map(function(t){return {id:t.id,label:t.id+" "+t.title,n:count(function(e){return e.tier===t.id;})};})),function(v){pick.tier=v;apply();});
chipGroup(botHost,[{id:"all",label:"全部策略",n:DATA.entries.length}].concat(DATA.bots.map(function(b){return {id:b.id,label:b.label,n:count(function(e){return e.bot===b.id;})};})),function(v){pick.bot=v;apply();});
chipGroup(openHost,[{id:"all",label:"全部",n:DATA.entries.length},{id:"open",label:"只看還沒做完的",n:count(function(e){return e.open;})}],function(v){pick.open=v;apply();});
var toTop=document.getElementById("totop");
toTop.addEventListener("click",function(){ window.scrollTo(0,0); var h=document.querySelector("h1"); if(h){ h.setAttribute("tabindex","-1"); h.focus({preventScroll:true}); } });
function syncTop(){ toTop.classList.toggle("show", filters.getBoundingClientRect().bottom<0); }
window.addEventListener("scroll",syncTop,{passive:true}); syncTop();
"""

_RISK_CSS = """
  #totop{position:fixed;right:20px;bottom:20px;width:46px;height:46px;border-radius:50%;border:1px solid var(--accent-line);background:var(--accent-bg);color:var(--accent);font-size:20px;line-height:1;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);opacity:0;pointer-events:none;visibility:hidden;transform:translateY(8px);transition:opacity .2s,transform .2s,visibility 0s linear .2s;}
  #totop.show{opacity:1;pointer-events:auto;visibility:visible;transform:none;transition:opacity .2s,transform .2s,visibility 0s;}
  #totop:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  @media (max-width:560px){ #totop{right:16px;bottom:16px;} }
"""


_ROLLOUT_CSS = """
  html{scroll-behavior:smooth;}
  @media (prefers-reduced-motion: reduce){ html{scroll-behavior:auto;} }
  .big{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;}
  .big a{display:block;text-decoration:none;color:inherit;border:1px solid var(--line);border-inline-start:4px solid var(--c);border-radius:3px;background:var(--paper-raised);padding:12px 14px;}
  .big a:hover{background:var(--cb);}
  .big b{display:block;font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-size:28px;line-height:1.1;color:var(--c);}
  .big span{font-size:13px;color:var(--ink-soft);}
  .toc{display:grid;grid-template-columns:1.4fr 1fr;gap:12px;margin:20px 0 8px;}
  .toc-col{border:1px solid var(--line);border-radius:3px;background:var(--paper-raised);padding:12px 14px;}
  .toc-col h3{margin:0 0 6px;font-size:15px;color:var(--c);}
  .toc-col h4{margin:12px 0 4px;font-size:12px;font-weight:700;color:var(--ink-faint);letter-spacing:.06em;}
  .toc-col ul{list-style:none;margin:0;padding:0;}
  .toc-col li a{display:flex;align-items:center;gap:8px;padding:5px 6px;margin-inline:-6px;border-radius:3px;text-decoration:none;color:var(--ink);font-size:13.5px;line-height:1.4;}
  .toc-col li a:hover,.toc-col li a:focus-visible{background:var(--accent-bg);outline:none;}
  .toc-col li a .t{flex:1;min-width:0;}
  .dots{display:inline-flex;gap:3px;flex-shrink:0;}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--dc);border:1px solid var(--dc);}
  .dot-done{--dc:var(--done);} .dot-pending{--dc:var(--pending);} .dot-na{--dc:var(--na);opacity:.55;}
  .dot-none{--dc:var(--line);background:transparent;}
  .dot-recent{--dc:var(--recent);box-shadow:0 0 0 2px var(--recent-bg);}
  .dot-legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--ink-faint);margin:0 0 4px;}
  .dot-legend span{display:inline-flex;align-items:center;gap:5px;}
  .new-badge{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.03em;color:var(--recent);background:var(--recent-bg);border-radius:999px;padding:1px 7px;margin-inline-start:4px;white-space:nowrap;vertical-align:middle;}
  .recent-box{border:1px solid var(--recent);border-radius:3px;background:var(--recent-bg);padding:12px 14px;margin-bottom:14px;}
  .recent-box h3{margin:0 0 8px;font-size:13px;color:var(--recent);}
  .recent-box ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px;}
  .recent-box li a{color:inherit;text-decoration:none;font-weight:700;font-size:13.5px;}
  .recent-box li a:hover,.recent-box li a:focus-visible{text-decoration:underline;}
  .recent-box .proj{font-weight:600;font-size:11.5px;color:var(--ink-soft);margin-inline-start:6px;}
  .recent-box .note{display:block;font-weight:400;font-size:12.5px;color:var(--ink-soft);margin-top:2px;}
  .group-head{display:flex;align-items:baseline;gap:10px;margin:40px 0 4px;padding-bottom:8px;border-block-end:2px solid var(--c);}
  .group-head h2{margin:0;color:var(--c);}
  .group-head .n{font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-size:13px;color:var(--ink-faint);}
  .group-sub{font-size:13.5px;color:var(--ink-soft);margin:6px 0 12px;line-height:1.6;}
  h3.kind{font-size:14px;color:var(--ink-faint);margin:22px 0 8px;font-weight:700;}
  .item{scroll-margin-top:16px;transition:box-shadow .3s,background-color .3s;}
  .item.flash{box-shadow:0 0 0 3px var(--accent-line);background:var(--accent-bg);}
  .item-head{display:flex;align-items:flex-start;gap:10px;}
  .item-head .h{flex:1;min-width:0;}
  .item-head .dots{margin-top:5px;}
  .sl{display:grid;grid-template-columns:88px 1fr;margin-top:10px;border-block-start:1px solid var(--line);font-size:13.5px;line-height:1.6;}
  .sl > .who{font-weight:700;color:var(--ink-soft);padding:8px 0;border-block-end:1px solid var(--line);}
  .sl > .lines{padding:8px 0;border-block-end:1px solid var(--line);display:flex;flex-direction:column;gap:6px;min-width:0;overflow-wrap:anywhere;}
  .aspect{font-weight:700;color:var(--ink-soft);margin-inline-end:4px;}
  .phase{display:inline-block;font-size:11.5px;padding:1px 7px;margin-inline-start:6px;border-radius:3px;border:1px dashed var(--pending);color:var(--pending);}
  details.done-card{padding:0;margin-bottom:8px;}
  details.done-card > summary{list-style:none;display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;color:var(--ink);font-weight:400;}
  details.done-card > summary::-webkit-details-marker{display:none;}
  details.done-card > summary::before{content:"▸";color:var(--ink-faint);font-size:12px;transition:transform .15s;}
  details.done-card[open] > summary::before{transform:rotate(90deg);}
  details.done-card > summary .ok{color:var(--done);font-weight:700;}
  details.done-card > summary .t{flex:1;min-width:0;font-weight:700;font-size:14.5px;}
  details.done-card > .body{padding:0 16px 14px;}
  .phase-list .card p{margin-top:2px;}
  #totop{position:fixed;right:20px;bottom:20px;width:46px;height:46px;border-radius:50%;border:1px solid var(--accent-line);background:var(--accent-bg);color:var(--accent);font-size:20px;line-height:1;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);opacity:0;pointer-events:none;visibility:hidden;transform:translateY(8px);transition:opacity .2s,transform .2s,visibility 0s linear .2s;}
  #totop.show{opacity:1;pointer-events:auto;visibility:visible;transform:none;transition:opacity .2s,transform .2s,visibility 0s;}
  #totop:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  .c-pending{--c:var(--pending);--cb:var(--pending-bg);} .c-done{--c:var(--done);--cb:var(--done-bg);}
  .gloss-link{font-weight:700;color:var(--accent);}
  .gloss-cat{border:1px solid var(--line);border-radius:3px;background:var(--paper-raised);margin-bottom:12px;}
  .gloss-cat h3{margin:0;padding:10px 14px;font-size:14px;border-block-end:1px solid var(--line);color:var(--ink-soft);}
  .gloss-row{display:grid;grid-template-columns:170px 1fr;gap:4px 14px;padding:10px 14px;border-block-end:1px solid var(--line);font-size:13.5px;line-height:1.6;scroll-margin-top:16px;}
  .gloss-row:last-child{border-block-end:0;}
  .gloss-zh{font-weight:700;}
  .gloss-en{font-family:"IBM Plex Mono","Noto Sans TC",monospace;font-size:11.5px;color:var(--ink-faint);overflow-wrap:anywhere;}
  .gloss-def{color:var(--ink);}
  .gloss-note{color:var(--ink-soft);font-size:12.5px;}
  .gloss-old{color:var(--ink-faint);font-size:12.5px;}
  .gloss-old s{margin-inline-end:6px;}
  @media (max-width:560px){
    .toc{grid-template-columns:1fr;}
    .sl{grid-template-columns:1fr;} .sl > .who{padding-bottom:0;border-block-end:0;}
    .gloss-row{grid-template-columns:1fr;}
    #totop{right:16px;bottom:16px;}
  }
"""

_ROLLOUT_JS = _JS_HELPERS + r"""
var DOT_LABEL={"done":"已做","pending":"未做","na":"不適用","none":"跟這支無關","recent":"最新變動"};
var KINDS=[["cap","機隊功能"],["rule","錯誤處理規則"]];
function dots(item){
  var s=el("span","dots"); s.setAttribute("aria-hidden","true");
  DATA.project_order.forEach(function(p){ var d=el("span","dot dot-"+item.dots[p]); d.title=DATA.projects[p]+"："+DOT_LABEL[item.dots[p]]; s.appendChild(d); });
  return s;
}
function newBadge(){ var b=el("span","new-badge","🆕 最新變動"); b.title="這次更新才有的變化"; return b; }
function table(item){
  var g=el("div","sl");
  item.rows.forEach(function(r){
    g.appendChild(el("span","who",r.label));
    var box=el("div","lines");
    r.lines.forEach(function(l){
      var line=el("div");
      line.appendChild(el("span","st "+STATE_CLASS[l.state],STATE_LABEL[l.state]));
      line.appendChild(document.createTextNode(" "));
      if(l.aspect) line.appendChild(el("span","aspect",l.aspect));
      line.appendChild(document.createTextNode(l.text));
      if(l.phase) line.appendChild(el("span","phase","預定："+l.phase));
      box.appendChild(line);
    });
    g.appendChild(box);
  });
  return g;
}
function pendingCard(item){
  var c=el("div","card item"); c.id=item.anchor;
  var head=el("div","item-head"), h=el("div","h");
  h.appendChild(el("h3",null,item.title)); if(item.has_recent||item.added_recent) h.appendChild(newBadge());
  h.appendChild(el("p",item.kind==="cap"?"desc":"code",item.sub));
  head.appendChild(h); head.appendChild(dots(item)); c.appendChild(head);
  c.appendChild(table(item)); return c;
}
function doneCard(item){
  var d=el("details","card item done-card"); d.id=item.anchor;
  var s=el("summary"); s.appendChild(el("span","ok","✓")); s.appendChild(el("span","t",item.title));
  if(item.has_recent||item.added_recent) s.appendChild(newBadge());
  s.appendChild(dots(item));
  d.appendChild(s);
  var body=el("div","body"); body.appendChild(el("p",item.kind==="cap"?"desc":"code",item.sub)); body.appendChild(table(item));
  d.appendChild(body); return d;
}
function go(id){
  var n=document.getElementById(id); if(!n) return;
  if(n.tagName==="DETAILS") n.open=true;
  n.scrollIntoView({block:"start"});
  n.classList.remove("flash"); void n.offsetWidth; n.classList.add("flash");
  setTimeout(function(){ n.classList.remove("flash"); },1600);
}
function tocColumn(group, title){
  var col=el("div","toc-col c-"+group);
  var items=DATA.items.filter(function(i){return (group==="done")===i.complete;});
  col.appendChild(el("h3",null,title+"（"+items.length+"）"));
  KINDS.forEach(function(k){
    var list=items.filter(function(i){return i.kind===k[0];}); if(!list.length) return;
    col.appendChild(el("h4",null,k[1]+" · "+list.length));
    var ul=el("ul");
    list.forEach(function(i){
      var li=el("li"), a=el("a"); a.href="#"+i.anchor;
      a.appendChild(el("span","t",i.title)); if(i.has_recent||i.added_recent) a.appendChild(newBadge());
      a.appendChild(dots(i));
      a.addEventListener("click",function(ev){ ev.preventDefault(); go(i.anchor); });
      li.appendChild(a); ul.appendChild(li);
    });
    col.appendChild(ul);
  });
  return col;
}
function fillGroup(host, group){
  KINDS.forEach(function(k){
    var list=DATA.items.filter(function(i){return (group==="done")===i.complete && i.kind===k[0];}); if(!list.length) return;
    host.appendChild(el("h3","kind",k[1]+"（"+list.length+"）"));
    list.forEach(function(i){ host.appendChild(group==="done"?doneCard(i):pendingCard(i)); });
  });
}
var recentBox=document.getElementById("recentBox"), recentList=document.getElementById("recentList");
if(DATA.recent_summary && DATA.recent_summary.length){
  DATA.recent_summary.forEach(function(r){
    var li=el("li"), a=el("a"); a.href="#"+r.anchor;
    a.appendChild(document.createTextNode(r.title));
    if(r.project) a.appendChild(el("span","proj",r.project));
    a.appendChild(el("span","note",r.note));
    a.addEventListener("click",function(ev){ ev.preventDefault(); go(r.anchor); });
    li.appendChild(a); recentList.appendChild(li);
  });
  recentBox.hidden=false;
}
var glossHost=document.getElementById("glossaryHost");
DATA.glossary.forEach(function(group){
  var card=el("div","gloss-cat"); card.appendChild(el("h3",null,group.category));
  group.entries.forEach(function(g){
    var row=el("div","gloss-row"); row.id="term-"+g.id;
    var left=el("div"); left.appendChild(el("div","gloss-zh",g.zh)); left.appendChild(el("div","gloss-en",g.en.join("、")));
    var right=el("div"); right.appendChild(el("div","gloss-def",g.definition));
    if(g.note) right.appendChild(el("div","gloss-note",g.note));
    if(g.retired.length){
      var old=el("div","gloss-old"); old.appendChild(document.createTextNode("不要再用："));
      g.retired.forEach(function(t){ old.appendChild(el("s",null,t)); });
      right.appendChild(old);
    }
    row.appendChild(left); row.appendChild(right); card.appendChild(row);
  });
  glossHost.appendChild(card);
});
document.querySelectorAll(".gloss-link").forEach(function(a){ a.addEventListener("click",function(ev){ ev.preventDefault(); document.getElementById("glossary").scrollIntoView({block:"start"}); }); });
var toc=document.getElementById("toc");
toc.appendChild(tocColumn("pending","未完成")); toc.appendChild(tocColumn("done","已完成"));
fillGroup(document.getElementById("pending"),"pending");
fillGroup(document.getElementById("done"),"done");
document.querySelectorAll(".big a").forEach(function(a){ a.addEventListener("click",function(ev){ ev.preventDefault(); go(a.getAttribute("href").slice(1)); }); });
var sum=document.getElementById("summary");
DATA.project_order.forEach(function(p){
  var d=el("div"); d.appendChild(el("b",null,DATA.projects[p]));
  var t=DATA.totals[p]; d.appendChild(document.createTextNode("已做 "+t.done+"｜未做 "+t.pending+"｜不適用 "+t["n/a"])); sum.appendChild(d);
});
var phaseHost=document.getElementById("phases");
DATA.phase_order.forEach(function(k){
  var c=el("div","card"); c.appendChild(el("h3",null,DATA.phases[k])); c.appendChild(el("p","code",k+"｜未做 "+DATA.phase_counts[k]+" 格")); phaseHost.appendChild(c);
});
var toTop=document.getElementById("totop");
toTop.addEventListener("click",function(){ window.scrollTo(0,0); var h=document.querySelector("h1"); if(h){ h.setAttribute("tabindex","-1"); h.focus({preventScroll:true}); } });
function syncTop(){ toTop.classList.toggle("show", toc.getBoundingClientRect().bottom<0); }
window.addEventListener("scroll",syncTop,{passive:true}); syncTop();
"""


def _combined(statuses: dict[str, Any]) -> dict[str, Any]:
    """One status for a row that spans several strategies (FLEET.*): done only
    if every strategy is done, n/a only if every one is n/a, else pending."""
    states = {s["state"] for s in statuses.values()}
    if states == {"done"}:
        return {"state": "done"}
    if states == {"n/a"}:
        return {"state": "n/a"}
    return {"state": "pending"}


def render_risk_register(catalog: dict[str, Any], registry: dict[str, Any]) -> str:
    projects = registry["projects"]
    phases = registry["phases"]
    rows_by_code = {row["code"]: row for row in registry["catalog"]}
    entries = []
    for entry in catalog["entries"]:
        code = entry["code"]
        row = rows_by_code[code]
        project_keys = owners(code)
        fleet = code.startswith("FLEET.")
        notes = []
        for key, label in (("behaviour", "行為"), ("emits_event", "寫進事件日誌")):
            for project in project_keys:
                status = row[key][project]
                if status["state"] == "pending":
                    who = f"{projects[project]}：" if fleet else ""
                    notes.append(f"{label}未做 — {who}{status['reason']}（預定：{phases[status['phase']]}）")
        message = entry["operator_message"]
        entries.append({
            "code": code, "tier": entry["risk_tier"], "title": entry["title"],
            "bot": "fleet" if fleet else project_keys[0],
            "bot_label": BOT_LABEL_FLEET if fleet else projects[project_keys[0]],
            "what": message["what"], "direction": message["direction"],
            "steps": message["steps"] if entry["risk_tier"] in ("R2", "R3") else [],
            "ai_prompt": message.get("ai_prompt"),
            "behaviour": _combined(row["behaviour"]) if fleet else row["behaviour"][project_keys[0]],
            "emits_event": _combined(row["emits_event"]) if fleet else row["emits_event"][project_keys[0]],
            "notes": notes,
            "open": bool(notes),
        })
    bots = [{"id": p, "label": projects[p]} for p in STRATEGY_PROJECTS] + [{"id": "fleet", "label": BOT_LABEL_FLEET}]
    data = {"tiers": TIERS, "entries": entries, "bots": bots}
    count = len(entries)
    open_count = sum(1 for e in entries if e["open"])
    body = f"""<div class="wrap">
  <div class="eyebrow">交易機隊 · 錯誤處理設計（錯誤目錄 v2）</div>
  <h1>機隊風險登記冊</h1>
  <p class="lede">
    四支策略目前所有已知的「出問題」情況，共 <b>{count} 種</b>。排列的依據是<b>「人能不能做出跟自動處理不一樣的決定」</b>，
    不是事情多嚴重：R0、R1 你沒有決定可做，所以不會通知你；R2 系統會先自己試，試不起來才找你；R3 一定要人處理。
    每一條下面標示這支策略<b>目前實際做到了沒有</b>——其中 <b>{open_count} 種</b>還有部分沒做完，點「只看還沒做完的」可以篩出來。
  </p>
  <div class="legend">
{''.join(f'''    <div class="legend-item"><span class="legend-code" style="color:var(--{t['id']})">{t['id']}</span><span class="legend-name">{t['title']}</span><span class="legend-sub">{t['sub']}</span></div>
''' for t in TIERS)}  </div>
  <div id="filters"></div>
  <div id="register"></div>
  <div class="foot">
    資料來源：trade-alerts <code>{catalog['catalog_version']}</code>（錯誤分類）與 <code>{registry['registry_version']}</code>（各策略實際進度，{registry['updated_at']} 盤點）。
    本頁由 <code>scripts/render_guides.py</code> 產生，請勿手改；手改會讓 CI 失敗。另見同目錄的「機隊一致性登記冊」。
  </div>
</div>
<button type="button" id="totop" aria-label="回到最上方" title="回到最上方">↑</button>"""
    return _page("機隊風險登記冊", body, data, _RISK_JS, _RISK_CSS)


def _line(status: dict[str, Any], aspect: str | None, phases: dict[str, str]) -> dict[str, Any]:
    state = status["state"]
    text = status["evidence"] if state == "done" else status["reason"]
    return {"aspect": aspect, "state": state, "text": text,
            "phase": phases[status["phase"]] if state == "pending" else None}


def _dot(states: set[str]) -> str:
    """One strategy's colour in the four-dot strip: pending wins, then done."""
    if not states:
        return "none"
    if "pending" in states:
        return "pending"
    return "done" if "done" in states else "na"


def rollout_items(catalog: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Every capability and catalog row as one page item.  ``complete`` means no
    cell is pending -- every applicable strategy is done or n/a, nothing left to do.
    ``recent_changes`` (see the registry schema) overlays a page-only "recent" marker
    for whatever the latest edit touched, in two flavours that never affect ``complete``
    (which always reflects the real pending/done/n-a state): a ``completed`` entry turns
    an otherwise done/n-a cell's dot gold for exactly the (kind, id, project) it names,
    and always flags the item -- a rule whose named aspect just flipped while its other
    aspect is still pending keeps its pending dot (there is still work left) but must
    still show up as "what changed"; an ``added`` entry (a brand-new row this edit introduced, which has no done/n-a cell
    to point at yet) just flags the whole item so it still shows up as "what changed"."""
    projects, phases = registry["projects"], registry["phases"]
    titles = {entry["code"]: (entry["risk_tier"], entry["title"]) for entry in catalog["entries"]}
    items = []
    for capability in registry["capabilities"]:
        rows = [{"label": projects[p], "lines": [_line(capability["status"][p], None, phases)]}
                for p in STRATEGY_PROJECTS if p in capability["status"]]
        states = {p: {capability["status"][p]["state"]} if p in capability["status"] else set() for p in STRATEGY_PROJECTS}
        items.append({"kind": "cap", "id": capability["id"], "anchor": f"cap-{capability['id']}", "title": capability["title"],
                      "sub": capability["description"], "rows": rows, "states": states})
    for row in registry["catalog"]:
        tier, title = titles[row["code"]]
        present = [p for p in STRATEGY_PROJECTS if p in row["behaviour"]]
        rows = [{"label": projects[p], "lines": [_line(row["behaviour"][p], "行為", phases),
                                                 _line(row["emits_event"][p], "寫進事件日誌", phases)]} for p in present]
        states = {p: ({row["behaviour"][p]["state"], row["emits_event"][p]["state"]} if p in present else set())
                  for p in STRATEGY_PROJECTS}
        items.append({"kind": "rule", "id": row["code"], "anchor": f"rule-{row['code']}", "title": f"{tier}｜{title}",
                      "sub": row["code"], "rows": rows, "states": states})
    changes = registry.get("recent_changes") or []
    completed_set = {(c["kind"], c["id"], c["project"]) for c in changes if c.get("type", "completed") == "completed"}
    added_set = {(c["kind"], c["id"]) for c in changes if c.get("type") == "added"}
    for item in items:
        states = item.pop("states")
        item["dots"] = {p: _dot(s) for p, s in states.items()}
        item["complete"] = "pending" not in set().union(*states.values())
        for p in STRATEGY_PROJECTS:
            if item["dots"][p] in ("done", "na") and (item["kind"], item["id"], p) in completed_set:
                item["dots"][p] = "recent"
        item["has_recent"] = any((item["kind"], item["id"], p) in completed_set for p in STRATEGY_PROJECTS)
        item["added_recent"] = (item["kind"], item["id"]) in added_set
    return items


def _glossary_groups(glossary: dict[str, Any]) -> list[dict[str, Any]]:
    """Entries grouped by category, in the order categories first appear."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in glossary["entries"]:
        groups.setdefault(entry["category"], []).append(
            {k: entry.get(k) for k in ("id", "zh", "en", "definition", "retired", "note")})
    return [{"category": category, "entries": entries} for category, entries in groups.items()]


def render_rollout_register(catalog: dict[str, Any], registry: dict[str, Any], glossary: dict[str, Any]) -> str:
    projects = registry["projects"]
    phases = registry["phases"]
    totals = {p: {"done": 0, "pending": 0, "n/a": 0} for p in STRATEGY_PROJECTS}
    phase_counts = {k: 0 for k in phases}
    statuses = [s for c in registry["capabilities"] for s in c["status"].items()]
    statuses += [s for row in registry["catalog"] for key in ("behaviour", "emits_event") for s in row[key].items()]
    for project, status in statuses:
        totals[project][status["state"]] += 1
        if status["state"] == "pending":
            phase_counts[status["phase"]] += 1
    items = rollout_items(catalog, registry)
    n_done = sum(1 for i in items if i["complete"])
    n_pending = len(items) - n_done
    by_key = {(i["kind"], i["id"]): i for i in items}
    recent_summary = []
    for change in registry.get("recent_changes") or []:
        item = by_key.get((change["kind"], change["id"]))
        if item is None:
            continue
        project = change.get("project")
        recent_summary.append({
            "anchor": item["anchor"], "title": item["title"],
            "project": projects[project] if project else None, "note": change["note"],
        })
    data = {
        "projects": projects, "project_order": list(STRATEGY_PROJECTS), "phases": phases,
        "phase_order": list(phases), "phase_counts": phase_counts, "totals": totals, "items": items,
        "recent_summary": recent_summary, "glossary": _glossary_groups(glossary),
    }
    sources = "；".join(
        f"{html.escape(registry['projects'][p])} <code>{html.escape(s['repo'])}@{html.escape(s['branch'])} {html.escape(s['commit'][:7])}</code>"
        for p, s in ((p, registry["sources"][p]) for p in STRATEGY_PROJECTS)
    )
    order = "、".join(html.escape(projects[p]) for p in STRATEGY_PROJECTS)
    body = f"""<div class="wrap">
  <div class="eyebrow">交易機隊 · 四支策略做到哪裡了</div>
  <h1>機隊一致性登記冊</h1>
  <p class="lede">
    每一項機隊功能、每一條錯誤處理規則，在四支策略裡<b>實際做到了沒有</b>。
    <b>「已做」＝正式機已經在跑</b>（正式機分支 <code>operations</code> 上有），只合併到開發主幹、或只在開發機上的一律算「未做」；
    「未做」會寫預定在哪一關做，「不適用」會寫理由，漏寫 CI 會擋下來。
    看不懂某個名詞？看最下面的 <a class="gloss-link" href="#glossary">名詞對照表</a>。
  </p>
  <div class="big">
    <a class="c-pending" href="#group-pending"><b>{n_pending}</b><span>項未完成——還有策略沒做到</span></a>
    <a class="c-done" href="#group-done"><b>{n_done}</b><span>項已完成——四支都到位，不用再動</span></a>
  </div>
  <div class="summary" id="summary"></div>
  <p class="dot-legend">
    <span>每項右邊的四個點依序是 {order}：</span>
    <span><i class="dot dot-done"></i>已做</span><span><i class="dot dot-pending"></i>未做</span>
    <span><i class="dot dot-na"></i>不適用</span><span><i class="dot dot-none"></i>跟這支無關</span>
    <span><i class="dot dot-recent"></i>🆕 最新變動</span>
  </p>
  <div class="recent-box" id="recentBox" hidden>
    <h3>🆕 最新變動</h3>
    <ul id="recentList"></ul>
  </div>
  <nav class="toc" id="toc" aria-label="目錄"></nav>

  <div class="group-head c-pending" id="group-pending"><h2>未完成</h2><span class="n">{n_pending} 項</span></div>
  <p class="group-sub">至少有一支策略還沒做到。黃色「未做」旁邊的虛線框是預定在哪一關做。</p>
  <div id="pending"></div>

  <div class="group-head c-done" id="group-done"><h2>已完成</h2><span class="n">{n_done} 項</span></div>
  <p class="group-sub">每支相關的策略都已做到或註明不適用，不用再動。點一下可以展開看證據。</p>
  <div id="done"></div>

  <div class="group-head" id="group-phases" style="--c:var(--ink-soft)"><h2>預定的關卡</h2></div>
  <p class="group-sub">「未做」算的是格數：一項功能在兩支策略未做就算兩格。</p>
  <div id="phases" class="phase-list"></div>

  <div class="group-head" id="glossary" style="--c:var(--accent)"><h2>名詞對照表</h2><span class="n">{len(glossary['entries'])} 條</span></div>
  <p class="group-sub">整個專案給人看的文字一律用這裡的中文名；「不要再用」的舊叫法，自動檢查會擋。英文代號照現況列出，方便對照程式與設定檔。</p>
  <div id="glossaryHost"></div>
  <div class="foot">
    資料來源：trade-alerts <code>{registry['registry_version']}</code>（{registry['updated_at']} 對四個 repo 逐項盤點）、<code>{catalog['catalog_version']}</code> 與 <code>{glossary['glossary_version']}</code>。
    「檔案:行號」證據對應的版本：{sources}。
    本頁由 <code>scripts/render_guides.py</code> 產生，請勿手改；手改會讓 CI 失敗。
  </div>
</div>
<button type="button" id="totop" aria-label="回到最上方" title="回到最上方">↑</button>"""
    return _page("機隊一致性登記冊", body, data, _ROLLOUT_JS, _ROLLOUT_CSS)


def rendered_pages() -> dict[Path, str]:
    catalog = load_error_catalog()
    registry = load_rollout_registry()
    glossary = load_glossary()
    return {RISK_PAGE: render_risk_register(catalog, registry),
            ROLLOUT_PAGE: render_rollout_register(catalog, registry, glossary)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if a committed page differs from a fresh render")
    args = parser.parse_args(argv)
    stale = []
    for path, html in rendered_pages().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != html:
                stale.append(path)
        else:
            path.write_text(html, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("stale (run scripts/render_guides.py): " + ", ".join(str(p.relative_to(ROOT)) for p in stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
