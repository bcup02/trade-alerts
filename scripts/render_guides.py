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
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      --paper:#18150F; --paper-raised:#211D16; --line:#332D22;
      --ink:#EDE6D8; --ink-soft:#B7AF9C; --ink-faint:#847C6C;
      --accent:#C6A0C8; --accent-bg:#302733; --accent-line:#5A455C;
      --R3:#E58A7C; --R3-bg:#3A241F; --R2:#D9B364; --R2-bg:#382D18;
      --R1:#7FC6A2; --R1-bg:#1D3227; --R0:#A6AD97; --R0-bg:#292B21;
      --done:#7FC6A2; --done-bg:#1D3227; --pending:#D9B364; --pending-bg:#382D18; --na:#A6AD97; --na-bg:#292B21;
    }
  }
  :root[data-theme="dark"]{
    --paper:#18150F; --paper-raised:#211D16; --line:#332D22;
    --ink:#EDE6D8; --ink-soft:#B7AF9C; --ink-faint:#847C6C;
    --accent:#C6A0C8; --accent-bg:#302733; --accent-line:#5A455C;
    --R3:#E58A7C; --R3-bg:#3A241F; --R2:#D9B364; --R2-bg:#382D18;
    --R1:#7FC6A2; --R1-bg:#1D3227; --R0:#A6AD97; --R0-bg:#292B21;
    --done:#7FC6A2; --done-bg:#1D3227; --pending:#D9B364; --pending-bg:#382D18; --na:#A6AD97; --na-bg:#292B21;
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


def _page(title: str, body: str, data: dict[str, Any], script: str) -> str:
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1).replace("</", "<\\/")
    return (f"<title>{title}</title>\n{_FONTS}\n<style>{_CSS}</style>\n\n{body}\n\n"
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
function statusText(s, phases){
  if(s.state==="done") return "已做："+s.evidence;
  if(s.state==="n/a") return "不適用："+s.reason;
  return "未做："+s.reason+"（預定："+(phases[s.phase]||s.phase)+"）";
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
    [["行為",e.behaviour],["白話通知",e.emits_event]].forEach(function(pair){
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
"""

_ROLLOUT_JS = _JS_HELPERS + r"""
var pick={project:"all",state:"all"};
var items=[];
function card(host, title, sub, subClass, statuses){
  var c=el("div","card"); c.appendChild(el("h3",null,title)); if(sub) c.appendChild(el("p",subClass,sub));
  var g=el("div","grid");
  statuses.forEach(function(s){
    var who=el("span","who",s.label); var what=el("span");
    what.appendChild(el("span","st "+STATE_CLASS[s.status.state],STATE_LABEL[s.status.state]));
    what.appendChild(document.createTextNode(" "+statusText(s.status,DATA.phases)));
    who.dataset.project=s.project; who.dataset.state=s.status.state; what.dataset.project=s.project; what.dataset.state=s.status.state;
    g.appendChild(who); g.appendChild(what); items.push(who); items.push(what);
  });
  c.appendChild(g); host.appendChild(c); return c;
}
var cards=[];
var capHost=document.getElementById("capabilities");
DATA.capabilities.forEach(function(cap){
  var c=card(capHost, cap.title, cap.description, "desc", DATA.project_order.map(function(p){return {project:p,label:DATA.projects[p],status:cap.status[p]};}));
  cards.push(c);
});
var entryHost=document.getElementById("entries");
DATA.catalog.forEach(function(row){
  var statuses=[];
  Object.keys(row.behaviour).sort(function(a,b){return DATA.project_order.indexOf(a)-DATA.project_order.indexOf(b);}).forEach(function(p){
    statuses.push({project:p,label:DATA.projects[p]+"｜行為",status:row.behaviour[p]});
    statuses.push({project:p,label:DATA.projects[p]+"｜白話通知",status:row.emits_event[p]});
  });
  cards.push(card(entryHost, row.tier+"｜"+row.title, row.code, "code", statuses));
});
var phaseHost=document.getElementById("phases");
DATA.phase_order.forEach(function(k){
  var c=el("div","card"); c.appendChild(el("h3",null,DATA.phases[k])); c.appendChild(el("p","code",k+"｜待做 "+DATA.phase_counts[k]+" 項")); phaseHost.appendChild(c);
});
var sum=document.getElementById("summary");
DATA.project_order.forEach(function(p){
  var d=el("div"); d.appendChild(el("b",null,DATA.projects[p]));
  var t=DATA.totals[p]; d.appendChild(document.createTextNode("已做 "+t.done+"｜未做 "+t.pending+"｜不適用 "+t["n/a"])); sum.appendChild(d);
});
function apply(){
  items.forEach(function(n){ n.hidden=!((pick.project==="all"||n.dataset.project===pick.project)&&(pick.state==="all"||n.dataset.state===pick.state)); });
  cards.forEach(function(c){ c.hidden=!Array.prototype.some.call(c.querySelectorAll(".grid > span"),function(n){return !n.hidden;}); });
}
var f=document.getElementById("filters"), a=el("div","filters"), b=el("div","filters"); f.appendChild(a); f.appendChild(b);
function rowsOf(p, s){ var t=DATA.totals[p]; return s ? t[s] : t.done+t.pending+t["n/a"]; }
function allRows(s){ return DATA.project_order.reduce(function(n,p){return n+rowsOf(p,s);},0); }
chipGroup(a,[{id:"all",label:"全部策略",n:allRows()}].concat(DATA.project_order.map(function(p){return {id:p,label:DATA.projects[p],n:rowsOf(p)};})),function(v){pick.project=v;apply();});
chipGroup(b,[{id:"all",label:"全部狀態",n:allRows()},{id:"pending",label:"只看未做",n:allRows("pending")},{id:"done",label:"已做",n:allRows("done")},{id:"n/a",label:"不適用",n:allRows("n/a")}],function(v){pick.state=v;apply();});
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
        for key, label in (("behaviour", "行為"), ("emits_event", "白話通知")):
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
</div>"""
    return _page("機隊風險登記冊", body, data, _RISK_JS)


def render_rollout_register(catalog: dict[str, Any], registry: dict[str, Any]) -> str:
    projects = registry["projects"]
    phases = registry["phases"]
    titles = {entry["code"]: (entry["risk_tier"], entry["title"]) for entry in catalog["entries"]}
    totals = {p: {"done": 0, "pending": 0, "n/a": 0} for p in STRATEGY_PROJECTS}
    phase_counts = {k: 0 for k in phases}
    for capability in registry["capabilities"]:
        for project, status in capability["status"].items():
            totals[project][status["state"]] += 1
            if status["state"] == "pending":
                phase_counts[status["phase"]] += 1
    catalog_rows = []
    for row in registry["catalog"]:
        tier, title = titles[row["code"]]
        catalog_rows.append({**row, "tier": tier, "title": title})
        for key in ("behaviour", "emits_event"):
            for project, status in row[key].items():
                totals[project][status["state"]] += 1
                if status["state"] == "pending":
                    phase_counts[status["phase"]] += 1
    data = {
        "projects": projects, "project_order": list(STRATEGY_PROJECTS), "phases": phases,
        "phase_order": list(phases), "phase_counts": phase_counts, "totals": totals,
        "capabilities": registry["capabilities"], "catalog": catalog_rows,
    }
    sources = "；".join(
        f"{html.escape(registry['projects'][p])} <code>{html.escape(s['repo'])}@{html.escape(s['branch'])} {html.escape(s['commit'][:7])}</code>"
        for p, s in ((p, registry["sources"][p]) for p in STRATEGY_PROJECTS)
    )
    body = f"""<div class="wrap">
  <div class="eyebrow">交易機隊 · 四支策略做到哪裡了</div>
  <h1>機隊一致性登記冊</h1>
  <p class="lede">
    每一項機隊功能、每一條錯誤處理規則，在四支策略裡<b>實際做到了沒有</b>。規則只有一條：
    沒做的一定要寫在這裡——<b>「未做」要寫目前狀況和預定在哪一關做</b>，<b>「不適用」要寫理由</b>。
    漏寫的話，自動檢查（CI）會擋下來，不會再有「只做了一支、沒人記得」。
    <b>「已做」指的是真倉已經在跑</b>（部署來源 <code>operations</code> 分支上有）；只合併到開發分支或只在測試機上的，一律算「未做」。
  </p>
  <div class="summary" id="summary"></div>
  <div id="filters"></div>
  <h2>機隊功能</h2>
  <div id="capabilities"></div>
  <h2>錯誤處理規則（依錯誤目錄逐條）</h2>
  <p class="lede">「行為」：這條錯誤發生時，策略有沒有照錯誤目錄說的處理。「白話通知」：有沒有寫進共用事件日誌——只有寫進去的，才會變成你手機上的白話通知。</p>
  <div id="entries"></div>
  <h2>預定的關卡</h2>
  <div id="phases"></div>
  <div class="foot">
    資料來源：trade-alerts <code>{registry['registry_version']}</code>（{registry['updated_at']} 對四個 repo 逐項盤點）與 <code>{catalog['catalog_version']}</code>。
    「檔案:行號」證據對應的版本：{sources}。
    本頁由 <code>scripts/render_guides.py</code> 產生，請勿手改；手改會讓 CI 失敗。
  </div>
</div>"""
    return _page("機隊一致性登記冊", body, data, _ROLLOUT_JS)


def rendered_pages() -> dict[Path, str]:
    catalog = load_error_catalog()
    registry = load_rollout_registry()
    return {RISK_PAGE: render_risk_register(catalog, registry), ROLLOUT_PAGE: render_rollout_register(catalog, registry)}


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
