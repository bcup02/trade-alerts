from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
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
