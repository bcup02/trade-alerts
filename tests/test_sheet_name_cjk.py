"""f-26b: the tab name of a source is shown to people, so it may be Chinese (趨勢策略 …)."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from trade_alerts.ledger_integrity import (
    LedgerIntegrityError,
    build_provenance,
    canonical_json,
    signed_read_audit_request,
    signed_reconciliation_request,
    signed_request,
    verify_signed_request,
)

CHINESE_TABS = ["趨勢策略", "動能策略", "加密策略", "競賽策略"]
ASCII_TABS = ["ed-seykota", "mexc-4h-momentum-trailing-stop", "my-crypto-bot", "btc-competition"]
BAD_TABS = ["", " ", "趨勢 策略", "趨勢策略 ", "\n趨勢策略", "趨勢策略\n", "../趨勢策略", "趨/勢", "趨'勢", '趨"勢', "-趨勢", ".趨勢", "_趨勢", "趨" * 101]


def _provenance():
    return build_provenance(
        project_id="ed-seykota", trade_id="a" * 32, event_type="trade_open",
        ledger_event={"event_type": "trade_open", "trade_id": "a" * 32},
        projection={"trade_id": "a" * 32, "entry_price": 1.0},
        request_id="00000000-0000-4000-8000-000000000007", issued_at="2026-10-09T10:00:00Z",
        source_id="seykota-wsl-prod",
    )


def _signed(sheet_name: str):
    return signed_request(
        action="append_open_v2", sheet_name=sheet_name, provenance=_provenance(),
        projection={"trade_id": "a" * 32, "entry_price": 1.0}, source_hmac_secret="test-secret",
    )


@pytest.mark.parametrize("name", CHINESE_TABS + ASCII_TABS)
def test_chinese_and_ascii_tab_names_are_accepted_and_the_signature_verifies(name):
    payload = _signed(name)
    assert payload["sheet_name"] == name
    assert verify_signed_request(payload, source_hmac_secret="test-secret")


@pytest.mark.parametrize("name", BAD_TABS)
def test_unsafe_tab_names_are_still_refused(name):
    with pytest.raises(LedgerIntegrityError, match="invalid sheet_name"):
        _signed(name)
    with pytest.raises(LedgerIntegrityError, match="invalid sheet_name"):
        signed_reconciliation_request(
            project_id="ed-seykota", sheet_name=name, source_id="seykota-wsl-prod",
            request_id="00000000-0000-4000-8000-000000000008", issued_at="2026-10-09T10:00:00Z",
            source_hmac_secret="test-secret",
        )


def test_signature_covers_the_chinese_tab_name_as_raw_utf8_not_escaped():
    """The Apps Script receiver rebuilds the text with JSON.stringify, which leaves Chinese unescaped."""
    payload = _signed("趨勢策略")
    unsigned = {k: v for k, v in payload.items() if k != "signature"}
    text = canonical_json(unsigned)
    assert '"sheet_name":"趨勢策略"' in text and "\\u" not in text
    expected = hmac.new(b"test-secret", text.encode("utf-8"), hashlib.sha256).hexdigest()
    assert payload["signature"] == expected
    assert json.loads(text)["sheet_name"] == "趨勢策略"


def test_changing_the_tab_name_changes_the_signature():
    assert _signed("趨勢策略")["signature"] != _signed("ed-seykota")["signature"]


def test_reconciliation_and_audit_requests_accept_chinese_tabs():
    rec = signed_reconciliation_request(
        project_id="ed-seykota", sheet_name="趨勢策略", source_id="seykota-wsl-prod",
        request_id="00000000-0000-4000-8000-000000000009", issued_at="2026-10-09T10:00:00Z",
        source_hmac_secret="test-secret",
    )
    assert rec["sheet_name"] == "趨勢策略" and verify_signed_request(rec, source_hmac_secret="test-secret")
    audit = signed_read_audit_request(
        sheet_name="趨勢策略", provenance=_provenance(), projection={"trade_id": "a" * 32, "entry_price": 1.0},
        request_id="00000000-0000-4000-8000-00000000000a", issued_at="2026-10-09T10:00:00Z",
        source_hmac_secret="test-secret",
    )
    assert audit["sheet_name"] == "趨勢策略" and verify_signed_request(audit, source_hmac_secret="test-secret")
