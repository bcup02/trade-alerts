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
import re
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
from trade_alerts.rollout_registry import ACTIVE_PROJECTS, RETIRED_PROJECTS, STRATEGY_PROJECTS, owners

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


def test_strategy_projects_are_the_five_strategies():
    """v0.30.25：趨勢策略・流星池版（V11）有了自己的欄位，登記冊是五個專案欄。"""
    assert set(STRATEGY_PROJECTS) == {"seykota", "momentum", "mycrypto", "btc-competition", "trend-meteor"}


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
    assert any("must list every active strategy" in p for p in problems)


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
    # A bare ":line" belongs to the path cited just before it -- and is checked.
    assert citations("src/a.py:10 先查，:11 再查；src/b.py:20 再停，:30 暫停，2026-09-25 01:22 UTC") == [
        ("src/a.py", 10), ("src/a.py", 11), ("src/b.py", 20), ("src/b.py", 30)]


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
        # 舊趨勢（SEY.*）已停用：一致性登記冊沒有它的欄，只在風險登記冊
        assert (entry["code"] in pages["fleet-rollout-register.html"]) is bool(set(owners(entry["code"])) - set(RETIRED_PROJECTS))
    for capability in registry["capabilities"]:
        assert capability["id"] in pages["fleet-rollout-register.html"]


def test_pages_never_inject_html_from_data():
    for html in _render_guides().rendered_pages().values():
        assert "innerHTML" not in html
        assert "insertAdjacentHTML" not in html


def _stage(states):
    return "pending" if "pending" in states else ("built" if "built" in states else "done")


def test_rollout_page_groups_items_by_whether_any_cell_is_pending_or_built(registry, catalog):
    """未完成＝有一格是未做；沒有未做但有一格已完成未上線＝等上線；其餘才是已完成（complete 只給最後一類）。"""
    items = {i["anchor"]: i for i in _render_guides().rollout_items(catalog, registry)}
    shown_rules = [row for row in registry["catalog"] if set(owners(row["code"])) - set(RETIRED_PROJECTS)]
    assert len(items) == len(registry["capabilities"]) + len(shown_rules)
    for capability in registry["capabilities"]:
        item = items[f"cap-{capability['id']}"]
        stage = _stage({s["state"] for p, s in capability["status"].items() if p in ACTIVE_PROJECTS})
        assert item["stage"] == stage and item["complete"] is (stage == "done")
    for row in shown_rules:
        item = items[f"rule-{row['code']}"]
        stage = _stage({s["state"] for key in ("behaviour", "emits_event") for p, s in row[key].items() if p in ACTIVE_PROJECTS})
        assert item["stage"] == stage and item["complete"] is (stage == "done")


def _first_built_cap(reg):
    for capability in reg["capabilities"]:
        for project, status in capability["status"].items():
            if status["state"] == "built":
                return capability, project, status
    raise AssertionError("fixture has no built cell")


def test_built_cell_needs_evidence_and_a_registered_phase(registry, catalog):
    """已完成、尚未上線：像已做一樣要引用程式（evidence），再加上線的關卡（phase）；不能帶 reason／limit／verified_at。"""
    for field, bad, needle in (("evidence", None, "built without evidence"), ("phase", "no-such-phase", "built phase"),
                               ("reason", "x", "does not belong on a built cell"), ("limit", "x", "does not belong on a built cell"),
                               ("verified_at", "2026-11-10", "does not belong on a built cell")):
        reg = copy.deepcopy(registry)
        _, _, status = _first_built_cap(reg)
        if bad is None:
            status.pop(field)
        else:
            status[field] = bad
        assert [p for p in registry_problems(reg, catalog) if needle in p], field


def test_a_built_cell_never_counts_as_done_on_the_page(registry, catalog):
    """已完成未上線的格子在頁面是自己一類：點是 built、項目 stage 不是 done；只有每一格都是已做或不適用才算已完成。"""
    render_guides = _render_guides()
    capability, project, _ = _first_built_cap(registry)
    item = {i["anchor"]: i for i in render_guides.rollout_items(catalog, registry)}[f"cap-{capability['id']}"]
    assert item["dots"][project] == "built" and item["stage"] in ("built", "pending") and item["complete"] is False
    html = render_guides.render_rollout_register(catalog, registry, render_guides.load_glossary())
    assert "已完成、尚未上線" in html and 'id="group-built"' in html


def test_built_cell_can_name_the_commit_it_waits_for(registry, catalog):
    reg = copy.deepcopy(registry)
    _, _, status = _first_built_cap(reg)
    status["awaits_commit"] = "0123456789abcdef0123456789abcdef01234567"
    assert not [p for p in registry_problems(reg, catalog) if "awaits_commit" in p]
    status["awaits_commit"] = "XYZ"
    assert [p for p in registry_problems(reg, catalog) if "awaits_commit must be" in p]


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
    # No live row is in this shape any more (every emits_event cell is done), so build one: a rule
    # whose behaviour is done on momentum and whose emits_event cell is turned back into pending.
    project = "momentum"
    row = next(r for r in edited["catalog"]
               if r["behaviour"].get(project, {}).get("state") == "done"
               and r["emits_event"].get(project, {}).get("state") == "done")
    row["emits_event"][project] = {"state": "pending", "phase": "8-momentum", "reason": "x"}
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
    change = registry.get("recent_changes")
    if not change:
        # The live registry may legitimately carry [] (schema: "set to [] when
        # nothing from the latest edit remains current") -- then exercise the
        # renderer with a synthetic entry on a cell that is already done.
        import copy

        registry = copy.deepcopy(registry)
        row = next(
            (r, p) for r in registry["catalog"]
            for p, v in (r.get("behaviour") or {}).items()
            if isinstance(v, dict) and v.get("state") == "done"
        )
        registry["recent_changes"] = [
            {"kind": "rule", "id": row[0]["code"], "project": row[1],
             "aspect": "behaviour", "type": "completed", "note": "synthetic"}
        ]
        change = registry["recent_changes"]
        monkeypatched = True
    else:
        monkeypatched = False
    items = {i["anchor"]: i for i in render_guides.rollout_items(catalog, registry)}
    for entry in change:
        anchor_prefix = "cap-" if entry["kind"] == "cap" else "rule-"
        item = items[anchor_prefix + entry["id"]]
        if entry.get("type", "completed") in ("added", "updated"):
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
    if monkeypatched:
        return  # the rendered pages come from the live registry, which has none
    pages = {path.name: html for path, html in render_guides.rendered_pages().items()}
    assert "recent_summary" in pages["fleet-rollout-register.html"]
    assert "最新變動" in pages["fleet-rollout-register.html"]


