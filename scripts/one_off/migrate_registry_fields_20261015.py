#!/usr/bin/env python3
"""One-off (2026-10-15, phase-sync4): split the long prose of every ``done`` rollout-registry cell into fields.

Kept in the repo so the change can be reviewed and re-run on the pre-migration registry.  For each done cell ``evidence``
becomes ``evidence`` (what the code does, with the file:line citations) + ``limit`` (the text after ``限制：``) +
``verified_at`` (the date of the A1 check, when the cell has one), and the long A1 verification paragraph
(``A1 正式機（新）…執行環境…``) moves to ``docs/registry-a1-checks.json``.  Nothing is lost: the script checks, per cell, that
evidence + a1_check + limit read back equal the original text up to whitespace, and that ``evidence`` still cites a file
(the strategy repos' self-checks need that).  A cell whose citations all sit inside the A1 paragraph is left alone.

    python scripts/one_off/migrate_registry_fields_20261015.py            # rewrite the two files
    python scripts/one_off/migrate_registry_fields_20261015.py --check    # only verify, print the summary
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "src" / "trade_alerts" / "catalog" / "fleet-rollout-registry.json"
ARCHIVE = ROOT / "docs" / "registry-a1-checks.json"

_A1 = re.compile(r"A1 正式機（新）(?:實際)?執行環境")
_LIMIT = "限制："
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# the check date counts only when the header parenthesis right after "執行環境" says it was a read-only check
# ("（唯讀查證，2026-10-14 台北）", "（2026-10-04 台北約 20:16 唯讀查）"); a date elsewhere in the paragraph is usually the deploy date (review of #200)
_CHECK_HEADER = re.compile(r"執行環境（([^）]*)）")
_CITATION = re.compile(r"(?<![\w./-])((?:(?:src|scripts|tools|tests|docs|deploy)/[\w./-]+\.\w+)|[\w-]+\.py)")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def split_evidence(text: str) -> dict[str, str | None]:
    """``{"evidence", "a1_check", "limit", "verified_at"}`` -- or the text unchanged when splitting would leave no citation."""
    a1 = _A1.search(text)
    start_a1 = a1.start() if a1 else None
    start_limit = text.find(_LIMIT, start_a1 or 0)
    if start_limit < 0 and start_a1 is None:
        return {"evidence": text, "a1_check": None, "limit": None, "verified_at": None}
    if start_limit < 0:
        start_limit = None
    cut = min(x for x in (start_a1, start_limit) if x is not None)
    core = text[:cut].rstrip()
    a1_text = text[start_a1:start_limit].strip() if start_a1 is not None else None
    limit = text[start_limit + len(_LIMIT):].strip() if start_limit is not None else None
    if not core or not _CITATION.search(core):
        return {"evidence": text, "a1_check": None, "limit": None, "verified_at": None}
    return {"evidence": core, "a1_check": a1_text, "limit": limit, "verified_at": check_date(a1_text)}


def check_date(a1_text: str | None) -> str | None:
    """The date the A1 paragraph says the read-only check ran, or ``None`` when it only carries other dates (deploy dates)."""
    header = _CHECK_HEADER.search(a1_text or "")
    found = _DATE.search(header.group(1)) if header and "唯讀查" in header.group(1) else None
    return found.group(0) if found else None


def recompose(parts: dict[str, str | None]) -> str:
    return " ".join(x for x in (parts["evidence"], parts["a1_check"], (_LIMIT + parts["limit"]) if parts["limit"] else None) if x)


def cells(registry: dict):
    for capability in registry["capabilities"]:
        for project, status in capability["status"].items():
            yield f"cap:{capability['id']}|{project}", status
    for row in registry["catalog"]:
        for aspect in ("behaviour", "emits_event"):
            for project, status in row[aspect].items():
                yield f"rule:{row['code']}:{aspect}|{project}", status


def main(argv: list[str]) -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    archive: dict[str, dict[str, str]] = {}
    split = kept = 0
    for key, status in cells(registry):
        if status["state"] != "done":
            continue
        original = status["evidence"]
        parts = split_evidence(original)
        assert _squash(recompose(parts)) == _squash(original), f"not lossless: {key}"
        if parts["a1_check"] is None and parts["limit"] is None:
            kept += 1
            continue
        split += 1
        status["evidence"] = parts["evidence"]
        if parts["verified_at"]:
            status["verified_at"] = parts["verified_at"]
        if parts["limit"]:
            status["limit"] = parts["limit"]
        if parts["a1_check"]:
            archive[key] = {"a1_check": parts["a1_check"]}
    print(f"done cells split: {split}, left as they were: {kept}, A1 paragraphs archived: {len(archive)}")
    if "--check" in argv:
        return 0
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ARCHIVE.write_text(json.dumps({
        "note": "The long A1 verification paragraphs of the rollout registry's done cells (moved out of the cells on 2026-10-15, phase-sync4). "
                "Key = cell (cap:<id>|<project> or rule:<code>:<aspect>|<project>); the cell's evidence keeps the file:line citations.",
        "cells": dict(sorted(archive.items())),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
