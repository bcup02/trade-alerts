"""The fleet error catalog is data the Phase 4 queue will be built on, so the
invariants that make it usable are asserted here rather than left to review.

The formal JSON Schema check needs ``jsonschema``, which is deliberately not a
dependency of this library (nothing at runtime reads the catalog).  The
structural invariants below run unconditionally and are what actually matters:
a schema can say "risk_tier is one of five strings", it cannot say "a
MECHANICAL verdict must not end up in a tier that notifies a human".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = _ROOT / "src" / "trade_alerts" / "catalog" / "fleet-error-catalog-v2.json"
SCHEMA_PATH = _ROOT / "schemas" / "fleet-error-catalog-v2.schema.json"


@pytest.fixture(scope="module")
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_matches_its_json_schema(catalog):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(catalog))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


def test_codes_are_unique(catalog):
    codes = [entry["code"] for entry in catalog["entries"]]
    assert len(codes) == len(set(codes))


def test_every_entry_names_a_known_project(catalog):
    known = set(catalog["projects"])
    assert {entry["project"] for entry in catalog["entries"]} <= known


def test_code_prefix_agrees_with_project(catalog):
    prefix_for = {
        "seykota": "SEY", "momentum": "MOM", "mycrypto": "MYC",
        "btc-competition": "BTC", "fleet": "FLEET",
    }
    for entry in catalog["entries"]:
        assert entry["code"].split(".", 1)[0] == prefix_for[entry["project"]], entry["code"]


def test_mechanical_verdicts_never_reach_a_notifying_tier(catalog):
    """The governing test of the whole project: if a human cannot decide
    anything different, the condition must not be able to page one.  In v2 the
    two silent tiers are R0 (log) and R1 (automatic), so MECHANICAL is limited
    to those and the tiers that can reach a human (R2 once escalated, R3) are
    reserved for JUDGEMENT."""
    tiers = catalog["risk_tiers"]
    for entry in catalog["entries"]:
        tier = tiers[entry["risk_tier"]]
        if entry["verdict"] == "MECHANICAL":
            assert not tier["notifies"], entry["code"]
        else:
            assert tier["notifies"], entry["code"]


def test_v2_tier_semantics(catalog):
    """fleet-error-catalog/v2 (2026-09-18): R0 log, R1 automatic and silent, R2
    automatic with escalation after ``escalate_after`` failures, R3 human only.
    v1's after-the-fact audit notice is gone: an R1 action has no second
    option, so telling someone about it asks nothing of them."""
    tiers = catalog["risk_tiers"]
    assert set(tiers) == {"R0", "R1", "R2", "R3"}
    assert (tiers["R0"]["notifies"], tiers["R0"]["auto_executes"]) == (False, False)
    assert (tiers["R1"]["notifies"], tiers["R1"]["auto_executes"]) == (False, True)
    assert (tiers["R2"]["notifies"], tiers["R2"]["auto_executes"]) == (True, True)
    assert (tiers["R3"]["notifies"], tiers["R3"]["auto_executes"]) == (True, False)
    assert all("audit_notice" not in tier for tier in tiers.values())


def test_only_r2_escalates_and_it_says_after_how_many_failures(catalog):
    tiers = catalog["risk_tiers"]
    assert isinstance(tiers["R2"].get("escalate_after"), int) and tiers["R2"]["escalate_after"] >= 1
    assert [name for name, tier in tiers.items() if "escalate_after" in tier] == ["R2"]


def test_retired_codes_are_never_reused(catalog):
    """A retired code stays retired: an entry may keep one only while its call
    site still exists and is on its way out, and its own reason must say so."""
    retired = {item["code"]: item for item in catalog["retired_codes"]}
    assert retired, "v2 retires at least the v1 proposal codes"
    live = {entry["code"] for entry in catalog["entries"]}
    for code in retired.keys() & live:
        assert "until" in retired[code]["reason"].lower() or "直到" in retired[code]["reason"], code


def test_only_judgement_conditions_latch_after_phase_4(catalog):
    """A latch stops a strategy from trading.  Nothing whose verdict is
    MECHANICAL may keep one."""
    for entry in catalog["entries"]:
        if entry["current"]["latch"] and entry["verdict"] == "MECHANICAL":
            assert entry["resume"] == "automatic", entry["code"]


def test_latching_conditions_declare_a_resume_path(catalog):
    """seykota's original defect was eight latch reasons and no way back.
    Every condition that can latch must name how it is cleared."""
    for entry in catalog["entries"]:
        if entry["current"]["latch"]:
            assert entry["resume"] != "n/a", entry["code"]


def test_r0_conditions_do_not_burn_a_unit_exit_code(catalog):
    """An exit code is a notification channel.  An R0 condition that still
    exits non-zero is notifying through systemd behind the catalog's back --
    allowed only while the change is still scheduled for a later phase."""
    for entry in catalog["entries"]:
        if entry["risk_tier"] == "R0" and entry["current"]["unit_exit"]:
            assert entry["lands_in_phase"] > 3, entry["code"]


def test_sources_look_like_file_line_references(catalog):
    for entry in catalog["entries"]:
        for source in entry["sources"]:
            path, _, line = source.rpartition(":")
            assert path and line.isdigit(), source


def test_operator_messages_have_all_three_parts(catalog):
    """An operator_message is what a phone shows when the condition pages
    someone.  A missing "what", "direction" or step list would send a message
    that says something is wrong without saying what to do -- exactly the
    notification the whole project set out to stop sending.  Checked here as
    well as in the schema because jsonschema is optional."""
    for entry in catalog["entries"]:
        message = entry.get("operator_message")
        if message is None:
            continue
        assert set(message) <= {"what", "direction", "steps", "ai_prompt"}, entry["code"]
        assert isinstance(message["what"], str) and message["what"].strip(), entry["code"]
        assert isinstance(message["direction"], str) and message["direction"].strip(), entry["code"]
        assert isinstance(message["steps"], list) and message["steps"], entry["code"]
        for step in message["steps"]:
            assert isinstance(step, str) and step.strip(), entry["code"]


def test_every_entry_has_an_operator_message(catalog):
    """v2: every entry, not just the ones already wired to ops-notify -- the
    generated risk register page reads its plain-language text from here, and
    "write it when the strategy is connected" is how v1 ended up with 3 of 33."""
    for entry in catalog["entries"]:
        assert "operator_message" in entry, entry["code"]


def test_tiers_that_reach_a_human_carry_an_ai_prompt(catalog):
    """An R2 escalation or an R3 stop hands the operator a problem the machine
    could not solve; the message must include a prompt an AI can use to trace
    the root cause, not just "go look"."""
    for entry in catalog["entries"]:
        prompt = entry["operator_message"].get("ai_prompt")
        if entry["risk_tier"] in ("R2", "R3"):
            assert isinstance(prompt, str) and prompt.strip(), entry["code"]
        else:
            assert prompt is None, entry["code"]


def test_packaged_catalog_is_the_file_the_tests_read():
    from trade_alerts import load_error_catalog

    assert load_error_catalog() == json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_seykota_and_momentum_repair_shadow_bots_get_symmetric_catalog_entries(catalog):
    """seykota's Phase 5c shadow bot is the momentum 5b design ported unmodified
    (same single event code, same risk tier); the two must be catalogued the
    same way, or one strategy's rollout-bot activity is invisible on the
    register while the other's is not -- the exact gap this test guards."""
    entries = {entry["code"]: entry for entry in catalog["entries"]}
    mom = entries["MOM.VERIFIED_CLOSE_PROPOSED"]
    sey = entries["SEY.VERIFIED_CLOSE_PROPOSED"]
    for key in ("verdict", "risk_tier", "resume", "lands_in_phase"):
        assert mom[key] == sey[key], key
    retired = {item["code"] for item in catalog["retired_codes"]}
    assert {"MOM.VERIFIED_CLOSE_PROPOSED", "SEY.VERIFIED_CLOSE_PROPOSED"} <= retired
