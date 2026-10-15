#!/usr/bin/env python3
"""Check that the progress page and the rollout registry agree about what is finished (phase-sync3).

    git fetch origin   # the registry is read from origin/main
    python scripts/check_progress_links.py <progress page .html>        # items are read from the page's ITEMS
    python scripts/check_progress_links.py --items-json items.json      # or from a JSON list of items

A progress item may carry ``"registry": ["cap:<capability id>@seykota,momentum", "rule:<catalog code>#emits_event", ...]``
-- the registry cells it is about (``@`` names the strategies, ``#`` one aspect of a rule; without them every strategy
and both aspects count).  Each link is checked against the rollout registry on ``origin/main`` (or ``--registry FILE``):

* the item is ``done`` but a linked cell is still pending  -> error (the item was closed before the work was);
* the item is still open (``todo`` / ``active`` / ``waiting``) but every linked cell is done or n/a -> error
  (the work is finished, the item was forgotten -- the f-23e kind of leftover).  An item listed in the page's
  觀察區 (``WATCH``) is open on purpose -- it waits for a real event -- and is exempt from this one;
* a link that is malformed, or names a capability / catalog code that does not exist, or a strategy / aspect that has
  no cell there (every strategy and aspect a link names must have one) -> error: a typo must not silently check nothing;
* an item with a ``registry`` field whose ``status`` is missing or not one of the known values -> error;
* an item that carries ``registry`` but cannot be read from the page at all -> error (``extract_items``).

``skipped`` items are not compared with the cells (they will not be done), their links are still validated.  Items
without ``registry`` are not checked.  The page is not changed.  Run it on the page file before publishing the progress
page (收尾 SOP).  The registry is the local ``origin/main`` -- ``git fetch`` first; the script cannot know it is stale.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trade_alerts.rollout_registry import STRATEGY_PROJECTS, load_rollout_registry  # noqa: E402

_LINK = re.compile(r"^(cap|rule):([A-Za-z0-9_.]+)(?:#(behaviour|emits_event))?(?:@([a-z\-]+(?:,[a-z\-]+)*))?$")
ASPECTS = ("behaviour", "emits_event")
OPEN_STATUSES = ("todo", "active", "waiting")
KNOWN_STATUSES = ("done", "skipped") + OPEN_STATUSES
FINISHED_STATES = ("done", "n/a")


# --- reading the page ---------------------------------------------------------------------------------------------

def _json_objects(region: str, key: str) -> list[dict[str, Any]]:
    """Every JSON object in ``region`` that starts with ``{"<key>"`` -- on one line or several, with or without a
    trailing comma.  JS-literal lines (unquoted keys) never match and are skipped."""
    decoder, found, position = json.JSONDecoder(), [], 0
    opener = re.compile(r'\{\s*"' + re.escape(key) + r'"')
    while True:
        match = opener.search(region, position)
        if not match:
            return found
        try:
            obj, end = decoder.raw_decode(region, match.start())
        except ValueError:
            position = match.start() + 1
            continue
        found.append(obj)
        position = end


#: Any way of writing the key `registry` that a JS object could use -- double, single or back quotes, or none -- followed by a
#: colon.  The check is "fail closed": every such spot must be a field of an item that was read, so a form this script cannot read
#: (single-quoted, unquoted, a JS literal item ...) is an error instead of a link that quietly checks nothing.  Text inside a
#: string that merely looks like `registry:` is a loud false alarm, never a silent pass.
_REGISTRY_KEY = re.compile(r"""(?<![\w\\.])(["'`]?)registry\1\s*:""")


def _block(page_html: str, name: str) -> str | None:
    start = page_html.find(f"var {name} = [")
    end = page_html.find("\n  ];", start)
    return None if start < 0 or end < 0 else page_html[start:end]


def extract_items(page_html: str) -> list[dict[str, Any]]:
    """The progress items written as JSON in the page's ``var ITEMS = [ ... ];``.

    An item that carries a ``registry`` field but could not be read (written as a JS literal -- quoted or unquoted key --
    or broken JSON) would be a link that silently checks nothing, so that is an error: the number of ``registry`` keys in
    the block must equal the number found in the items that were read."""
    block = _block(page_html, "ITEMS")
    if block is None:
        raise ValueError("no `var ITEMS = [ ... ];` block in the page")
    items = _json_objects(block, "id")
    in_text = len(_REGISTRY_KEY.findall(block))
    in_items = sum(1 for item in items if "registry" in item)
    if in_text != in_items:
        raise ValueError(f"頁面 ITEMS 裡有 {in_text} 處 registry 欄，只讀得到 {in_items} 個項目帶它：有項目的寫法讀不懂"
                         "（舊式 JS 物件寫法或 JSON 壞掉），連結會變成靜默不檢查，請改成 JSON 寫法")
    return items


def extract_watch_ids(page_html: str) -> set[str]:
    """The item ids in the page's ``var WATCH = [ ... ];`` (the 觀察區), read the same way as the items."""
    block = _block(page_html, "WATCH")
    return set() if block is None else {o["id"] for o in _json_objects(block, "id") if isinstance(o.get("id"), str)}


# --- the registry side --------------------------------------------------------------------------------------------

def cells_for(registry: Mapping[str, Any], link: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """``([(label, project, state), ...], problems)`` for one link string.

    Every (strategy, aspect) the link names must have a cell: a missing one is a problem of its own, and the cells that do
    exist are still returned so they are still compared."""
    match = _LINK.match(link)
    if not match:
        return [], [f"連結寫法不對：{link!r}（要 cap:<能力編號> 或 rule:<錯誤代碼>，可加 #面向 與 @策略,策略）"]
    kind, ident, aspect, scope = match.groups()
    if aspect and kind == "cap":
        return [], [f"連結 {link!r}：#面向只用在 rule"]
    projects = scope.split(",") if scope else list(STRATEGY_PROJECTS)
    unknown = [p for p in projects if p not in STRATEGY_PROJECTS]
    if unknown:
        return [], [f"連結 {link!r} 裡的策略名不認得：{unknown}"]
    cells: list[tuple[str, str, str]] = []
    missing: list[str] = []
    if kind == "cap":
        capability = next((c for c in registry.get("capabilities") or [] if c.get("id") == ident), None)
        if capability is None:
            return [], [f"登記冊沒有這個能力：{ident!r}"]
        for project in projects:
            status = (capability.get("status") or {}).get(project)
            if status is None:
                missing.append(f"能力 {ident} 對 {project} 沒有格子")
            else:
                cells.append((f"能力 {ident}", project, status["state"]))
    else:
        row = next((r for r in registry.get("catalog") or [] if r.get("code") == ident), None)
        if row is None:
            return [], [f"登記冊沒有這個錯誤代碼：{ident!r}"]
        for one in ((aspect,) if aspect else ASPECTS):
            for project in projects:
                status = (row.get(one) or {}).get(project)
                if status is None:
                    # a rule belongs to one strategy (or all, for FLEET.*): when no strategy was named, "all four" simply
                    # means the owners, so only a strategy the link named on purpose can be missing
                    if scope:
                        missing.append(f"規則 {ident} 的 {one} 對 {project} 沒有格子")
                else:
                    cells.append((f"規則 {ident} {one}", project, status["state"]))
    problems = [f"連結 {link!r}：{m}" for m in missing]
    if not cells and not problems:
        problems.append(f"連結 {link!r} 指不到任何格子")
    return cells, problems


def link_problems(items: Iterable[Mapping[str, Any]], registry: Mapping[str, Any], watch_ids: Iterable[str] = ()) -> list[str]:
    problems: list[str] = []
    watching = set(watch_ids)
    for item in items:
        if "registry" not in item:          # no field = nothing to check; a field with null is an invalid value, not "no field"
            continue
        links = item["registry"]
        name = f"{item.get('id')}（{str(item.get('title', ''))[:24]}）"
        status = item.get("status")
        if status not in KNOWN_STATUSES:
            problems.append(f"{name}：status {status!r} 不是已知的值（{'、'.join(KNOWN_STATUSES)}），連結沒辦法比對")
        if not isinstance(links, list) or not links or not all(isinstance(x, str) for x in links):
            problems.append(f"{name}：registry 要是非空的字串清單")
            continue
        cells: list[tuple[str, str, str]] = []
        for link in links:
            found, found_problems = cells_for(registry, link)
            problems += [f"{name}：{p}" for p in found_problems]
            cells += found
        if not cells:
            continue
        unfinished = [f"{label} / {project}" for label, project, state in cells if state not in FINISHED_STATES]
        if status == "done" and unfinished:
            problems.append(f"{name}：項目已完成，但連到的格子還沒做：" + "；".join(unfinished[:6]) + ("…" if len(unfinished) > 6 else ""))
        elif status in OPEN_STATUSES and not unfinished and item.get("id") not in watching:
            problems.append(f"{name}：項目還是「{status}」，但連到的 {len(cells)} 個格子都已做完或不適用：該結案了")
    return problems


def load_registry_from_main(root: Path = ROOT) -> dict[str, Any]:
    shown = subprocess.run(["git", "-C", str(root), "show", "origin/main:src/trade_alerts/catalog/fleet-rollout-registry.json"],
                           capture_output=True, text=True)
    if shown.returncode != 0:
        raise RuntimeError(f"cannot read the registry from origin/main in {root}: {shown.stderr.strip()[:160]}")
    return json.loads(shown.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page", nargs="?", type=Path, help="the progress page .html (its ITEMS are checked)")
    parser.add_argument("--items-json", type=Path, help="a JSON list of items instead of a page")
    parser.add_argument("--registry", type=Path, help="a registry JSON file (default: origin/main of this repo; run `git fetch` first)")
    args = parser.parse_args(argv)
    if bool(args.page) == bool(args.items_json):
        parser.error("give exactly one of: the page, or --items-json")
    watch: set[str] = set()
    try:
        if args.items_json:
            items = json.loads(args.items_json.read_text(encoding="utf-8"))
        else:
            text = args.page.read_text(encoding="utf-8")
            items, watch = extract_items(text), extract_watch_ids(text)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1
    registry = load_rollout_registry(args.registry) if args.registry else load_registry_from_main()
    linked = [i for i in items if "registry" in i]
    problems = link_problems(items, registry, watch)
    print(f"進度項目 {len(items)} 項，其中 {len(linked)} 項連了登記冊格子；問題 {len(problems)} 個")
    for line in problems:
        print("  ✗ " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
