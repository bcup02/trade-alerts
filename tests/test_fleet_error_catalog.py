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
CATALOG_PATH = _ROOT / "src" / "trade_alerts" / "catalog" / "fleet-error-catalog-v1.json"
SCHEMA_PATH = _ROOT / "schemas" / "fleet-error-catalog-v1.schema.json"


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
    anything different, the condition must not be able to page one.  R2 is the
    one tier that automates without notifying, so MECHANICAL is limited to
    R0/R2 and every notifying tier is reserved for JUDGEMENT."""
    tiers = catalog["risk_tiers"]
    for entry in catalog["entries"]:
        tier = tiers[entry["risk_tier"]]
        if entry["verdict"] == "MECHANICAL":
            assert not tier["notifies"], entry["code"]
        else:
            assert tier["notifies"], entry["code"]


def test_an_audit_notice_never_doubles_as_a_decision_request(catalog):
    """Phase 6 draws a line the governing test above depends on: a tier may
    tell a human what it already did (``audit_notice``) without that counting
    as asking them to decide (``notifies``).  The line only holds while the
    two can never be true at once -- otherwise any tier could notify freely by
    calling it an audit notice, and MECHANICAL conditions would be back to
    paging people."""
    for name, tier in catalog["risk_tiers"].items():
        if tier["audit_notice"]:
            assert not tier["notifies"], name
            assert tier["auto_executes"], name


def test_only_an_automatic_tier_reports_after_the_fact(catalog):
    """An audit notice reports a completed action, so a tier that executes
    nothing has nothing to report."""
    reporting = {name for name, tier in catalog["risk_tiers"].items() if tier["audit_notice"]}
    assert reporting == {"R2"}


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
        assert set(message) == {"what", "direction", "steps"}, entry["code"]
        assert isinstance(message["what"], str) and message["what"].strip(), entry["code"]
        assert isinstance(message["direction"], str) and message["direction"].strip(), entry["code"]
        assert isinstance(message["steps"], list) and message["steps"], entry["code"]
        for step in message["steps"]:
            assert isinstance(step, str) and step.strip(), entry["code"]


def test_r0_conditions_carry_no_operator_message(catalog):
    """R0 notifies nobody, so text written for it could never be read."""
    for entry in catalog["entries"]:
        if entry["risk_tier"] == "R0":
            assert "operator_message" not in entry, entry["code"]


def test_momentum_repair_bot_conditions_have_operator_messages(catalog):
    """Phase 7b wires these three to ops-notify first; the export would fall
    back to the bare catalog title without them."""
    by_code = {entry["code"]: entry for entry in catalog["entries"]}
    for code in ("MOM.VERIFIED_CLOSE_PROPOSED", "MOM.VERIFIED_CLOSE_AUTO_REPAIRED", "MOM.VERIFIED_CLOSE_REPAIR_BLOCKED"):
        assert "operator_message" in by_code[code], code


def test_packaged_catalog_is_the_file_the_tests_read():
    from trade_alerts import load_error_catalog

    assert load_error_catalog() == json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
