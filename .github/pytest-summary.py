#!/usr/bin/env python3
"""Render pytest's JUnit XML as a short Markdown summary.

Writes ``pytest-summary.md`` (picked up by the PR-comment step) and appends the
same block to ``$GITHUB_STEP_SUMMARY``.  Never raises into CI: a missing or
unparseable report just produces a note so the comment step still has content.
"""
from __future__ import annotations

import os
import pathlib
import xml.etree.ElementTree as ET
from collections import Counter

REPORT = pathlib.Path("pytest.xml")
OUT = pathlib.Path("pytest-summary.md")


def _module_key(classname: str) -> str:
    """`tests.test_bot.TestX` -> `tests.test_bot`; leave bare modules alone."""
    key = classname or "?"
    if "." in key and key.rsplit(".", 1)[1][:1].isupper():
        key = key.rsplit(".", 1)[0]
    return key


def render() -> str:
    if not REPORT.is_file():
        return "⚠️ no `pytest.xml` — pytest did not get far enough to report."
    try:
        root = ET.parse(REPORT).getroot()
    except ET.ParseError as exc:
        return f"⚠️ could not parse `pytest.xml`: {exc}"

    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        return "⚠️ `pytest.xml` contained no <testsuite>."

    total = failures = errors = skipped = 0
    duration = 0.0
    per_module: Counter[str] = Counter()
    for suite in suites:
        total += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0"))
        errors += int(suite.get("errors", "0"))
        skipped += int(suite.get("skipped", "0"))
        duration += float(suite.get("time", "0") or 0)
        for case in suite.iter("testcase"):
            per_module[_module_key(case.get("classname", ""))] += 1

    passed = total - failures - errors - skipped
    headline = f"**{passed} passed**"
    for label, count in (("skipped", skipped), ("failed", failures), ("errored", errors)):
        if count:
            headline += f", {count} {label}"
    verdict = "✅ green" if failures == 0 and errors == 0 else "❌ not green"

    rows = "\n".join(f"| `{mod}` | {n} |" for mod, n in sorted(per_module.items()))
    return "\n".join(
        [
            f"### pytest — {headline}",
            "",
            f"{verdict} · {total} collected · {duration:.1f}s",
            "",
            "| module | tests |",
            "| --- | --: |",
            rows,
        ]
    )


def main() -> None:
    body = render()
    OUT.write_text(body + "\n", encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(body + "\n")
    print(body)


if __name__ == "__main__":
    main()
