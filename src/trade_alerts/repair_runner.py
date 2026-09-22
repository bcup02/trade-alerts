"""The fleet's one verified-close repair runner (fleet-error-catalog/v2).

A tracked position that closed on the exchange without the strategy writing a
``trade_close`` leaves an orphan ``trade_open`` in the ledger. The exchange is
the authority, so the fix is to write what the exchange says happened. This
module is that repair, run unattended on a timer, for every strategy: each
strategy supplies a ``RepairAdapter`` (how to fetch evidence from its exchange,
how to stage rows in its own ledger format, how to queue its Google projection)
and nothing else. Before v2 momentum and seykota each carried their own copy
of this loop.

One round:

  1. ``<PROJECT>_REPAIR_PAUSED`` true -> no detection, no exchange query, no
     ledger write. ``audit/ops_export.json`` is still refreshed, so a paused
     strategy whose only export writer is this timer is not reported STALE.
  2. Close requests the ledger has overtaken: an open request for a trade
     that now has a ``trade_close`` (someone repaired it by hand) is
     ``WITHDRAWN``.
  3. Map the ``DIVERGED`` verdict in ``audit/ledger_status.json`` to candidate
     ``trade_id`` s (``detect_repair_candidates``) and take them in order:

     * open R3 request for the trade -> leave it alone until a human has
       dealt with it;
     * a write already attempted this round -> defer to the next round (at
       most one ledger write per round; several orphans are repaired one per
       round, in order, rather than refused);
     * exchange still holds the position (``PositionStillOpen``) -> not yet
       time, not a failure;
     * fetch raised anything else, or ``assess_repair`` says ``unmappable``
       -> one failed attempt (R2). The ``escalate_after``-th consecutive one
       opens a request and marks the event ``escalated`` -- the only R2 event
       ops-notify relays. After that the runner keeps retrying silently; a
       later success closes the request ``RESOLVED_AUTO``;
     * ``assess_repair`` says ``halt`` (the ledger already carries part of a
       repair), or the batch write fails -> stop (R3), one request, never
       retried;
     * otherwise write it (R1, no notification): evidence file, rows staged
       through the strategy's own ledger writer, one locked append, Google
       projection queued.

The runner never notifies anyone directly. Strategies keep ``ALERTS_ENABLED``
off; what needs a human is the escalated R2 or R3 event, which
``ops_export`` hands to ops-notify.
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .atomic_ledger_append import append_lines_atomically, stage_lines
from .error_request_queue import open_error_request, outstanding_error_requests, record_request_outcome
from .fleet_event_log import append_fleet_event, load_error_catalog, read_fleet_events, risk_tier_for
from .ledger_reconcile import atomic_write, norm_symbol_plain, read_json, read_ledger
from .ops_export import build_ops_export, write_ops_export
from .verified_close_backfill import (
    HALT,
    UNMAPPABLE,
    VerifiedCloseError,
    append_repair_from_evidence,
    assess_repair,
    build_repair_events,
    detect_repair_candidates,
)

LOGGER = logging.getLogger("trade_alerts.repair_runner")

CODE_AUTO_REPAIRED = "VERIFIED_CLOSE_AUTO_REPAIRED"
CODE_REPAIR_FAILED = "VERIFIED_CLOSE_REPAIR_FAILED"
CODE_REPAIR_BLOCKED = "VERIFIED_CLOSE_REPAIR_BLOCKED"
RUNNER_CODES = (CODE_AUTO_REPAIRED, CODE_REPAIR_FAILED, CODE_REPAIR_BLOCKED)

_TRUE = {"1", "true", "yes", "on"}


class PositionStillOpen(Exception):
    """Raised by an adapter's ``fetch_evidence`` when the exchange still holds
    the position: the close has not happened yet, so there is nothing to
    repair and nothing has failed."""


@dataclass(frozen=True)
class RepairAdapter:
    """What one strategy tells the runner.

    ``fetch_evidence(trade_id)`` returns a schema-1.0 evidence dict built with
    ``verified_close_backfill.build_evidence`` from a read-only exchange query;
    it raises ``PositionStillOpen`` while the exchange still holds the
    position, and anything else it raises counts as a failed attempt.
    ``staging_ledger(path)`` returns the ``append`` of the strategy's own
    ledger writer pointed at ``path``, so staged rows are in exactly the format
    the strategy writes. ``queue_projection(trade_id)`` queues the
    ``trade_close`` row for the Google sheet.
    """

    project: str
    fetch_evidence: Callable[[str], dict[str, Any]]
    staging_ledger: Callable[[Path], Callable[..., str]]
    queue_projection: Callable[[str], Any]
    norm_symbol: Callable[[Any], str] = norm_symbol_plain
    #: Position side assumed for a ``trade_open`` that records none.
    default_position_side: str = "long"


@dataclass(frozen=True)
class RepairPaths:
    """Where one strategy keeps its files; defaults are the fleet's layout,
    relative to the strategy's working directory."""

    ledger: str = "audit/trading_ledger.jsonl"
    ledger_status: str = "audit/ledger_status.json"
    fleet_event_log: str = "audit/fleet_event_log.jsonl"
    request_queue: str = "audit/error_requests.jsonl"
    evidence_dir: str = "audit/verified-close-evidence"
    ops_export: str = "audit/ops_export.json"


