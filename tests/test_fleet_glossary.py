"""The glossary is only worth having if it is enforced: every human-facing text
in this repo is scanned for retired names, so a page can't quietly drift back to
calling one thing by three names."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_alerts.glossary import glossary_problems, load_glossary, retired_hits

_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = _ROOT / "schemas" / "fleet-glossary-v1.schema.json"
CATALOG_DIR = _ROOT / "src" / "trade_alerts" / "catalog"

# Human-facing text in this repo.  Excluded on purpose: the glossary itself
# (it lists the retired names) and docs/consumer-release-runbook.md (a dated
# release log -- rewriting history would make it lie about what was said then).
_TEXT_FILES = [
    _ROOT / "scripts" / "render_guides.py",
    _ROOT / "docs" / "guides" / "README.md",
    _ROOT / "docs" / "fleet-error-catalog.md",
]


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _human_texts():
    registry = json.loads((CATALOG_DIR / "fleet-rollout-registry.json").read_text(encoding="utf-8"))
    for text in _strings(registry):
        yield "fleet-rollout-registry.json", text
    catalog = json.loads((CATALOG_DIR / "fleet-error-catalog-v2.json").read_text(encoding="utf-8"))
    for entry in catalog["entries"]:
        for text in _strings({"title": entry["title"], "operator_message": entry["operator_message"]}):
            yield f"fleet-error-catalog-v2.json {entry['code']}", text
    for path in _TEXT_FILES:
        yield str(path.relative_to(_ROOT)), path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def glossary():
    return load_glossary()


def test_glossary_matches_its_json_schema(glossary):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(glossary))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


def test_glossary_is_self_consistent(glossary):
    assert glossary_problems(glossary) == []


def test_the_four_strategies_have_their_agreed_names(glossary):
    names = {e["id"]: e["zh"] for e in glossary["entries"]}
    assert names["strategy.seykota"] == "趨勢策略"
    assert names["strategy.momentum"] == "動能策略"
    assert names["strategy.mycrypto"] == "加密策略"
    assert names["strategy.btc-competition"] == "競賽策略"
    assert names["host.main"] == "正式機" and names["host.dev"] == "開發機"


def test_no_human_facing_text_uses_a_retired_name(glossary):
    found = []
    for where, text in _human_texts():
        for term, entry_id, zh in retired_hits(text, glossary):
            found.append(f"{where}: {term!r} -> use {zh!r} ({entry_id})")
    assert not found, "\n".join(sorted(set(found)))


def test_a_retired_name_is_caught(glossary):
    assert retired_hits("修復 bot 已部署到測試機", glossary)
    assert not retired_hits("修復機器人已部署到開發機", glossary)


def test_a_retired_name_inside_a_canonical_name_is_rejected(glossary):
    broken = json.loads(json.dumps(glossary))
    broken["entries"][0]["retired"].append(broken["entries"][1]["zh"][:2])
    assert any("inside canonical name" in p for p in glossary_problems(broken))
