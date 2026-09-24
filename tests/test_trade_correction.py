"""``trade_alerts.trade_correction`` against the real 2026-09-21 incident.

ed-seykota sent one entry twice (same clientOrderId, both filled) and recorded
only the first; the native-stop close then recorded 0.008 of the 0.011 that
really left.  The fixture is the production ledger and the exchange's own
fills (reconcile-source/v1), so the expected figures are the exchange's.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trade_alerts import (
    CORRECTED_FIELDS,
    TRADE_CORRECTION_EVENT,
    TradeCorrectionError,
    apply_trade_corrections,
    build_trade_correction,
    correction_order_ids,
    exchange_ledger_compare,
    fold_ledger_trades,
    norm_symbol_plain,
    recorded_order_ids,
    validate_trade_correction,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "seykota_duplicate_entry_20260921.json").read_text("utf-8")
)
LEDGER = FIXTURE["ledger"]
STATE = FIXTURE["exchange_state"]
TRADE_A = "BTCUSDT-1139592365588"  # 09-18 entry + 09-19 add recorded with estimates
TRADE_B = "BTCUSDT-1142206675339"  # 09-21 duplicate entry
ORDERS_A = {"1139592365588", "1140379790881", "1141997710722"}
ORDERS_B = {"1142206675339", "1142206692162", "1143212109561", "1144042776223"}
NOW = datetime(2026, 9, 24, 5, 30, 30, tzinfo=timezone.utc)


def _fills(order_ids):
    return [f for f in STATE["fills"] if str(f["order_id"]) in order_ids]


def _append(ledger, fields, event_id):
    return [*ledger, {"event_type": TRADE_CORRECTION_EVENT, "event_id": event_id,
                      "event_epoch_ms": 1790200000000, **fields}]


def _build_b(ledger=LEDGER):
    return build_trade_correction(
        ledger, trade_id=TRADE_B, fills=_fills(ORDERS_B), reason_code="DUPLICATE_ENTRY_UNRECORDED",
        reason="2026-09-21 同一 clientOrderId 成交兩張，第二張未入帳", evidence_source="fixture",
    )


def _build_a(ledger=LEDGER):
    return build_trade_correction(
        ledger, trade_id=TRADE_A, fills=_fills(ORDERS_A), reason_code="ESTIMATED_FILL_SUPERSEDED",
        reason="09-19 加碼的價格與手續費是估算值", evidence_source="fixture",
    )


# --------------------------------------------------------------------------- #
# builder
# --------------------------------------------------------------------------- #
def test_duplicate_entry_is_restated_from_the_exchange():
    fields = _build_b()
    c = fields["corrected"]
    assert c["entry_volume"] == pytest.approx(0.011) and c["exit_volume"] == pytest.approx(0.011)
    assert c["entry_price"] == pytest.approx(86097.7727272727)
    assert c["exit_price"] == pytest.approx(84980.3)
    assert c["entry_fee"] == pytest.approx(0.47353775)
    assert c["exit_fee"] == pytest.approx(0.46739165)
    assert c["gross_pnl"] == pytest.approx(-12.2922)  # == the exchange's realizedPnl
    assert c["net_pnl"] == pytest.approx(-13.2331294)
    assert c["exit_order_id"] == "1144042776223"
    assert fields["previous"]["net_pnl"] == pytest.approx(-10.386960205299998)
    assert fields["previous"]["exit_volume"] == pytest.approx(0.008)
    assert fields["previous"]["exit_order_id"] is None
    assert [f["order_id"] for f in fields["added_fills"]] == ["1142206692162", "1144042776223"]
    assert set(fields["exchange_order_ids"]) == ORDERS_B
    assert set(fields["corrected"]) == set(CORRECTED_FIELDS)


def test_estimated_add_is_restated_without_added_fills():
    fields = _build_a()
    c = fields["corrected"]
    assert c["entry_price"] == pytest.approx(81152.15)
    assert c["entry_fee"] == pytest.approx(0.24345645)
    assert c["gross_pnl"] == pytest.approx(21.9459)
    assert c["net_pnl"] == pytest.approx(21.44801416)
    assert c["exit_order_id"] == "1141997710722"
    assert fields["added_fills"] == []


def test_every_recorded_order_must_be_among_the_fills():
    with pytest.raises(TradeCorrectionError, match="missing from the exchange fills"):
        build_trade_correction(
            LEDGER, trade_id=TRADE_B, fills=_fills(ORDERS_B - {"1143212109561"}),
            reason_code="UNRECORDED_FILL", reason="x", evidence_source="fixture",
        )


def test_fills_that_do_not_net_flat_are_refused():
    with pytest.raises(TradeCorrectionError, match="not flat"):
        build_trade_correction(
            LEDGER, trade_id=TRADE_B, fills=_fills(ORDERS_B - {"1142206692162"}),
            reason_code="UNRECORDED_FILL", reason="x", evidence_source="fixture",
        )


def test_a_gross_that_disagrees_with_the_exchange_realized_pnl_is_refused():
    fills = copy.deepcopy(_fills(ORDERS_B))
    next(f for f in fills if str(f["order_id"]) == "1144042776223")["realized_pnl"] = -5.0
    with pytest.raises(TradeCorrectionError, match="realized PnL"):
        build_trade_correction(LEDGER, trade_id=TRADE_B, fills=fills, reason_code="UNRECORDED_FILL",
                               reason="x", evidence_source="fixture")


def test_non_usdt_commission_is_refused():
    fills = copy.deepcopy(_fills(ORDERS_B))
    fills[0]["commission_asset"] = "BNB"
    with pytest.raises(TradeCorrectionError, match="USDT"):
        build_trade_correction(LEDGER, trade_id=TRADE_B, fills=fills, reason_code="UNRECORDED_FILL",
                               reason="x", evidence_source="fixture")


def test_an_open_trade_cannot_be_corrected():
    ledger = [e for e in LEDGER if not (e["trade_id"] == TRADE_B and e["event_type"] != "trade_open")]
    with pytest.raises(TradeCorrectionError, match="not closed"):
        build_trade_correction(ledger, trade_id=TRADE_B, fills=_fills(ORDERS_B),
                               reason_code="UNRECORDED_FILL", reason="x", evidence_source="fixture")


def test_rebuilding_after_the_correction_finds_nothing_to_correct():
    ledger = _append(LEDGER, _build_b(), "corr-b")
    with pytest.raises(TradeCorrectionError, match="nothing to correct"):
        _build_b(ledger)


def test_a_reason_is_required():
    with pytest.raises(TradeCorrectionError, match="reason"):
        build_trade_correction(LEDGER, trade_id=TRADE_B, fills=_fills(ORDERS_B),
                               reason_code="UNRECORDED_FILL", reason=" ", evidence_source="fixture")


# --------------------------------------------------------------------------- #
# consumers
# --------------------------------------------------------------------------- #
def test_apply_replaces_the_close_with_the_corrected_view():
    ledger = _append(LEDGER, _build_b(), "corr-b")
    effective = apply_trade_corrections(ledger)
    close = next(e for e in effective if e["event_type"] == "trade_close" and e["trade_id"] == TRADE_B)
    assert close["net_pnl"] == pytest.approx(-13.2331294)
    assert close["exit_volume"] == pytest.approx(0.011)
    assert close["order_id"] == "1144042776223"
    assert close["corrected_by"] == ["corr-b"]
    # the original event list is untouched (append-only; nothing is edited)
    assert next(e for e in ledger if e["event_type"] == "trade_close" and e["trade_id"] == TRADE_B)["net_pnl"] \
        == pytest.approx(-10.386960205299998)


def test_a_stale_correction_raises_instead_of_applying_partially():
    fields = _build_b()
    ledger = _append(_append(LEDGER, fields, "corr-b"), fields, "corr-b-again")
    with pytest.raises(TradeCorrectionError, match="no longer applies"):
        apply_trade_corrections(ledger)


def test_corrections_chain_on_the_previous_correction():
    first = _build_b()
    ledger = _append(LEDGER, first, "corr-b")
    fills = copy.deepcopy(_fills(ORDERS_B))
    for fill in fills:
        fill["commission"] = fill["commission"] * 2  # a later, genuinely different restatement
        fill["realized_pnl"] = fill.get("realized_pnl")
    second = build_trade_correction(ledger, trade_id=TRADE_B, fills=fills, reason_code="UNRECORDED_FILL",
                                    reason="fee restated", evidence_source="fixture")
    assert second["previous"]["net_pnl"] == pytest.approx(first["corrected"]["net_pnl"])
    close = next(e for e in apply_trade_corrections(_append(ledger, second, "corr-b2"))
                 if e["event_type"] == "trade_close" and e["trade_id"] == TRADE_B)
    assert close["corrected_by"] == ["corr-b", "corr-b2"]


def test_a_correction_without_a_close_raises():
    ledger = [e for e in LEDGER if not (e["trade_id"] == TRADE_B and e["event_type"] == "trade_close")]
    with pytest.raises(TradeCorrectionError, match="no trade_close"):
        apply_trade_corrections(_append(ledger, _build_b(), "corr-b"))


def test_validate_refuses_a_correction_that_would_move_the_position():
    fields = _build_b()
    fields["corrected"]["exit_volume"] = 0.008
    with pytest.raises(TradeCorrectionError, match="differ"):
        validate_trade_correction(fields)


def test_correction_orders_count_as_recorded():
    ledger = _append(LEDGER, _build_b(), "corr-b")
    assert correction_order_ids(ledger) == ORDERS_B
    assert ORDERS_B <= recorded_order_ids(ledger)


def test_the_incident_reconciles_once_both_corrections_are_appended():
    def compare(ledger):
        return exchange_ledger_compare(STATE, ledger, is_paper=lambda e: False,
                                       norm_symbol=norm_symbol_plain, now=NOW)

    before = compare(LEDGER)
    assert before["value"] == "DIVERGED"
    assert {str(f["order_id"]) for f in before["evidence"]["unmatched_exchange_fills"]} \
        == {"1142206692162", "1144042776223"}

    ledger = _append(_append(LEDGER, _build_a(), "corr-a"), _build_b(), "corr-b")
    after = compare(ledger)
    assert after["value"] == "RECONCILED", after
    assert after["evidence"]["position_diffs"] == []


def test_the_fold_carries_the_corrected_close():
    ledger = _append(LEDGER, _build_b(), "corr-b")
    trades = fold_ledger_trades(ledger, norm_symbol=norm_symbol_plain)
    assert trades[TRADE_B]["close_event"]["net_pnl"] == pytest.approx(-13.2331294)
    assert trades[TRADE_B]["closed"] is True


# --------------------------------------------------------------------------- #
# Google projection path (correct_close_v2)
# --------------------------------------------------------------------------- #
from trade_alerts import correction_projection_fields  # noqa: E402
from trade_alerts.ledger_integrity import (  # noqa: E402
    LedgerIntegrityError,
    build_provenance,
    signed_request,
)
from trade_alerts.projection_outbox import ProjectionIntent  # noqa: E402

_REQUEST_ID = "00000000-0000-4000-8000-000000000001"


def _correction_event():
    return {"event_type": TRADE_CORRECTION_EVENT, "event_id": "corr-b", **_build_b()}


def _provenance(event_type, projection):
    return build_provenance(
        project_id="seykota-btcusdt-4h", trade_id=TRADE_B, event_type=event_type,
        ledger_event=_correction_event(), projection=projection, request_id=_REQUEST_ID,
        issued_at="2026-09-24T06:00:00Z", source_id="seykota-prod",
    )


def test_projection_fields_carry_the_corrected_close_and_a_readable_note():
    fields = correction_projection_fields(_correction_event())
    assert fields["net_pnl"] == pytest.approx(-13.2331294)
    assert fields["exit_order_id"] == "1144042776223"
    assert fields["reason_code"] == "DUPLICATE_ENTRY_UNRECORDED"
    assert "帳本更正" in fields["notes"] and "-13.2331294" in fields["notes"]


def test_a_trade_correction_provenance_is_signable_as_correct_close_v2():
    projection = {"trade_id": TRADE_B, **correction_projection_fields(_correction_event()),
                  "corrects_payload_digest": "c" * 64}
    provenance = _provenance("trade_correction", projection)
    payload = signed_request(action="correct_close_v2", sheet_name="ed-seykota", provenance=provenance,
                             projection=projection, source_hmac_secret="test-only")
    assert payload["action"] == "correct_close_v2"
    intent = ProjectionIntent.from_provenance(action="correct_close_v2", provenance=provenance)
    assert intent.event_type == "trade_correction"


def test_an_action_must_match_its_ledger_event_type():
    provenance = _provenance("trade_correction", {"trade_id": TRADE_B})
    with pytest.raises(ValueError, match="does not match"):
        ProjectionIntent.from_provenance(action="update_close_v2", provenance=provenance)
    close_provenance = _provenance("trade_close", {"trade_id": TRADE_B})
    with pytest.raises(ValueError, match="does not match"):
        ProjectionIntent.from_provenance(action="correct_close_v2", provenance=close_provenance)


def test_unknown_event_types_are_still_refused():
    with pytest.raises(LedgerIntegrityError, match="event_type"):
        _provenance("trade_adjustment", {"trade_id": TRADE_B})
