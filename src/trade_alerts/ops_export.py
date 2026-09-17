"""What a strategy's operator should hear about, as one file ops-notify reads.

Strategy hosts do not push these notifications themselves: a strategy's own
env keeps ``ALERTS_ENABLED`` off, and ops-notify owns the maintenance channel.
So each strategy writes this snapshot into its ``audit/`` directory from its
fleet event log and request queue, and ops-notify relays it.

The direction of trust is the same as for the request queue: the strategy's
service account writes the file, while ops-notify and ops-control can only
read it (``audit/`` is group-readable, never group-writable).  Nothing on the
relay side can fabricate an item to send.

The file is a full snapshot rewritten every time, not an append log, so a
reader never has to reconcile partial writes: ``notices`` are the notifying
events of the last ``window_days``, identified by ``event_id`` so the reader
can send each exactly once, and ``open_requests`` is everything still open.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .error_request_queue import outstanding_error_requests
from .fleet_event_log import (
    RISK_TIERS,
    FleetEventLogError,
    catalog_code,
    catalog_entry,
    load_error_catalog,
    read_fleet_events,
    utc_now_iso,
)

OPS_EXPORT_VERSION = "fleet-ops-export/v1"
DEFAULT_WINDOW_DAYS = 7
#: R0 is "log only": the action after detection is fixed, so it never reaches
#: the operator and never appears here.
NOTIFYING_TIERS = tuple(tier for tier in RISK_TIERS if tier != "R0")
_EXPORT_MODE = 0o644

_TIER_HEADERS = {
    "R1": "📋 修復提案（需要你決定）",
    "R2": "✅ 已自動處理（事後通知，不需要動作）",
    "R3": "⚠️ 中風險狀況（逾時會自動處理）",
    "R4": "🔴 需要人工處理",
}


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _entry_or_none(catalog: Mapping[str, Any], project: str, code: str) -> dict[str, Any] | None:
    try:
        return catalog_entry(catalog, project, code)
    except FleetEventLogError:
        return None


def _resolve_tier(event: Mapping[str, Any], entry: Mapping[str, Any] | None) -> str | None:
    """The tier recorded on the event wins -- it is what the strategy decided at
    the time -- and the catalog fills in for an event written without one."""
    recorded = event.get("risk_tier")
    if recorded in RISK_TIERS:
        return str(recorded)
    tier = (entry or {}).get("risk_tier")
    return str(tier) if tier in RISK_TIERS else None


def render_notice_text(event: Mapping[str, Any], entry: Mapping[str, Any] | None, risk_tier: str) -> str:
    """Plain-language message for one event: tier header, catalog title, the
    entry's ``operator_message`` when it has one, then the technical detail the
    strategy attached (``details.notice_text``, else the event summary)."""
    code = str(event.get("code") or "")
    lines = [_TIER_HEADERS.get(risk_tier, risk_tier), str((entry or {}).get("title") or code)]

    message = (entry or {}).get("operator_message")
    if isinstance(message, Mapping):
        lines += ["", "發生什麼事：", str(message["what"]), "", "解決方向：", str(message["direction"]),
                  "", "處理步驟："]
        lines += [f"{number}. {step}" for number, step in enumerate(message["steps"], start=1)]

    details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
    technical = details.get("notice_text")
    if not (isinstance(technical, str) and technical.strip()):
        technical = event.get("summary")
    if isinstance(technical, str) and technical.strip():
        lines += ["", "技術細節：", technical.strip()]
    return "\n".join(lines)


def build_ops_export(
    fleet_event_log: str | Path,
    request_queue: str | Path,
    *,
    project: str,
    catalog: Mapping[str, Any] | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the ``fleet-ops-export/v1`` document for one strategy.

    A malformed event log or request queue raises (see ``read_jsonl``): an
    export that silently left part of the evidence out would read as complete.
    The caller treats the write as best-effort, and ops-notify reports an
    export that stops refreshing as ``STALE``.

    ``open_requests[].handling_started_at`` is always ``null`` in this version;
    Phase 7e fills it in when an operator presses 「開始處理」.  The field is
    already part of v1 so that change needs no new format version.
    """
    if window_days < 1:
        raise ValueError("window_days must be at least 1")
    catalog = catalog if catalog is not None else load_error_catalog()
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = moment - timedelta(days=window_days)

    notices: list[dict[str, Any]] = []
    for event in read_fleet_events(fleet_event_log):
        if event.get("project") != project:
            continue
        recorded = _parse_iso(event.get("recorded_at"))
        # An unparseable timestamp is kept rather than dropped: the reader
        # de-duplicates on event_id, so the cost is one stale line, while
        # dropping it could hide an event nobody was ever told about.
        if recorded is not None and recorded < cutoff:
            continue
        bare_code = str(event.get("code") or "")
        entry = _entry_or_none(catalog, project, bare_code)
        tier = _resolve_tier(event, entry)
        if tier not in NOTIFYING_TIERS:
            continue
        notices.append({
            "event_id": str(event.get("event_id") or ""),
            "recorded_at": event.get("recorded_at"),
            "code": catalog_code(project, bare_code),
            "risk_tier": tier,
            "critical": tier == "R4",
            "text": render_notice_text(event, entry, tier),
        })
    notices.sort(key=lambda notice: (str(notice["recorded_at"] or ""), notice["event_id"]))

    open_requests: list[dict[str, Any]] = []
    for request in outstanding_error_requests(request_queue):
        if request.get("project") != project:
            continue
        bare_code = str(request.get("code") or "")
        entry = _entry_or_none(catalog, project, bare_code)
        message = (entry or {}).get("operator_message")
        message = message if isinstance(message, Mapping) else {}
        open_requests.append({
            "request_id": request.get("request_id"),
            "fingerprint": request.get("fingerprint"),
            "code": catalog_code(project, bare_code),
            "risk_tier": request.get("risk_tier"),
            "opened_at": request.get("opened_at"),
            "summary": request.get("summary") or "",
            "what": message.get("what"),
            "direction": message.get("direction"),
            "steps": list(message.get("steps") or []),
            "handling_started_at": None,
        })

    return {
        "export_version": OPS_EXPORT_VERSION,
        "project": project,
        "generated_at": utc_now_iso(moment),
        "window_days": window_days,
        "notices": notices,
        "open_requests": open_requests,
    }


def write_ops_export(path: str | Path, export: Mapping[str, Any]) -> None:
    """Atomically replace the export file (``0644``: the group-member readers
    are other service accounts)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(export), handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, _EXPORT_MODE)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
