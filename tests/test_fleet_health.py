from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trade_alerts.fleet_health import (
    HEALTH_MAX_B64_CHARS,
    HealthTableError,
    build_health_table,
    decode_health_table,
    encode_health_table,
    health_cell_text,
    parse_health_cell,
    signed_health_request,
    validate_health_table,
)
from trade_alerts.ledger_integrity import canonical_json

GOLDEN = Path(__file__).parent / "golden" / "health_request.json"
REQUEST_ID = "00000000-0000-4000-8000-000000000001"


def _reading(target: str = "seykota", axis: str = "ledger", value: str = "RECONCILED", severity: str = "ok") -> dict:
    return {"target": target, "axis": axis, "value": value, "severity": severity, "checked_at": "2026-10-22T04:00:07Z"}


def _table(readings=None) -> dict:
    return build_health_table([_reading()] if readings is None else readings, generated_at="2026-10-22T04:00:10Z", checked_at="2026-10-22T04:00:07Z")


def test_table_is_sorted_and_keeps_only_the_five_fields():
    rows = [dict(_reading("seykota", "ledger"), extra="x"), _reading("momentum", "google"), _reading("momentum", "ledger")]
    table = _table(rows)
    assert [(r["target"], r["axis"]) for r in table["readings"]] == [("momentum", "google"), ("momentum", "ledger"), ("seykota", "ledger")]
    assert all(set(r) == {"target", "axis", "value", "severity", "checked_at"} for r in table["readings"])


@pytest.mark.parametrize("bad", [[], [{"target": "a", "axis": "b", "value": "c", "severity": "ok"}], ["not a mapping"]])
def test_table_refuses_empty_or_incomplete_readings(bad):
    with pytest.raises(HealthTableError):
        _table(bad)


def test_pack_round_trip_and_determinism():
    table = _table([_reading("momentum", "google"), _reading("seykota", "ledger", "DIVERGED", "alert")])
    first, second = encode_health_table(table), encode_health_table(table)
    assert first == second
    assert decode_health_table(first) == table


def test_cap_is_the_receivers_cap_and_is_enforced():
    assert HEALTH_MAX_B64_CHARS == 9000
    noisy = [dict(_reading(f"t{i}", f"a{j}"), value=hashlib.sha256(f"{i}{j}".encode()).hexdigest() * 3) for i in range(20) for j in range(20)]
    with pytest.raises(HealthTableError, match="cap"):
        encode_health_table(_table(noisy))


def test_cell_text_round_trip_and_cut_off_cell_is_refused():
    table = _table()
    text = health_cell_text(encode_health_table(table))
    assert text.startswith("HEALTHv1|") and text.endswith("|HEALTHEND")
    assert parse_health_cell(text) == table
    for damaged in (text[:-20], text[len("HEALTHv1|"):], "HEALTHv1|" + "A" * 40 + "|HEALTHEND"):
        with pytest.raises(HealthTableError):
            parse_health_cell(damaged)


def test_decode_refuses_wrong_schema_and_non_gzip():
    other = base64.b64encode(gzip.compress(json.dumps({"schema": "x", "readings": []}).encode())).decode()
    with pytest.raises(HealthTableError):
        decode_health_table(other)
    with pytest.raises(HealthTableError):
        decode_health_table(base64.b64encode(b"plain").decode())


def test_signed_request_shape_and_signature():
    b64 = encode_health_table(_table())
    request = signed_health_request(source_id="fleet-health-a1", project_id="fleet-health", request_id=REQUEST_ID,
                                    issued_at="2026-10-22T04:00:10Z", b64=b64, generated_at="2026-10-22T04:00:10Z",
                                    source_hmac_secret="s3cret")
    assert request["action"] == "put_health_v1" and request["sheet_name"] == "維運健康"
    assert set(request["health"]) == {"b64", "generated_at"}
    unsigned = {k: v for k, v in request.items() if k != "signature"}
    assert request["signature"] == hmac.new(b"s3cret", canonical_json(unsigned).encode("utf-8"), hashlib.sha256).hexdigest()
    assert "s3cret" not in json.dumps(request)


