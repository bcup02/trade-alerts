"""Idempotent re-announcement of facts that were written but never announced.

Every notice in this fleet is produced from ``fleet_event_log``, and several
handlers write the durable fact *first* (a ledger correction, an open error
request) and the fleet event *second*.  A process killed between the two leaves
a fact nobody was told about, and the next round sees the fact already in place
and stays silent -- the human never learns that a duplicate send was corrected,
or that an automatic repair gave up.  The helpers here find those facts and
write the missing event, marked ``details.replayed = true``.

Everything is keyed by something the first write already stored (an evidence
file path, a request id), so running it every round is a no-op once the event
exists.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .error_request_queue import outstanding_error_requests
from .fleet_event_log import append_fleet_event, read_fleet_events


def events_for(fleet_events: Iterable[Mapping[str, Any]], project: str, codes: Iterable[str]) -> list[Mapping[str, Any]]:
    wanted = set(codes)
    return [e for e in fleet_events if e.get("project") == project and e.get("code") in wanted]


def announced_request_ids(fleet_events: Iterable[Mapping[str, Any]], project: str, codes: Iterable[str]) -> set[str]:
    """``details.request_id`` of every event that already announced a request."""
    ids: set[str] = set()
    for event in events_for(fleet_events, project, codes):
        details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
        if details.get("request_id"):
            ids.add(str(details["request_id"]))
    return ids


def replay_unannounced_requests(
    *,
    fleet_event_log: str | Path,
    request_queue: str | Path,
    project: str,
    code: str,
    risk_tier: str,
    notice_text: Any,
    extra_details: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Write the fleet event for every open request of ``code`` that has none.

    ``notice_text(request)`` renders the technical text from the request itself
    (its summary and details are all that survived the kill).  ``extra_details``
    is merged into the event (an R2 escalation must carry ``escalated=True`` for
    the exporter to treat it as notifying).  Returns the events written.
    """
    fleet_events = read_fleet_events(fleet_event_log)
    announced = announced_request_ids(fleet_events, project, [code])
    written: list[dict[str, Any]] = []
    for request in outstanding_error_requests(request_queue):
        if request.get("project") != project or request.get("code") != code:
            continue
        request_id = str(request.get("request_id") or "")
        if not request_id or request_id in announced:
            continue
        details = dict(request.get("details") or {})
        details.update(dict(extra_details or {}), request_id=request_id, replayed=True, notice_text=notice_text(request))
        written.append(append_fleet_event(
            fleet_event_log, project=project, code=code, risk_tier=risk_tier,
            summary=str(request.get("summary") or ""), evidence=dict(request.get("evidence") or {}),
            details=details,
        ))
        announced.add(request_id)
    return written


def read_evidence_files(directory: str | Path) -> list[tuple[str, dict[str, Any]]]:
    """``(path, content)`` of every readable JSON evidence file, oldest name first.

    An unreadable file is skipped: evidence files are written atomically, so a
    bad one is not ours, and a replay must never fail a round.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(root.glob("*.json")):
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(content, dict):
            out.append((str(path), content))
    return out


__all__ = [
    "announced_request_ids",
    "events_for",
    "read_evidence_files",
    "replay_unannounced_requests",
]
