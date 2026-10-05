"""Reusable local-ledger reconciliation primitives.

Every automated-trading project in this fleet keeps an append-only JSONL trade
ledger and reconciles it two ways:

  * **ledger vs exchange** -- does the real trade record match what the exchange
    account actually holds / filled?  (Phase 1.)
  * **ledger vs the shared Google "AI自動程式交易紀錄" sheet** -- does every real
    trade have a matching, agreeing sheet row?  (Phase 3 Part 1.)

The comparison logic was copy-pasted across ``mexc-4h-momentum-trailing-stop``
and ``my-crypto-bot`` (`reconcile_compare.py` / `reconcile_shared.py` /
`google_reconcile.py`).  This module is the single home for it.  Each project
keeps a thin adapter that supplies the handful of genuinely project-specific
knobs:

  * ``is_paper`` -- how to tell a DRY_RUN / paper ledger row from a real one.
    momentum keeps LIVE and DRY_RUN in one file and has no LIVE carve-out;
    my-crypto keeps DRY_RUN in a *separate* file but still filters as a belt,
    and a LIVE ``trade_close`` with an estimated exit price (``order_id=null``)
    is real, not paper -- pass ``is_paper_event(..., live_close_estimate_is_real=True)``.
  * ``norm_symbol`` -- momentum symbols are already plain (``GPS_USDT``);
    my-crypto mixes ``BTC/USDT:USDT`` (ledger / ccxt) with ``BTC_USDT`` (toolkit
    order-deals), so it strips separators.  Ready-made: ``norm_symbol_plain`` /
    ``norm_symbol_ccxt``.
  * ``open_event_types`` -- momentum counts only ``trade_open`` as opening a
    position; my-crypto also treats a ``position_recovered`` (a legacy-state
    backfill) as an open.

Pure stdlib apart from :func:`fetch_sheet_rows` (which uses ``requests``, already
a hard dependency of this package).  No secrets live here; the sheet URL /
secret come from the caller or the environment.  Detection only -- nothing in
here writes a ledger, places an order, or pushes anywhere.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from .trade_correction import apply_trade_corrections, correction_order_ids

log = logging.getLogger("trade_alerts.ledger_reconcile")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: ``schema_version`` of the exchange snapshot the fetchers write.
RECONCILE_SOURCE_SCHEMA = "reconcile-source/v1"

#: ``source`` values written by a DRY_RUN paper path -- never a real fill.
#: Byte-for-byte the set both consumers use today
#: (momentum ``reconcile_shared.DRY_RUN_SOURCES`` / my-crypto ``_DRY_RUN_SOURCES``).
DRY_RUN_SOURCES = frozenset({"dry_run_signal", "dry_run_simulated"})

#: Settlement markers the strategy / a settler append once a missing position's
#: fate is known.  Treated as "this position is closed".
CLOSE_MARKERS = frozenset({"position_reconciled_closed", "position_presumed_closed"})

#: Older-format operator clear of a stale *local* position that never had an
#: exchange order behind it.
STALE_STATE_CLEAR_ACTION = "clear_local_stale_position_without_exchange_order"

#: A~U (21-column) unified schema shared by every project tab -- column letter
#: as a 0-based index into a ``list_by_sheet`` row's ``values``.
SHEET_COLUMN_INDEX = {
    "trade_id": 0, "execution_mode": 1, "symbol": 2, "side": 3, "entry_time": 4,
    "exit_time": 5, "entry_price": 6, "exit_price": 7, "volume": 8, "leverage": 9,
    "entry_fee": 10, "exit_fee": 11, "gross_pnl": 12, "net_pnl": 13,
    "return_on_margin": 14, "source": 15, "entry_order_id": 16, "exit_order_id": 17,
    "stop_plan_order_id": 18, "exit_anomaly": 19, "notes": 20,
}

#: ``execution_mode`` cell values that mark a sheet row as a paper trade -- such
#: a row is never expected to have a matching real ledger trade.
SHEET_PAPER_MODES = frozenset(
    {"DRY_RUN", "DRY_RUN_ONLY", "DRY_RUN_ONLINE", "PAPER", "SMOKE", "SMOKE_TEST"}
)

#: Discrepancy kinds that mean "an operator must act" (``divergence=True``).
SHEET_DIVERGENCE_KINDS = frozenset({
    "SHEET_MISSING_ROW", "SHEET_MISSING_CLOSE", "SHEET_UNEXPECTED_CLOSE",
    "VALUE_MISMATCH", "LEDGER_MISSING_ROW",
})

#: Discrepancy kinds reported for visibility but never flipping the verdict.
SHEET_INFO_KINDS = ("estimate_superseded", "trade_id_mismatch")

_FILL_GRACE_MS = 5 * 60 * 1000
_PUBLISHED_MODE = 0o644


# --------------------------------------------------------------------------- #
# Generic IO / parse helpers
# --------------------------------------------------------------------------- #

def utc_now_iso(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def to_float(value: Any) -> float:
    """Coerce to ``float``; ``0.0`` on anything that will not convert."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_number(value: Any) -> float | None:
    """Coerce a sheet cell / ledger value to ``float``, or ``None`` if it is
    empty or non-numeric (distinct from :func:`to_float`, which returns 0.0)."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_ledger(path: str | Path) -> list[dict[str, Any]]:
    """Parse an append-only JSONL ledger, skipping blank / unparseable /
    non-object lines.  Missing file -> ``[]``."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            out.append(event)
    return out