@pytest.mark.parametrize("override", [
    {"source_id": "bad id"}, {"project_id": ""}, {"request_id": "not-a-uuid"}, {"b64": "has space"},
    {"b64": "A" * (HEALTH_MAX_B64_CHARS + 1)}, {"source_hmac_secret": ""}, {"issued_at": ""}, {"generated_at": ""},
])
def test_signed_request_refuses_bad_inputs(override):
    args = dict(source_id="fleet-health-a1", project_id="fleet-health", request_id=REQUEST_ID, issued_at="2026-10-22T04:00:10Z",
                b64="AAAA", generated_at="2026-10-22T04:00:10Z", source_hmac_secret="s3cret")
    args.update(override)
    with pytest.raises(HealthTableError):
        signed_health_request(**args)


def test_golden_request_is_reproduced_byte_for_byte():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    table = golden["table"]
    assert encode_health_table(table) == golden["request"]["health"]["b64"]
    rebuilt = signed_health_request(source_id="fleet-health-a1", project_id="fleet-health", request_id=REQUEST_ID,
                                    issued_at="2026-10-22T04:00:10Z", b64=encode_health_table(table),
                                    generated_at="2026-10-22T04:00:10Z", source_hmac_secret=golden["secret"])
    assert rebuilt == golden["request"]


GOOD_ARGS = dict(source_id="fleet-health-a1", project_id="fleet-health", request_id=REQUEST_ID, issued_at="2026-10-22T04:00:10Z",
                 b64="AAAA", generated_at="2026-10-22T04:00:10Z", source_hmac_secret="s3cret")


@pytest.mark.parametrize("field", ["issued_at", "generated_at"])
@pytest.mark.parametrize("bad", ["not-a-date", "2026-10-22", "2026-10-22T04:00:10", "2026-10-22 04:00:10Z", "Oct 22 2026 04:00 UTC", "2026-13-40T04:00:10Z"])
def test_signed_request_refuses_times_the_receiver_would_refuse(field, bad):
    with pytest.raises(HealthTableError):
        signed_health_request(**{**GOOD_ARGS, field: bad})


def test_signed_request_has_no_sheet_name_parameter_and_always_uses_the_health_tab():
    with pytest.raises(TypeError):
        signed_health_request(**GOOD_ARGS, sheet_name="trading-tab")  # type: ignore[call-arg]
    assert signed_health_request(**GOOD_ARGS)["sheet_name"] == "維運健康"


def test_signed_request_freshness_window_when_now_is_given():
    issued = datetime(2026, 10, 22, 4, 0, 10, tzinfo=timezone.utc)
    signed_health_request(**GOOD_ARGS, now=issued + timedelta(minutes=5))
    signed_health_request(**GOOD_ARGS, now=issued - timedelta(minutes=5))
    for off in (timedelta(minutes=5, seconds=1), -timedelta(minutes=5, seconds=1), timedelta(hours=1)):
        with pytest.raises(HealthTableError):
            signed_health_request(**GOOD_ARGS, now=issued + off)
    with pytest.raises(HealthTableError):   # generated_at stale even though issued_at is fresh
        signed_health_request(**{**GOOD_ARGS, "generated_at": "2026-10-22T03:00:00Z"}, now=issued)
    with pytest.raises(HealthTableError):
        signed_health_request(**GOOD_ARGS, now=datetime(2026, 10, 22, 4, 0, 10))


def _good() -> dict:
    return _table()


# --- f-62: a reading that could not be read has no time (checked_at is null) ---------------------------------------------

def _with_null_time() -> dict:
    return _table([_reading("momentum", "ledger"), dict(_reading("host", "units", "UNAVAILABLE", "warn"), checked_at=None)])


