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
    """While a retired code is still catalogued (its call site not yet replaced
    on the live host), its behaviour may only be pending replacement. The real
    catalog has no such code left since v2-W6 removed both PROPOSED entries, so
    build one: put a retired code back into the catalog with a done row."""
    retired = [item["code"] for item in catalog.get("retired_codes") or []]
    assert retired, "the v2 catalog retires codes; this test needs one"
    code = retired[0]
    template = next(entry for entry in catalog["entries"] if entry["code"].split(".")[0] == code.split(".")[0])
    catalog = copy.deepcopy(catalog)
    catalog["entries"].append({**copy.deepcopy(template), "code": code})
    template_row = next(row for row in registry["catalog"] if row["code"] == template["code"])

    def add_done_row(r):
        row = copy.deepcopy(template_row)
        row["code"] = code
        for project in row["behaviour"]:
            row["behaviour"][project] = {"state": "done", "evidence": "somewhere"}
        r["catalog"].append(row)

    problems = _problems_after(registry, catalog, add_done_row)
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


def test_rollout_page_groups_items_by_whether_any_cell_is_pending(registry, catalog):
    items = {i["anchor"]: i for i in _render_guides().rollout_items(catalog, registry)}
    assert len(items) == len(registry["capabilities"]) + len(registry["catalog"])
    for capability in registry["capabilities"]:
        pending = any(s["state"] == "pending" for s in capability["status"].values())
        assert items[f"cap-{capability['id']}"]["complete"] is not pending
    for row in registry["catalog"]:
        pending = any(s["state"] == "pending" for key in ("behaviour", "emits_event") for s in row[key].values())
        assert items[f"rule-{row['code']}"]["complete"] is not pending


def test_recent_change_pointing_at_a_still_pending_cell_is_caught(registry, catalog):
    def break_it(r):
        capability = r["capabilities"][0]
        pending_project = next(p for p, s in capability["status"].items() if s["state"] != "done")
        capability["status"][pending_project] = {
            "state": "pending", "phase": next(iter(r["phases"])), "reason": "test",
        }
        r["recent_changes"] = [{"kind": "cap", "id": capability["id"], "project": pending_project, "note": "x"}]

    problems = _problems_after(registry, catalog, break_it)
    assert any("not done/n-a" in p for p in problems)


def test_recent_change_pointing_at_an_unknown_id_is_caught(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r.update(recent_changes=[
        {"kind": "cap", "id": "nonexistent.capability", "project": "momentum", "note": "x"},
    ]))
    assert any("not found" in p for p in problems)


def test_recent_change_on_a_rule_without_aspect_is_caught(registry, catalog):
    code = registry["catalog"][0]["code"]
    problems = _problems_after(registry, catalog, lambda r: r.update(recent_changes=[
        {"kind": "rule", "id": code, "project": "momentum", "note": "x"},
    ]))
    assert any("aspect" in p for p in problems)


def test_recent_change_type_added_does_not_need_a_done_cell(registry, catalog):
    """A brand-new row has nothing to point a done/n-a check at yet -- type=added
    must not be held to the same rule as type=completed, and doesn't even need
    a project (the whole row is new, not one strategy's cell)."""
    capability = registry["capabilities"][0]
    problems = _problems_after(registry, catalog, lambda r: r.update(recent_changes=[
        {"kind": "cap", "id": capability["id"], "type": "added", "note": "x"},
    ]))
    assert problems == []


def test_recent_change_type_added_still_needs_a_real_id(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: r.update(recent_changes=[
        {"kind": "cap", "id": "nonexistent.capability", "type": "added", "note": "x"},
    ]))
    assert any("not found" in p for p in problems)


def test_recent_change_type_added_with_a_bogus_project_is_caught(registry, catalog):
    capability = registry["capabilities"][0]
    problems = _problems_after(registry, catalog, lambda r: r.update(recent_changes=[
        {"kind": "cap", "id": capability["id"], "type": "added", "project": "not-a-real-project", "note": "x"},
    ]))
    assert any("not a known strategy" in p for p in problems)


