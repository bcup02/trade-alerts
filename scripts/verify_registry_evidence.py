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
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trade_alerts.rollout_registry import load_rollout_registry  # noqa: E402

# A path under a known top-level directory, or a bare ``name.py`` (my-crypto
# keeps its modules at the repo root), optionally followed by ``:line``.
_CITATION = re.compile(r"(?<![\w./-])((?:(?:src|scripts|tools|tests|docs|deploy)/[\w./-]+\.\w+)|[\w-]+\.py)(?::(\d+))?")


# A bare ``:line`` (``…bot.py:844 … :779 …``) is shorthand for the last path
# cited before it.  2026-09-25: an evidence text cited runner.py lines as bare
# ``:330``/``:385`` right after an executor.py path, so a reader resolved them
# to the wrong file and nothing here noticed -- bare lines were not checked.
_BARE_LINE = re.compile(r"(?<![\w./:-]):(\d+)(?![\d:])")


def citations(text: str) -> list[tuple[str, int | None]]:
    """Every cited path, plus every bare ``:line`` resolved against the path
    cited just before it (the way a reader resolves it)."""
    named = [(m.start(), m.end(), m.group(1), int(m.group(2)) if m.group(2) else None) for m in _CITATION.finditer(text)]
    found = [(start, path, line) for start, _end, path, line in named]
    for m in _BARE_LINE.finditer(text):
        if any(start <= m.start() < end for start, end, _path, _line in named):
            continue
        before = [path for start, _end, path, _line in named if start < m.start()]
        if before:
            found.append((m.start(), before[-1], int(m.group(1))))
    return [(path, line) for _, path, line in sorted(found)]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repos-root", type=Path, default=Path.home(), help="directory holding the four clones")
    args = parser.parse_args(argv)
    registry = load_rollout_registry()
    failures = 0
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
