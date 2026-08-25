from __future__ import annotations

import json

from trade_alerts.ledger_integrity import build_provenance
from trade_alerts.provenance_outbox import append_outbox_record


def _provenance():
    return build_provenance(
        project_id="mexc-4h-momentum",
        trade_id="c" * 32,
        event_type="trade_open",
        ledger_event={"event_type": "trade_open", "trade_id": "c" * 32},
        projection={"trade_id": "c" * 32, "entry_price": 1.0},
        request_id="00000000-0000-4000-8000-000000000004",
        issued_at="2026-08-25T10:00:00Z",
        source_id="momentum-wsl-prod",
    )


def test_outbox_records_only_non_secret_provenance_lifecycle(tmp_path):
    path = tmp_path / "provenance.jsonl"
    pending = append_outbox_record(path, provenance=_provenance(), action="append_open_v2", status="PENDING")
    confirmed = append_outbox_record(path, provenance=_provenance(), action="append_open_v2", status="CONFIRMED", receiver_row=4)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["PENDING", "CONFIRMED"]
    assert pending["provenance"]["trade_id"] == "c" * 32
    assert confirmed["receiver_row"] == 4
    serialized = path.read_text(encoding="utf-8")
    assert "secret" not in serialized.lower()
    assert "signature" not in serialized.lower()