def test_updated_recent_change_is_accepted_and_flagged(registry, catalog):
    """type=updated names an existing row whose content changed without any
    cell flipping (e.g. a pending description rewritten, a catalog row
    retitled): it must validate while the row exists, fail when it doesn't,
    and show up in the page's 'recently changed' summary like added does."""
    import copy

    reg = copy.deepcopy(registry)
    capability, _, _ = _first_pending_cap(reg)
    reg["recent_changes"] = [{"kind": "cap", "id": capability["id"], "type": "updated", "note": "x"}]
    assert not [p for p in registry_problems(reg, catalog) if "recent_changes" in p]
    reg["recent_changes"] = [{"kind": "cap", "id": "nonexistent.capability", "type": "updated", "note": "x"}]
    assert [p for p in registry_problems(reg, catalog) if "recent_changes" in p]
    reg["recent_changes"] = [{"kind": "cap", "id": capability["id"], "type": "updated", "note": "x"}]
    items = {i["anchor"]: i for i in _render_guides().rollout_items(catalog, reg)}
    assert items["cap-" + capability["id"]]["added_recent"] is True


def _page_data(html: str) -> dict:
    import re

    match = re.search(r'<script type="application/json" id="data">\n(.*?)\n</script>', html, re.S)
    assert match, "the rollout page has no embedded data"
    return json.loads(match.group(1))


def test_recent_summary_lists_a_rule_once_when_both_aspects_flipped(registry, catalog):
    """A rule whose behaviour and event-log aspects both became true needs two recent_changes entries (the
    validator wants the aspect), but the 'what changed' box must show one line, not two identical ones."""
    render_guides = _render_guides()
    reg = copy.deepcopy(registry)
    code, project = next(
        (row["code"], p) for row in reg["catalog"] for p in row["behaviour"]
        if p in ACTIVE_PROJECTS and row["behaviour"][p]["state"] == "done" and row["emits_event"][p]["state"] == "done"
    )
    reg["recent_changes"] = [
        {"kind": "rule", "id": code, "project": project, "aspect": aspect, "type": "completed", "note": "同一句話"}
        for aspect in ("behaviour", "emits_event")
    ]
    assert not [p for p in registry_problems(reg, catalog) if "recent_changes" in p]
    data = _page_data(render_guides.render_rollout_register(catalog, reg, render_guides.load_glossary()))
    assert [r["note"] for r in data["recent_summary"]] == ["同一句話"]
    # a different note for the same rule is a different line
    reg["recent_changes"][1]["note"] = "另一句話"
    data = _page_data(render_guides.render_rollout_register(catalog, reg, render_guides.load_glossary()))
    assert sorted(r["note"] for r in data["recent_summary"]) == ["另一句話", "同一句話"]


def test_rollout_page_lists_only_phases_that_still_have_pending_or_built_cells(registry, catalog):
    """'預定的關卡' is what is still to do: a phase with no pending or built (done on development, not live) cell left is history, not a plan."""
    render_guides = _render_guides()
    data = _page_data(render_guides.render_rollout_register(catalog, registry, render_guides.load_glossary()))
    assert data["phase_order"] == [k for k in registry["phases"] if data["phase_counts"][k] or data["phase_built_counts"][k]]
    assert all(data["phase_counts"][k] or data["phase_built_counts"][k] for k in data["phase_order"])
    assert set(data["phase_counts"]) == set(registry["phases"])  # the counts still cover every phase


# --- a pending cell that waits for a deployment names the commit (phase-sync1) --------------------------------


def _first_pending_cap(reg):
    """A pending capability cell of ``reg``; once every capability cell has shipped (2026-10-19), the first done cell
    of the copy is turned pending so these checks still have a cell to bend."""
    for capability in reg["capabilities"]:
        for project, status in capability["status"].items():
            if status["state"] == "pending":
                return capability, project, status
    capability = reg["capabilities"][0]
    project = next(iter(capability["status"]))
    capability["status"][project] = {"state": "pending", "phase": next(iter(reg["phases"])), "reason": "test"}
    return capability, project, capability["status"][project]


def test_a_reason_that_promises_a_deployment_must_name_the_commit(registry, catalog):
    reg = copy.deepcopy(registry)
    _, _, status = _first_pending_cap(reg)
    status["reason"] = "已在開發主幹實作，還沒上正式機，上線後改已做。"
    status.pop("awaits_commit", None)
    problems = [p for p in registry_problems(reg, catalog) if "awaits_commit" in p]
    assert len(problems) == 1 and "names no commit" in problems[0]
    status["awaits_commit"] = "0123456789abcdef0123456789abcdef01234567"
    assert not [p for p in registry_problems(reg, catalog) if "awaits_commit" in p]
    status["awaits_commit"] = "0123abc"  # a short hash is enough to find the commit
    assert not [p for p in registry_problems(reg, catalog) if "awaits_commit" in p]


@pytest.mark.parametrize("bad", ["", "XYZ", "0123ab", "0123456789ABCDEF", 12345, "g" * 40])
def test_awaits_commit_must_look_like_a_commit(registry, catalog, bad):
    reg = copy.deepcopy(registry)
    _, _, status = _first_pending_cap(reg)
    status["awaits_commit"] = bad
    assert [p for p in registry_problems(reg, catalog) if "awaits_commit must be" in p]


