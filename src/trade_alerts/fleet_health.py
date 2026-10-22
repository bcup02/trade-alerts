"""Pure contract for the fleet health table that rides in one Google cell (f-45).

The A1 ops-notify publisher builds the latest health table (every target x axis
reading), packs it as gzip + base64 and signs a ``put_health_v1`` request; the
receiver writes it to A1 of its own tab as ``HEALTHv1|<b64>|HEALTHEND``; the
rule-register page reads that one cell through the Drive connector and unpacks
it.  This module holds the shared, secret-free parts: packing, unpacking, the
cell text and the signed request.  No HTTP, no filesystem, no clock reads --
the caller passes every time and id in, so the output is deterministic.

The numbers mirror ``apps_script/google_ledger_receiver.gs`` (``HEALTH_*``);
``tests/test_fleet_health.py`` and ``tests/apps_script_put_health_node_test.js``
pin both sides to the same golden request.
"""
from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import hmac
import json
import re
from typing import Any, Iterable, Mapping

from .ledger_integrity import LEDGER_PROJECTION_SCHEMA_VERSION, LedgerIntegrityError, _require_request_id, canonical_json

HEALTH_ACTION = "put_health_v1"
HEALTH_SHEET_NAME = "維運健康"
HEALTH_TABLE_SCHEMA = "fleet-health-v1"
HEALTH_CELL_PREFIX = "HEALTHv1|"
HEALTH_CELL_SUFFIX = "|HEALTHEND"
# Same cap as the receiver: the Drive connector returned a single 9 KB cell whole on 2026-10-20.
HEALTH_MAX_B64_CHARS = 9000

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_READING_FIELDS = ("target", "axis", "value", "severity", "checked_at")


class HealthTableError(LedgerIntegrityError):
    """The health table or request cannot be built or read as specified."""


def build_health_table(readings: Iterable[Mapping[str, Any]], *, generated_at: str, checked_at: str) -> dict[str, Any]:
    """One latest-state table: ``checked_at`` is the poll's own time, ``generated_at`` the moment it was packed.

    Each reading keeps only the five fields the page shows, in a stable order, so the same poll always packs to the
    same bytes.  A reading missing a field is refused rather than padded: a half-empty row would read as healthy.
    """
    rows: list[dict[str, Any]] = []
    for reading in readings:
        if not isinstance(reading, Mapping) or any(field not in reading for field in _READING_FIELDS):
            raise HealthTableError("reading is missing a required field")
        rows.append({field: reading[field] for field in _READING_FIELDS})
    if not rows:
        raise HealthTableError("health table has no readings")
    for name, value in (("generated_at", generated_at), ("checked_at", checked_at)):
        if not isinstance(value, str) or not value:
            raise HealthTableError(f"invalid {name}")
    rows.sort(key=lambda row: (str(row["target"]), str(row["axis"])))
    return {"schema": HEALTH_TABLE_SCHEMA, "generated_at": generated_at, "checked_at": checked_at, "readings": rows}


def encode_health_table(table: Mapping[str, Any]) -> str:
    """gzip (mtime 0, so deterministic) + standard base64 of the canonical table JSON; refuses past the cell cap."""
    if table.get("schema") != HEALTH_TABLE_SCHEMA:
        raise HealthTableError("unknown health table schema")
    raw = canonical_json(table).encode("utf-8")
    packed = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    if len(packed) > HEALTH_MAX_B64_CHARS:
        raise HealthTableError(f"health table is {len(packed)} base64 characters, over the {HEALTH_MAX_B64_CHARS} cap")
    return packed


def decode_health_table(b64: str) -> dict[str, Any]:
    """Inverse of :func:`encode_health_table`; any damage (base64, gzip, JSON, schema) raises ``HealthTableError``."""
    if not isinstance(b64, str) or not _B64_RE.fullmatch(b64):
        raise HealthTableError("health cell is not base64")
    try:
        table = json.loads(gzip.decompress(base64.b64decode(b64, validate=True)).decode("utf-8"))
    except (binascii.Error, OSError, EOFError, ValueError) as exc:
        raise HealthTableError("health cell is not a gzip JSON table") from exc
    if not isinstance(table, dict) or table.get("schema") != HEALTH_TABLE_SCHEMA or not isinstance(table.get("readings"), list):
        raise HealthTableError("health cell holds an unknown table")
    return table


def health_cell_text(b64: str) -> str:
    """The exact text the receiver writes to A1."""
    return f"{HEALTH_CELL_PREFIX}{b64}{HEALTH_CELL_SUFFIX}"


def parse_health_cell(text: str) -> dict[str, Any]:
    """Unpack a cell as the page reads it: markers first, then the table.  A cut-off cell fails on the end marker."""
    if not isinstance(text, str) or not text.startswith(HEALTH_CELL_PREFIX) or not text.endswith(HEALTH_CELL_SUFFIX):
        raise HealthTableError("health cell markers are missing (cell cut off or not written by the publisher)")
    return decode_health_table(text[len(HEALTH_CELL_PREFIX):-len(HEALTH_CELL_SUFFIX)])


def signed_health_request(
    *,
    source_id: str,
    project_id: str,
    request_id: str,
    issued_at: str,
    b64: str,
    generated_at: str,
    source_hmac_secret: str,
    sheet_name: str = HEALTH_SHEET_NAME,
) -> dict[str, Any]:
    """Build the signed ``put_health_v1`` payload; the secret is used in memory only and never returned."""
    for name, value in (("source_id", source_id), ("project_id", project_id)):
        if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
            raise HealthTableError(f"invalid {name}")
    if not isinstance(source_hmac_secret, str) or not source_hmac_secret:
        raise HealthTableError("missing source signing credential")
    if not isinstance(b64, str) or not _B64_RE.fullmatch(b64) or len(b64) > HEALTH_MAX_B64_CHARS:
        raise HealthTableError("invalid health payload")
    try:
        _require_request_id(request_id)
    except LedgerIntegrityError as exc:
        raise HealthTableError("invalid request_id") from exc
    for name, value in (("issued_at", issued_at), ("generated_at", generated_at)):
        if not isinstance(value, str) or not value:
            raise HealthTableError(f"invalid {name}")
    body: dict[str, Any] = {
        "schema_version": LEDGER_PROJECTION_SCHEMA_VERSION,
        "action": HEALTH_ACTION,
        "source_id": source_id,
        "project_id": project_id,
        "sheet_name": sheet_name,
        "request_id": request_id,
        "issued_at": issued_at,
        "health": {"b64": b64, "generated_at": generated_at},
    }
    signature = hmac.new(source_hmac_secret.encode("utf-8"), canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
    return {**body, "signature": signature}
