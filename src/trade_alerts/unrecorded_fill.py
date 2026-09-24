"""Unrecorded exchange fills: detect, attribute, and correct only the certain case (g1).

The ledger-vs-exchange check (``ledger_reconcile.exchange_ledger_compare``)
lists every exchange fill the ledger does not account for in
``evidence.unmatched_exchange_fills`` and turns the verdict ``DIVERGED`` --
and until now nothing took it from there.  2026-09-21 ed-seykota sent one
entry twice under the same clientOrderId, both filled, the ledger recorded
one, and the divergence sat unattended for three days.

This module is the fleet's one handler for that list, run on each strategy's
timer.  The operator's rule (2026-09-25):

* the ledger is corrected automatically **only** when the extra order is
  certainly the strategy's own duplicate send -- the exchange reports the
  same clientOrderId as an order the ledger already recorded -- and the
  exchange fills restate the trade completely.  The correction is appended
  (never an edit) and the operator is told at once (``UNRECORDED_FILL_CORRECTED``,
  R3): a duplicate send is a bug whose root cause must be found;
* every other unrecorded fill -- unknown origin (e.g. an order placed by
  hand in the exchange app), a duplicate whose position is still open, one
  the fills cannot restate, one whose order could not be looked up -- is
  never written: one request, one R3 notice with steps
  (``UNRECORDED_FILL_UNRESOLVED``).  The request is withdrawn automatically
  once the ledger accounts for the order (a human corrected it).

Two ledger shapes:

* ``style="trade"`` (futures: ``trade_open`` / ``trade_close``): the whole
  closed trade is restated from the exchange with
  ``trade_correction.build_trade_correction``;
* ``style="spot"`` (btc-competition: one ``spot_fill`` per fill): the
  duplicate order's own fills are appended as the strategy's ``spot_fill``
  rows by the adapter.

A strategy that cannot tell a duplicate apart (no client order ids,
``client_ids=False``) only ever reports ``UNRESOLVED``.

At most one ledger write per round.  The module never places or cancels an
order: the adapter's exchange calls are read-only lookups.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .error_request_queue import open_error_request, outstanding_error_requests, record_request_outcome
from .fleet_event_log import append_fleet_event, load_error_catalog, risk_tier_for
from .ledger_reconcile import (
    atomic_write,
    is_paper_event,
    norm_symbol_plain,
    parse_iso,
    read_json,
    read_ledger,
    recorded_order_ids,
)
from .ops_export import build_ops_export, write_ops_export
from .trade_correction import TRADE_CORRECTION_EVENT, build_trade_correction

LOGGER = logging.getLogger("trade_alerts.unrecorded_fill")

CODE_CORRECTED = "UNRECORDED_FILL_CORRECTED"
CODE_UNRESOLVED = "UNRECORDED_FILL_UNRESOLVED"

#: Why an unrecorded fill was left for a human.
ORIGIN_UNKNOWN = "ORIGIN_UNKNOWN"          # not a duplicate of any recorded order
NO_CLIENT_IDS = "NO_CLIENT_IDS"            # this strategy cannot tell (no client ids)
POSITION_OPEN = "POSITION_OPEN"            # a duplicate, but its trade is still open
NOT_RESTATABLE = "NOT_RESTATABLE"          # the fills do not restate the trade
LOOKUP_FAILED = "LOOKUP_FAILED"            # the order could not be looked up for too long
WRITE_FAILED = "WRITE_FAILED"              # the correction write failed or could not be verified

#: Recorded orders within this distance of an unrecorded fill are the ones
#: whose client ids are compared with it.  A duplicate send lands within
#: seconds of the original; a generous window costs only a few lookups.
DUPLICATE_WINDOW_MS = 30 * 60 * 1000
#: Unrecorded orders this close to a duplicate's trade (before its first open,
#: after its close) are taken as part of that trade when restating it.
TRADE_SLACK_MS = 10 * 60 * 1000
#: An order that cannot be looked up is retried silently for this long, then
#: reported: a network blip must not page anyone, a lasting one must.
LOOKUP_GRACE_MS = 2 * 60 * 60 * 1000


@dataclass(frozen=True)
class UnrecordedFillAdapter:
    """What one strategy tells the handler.

    ``client_order_id(symbol, order_id)`` returns the exchange's clientOrderId
    for an order (a read-only lookup; ``None`` when it has none).
    ``fetch_fills(symbol, order_ids)`` returns ``reconcile-source/v1`` fill
    rows for exactly those orders.  For ``style="trade"``,
    ``append_trade_correction(fields)`` appends one ``trade_correction`` with
    the strategy's own ledger writer and returns its event id, and
    ``after_trade_correction(fields, event_id)`` queues the Google projection /
    LINE query (best-effort; the ledger already stands).  For
    ``style="spot"``, ``append_spot_fills(symbol, order_id, fills)`` appends
    the order's fills as the strategy's own rows (projection included) and
    returns a dict with at least ``event_ids``.
    """

    project: str
    style: str
    client_ids: bool
    evidence_source: str
    client_order_id: Callable[[str, str], str | None] | None = None
    fetch_fills: Callable[[str, list[str]], list[dict[str, Any]]] | None = None
    append_trade_correction: Callable[[dict[str, Any]], str] | None = None
    after_trade_correction: Callable[[dict[str, Any], str], dict[str, Any]] | None = None
    append_spot_fills: Callable[[str, str, list[dict[str, Any]]], dict[str, Any]] | None = None
    norm_symbol: Callable[[Any], str] = norm_symbol_plain
    is_paper: Callable[[dict[str, Any]], bool] = is_paper_event
    qty_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.style not in ("trade", "spot"):
            raise ValueError("style must be 'trade' or 'spot'")
        if not self.client_ids:
            return
        needed = ["client_order_id", "fetch_fills"]
        needed.append("append_trade_correction" if self.style == "trade" else "append_spot_fills")
        missing = [name for name in needed if getattr(self, name) is None]
        if missing:
            raise ValueError(f"a {self.style} adapter that corrects needs {missing}")

    @property
    def codes(self) -> tuple[str, ...]:
        return (CODE_CORRECTED, CODE_UNRESOLVED) if self.client_ids else (CODE_UNRESOLVED,)


@dataclass(frozen=True)
class UnrecordedFillPaths:
    ledger: str = "audit/trading_ledger.jsonl"
    ledger_status: str = "audit/ledger_status.json"
    fleet_event_log: str = "audit/fleet_event_log.jsonl"
    request_queue: str = "audit/error_requests.jsonl"
    evidence_dir: str = "audit/unrecorded-fill-evidence"
    ops_export: str = "audit/ops_export.json"


def run_unrecorded_fill_round(
    adapter: UnrecordedFillAdapter,
    paths: UnrecordedFillPaths = UnrecordedFillPaths(),
    *,
    catalog: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    refresh_ops_export: bool = True,
) -> dict[str, Any]:
    """One round; returns what it did, for the caller to print.

    Raises before touching anything when the catalog lacks a code this
    adapter can emit.  ``refresh_ops_export=False`` for a caller that
    refreshes the export itself afterwards (the repair timer does).
    """
    catalog = catalog if catalog is not None else load_error_catalog()
    tiers = {code: risk_tier_for(catalog, adapter.project, code) for code in adapter.codes}
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result: dict[str, Any] = {
        "project": adapter.project, "unrecorded_orders": [], "corrected": [], "unresolved": [],
        "awaiting_human": [], "deferred": [], "withdrawn": [], "ops_export_written": None,
    }
    try:
        _Round(adapter, paths, tiers, moment, result).run()
    finally:
        if refresh_ops_export:
            result["ops_export_written"] = _refresh_ops_export(adapter.project, paths, catalog)
    return result


def _refresh_ops_export(project: str, paths: UnrecordedFillPaths, catalog: Mapping[str, Any]) -> bool:
    try:
        write_ops_export(paths.ops_export, build_ops_export(
            paths.fleet_event_log, paths.request_queue, project=project, catalog=catalog,
        ))
    except Exception as exc:  # noqa: BLE001 -- best-effort, same as the repair runner
        LOGGER.warning("ops_export_refresh_failed path=%s error=%s: %s", paths.ops_export, type(exc).__name__, exc)
        return False
    return True


def _event_ms(event: Mapping[str, Any]) -> int | None:
    value = event.get("event_epoch_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    parsed = parse_iso(event.get("event_time") or event.get("ts"))
    return int(parsed.timestamp() * 1000) if parsed else None


def unrecorded_orders(ledger_status: Mapping[str, Any], ledger_events: list[dict[str, Any]],
                      *, norm_symbol: Callable[[Any], str] = norm_symbol_plain) -> list[dict[str, Any]]:
    """The exchange orders behind ``unmatched_exchange_fills`` that the ledger
    still does not account for, oldest first, one entry per order."""
    if (ledger_status or {}).get("value") != "DIVERGED":
        return []
    evidence = ledger_status.get("evidence") or {}
    accounted = recorded_order_ids(ledger_events)
    orders: dict[str, dict[str, Any]] = {}
    for fill in evidence.get("unmatched_exchange_fills") or []:
        oid = str(fill.get("order_id") or "").strip()
        if not oid or oid in accounted:
            continue
        order = orders.setdefault(oid, {
            "order_id": oid, "symbol": fill.get("symbol"), "norm_symbol": norm_symbol(fill.get("symbol")),
            "side": str(fill.get("side") or "").lower() or None, "time_ms": fill.get("time_ms"), "fills": [],
        })
        order["fills"].append(dict(fill))
        if isinstance(fill.get("time_ms"), (int, float)) and (
            order["time_ms"] is None or fill["time_ms"] < order["time_ms"]
        ):
            order["time_ms"] = fill["time_ms"]
    return sorted(orders.values(), key=lambda o: (o["time_ms"] or 0, o["order_id"]))


class _Round:
    def __init__(self, adapter: UnrecordedFillAdapter, paths: UnrecordedFillPaths, tiers: dict[str, str],
                 moment: datetime, result: dict[str, Any]) -> None:
        self.adapter = adapter
        self.project = adapter.project
        self.paths = paths
        self.tiers = tiers
        self.moment_ms = int(moment.timestamp() * 1000)
        self.result = result
        self._client_ids: dict[str, str | None] = {}

    def run(self) -> None:
        ledger_events = read_ledger(self.paths.ledger)
        accounted = recorded_order_ids(ledger_events)
        open_requests = self._withdraw_accounted_requests(accounted)
        orders = unrecorded_orders(read_json(self.paths.ledger_status) or {}, ledger_events,
                                   norm_symbol=self.adapter.norm_symbol)
        self.result["unrecorded_orders"] = [o["order_id"] for o in orders]

        write_attempted = False
        handled: set[str] = set()
        for order in orders:
            oid = order["order_id"]
            if oid in handled:
                continue
            if oid in open_requests:
                self.result["awaiting_human"].append({"order_id": oid, "request_id": open_requests[oid]["request_id"]})
                continue
            outcome = self._handle(order, orders, ledger_events, allow_write=not write_attempted)
            handled.update(outcome.get("order_ids", [oid]))
            write_attempted = write_attempted or outcome.get("wrote", False)

    # -- one unrecorded order ------------------------------------------------ #
    def _handle(self, order: dict[str, Any], orders: list[dict[str, Any]], ledger_events: list[dict[str, Any]],
                *, allow_write: bool) -> dict[str, Any]:
        oid = order["order_id"]
        if not self.adapter.client_ids:
            self._unresolved(order, NO_CLIENT_IDS, "這支策略下單不帶自訂編號，無法判斷是不是自己重複送單，不自動更正。")
            return {}
        try:
            match = self._duplicate_of(order, ledger_events)
        except Exception as exc:  # noqa: BLE001 -- a lookup failure is retried, then reported
            age = self.moment_ms - int(order["time_ms"] or 0)
            if age < LOOKUP_GRACE_MS:
                self.result["deferred"].append({"order_id": oid, "reason": f"{type(exc).__name__}: {exc}"})
                return {}
            self._unresolved(order, LOOKUP_FAILED, f"查不到這張單的自訂編號（已持續 {age // 60000} 分鐘）：{type(exc).__name__}: {exc}")
            return {}
        if match is None:
            self._unresolved(order, ORIGIN_UNKNOWN, "這張單的自訂編號跟帳本已記的任何一張單都不同，來源不明（例如在交易所 App 手動下的單）。")
            return {}
        if not allow_write:
            self.result["deferred"].append({"order_id": oid, "reason": "one ledger write per round"})
            return {}
        if self.adapter.style == "spot":
            return self._correct_spot(order, match)
        return self._correct_trade(order, match, orders, ledger_events)

    def _client_id(self, symbol: str, order_id: str) -> str | None:
        if order_id not in self._client_ids:
            value = self.adapter.client_order_id(symbol, order_id)
            self._client_ids[order_id] = str(value).strip() if value not in (None, "") else None
        return self._client_ids[order_id]

    def _duplicate_of(self, order: dict[str, Any], ledger_events: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The recorded ledger event whose order has the same clientOrderId, or None."""
        mine = self._client_id(str(order["symbol"]), order["order_id"])
        if not mine:
            return None
        when = int(order["time_ms"] or 0)
        for event in ledger_events:
            oid = str(event.get("order_id") or "").strip()
            if not oid or oid == order["order_id"] or self.adapter.is_paper(event):
                continue
            if self.adapter.norm_symbol(event.get("symbol")) != order["norm_symbol"]:
                continue
            at = _event_ms(event)
            if at is None or abs(at - when) > DUPLICATE_WINDOW_MS:
                continue
            if self._client_id(str(order["symbol"]), oid) == mine:
                return {"event": event, "order_id": oid, "client_order_id": mine}
        return None

    # -- corrections --------------------------------------------------------- #
    def _correct_trade(self, order: dict[str, Any], match: dict[str, Any], orders: list[dict[str, Any]],
                       ledger_events: list[dict[str, Any]]) -> dict[str, Any]:
        trade_id = str(match["event"].get("trade_id") or "")
        # Not paper-filtered: the match already came from a real order, and a
        # native-stop close legitimately has no order_id (2026-09-23), which
        # the generic paper test would drop -- making the trade look open.
        trade = [e for e in ledger_events if str(e.get("trade_id") or "") == trade_id]
        opens = [e for e in trade if e.get("event_type") == "trade_open"]
        closes = [e for e in trade if e.get("event_type") == "trade_close"]
        if not trade_id or not opens:
            self._unresolved(order, NOT_RESTATABLE, f"重複送單對應的帳本紀錄沒有 trade_open（trade_id={trade_id!r}）。", match=match)
            return {}
        if not closes:
            self._unresolved(order, POSITION_OPEN, (
                f"這是策略自己重複送單（跟帳本已記的訂單 {match['order_id']} 同一個自訂編號），"
                f"但交易 {trade_id} 還沒平倉：交易所部位比帳本多，要不要減倉由你決定。"), match=match)
            return {}

        start = min(_event_ms(e) or 0 for e in opens) - TRADE_SLACK_MS
        end = max(_event_ms(e) or 0 for e in closes) + TRADE_SLACK_MS
        group = [o for o in orders if o["norm_symbol"] == order["norm_symbol"]
                 and o["time_ms"] is not None and start <= o["time_ms"] <= end]
        group_ids = sorted({o["order_id"] for o in group} | {order["order_id"]})
        recorded = sorted({str(e["order_id"]) for e in [*opens, *closes]
                           if e.get("order_id") is not None and str(e.get("order_id")).strip()})
        entry_side = "buy" if str(opens[0].get("side") or closes[0].get("side") or "long").lower() == "long" else "sell"
        reason_code = "DUPLICATE_ENTRY_UNRECORDED" if order["side"] == entry_side else "UNRECORDED_FILL"
        reason = (f"策略重複送單：訂單 {order['order_id']} 與帳本已記的訂單 {match['order_id']} 用同一個自訂編號 "
                  f"{match['client_order_id']}，帳本漏記；以交易所成交重述整筆交易（一併納入同時段未記的訂單 "
                  f"{', '.join(o for o in group_ids if o != order['order_id']) or '無'}）。")
        try:
            fills = self.adapter.fetch_fills(str(order["symbol"]), sorted(set(recorded) | set(group_ids)))
            fields = build_trade_correction(
                ledger_events, trade_id=trade_id, fills=fills, reason_code=reason_code, reason=reason,
                evidence_source=self.adapter.evidence_source, qty_multiplier=self.adapter.qty_multiplier,
            )
        except Exception as exc:  # noqa: BLE001 -- TradeCorrectionError or a fetch failure: cannot restate
            self._unresolved(order, NOT_RESTATABLE, f"交易所成交無法完整重述交易 {trade_id}：{type(exc).__name__}: {exc}",
                             match=match, order_ids=group_ids)
            return {"order_ids": group_ids}

        evidence = {"order_ids": group_ids, "duplicate_of": match["order_id"], "client_order_id": match["client_order_id"],
                    "trade_id": trade_id, "fills": fills, "correction": fields}
        evidence_path = self._persist_evidence(order["order_id"], evidence)
        if evidence_path is None:
            self.result["deferred"].append({"order_id": order["order_id"], "reason": "could not persist the evidence file"})
            return {"order_ids": group_ids}
        # Re-read immediately before writing: another writer (a human with the
        # manual tool) may have corrected it since this round started.
        if set(group_ids) & recorded_order_ids(read_ledger(self.paths.ledger)):
            self.result["deferred"].append({"order_id": order["order_id"], "reason": "accounted for since the round started"})
            return {"order_ids": group_ids}
        try:
            event_id = self.adapter.append_trade_correction(fields)
            if set(group_ids) - recorded_order_ids(read_ledger(self.paths.ledger)):
                raise RuntimeError("the appended correction does not account for every order")
        except Exception as exc:  # noqa: BLE001 -- a failed or unverifiable write is never retried
            self._unresolved(order, WRITE_FAILED, f"帳本更正寫入失敗或無法確認：{type(exc).__name__}: {exc}",
                             match=match, order_ids=group_ids, extra={"evidence_path": evidence_path})
            return {"order_ids": group_ids, "wrote": True}
        post: dict[str, Any] = {}
        if self.adapter.after_trade_correction is not None:
            try:
                post = dict(self.adapter.after_trade_correction(fields, event_id) or {})
            except Exception as exc:  # noqa: BLE001 -- the ledger stands; the sheet check reports a gap
                post = {"error": f"{type(exc).__name__}: {exc}"}
        previous, corrected = fields["previous"], fields["corrected"]
        notice = "\n".join([
            "策略自己重複送單，帳本漏記的成交已照交易所自動更正（只追加、不改舊紀錄）。",
            f"trade_id: {trade_id}  symbol: {order['symbol']}",
            f"重複的訂單: {order['order_id']}（與帳本已記的 {match['order_id']} 同一個自訂編號 {match['client_order_id']}）",
            f"一併重述的訂單: {', '.join(group_ids)}",
            f"數量 {previous['exit_volume']} → {corrected['exit_volume']}；淨損益 {previous['net_pnl']} → {corrected['net_pnl']}",
            f"帳本更正事件: {event_id}",
        ])
        event = append_fleet_event(
            self.paths.fleet_event_log, project=self.project, code=CODE_CORRECTED, risk_tier=self.tiers[CODE_CORRECTED],
            summary=f"duplicate send {order['order_id']} of {match['order_id']} corrected in trade_id={trade_id}",
            evidence={"order_ids": group_ids, "trade_id": trade_id, "symbol": order["symbol"]},
            details={"correction_event_id": event_id, "duplicate_of": match["order_id"],
                     "client_order_id": match["client_order_id"], "reason_code": reason_code,
                     "evidence_path": evidence_path, "post": post, "notice_text": notice},
            measurements={"previous_net_pnl": previous["net_pnl"], "corrected_net_pnl": corrected["net_pnl"],
                          "previous_exit_volume": previous["exit_volume"], "corrected_exit_volume": corrected["exit_volume"]},
        )
        self.result["corrected"].append({"order_ids": group_ids, "trade_id": trade_id, "event_id": event_id,
                                         "fleet_event_id": event["event_id"], "post": post})
        return {"order_ids": group_ids, "wrote": True}

    def _correct_spot(self, order: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
        oid = order["order_id"]
        try:
            fills = self.adapter.fetch_fills(str(order["symbol"]), [oid])
            if not fills:
                raise RuntimeError("the exchange returned no fills for the order")
        except Exception as exc:  # noqa: BLE001
            self._unresolved(order, NOT_RESTATABLE, f"查不到這張單的成交明細：{type(exc).__name__}: {exc}", match=match)
            return {}
        evidence_path = self._persist_evidence(oid, {"order_ids": [oid], "duplicate_of": match["order_id"],
                                                     "client_order_id": match["client_order_id"], "fills": fills})
        if evidence_path is None:
            self.result["deferred"].append({"order_id": oid, "reason": "could not persist the evidence file"})
            return {}
        if oid in recorded_order_ids(read_ledger(self.paths.ledger)):
            self.result["deferred"].append({"order_id": oid, "reason": "accounted for since the round started"})
            return {}
        try:
            written = dict(self.adapter.append_spot_fills(str(order["symbol"]), oid, fills) or {})
            if oid not in recorded_order_ids(read_ledger(self.paths.ledger)):
                raise RuntimeError("the appended rows do not account for the order")
        except Exception as exc:  # noqa: BLE001
            self._unresolved(order, WRITE_FAILED, f"補記成交寫入失敗或無法確認：{type(exc).__name__}: {exc}",
                             match=match, extra={"evidence_path": evidence_path})
            return {"wrote": True}
        notice = "\n".join([
            "策略自己重複送單，帳本漏記的現貨成交已照交易所自動補記（只追加）。",
            f"symbol: {order['symbol']}  重複的訂單: {oid}（與帳本已記的 {match['order_id']} 同一個自訂編號 {match['client_order_id']}）",
            f"補記事件: {', '.join(map(str, written.get('event_ids') or []))}",
        ])
        event = append_fleet_event(
            self.paths.fleet_event_log, project=self.project, code=CODE_CORRECTED, risk_tier=self.tiers[CODE_CORRECTED],
            summary=f"duplicate send {oid} of {match['order_id']} recorded from exchange fills",
            evidence={"order_ids": [oid], "symbol": order["symbol"]},
            details={"duplicate_of": match["order_id"], "client_order_id": match["client_order_id"],
                     "evidence_path": evidence_path, "written": written, "notice_text": notice},
        )
        self.result["corrected"].append({"order_ids": [oid], "written": written, "fleet_event_id": event["event_id"]})
        return {"wrote": True}

    # -- outcomes ------------------------------------------------------------ #
    def _unresolved(self, order: dict[str, Any], reason_code: str, reason: str, *, match: dict[str, Any] | None = None,
                    order_ids: Iterable[str] | None = None, extra: Mapping[str, Any] | None = None) -> None:
        oid = order["order_id"]
        ids = sorted(set(order_ids or []) | {oid})
        tier = self.tiers[CODE_UNRESOLVED]
        fills = [{k: f.get(k) for k in ("order_id", "side", "quantity", "price", "time_ms")} for f in order["fills"]]
        request = open_error_request(
            self.paths.request_queue, project=self.project, code=CODE_UNRESOLVED, risk_tier=tier,
            summary=reason, evidence={"order_id": oid},
            details={"reason_code": reason_code, "order_ids": ids, "symbol": order["symbol"], "fills": fills,
                     **({"duplicate_of": match["order_id"], "client_order_id": match["client_order_id"]} if match else {}),
                     **dict(extra or {})},
        )
        notice = "\n".join([
            f"帳本漏記交易所成交，沒有自動更正（{reason_code}）。",
            f"symbol: {order['symbol']}  訂單: {', '.join(ids)}",
            *[f"- {f['side']} {f['quantity']} @ {f['price']}（time_ms {f['time_ms']}）" for f in fills],
            f"原因：{reason}",
        ])
        append_fleet_event(
            self.paths.fleet_event_log, project=self.project, code=CODE_UNRESOLVED, risk_tier=tier,
            summary=reason, evidence={"order_id": oid, "symbol": order["symbol"]},
            details={"reason_code": reason_code, "order_ids": ids, "request_id": request["request_id"],
                     **({"duplicate_of": match["order_id"]} if match else {}), **dict(extra or {}),
                     "notice_text": notice},
        )
        self.result["unresolved"].append({"order_id": oid, "order_ids": ids, "reason_code": reason_code,
                                          "request_id": request["request_id"]})

    def _withdraw_accounted_requests(self, accounted: set[str]) -> dict[str, dict[str, Any]]:
        still_open: dict[str, dict[str, Any]] = {}
        for request in outstanding_error_requests(self.paths.request_queue):
            if request.get("project") != self.project or request.get("code") != CODE_UNRESOLVED:
                continue
            oid = str((request.get("evidence") or {}).get("order_id") or "")
            if oid and oid in accounted:
                record_request_outcome(self.paths.request_queue, request_id=request["request_id"], status="WITHDRAWN",
                                       note="the ledger now accounts for this order", details={})
                self.result["withdrawn"].append({"order_id": oid, "request_id": request["request_id"]})
            elif oid:
                # Every order the request covers waits for the human, not just
                # the one it was opened for: one incident, one notice.
                for covered in {oid, *map(str, (request.get("details") or {}).get("order_ids") or [])}:
                    still_open[covered] = request
        return still_open

    def _persist_evidence(self, order_id: str, evidence: dict[str, Any]) -> str | None:
        stamp = datetime.fromtimestamp(self.moment_ms / 1000, timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = Path(self.paths.evidence_dir) / f"{order_id}-{stamp}.json"
        try:
            atomic_write(path, evidence)
        except Exception as exc:  # noqa: BLE001 -- nothing written to the ledger yet
            LOGGER.warning("unrecorded_fill_evidence_write_failed path=%s: %s", path, exc)
            return None
        return str(path)


__all__ = [
    "CODE_CORRECTED",
    "CODE_UNRESOLVED",
    "TRADE_CORRECTION_EVENT",
    "UnrecordedFillAdapter",
    "UnrecordedFillPaths",
    "run_unrecorded_fill_round",
    "unrecorded_orders",
]
