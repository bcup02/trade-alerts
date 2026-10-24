"""f-45: the health panel on the rollout register page -- what the generator puts into the page, and what it refuses."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from trade_alerts.glossary import load_glossary

ROOT = Path(__file__).resolve().parents[1]
ROLLOUT = ROOT / "docs" / "guides" / "fleet-rollout-register.html"
RISK = ROOT / "docs" / "guides" / "fleet-risk-register.html"
CORE = ROOT / "scripts" / "health_panel_core.js"


def _render_guides():
    spec = importlib.util.spec_from_file_location("render_guides", ROOT / "scripts" / "render_guides.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def module():
    return _render_guides()


@pytest.fixture(scope="module")
def page_text():
    return ROLLOUT.read_text(encoding="utf-8")


def _page_data(text: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="data">\n(.*?)\n</script>', text, re.S).group(1))


def _page_script(text: str) -> str:
    return re.search(r"</script>\n<script>\n(.*?)\n</script>\s*$", text, re.S).group(1)


def test_the_panel_is_at_the_top_of_the_consistency_register_only(page_text):
    assert page_text.count('id="healthSources"') == 1
    assert page_text.index('id="healthPanel"') < page_text.index('class="big"') < page_text.index('id="group-pending"')
    assert page_text.index("機隊一致性登記冊") < page_text.index('id="healthPanel"')
    risk = RISK.read_text(encoding="utf-8")
    assert "healthPanel" not in risk and "HealthPanel" not in risk and "watchTool" not in risk


def test_the_page_carries_the_tested_core_verbatim_and_once(page_text):
    core = CORE.read_text(encoding="utf-8")
    script = _page_script(page_text)
    assert script.count(core) == 1
    assert script.count("var HealthPanel = ") == 1
    assert "</script" not in core.lower()


def test_nothing_in_the_page_script_can_turn_text_into_markup(page_text):
    script = _page_script(page_text)
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "srcdoc", "javascript:"):
        assert forbidden not in script, forbidden


def test_the_connector_is_used_only_as_declared(page_text, module):
    script = _page_script(page_text)
    calls = re.findall(r"\b(watchTool|callTool)\(([^,]+),\s*([^,]+),", script)
    assert calls and all(server == "H.server" and tool == "H.tool" for _name, server, tool in calls), calls
    assert script.count(".watchTool(") == 1 and script.count(".callTool(") == 1
    data = _page_data(page_text)["health"]
    declared = module.HEALTH_CAPABILITIES["mcp"]["servers"]
    assert declared == [{"server": data["server"], "tools": [data["tool"]]}]
    assert (data["server"], data["tool"]) == ("Google Drive", "read_file_content")
    assert data["refresh_ms"] >= 30000


def test_the_names_on_the_panel_are_the_glossary_and_axes_table_names(page_text, module):
    data = _page_data(page_text)["health"]
    glossary = load_glossary()
    zh = {entry["id"]: entry["zh"] for entry in glossary["entries"]}
    assert [t["label"] for t in data["targets"][:4]] == [zh["strategy.momentum"], zh["strategy.mycrypto"], zh["strategy.seykota"], zh["strategy.btc-competition"]]
    assert data["targets"][4] == {"id": "host", "label": "主機"}
    assert [(a["id"], a["label"]) for a in data["axes"]] == [(key, name) for name, key, _m, _c in module.OPS_NOTIFY_AXES]
    assert [s["label"] for s in data["sources"]] == [zh["host.main"], zh["host.dev"]]      # A1 first: the page opens on it


def test_a_source_without_a_spreadsheet_yet_is_null_and_the_page_says_so(page_text):
    data = _page_data(page_text)["health"]
    # A1's publisher went live on 2026-10-23 (first publish succeeded), so both shipped sources carry their file id; the
    # page keeps its "not set up yet" branch for a source whose file_id is still null (a new host).
    assert [(s["id"], bool(s["file_id"])) for s in data["sources"]] == [("a1", True), ("dev", True)]
    assert data["sources"][0]["file_id"] == "1TyCEF1x60MbWtbZJeO42VhiMkxkXyx5XaFL8zdLX0T4"
    assert "還沒設定讀數來源" in _page_script(page_text)


def test_the_page_opens_on_a1_and_offers_the_development_host_as_a_tab(page_text):
    data = _page_data(page_text)["health"]
    assert [s["id"] for s in data["sources"]] == ["a1", "dev"]
    assert data["sources"][1]["file_id"] is not None                                       # previewable before A1 is deployed
    assert 'id="healthTabs"' in page_text and '"tablist"' in _page_script(page_text)


def test_the_target_keys_are_the_ones_ops_notify_publishes(module):
    assert [key for key, _term in module.HEALTH_TARGETS] == ["momentum", "mycrypto", "seykota", "btc-competition"]
    assert module.HEALTH_HOST_TARGET[0] == "host"


GOOD = {"server": "Google Drive", "tool": "read_file_content", "refresh_ms": 60000,
        "sources": [{"id": "a1", "host_term": "host.main", "file_id": "a" * 33}]}


def _with(**changes):
    return {**GOOD, **changes}


def test_a_good_source_document_passes_and_carries_the_file_id(module):
    data = module.health_panel_data(load_glossary(), GOOD)
    assert data["sources"] == [{"id": "a1", "label": "正式機", "file_id": "a" * 33}]


@pytest.mark.parametrize("doc,why", [
    (_with(sources=[{"id": "a1", "host_term": "host.main", "file_id": "short"}]), "file_id"),
    (_with(sources=[{"id": "a1", "host_term": "host.main", "file_id": "has space " + "a" * 30}]), "file_id"),
    (_with(sources=[{"id": "a1", "host_term": "host.main", "file_id": 12345678901234567890}]), "file_id"),
    (_with(sources=[{"id": "a1", "host_term": "no.such.term", "file_id": None}]), "glossary"),
    (_with(sources=[{"id": "A1", "host_term": "host.main", "file_id": None}]), "id"),
    (_with(sources=[{"id": "a1", "host_term": "host.main", "file_id": None}, {"id": "a1", "host_term": "host.dev", "file_id": None}]), "repeated"),
    (_with(sources=[{"id": "a1", "host_term": "host.main"}]), "members"),
    (_with(sources=[{"id": "a1", "host_term": "host.main", "file_id": None, "label": "A1"}]), "members"),
    (_with(sources=[]), "no health source"),
    (_with(server="Gmail"), "Google Drive"),
    (_with(tool="search_files"), "read_file_content"),
    (_with(refresh_ms=1000), "refresh_ms"),
    (_with(refresh_ms="60000"), "refresh_ms"),
])
def test_a_bad_source_document_is_refused_before_it_reaches_the_page(module, doc, why):
    with pytest.raises(ValueError, match=why):
        module.health_panel_data(load_glossary(), doc)


def test_the_committed_sources_file_is_valid_and_has_no_secret():
    doc = json.loads((ROOT / "src" / "trade_alerts" / "catalog" / "fleet-health-sources.json").read_text(encoding="utf-8"))
    assert set(doc) == {"note", "server", "tool", "refresh_ms", "sources"}
    assert not re.search(r"[0-9a-f]{64}", json.dumps(doc))             # no key-like value; the file id is the only identifier here
