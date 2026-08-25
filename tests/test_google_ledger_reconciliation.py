from __future__ import annotations

from trade_alerts.google_ledger_reconciliation import classify_projection_inventory
from trade_alerts.ledger_integrity import ProjectionClassification, build_provenance


def _proof(trade_id: str, event_type: str = "trade_open"):
    return build_provenance(
        project_id="mexc-4h-momentum", trade_id=trade_id, event_type=event_type,
        ledger_event={"event_type": event_type, "trade_id": trade_id, "price": 1},
        projection={"trade_id": trade_id, "price": 1},
        request_id="00000000-0000-4000-8000-000000000007",
        issued_at="2026-08-25T10:02:00Z", source_id="momentum-wsl-prod",
    )


def test_reconciliation_classifies_only_and_keeps_outbox_context():
    proof = _proof("a" * 32)
    items = [{
        "trade_id": proof.trade_id, "google_row_count": 1,
        "audit": [{"event_type": "trade_open", "payload_digest": proof.payload_digest, "status": "CONFIRMED"}],
    }]
    outbox = [{"trade_id": proof.trade_id, "event_type": "trade_open", "payload_digest": proof.payload_digest, "status": "CONFIRMED"}]
    finding = classify_projection_inventory(local_provenances=[proof], outbox_records=outbox, receiver_items=items)[0]
    assert finding.classification == ProjectionClassification.MATCHED
    assert finding.outbox_status == "CONFIRMED"


def test_reconciliation_marks_pending_rejected_duplicate_and_no_source_without_repair():
    proof = _proof("b" * 32)
    pending = classify_projection_inventory(local_provenances=[proof], outbox_records=[], receiver_items=[])[0]
    assert pending.classification == ProjectionClassification.PENDING_SYNC

    rejected = classify_projection_inventory(
        local_provenances=[proof], outbox_records=[],
        receiver_items=[{"trade_id": proof.trade_id, "google_row_count": 0, "audit": [{"event_type": "trade_open", "status": "REJECTED"}]}],
    )[0]
    assert rejected.classification == ProjectionClassification.SOURCE_REJECTED

    duplicate = classify_projection_inventory(
        local_provenances=[proof], outbox_records=[],
        receiver_items=[{"trade_id": proof.trade_id, "google_row_count": 2, "audit": [{"event_type": "trade_open", "payload_digest": proof.payload_digest, "status": "CONFIRMED"}]}],
    )[0]
    assert duplicate.classification == ProjectionClassification.DUPLICATE_GOOGLE_TRADE_ID

    historical = classify_projection_inventory(
        local_provenances=[], outbox_records=[],
        receiver_items=[{"trade_id": "historical-dry-run", "google_row_count": 1, "audit": []}],
    )[0]
    assert historical.classification == ProjectionClassification.GOOGLE_NO_LEDGER_SOURCE
