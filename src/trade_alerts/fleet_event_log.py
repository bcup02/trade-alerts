"""Append-only event log for every operator-visible detection in the fleet.

This log notifies nobody.  That is its whole point: the fleet error catalog
found that 25 of 57 surviving error paths gave a human no decision they could
make differently, so the useful record of them is a durable line, not an alert.
Phase 5's repair bot reads this log to judge its own past decisions over a
window of time instead of asking an operator to inspect each detection as it
happens.

One file per strategy, written next to that strategy's ledger under ``audit/``.
Because the file is per-project, an event stores the *bare* condition name the
strategy emits (``PROTECTION_UNVERIFIED``); ``catalog_code`` adds the project
prefix when a reader joins events back to the catalog or aggregates across the
fleet.  The record shape and its locking follow ``projection_outbox``: one
JSON object per line, exclusive ``flock`` while appending, ``fsync`` before the
lock is released, shared lock while reading.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Iterator, Mapping
from uuid import uuid4

FLEET_EVENT_KIND = "fleet_event_v1"
#: fleet-error-catalog/v2 (2026-09-18): R0 log / R1 auto, silent / R2 auto-retry,
#: escalate after N failures / R3 human required.
RISK_TIERS = ("R0", "R1", "R2", "R3")

#: Catalog code prefix per project key.  The project keys are the ones
#: ``ops-notify`` already uses as notification target keys, so an event joins to
#: a notification axis without a second mapping table.  A test asserts that
#: prefix + bare condition name reproduces every ``code`` in the published
#: catalog, so this table cannot drift away from it silently.
PROJECT_CODE_PREFIXES: Mapping[str, str] = {
    "seykota": "SEY",
    "momentum": "MOM",
    "mycrypto": "MYC",
    "btc-competition": "BTC",
    "fleet": "FLEET",
}


class FleetEventLogError(ValueError):
    """A rejected event; the log itself is append-only and never rewritten."""


def utc_now_iso(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def catalog_code(project: str, code: str) -> str:
    """Join a project and a bare condition name into its catalog code."""
    prefix = PROJECT_CODE_PREFIXES.get(project)
    if prefix is None:
        raise FleetEventLogError(f"unknown project {project!r}")
    if not isinstance(code, str) or not code:
        raise FleetEventLogError("condition code is required")
    if "." in code:
        raise FleetEventLogError(f"expected a bare condition name, got catalog code {code!r}")
    return f"{prefix}.{code}"


def _require_project(project: Any) -> str:
    if project not in PROJECT_CODE_PREFIXES:
        raise FleetEventLogError(f"unknown project {project!r}")
    return str(project)


def _require_bare_code(code: Any) -> str:
    if not isinstance(code, str) or not code:
        raise FleetEventLogError("condition code is required")
    if "." in code:
        raise FleetEventLogError(
            f"store the bare condition name, not the catalog code {code!r}; "
            "readers add the project prefix with catalog_code()"
        )
    return code


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise FleetEventLogError(f"{label} must be a mapping")
    return dict(value)


def _require_risk_tier(risk_tier: Any) -> str | None:
    if risk_tier is None:
        return None
    if risk_tier not in RISK_TIERS:
        raise FleetEventLogError(f"unknown risk tier {risk_tier!r}")
    return str(risk_tier)


def _canonical_line(record: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise FleetEventLogError("event is not canonical JSON") from exc


@contextmanager
def exclusive_log_lock(path: str | Path) -> Iterator[None]:
    """Serialise a read-then-append sequence against other writers.

    A sibling ``<name>.lock`` file carries the lock, not the log itself: taking
    an exclusive ``flock`` on the log while ``append_jsonl`` takes a second one
    through its own descriptor would have the caller wait on itself.  Same
    mechanism as ``projection_outbox``, for the same reason -- a strategy bot
    and the repair bot both write these files.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_jsonl(path: str | Path, record: Mapping[str, Any]) -> None:
    """Append one canonical JSON line under an exclusive lock, then fsync."""
    encoded = _canonical_line(record) + "\n"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_jsonl(path: str | Path, *, error: type[ValueError] = FleetEventLogError) -> list[dict[str, Any]]:
    """Read every JSON object in a log, or an empty list if it does not exist.

    A malformed line raises rather than being skipped: this file is evidence,
    and silently dropping part of it would make an audit read as complete when
    it is not.
    """
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise error(f"{target} contains malformed JSON at line {line_number}") from exc
                if not isinstance(value, dict):
                    raise error(f"{target} record at line {line_number} is not an object")
                records.append(value)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return records


def append_fleet_event(
    path: str | Path,
    *,
    project: str,
    code: str,
    summary: str = "",
    risk_tier: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
    measurements: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Record one detection and return the exact stored object.

    ``evidence`` is the stable set of facts that identify *this* occurrence --
    the same split as ``safe_halt_model.build_safe_halt``, and what a request
    fingerprint is derived from.  ``details`` is diagnostic context, and
    ``measurements`` holds the numeric indicators of a condition that is only a
    metric (a single ``reconciliation_delta`` is stored here every time and
    escalates nothing; only an aggregate drift opens a request).

    ``risk_tier`` is recorded when the caller already resolved it from the
    catalog, purely so the log shows what the tier was at the time; this
    function never decides a tier and never notifies.
    """
    record = {
        "kind": FLEET_EVENT_KIND,
        "event_id": event_id or uuid4().hex,
        "recorded_at": recorded_at or utc_now_iso(),
        "project": _require_project(project),
        "code": _require_bare_code(code),
        "summary": summary if isinstance(summary, str) else "",
        "risk_tier": _require_risk_tier(risk_tier),
        "evidence": _require_mapping(evidence, "evidence"),
        "details": _require_mapping(details, "details"),
        "measurements": _require_mapping(measurements, "measurements"),
    }
    append_jsonl(path, record)
    return record


def read_fleet_events(path: str | Path) -> list[dict[str, Any]]:
    """Return every fleet event in the log in write order."""
    return [record for record in read_jsonl(path) if record.get("kind") == FLEET_EVENT_KIND]


PACKAGED_CATALOG_NAME = "fleet-error-catalog-v2.json"


def load_error_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Read a fleet error catalog document -- by default the one shipped inside
    this package, which is the single published copy.

    Since Phase 7b the catalog is package data: a strategy host builds its ops
    export from each condition's ``operator_message`` at runtime, and pinning a
    ``trade-alerts`` tag is what pins the wording it sends.  Nothing in this
    library decides classifications of its own; it only looks them up.
    """
    if path is None:
        raw = resources.files("trade_alerts").joinpath("catalog", PACKAGED_CATALOG_NAME).read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise FleetEventLogError("catalog document is not a fleet error catalog")
    return payload


def catalog_entry(catalog: Mapping[str, Any], project: str, code: str) -> dict[str, Any]:
    """Find one catalog entry by project and bare condition name."""
    wanted = catalog_code(project, code)
    for entry in catalog.get("entries") or []:
        if isinstance(entry, Mapping) and entry.get("code") == wanted:
            return dict(entry)
    raise FleetEventLogError(f"no catalog entry for {wanted}")


def risk_tier_for(catalog: Mapping[str, Any], project: str, code: str) -> str:
    """Return the catalog's risk tier for one condition."""
    tier = catalog_entry(catalog, project, code).get("risk_tier")
    resolved = _require_risk_tier(tier)
    if resolved is None:
        raise FleetEventLogError(f"catalog entry for {catalog_code(project, code)} has no risk tier")
    return resolved
