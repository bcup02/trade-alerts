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
BAD_TABS = [
    "", " ", "趨勢 策略", "趨勢策略 ", "\n趨勢策略", "趨勢策略\n", "../趨勢策略", "趨/勢", "趨'勢", '趨"勢', "趨\\勢",
    "-趨勢", ".趨勢", "_趨勢", ":趨勢", "趨" * 257, "a" * 257,
    # look-alikes and invisible characters must not pass: they would never equal the name registered in the receiver
    "趨勢策略\u3164", "趨勢策略\uffa0", "趨勢策略\u115f", "\u3164趨勢策略", "趨勢策略\u200b", "趨勢\u200d策略", "趨勢策略\u0301",
    "趨勢策略\u3000", "趨勢策略\u00b2", "趨勢策略\u2160", "趨勢策略\u2460", "趨勢策略１", "趨勢策略Ａ", "Ａ趨勢策略",
    "趨勢策略，", "趨勢策略：", "趨勢策略（", "趨勢策略\x00", "趨勢策略\t", "趨勢策略\ufeff", "ｅd-seykota",
]
EDGE_OK = ["1趨勢策略", "趨勢策略1", "趨勢-策略.v2:a_b", "a" * 256, "趨" * 256, "趨" + "a" * 255, "\u3400趨勢", "趨勢\u9fff"]


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


@pytest.mark.parametrize("name", EDGE_OK)
def test_boundary_names_that_are_plain_ascii_or_ideographs_pass(name):
    assert verify_signed_request(_signed(name), source_hmac_secret="test-secret")


def test_every_previously_valid_ascii_name_is_still_valid():
    """The old ASCII identifier contract (up to 256 characters) is unchanged for tab names."""
    import itertools
    import re

    old = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
    alphabet = "aZ09._:- "
    samples = ["".join(c) for n in (1, 2, 3) for c in itertools.product(alphabet, repeat=n)]
    samples += ["a" * 255, "a" * 256, "a" * 257, "9" + "-" * 255, "ed-seykota", "btc-competition"]
    for s in samples:
        try:
            _signed(s)
            accepted = True
        except LedgerIntegrityError:
            accepted = False
        assert accepted == bool(old.fullmatch(s)), repr(s)


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


@pytest.mark.parametrize("name", ["趨勢策略\u3164", "趨勢策略１", "趨勢策略\u200b", "趨\\勢"])
def test_audit_request_also_refuses_look_alike_and_unsafe_names(name):
    with pytest.raises(LedgerIntegrityError, match="invalid sheet_name"):
        signed_read_audit_request(
            sheet_name=name, provenance=_provenance(), projection={"trade_id": "a" * 32, "entry_price": 1.0},
            request_id="00000000-0000-4000-8000-00000000000b", issued_at="2026-10-09T10:00:00Z",
            source_hmac_secret="test-secret",
        )


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
