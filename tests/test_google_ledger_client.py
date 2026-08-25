from __future__ import annotations

import json

from trade_alerts.google_ledger_client import read_reconciliation_inventory_v2, submit_projection_v2
from trade_alerts.ledger_integrity import build_provenance, signed_reconciliation_request, signed_request


def _payload():
    provenance = build_provenance(
        project_id="mexc-4h-momentum",
        trade_id="d" * 32,
        event_type="trade_open",
        ledger_event={"event_type": "trade_open", "trade_id": "d" * 32},
        projection={"trade_id": "d" * 32, "entry_price": 1.0},
        request_id="00000000-0000-4000-8000-000000000005",
        issued_at="2026-08-25T10:00:00Z",
        source_id="momentum-wsl-prod",
    )
    return provenance, signed_request(
        action="append_open_v2", sheet_name="mexc-4h-momentum-trailing-stop",
        provenance=provenance, projection={"trade_id": "d" * 32, "entry_price": 1.0},
        source_hmac_secret="test-secret",
    )


class _Response:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def test_missing_endpoint_fails_closed_and_records_no_secret(tmp_path):
    provenance, payload = _payload()
    result = submit_projection_v2(endpoint=None, payload=payload, provenance=provenance, outbox_path=tmp_path / "outbox.jsonl")
    assert not result.ok
    assert result.error_code == "endpoint_not_configured"
    text = (tmp_path / "outbox.jsonl").read_text(encoding="utf-8")
    assert "test-secret" not in text
    assert "signature" not in text


def test_receiver_success_and_rejection_are_terminal_outbox_states(tmp_path):
    provenance, payload = _payload()
    success = submit_projection_v2(
        endpoint="https://example.test/receiver", payload=payload, provenance=provenance, outbox_path=tmp_path / "success.jsonl",
        post=lambda *args, **kwargs: _Response({"ok": True, "row": 7}), sleep=lambda _: None,
    )
    assert success.ok and success.receiver_row == 7

    rejected = submit_projection_v2(
        endpoint="https://example.test/receiver", payload=payload, provenance=provenance, outbox_path=tmp_path / "rejected.jsonl",
        post=lambda *args, **kwargs: _Response({"ok": False, "error": "source_not_allowed"}), sleep=lambda _: None,
    )
    assert not rejected.ok and rejected.error_code == "source_not_allowed"
    rows = [json.loads(line) for line in (tmp_path / "rejected.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["PENDING", "REJECTED"]


def test_transport_failure_is_bounded_and_never_falls_back(tmp_path):
    provenance, payload = _payload()
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("network unavailable")

    result = submit_projection_v2(
        endpoint="https://example.test/receiver", payload=payload, provenance=provenance, outbox_path=tmp_path / "failed.jsonl",
        post=fail, sleep=lambda _: None, attempts=2,
    )
    assert not result.ok and result.status == "TRANSPORT_FAILED"
    assert len(calls) == 2


def test_reconciliation_inventory_is_read_only_and_requires_fixed_action():
    payload = signed_reconciliation_request(
        project_id="mexc-4h-momentum", sheet_name="mexc-4h-momentum-trailing-stop",
        source_id="momentum-wsl-prod", request_id="00000000-0000-4000-8000-000000000006",
        issued_at="2026-08-25T10:01:00Z", source_hmac_secret="test-secret",
    )
    result = read_reconciliation_inventory_v2(
        endpoint="https://example.test/receiver", payload=payload,
        post=lambda *args, **kwargs: _Response({"ok": True, "items": [{"trade_id": "d" * 32, "audit": []}]}),
    )
    assert result.ok and result.items[0]["trade_id"] == "d" * 32
    wrong_action = read_reconciliation_inventory_v2(endpoint="https://example.test/receiver", payload={**payload, "action": "append_open_v2"})
    assert not wrong_action.ok and wrong_action.error_code == "reconciliation_action_invalid"


def test_read_audit_is_read_only_and_requires_fixed_audit_action():
    from trade_alerts.google_ledger_client import read_projection_audit_v2

    provenance, payload = _payload()
    payload = {**payload, "action": "read_audit_v2"}
    result = read_projection_audit_v2(
        endpoint="https://example.test/receiver", payload=payload,
        post=lambda *args, **kwargs: _Response({"ok": True, "audit": [{"payload_digest": provenance.payload_digest}]}),
    )
    assert result.ok
    assert result.audit[0]["payload_digest"] == provenance.payload_digest

    wrong_action = read_projection_audit_v2(endpoint="https://example.test/receiver", payload={**payload, "action": "append_open_v2"})
    assert not wrong_action.ok
    assert wrong_action.error_code == "audit_action_invalid"