def pause_env_name(project: str) -> str:
    """``MOMENTUM_REPAIR_PAUSED``, ``SEYKOTA_REPAIR_PAUSED``, ... -- one name
    per strategy, same behaviour everywhere."""
    return f"{project.upper().replace('-', '_')}_REPAIR_PAUSED"


def repair_paused(project: str, environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(pause_env_name(project), "false")).strip().lower() in _TRUE


def run_repair_round(
    adapter: RepairAdapter,
    paths: RepairPaths = RepairPaths(),
    *,
    paused: bool | None = None,
    catalog: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One repair round; returns what it did, for the caller to print.

    A strategy without all three runner codes in the catalog raises before
    touching anything: an event the catalog cannot place in a tier is an
    event nobody can be told about.
    """
    catalog = catalog if catalog is not None else load_error_catalog()
    tiers = {code: risk_tier_for(catalog, adapter.project, code) for code in RUNNER_CODES}
    escalate_after = int(catalog["risk_tiers"]["R2"]["escalate_after"])
    if paused is None:
        paused = repair_paused(adapter.project, environ)

    result: dict[str, Any] = {
        "project": adapter.project, "paused": paused, "candidates": [], "repaired": [], "failed": [],
        "escalated": [], "blocked": [], "still_open": [], "awaiting_human": [], "deferred": [],
        "closed_requests": [], "ops_export_written": False,
    }
    try:
        if not paused:
            _Round(adapter, paths, tiers, escalate_after, result).run()
    finally:
        result["ops_export_written"] = _refresh_ops_export(adapter.project, paths, catalog)
    return result


def _refresh_ops_export(project: str, paths: RepairPaths, catalog: Mapping[str, Any]) -> bool:
    """Best-effort: ops-notify reports an export that stops refreshing as
    ``STALE``, so a failure here must never break the round."""
    try:
        write_ops_export(paths.ops_export, build_ops_export(
            paths.fleet_event_log, paths.request_queue, project=project, catalog=catalog,
        ))
    except Exception as exc:  # noqa: BLE001 -- see docstring
        LOGGER.warning("ops_export_refresh_failed path=%s error=%s: %s", paths.ops_export, type(exc).__name__, exc)
        return False
    return True


class _Round:
    def __init__(
        self, adapter: RepairAdapter, paths: RepairPaths, tiers: dict[str, str], escalate_after: int,
        result: dict[str, Any],
    ) -> None:
        self.adapter = adapter
        self.project = adapter.project
        self.paths = paths
        self.tiers = tiers
        self.escalate_after = escalate_after
        self.result = result
        self.fleet_events: list[dict[str, Any]] = []

    def run(self) -> None:
        ledger_events = read_ledger(self.paths.ledger)
        self.fleet_events = [
            event for event in read_fleet_events(self.paths.fleet_event_log) if event.get("project") == self.project
        ]
        open_requests = self._close_overtaken_requests(ledger_events)

        candidates = detect_repair_candidates(
            read_json(self.paths.ledger_status) or {}, ledger_events, norm_symbol=self.adapter.norm_symbol,
        )
        self.result["candidates"] = candidates

        write_attempted = False
        for trade_id in candidates:
            request = open_requests.get(trade_id)
            if request is not None and request["code"] == CODE_REPAIR_BLOCKED:
                self.result["awaiting_human"].append({"trade_id": trade_id, "request_id": request["request_id"]})
                continue
            if write_attempted:
                self.result["deferred"].append(trade_id)
                continue
            write_attempted = self._handle(trade_id, ledger_events, request)

    # -- one candidate ------------------------------------------------------ #
    def _handle(
        self, trade_id: str, ledger_events: list[dict[str, Any]], escalated_request: dict[str, Any] | None,
    ) -> bool:
        """Returns whether a ledger write was attempted."""
        identity = {"trade_id": trade_id, "symbol": _symbol_of(ledger_events, trade_id)}
        try:
            evidence = self.adapter.fetch_evidence(trade_id)
        except PositionStillOpen as exc:
            self.result["still_open"].append({"trade_id": trade_id, "reason": str(exc)})
            return False
        except Exception as exc:  # noqa: BLE001 -- any fetch failure is one failed attempt
            self._fail(identity, [f"evidence fetch failed: {type(exc).__name__}: {exc}"], {}, escalated_request)
            return False

        identity = {"incident_id": evidence.get("incident_id"), **identity}
        assessment = assess_repair(
            evidence, ledger_events, default_position_side=self.adapter.default_position_side,
        )
        if assessment["verdict"] == HALT:
            self._block(identity, "the ledger already carries repair records for this trade",
                        {"reasons": assessment["reasons"], "checks": assessment["checks"]}, escalated_request)
            return False
        if assessment["verdict"] == UNMAPPABLE:
            self._fail(identity, assessment["reasons"], {"checks": assessment["checks"]}, escalated_request)
            return False

        self._write(identity, evidence, escalated_request)
        return True

    def _write(self, identity: dict[str, Any], evidence: dict[str, Any], escalated_request: dict[str, Any] | None) -> None:
        trade_id = identity["trade_id"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        evidence_path = Path(self.paths.evidence_dir) / f"{trade_id}-{stamp}.json"
        try:
            atomic_write(evidence_path, evidence)
        except Exception as exc:  # noqa: BLE001 -- nothing written to the ledger yet, so retry next round
            self._fail(identity, [f"could not persist the evidence file: {type(exc).__name__}: {exc}"], {},
                       escalated_request)
            return

        # Stage through the strategy's own ledger writer so every line is in
        # exactly the format it writes, then land the batch in one locked
        # write. The idempotency checks inside append_repair_from_evidence
        # read the REAL ledger; only the writes go to the scratch file.
        try:
            with tempfile.TemporaryDirectory(prefix=f"{self.project}-repair-") as scratch_dir:
                scratch = Path(scratch_dir) / "staged.jsonl"
                staged = append_repair_from_evidence(
                    self.paths.ledger, evidence, ledger_append=self.adapter.staging_ledger(scratch), apply=True,
                )
                lines = stage_lines(scratch)
                if len(lines) != staged["event_count"]:
                    raise VerifiedCloseError(
                        f"staged {len(lines)} lines but the repair has {staged['event_count']} events"
                    )
                appended = append_lines_atomically(self.paths.ledger, lines)
        except Exception as exc:  # noqa: BLE001 -- any failure here must stop, never retry
            self._block(identity, f"ledger write failed or could not be verified: {exc}",
                        {"evidence_path": str(evidence_path)}, escalated_request)
            return

        projection: dict[str, Any] = {}
        try:
            projection["intent_id"] = self.adapter.queue_projection(trade_id)
        except Exception as exc:  # noqa: BLE001 -- the ledger is already right; the sheet check reports the gap
            projection["error"] = f"{type(exc).__name__}: {exc}"

        trade_close = next(fields for event_type, fields in build_repair_events(evidence) if event_type == "trade_close")
        reconciliation = trade_close["reconciliation"]
        measurements = {
            "gross_pnl": trade_close["gross_pnl"],
            "net_pnl": trade_close["net_pnl"],
            "exchange_profit": trade_close["exchange_profit"],
            "reconciliation_delta": trade_close["reconciliation_delta"],
        }
        details: dict[str, Any] = {
            "evidence_path": str(evidence_path), "appended_event_count": appended, "projection": projection,
            "pnl_source": reconciliation.get("pnl_source", "local"),
        }
        if "local_gross_pnl" in reconciliation:
            details["local_gross_pnl"] = reconciliation["local_gross_pnl"]
            details["exchange_pnl_residual"] = reconciliation["exchange_pnl_residual"]
        event = append_fleet_event(
            self.paths.fleet_event_log, project=self.project, code=CODE_AUTO_REPAIRED,
            risk_tier=self.tiers[CODE_AUTO_REPAIRED],
            summary=f"verified close written from exchange evidence for trade_id={trade_id}",
            evidence=identity, details=details, measurements=measurements,
        )
        if escalated_request is not None:
            self._close_request(escalated_request, "RESOLVED_AUTO", "a later automatic retry repaired it",
                                {"event_id": event["event_id"]})
        self.result["repaired"].append({**identity, "appended_event_count": appended, "projection": projection,
                                        "pnl_source": details["pnl_source"]})

    # -- outcomes ----------------------------------------------------------- #
    def _fail(
        self, identity: dict[str, Any], reasons: list[str], extra: dict[str, Any],
        escalated_request: dict[str, Any] | None,
    ) -> None:
        """One failed attempt. Already escalated: retry silently -- the human
        has been told once, and a line every 15 minutes would bury it."""
        trade_id = identity["trade_id"]
        if escalated_request is not None:
            self.result["failed"].append({**identity, "reasons": reasons, "silent": True,
                                          "request_id": escalated_request["request_id"]})
            return

        attempt = _failures_since_last_escalation(self.fleet_events, trade_id) + 1
        tier = self.tiers[CODE_REPAIR_FAILED]
        details: dict[str, Any] = {
            **extra, "reasons": reasons, "attempt": attempt, "escalate_after": self.escalate_after,
            "escalated": False,
        }
        summary = f"verified close for trade_id={trade_id} could not be written (attempt {attempt}): {reasons[0]}"
        if attempt < self.escalate_after:
            append_fleet_event(
                self.paths.fleet_event_log, project=self.project, code=CODE_REPAIR_FAILED, risk_tier=tier,
                summary=summary, evidence=identity, details=details,
            )
            self.result["failed"].append({**identity, "reasons": reasons, "attempt": attempt})
            return

        request = open_error_request(
            self.paths.request_queue, project=self.project, code=CODE_REPAIR_FAILED, risk_tier=tier,
            summary=summary, evidence={"trade_id": trade_id, "symbol": identity["symbol"]},
            details={"reasons": reasons, "attempts": attempt},
        )
        details.update(escalated=True, request_id=request["request_id"],
                       notice_text=_notice_text(identity, reasons, f"已連續 {attempt} 次自動補寫失敗"))
        append_fleet_event(
            self.paths.fleet_event_log, project=self.project, code=CODE_REPAIR_FAILED, risk_tier=tier,
            summary=summary, evidence=identity, details=details,
        )
        self.result["escalated"].append({**identity, "reasons": reasons, "attempt": attempt,
                                         "request_id": request["request_id"]})

    def _block(
        self, identity: dict[str, Any], reason: str, extra: dict[str, Any],
        escalated_request: dict[str, Any] | None,
    ) -> None:
        tier = self.tiers[CODE_REPAIR_BLOCKED]
        request = open_error_request(
            self.paths.request_queue, project=self.project, code=CODE_REPAIR_BLOCKED, risk_tier=tier,
            summary=reason, evidence={"trade_id": identity["trade_id"], "symbol": identity["symbol"]},
            details=extra,
        )
        reasons = [reason, *extra.get("reasons", [])]
        append_fleet_event(
            self.paths.fleet_event_log, project=self.project, code=CODE_REPAIR_BLOCKED, risk_tier=tier,
            summary=reason, evidence=identity,
            details={**extra, "request_id": request["request_id"],
                     "notice_text": _notice_text(identity, reasons, "自動補寫已停手，這筆不會再自動重試")},
        )
        if escalated_request is not None:
            self._close_request(escalated_request, "SUPERSEDED", "the repair stopped; see the R3 request",
                                {"superseded_by": request["request_id"]})
        self.result["blocked"].append({**identity, "reason": reason, "request_id": request["request_id"]})

    # -- requests ----------------------------------------------------------- #
    def _close_overtaken_requests(self, ledger_events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Withdraw requests whose trade now has a ``trade_close``; return the
        rest keyed by trade_id."""
        closed = {
            str(event.get("trade_id")) for event in ledger_events if event.get("event_type") == "trade_close"
        }
        still_open: dict[str, dict[str, Any]] = {}
        for request in outstanding_error_requests(self.paths.request_queue):
            if request.get("project") != self.project or request.get("code") not in (
                CODE_REPAIR_FAILED, CODE_REPAIR_BLOCKED,
            ):
                continue
            trade_id = str((request.get("evidence") or {}).get("trade_id") or "")
            if trade_id in closed:
                self._close_request(request, "WITHDRAWN", "the ledger now has a trade_close for this trade", {})
            elif trade_id:
                still_open[trade_id] = request
        return still_open

    def _close_request(self, request: dict[str, Any], status: str, note: str, details: dict[str, Any]) -> None:
        record_request_outcome(
            self.paths.request_queue, request_id=request["request_id"], status=status, note=note, details=details,
        )
        self.result["closed_requests"].append({
            "request_id": request["request_id"], "code": request["code"],
            "trade_id": (request.get("evidence") or {}).get("trade_id"), "status": status,
        })


def _symbol_of(ledger_events: list[dict[str, Any]], trade_id: str) -> str | None:
    for event in ledger_events:
        if event.get("event_type") == "trade_open" and str(event.get("trade_id")) == trade_id:
            return event.get("symbol")
    return None


def _failures_since_last_escalation(fleet_events: list[dict[str, Any]], trade_id: str) -> int:
    """Failed attempts for this trade after its last escalation. Nothing but
    an escalation resets the count: a round that finds the position still
    open is not a success, and a success ends the candidate altogether."""
    count = 0
    for event in fleet_events:
        if event.get("code") != CODE_REPAIR_FAILED or (event.get("evidence") or {}).get("trade_id") != trade_id:
            continue
        count = 0 if (event.get("details") or {}).get("escalated") is True else count + 1
    return count


def _notice_text(identity: dict[str, Any], reasons: list[str], headline: str) -> str:
    lines = [
        headline,
        f"trade_id: {identity['trade_id']}  symbol: {identity.get('symbol')}",
    ]
    if identity.get("incident_id"):
        lines.append(f"incident_id: {identity['incident_id']}")
    lines.append("原因：")
    lines += [f"- {reason}" for reason in reasons]
    return "\n".join(lines)