def atomic_write(path: str | Path, document: dict[str, Any]) -> None:
    """Write ``document`` as pretty sorted JSON to ``path`` atomically, 0644."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, _PUBLISHED_MODE)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def norm_symbol_plain(raw: Any) -> str:
    """Symbols are already plain (``GPS_USDT``) -- just normalise case."""
    return str(raw or "").strip().upper()


def norm_symbol_ccxt(raw: Any) -> str:
    """Collapse ``BTC/USDT:USDT`` (ledger / ccxt positions) and ``BTC_USDT``
    (toolkit order-deals) to the same comparison key by dropping the settlement
    suffix and every non-alphanumeric character."""
    s = str(raw or "").upper()
    if ":" in s:
        s = s.split(":", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", s)


# --------------------------------------------------------------------------- #
# Event classification
# --------------------------------------------------------------------------- #

def is_paper_event(event: dict[str, Any], *, live_close_estimate_is_real: bool = False) -> bool:
    """True if ``event`` is a DRY_RUN / paper ledger row.

    A real fill always carries an ``order_id``; a paper ``trade_open`` /
    ``trade_close`` does not.  With ``live_close_estimate_is_real`` a
    ``trade_close`` tagged ``execution_mode=LIVE`` is treated as real even
    without an ``order_id`` -- the 2026-08-21 my-crypto native-stop incident
    recorded a real close with an *estimated* exit price because the fill could
    not be retrieved at the time; dropping it as paper produced a false
    divergence.
    """
    if str(event.get("source") or "") in DRY_RUN_SOURCES:
        return True
    if event.get("event_type") in ("trade_open", "trade_close") and event.get("order_id") is None:
        if live_close_estimate_is_real and str(event.get("execution_mode") or "").upper() == "LIVE":
            return False
        return True
    return False


def recorded_order_ids(real_events: list[dict[str, Any]]) -> set[str]:
    """Exchange order ids the ledger accounts for: every event's ``order_id``
    plus the ``exchange_order_ids`` of appended ``trade_correction`` events (an
    order the strategy sent but never recorded, restated from the exchange)."""
    ids: set[str] = set()
    for e in real_events:
        oid = e.get("order_id")
        if oid is not None and str(oid).strip():
            ids.add(str(oid))
    return ids | correction_order_ids(real_events)


#: How long after an exchange fill the ledger may first have recorded the
#: adopted position (or the reconciled native-stop close) that fill belongs to.
ADOPTED_FILL_WINDOW_MS = 12 * 60 * 60 * 1000
_ADOPTED_REAL_MODES = frozenset({"LIVE", "DEMO"})

#: The ledger event that records an adopted position (an exchange position the strategy took over).
_ADOPTION_OPEN_TYPE = "position_recovered"

#: Fill ``side`` labels that agree with a ledger event, keyed by (position side,
#: is-entry).  Binance-style fills carry the order side (buy/sell); MEXC futures
#: fills carry the action *and* direction (open_long, close_long, open_short,
#: close_short).  A MEXC label is accepted only for exactly its own action, so
#: ``close_short`` (a buy) never explains the entry of a long.
_ADOPTED_FILL_SIDES: dict[tuple[str, bool], frozenset[str]] = {
    ("long", True): frozenset({"buy", "open_long"}),
    ("long", False): frozenset({"sell", "close_long"}),
    ("short", True): frozenset({"sell", "open_short"}),
    ("short", False): frozenset({"buy", "close_short"}),
}


def _is_boolean(value: Any) -> bool:
    """``True``/``False`` and numpy's ``bool_``: neither is ever a time, a price or a size."""
    return isinstance(value, bool) or type(value).__name__ in ("bool", "bool_")


