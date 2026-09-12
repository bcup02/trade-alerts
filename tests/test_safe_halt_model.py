import json
from pathlib import Path

import pytest

from trade_alerts.safe_halt_model import (
    RESUME_PATHS,
    SAFE_HALT_CLEARED_EVENT,
    SafeHaltModelError,
    active_safe_halt,
    assert_not_already_cleared,
    build_safe_halt,
    check_confirmation,
    cleared_fingerprints,
    is_latched,
    re_assert,
    require_active_safe_halt,
    resume_preview,
    safe_halt_cleared_fields,
    safe_halt_fingerprint,
)

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "catalog" / "fleet-error-catalog-v1.json").read_text(encoding="utf-8"))


def _halt(**overrides):
    payload = {
        "code": "PROTECTION_UNVERIFIED",
        "reason": "交易所存在部位，但沒有可唯一確認的原生保護單",
        "evidence": {"symbol": "BTCUSDT", "side": "long", "quantity": 0.01},
    }
    payload.update(overrides)
    return build_safe_halt(**payload)


def test_build_safe_halt_has_the_unified_shape():
    halt = _halt(since="2026-09-12T10:03:00Z")
    assert halt == {
        "active": True,
        "code": "PROTECTION_UNVERIFIED",
        "reason": "交易所存在部位，但沒有可唯一確認的原生保護單",
        "since": "2026-09-12T10:03:00Z",
        "evidence": {"symbol": "BTCUSDT", "side": "long", "quantity": 0.01},
        "details": {},
    }
    assert "fingerprint" not in halt


def test_a_catalog_code_is_refused_where_a_condition_name_belongs():
    with pytest.raises(SafeHaltModelError, match="without a project prefix"):
        build_safe_halt(code="SEY.PROTECTION_UNVERIFIED", reason="x")


def test_reason_is_required():
    with pytest.raises(SafeHaltModelError, match="reason is required"):
        build_safe_halt(code="PROTECTION_UNVERIFIED", reason="")


def test_non_canonical_evidence_is_rejected_at_write_time():
    with pytest.raises(SafeHaltModelError, match="canonical JSON"):
        build_safe_halt(code="X", reason="y", evidence={"delta": float("nan")})


def test_fingerprint_ignores_when_and_diagnostics_but_follows_evidence():
    base = _halt(since="2026-09-12T10:03:00Z")
    later = _halt(since="2026-09-13T22:00:00Z", details={"retries": 4, "mark_price": 64000.5})
    assert safe_halt_fingerprint(base) == safe_halt_fingerprint(later)

    different_evidence = _halt(evidence={"symbol": "BTCUSDT", "side": "long", "quantity": 0.02})
    assert safe_halt_fingerprint(base) != safe_halt_fingerprint(different_evidence)

    different_reason = _halt(reason="其他原因")
    assert safe_halt_fingerprint(base) != safe_halt_fingerprint(different_reason)


def test_fingerprint_is_twelve_hex_characters():
    token = safe_halt_fingerprint(_halt())
    assert len(token) == 12
    assert all(character in "0123456789abcdef" for character in token)


def test_re_assert_keeps_the_original_clock_only_for_the_same_halt():
    first = _halt(since="2026-09-12T10:03:00Z")
    same = re_assert(first, _halt(since="2026-09-12T18:00:00Z", details={"cycle": 200}))
    assert same["since"] == "2026-09-12T10:03:00Z"

    changed = re_assert(first, _halt(since="2026-09-12T18:00:00Z", evidence={"symbol": "BTCUSDT", "side": "long", "quantity": 0.5}))
    assert changed["since"] == "2026-09-12T18:00:00Z"

    assert re_assert(None, first)["since"] == "2026-09-12T10:03:00Z"
    assert re_assert({"active": False, "since": "2026-01-01T00:00:00Z"}, first)["since"] == "2026-09-12T10:03:00Z"


