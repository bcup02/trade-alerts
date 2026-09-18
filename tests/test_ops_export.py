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
    needs_human,
    render_notice_text,
    write_ops_export,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "fleet-ops-export-v2.schema.json"
NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
CATALOG = load_error_catalog()
BY_CODE = {entry["code"]: entry for entry in CATALOG["entries"]}


def _iso(moment):
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "fleet_event_log.jsonl", tmp_path / "error_requests.jsonl"


def _event(log, *, code, risk_tier, age=timedelta(hours=1), project="momentum", **extra):
    return append_fleet_event(
        log, project=project, code=code, risk_tier=risk_tier, recorded_at=_iso(NOW - age), **extra,
    )


def _escalated(**details):
    return {"escalated": True, **details}


def _build(paths, **kwargs):
    log, queue = paths
    return build_ops_export(log, queue, project="momentum", catalog=CATALOG, now=NOW, **kwargs)


def test_missing_files_give_an_empty_export(paths):
    assert _build(paths) == {
        "export_version": OPS_EXPORT_VERSION, "project": "momentum", "generated_at": "2026-09-18T12:00:00Z",
        "window_days": 7, "notices": [], "open_requests": [],
    }
    assert OPS_EXPORT_VERSION == "fleet-ops-export/v2"


# --------------------------------------------------------------------------- #
# who reaches a human (fleet-error-catalog/v2)
# --------------------------------------------------------------------------- #
def test_r0_and_r1_never_become_notices(paths):
    log, _queue = paths
    _event(log, code="RUNTIME_CYCLE_FAILED", risk_tier="R0")
    _event(log, code="VERIFIED_CLOSE_AUTO_REPAIRED", risk_tier="R1", details={"notice_text": "x"})
    assert NOTIFYING_TIERS == ("R2", "R3")
    assert _build(paths)["notices"] == []


def test_r2_stays_silent_until_it_escalates(paths):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R2", details={"attempt": 1})
    _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R2", details={"attempt": 2, "escalated": False})
    assert _build(paths)["notices"] == []

    escalated = _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R2", details=_escalated(attempt=3))
    [notice] = _build(paths)["notices"]
    assert notice["event_id"] == escalated["event_id"]
    assert notice["risk_tier"] == "R2" and notice["critical"] is False
    assert notice["text"].startswith("⚠️ 自動處理失敗，需要你處理")


def test_escalation_flag_must_be_literally_true(paths):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R2", details={"escalated": "yes"})
    assert _build(paths)["notices"] == []


def test_needs_human_rule():
    assert needs_human({}, "R3") is True
    assert needs_human({"details": {"escalated": True}}, "R2") is True
    assert needs_human({"details": {}}, "R2") is False
    assert needs_human({"details": {"escalated": True}}, "R1") is False
    assert needs_human({}, None) is False


def test_r3_notice_carries_header_plain_language_technical_detail_and_ai_block(paths):
    log, _queue = paths
    event = _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R3", summary="ledger write failed",
                   evidence={"trade_id": "T1", "incident_id": "inc-1"},
                   details={"notice_text": "incident_id: inc-1\ntrade_id: T1"})

    [notice] = _build(paths)["notices"]

    assert notice["event_id"] == event["event_id"]
    assert notice["code"] == "MOM.VERIFIED_CLOSE_REPAIR_BLOCKED"
    assert notice["risk_tier"] == "R3" and notice["critical"] is True
    text = notice["text"]
    assert text.startswith("🔴 需要人工處理\n自動修復停手")
    assert "發生什麼事：" in text and "解決方向：" in text and "處理步驟：\n1. " in text
    assert "技術細節：\nincident_id: inc-1\ntrade_id: T1" in text
    assert "ledger write failed" not in text  # notice_text wins over the summary
    ai_prompt = BY_CODE["MOM.VERIFIED_CLOSE_REPAIR_BLOCKED"]["operator_message"]["ai_prompt"]
    assert "給 AI 的追查指令（整段貼給 Claude）：\n" + ai_prompt in text
    assert f"錯誤碼：momentum/VERIFIED_CLOSE_REPAIR_BLOCKED　事件編號：{event['event_id']}" in text
    assert text.endswith('事件資料：{"incident_id": "inc-1", "trade_id": "T1"}')


def test_summary_is_the_technical_detail_when_no_notice_text(paths):
    log, _queue = paths
    _event(log, code="PROTECTION_UNVERIFIED", risk_tier="R3", summary="trailing stop not found")
    [notice] = _build(paths)["notices"]
    assert "技術細節：\ntrailing stop not found" in notice["text"]


def test_events_older_than_the_window_are_dropped(paths):
    log, _queue = paths
    _event(log, code="PROTECTION_UNVERIFIED", risk_tier="R3", age=timedelta(days=8))
    recent = _event(log, code="PROTECTION_UNVERIFIED", risk_tier="R3", age=timedelta(days=6))
    assert [n["event_id"] for n in _build(paths)["notices"]] == [recent["event_id"]]
    assert len(_build(paths, window_days=9)["notices"]) == 2