def test_awaits_commit_only_belongs_on_pending_cells(registry, catalog):
    reg = copy.deepcopy(registry)
    capability = next(c for c in reg["capabilities"] if any(s["state"] == "done" for s in c["status"].values()))
    status = next(s for s in capability["status"].values() if s["state"] == "done")
    status["awaits_commit"] = "0123456789abcdef0123456789abcdef01234567"
    assert [p for p in registry_problems(reg, catalog) if "only belongs on a pending or built cell" in p]


def test_a_pending_reason_that_does_not_promise_a_deployment_needs_no_commit(registry, catalog):
    """'Waits for a phone test / x3e / a decision' is not a deployment; those cells stay as they are."""
    reg = copy.deepcopy(registry)
    _, _, status = _first_pending_cap(reg)
    status["reason"] = "要等 x5 測試網實測，驗過才改已做。"
    status.pop("awaits_commit", None)
    assert not [p for p in registry_problems(reg, catalog) if "awaits_commit" in p]
    assert not [p for p in registry_problems(registry, catalog) if "awaits_commit" in p]  # the shipped registry is clean


# --- the published page fingerprints itself (phase-sync2) -------------------------------------------------------

_WRAP_HEAD = '<!doctype html><html><head><meta charset=utf8><style>:root{}</style></head><body>\n'
_WRAP_TAIL = "\n</body></html>"


def _wrapped(page: str) -> str:
    """What the artifact service stores: our page between its own head and tail."""
    return _WRAP_HEAD + page + _WRAP_TAIL


def test_every_rendered_page_carries_a_consistent_fingerprint():
    render_guides = _render_guides()
    for path, page in render_guides.rendered_pages().items():
        stamp = render_guides._DIGEST_COMMENT.search(page)
        assert stamp and page.splitlines()[1].startswith("<!-- fleet-guide-digest: "), "the stamp is on line 2"
        assert render_guides.verify_digest(page) == (stamp.group(1), "")
        assert f"頁面版本碼 <code>{stamp.group(1)}</code>" in page
        assert render_guides.DIGEST_PLACEHOLDER not in page
        assert render_guides.published_core(_wrapped(page)) == page   # the host's wrapper does not disturb it


def test_check_published_says_current_stale_or_altered(tmp_path, registry, catalog):
    render_guides = _render_guides()
    fresh = render_guides.rendered_pages()[render_guides.ROLLOUT_PAGE]
    saved = tmp_path / "saved.html"

    saved.write_text(_wrapped(fresh), encoding="utf-8")
    assert render_guides.check_published("rollout", saved)[0] == "current"

    older_registry = copy.deepcopy(registry)
    older_registry["updated_at"] = "2020-01-01"                        # an earlier, untouched render of the same page
    older = render_guides.render_rollout_register(catalog, older_registry, render_guides.load_glossary())
    assert older != fresh
    saved.write_text(_wrapped(older), encoding="utf-8")
    verdict, why = render_guides.check_published("rollout", saved)
    assert verdict == "stale" and "直接發布" in why

    edited = fresh.replace("機隊一致性登記冊", "機隊一致性登記冊（手改）", 1)   # someone edited the published text
    saved.write_text(_wrapped(edited), encoding="utf-8")
    assert render_guides.check_published("rollout", saved)[0] == "altered"

    unstamped = render_guides._DIGEST_COMMENT.sub("", fresh)             # a page from before version codes existed
    saved.write_text(_wrapped(unstamped), encoding="utf-8")
    verdict, why = render_guides.check_published("rollout", saved)
    assert verdict == "altered" and "沒有版本碼" in why

    saved.write_text(_wrapped(fresh), encoding="utf-8")                  # the other page's file is not this page
    assert render_guides.check_published("risk", saved)[0] == "stale"


def test_check_published_cli_exit_codes(tmp_path, capsys):
    render_guides = _render_guides()
    fresh = render_guides.rendered_pages()[render_guides.RISK_PAGE]
    good, bad = tmp_path / "good.html", tmp_path / "bad.html"
    good.write_text(_wrapped(fresh), encoding="utf-8")
    bad.write_text(_wrapped(fresh.replace("機隊風險登記冊", "x", 1)), encoding="utf-8")
    assert render_guides.main(["--check-published", "risk", str(good)]) == 0
    assert "risk: CURRENT" in capsys.readouterr().out
    assert render_guides.main(["--check-published", "risk", str(bad)]) == 2
    assert render_guides.main(["--check-published", "risk", str(good), "--check-published", "rollout", str(good)]) == 1


def _verdict(render_guides, tmp_path, page, kind="rollout"):
    saved = tmp_path / "saved.html"
    saved.write_text(_wrapped(page), encoding="utf-8")
    return render_guides.check_published(kind, saved)


def test_changing_only_the_footer_version_code_is_altered(tmp_path):
    """Review of #195 (BLOCK-1): the footer code used to be masked out of the hash and never compared with line 2."""
    render_guides = _render_guides()
    fresh = render_guides.rendered_pages()[render_guides.ROLLOUT_PAGE]
    code = render_guides._DIGEST_COMMENT.search(fresh).group(1)
    tampered = fresh.replace(f"頁面版本碼 <code>{code}</code>", "頁面版本碼 <code>0000000000000000</code>")
    assert tampered != fresh
    verdict, why = _verdict(render_guides, tmp_path, tampered)
    assert verdict == "altered" and "不一樣" in why
    assert _verdict(render_guides, tmp_path, fresh)[0] == "current"          # the unmodified page still passes


def test_inserting_the_old_placeholder_text_into_the_body_is_altered(tmp_path):
    """Review of #195 (BLOCK-2): the placeholder was deleted from the whole page before hashing, so text added with that
    name vanished from the hash input."""
    render_guides = _render_guides()
    fresh = render_guides.rendered_pages()[render_guides.ROLLOUT_PAGE]
    for sneaky in (render_guides.DIGEST_PLACEHOLDER, "0" * 16, "頁面版本碼 <code>" + "a" * 16 + "</code>", "<!-- fleet-guide-digest: " + "b" * 16 + " -->"):
        edited = fresh.replace("<h1>機隊一致性登記冊</h1>", "<h1>機隊一致性登記冊" + sneaky + "</h1>", 1)
        assert edited != fresh
        assert _verdict(render_guides, tmp_path, edited)[0] == "altered", sneaky


