"""Check every file:line the rollout registry cites against the strategy repos.

    python scripts/verify_registry_evidence.py [--repos-root ~]

``registry_problems`` can only see the registry itself; whether a ``done``
cell's evidence points at real code lives in four other (private) repos, so
this runs by hand before a registry change goes to review, not in CI.  For
every path (and line) in a cell's ``evidence`` or ``reason`` it reads the file
at the commit in ``sources`` -- the live branch -- and reports:

* a ``done`` cell citing a file that does not exist at that commit (saying
  whether it exists on ``origin/development``: the usual cause is dev-only
  code marked done);
* a ``pending`` / ``n/a`` cell citing a file that exists neither at that
  commit nor on ``origin/development`` (their reasons may describe dev-only
  code, but not code that exists nowhere);
* a cited line past the end of the file.
* a ``done`` cell with no file citation at all -- "done" has to point at
  something a reviewer can open.

It prints each ``done`` citation with the cited line so a reviewer can see
that it is the claimed code.  Exit 1 if anything is wrong.

Changing a ``sources`` commit moves lines, and "the line exists" cannot see
that a citation now points at different code (2026-09-26 and 2026-10-04: 108
citations silently pointed elsewhere after a ``sources`` change, and this
script still said 0 problems).  So it also compares the registry against a
baseline (``--against``, default ``origin/main``): for every cell whose
project ``sources`` commit changed, each cited line must read the same -- and
sit in the same function -- at the old commit (old line number) as at the new
commit (new line number).  Two kinds of mismatch:

* ``shifted`` -- the old line's text still exists, once, in the same function
  at the new commit on another line number, so the citation now points at the
  wrong code.  Always fails.
* ``changed`` -- the old line's text was edited or removed, moved to another
  function, or has several equal lines to choose from.  Nothing can say
  whether the citation is still right, so it fails
  and prints both lines for a human to read; ``--accept-changed`` turns those
  into notes once someone has (put the printed list in the review attachment).

A cell whose citations were rewritten (different count or files) cannot be
paired and is listed for a human to compare.

``--relocate`` repairs the ``shifted`` ones it can place unambiguously: it moves
the citation to the line holding the same text in the same function at the new
commit and rewrites the registry JSON; whatever it cannot place is reported,
never guessed.  ``--no-compare`` skips the baseline comparison.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
REGISTRY_RELPATH = "src/trade_alerts/catalog/fleet-rollout-registry.json"
REGISTRY_PATH = ROOT / REGISTRY_RELPATH

from trade_alerts.rollout_registry import load_rollout_registry  # noqa: E402

# A path under a known top-level directory, or a bare ``name.py`` (my-crypto
# keeps its modules at the repo root), optionally followed by ``:line``.
_CITATION = re.compile(r"(?<![\w./-])((?:(?:src|scripts|tools|tests|docs|deploy)/[\w./-]+\.\w+)|[\w-]+\.py)(?::(\d+))?")


# A bare ``:line`` (``…bot.py:844 … :779 …``) is shorthand for the last path
# cited before it.  2026-09-25: an evidence text cited runner.py lines as bare
# ``:330``/``:385`` right after an executor.py path, so a reader resolved them
# to the wrong file and nothing here noticed -- bare lines were not checked.
_BARE_LINE = re.compile(r"(?<![\w./:-]):(\d+)(?![\d:])")


def citation_spans(text: str) -> list[tuple[str, int | None, tuple[int, int] | None]]:
    """Every cited path with its line and the ``(start, end)`` of the line digits
    in ``text`` (None when the citation has no line), in reading order.  Bare
    ``:line`` shorthands are resolved against the path cited just before them
    (the way a reader resolves it)."""
    named = [(m.start(), m.end(), m.group(1), int(m.group(2)) if m.group(2) else None,
              m.span(2) if m.group(2) else None) for m in _CITATION.finditer(text)]
    found = [(start, path, line, span) for start, _end, path, line, span in named]
    for m in _BARE_LINE.finditer(text):
        if any(start <= m.start() < end for start, end, _path, _line, _span in named):
            continue
        before = [path for start, _end, path, _line, _span in named if start < m.start()]
        if before:
            found.append((m.start(), before[-1], int(m.group(1)), m.span(1)))
    found.sort(key=lambda item: item[0])
    return [(path, line, span) for _, path, line, span in found]


def citations(text: str) -> list[tuple[str, int | None]]:
    """Every cited path, plus every bare ``:line`` resolved against the path
    cited just before it (the way a reader resolves it)."""
    return [(path, line) for path, line, _span in citation_spans(text)]


def _cells(registry):
    for capability in registry["capabilities"]:
        for project, status in capability["status"].items():
            yield f"capability {capability['id']}", project, status
    for row in registry["catalog"]:
        for key in ("behaviour", "emits_event"):
            for project, status in row[key].items():
                yield f"{row['code']} {key}", project, status


def _show(clone: Path, ref: str, path: str) -> str | None:
    result = subprocess.run(["git", "-C", str(clone), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def _status_text(status: dict) -> str:
    return " ".join(str(status.get(key, "")) for key in ("evidence", "reason"))


_DEF = re.compile(r"^(\s*)(?:async\s+)?(?:def|class)\s+(\w+)")


def _scope(lines: list[str], line_no: int, path: str) -> str | None:
    """The function (or class) a line sits in; ``<module>`` at top level; None for
    files that are not Python, where only the line text can be compared."""
    if not path.endswith(".py"):
        return None
    text = lines[line_no - 1]
    own = _DEF.match(text)
    if own:
        return own.group(2)
    indent = len(text) - len(text.lstrip())
    for j in range(line_no - 2, -1, -1):
        outer = _DEF.match(lines[j])
        if outer and len(outer.group(1)) < indent:
            return outer.group(2)
    return "<module>"


def _relocate(old_lines: list[str], old_line: int, new_lines: list[str], path: str) -> tuple[int | None, str]:
    """Where the line ``old_line`` of ``old_lines`` is in ``new_lines``: the line with
    the same text in the same function, or, if several, the same-numbered
    occurrence within that function.  ``(None, why)`` when it cannot be placed."""
    text = old_lines[old_line - 1].strip()
    scope = _scope(old_lines, old_line, path)
    same_text = [n for n, line in enumerate(new_lines, 1) if line.strip() == text]
    if not same_text:
        return None, "no line with that text at the new commit"
    in_scope = [n for n in same_text if _scope(new_lines, n, path) == scope]
    if not in_scope:
        return None, f"that text exists only outside {scope} at the new commit"
    if len(in_scope) == 1:
        return in_scope[0], ""
    old_same = [n for n, line in enumerate(old_lines, 1)
                if line.strip() == text and _scope(old_lines, n, path) == scope]
    if len(old_same) == len(in_scope):
        return in_scope[old_same.index(old_line)], ""
    return None, f"{len(in_scope)} candidate lines in {scope}"


def baseline_registry(ref: str) -> dict | None:
    """The registry as committed at ``ref`` in this repo (None if unreadable)."""
    text = _show(ROOT, ref, REGISTRY_RELPATH)
    try:
        return json.loads(text) if text is not None else None
    except ValueError:
        return None


Reader = Callable[[str, str, str], "list[str] | None"]  # (project, commit, path) -> lines


def drift(old: dict, new: dict, read: Reader) -> dict:
    """Compare every citation of ``new`` against ``old`` for projects whose ``sources``
    commit changed.  Returns ``mismatches`` (one dict per citation that now reads
    differently: its ``kind`` -- shifted or changed -- cell ``status``, ``where``, ``project``, ``path``, both line
    numbers, the digits ``span`` in the cell text, both files' lines, ``reason``),
    ``rewritten`` (cells whose citations cannot be paired old-to-new, for a human
    to compare), and the ``compared`` / ``unreadable`` counts."""
    old_cells = {(where, project): status for where, project, status in _cells(old)}
    result = {"mismatches": [], "rewritten": [], "compared": 0, "unreadable": 0}
    for where, project, status in _cells(new):
        old_status = old_cells.get((where, project))
        old_commit = old["sources"][project]["commit"]
        new_commit = new["sources"][project]["commit"]
        if old_status is None or old_commit == new_commit:
            continue
        old_cites = citation_spans(_status_text(old_status))
        new_cites = citation_spans(_status_text(status))
        if not new_cites and not old_cites:
            continue
        if len(old_cites) != len(new_cites) or any(o[0] != n[0] for o, n in zip(old_cites, new_cites)):
            result["rewritten"].append(f"{where} / {project}")
            continue
        for (path, old_line, _), (_, new_line, span) in zip(old_cites, new_cites):
            if old_line is None or new_line is None:
                continue
            old_lines = read(project, old_commit, path)
            new_lines = read(project, new_commit, path)
            if old_lines is None or new_lines is None or old_line > len(old_lines) or new_line > len(new_lines):
                result["unreadable"] += 1
                continue
            result["compared"] += 1
            old_text, new_text = old_lines[old_line - 1].strip(), new_lines[new_line - 1].strip()
            if old_text != new_text:
                reason = f"line text differs: old {old_text[:70]!r} / new {new_text[:70]!r}"
            elif _scope(old_lines, old_line, path) != _scope(new_lines, new_line, path):
                reason = (f"same text but in {_scope(new_lines, new_line, path)}"
                          f" (was {_scope(old_lines, old_line, path)})")
            else:
                continue
            target, why = _relocate(old_lines, old_line, new_lines, path)
            # The old code is at one known place in the same function and the citation does not
            # point there: wrong.  Anything else (edited, removed, moved to another function, or
            # several equal lines to choose from) needs a human to read it.
            shifted = target is not None
            result["mismatches"].append({
                "kind": "shifted" if shifted else "changed", "target": target,
                "status": status, "where": where, "project": project, "path": path,
                "old_line": old_line, "new_line": new_line, "span": span, "reason": reason,
                "old_lines": old_lines, "new_lines": new_lines})
    return result


def apply_relocation(report: dict) -> tuple[list[str], list[str]]:
    """Rewrite the line numbers of ``report['mismatches']`` inside their cells (the
    status dicts of the registry that was compared).  Returns ``(moved, unresolved)``
    messages.  ``span`` offsets index the joined evidence/reason text, so edits go
    right to left and are mapped back to the field they fall in."""
    moved: list[str] = []
    unresolved: list[str] = []
    by_cell: dict[int, list[dict]] = {}
    for item in report["mismatches"]:
        if item["kind"] != "shifted":
            continue
        label = f"{item['where']} / {item['project']}: {item['path']}:{item['old_line']}->{item['new_line']}"
        target, why = _relocate(item["old_lines"], item["old_line"], item["new_lines"], item["path"])
        if target is None:
            unresolved.append(f"{label} -- {why}")
            continue
        moved.append(f"{label} => {item['path']}:{target}")
        by_cell.setdefault(id(item["status"]), []).append({**item, "target": target})
    for edits in by_cell.values():
        status = edits[0]["status"]
        fields = {key: str(status.get(key, "")) for key in ("evidence", "reason")}
        evidence_len = len(fields["evidence"])
        for item in sorted(edits, key=lambda e: e["span"][0], reverse=True):
            start, end = item["span"]
            key, shift = ("evidence", 0) if start < evidence_len else ("reason", evidence_len + 1)
            text = fields[key]
            fields[key] = text[:start - shift] + str(item["target"]) + text[end - shift:]
        for key, value in fields.items():
            if key in status:
                status[key] = value
    return moved, unresolved


def _compare_with_baseline(registry: dict, args: argparse.Namespace) -> int:
    old = baseline_registry(args.against)
    if old is None:
        print(f"FAIL cannot read the baseline registry at {args.against}: pass --against REF, or --no-compare to skip")
        return 1
    cache: dict[tuple[str, str, str], list[str] | None] = {}

    def read(project: str, commit: str, path: str) -> list[str] | None:
        key = (project, commit, path)
        if key not in cache:
            clone = args.repos_root / registry["sources"][project]["repo"].split("/", 1)[1]
            content = _show(clone, commit, path)
            cache[key] = content.splitlines() if content is not None else None
        return cache[key]

    report = drift(old, registry, read)
    if args.relocate and report["mismatches"]:
        moved, unresolved = apply_relocation(report)
        for message in moved:
            print(f"moved {message}")
        REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report = drift(old, registry, read)  # whatever is left is for a human
        for message in unresolved:
            print(f"UNRESOLVED {message}")
    failures = 0
    for item in report["mismatches"]:
        line = (f"{item['where']} / {item['project']}: {item['path']}:{item['old_line']}"
                f" (baseline) -> :{item['new_line']} -- {item['reason']}")
        if item["kind"] == "shifted":
            line += f"; the old line is now :{item['target']}"
        if item["kind"] == "changed" and args.accept_changed:
            print(f"note [changed, accepted] {line}")
        else:
            print(f"FAIL [{item['kind']}] {line}")
            failures += 1
    for cell in report["rewritten"]:
        print(f"note [rewritten, compare by hand] {cell}")
    kinds = [item["kind"] for item in report["mismatches"]]
    print(f"baseline {args.against}: {report['compared']} citation(s) compared, "
          f"{kinds.count('shifted')} shifted, {kinds.count('changed')} changed, "
          f"{len(report['rewritten'])} cell(s) rewritten, {report['unreadable']} unreadable")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repos-root", type=Path, default=Path.home(), help="directory holding the four clones")
    parser.add_argument("--against", default="origin/main", metavar="REF",
                        help="git ref of this repo holding the baseline registry (default origin/main)")
    parser.add_argument("--no-compare", action="store_true", help="skip the baseline comparison")
    parser.add_argument("--relocate", action="store_true",
                        help="move shifted citations to the same line at the new commit and rewrite the registry JSON")
    parser.add_argument("--accept-changed", action="store_true",
                        help="a human has read every 'changed' line (edited, removed or moved code); report them as notes")
    args = parser.parse_args(argv)
    registry = load_rollout_registry()
    failures = 0
    if not args.no_compare:
        failures += _compare_with_baseline(registry, args)
    for where, project, status in _cells(registry):
        source = registry["sources"][project]
        clone = args.repos_root / source["repo"].split("/", 1)[1]
        text = " ".join(str(status.get(key, "")) for key in ("evidence", "reason"))
        if status["state"] == "done" and not citations(status["evidence"]):
            print(f"FAIL [done] {where} / {project}: evidence cites no file -- {status['evidence']}")
            failures += 1
        for path, line in citations(text):
            content = _show(clone, source["commit"], path)
            label = f"[{status['state']}] {where} / {project}: {path}{f':{line}' if line else ''}"
            if content is None:
                content = _show(clone, "origin/development", path)
                if status["state"] == "done" or content is None:
                    print(f"FAIL {label} -- not at {source['branch']} {source['commit'][:7]}"
                          + (" (exists on development only)" if content is not None else " nor on development"))
                    failures += 1
                    continue
            lines = content.splitlines()
            if line is not None and line > len(lines):
                print(f"FAIL {label} -- line past end of file ({len(lines)} lines)")
                failures += 1
            elif status["state"] == "done" and line is not None:
                print(f"ok   {label} -> {lines[line - 1].strip()[:100]}")
    print(f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
