"""The rollout registry is the fleet's "four strategies or say why not" rule in
executable form, so it gets the same treatment as the error catalog: the
shipped copy must be consistent, every rule ``registry_problems`` claims to
enforce has a counter-example here that it catches, and the two generated
guide pages must equal a fresh render.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from trade_alerts import (
    REGISTRY_VERSION,
    STRATEGY_PROJECTS,
    load_rollout_registry,
    project_rows,
    registry_problems,
)
from trade_alerts.fleet_event_log import load_error_catalog
from trade_alerts.rollout_registry import owners

_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = _ROOT / "src" / "trade_alerts" / "catalog" / "fleet-rollout-registry.json"
SCHEMA_PATH = _ROOT / "schemas" / "fleet-rollout-registry-v1.schema.json"


@pytest.fixture(scope="module")
def catalog() -> dict:
    return load_error_catalog()


@pytest.fixture()
def registry() -> dict:
    return load_rollout_registry()


def _script(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render_guides():
    return _script("render_guides")


# --- the shipped registry --------------------------------------------------


def test_registry_matches_its_json_schema(registry):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(registry))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


def test_shipped_registry_is_consistent_with_the_catalog(registry, catalog):
    assert registry_problems(registry, catalog) == []


def test_packaged_copy_is_the_repo_file(registry):
    assert registry == json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert load_rollout_registry(REGISTRY_PATH) == registry


def test_strategy_projects_are_the_four_strategies():
    assert set(STRATEGY_PROJECTS) == {"seykota", "momentum", "mycrypto", "btc-competition"}


def test_load_rejects_another_document(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"registry_version": "something-else/v9"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_rollout_registry(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_rollout_registry(path)


# --- owners / project_rows -------------------------------------------------


def test_owners_maps_prefix_to_strategy():
    assert owners("SEY.POSITION_AMBIGUOUS") == ("seykota",)
    assert owners("MOM.PROTECTION_UNVERIFIED") == ("momentum",)
    assert owners("FLEET.ANYTHING") == STRATEGY_PROJECTS
    with pytest.raises(ValueError):
        owners("XYZ.NOPE")


def test_project_rows_covers_every_claim_about_one_strategy(registry):
    rows = project_rows(registry, "seykota")
    for capability in registry["capabilities"]:
        assert rows[f"capability:{capability['id']}"] == capability["status"]["seykota"]
    sey_codes = [row["code"] for row in registry["catalog"] if row["code"].startswith("SEY.")]
    assert sey_codes
    for code in sey_codes:
        assert f"{code}:behaviour" in rows and f"{code}:emits_event" in rows
    assert not any(key.startswith("MOM.") for key in rows)


def test_project_rows_returns_copies(registry):
    rows = project_rows(registry, "momentum")
    key = next(iter(rows))
    rows[key]["state"] = "tampered"
    assert project_rows(registry, "momentum")[key]["state"] != "tampered"


def test_project_rows_rejects_unknown_project(registry):
    with pytest.raises(ValueError):
        project_rows(registry, "fleet")


# --- every rule has a counter-example ----------------------------------------


def _problems_after(registry, catalog, mutate) -> list[str]:
    broken = copy.deepcopy(registry)
    mutate(broken)
    return registry_problems(broken, catalog)


def _capability(registry, index=0):
    return registry["capabilities"][index]


def test_wrong_registry_version_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r.update(registry_version="x/v0"))
    assert any(REGISTRY_VERSION in p for p in problems)


def test_catalog_version_mismatch_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r.update(catalog_version="fleet-error-catalog/v1"))
    assert any("catalog is" in p for p in problems)


def test_missing_project_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r["projects"].pop("mycrypto"))
    assert any(p.startswith("projects must be exactly") for p in problems)


def test_capability_missing_a_strategy_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].pop("btc-competition"))
    assert any("must list all four strategies" in p for p in problems)


def test_duplicate_capability_id_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r["capabilities"].append(copy.deepcopy(_capability(r))))
    assert any("missing or duplicated" in p for p in problems)


@pytest.mark.parametrize("key", ["title", "description"])
def test_capability_without_text_is_caught(registry, catalog, key):
    problems = _problems_after(registry, catalog, lambda r: _capability(r).update({key: "  "}))
    assert any(f"missing {key}" in p for p in problems)


def test_unknown_state_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].update(seykota={"state": "maybe"}))
    assert any("unknown state 'maybe'" in p for p in problems)


def test_done_without_evidence_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].update(seykota={"state": "done"}))
    assert any("done without evidence" in p for p in problems)


def test_pending_without_reason_is_caught(registry, catalog):
    status = {"state": "pending", "phase": "v2-W2"}
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].update(seykota=status))
    assert any("pending without a reason" in p for p in problems)


def test_pending_in_an_unregistered_phase_is_caught(registry, catalog):
    status = {"state": "pending", "phase": "someday", "reason": "later"}
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].update(seykota=status))
    assert any("'someday' is not a registered phase" in p for p in problems)


def test_na_without_reason_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].update(seykota={"state": "n/a"}))
    assert any("n/a without a reason" in p for p in problems)


def test_catalog_entry_without_a_row_is_caught(registry, catalog):
    code = registry["catalog"][0]["code"]
    problems = _problems_after(registry, catalog, lambda r: r["catalog"].pop(0))
    assert f"catalog entry {code} has no registry row" in problems


def test_row_for_an_unknown_code_is_caught(registry, catalog):
    def add(r):
        row = copy.deepcopy(r["catalog"][0])
        row["code"] = "SEY.NOT_IN_CATALOG"
        r["catalog"].append(row)

    assert "registry row SEY.NOT_IN_CATALOG is not in the catalog" in _problems_after(registry, catalog, add)


def test_row_claiming_another_strategy_is_caught(registry, catalog):
    def add_foreign(r):
        row = next(row for row in r["catalog"] if row["code"].startswith("SEY."))
        row["behaviour"]["momentum"] = {"state": "n/a", "reason": "not mine"}

    problems = _problems_after(registry, catalog, add_foreign)
    assert any("behaviour: must list exactly ['seykota']" in p for p in problems)


def test_retired_code_marked_done_is_caught(registry, catalog):
    retired = [item["code"] for item in catalog.get("retired_codes") or []]
    assert retired, "the v2 catalog retires codes; this test needs one"
    code = retired[0]

    def finish(r):
        row = next(row for row in r["catalog"] if row["code"] == code)
        for project in row["behaviour"]:
            row["behaviour"][project] = {"state": "done", "evidence": "somewhere"}

    problems = _problems_after(registry, catalog, finish)
    assert any(f"{code} is retired" in p for p in problems)


def test_sources_missing_a_strategy_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r["sources"].pop("seykota"))
    assert any(p.startswith("sources must list exactly") for p in problems)


def test_sources_on_a_non_live_branch_is_caught(registry, catalog):
    # The PR #31 review found done evidence pointing at code that only exists
    # on development; "done" is pinned to what the live host runs.
    problems = _problems_after(registry, catalog, lambda r: r["sources"]["momentum"].update(branch="development"))
    assert any("sources / momentum: branch must be 'operations'" in p for p in problems)


@pytest.mark.parametrize("commit", ["520cb9e", "HEAD", "Z" * 40, None])
def test_sources_commit_must_be_a_full_sha(registry, catalog, commit):
    problems = _problems_after(registry, catalog, lambda r: r["sources"]["momentum"].update(commit=commit))
    assert any("sources / momentum: commit must be a full 40-character SHA" in p for p in problems)


def test_sources_repo_must_be_owner_slash_name(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r["sources"]["momentum"].update(repo="just-a-name"))
    assert any("sources / momentum: repo must be owner/name" in p for p in problems)


# --- evidence citations (the cross-repo check itself runs by hand) ----------


def test_citation_parser_reads_paths_lines_and_root_modules():
    citations = _script("verify_registry_evidence").citations
    assert citations("src/strategy.py:1067 build_safe_halt") == [("src/strategy.py", 1067)]
    assert citations("MOMENTUM_REPAIR_PAUSED（scripts/repair_bot.py:90）") == [("scripts/repair_bot.py", 90)]
    assert citations("mexc_futures_bot.py:713 append_fleet_event") == [("mexc_futures_bot.py", 713)]
    assert citations("reconcile_compare.py main") == [("reconcile_compare.py", None)]
    assert citations("src/seykota_bot/bot.py 守衛；src/seykota_bot/safe_halt_resume.py:103") == [
        ("src/seykota_bot/bot.py", None), ("src/seykota_bot/safe_halt_resume.py", 103)]
    assert citations("程式已照目錄描述處理（Phase 3）") == []


def test_every_done_cell_cites_a_file(registry):
    citations = _script("verify_registry_evidence").citations
    for where, project, status in _script("verify_registry_evidence")._cells(registry):
        if status["state"] == "done":
            assert citations(status["evidence"]), f"{where} / {project}: done evidence cites no file"


# --- generated pages -------------------------------------------------------


def test_committed_guide_pages_equal_a_fresh_render():
    render_guides = _render_guides()
    for path, html in render_guides.rendered_pages().items():
        assert path.read_text(encoding="utf-8") == html, f"{path.name} is stale: run scripts/render_guides.py"


def test_render_check_mode_passes_on_the_committed_pages():
    assert _render_guides().main(["--check"]) == 0


def test_render_check_mode_flags_a_hand_edited_page(tmp_path, monkeypatch):
    render_guides = _render_guides()
    pages = render_guides.rendered_pages()
    edited = {}
    for path, html in pages.items():
        copy_path = tmp_path / path.name
        copy_path.write_text(html, encoding="utf-8")
        edited[copy_path] = html
    first = next(iter(edited))
    first.write_text(edited[first].replace("</body>", "<!-- hand edit --></body>", 1) + " ", encoding="utf-8")
    monkeypatch.setattr(render_guides, "ROOT", tmp_path)
    monkeypatch.setattr(render_guides, "rendered_pages", lambda: edited)
    assert render_guides.main(["--check"]) == 1


def test_pages_cover_every_catalog_entry_and_capability(registry, catalog):
    pages = {path.name: html for path, html in _render_guides().rendered_pages().items()}
    for entry in catalog["entries"]:
        assert entry["code"] in pages["fleet-risk-register.html"]
        assert entry["code"] in pages["fleet-rollout-register.html"]
    for capability in registry["capabilities"]:
        assert capability["id"] in pages["fleet-rollout-register.html"]


def test_pages_never_inject_html_from_data():
    for html in _render_guides().rendered_pages().values():
        assert "innerHTML" not in html
        assert "insertAdjacentHTML" not in html
