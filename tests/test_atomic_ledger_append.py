"""Batch ledger appends for unattended repairs: all of it, or a fragment that
reads as nothing -- never a half-applied repair that looks complete."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from trade_alerts import AtomicAppendError, append_lines_atomically, stage_lines
from trade_alerts.ledger_reconcile import read_ledger


def _line(event_type, **fields):
    return json.dumps({"event_type": event_type, **fields}, sort_keys=True)


def _batch():
    return [
        _line("reconciliation_evidence_recorded", trade_id="T1"),
        _line("fill", trade_id="T1", volume=1.5),
        _line("trade_close", trade_id="T1", net_pnl=-24.3),
        _line("position_reconciled_closed", trade_id="T1"),
    ]


def test_appends_the_whole_batch_and_returns_its_size(tmp_path):
    ledger = tmp_path / "trading_ledger.jsonl"
    ledger.write_text(_line("trade_open", trade_id="T1") + "\n", encoding="utf-8")

    assert append_lines_atomically(ledger, _batch()) == 4

    events = read_ledger(ledger)
    assert [event["event_type"] for event in events] == [
        "trade_open", "reconciliation_evidence_recorded", "fill", "trade_close", "position_reconciled_closed",
    ]


def test_creates_the_ledger_when_it_does_not_exist_yet(tmp_path):
    ledger = tmp_path / "nested" / "trading_ledger.jsonl"
    assert append_lines_atomically(ledger, _batch()) == 4
    assert len(read_ledger(ledger)) == 4


def test_an_empty_batch_is_a_no_op(tmp_path):
    ledger = tmp_path / "trading_ledger.jsonl"
    ledger.write_text(_line("trade_open", trade_id="T1") + "\n", encoding="utf-8")
    before = ledger.read_text(encoding="utf-8")

    assert append_lines_atomically(ledger, []) == 0
    assert ledger.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "bad_line, match",
    [
        ("   ", "blank"),
        ('{"a": 1}\n{"b": 2}', "embedded newline"),
        ("not json at all", "not valid JSON"),
    ],
)
def test_refuses_a_batch_line_that_is_not_one_json_object(tmp_path, bad_line, match):
    ledger = tmp_path / "trading_ledger.jsonl"
    ledger.write_text(_line("trade_open", trade_id="T1") + "\n", encoding="utf-8")
    before = ledger.read_text(encoding="utf-8")

    with pytest.raises(AtomicAppendError, match=match):
        append_lines_atomically(ledger, [_line("fill", trade_id="T1"), bad_line])

    # Validation happens before any write: a rejected batch leaves nothing.
    assert ledger.read_text(encoding="utf-8") == before


def test_raises_when_the_file_changes_between_write_and_read_back(tmp_path, monkeypatch):
    """The read-back is the only thing standing between a partial write and a
    caller that believes the repair landed.

    ``os.fsync`` is only the injection point here, not the failure being
    modelled -- a real fsync failure raises OSError, which propagates on its
    own. What this simulates is the file's content no longer ending with the
    batch by the time it is read back, whatever the cause."""
    ledger = tmp_path / "trading_ledger.jsonl"
    real_fsync = os.fsync

    def fsync_then_file_changes_underneath(fd):
        real_fsync(fd)
        ledger.write_text("", encoding="utf-8")

    monkeypatch.setattr("trade_alerts.atomic_ledger_append.os.fsync", fsync_then_file_changes_underneath)

    with pytest.raises(AtomicAppendError, match="do not retry automatically"):
        append_lines_atomically(ledger, _batch())


def test_a_torn_trailing_line_from_an_earlier_crash_reads_as_nothing(tmp_path):
    """The documented failure shape: a crash mid-write can leave a fragment.
    read_ledger already skips it, so the batch that follows still reads clean
    and the fragment never becomes a phantom event."""
    ledger = tmp_path / "trading_ledger.jsonl"
    ledger.write_text(_line("trade_open", trade_id="T1") + "\n" + '{"event_type": "fi', encoding="utf-8")

    append_lines_atomically(ledger, _batch())

    events = read_ledger(ledger)
    assert [event["event_type"] for event in events] == [
        "trade_open", "reconciliation_evidence_recorded", "fill", "trade_close", "position_reconciled_closed",
    ]


def test_stage_lines_reads_back_what_a_staging_writer_produced(tmp_path):
    scratch = tmp_path / "scratch.jsonl"
    scratch.write_text("\n".join(_batch()) + "\n\n", encoding="utf-8")

    assert stage_lines(scratch) == _batch()


def test_stage_lines_on_a_writer_that_produced_nothing(tmp_path):
    assert stage_lines(tmp_path / "never-written.jsonl") == []
