"""Append-only, non-secret provenance outbox for Google ledger projections."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .ledger_integrity import LedgerProvenance

OutboxStatus = Literal["PENDING", "CONFIRMED", "REJECTED", "TRANSPORT_FAILED"]
_ALLOWED_STATUS = frozenset({"PENDING", "CONFIRMED", "REJECTED", "TRANSPORT_FAILED"})


def append_outbox_record(
    path: str | Path,
    *,
    provenance: LedgerProvenance,
    action: str,
    status: OutboxStatus,
    receiver_row: int | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Append one non-secret audit record and return the exact stored object.

    The outbox never stores a request body, signature, URL, source credential,
    or raw Google response. It is intentionally only an auditable local index
    of a ledger event's projection lifecycle.
    """
    if status not in _ALLOWED_STATUS:
        raise ValueError("unsupported provenance outbox status")
    if not isinstance(action, str) or not action:
        raise ValueError("outbox action is required")
    if receiver_row is not None and (not isinstance(receiver_row, int) or receiver_row < 2):
        raise ValueError("invalid receiver row")
    if error_code is not None and (not isinstance(error_code, str) or not error_code):
        raise ValueError("invalid error code")
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": status,
        "action": action,
        "receiver_row": receiver_row,
        "error_code": error_code,
        "provenance": provenance.as_dict(),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record