def test_missing_or_duplicated_version_codes_are_altered(tmp_path):
    render_guides = _render_guides()
    fresh = render_guides.rendered_pages()[render_guides.ROLLOUT_PAGE]
    code = render_guides._DIGEST_COMMENT.search(fresh).group(1)
    footer = f"頁面版本碼 <code>{code}</code>"
    assert _verdict(render_guides, tmp_path, fresh.replace(footer, "頁面版本碼"))[0] == "altered"                 # footer code removed
    assert _verdict(render_guides, tmp_path, fresh.replace(footer, footer + " " + footer, 1))[0] == "altered"    # footer code twice
    stamp = f"<!-- fleet-guide-digest: {code} -->"
    assert _verdict(render_guides, tmp_path, fresh.replace(stamp, stamp + stamp, 1))[0] == "altered"            # line-2 code twice


def test_the_page_templates_have_exactly_one_footer_placeholder():
    render_guides = _render_guides()
    import pytest as _pytest
    with _pytest.raises(ValueError, match="exactly once"):
        render_guides._page("t", "no placeholder here", {}, "")
    with _pytest.raises(ValueError, match="exactly once"):
        render_guides._page("t", render_guides.DIGEST_PLACEHOLDER * 2, {}, "")
    with _pytest.raises(ValueError, match="exactly once"):
        render_guides._page("t", render_guides.DIGEST_PLACEHOLDER, {"x": render_guides.DIGEST_PLACEHOLDER}, "")


# --- cell fields: verified_at, limit, length caps (phase-sync4) -------------------------------------------------

from trade_alerts.rollout_registry import MAX_EVIDENCE_CHARS, MAX_LIMIT_CHARS, MAX_REASON_CHARS  # noqa: E402


def _first_done_cap(reg):
    for capability in reg["capabilities"]:
        for project, status in capability["status"].items():
            if status["state"] == "done":
                return capability, project, status
    raise AssertionError("no done capability cell")


def test_verified_at_and_limit_are_accepted_on_done_cells_and_checked(registry, catalog):
    reg = copy.deepcopy(registry)
    _, _, status = _first_done_cap(reg)
    status.update({"verified_at": "2026-10-15", "limit": "A1 沒有觸發過。"})
    assert not [p for p in registry_problems(reg, catalog) if "verified_at" in p or "limit" in p]
    for bad in ("2026-13-01", "2026-10-32", "2026-02-31", "2026-04-31", "10/15", "2026-1-5", "", 20261015, None):
        status["verified_at"] = bad
        assert [p for p in registry_problems(reg, catalog) if "verified_at must be" in p], bad
    status["verified_at"] = "2026-10-15"
    for bad in ("", "   ", 5, None):
        status["limit"] = bad
        assert [p for p in registry_problems(reg, catalog) if "limit must be" in p], bad


def test_verified_at_and_limit_do_not_belong_on_pending_or_na_cells(registry, catalog):
    reg = copy.deepcopy(registry)
    _, _, pending = _first_pending_cap(reg)
    pending["limit"] = "x"
    assert [p for p in registry_problems(reg, catalog) if "limit only belongs on a done cell" in p]
    del pending["limit"]
    pending["verified_at"] = "2026-10-15"
    assert [p for p in registry_problems(reg, catalog) if "verified_at only belongs on a done cell" in p]


def test_the_prose_length_caps(registry, catalog):
    # the caps are a ratchet: raising one has to be a visible change here, reviewed on its own
    assert (MAX_EVIDENCE_CHARS, MAX_LIMIT_CHARS, MAX_REASON_CHARS) == (700, 300, 450)
    reg = copy.deepcopy(registry)
    _, _, done = _first_done_cap(reg)
    original = done["evidence"]
    done["evidence"] = "src/a.py:1 " + "字" * MAX_EVIDENCE_CHARS
    assert [p for p in registry_problems(reg, catalog) if "evidence is" in p and "docs/registry-a1-checks.json" in p]
    done["evidence"] = original
    done["limit"] = "字" * (MAX_LIMIT_CHARS + 1)
    assert [p for p in registry_problems(reg, catalog) if "limit is" in p]
    del done["limit"]
    _, _, pending = _first_pending_cap(reg)
    pending["reason"] = "字" * (MAX_REASON_CHARS + 1)
    assert [p for p in registry_problems(reg, catalog) if "reason is" in p]
    assert not [p for p in registry_problems(registry, catalog) if "characters" in p]       # the shipped registry is within its caps


A1_CHECKS_PATH = _ROOT / "docs" / "registry-a1-checks.json"


def _cell_status(reg, key):
    kind, rest = key.split(":", 1)
    ident, project = rest.rsplit("|", 1)
    if kind == "cap":
        return next(c for c in reg["capabilities"] if c["id"] == ident)["status"][project]
    code, aspect = ident.rsplit(":", 1)
    return next(r for r in reg["catalog"] if r["code"] == code)[aspect][project]


def test_every_archived_a1_check_belongs_to_a_done_cell(registry):
    archive = json.loads(A1_CHECKS_PATH.read_text(encoding="utf-8"))["cells"]
    assert archive
    for key, entry in archive.items():
        assert _cell_status(registry, key)["state"] == "done", key
        assert entry["a1_check"].strip().startswith("A1 正式機（新）"), key
        assert set(entry) == {"a1_check"}