def test_rollout_items_recolors_the_dot_for_a_type_completed_change(registry, catalog):
    """Synthetic, not data-driven: the live registry's recent_changes can (and
    currently does) hold only type=added entries, which would leave this
    render path -- dot recoloring + has_recent for type=completed -- with no
    regression coverage at all (flagged in PR #39 review). Fabricate a
    completed entry against whichever cell is actually done in the fixture,
    independent of what recent_changes currently contains for real."""
    render_guides = _render_guides()
    capability = next(
        c for c in registry["capabilities"]
        if any(s["state"] == "done" for s in c["status"].values())
    )
    project = next(p for p, s in capability["status"].items() if s["state"] == "done")
    edited = copy.deepcopy(registry)
    edited["recent_changes"] = [{"kind": "cap", "id": capability["id"], "project": project, "note": "x"}]
    assert registry_problems(edited, catalog) == []  # sanity: this is a legal completed entry

    items = {i["anchor"]: i for i in render_guides.rollout_items(catalog, edited)}
    item = items[f"cap-{capability['id']}"]
    assert item["dots"][project] == "recent"
    assert item["has_recent"] is True
    assert item["added_recent"] is False


def _other_aspect_pending(registry, entry) -> bool:
    row = next(r for r in registry["catalog"] if r["code"] == entry["id"])
    other = "emits_event" if entry["aspect"] == "behaviour" else "behaviour"
    return row[other][entry["project"]]["state"] == "pending"


def test_a_rule_whose_other_aspect_is_still_pending_is_still_flagged_recent(registry, catalog):
    """2026-09-25: BTC.ORDER_STATUS_UNKNOWN's behaviour reached the live host while
    its emits_event cell stays pending until phase 8.  A completed entry for the
    behaviour must still badge the row -- before this the page silently showed it
    as an ordinary pending row, so the latest change was invisible."""
    render_guides = _render_guides()
    edited = copy.deepcopy(registry)
    row = next(r for r in edited["catalog"]
               for p, st in r["behaviour"].items()
               if st["state"] == "done" and r["emits_event"][p]["state"] == "pending")
    project = next(p for p, st in row["behaviour"].items()
                   if st["state"] == "done" and row["emits_event"][p]["state"] == "pending")
    edited["recent_changes"] = [{"kind": "rule", "id": row["code"], "project": project,
                                 "aspect": "behaviour", "note": "x"}]
    assert registry_problems(edited, catalog) == []
    item = {i["anchor"]: i for i in render_guides.rollout_items(catalog, edited)}[f"rule-{row['code']}"]
    assert item["has_recent"] is True
    assert item["dots"][project] == "pending"
    assert item["complete"] is False


def test_rollout_page_highlights_recent_changes_and_lists_them(registry, catalog):
    """Both flavours of recent_changes entry -- type=completed (an existing cell
    just flipped to done/n-a) and type=added (a brand-new row, no cell to flip
    yet) -- must surface as "what changed" on the page, with no visible
    distinction between them (the person reading the page doesn't care which
    kind it was, only that this is what the latest edit touched)."""
    render_guides = _render_guides()
    items = {i["anchor"]: i for i in render_guides.rollout_items(catalog, registry)}
    change = registry.get("recent_changes")
    assert change, "fixture registry should carry at least one recent_changes entry"
    for entry in change:
        anchor_prefix = "cap-" if entry["kind"] == "cap" else "rule-"
        item = items[anchor_prefix + entry["id"]]
        if entry.get("type", "completed") == "added":
            assert item["added_recent"] is True
        else:
            assert item["has_recent"] is True
            if entry["kind"] == "rule" and _other_aspect_pending(registry, entry):
                # The named aspect is done, the other one is not: the strategy
                # still has work left, so its dot stays pending -- only the
                # badge says this row is what changed.
                assert item["dots"][entry["project"]] == "pending"
            else:
                assert item["dots"][entry["project"]] == "recent"
    pages = {path.name: html for path, html in render_guides.rendered_pages().items()}
    assert "recent_summary" in pages["fleet-rollout-register.html"]
    assert "最新變動" in pages["fleet-rollout-register.html"]