def test_a_reading_may_have_a_null_time_and_it_survives_pack_and_unpack():
    table = _with_null_time()
    null_row = next(r for r in table["readings"] if r["axis"] == "units")
    assert null_row["checked_at"] is None
    packed = encode_health_table(table)
    assert decode_health_table(packed) == table
    assert parse_health_cell(health_cell_text(packed)) == table
    assert next(r for r in decode_health_table(packed)["readings"] if r["axis"] == "units")["checked_at"] is None


def test_every_reading_may_be_null_but_the_table_times_may_not():
    table = _table([dict(_reading(), checked_at=None)])
    validate_health_table(table)
    for member in ("generated_at", "checked_at"):
        broken = _with_null_time()
        broken[member] = None
        with pytest.raises(HealthTableError):
            validate_health_table(broken)


@pytest.mark.parametrize("bad", ["", 0, 1761105607, "yesterday", "2026-10-22T04:00:07", False, [], {}])
def test_a_null_time_is_the_only_thing_besides_an_iso_time_the_reading_time_accepts(bad):
    table = _with_null_time()
    table["readings"][0]["checked_at"] = bad
    with pytest.raises(HealthTableError):
        validate_health_table(table)


def test_the_reading_time_key_is_still_required_even_when_it_may_be_null():
    table = _with_null_time()
    table["readings"][0].pop("checked_at")
    with pytest.raises(HealthTableError):
        validate_health_table(table)
    with pytest.raises(HealthTableError):
        _table([{k: v for k, v in _reading().items() if k != "checked_at"}])


@pytest.mark.parametrize("field", ["target", "axis", "value", "severity"])
def test_null_is_refused_for_every_other_reading_field(field):
    table = _with_null_time()
    table["readings"][0][field] = None
    with pytest.raises(HealthTableError):
        validate_health_table(table)


def test_the_golden_cell_with_a_null_time_unpacks_in_python_as_it_does_on_the_page():
    golden = json.loads((Path(__file__).parent / "golden" / "health_cell_real.json").read_text(encoding="utf-8"))
    table = parse_health_cell(golden["with_null_time"]["cell"])
    assert any(r["checked_at"] is None for r in table["readings"])
    assert not any(r["checked_at"] is None for r in parse_health_cell(golden["real"]["cell"])["readings"])


@pytest.mark.parametrize("mutate", [
    lambda t: t.pop("generated_at"),
    lambda t: t.pop("checked_at"),
    lambda t: t.update(readings=[]),
    lambda t: t.update(readings="rows"),
    lambda t: t.update(extra="x"),
    lambda t: t.update(generated_at="x"),
    lambda t: t.update(checked_at="2026-10-22T04:00:07"),
    lambda t: t["readings"].append({"target": "a"}),
    lambda t: t["readings"][0].pop("severity"),
    lambda t: t["readings"][0].update(extra="x"),
    lambda t: t["readings"][0].update(value=""),
    lambda t: t["readings"][0].update(value=3),
    lambda t: t["readings"][0].update(checked_at="yesterday"),
])
def test_encode_and_decode_refuse_a_damaged_table_that_keeps_the_schema_name(mutate):
    table = _good()
    mutate(table)
    with pytest.raises(HealthTableError):
        validate_health_table(table)
    with pytest.raises(HealthTableError):
        encode_health_table(table)
    # a damaged table that reached the cell by another route is refused when it is read, too
    packed = base64.b64encode(gzip.compress(canonical_json(table).encode("utf-8"), mtime=0)).decode()
    with pytest.raises(HealthTableError):
        decode_health_table(packed)
    with pytest.raises(HealthTableError):
        parse_health_cell(health_cell_text(packed))


def test_reviewers_two_reproductions_are_refused():
    with pytest.raises(HealthTableError):
        encode_health_table({"schema": "fleet-health-v1", "readings": []})
    with pytest.raises(HealthTableError):
        encode_health_table({"schema": "fleet-health-v1", "generated_at": "x", "checked_at": "x", "readings": [{"target": "a"}]})