def _load_one_off():
    spec = importlib.util.spec_from_file_location("migrate_fields", _ROOT / "scripts" / "one_off" / "migrate_registry_fields_20261015.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_splits_losslessly_and_keeps_a_citation_in_evidence():
    m = _load_one_off()
    text = ("src/a.py:10 does X；src/b.py:3 does Y。 A1 正式機（新）執行環境（唯讀查證，2026-10-14 台北）：/opt 的 src/a.py（blob abc1234）相同。 "
            "限制：A1 沒觸發過。")
    parts = m.split_evidence(text)
    assert parts["evidence"] == "src/a.py:10 does X；src/b.py:3 does Y。"
    assert parts["a1_check"].startswith("A1 正式機（新）執行環境") and parts["a1_check"].endswith("相同。")
    assert parts["limit"] == "A1 沒觸發過。" and parts["verified_at"] == "2026-10-14"
    assert m._squash(m.recompose(parts)) == m._squash(text)
    # review of #200: a deploy date is not a check date.  Only the header parenthesis after "執行環境" can say when the check ran.
    deploy_only = "src/a.py:10 does X。 A1 正式機（新）執行環境（唯讀查證）：operations abc1234 於 2026-10-08 台北 21:26 部署；/opt 的 src/a.py 相同。 限制：y"
    assert m.split_evidence(deploy_only)["verified_at"] is None
    assert m.split_evidence("x src/a.py:1。 A1 正式機（新）執行環境（2026-10-04 台北約 20:16 唯讀查）：ok。")["verified_at"] == "2026-10-04"
    assert m.split_evidence("x src/a.py:1。 A1 正式機（新）執行環境（部署 2026-10-04 台北）：ok。")["verified_at"] is None
    assert m.check_date(None) is None
    only_limit = m.split_evidence("src/a.py:1 does X。限制：none yet")
    assert only_limit["a1_check"] is None and only_limit["limit"] == "none yet" and only_limit["evidence"] == "src/a.py:1 does X。"
    plain = "src/a.py:1 does X"
    assert m.split_evidence(plain) == {"evidence": plain, "a1_check": None, "limit": None, "verified_at": None}
    # every citation sits inside the A1 paragraph: splitting would leave evidence without a file, so the cell is left alone
    unsplittable = "does X。 A1 正式機（新）執行環境：/opt 的 src/a.py 相同。 限制：y"
    assert m.split_evidence(unsplittable)["a1_check"] is None and m.split_evidence(unsplittable)["evidence"] == unsplittable


def test_the_pages_show_the_limit_and_the_verification_date_as_their_own_elements(registry, catalog):
    render_guides = _render_guides()
    data = _page_data(render_guides.render_rollout_register(catalog, registry, render_guides.load_glossary()))
    lines = [line for item in data["items"] for row in item["rows"] for line in row["lines"]]
    with_limit = [l for l in lines if l.get("limit")]
    assert with_limit and all(l["state"] == "done" and "限制：" not in l["text"] for l in with_limit)
    assert any(l.get("verified_at") for l in lines)
    risk = _page_data(render_guides.render_risk_register(catalog, registry))
    assert all(set(e["behaviour"]) == {"state"} and set(e["emits_event"]) == {"state"} for e in risk["entries"])   # evidence is not shown there


def test_every_verified_at_in_the_registry_is_the_check_date_its_archived_paragraph_states(registry):
    """Regression for the #200 review: the first date in a paragraph used to be taken, which is often the deploy date."""
    m = _load_one_off()
    archive = json.loads((Path(__file__).resolve().parents[1] / "docs" / "registry-a1-checks.json").read_text(encoding="utf-8"))["cells"]
    for key, status in m.cells(registry):
        if status["state"] == "done" and key in archive:
            assert status.get("verified_at") == m.check_date(archive[key]["a1_check"]), key


def test_trend_meteor_has_its_column_and_the_pending_mechanism_still_guards_the_next_project(registry, catalog, monkeypatch):
    """v0.30.25：V11 的欄位與目錄條目一起補上（進度頁 1.6a）。`REGISTRY_PENDING_PROJECTS` 這個機制留著：之後有專案先寫事件、還沒有欄位時，它的代碼不能先進目錄。"""
    import trade_alerts.rollout_registry as rr
    assert rr.REGISTRY_PENDING_PROJECTS == ()
    assert "trend-meteor" in STRATEGY_PROJECTS
    assert owners("FLEET.ANYTHING") == STRATEGY_PROJECTS and "trend-meteor" in owners("FLEET.ANYTHING")      # 跨 repo 的條件現在也含流星池
    assert owners("MET.LEDGER_DATA_QUALITY") == ("trend-meteor",)
    assert registry_problems(registry, catalog) == []
    monkeypatch.setattr(rr, "REGISTRY_PENDING_PROJECTS", ("trend-meteor",))
    assert any("no registry column yet" in p for p in registry_problems(registry, catalog))


def test_trend_meteor_has_no_done_cell_until_it_runs_on_the_live_branch(registry):
    """『已做』只算正式機分支（operations）上的；V11 還沒上線，所有格子只能是未做、已完成未上線或不適用，不能有已做。有一格寫已做就要先確認 sources 的 commit 真的含 V11 程式。"""
    rows = project_rows(registry, "trend-meteor")
    assert len(rows) == 35 + 2 * (9 + 37)                                                     # 35 項能力＋（9 條 FLEET＋36 條 MET）×（行為、事件）
    assert {r["state"] for r in rows.values()} <= {"built", "pending", "n/a"}, [k for k, r in rows.items() if r["state"] == "done"]


V11_TIERS = {
    # 1.6a：共用處理器要的 7 條
    "MET.VERIFIED_CLOSE_AUTO_REPAIRED": ("R1", "MECHANICAL"), "MET.VERIFIED_CLOSE_REPAIR_FAILED": ("R2", "JUDGEMENT"),
    "MET.VERIFIED_CLOSE_REPAIR_BLOCKED": ("R3", "JUDGEMENT"), "MET.VERIFIED_CLOSE_REPAIR_RECURRING": ("R3", "JUDGEMENT"),
    "MET.UNRECORDED_FILL_CORRECTED": ("R3", "JUDGEMENT"), "MET.UNRECORDED_FILL_UNRESOLVED": ("R3", "JUDGEMENT"),
    "MET.LEDGER_DATA_QUALITY": ("R3", "JUDGEMENT"),
    # 1.6b：V11 自己發的事件
    "MET.DATA_UNAVAILABLE": ("R2", "JUDGEMENT"), "MET.RUNTIME_CYCLE_FAILED": ("R0", "MECHANICAL"), "MET.LEDGER_ITEM_DROPPED": ("R3", "JUDGEMENT"),
    "MET.STOP_FILL_UNKNOWN": ("R3", "JUDGEMENT"), "MET.WINNER_NO_PERP": ("R3", "JUDGEMENT"), "MET.FUNDING_SHEET_WRITE_FAILED": ("R2", "JUDGEMENT"),
    # v0.30.32（進度頁 1.10）：待記帳積壓累計 3 個 UTC 日才通知一次，只通知不暫停
    "MET.LEDGER_WRITE_STUCK": ("R2", "JUDGEMENT"),
    # 1.6b：V11 的安全暫停原因碼（全部 R3：策略對部位、保護單或自己的記錄失去把握，停下來等人看交易所）
    **{f"MET.{c}": ("R3", "JUDGEMENT") for c in (
        "STATE_FILE_CORRUPT", "MISSED_DAYS", "HEDGE_MODE", "NOT_ISOLATED", "LEVERAGE_NOT_1", "UNEXPECTED_POSITION", "BAD_EXCHANGE_DATA",
        "ORDER_OUTCOME_UNKNOWN", "ORDER_NOT_TERMINAL", "PENDING_UNRESOLVED", "STEP_OUTCOME_UNKNOWN", "STOP_OUTCOME_UNKNOWN", "PROTECTION_UNVERIFIED",
        "STALE_STOP_CANCEL_FAILED", "STOP_STATE_UNKNOWN", "STOP_STATUS_UNRECOGNIZED", "POSITION_GONE_STOP_NOT_TRIGGERED", "STOP_TRIGGERED_UNREPORTED",
        "MARGIN_BELOW_FLOOR", "RECOVERY_LOOKUP_FAILED", "RECOVERY_STOP_STATE", "UNKNOWN_STEP", "EXECUTION_FAILED")},
}


def test_trend_meteor_catalog_entries_are_the_v11_ones_with_the_tiers_the_code_and_runners_need(catalog):
    entries = {e["code"]: e for e in catalog["entries"] if e["project"] == "trend-meteor"}
    assert {c: (e["risk_tier"], e["verdict"]) for c, e in entries.items()} == V11_TIERS and len(V11_TIERS) == 37


def test_trend_meteor_halt_entries_latch_and_say_the_resume_tool_is_a_5d_job(catalog):
    """暫停原因碼：latch 碼＝代碼名、解除路徑是兩段式；解除工具還沒做，條目不能把它寫成現成的（也不能出現要貼的指令）。"""
    import re
    halts = [e for e in catalog["entries"] if e["project"] == "trend-meteor" and e["current"]["latch"]]
    assert len(halts) == 24                                                                  # 23 個暫停原因碼＋DATA_UNAVAILABLE（連續 3 天升格後暫停）
    for e in halts:
        assert e["current"]["latch"] == e["code"].split(".", 1)[1] and e["resume"] == "two_stage_fingerprint", e["code"]
        assert "5d" in e["auto_action"], e["code"]
        assert not [sp for st in e["operator_message"]["steps"] for sp in re.findall(r"`[^`]+`", st)], e["code"]


def test_the_events_the_meteor_code_records_as_non_latching_say_how_they_reach_a_person(catalog):
    """不暫停的事件：R3 事件通知一次、R2 要升格才通知；R0 只記錄。V11 程式的記錄等級必須和這裡一致（V11 repo 的守門測試以真目錄逐一檢查）。"""
    by = {e["code"]: e for e in catalog["entries"] if e["project"] == "trend-meteor"}
    assert by["MET.WINNER_NO_PERP"]["risk_tier"] == "R3" and "各通知一次" in by["MET.WINNER_NO_PERP"]["auto_action"]
    assert by["MET.RUNTIME_CYCLE_FAILED"]["risk_tier"] == "R0" and by["MET.RUNTIME_CYCLE_FAILED"]["current"]["unit_exit"] == 1
    assert by["MET.FUNDING_SHEET_WRITE_FAILED"]["current"]["unit_exit"] == 3


# --- PR #343 審閱 BLOCK-343-01～08：條目文字只寫程式實際做的事 ----------------------------------------
def _met(catalog, code):
    return next(e for e in catalog["entries"] if e["code"] == f"MET.{code}")


def _all_text(entry):
    return json.dumps(entry, ensure_ascii=False)


def test_met_entry_texts_do_not_claim_what_the_v11_code_does_not_do(catalog):
    # 01 狀態檔備份只是嘗試，另存失敗時路徑仍會寫進 evidence、檔案不在
    e = _met(catalog, "STATE_FILE_CORRUPT")
    assert "嘗試" in e["operator_message"]["what"] and "另存失敗" in e["operator_message"]["what"]
    assert "真的存在" in " ".join(e["operator_message"]["steps"])
    # 02 執行器內部的 stop_missing 事件不會寫進事件日誌（halt 路徑只發布暫停事件）
    assert "stop_missing" not in _all_text(_met(catalog, "PROTECTION_UNVERIFIED"))
    # 03 資料抓不到的天數是「不同 UTC 日的累計」，不檢查連續日曆日；解除後補做有上限
    e = _met(catalog, "DATA_UNAVAILABLE")
    assert "累計 3 個" in e["operator_message"]["what"] and "不檢查" in e["auto_action"] and "連續 3 個 UTC 日" not in _all_text(e)
    assert "MET.MISSED_DAYS" in e["human_action"] and "最多補 3 個收盤日" in e["human_action"]
    # 04 單元非零結束只在重試用盡或不能重試時
    e = _met(catalog, "RUNTIME_CYCLE_FAILED")
    assert "重試" in e["auto_action"] and "最多 3 次" in e["auto_action"] and "重試用盡" in e["auto_action"] and e["current"]["unit_exit"] == 1
    # 05 兩種觸發的 evidence 欄位不同；積壓超限不證明帳本持續寫入失敗
    e = _met(catalog, "LEDGER_ITEM_DROPPED")
    assert "只有 dropped" in e["auto_action"] and "不驗證失敗持續了多久" in e["auto_action"] and "只有 dropped" in " ".join(e["operator_message"]["steps"])
    # 06 修復機器人只補「整筆交易沒有任何平倉列」的；部分減碼要人處理
    e = _met(catalog, "STOP_FILL_UNKNOWN")
    assert "整筆沒有任何平倉列" in e["auto_action"] or "整筆交易沒有任何平倉列" in e["auto_action"]
    assert "部分減碼" in e["auto_action"] and "部分減碼" in e["operator_message"]["direction"]
    # 07 開始與結束兩種事件的意義與 evidence 欄位不同，同一份文字要兩種都講
    e = _met(catalog, "WINNER_NO_PERP")
    assert "【開始】" in e["operator_message"]["what"] and "【結束】" in e["operator_message"]["what"]
    assert "streak_days" in " ".join(e["operator_message"]["steps"]) and "沒有 coin 與 held" in " ".join(e["operator_message"]["steps"])
    # 08 Google 寫入結果可能不明：不能說 G 欄確定沒更新
    e = _met(catalog, "FUNDING_SHEET_WRITE_FAILED")
    assert "尚未確認更新成功" in e["operator_message"]["what"] and "結果不明" in " ".join(e["operator_message"]["steps"])
    assert "沒有更新。" not in e["operator_message"]["what"]


def test_met_entry_texts_keep_the_conditions_the_v11_code_really_has(catalog):
    """PR #343 第二輪審閱 BLOCK-343-09～13：計數重置點、重試條件、無法識別被丟項目、強平成交沒記的範圍、表上是否被動過——都不能寫得比程式保證的更確定。"""
    e = _met(catalog, "DATA_UNAVAILABLE")                                                      # 09 歸零在每日決策完成後（下單之前），不是「成功跑完一輪」
    assert "決策階段完成後就歸零" in e["auto_action"] and "成功跑完一輪才歸零" not in _all_text(e) and "同一個 UTC 日只算一天" in e["auto_action"]
    e = _met(catalog, "RUNTIME_CYCLE_FAILED")                                                  # 10 只有程式標記可重試的例外才重試；連線檢查通過後就算進入可能改動交易所的階段
    assert "標記為可重試" in e["auto_action"] and "連線檢查通過後" in e["auto_action"] and "還沒碰交易所狀態之前失敗的" not in _all_text(e)
    e = _met(catalog, "LEDGER_ITEM_DROPPED")                                                   # 11 積壓超限時沒有逐筆記下被丟的項目
    steps = " ".join(e["operator_message"]["steps"])
    assert "無法直接識別" in steps and "找出被丟的是哪幾筆" not in steps
    e = _met(catalog, "STOP_FILL_UNKNOWN")                                                     # 12 不是所有情況都「沒有平倉」
    assert "帳本裡有進場、沒有平倉" not in e["rationale"] and "先前已有部分減碼的平倉列" in e["rationale"]
    e = _met(catalog, "FUNDING_SHEET_WRITE_FAILED")                                            # 13 接收端回報未成功也不保證表沒被動過
    assert "表一定沒有更新" not in _all_text(e) and "明確回報未成功" in " ".join(e["operator_message"]["steps"]) and "不論是哪一種原因" in " ".join(e["operator_message"]["steps"])


# --- 已完成、尚未上線（built）與未做（pending）的界線（PR #351 審閱 BLOCK-351-01／02）------------------------------
@pytest.mark.parametrize("states, expected", [
    ({"pending", "built"}, "pending"), ({"pending", "done"}, "pending"), ({"done", "built"}, "built"), ({"built"}, "built"),
    ({"built", "n/a"}, "built"), ({"done", "n/a"}, "done"),  # 不適用的策略不拖累：其餘適用的都已做就是已做
    ({"done"}, "done"), ({"n/a"}, "n/a"),
])
def test_a_fleet_row_across_strategies_combines_states_with_pending_first_then_built(states, expected):
    statuses = {f"p{i}": {"state": s} for i, s in enumerate(sorted(states))}
    assert _render_guides()._combined(statuses)["state"] == expected


_WRITTEN_ON_DEVELOPMENT = re.compile(r"已在(趨勢 repo )?開發分支|在開發分支")
_SAYS_WHAT_IS_MISSING = re.compile(r"還沒|尚未寫|沒有|要先|檢討|判斷|實測|待決定|前補|前做|之後做")


def test_a_pending_cell_that_says_the_code_is_on_development_names_what_is_still_missing(registry):
    """pending 專指還沒寫或還沒決定。理由若說程式已在開發分支，就必須同時寫出還缺什麼；只剩『尚未實跑』的格子是 built。"""
    bad = []
    for capability in registry["capabilities"]:
        for project, status in capability["status"].items():
            if status["state"] == "pending" and _WRITTEN_ON_DEVELOPMENT.search(status["reason"]) and not _SAYS_WHAT_IS_MISSING.search(status["reason"]):
                bad.append(f"cap {capability['id']} / {project}")
    for row in registry["catalog"]:
        for aspect in ("behaviour", "emits_event"):
            for project, status in row[aspect].items():
                if status["state"] == "pending" and _WRITTEN_ON_DEVELOPMENT.search(status["reason"]) and not _SAYS_WHAT_IS_MISSING.search(status["reason"]):
                    bad.append(f"{row['code']} {aspect} / {project}")
    assert bad == []


V11_STILL_PENDING = {
    "cap latch.restart_only_clear", "cap latch.consecutive_failure_counter", "cap reconcile.google_status", "cap docs.glossary_adopted",
    "cap reconcile.adopted_fills", "cap projection.requeue_parked",
    "FLEET.OPS_GOOGLE_DIVERGED behaviour", "FLEET.OPS_GOOGLE_DIVERGED emits_event",
    "FLEET.OPS_CLOCK_DEGRADED behaviour", "FLEET.OPS_CLOCK_DEGRADED emits_event",
    "MET.LEDGER_WRITE_STUCK behaviour", "MET.LEDGER_WRITE_STUCK emits_event",     # 新條目：程式在 V11 的 1.10 做，做完改已完成、尚未上線
}


def test_the_v11_cells_that_are_still_pending_are_exactly_the_ones_not_written_or_not_decided(registry):
    """V11 還剩的『未做』逐格點名（改了要有意識地改這份清單與對外說明）：其餘寫好的都是『已完成、尚未上線』。"""
    pending = {f"cap {c['id']}" for c in registry["capabilities"] if c["status"]["trend-meteor"]["state"] == "pending"}
    pending |= {f"{row['code']} {aspect}" for row in registry["catalog"] for aspect in ("behaviour", "emits_event")
                if row[aspect].get("trend-meteor", {}).get("state") == "pending"}
    assert pending == V11_STILL_PENDING


def test_the_rollout_page_intro_no_longer_says_development_only_code_counts_as_not_done(registry, catalog):
    """頁面開頭要說清楚三類：不能再寫『只在開發主幹的一律算未做』，因為寫好的已經分出『已完成、尚未上線』。"""
    html = _render_guides().render_rollout_register(catalog, registry, _render_guides().load_glossary())
    assert "的一律算「未做」" not in html
    assert "已完成、尚未上線" in html and "還沒寫或還沒決定的才算「未做」" in html


# --- 2026-11-10 登記冊命名統一（進度頁 1.9）：V11 叫「趨勢策略」，舊趨勢已停用、待封存、頁面不顯示欄 ---------------------------


def test_v11_is_called_trend_strategy_and_the_old_one_is_marked_retired(registry):
    assert registry["projects"]["trend-meteor"] == "趨勢策略"
    assert registry["projects"]["seykota"] == "舊趨勢（已停用、待封存）"
    assert RETIRED_PROJECTS == ("seykota",) and "seykota" not in ACTIVE_PROJECTS
    assert set(ACTIVE_PROJECTS) | set(RETIRED_PROJECTS) == set(STRATEGY_PROJECTS)


def test_rollout_page_has_no_column_for_the_retired_project_but_the_data_is_kept(registry, catalog):
    data = _page_data(_render_guides().render_rollout_register(catalog, registry, _render_guides().load_glossary()))
    assert data["project_order"] == list(ACTIVE_PROJECTS)
    assert set(data["totals"]) == set(ACTIVE_PROJECTS)
    for item in data["items"]:
        assert set(item["dots"]) == set(ACTIVE_PROJECTS)
        assert all(row["label"] != registry["projects"]["seykota"] for row in item["rows"])
    # 資料留著，等舊趨勢在正式機下線、repo 封存時再整批刪
    assert any("seykota" in c["status"] for c in registry["capabilities"])
    assert any(code.startswith("SEY.") for code in (row["code"] for row in registry["catalog"]))
    assert "seykota" in registry["sources"]


def test_risk_page_still_lists_the_retired_project_errors_under_its_new_label(registry, catalog):
    pages = {path.name: html for path, html in _render_guides().rendered_pages().items()}
    risk = _page_data(pages["fleet-risk-register.html"])
    sey = [e for e in risk["entries"] if e["code"].startswith("SEY.")]
    assert sey and {e["bot_label"] for e in sey} == {"舊趨勢（已停用、待封存）"}
    assert any(b["id"] == "seykota" and b["label"] == "舊趨勢（已停用、待封存）" for b in risk["bots"])


def test_a_new_capability_or_fleet_row_need_not_fill_the_retired_cell(registry, catalog):
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].pop("seykota"))
    assert not [p for p in problems if "capability" in p]
    fleet_code = next(row["code"] for row in registry["catalog"] if row["code"].startswith("FLEET."))

    def drop(reg):
        row = next(r for r in reg["catalog"] if r["code"] == fleet_code)
        for key in ("behaviour", "emits_event"):
            row[key].pop("seykota")
    assert not [p for p in _problems_after(registry, catalog, drop) if fleet_code in p]
    # 但活著的策略一個都不能少
    problems = _problems_after(registry, catalog, lambda r: _capability(r)["status"].pop("trend-meteor"))
    assert any("must list every active strategy" in p for p in problems)