def _finite_positive(value: Any) -> float | None:
    """A finite number > 0 (numeric strings count as numbers), else ``None``.

    Every comparison that decides "these two figures agree" must be written as a
    *positive* test on a value that went through here: ``abs(a - b) > tol`` is
    False for NaN, so a NaN price or size used to read as "the same" (reviewer
    finding F3 on #117)."""
    if _is_boolean(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _positive_ms(value: Any) -> int | None:
    """An epoch-millisecond timestamp, or ``None`` when there is no usable one.

    Unusable: missing, a bool (``True`` would read as 1 ms), not a number,
    not finite (NaN, +-inf), too large to convert, or below 1 ms (so ``0``,
    negatives and a fraction like ``0.5`` that would truncate to 0).  A usable
    value is a finite number >= 1; a numeric string is accepted as a number.
    ``to_float`` turns every unusable case into ``0.0``, which would make "no
    time" look like the Unix epoch -- and two missing times would then "line up"
    with each other -- so the adopted-fill matching and the unmatched-fill
    filter must both go through this and fail closed (reviewer findings on #117).
    """
    if _is_boolean(value):
        return None
    try:
        ms = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(ms) or ms < 1:
        return None
    try:
        return int(ms)
    except (OverflowError, ValueError):
        return None


def match_fills_to_adopted_events(
    fills: list[dict[str, Any]],
    ledger_events: list[dict[str, Any]],
    *,
    norm_symbol: Callable[[Any], str],
    window_ms: int = ADOPTED_FILL_WINDOW_MS,
) -> dict[int, dict[str, Any]]:
    """Which exchange fills a ledger event that has **no ``order_id``** explains.

    A position the strategy adopted after a restart (``position_recovered``) and
    the close of a native stop it reconciled afterwards (``trade_close``) are
    recorded without the exchange order id, so the order-id comparison cannot
    see that the fills behind them are accounted for (2026-10-03: two demo fills
    stayed ``DIVERGED`` for days although the ledger had both rows).

    A fill is explained only when *everything* lines up: same symbol, the side
    the event implies (entry of a long = buy or MEXC open_long, close of a long = sell or close_long; reversed
    for a short), the same quantity and price, and the fill happened no later
    than the event and at most ``window_ms`` before it.  Each event explains at
    most one fill, so a duplicated send of the same order still leaves its
    second fill unmatched.  Events from dry-run sources or without a LIVE/DEMO
    ``execution_mode`` are never used.  Returns ``{index into fills: info}``.
    """
    candidates: list[dict[str, Any]] = []
    for e in ledger_events:
        if e.get("order_id") is not None and str(e.get("order_id")).strip():
            continue
        if str(e.get("source") or "") in DRY_RUN_SOURCES:
            continue
        if str(e.get("execution_mode") or "").upper() not in _ADOPTED_REAL_MODES:
            continue
        et = e.get("event_type")
        if et == "position_recovered":
            qty, price, entry = _finite_positive(e.get("volume")), _finite_positive(e.get("entry_price")), True
        elif et == "trade_close":
            qty, price, entry = _finite_positive(e.get("exit_volume")), _finite_positive(e.get("exit_price")), False
        else:
            continue
        side = str(e.get("side") or "").lower()
        event_ms = _positive_ms(e.get("event_epoch_ms"))
        if side not in ("long", "short") or qty is None or price is None or event_ms is None:
            continue
        fill_sides = _ADOPTED_FILL_SIDES[(side, entry)]
        candidates.append({
            "event": e, "symbol": norm_symbol(e.get("symbol")), "qty": qty, "price": price,
            "sides": fill_sides, "ms": event_ms,
        })
    candidates.sort(key=lambda c: c["ms"])
    matched: dict[int, dict[str, Any]] = {}
    for c in candidates:
        best: int | None = None
        for i, f in enumerate(fills):
            if i in matched:
                continue
            fill_ms = _positive_ms(f.get("time_ms"))
            if fill_ms is None or not (0 <= c["ms"] - fill_ms <= window_ms):
                continue
            if norm_symbol(f.get("symbol")) != c["symbol"] or str(f.get("side") or "").lower() not in c["sides"]:
                continue
            fill_qty, fill_price = _finite_positive(f.get("quantity")), _finite_positive(f.get("price"))
            if fill_qty is None or fill_price is None:
                continue
            if not abs(fill_qty - c["qty"]) <= 1e-9:
                continue
            if not abs(fill_price - c["price"]) <= max(1e-9, c["price"] * 1e-9):
                continue
            if best is None or fill_ms < (_positive_ms(fills[best].get("time_ms")) or fill_ms):
                best = i
        if best is not None:
            e = c["event"]
            matched[best] = {"event_type": e.get("event_type"), "trade_id": e.get("trade_id"),
                             "event_id": e.get("event_id")}
    return matched


def _paper_only_trade_ids(
    all_events: list[dict[str, Any]], *, is_paper: Callable[[dict[str, Any]], bool]
) -> set[str]:
    """``trade_id``s that have at least one ``trade_open`` and whose
    ``trade_open`` rows are *all* paper -- the position was only ever a DRY_RUN
    paper position.  A ``trade_id`` with no ``trade_open`` at all (e.g. a
    ``position_recovered`` from an exchange sync) is NOT included -- that is a
    real position whose pending marker must still be honoured."""
    by_id: dict[str, list[bool]] = {}
    for e in all_events:
        if e.get("event_type") == "trade_open" and e.get("trade_id"):
            by_id.setdefault(str(e["trade_id"]), []).append(is_paper(e))
    return {tid for tid, flags in by_id.items() if flags and all(flags)}


def unsettled_pending_markers(
    all_events: list[dict[str, Any]], *, is_paper: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    """``position_reconciliation_pending`` markers that are still genuinely open.

    Pass the FULL event list (paper events included) -- rule 4 needs to see
    paper ``trade_open`` rows.  The returned markers are only ever real ones.

    A marker for ``trade_id`` X is settled / not-a-real-reconciliation when ANY:

    1. a later ``position_reconciled_closed`` / ``position_presumed_closed``
       for X -- the settlement markers the strategy / a settler write;
    2. a *real* ``trade_close`` for X -- once the close is recorded (native
       trailing stop, central verified reconciliation, historical orders/deals,
       or a normal exit) the position is closed and its P&L booked.  A paper
       (DRY_RUN) ``trade_close`` does not count;
    3. a ``manual_state_reconciliation`` for X with
       ``action="clear_local_stale_position_without_exchange_order"``;
    4. X is paper-only -- its ``trade_open`` rows are all DRY_RUN; the marker
       leaked from a paper position and there is no real trade to reconcile.
    """
    paper_only = _paper_only_trade_ids(all_events, is_paper=is_paper)
    settled: set[str] = set()
    pending: dict[str, dict[str, Any]] = {}
    for e in all_events:
        tid = str(e.get("trade_id") or "")
        if not tid:
            continue
        et = e.get("event_type")
        if et == "position_reconciliation_pending" and not is_paper(e):
            pending[tid] = {
                "trade_id": tid,
                "symbol": e.get("symbol"),
                "volume": e.get("volume"),
                "event_time": e.get("event_time") or e.get("ts"),
                "reason": e.get("reason"),
            }
        elif et in CLOSE_MARKERS or (et == "trade_close" and not is_paper(e)):
            settled.add(tid)
        elif et == "manual_state_reconciliation" and e.get("action") == STALE_STATE_CLEAR_ACTION:
            settled.add(tid)
    return [v for k, v in pending.items() if k not in settled and k not in paper_only]


# --------------------------------------------------------------------------- #
# Layer 1 -- ledger vs exchange
# --------------------------------------------------------------------------- #

def _id_text(value: Any) -> str | None:
    """A usable identifier as text: a non-empty string or an int (never a bool, list,
    dict, ...), else ``None``.  Nothing unhashable ever reaches a comparison."""
    if _is_boolean(value):
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int):
        return str(value)
    return None


def _adoption_twin_positions(
    real_events: list[dict[str, Any]], *, cutoff_ms: int,
    norm_symbol: Callable[[Any], str], open_event_types: frozenset[str],
) -> set[int]:
    """Indexes of ``position_recovered`` rows that are the second record of an opening
    a ``trade_open`` already records.

    The trend/momentum interrupted-entry adoption writes a ``position_recovered`` *and*
    a ``trade_open`` for one opening; counting both reads the position double (reviewer
    finding F1 on momentum #118).  A recovered row is collapsed into a ``trade_open``
    only when the pair is PROVABLY the same opening -- the same ``trade_id``, the same
    symbol, the same size, a shared link (the same ``recovered_from_attempt_event_id`` or the
    same ``order_id``, both non-empty) and NO contradiction: an identifier that both rows
    carry must agree (finding F3: same attempt but different orders are two orders).  Same ``trade_id`` alone is not enough: an
    add to an adopted trade shares it (finding F1 on #123).  Pairs are one-to-one, only
    rows at or before the snapshot are considered, and anything that cannot be proved
    stays counted (it can only read as a divergence, never hide one)."""
    if _ADOPTION_OPEN_TYPE not in open_event_types:
        return set()

    def usable(e: dict[str, Any]) -> bool:
        return (e.get("event_epoch_ms") or 0) <= cutoff_ms and bool(norm_symbol(e.get("symbol")))

    opens = [(i, e) for i, e in enumerate(real_events)
             if usable(e) and e.get("event_type") in open_event_types and e.get("event_type") != _ADOPTION_OPEN_TYPE]
    used: set[int] = set()
    skip: set[int] = set()
    for i, r in enumerate(real_events):
        if r.get("event_type") != _ADOPTION_OPEN_TYPE or not usable(r):
            continue
        tid, r_vol = _id_text(r.get("trade_id")), _finite_positive(r.get("volume"))
        if tid is None or r_vol is None:
            continue
        r_attempt, r_order = _id_text(r.get("recovered_from_attempt_event_id")), _id_text(r.get("order_id"))
        for j, o in opens:
            if j in used or _id_text(o.get("trade_id")) != tid:
                continue
            if norm_symbol(o.get("symbol")) != norm_symbol(r.get("symbol")):
                continue
            o_vol = _finite_positive(o.get("volume"))
            if o_vol is None or not abs(o_vol - r_vol) <= 1e-9:
                continue
            o_attempt, o_order = _id_text(o.get("recovered_from_attempt_event_id")), _id_text(o.get("order_id"))
            pairs = ((r_attempt, o_attempt), (r_order, o_order))
            if any(a is not None and b is not None and a != b for a, b in pairs):
                continue  # an identifier both rows carry disagrees: two different entries (finding F3)
            if any(a is not None and a == b for a, b in pairs):
                used.add(j)
                skip.add(i)
                break
    return skip


def _ledger_positions(
    real_events: list[dict[str, Any]], *, cutoff_ms: int,
    norm_symbol: Callable[[Any], str], open_event_types: frozenset[str],
) -> dict[str, float]:
    """Net contract quantity per normalised symbol implied by the real ledger,
    walking events in file order.  Only events at or before ``cutoff_ms`` (the
    exchange snapshot time) are counted -- a close recorded *after* the snapshot
    cannot be expected to show in it yet, so it is left for the PENDING path
    rather than read as a divergence."""
    skip = _adoption_twin_positions(
        real_events, cutoff_ms=cutoff_ms, norm_symbol=norm_symbol, open_event_types=open_event_types)
    pos: dict[str, float] = {}
    for i, e in enumerate(real_events):
        if (e.get("event_epoch_ms") or 0) > cutoff_ms:
            continue
        sym = norm_symbol(e.get("symbol"))
        if not sym:
            continue
        et = e.get("event_type")
        if i in skip:
            continue
        if et in open_event_types:
            pos[sym] = pos.get(sym, 0.0) + to_float(e.get("volume"))
        elif et == "trade_close":
            pos[sym] = pos.get(sym, 0.0) - to_float(e.get("exit_volume") or e.get("entry_volume"))
        elif et in CLOSE_MARKERS:
            pos[sym] = 0.0
    return {s: q for s, q in pos.items() if not abs(q) <= 1e-9}  # NaN is kept: it must not read as flat


def exchange_ledger_compare(
    exchange_state: Any,
    ledger_events: list[dict[str, Any]],
    *,
    is_paper: Callable[[dict[str, Any]], bool],
    norm_symbol: Callable[[Any], str],
    scope: str = "real-ledger-vs-exchange",
    open_event_types: frozenset[str] = frozenset({"trade_open"}),
    include_pending_markers: bool = True,
    now: datetime | None = None,
    stale_after_seconds: int = 3600,
) -> dict[str, Any]:
    """Pure verdict function for the ledger-vs-exchange layer.  Returns a
    ``ledger_status.json`` document (``RECONCILED`` / ``PENDING`` / ``DIVERGED``
    / ``UNKNOWN`` + evidence)."""
    now = now or datetime.now(timezone.utc)
    checked_at = utc_now_iso(now)
    base = {"checked_at": checked_at, "scope": scope, "last_reconciled_at": None, "source": None}

    if not isinstance(exchange_state, dict) or exchange_state.get("schema_version") != RECONCILE_SOURCE_SCHEMA:
        return {**base, "value": "UNKNOWN",
                "note": "no valid reconcile-source snapshot; run the fetcher", "evidence": {}}

    fetched_at = exchange_state.get("fetched_at")
    base["source"] = f"{RECONCILE_SOURCE_SCHEMA} @ {fetched_at}"
    fs = exchange_state.get("fetch_status") or {}
    if not fs.get("complete"):
        return {**base, "value": "UNKNOWN",
                "note": f"exchange fetch incomplete: {fs.get('errors')}", "evidence": {}}

    fa = parse_iso(fetched_at)
    if fa is None or (now - fa).total_seconds() > stale_after_seconds:
        return {**base, "value": "UNKNOWN", "note": "reconcile-source snapshot is stale", "evidence": {}}
    fa_ms = int(fa.timestamp() * 1000)

    real = [e for e in ledger_events if not is_paper(e)]
    if not real:
        return {**base, "value": "UNKNOWN", "note": "no real local ledger entries yet", "evidence": {}}

    recorded_ids = recorded_order_ids(real)
    ledger_pos = _ledger_positions(
        real, cutoff_ms=fa_ms, norm_symbol=norm_symbol, open_event_types=open_event_types
    )
    ex_pos: dict[str, float] = {}
    for p in exchange_state.get("positions") or []:
        key = norm_symbol(p.get("symbol"))
        ex_pos[key] = ex_pos.get(key, 0.0) + to_float(p.get("quantity"))

    position_diffs: list[dict[str, Any]] = []
    for sym in sorted(set(ledger_pos) | set(ex_pos)):
        lq = ledger_pos.get(sym, 0.0)
        eq = ex_pos.get(sym, 0.0)
        if not abs(lq - eq) <= 1e-6:  # NaN on either side is a mismatch
            position_diffs.append({"symbol": sym, "ledger_qty": lq, "exchange_qty": eq})

    # A fill whose time cannot be read is kept (never silently dropped): the
    # grace window only skips fills that are *known* to be too recent to be
    # recorded yet.  (NaN / +inf used to fall out of the old raw comparison.)
    not_by_order_id = [
        f for f in exchange_state.get("fills") or []
        if str(f.get("order_id")) not in recorded_ids
        and (_positive_ms(f.get("time_ms")) is None or _positive_ms(f.get("time_ms")) < fa_ms - _FILL_GRACE_MS)
    ]
    # ``real`` (not ``ledger_events``): a row the caller classifies as paper must
    # never explain a real exchange fill.
    explained = match_fills_to_adopted_events(not_by_order_id, real, norm_symbol=norm_symbol)
    unmatched_exchange_fills = [
        {"order_id": f.get("order_id"), "trade_id": f.get("trade_id"), "symbol": f.get("symbol"),
         "time_ms": f.get("time_ms"), "quantity": f.get("quantity"), "price": f.get("price"),
         "side": f.get("side")}
        for i, f in enumerate(not_by_order_id) if i not in explained
    ]
    fills_matched_to_adopted_events = [
        {"order_id": not_by_order_id[i].get("order_id"), "trade_id": not_by_order_id[i].get("trade_id"),
         "ledger_trade_id": info.get("trade_id"), "ledger_event_type": info.get("event_type")}
        for i, info in sorted(explained.items())
    ]

    events_after = sum(1 for e in real if (e.get("event_epoch_ms") or 0) > fa_ms)
    pending_recs = (
        unsettled_pending_markers(ledger_events, is_paper=is_paper)
        if include_pending_markers else []
    )

    evidence: dict[str, Any] = {
        "position_agreement": "mismatch" if position_diffs else "match",
        "position_diffs": position_diffs,
        "unmatched_exchange_fills": unmatched_exchange_fills,
        "ledger_events_after_snapshot": events_after,
    }
    if fills_matched_to_adopted_events:
        evidence["fills_matched_to_adopted_events"] = fills_matched_to_adopted_events
    if include_pending_markers:
        evidence["pending_reconciliations"] = pending_recs
    if exchange_state.get("symbols_queried") is not None:
        evidence["symbols_queried"] = exchange_state.get("symbols_queried")

    if position_diffs or unmatched_exchange_fills:
        parts = []
        if unmatched_exchange_fills:
            parts.append(f"{len(unmatched_exchange_fills)} exchange fill(s) not recorded in the ledger")
        if position_diffs:
            parts.append(f"{len(position_diffs)} symbol position mismatch(es)")
        return {**base, "value": "DIVERGED", "note": "; ".join(parts), "evidence": evidence}

    if events_after or pending_recs:
        return {**base, "value": "PENDING",
                "note": (f"{events_after} ledger event(s) newer than the snapshot; "
                         f"{len(pending_recs)} pending reconciliation(s)"),
                "evidence": evidence}

    return {**base, "value": "RECONCILED", "last_reconciled_at": checked_at,
            "note": "the real ledger agrees with the exchange", "evidence": evidence}


# --------------------------------------------------------------------------- #
# Layer 2 -- ledger vs the shared Google sheet
# --------------------------------------------------------------------------- #

def sheet_cell(values: list[Any], name: str) -> Any:
    idx = SHEET_COLUMN_INDEX[name]
    return values[idx] if idx < len(values) else ""


def _str_id(value: Any) -> str:
    """Normalise an order-id cell / field for comparison ('' means 'no id')."""
    if value is None:
        return ""
    return str(value).strip()


def _event_ms(event: dict[str, Any]) -> int:
    ms = event.get("event_epoch_ms")
    if isinstance(ms, (int, float)) and ms > 0:
        return int(ms)
    for key in ("event_time", "ts", "opened_at", "entry_time", "exit_time", "closed_at"):
        parsed = parse_iso(event.get(key))
        if parsed is not None:
            return int(parsed.timestamp() * 1000)
    return 0


def _is_estimate_close(event: dict[str, Any] | None) -> bool:
    """A ``trade_close`` whose exit is an estimate, not a verified fill.  Kept as
    honest history in the ledger; the sheet is allowed to carry the reconciled
    real values instead."""
    if not event or event.get("event_type") != "trade_close":
        return False
    source = str(event.get("source") or "").lower()
    if "estimate" in source:
        return True
    if event.get("order_id") is None and str(event.get("execution_mode") or "").upper() == "LIVE":
        return True
    return False


def fetch_sheet_rows(
    *, sheet_name: str, url: str | None = None, secret: str | None = None,
    attempts: int = 5, initial_backoff_seconds: float = 2.0, sleep=None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Read a sheet tab via the shared Apps Script Web App's read-only
    ``list_by_sheet`` action (see ``apps_script/google_ledger_receiver.gs``).

    Manual 302 follow + bounded exponential backoff, mirroring each project's
    ``_post_sheets_sync``.  Never raises; returns ``(rows, None)`` on success or
    ``(None, error)``.  ``url`` / ``secret`` default to ``SHEETS_SYNC_URL`` /
    ``SHEETS_SYNC_SECRET`` in the environment.
    """
    sleep = sleep or time.sleep
    url = url if url is not None else os.getenv("SHEETS_SYNC_URL")
    secret = secret if secret is not None else os.getenv("SHEETS_SYNC_SECRET")
    if not url or not secret:
        return None, "SHEETS_SYNC_URL / SHEETS_SYNC_SECRET not configured"

    payload = {"secret": secret, "sheet_name": sheet_name, "action": "list_by_sheet"}
    backoff = initial_backoff_seconds
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=payload, timeout=15, allow_redirects=False)
            if resp.status_code in (301, 302, 303) and resp.headers.get("Location"):
                resp = requests.get(resp.headers["Location"], timeout=15)
            resp.raise_for_status()
            if not resp.text.strip():
                last_error = "empty response body"
            else:
                body = resp.json()
                if not isinstance(body, dict) or not body.get("ok"):
                    return None, (f"receiver error: "
                                  f"{body.get('error') if isinstance(body, dict) else 'non-dict response'}")
                rows = body.get("rows")
                if not isinstance(rows, list):
                    return None, "receiver response has no rows list"
                clean: list[dict[str, Any]] = []
                for entry in rows:
                    if not isinstance(entry, dict):
                        continue
                    clean.append({"row": entry.get("row"), "values": list(entry.get("values") or [])})
                return clean, None
        except Exception as exc:  # noqa: BLE001 - detection tool must not crash the timer
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < attempts:
            log.warning("list_by_sheet attempt %d failed (%s); retrying in %ss", attempt, last_error, backoff)
            sleep(backoff)
            backoff = min(backoff * 2, 16)
    return None, last_error


def fold_ledger_trades(
    real_events: list[dict[str, Any]],
    *,
    norm_symbol: Callable[[Any], str],
    open_event_types: frozenset[str] = frozenset({"trade_open"}),
    close_markers: frozenset[str] = CLOSE_MARKERS,
) -> dict[str, dict[str, Any]]:
    """Fold the real ledger into one record per ``trade_id``.

    ``opened`` <- an event in ``open_event_types``.  ``closed`` <- a real
    ``trade_close`` OR a ``close_markers`` settlement marker (some projects
    record a marker alongside, or instead of, a ``trade_close``).
    ``close_event`` is only ever a real ``trade_close`` -- it can be ``None`` on
    a marker-only close, and callers must guard for that.

    A ``trade_id`` seen ONLY via peripheral events (``order_attempt`` /
    ``order_result`` / ``fill`` / ``position_reconciliation_pending`` / ...) --
    with its real open/close filtered out as paper -- is NOT a real position and
    is dropped (stops DRY_RUN ``order_attempt`` leak-through appearing as phantom
    ``SHEET_MISSING_ROW`` divergences).

    Appended ``trade_correction`` events are applied first (see
    :mod:`trade_alerts.trade_correction`): ``close_event`` is the effective,
    corrected close.  A correction that no longer applies raises
    ``TradeCorrectionError`` rather than being silently skipped.
    """
    trades: dict[str, dict[str, Any]] = {}
    for event in apply_trade_corrections(real_events):
        tid = event.get("trade_id")
        if not isinstance(tid, str) or not tid:
            continue
        rec = trades.setdefault(tid, {
            "trade_id": tid, "symbol": None, "opened": False, "closed": False,
            "open_event": None, "close_event": None, "opened_ms": 0, "closed_ms": 0,
        })
        if rec["symbol"] is None and event.get("symbol"):
            rec["symbol"] = norm_symbol(event.get("symbol"))
        et = event.get("event_type")
        if et in open_event_types and not rec["opened"]:
            rec["opened"] = True
            rec["open_event"] = event
            rec["opened_ms"] = _event_ms(event)
        elif et == "trade_close" and rec["close_event"] is None:
            # append-only: first trade_close wins, later duplicates are ignored
            rec["closed"] = True
            rec["close_event"] = event
            rec["closed_ms"] = _event_ms(event)
        elif et in close_markers and not rec["closed"]:
            rec["closed"] = True
            rec["closed_ms"] = _event_ms(event)
    return {tid: rec for tid, rec in trades.items() if rec["opened"] or rec["closed"]}


def _row_is_closed(values: list[Any]) -> bool:
    return any(str(sheet_cell(values, name)).strip() for name in ("exit_time", "exit_price", "net_pnl"))


def _row_in_scope(values: list[Any]) -> bool:
    mode = str(sheet_cell(values, "execution_mode")).strip().upper()
    return mode not in SHEET_PAPER_MODES


def _value_mismatch(close_event: dict[str, Any], values: list[Any], *,
                    price_tol_pct: float, pnl_tol: float) -> dict[str, Any] | None:
    """Compare the exit-side numbers of a closed ledger trade to its sheet row."""
    diffs: dict[str, Any] = {}

    l_exit = to_number(close_event.get("exit_price"))
    s_exit = to_number(sheet_cell(values, "exit_price"))
    if l_exit is not None and s_exit is not None:
        denom = abs(l_exit) or 1.0
        # Written as a positive test: ``x > tol`` is False for NaN, so a ``"nan"`` cell
        # (or an infinite one) used to read as "the same" (reviewer note on #117).
        if not abs(l_exit - s_exit) / denom <= price_tol_pct:
            diffs["exit_price"] = {"ledger": l_exit, "sheet": s_exit}

    for field in ("net_pnl", "gross_pnl"):
        lv = to_number(close_event.get(field))
        sv = to_number(sheet_cell(values, field))
        if lv is not None and sv is not None and not abs(lv - sv) <= pnl_tol:
            diffs[field] = {"ledger": lv, "sheet": sv}

    l_oid = _str_id(close_event.get("order_id"))
    s_oid = _str_id(sheet_cell(values, "exit_order_id"))
    if l_oid and s_oid and l_oid != s_oid:
        diffs["exit_order_id"] = {"ledger": l_oid, "sheet": s_oid}

    return diffs or None


def sheet_ledger_compare(
    trades: dict[str, dict[str, Any]],
    sheet_rows: list[dict[str, Any]] | None,
    *,
    sheet_name: str,
    norm_symbol: Callable[[Any], str],
    scope: str = "real-ledger-vs-google-sheet",
    fetch_error: str | None = None,
    now: datetime | None = None,
    since_ms: int | None = None,
    price_tol_pct: float = 0.001,
    pnl_tol: float = 0.01,
    ignore: Mapping[str, str] | None = None,
    ignore_problem: str | None = None,
) -> dict[str, Any]:
    """Pure verdict function for the ledger-vs-sheet layer.  Returns a
    ``google_reconcile_status.json`` document (``RECONCILED`` / ``DIVERGED`` /
    ``UNKNOWN`` + a per-row ``discrepancies`` list).

    ``ignore`` maps ``trade_id`` -> reason for trades the operator has decided
    are not wanted on the sheet (see :func:`load_reconcile_ignore`).  They are
    left out of the comparison -- but never silently: the document lists each
    one under ``ignored`` and counts them in ``summary['ignored']``.
    ``ignore_problem`` (a list file that could not be used) is carried into the
    document as ``ignore_list_problem`` so it is visible rather than hidden."""
    now = now or datetime.now(timezone.utc)
    checked_at = utc_now_iso(now)
    base = {"checked_at": checked_at, "scope": scope, "sheet_name": sheet_name,
            "last_reconciled_at": None}

    if fetch_error is not None or sheet_rows is None:
        return {**base, "value": "UNKNOWN", "discrepancies": [],
                "note": f"could not read the Google sheet: {fetch_error or 'no rows'}",
                "summary": {}}
    if not trades:
        return {**base, "value": "UNKNOWN", "discrepancies": [],
                "note": "no real local ledger trades yet", "summary": {}}

    def _in_scope(rec: dict[str, Any]) -> bool:
        if since_ms is None:
            return True
        return max(rec["opened_ms"], rec["closed_ms"]) >= since_ms

    sheet_by_id: dict[str, dict[str, Any]] = {}
    sheet_by_entry_oid: dict[str, dict[str, Any]] = {}
    for entry in sheet_rows:
        values = entry.get("values") or []
        tid = _str_id(sheet_cell(values, "trade_id"))
        if tid:
            sheet_by_id.setdefault(tid, entry)
        eoid = _str_id(sheet_cell(values, "entry_order_id"))
        if eoid:
            sheet_by_entry_oid.setdefault(eoid, entry)

    matched_rows: set[Any] = set()
    discrepancies: list[dict[str, Any]] = []

    ignore = dict(ignore or {})
    ignored: list[dict[str, str]] = []
    for tid, rec in sorted(trades.items(), key=lambda kv: max(kv[1]["opened_ms"], kv[1]["closed_ms"])):
        if not _in_scope(rec):
            continue
        if tid in ignore:
            ignored.append({"trade_id": tid, "symbol": rec["symbol"], "reason": ignore[tid]})
            continue
        entry = sheet_by_id.get(tid)
        matched_by = "trade_id"
        local_eoid = _str_id((rec.get("open_event") or {}).get("order_id"))
        if entry is None and local_eoid:
            # trade_id-only matching misses the case where the sheet row and the
            # ledger row were backfilled with independently-generated trade_ids.
            # entry_order_id is stable across both -- fall back to it.
            entry = sheet_by_entry_oid.get(local_eoid)
            if entry is not None:
                matched_by = "entry_order_id"
        if entry is None:
            discrepancies.append({
                "kind": "SHEET_MISSING_ROW", "trade_id": tid, "symbol": rec["symbol"],
                "sheet_row": None, "divergence": True,
                "detail": {"ledger_closed": rec["closed"]},
            })
            continue

        values = entry.get("values") or []
        sheet_row = entry.get("row")
        matched_rows.add(sheet_row)
        sheet_closed = _row_is_closed(values)
        close_event = rec["close_event"] or {}

        if matched_by == "entry_order_id":
            discrepancies.append({
                "kind": "trade_id_mismatch", "trade_id": tid, "symbol": rec["symbol"],
                "sheet_row": sheet_row, "divergence": False,
                "detail": {"note": "matched to the sheet row by entry_order_id; the "
                                   "trade_id differs (both sides backfilled with "
                                   "independently-generated ids) -- not actionable",
                           "sheet_trade_id": _str_id(sheet_cell(values, "trade_id")),
                           "entry_order_id": local_eoid},
            })

        if rec["closed"] and not sheet_closed:
            discrepancies.append({
                "kind": "SHEET_MISSING_CLOSE", "trade_id": tid, "symbol": rec["symbol"],
                "sheet_row": sheet_row, "divergence": True,
                "detail": {
                    "ledger_exit_price": close_event.get("exit_price"),
                    "ledger_net_pnl": close_event.get("net_pnl"),
                    "ledger_source": close_event.get("source"),
                    "marker_only": rec["close_event"] is None,
                },
            })
        elif not rec["closed"] and sheet_closed:
            discrepancies.append({
                "kind": "SHEET_UNEXPECTED_CLOSE", "trade_id": tid, "symbol": rec["symbol"],
                "sheet_row": sheet_row, "divergence": True,
                "detail": {"sheet_exit_time": sheet_cell(values, "exit_time"),
                           "sheet_net_pnl": sheet_cell(values, "net_pnl")},
            })
        elif rec["closed"] and sheet_closed and rec["close_event"] is not None:
            diffs = _value_mismatch(close_event, values,
                                    price_tol_pct=price_tol_pct, pnl_tol=pnl_tol)
            if diffs:
                estimate = _is_estimate_close(rec["close_event"])
                sheet_has_real_exit = bool(_str_id(sheet_cell(values, "exit_order_id")))
                if estimate and sheet_has_real_exit:
                    discrepancies.append({
                        "kind": "estimate_superseded", "trade_id": tid, "symbol": rec["symbol"],
                        "sheet_row": sheet_row, "divergence": False,
                        "detail": {"note": "ledger close is an estimate; sheet carries the "
                                           "reconciled real values -- expected end state",
                                   "diffs": diffs},
                    })
                else:
                    discrepancies.append({
                        "kind": "VALUE_MISMATCH", "trade_id": tid, "symbol": rec["symbol"],
                        "sheet_row": sheet_row, "divergence": True,
                        "detail": {"diffs": diffs, "ledger_is_estimate": estimate},
                    })

    known_ids = set(trades)
    for entry in sheet_rows:
        values = entry.get("values") or []
        tid = _str_id(sheet_cell(values, "trade_id"))
        if (not tid or tid in known_ids or entry.get("row") in matched_rows
                or not _row_in_scope(values)):
            continue
        discrepancies.append({
            "kind": "LEDGER_MISSING_ROW", "trade_id": tid,
            "symbol": norm_symbol(sheet_cell(values, "symbol")),
            "sheet_row": entry.get("row"), "divergence": True,
            "detail": {"sheet_execution_mode": sheet_cell(values, "execution_mode"),
                       "sheet_entry_time": sheet_cell(values, "entry_time")},
        })

    actionable = [d for d in discrepancies if d["divergence"]]
    by_kind: dict[str, int] = {}
    for d in discrepancies:
        by_kind[d["kind"]] = by_kind.get(d["kind"], 0) + 1
    summary = {
        "local_trades": len(trades),
        "sheet_rows": len(sheet_rows),
        "discrepancies": len(discrepancies),
        "actionable": len(actionable),
        "by_kind": by_kind,
    }
    extra: dict[str, Any] = {}
    if ignore or ignore_problem:
        summary["ignored"] = len(ignored)
        extra["ignored"] = ignored
    if ignore_problem:
        extra["ignore_list_problem"] = ignore_problem
    ignored_note = f"; {len(ignored)} trade(s) ignored by the operator's list" if ignored else ""

    if actionable:
        return {**base, "value": "DIVERGED",
                "note": f"{len(actionable)} sheet row(s) disagree with the local ledger" + ignored_note,
                "discrepancies": discrepancies, "summary": summary, **extra}
    info = [f"{by_kind[k]}x {k}" for k in SHEET_INFO_KINDS if by_kind.get(k)]
    return {**base, "value": "RECONCILED", "last_reconciled_at": checked_at,
            "note": "every real ledger trade agrees with its Google sheet row"
                    + (f" ({', '.join(info)} -- informational)" if info else "") + ignored_note,
            "discrepancies": discrepancies, "summary": summary, **extra}


RECONCILE_IGNORE_FILENAME = "google-reconcile-ignore.json"


def load_reconcile_ignore(path: str | Path) -> tuple[dict[str, str], str | None]:
    """Read the operator's "do not reconcile these trades" list.

    The file is ``{"ignore": [{"trade_id": "...", "reason": "..."}, ...]}``.  A
    missing file is an empty list.  Anything unusable -- not JSON, wrong shape,
    an entry without a ``trade_id`` or without a ``reason`` -- returns an empty
    list and a one-line problem: a broken list must never hide a divergence, so
    the caller reports the problem and compares everything.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, None
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"cannot read {p.name} ({type(exc).__name__})"
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return {}, f"{p.name} is not valid JSON"
    entries = doc.get("ignore") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return {}, f'{p.name} must be {{"ignore": [...]}}'
    out: dict[str, str] = {}
    for index, entry in enumerate(entries, start=1):
        trade_id = entry.get("trade_id") if isinstance(entry, dict) else None
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if not isinstance(trade_id, str) or not trade_id.strip() or not isinstance(reason, str) or not reason.strip():
            return {}, f"{p.name} entry {index} needs a non-empty trade_id and reason"
        out[trade_id.strip()] = reason.strip()
    return out, None
