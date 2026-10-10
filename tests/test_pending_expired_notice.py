"""f-30: the competition-shaped announcer (one ``pending_expired`` dict, not a marker list)."""
from __future__ import annotations

import json
import threading

import pytest

from trade_alerts.fleet_event_log import read_fleet_events
from trade_alerts.pending_expired_notice import (
    CODE_PENDING_EXPIRED,
    announce_batch_expired,
    expired_markers,
    plan_pending_expired_notice,
)

BLOCK = {"reason": "waited_over_limit", "since": "2026-10-02T08:10:00Z", "age_hours": 50.0, "max_hours": 24.0,
         "rebalance_batch_without_snapshot": True, "spot_fills_after_last_snapshot": 1}


def _status(block=BLOCK, value="RECONCILED"):
    return {"value": value, "evidence": {"pending_expired": block}}


def _announce(log, status, **kw):
    return announce_batch_expired(status, project="btc-competition", fleet_event_log=log, risk_tier="R3", **kw)


def test_announced_once_per_episode(tmp_path):
    log = tmp_path / "log.jsonl"
    first = _announce(log, _status())
    assert first["code"] == CODE_PENDING_EXPIRED and first["evidence"] == {"episode": "2026-10-02T08:10:00Z"}
    assert _announce(log, _status()) is None
    assert _announce(log, _status({**BLOCK, "since": "2026-10-09T08:10:00Z"}))["evidence"]["episode"].startswith("2026-10-09")
    assert len(read_fleet_events(log)) == 2


def test_other_projects_events_do_not_suppress_it(tmp_path):
    log = tmp_path / "log.jsonl"
    announce_batch_expired(_status(), project="momentum", fleet_event_log=log, risk_tier="R3")
    assert _announce(log, _status()) is not None


@pytest.mark.parametrize("status", [
    None, [], "x", {}, _status(value="DIVERGED"), _status(value="PENDING"), {"value": "RECONCILED", "evidence": []},
    {"value": "RECONCILED", "evidence": {"pending_expired": []}},
    {"value": "RECONCILED", "evidence": {"pending_expired": {"markers": [{"trade_id": "T1"}]}}},   # momentum's shape
])
def test_nothing_to_announce(tmp_path, status):
    assert _announce(tmp_path / "log.jsonl", status) is None
    assert not (tmp_path / "log.jsonl").exists()


def test_concurrent_rounds_write_one_event(tmp_path):
    log = tmp_path / "log.jsonl"
    barrier, errors = threading.Barrier(8), []

    def work():
        try:
            barrier.wait()
            _announce(log, _status())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and len(read_fleet_events(log)) == 1


def test_an_unreadable_log_raises_for_the_caller_to_isolate(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text("{broken\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _announce(log, _status())


def test_the_marker_planner_ignores_the_batch_shape():
    assert expired_markers(_status()) == []
    assert plan_pending_expired_notice(_status(), [], project="btc-competition") is None