def test_a_single_owner_rule_still_needs_its_own_cell(registry, catalog):
    sey = next(row["code"] for row in registry["catalog"] if row["code"].startswith("SEY."))

    def drop(reg):
        next(r for r in reg["catalog"] if r["code"] == sey)["behaviour"].pop("seykota")
    assert any(sey in p and "behaviour" in p for p in _problems_after(registry, catalog, drop))


def test_the_ledger_write_stuck_entry_notifies_once_and_never_halts(catalog, registry):
    entry = next(e for e in catalog["entries"] if e["code"] == "MET.LEDGER_WRITE_STUCK")
    assert (entry["error_id"], entry["risk_tier"], entry["resume"]) == ("ERR-108", "R2", "n/a")
    assert entry["current"]["latch"] is None and catalog["error_ids_issued"] == 108
    assert "不暫停" in entry["auto_action"] and "3 天" in entry["auto_action"] and "不同的 UTC 日" in entry["auto_action"]
    assert "MET.LEDGER_ITEM_DROPPED" in entry["auto_action"]                                       # 丟棄是另一條（R3），這條不取代它
    # BLOCK-355-01：自動補記只適用於仍留在待記帳清單的項目；已被丟棄的（MET.LEDGER_ITEM_DROPPED）不會自動補回，文字不可無條件承諾「不需要手動補記」
    for text in (entry["human_action"], entry["operator_message"]["direction"]):
        assert "仍留在待記帳清單" in text and "MET.LEDGER_ITEM_DROPPED" in text and "不會自動補回" in text
    assert "不需要手動補記" not in entry["human_action"] + entry["operator_message"]["direction"] + " ".join(entry["operator_message"]["steps"])
    assert any("MET.LEDGER_ITEM_DROPPED" in step for step in entry["operator_message"]["steps"])
    assert "不保證沒有項目已經被丟棄" in entry["auto_action"]
