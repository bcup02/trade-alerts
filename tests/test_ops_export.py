import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trade_alerts.error_request_queue import open_error_request, record_request_outcome
from trade_alerts.fleet_event_log import append_fleet_event, load_error_catalog
from trade_alerts.ops_export import (
    NOTIFYING_TIERS,
    OPS_EXPORT_VERSION,
    build_ops_export,
    render_notice_text,
    write_ops_export,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "fleet-ops-export-v1.schema.json"
NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
CATALOG = load_error_catalog()


def _iso(moment):
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "fleet_event_log.jsonl", tmp_path / "error_requests.jsonl"


def _event(log, *, code, risk_tier, age=timedelta(hours=1), project="momentum", **extra):
    return append_fleet_event(
        log, project=project, code=code, risk_tier=risk_tier, recorded_at=_iso(NOW - age), **extra,
    )


def _build(paths, **kwargs):
    log, queue = paths
    return build_ops_export(log, queue, project="momentum", catalog=CATALOG, now=NOW, **kwargs)


def test_missing_files_give_an_empty_export(paths):
    export = _build(paths)
    assert export == {
        "export_version": OPS_EXPORT_VERSION, "project": "momentum", "generated_at": "2026-09-17T12:00:00Z",
        "window_days": 7, "notices": [], "open_requests": [],
    }


def test_r0_events_never_become_notices(paths):
    log, _queue = paths
    _event(log, code="RUNTIME_CYCLE_FAILED", risk_tier="R0")
    assert "R0" not in NOTIFYING_TIERS
    assert _build(paths)["notices"] == []


def test_notifying_events_carry_header_plain_language_and_technical_detail(paths):
    log, _queue = paths
    event = _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R4", summary="ledger write failed",
                   details={"notice_text": "incident_id: abc\ntrade_id: t-1"})

    [notice] = _build(paths)["notices"]

    assert notice["event_id"] == event["event_id"]
    assert notice["code"] == "MOM.VERIFIED_CLOSE_REPAIR_BLOCKED"
    assert notice["risk_tier"] == "R4" and notice["critical"] is True
    text = notice["text"]
    assert text.startswith("🔴 需要人工處理\n自動修復停手")
    assert "發生什麼事：" in text and "解決方向：" in text and "處理步驟：\n1. " in text
    assert "技術細節：\nincident_id: abc\ntrade_id: t-1" in text
    assert "ledger write failed" not in text  # notice_text wins over the summary


def test_summary_is_the_technical_detail_when_no_notice_text(paths):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R1", summary="proposal computed for trade_id=t-2")
    [notice] = _build(paths)["notices"]
    assert notice["critical"] is False
    assert notice["text"].startswith("📋 修復提案（需要你決定）")
    assert notice["text"].endswith("技術細節：\nproposal computed for trade_id=t-2")


def test_r2_is_labelled_as_an_after_the_fact_notice(paths):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_AUTO_REPAIRED", risk_tier="R2")
    [notice] = _build(paths)["notices"]
    assert notice["text"].startswith("✅ 已自動處理（事後通知，不需要動作）")
    assert notice["critical"] is False


def test_events_older_than_the_window_are_dropped(paths):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R1", age=timedelta(days=8), summary="old")
    recent = _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R1", age=timedelta(days=6), summary="new")
    assert [n["event_id"] for n in _build(paths)["notices"]] == [recent["event_id"]]
    assert len(_build(paths, window_days=9)["notices"]) == 2


def test_notices_are_oldest_first(paths):
    log, _queue = paths
    newer = _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R1", age=timedelta(hours=1))
    older = _event(log, code="VERIFIED_CLOSE_AUTO_REPAIRED", risk_tier="R2", age=timedelta(hours=3))
    assert [n["event_id"] for n in _build(paths)["notices"]] == [older["event_id"], newer["event_id"]]


def test_tier_falls_back_to_the_catalog_when_the_event_has_none(paths):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier=None)
    [notice] = _build(paths)["notices"]
    assert notice["risk_tier"] == "R4"


