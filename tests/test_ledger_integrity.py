from __future__ import annotations

import pytest

from trade_alerts.ledger_integrity import (
    LedgerIntegrityError,
    ProjectionClassification,
    build_provenance,
    canonical_json,
    comparison_for,
    sha256_digest,
    normalise_projection,
    signed_read_audit_request,
    signed_reconciliation_request,
    signed_request,
    verify_signed_request,
)


LEDGER_EVENT = {
    "event": "trade_open",
    "trade_id": "a" * 32,
    "symbol": "UAI_USDT",
    "entry_price": 0.3404,
    "execution_mode": "LIVE",
}
PROJECTION = {
    "trade_id": "a" * 32,
    "execution_mode": "LIVE",
    "symbol": "UAI_USDT",
    "entry_price": 0.3404,
}
REQUEST_ID = "00000000-0000-4000-8000-000000000001"
ISSUED_AT = "2026-08-25T08:00:00Z"


def _provenance():
    return build_provenance(
        project_id="mexc-4h-momentum",
        trade_id="a" * 32,
        event_type="trade_open",
        ledger_event=LEDGER_EVENT,
        projection=PROJECTION,
        request_id=REQUEST_ID,
        issued_at=ISSUED_AT,
        source_id="momentum-wsl-prod",
    )


def test_canonical_json_and_digest_do_not_depend_on_mapping_order():
    left = {"b": [2, 1], "a": {"y": "z", "x": 1}}
    right = {"a": {"x": 1, "y": "z"}, "b": [2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert sha256_digest(left) == sha256_digest(right)


def test_signed_request_verifies_and_tampering_is_rejected():
    payload = signed_request(
        action="append_open_v2",
        sheet_name="mexc-4h-momentum-trailing-stop",
        provenance=_provenance(),
        projection=PROJECTION,
        source_hmac_secret="test-only-secret",
    )

    assert verify_signed_request(payload, source_hmac_secret="test-only-secret")
    assert payload["projection"]["entry_price"] == "0.3404"
    assert not verify_signed_request(payload, source_hmac_secret="wrong-secret")

    tampered = {**payload, "projection": {**PROJECTION, "entry_price": 999.0}}
    assert not verify_signed_request(tampered, source_hmac_secret="test-only-secret")


def test_signed_reconciliation_request_is_fixed_and_signed():
    payload = signed_reconciliation_request(
        project_id="mexc-4h-momentum",
        sheet_name="mexc-4h-momentum-trailing-stop",
        source_id="momentum-wsl-prod",
        request_id="00000000-0000-4000-8000-000000000003",
        issued_at="2026-08-25T08:02:00Z",
        source_hmac_secret="test-only-secret",
    )
    assert payload["action"] == "read_reconciliation_v2"
    assert payload["query"] == {"kind": "source_projection_inventory_v1"}
    assert verify_signed_request(payload, source_hmac_secret="test-only-secret")
    assert not verify_signed_request({**payload, "query": {"kind": "arbitrary"}}, source_hmac_secret="test-only-secret")


def test_signed_read_audit_request_refreshes_only_request_proof():
    payload = signed_read_audit_request(
        sheet_name="mexc-4h-momentum-trailing-stop",
        provenance=_provenance(),
        projection=PROJECTION,
        request_id="00000000-0000-4000-8000-000000000002",
        issued_at="2026-08-25T08:01:00Z",
        source_hmac_secret="test-only-secret",
    )
    assert payload["action"] == "read_audit_v2"
    assert payload["provenance"]["payload_digest"] == _provenance().payload_digest
    assert payload["request_id"] == "00000000-0000-4000-8000-000000000002"
    assert verify_signed_request(payload, source_hmac_secret="test-only-secret")


def test_invalid_ledger_event_inputs_are_rejected_before_request_building():
    with pytest.raises(LedgerIntegrityError):
        build_provenance(
            project_id="invalid project id",
            trade_id="a" * 32,
            event_type="trade_open",
            ledger_event=LEDGER_EVENT,
            projection=PROJECTION,
            request_id=REQUEST_ID,
            issued_at=ISSUED_AT,
            source_id="momentum-wsl-prod",
        )
    with pytest.raises(LedgerIntegrityError):
        build_provenance(
            project_id="mexc-4h-momentum",
            trade_id="a" * 32,
            event_type="manual_backfill",
            ledger_event=LEDGER_EVENT,
            projection=PROJECTION,
            request_id=REQUEST_ID,
            issued_at=ISSUED_AT,
            source_id="momentum-wsl-prod",
        )


def test_projection_number_normalisation_is_cross_runtime_stable():
    assert normalise_projection({"volume": 15.0, "price": 0.3404}) == {"volume": "15", "price": "0.3404"}


def test_projection_signed_zero_has_one_canonical_digest():
    negative = normalise_projection({"gross_pnl": -0.0, "net_pnl": -0.0})
    positive = normalise_projection({"gross_pnl": 0.0, "net_pnl": 0.0})
    assert negative == positive == {"gross_pnl": "0", "net_pnl": "0"}
    assert sha256_digest(negative) == sha256_digest(positive)


def test_readonly_comparison_classifies_each_prohibited_or_pending_state():
    payload_digest = sha256_digest(normalise_projection(PROJECTION))
    assert comparison_for(trade_id="a" * 32, local_payload_digest=payload_digest, google_payload_digests=[]).classification == ProjectionClassification.PENDING_SYNC
    assert comparison_for(trade_id="a" * 32, local_payload_digest=None, google_payload_digests=[payload_digest]).classification == ProjectionClassification.GOOGLE_NO_LEDGER_SOURCE
    assert comparison_for(trade_id="a" * 32, local_payload_digest=payload_digest, google_payload_digests=["b" * 64]).classification == ProjectionClassification.DIGEST_MISMATCH
    assert comparison_for(trade_id="a" * 32, local_payload_digest=payload_digest, google_payload_digests=[payload_digest, payload_digest]).classification == ProjectionClassification.DUPLICATE_GOOGLE_TRADE_ID
    assert comparison_for(trade_id="a" * 32, local_payload_digest=payload_digest, google_payload_digests=[payload_digest], receiver_rejected=True).classification == ProjectionClassification.SOURCE_REJECTED
    assert comparison_for(trade_id="a" * 32, local_payload_digest=payload_digest, google_payload_digests=[payload_digest]).classification == ProjectionClassification.MATCHED
