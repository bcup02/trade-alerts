#!/usr/bin/env python3
"""Check that the progress page and the rollout registry agree about what is finished (phase-sync3).

    python scripts/check_progress_links.py <progress page .html>        # items are read from the page's ITEMS
    python scripts/check_progress_links.py --items-json items.json      # or from a JSON list of items

A progress item may carry ``"registry": ["cap:<capability id>@seykota,momentum", "rule:<catalog code>#emits_event", ...]`` -- the
registry cells it is about (``@`` limits it to those strategies, ``#`` to one aspect of a rule; without them every
strategy and both aspects count).  Each link is checked
against the rollout registry on ``origin/main`` (or ``--registry FILE``):

* the item is ``done`` but a linked cell is still pending  -> error (the item was closed before the work was);
* the item is still open (``todo`` / ``active`` / ``waiting``) but every linked cell is done or n/a -> error
  (the work is finished, the item was forgotten -- the f-23e kind of leftover).  An item listed in the page's
  觀察區 (``WATCH``) is open on purpose -- it waits for a real event -- and is exempt from this one;
* a link that names no capability or catalog code, or is malformed -> error (a typo must not silently check nothing).

``skipped`` items are not checked (they will not be done).  Items without ``registry`` are not checked; the page is not
changed by this script.  Run it on the page file before publishing the progress page (收尾 SOP).
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
OPEN_STATUSES = ("todo", "active", "waiting")
FINISHED_STATES = ("done", "n/a")


def extract_items(page_html: str) -> list[dict[str, Any]]:
    """The progress items that are JSON lines in the page's ``var ITEMS = [ ... ];`` (the older JS-literal lines have no
    ``registry`` field and are skipped)."""
    start = page_html.find("var ITEMS = [")
    end = page_html.find("\n  ];", start)
    if start < 0 or end < 0:
        raise ValueError("no `var ITEMS = [ ... ];` block in the page")
    items = []
    for line in page_html[start:end].splitlines():
        line = line.strip()
        if line.startswith('{"id"') and line.endswith("},"):
            items.append(json.loads(line[:-1]))
    return items


def cells_for(registry: Mapping[str, Any], link: str) -> tuple[list[tuple[str, str, str]], str | None]:
    """``([(label, project, state), ...], problem)`` for one link string."""
    match = _LINK.match(link)
    if not match:
        return [], f"連結寫法不對：{link!r}（要 cap:<能力編號> 或 rule:<錯誤代碼>，可加 @策略,策略）"
    kind, ident, aspect, scope = match.groups()
    if aspect and kind == "cap":
        return [], f"連結 {link!r}：#面向只用在 rule"
    projects = scope.split(",") if scope else list(STRATEGY_PROJECTS)
    bad = [p for p in projects if p not in STRATEGY_PROJECTS]
    if bad:
        return [], f"連結 {link!r} 裡的策略名不認得：{bad}"
    cells: list[tuple[str, str, str]] = []
    if kind == "cap":
        capability = next((c for c in registry.get("capabilities") or [] if c.get("id") == ident), None)
        if capability is None:
            return [], f"登記冊沒有這個能力：{ident!r}"
        for project in projects:
            status = (capability.get("status") or {}).get(project)
            if status is not None:
                cells.append((f"能力 {ident}", project, status["state"]))
    else:
        row = next((r for r in registry.get("catalog") or [] if r.get("code") == ident), None)
        if row is None:
            return [], f"登記冊沒有這個錯誤代碼：{ident!r}"
        for one in ((aspect,) if aspect else ("behaviour", "emits_event")):
            for project in projects:
                status = (row.get(one) or {}).get(project)
                if status is not None:
                    cells.append((f"規則 {ident} {one}", project, status["state"]))
    if not cells:
        return [], f"連結 {link!r} 指到的策略在那一格裡都沒有格子（名字寫錯，或該格不屬於它們）"
    return cells, None


def extract_watch_ids(page_html: str) -> set[str]:
    """The item ids in the page's ``var WATCH = [ ... ];`` (the 觀察區)."""
    start = page_html.find("var WATCH = [")
    end = page_html.find("\n  ];", start)
    if start < 0 or end < 0:
        return set()
    return set(re.findall(r'\{"id":\s*"([^"]+)"', page_html[start:end]))


def link_problems(items: Iterable[Mapping[str, Any]], registry: Mapping[str, Any], watch_ids: Iterable[str] = ()) -> list[str]:
    problems: list[str] = []
    watching = set(watch_ids)
    for item in items:
        links = item.get("registry")
        if links is None:
            continue
        name = f"{item.get('id')}（{str(item.get('title', ''))[:24]}）"
        if not isinstance(links, list) or not links or not all(isinstance(x, str) for x in links):
            problems.append(f"{name}：registry 要是非空的字串清單")
            continue
        cells: list[tuple[str, str, str]] = []
        for link in links:
            found, problem = cells_for(registry, link)
            if problem:
                problems.append(f"{name}：{problem}")
            cells += found
        if not cells:
            continue
        status = item.get("status")
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
    if args.items_json:
        items = json.loads(args.items_json.read_text(encoding="utf-8"))
    else:
        text = args.page.read_text(encoding="utf-8")
        items, watch = extract_items(text), extract_watch_ids(text)
    registry = load_rollout_registry(args.registry) if args.registry else load_registry_from_main()
    linked = [i for i in items if i.get("registry") is not None]
    problems = link_problems(items, registry, watch)
    print(f"進度項目 {len(items)} 項，其中 {len(linked)} 項連了登記冊格子；問題 {len(problems)} 個")
    for line in problems:
        print("  ✗ " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
