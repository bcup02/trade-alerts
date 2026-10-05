"""Fleet glossary: one Chinese name per fleet concept, mapped to its English identifiers.

The fleet kept calling the same thing by several names (the repair bot had eight)
and different things by one name (真倉 meant both the live host and real-money
mode), so a reader could not tell whether two pages were talking about the same
thing.  ``catalog/fleet-glossary.json`` fixes one ``zh`` name per concept and
lists the ``retired`` names that must not be used any more; ``retired_hits`` is
what the tests run over every human-facing text in this repo.  Only Chinese
wording is governed here -- English identifiers (env vars, unit names, project
ids) are listed as they are, not renamed.
"""
from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

GLOSSARY_VERSION = "fleet-glossary/v1"
PACKAGED_GLOSSARY_NAME = "fleet-glossary.json"


def load_glossary(path: str | Path | None = None) -> dict[str, Any]:
    """Read the glossary -- by default the copy shipped inside this package."""
    if path is None:
        raw = resources.files("trade_alerts").joinpath("catalog", PACKAGED_GLOSSARY_NAME).read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("glossary_version") != GLOSSARY_VERSION:
        raise ValueError(f"not a {GLOSSARY_VERSION} document")
    return payload


def glossary_problems(glossary: Mapping[str, Any]) -> list[str]:
    """Every way the glossary contradicts itself; empty means usable."""
    problems: list[str] = []
    entries = glossary.get("entries") or []
    ids = [e.get("id") for e in entries]
    zhs = [e.get("zh") for e in entries]
    for label, values in (("id", ids), ("zh", zhs)):
        dupes = sorted({v for v in values if values.count(v) > 1})
        if dupes:
            problems.append(f"duplicate {label}: {dupes}")
    for entry in entries:
        for term in entry.get("retired") or []:
            for zh in zhs:
                # A retired name inside a canonical name would make the
                # canonical name itself trip the scan.
                if zh and term in zh:
                    problems.append(f"{entry.get('id')}: retired {term!r} occurs inside canonical name {zh!r}")
    return problems


def retired_hits(text: str, glossary: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """``(retired term, entry id, canonical zh)`` for every retired name in ``text``."""
    hits = []
    for entry in glossary.get("entries") or []:
        for term in entry.get("retired") or []:
            if term in text:
                hits.append((term, entry["id"], entry["zh"]))
    return hits


# English project codenames that must not stand in for the Chinese strategy
# names (趨勢策略／加密策略／動能策略／競賽策略) inside Chinese prose.  Identifiers
# are fine -- a command, unit, repo or path (``seykota-resume``, ``/opt/my-crypto-bot``)
# or anything inside backticks -- so only a bare codename is flagged.
_BARE_CODENAME = re.compile(
    r"(?<![A-Za-z0-9_/\-.])(seykota|momentum|my-?crypto|btc[- ]competition)(?![A-Za-z0-9_/\-]|\.[A-Za-z0-9_])",
    re.IGNORECASE,
)
_BACKTICK_SPAN = re.compile(r"`[^`]*`")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def bare_codename_hits(text: str) -> list[str]:
    """Bare English strategy codenames used inside Chinese prose (outside backticks).

    Only lines that contain Chinese are looked at: an English-only line is a
    code sample or an identifier list, not wording a reader sees.
    """
    found: list[str] = []
    for line in text.splitlines():
        if not _CJK.search(line):
            continue
        for match in _BARE_CODENAME.finditer(_BACKTICK_SPAN.sub("", line)):
            found.append(match.group(1))
    return found