def test_active_safe_halt_reads_only_a_real_latch():
    assert is_latched({"safe_halt": _halt()})
    assert not is_latched({})
    assert not is_latched({"safe_halt": None})
    assert not is_latched({"safe_halt": {}})
    assert not is_latched({"safe_halt": {"active": False, "code": "X"}})
    # seykota's pre-Phase-4 spelling: a status string, not a latch dict.
    assert not is_latched({"status": "SAFE_HALT"})
    assert active_safe_halt({"safe_halt": "SAFE_HALT"}) is None

    with pytest.raises(SafeHaltModelError, match="not active"):
        require_active_safe_halt({})


def test_cleared_fingerprints_folds_one_strategy_ledger():
    events = [
        {"event_type": "entry_submitted"},
        {"event_type": SAFE_HALT_CLEARED_EVENT, "halt_fingerprint": "abc123abc123"},
        {"event_type": SAFE_HALT_CLEARED_EVENT},
        "not a mapping",
    ]
    assert cleared_fingerprints(events) == frozenset({"abc123abc123"})
    assert_not_already_cleared("def456def456", events)
    with pytest.raises(SafeHaltModelError, match="already cleared"):
        assert_not_already_cleared("abc123abc123", events)


def test_resume_preview_never_touches_state_and_refuses_a_replayed_clear():
    halt = _halt(since="2026-09-12T10:03:00Z")
    preview = resume_preview(halt, [])
    assert preview["state_file_touched"] is False
    assert preview["ledger_event_to_append"] == SAFE_HALT_CLEARED_EVENT
    assert preview["halt_since"] == "2026-09-12T10:03:00Z"
    assert preview["confirmation_token"] == safe_halt_fingerprint(halt)

    cleared = [{"event_type": SAFE_HALT_CLEARED_EVENT, "halt_fingerprint": preview["confirmation_token"]}]
    with pytest.raises(SafeHaltModelError, match="already cleared"):
        resume_preview(halt, cleared)


def test_check_confirmation_rejects_a_stale_or_foreign_token():
    halt = _halt()
    assert check_confirmation(halt, f"  {safe_halt_fingerprint(halt)} ") == safe_halt_fingerprint(halt)
    with pytest.raises(SafeHaltModelError, match="does not match"):
        check_confirmation(halt, "000000000000")
    with pytest.raises(SafeHaltModelError, match="does not match"):
        check_confirmation(halt, None)
    # The token an operator read before the evidence moved is no longer valid.
    moved = _halt(evidence={"symbol": "BTCUSDT", "side": "long", "quantity": 9.0})
    with pytest.raises(SafeHaltModelError, match="does not match"):
        check_confirmation(moved, safe_halt_fingerprint(halt))


def test_cleared_ledger_fields_are_identical_across_strategies():
    halt = _halt(since="2026-09-12T10:03:00Z")
    fields = safe_halt_cleared_fields(halt, method="operator_confirmed_local_resume", cleared_at="2026-09-12T11:00:00Z", exchange_verified=True)
    assert fields == {
        "halt_code": "PROTECTION_UNVERIFIED",
        "halt_reason": halt["reason"],
        "halt_since": "2026-09-12T10:03:00Z",
        "halt_fingerprint": safe_halt_fingerprint(halt),
        "halt_evidence": halt["evidence"],
        "cleared_at": "2026-09-12T11:00:00Z",
        "method": "operator_confirmed_local_resume",
        "reason": "safe_halt cleared (operator_confirmed_local_resume)",
        "exchange_verified": True,
    }
    with pytest.raises(SafeHaltModelError, match="method is required"):
        safe_halt_cleared_fields(halt, method="")


def test_every_catalog_resume_path_is_one_this_model_implements():
    """A catalog entry cannot prescribe a resume path no strategy can offer."""
    unknown = sorted({entry["resume"] for entry in CATALOG["entries"] if entry.get("resume") not in RESUME_PATHS})
    assert unknown == []
