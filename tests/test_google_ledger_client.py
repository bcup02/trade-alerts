from __future__ import annotations

import json

from trade_alerts.google_ledger_client import deliver_projection_v2, read_reconciliation_inventory_v2, submit_projection_v2
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


def test_pure_delivery_writes_no_legacy_outbox_record(tmp_path):
    _provenance, payload = _payload()
    result = deliver_projection_v2(
        endpoint="https://example.test/receiver", payload=payload,
        post=lambda *args, **kwargs: _Response({"ok": True, "row": 3}), sleep=lambda _: None,
    )
    assert result.ok and result.receiver_row == 3
    assert not list(tmp_path.iterdir())


def test_receiver_success_and_rejection_are_terminal_outbox_states(tmp_path):
    provenance, payload = _payload()
    success = submit_projection_v2(
        endpoint="https://example.test/receiver", payload=payload, provenance=provenance, outbox_path=tmp_path / "success.jsonl",
        post=lambda *args, **kwargs: _Response({"ok": True, "row": 7}), sleep=lambda _: None,
    )
    assert success.ok and success.receiver_row == 7

    rejected = submit_projection_v2(
        endpoint="https://example.test/receiver", payload=payload, provenance=provenance, outbox_path=tmp_path / "rejected.jsonl",
        post=lambda *args, **kwargs: _Response({"ok": False, "error": "provenance_invalid"}), sleep=lambda _: None,
    )
    assert not rejected.ok and rejected.status == "REJECTED" and rejected.error_code == "provenance_invalid"
    rows = [json.loads(line) for line in (tmp_path / "rejected.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["PENDING", "REJECTED"]


def test_receiver_config_errors_stay_retryable_so_the_intent_is_not_burned(tmp_path):
    # A stale/misdeployed receiver or an unregistered source is a config
    # problem the operator can fix -- the SAME intent must survive it, not be
    # marked terminal REJECTED (which would drop it from the durable outbox).
    provenance, payload = _payload()
    for err in ("unauthorized", "signature_invalid", "source_not_allowed",
                "unsupported_action", "request_not_fresh", "sheet_not_found"):
        out = submit_projection_v2(
            endpoint="https://example.test/receiver", payload=payload, provenance=provenance,
            outbox_path=tmp_path / f"{err}.jsonl",
            post=lambda *a, _e=err, **k: _Response({"ok": False, "error": _e}), sleep=lambda _: None, attempts=1,
        )
        assert not out.ok and out.status == "TRANSPORT_FAILED" and out.error_code == err
        rows = [json.loads(line) for line in (tmp_path / f"{err}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [r["status"] for r in rows] == ["PENDING", "TRANSPORT_FAILED"]


def test_sender_rejects_non_projection_action_without_outbox(tmp_path):
    provenance, payload = _payload()
    result = submit_projection_v2(
        endpoint="https://example.test/receiver", payload={**payload, "action": "quarantine_v2"},
        provenance=provenance, outbox_path=tmp_path / "outbox.jsonl",
    )
    assert not result.ok and result.error_code == "action_not_allowed"
    assert not (tmp_path / "outbox.jsonl").exists()


def test_redirect_is_limited_to_https_allowed_hosts(tmp_path):
    provenance, payload = _payload()
    calls = []
    blocked = submit_projection_v2(
        endpoint="https://example.test/receiver", payload=payload, provenance=provenance,
        outbox_path=tmp_path / "blocked.jsonl",
        post=lambda *args, **kwargs: _Response({}, 302, {"Location": "http://example.test/insecure"}),
        get=lambda location, **kwargs: calls.append(location) or _Response({"ok": True, "row": 2}), sleep=lambda _: None, attempts=1,
    )
    assert not blocked.ok and blocked.status == "TRANSPORT_FAILED"
    assert calls == []

    allowed = submit_projection_v2(
        endpoint="https://script.google.com/macros/s/example/exec", payload=payload, provenance=provenance,
        outbox_path=tmp_path / "allowed.jsonl",
        post=lambda *args, **kwargs: _Response({}, 302, {"Location": "https://script.googleusercontent.com/macros/echo"}),
        get=lambda location, **kwargs: calls.append(location) or _Response({"ok": True, "row": 2}), sleep=lambda _: None,
    )
    assert allowed.ok
    assert calls == ["https://script.googleusercontent.com/macros/echo"]


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