def test_notices_are_oldest_first(paths):
    log, _queue = paths
    newer = _event(log, code="PROTECTION_UNVERIFIED", risk_tier="R3", age=timedelta(hours=1))
    older = _event(log, code="STATE_REPAIRED_SAFE_HALT", risk_tier="R3", age=timedelta(hours=3))
    assert [n["event_id"] for n in _build(paths)["notices"]] == [older["event_id"], newer["event_id"]]


def test_tier_falls_back_to_the_catalog_when_the_event_has_none(paths):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier=None)
    [notice] = _build(paths)["notices"]
    assert notice["risk_tier"] == "R3"


def test_uncatalogued_event_with_a_recorded_tier_still_notifies_under_its_code(paths):
    log, _queue = paths
    _event(log, code="SOMETHING_NEW", risk_tier="R3", summary="brand new condition")
    [notice] = _build(paths)["notices"]
    assert notice["text"] == "🔴 需要人工處理\nSOMETHING_NEW\n\n技術細節：\nbrand new condition"


def test_uncatalogued_event_without_a_tier_is_skipped(paths):
    log, _queue = paths
    _event(log, code="SOMETHING_NEW", risk_tier=None)
    assert _build(paths)["notices"] == []


def test_other_projects_events_are_ignored(paths):
    log, _queue = paths
    _event(log, code="PROTECTION_UNVERIFIED", risk_tier="R3", project="seykota")
    assert _build(paths)["notices"] == []


# --------------------------------------------------------------------------- #
# open requests
# --------------------------------------------------------------------------- #
def test_open_requests_carry_the_operator_message_and_closed_ones_are_gone(paths):
    _log, queue = paths
    blocked = open_error_request(queue, project="momentum", code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R3",
                                 summary="ledger write failed", evidence={"trade_id": "t-1"},
                                 opened_at="2026-09-18T11:00:00Z")
    closed = open_error_request(queue, project="momentum", code="VERIFIED_CLOSE_PROPOSED", risk_tier="R2",
                                evidence={"trade_id": "t-2"})
    record_request_outcome(queue, request_id=closed["request_id"], status="RESOLVED_HUMAN")

    [request] = _build(paths)["open_requests"]

    message = BY_CODE["MOM.VERIFIED_CLOSE_REPAIR_BLOCKED"]["operator_message"]
    assert request == {
        "request_id": blocked["request_id"], "fingerprint": blocked["fingerprint"],
        "code": "MOM.VERIFIED_CLOSE_REPAIR_BLOCKED", "risk_tier": "R3", "opened_at": "2026-09-18T11:00:00Z",
        "summary": "ledger write failed", "what": message["what"], "direction": message["direction"],
        "steps": message["steps"], "ai_prompt": message["ai_prompt"], "handling_started_at": None,
    }


def test_open_request_for_an_uncatalogued_code_has_nulls(paths):
    _log, queue = paths
    open_error_request(queue, project="momentum", code="SOMETHING_NEW", risk_tier="R3", evidence={"x": 1})
    [request] = _build(paths)["open_requests"]
    assert request["what"] is None and request["direction"] is None
    assert request["steps"] == [] and request["ai_prompt"] is None


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
def test_defaults_to_the_packaged_catalog(paths):
    log, queue = paths
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R3")
    [notice] = build_ops_export(log, queue, project="momentum", now=NOW)["notices"]
    assert "發生什麼事：" in notice["text"] and "給 AI 的追查指令" in notice["text"]


def test_rejects_a_non_positive_window(paths):
    with pytest.raises(ValueError):
        _build(paths, window_days=0)


def test_malformed_event_log_raises_instead_of_exporting_a_partial_view(paths):
    log, _queue = paths
    log.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _build(paths)


def test_render_notice_text_without_entry_or_detail():
    assert render_notice_text({"code": "X"}, None, "R3") == "🔴 需要人工處理\nX"


def test_write_is_atomic_world_readable_and_round_trips(paths, tmp_path):
    log, _queue = paths
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R3", details={"notice_text": "詳細"})
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
    _event(log, code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R3", details={"notice_text": "x"})
    _event(log, code="VERIFIED_CLOSE_PROPOSED", risk_tier="R2", details=_escalated())
    _event(log, code="VERIFIED_CLOSE_AUTO_REPAIRED", risk_tier="R1")
    open_error_request(queue, project="momentum", code="VERIFIED_CLOSE_REPAIR_BLOCKED", risk_tier="R3",
                       evidence={"trade_id": "t-1"})
    export = _build(paths)
    assert sorted(n["risk_tier"] for n in export["notices"]) == ["R2", "R3"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(export))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]