def test_uncatalogued_event_with_a_recorded_tier_still_notifies_under_its_code(paths):
    log, _queue = paths
    _event(log, code="SOMETHING_NEW", risk_tier="R4", summary="brand new condition")
    [notice] = _build(paths)["notices"]
    assert notice["text"] == "🔴 需要人工處理\nSOMETHING_NEW\n\n技術細節：\nbrand new condition"


def test_uncatalogued_event_without_a_tier_is_skipped(paths):
    log, _queue = paths
    _event(log, code="SOMETHING_NEW", risk_tier=None)
    assert _build(paths)["notices"] == []


def test_other_projects_events_are_ignored(paths):
    log, _queue = paths
    _event(log, code="PROTECTION_UNVERIFIED", risk_tier="R4", project="seykota")
    assert _build(paths)["notices"] == []


def test_open_requests_carry_the_operator_message_and_closed_ones_are_gone(paths):
    _log, queue = paths
    blocked = open_error_request(queue, project="momentum", code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R4",
                                 summary="ledger write failed", evidence={"trade_id": "t-1"},
                                 opened_at="2026-09-17T11:00:00Z")
    closed = open_error_request(queue, project="momentum", code="VERIFIED_CLOSE_AUTO_REPAIRED", risk_tier="R2",
                                evidence={"trade_id": "t-2"})
    record_request_outcome(queue, request_id=closed["request_id"], status="RESOLVED_AUTO")

    [request] = _build(paths)["open_requests"]

    entry = next(e for e in CATALOG["entries"] if e["code"] == "MOM.VERIFIED_CLOSE_REPAIR_BLOCKED")
    assert request == {
        "request_id": blocked["request_id"], "fingerprint": blocked["fingerprint"],
        "code": "MOM.VERIFIED_CLOSE_REPAIR_BLOCKED", "risk_tier": "R4", "opened_at": "2026-09-17T11:00:00Z",
        "summary": "ledger write failed",
        "what": entry["operator_message"]["what"], "direction": entry["operator_message"]["direction"],
        "steps": entry["operator_message"]["steps"], "handling_started_at": None,
    }


def test_open_request_without_an_operator_message_has_nulls(paths):
    _log, queue = paths
    open_error_request(queue, project="seykota", code="PROTECTION_UNVERIFIED", risk_tier="R4", evidence={"x": 1})
    log, _ = paths
    [request] = build_ops_export(log, queue, project="seykota", catalog=CATALOG, now=NOW)["open_requests"]
    assert request["what"] is None and request["direction"] is None and request["steps"] == []


def test_defaults_to_the_packaged_catalog(paths):
    log, queue = paths
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R4")
    [notice] = build_ops_export(log, queue, project="momentum", now=NOW)["notices"]
    assert "發生什麼事：" in notice["text"]


def test_rejects_a_non_positive_window(paths):
    with pytest.raises(ValueError):
        _build(paths, window_days=0)


def test_malformed_event_log_raises_instead_of_exporting_a_partial_view(paths):
    log, _queue = paths
    log.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _build(paths)


def test_render_notice_text_without_entry_or_detail():
    assert render_notice_text({"code": "X"}, None, "R1") == "📋 修復提案（需要你決定）\nX"


def test_write_is_atomic_world_readable_and_round_trips(paths, tmp_path):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R4", details={"notice_text": "詳細"})
    export = _build(paths)
    target = tmp_path / "audit" / "ops_export.json"

    write_ops_export(target, export)
    write_ops_export(target, export)  # replacing an existing file

    assert json.loads(target.read_text(encoding="utf-8")) == export
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert [p.name for p in target.parent.iterdir()] == ["ops_export.json"]  # no temp file left behind


def test_export_matches_its_json_schema(paths):
    jsonschema = pytest.importorskip("jsonschema")
    log, queue = paths
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R4", details={"notice_text": "x"})
    _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R1")
    open_error_request(queue, project="momentum", code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R4",
                       evidence={"trade_id": "t-1"})
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(_build(paths)))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]
