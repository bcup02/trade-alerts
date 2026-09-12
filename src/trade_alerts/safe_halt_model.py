"""One safe-halt latch shape, and one fingerprint algorithm, for the whole fleet.

Before Phase 4 each strategy latched differently: momentum kept a single dict,
btc-competition four flat fields, seykota a ``SAFE_HALT`` string inside the same
``state.status`` field that also carries ``FLAT`` / ``LONG`` (so "the strategy is
halted" and "the strategy is flat" shared one slot), and my-crypto had no latch
at all.  Three separate resume tools computed three different fingerprints, and
only momentum made clearing a latch idempotent against its ledger.

This module is the single definition all of them now share:

* ``build_safe_halt`` writes the latch dict that goes into ``state.safe_halt``.
* ``safe_halt_fingerprint`` derives the confirmation token from the latch.
* ``cleared_fingerprints`` / ``safe_halt_cleared_fields`` make clearing a latch
  ledger-idempotent with identical fields in every strategy.

Evidence vs details is the one distinction a caller must get right.
``evidence`` is the stable set of facts an operator is really confirming and it
is the *only* input to the fingerprint besides ``code`` and ``reason``.
``details`` is diagnostic context that may change on every re-assertion of the
same halt (a re-read protection status, a current mark price, a retry count).
Feeding churning values into a fingerprint would move the confirmation token
every cycle, so the token printed by a preview would already be stale by the
time an operator pasted it back -- the latch could never be cleared at all.
Momentum's own resume tool had to carry a hand-maintained exclusion list for
exactly this reason; making the split explicit at write time removes the class
of bug instead of re-listing its instances.

Local-only by construction: nothing here reads a secret, opens a socket, or
imports an exchange client.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

FINGERPRINT_LENGTH = 12
SAFE_HALT_CLEARED_EVENT = "safe_halt_cleared"

#: A resume path a catalog entry can prescribe.  ``automatic`` clears the latch
#: without an operator once the condition is provably gone; ``two_stage_
#: fingerprint`` requires the preview/confirm gate below; ``restart_after_
#: config_fix`` deliberately offers no clear action, because what is wrong is a
#: setting or a credential and a "resume" button would imply the strategy may
#: run without fixing it.
RESUME_PATHS = frozenset({"automatic", "two_stage_fingerprint", "restart_after_config_fix", "n/a"})


class SafeHaltModelError(ValueError):
    """A latch, fingerprint, or clearing attempt violated the shared model."""


def utc_now_iso(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SafeHaltModelError("safe-halt payload is not canonical JSON") from exc


def _require_condition_code(code: Any) -> str:
    """Accept the bare condition name the strategies emit, not a catalog code.

    ``fleet_event_log.catalog_code`` is what joins a bare name back to the
    catalog; a prefixed code stored in state would make the same condition
    spell itself two ways depending on which layer wrote it.
    """
    if not isinstance(code, str) or not code:
        raise SafeHaltModelError("safe-halt code is required")
    if "." in code:
        raise SafeHaltModelError(
            "safe-halt code must be the bare condition name without a project prefix "
            f"(got {code!r}); use catalog_code() when a catalog code is needed"
        )
    return code


def build_safe_halt(
    *,
    code: str,
    reason: str,
    evidence: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Return the latch dict to store in ``state.safe_halt``.

    ``since`` is the moment this latch was first raised.  A caller re-asserting
    a latch that is already active must pass the original value through rather
    than stamping "now", so an operator can see how long a strategy has been
    stopped.  ``re_assert`` does that for them.
    """
    if not isinstance(reason, str) or not reason:
        raise SafeHaltModelError("safe-halt reason is required")
    halt = {
        "active": True,
        "code": _require_condition_code(code),
        "reason": reason,
        "since": since or utc_now_iso(),
        "evidence": dict(evidence or {}),
        "details": dict(details or {}),
    }
    _canonical(_fingerprint_core(halt))  # reject non-canonical evidence at write time
    return halt


def re_assert(previous: Mapping[str, Any] | None, latch: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the original ``since`` when the same condition is latched again.

    "Same" means the fingerprint is unchanged: identical code, reason and
    evidence.  A latch whose evidence changed is a different halt and starts its
    own clock, even though the code is the same.
    """
    updated = dict(latch)
    if isinstance(previous, Mapping) and previous.get("active") is True:
        try:
            unchanged = safe_halt_fingerprint(previous) == safe_halt_fingerprint(latch)
        except SafeHaltModelError:
            unchanged = False
        if unchanged and isinstance(previous.get("since"), str) and previous["since"]:
            updated["since"] = previous["since"]
    return updated


def _fingerprint_core(halt: Mapping[str, Any]) -> dict[str, Any]:
    evidence = halt.get("evidence")
    return {
        "code": halt.get("code"),
        "reason": halt.get("reason"),
        "evidence": dict(evidence) if isinstance(evidence, Mapping) else {},
    }


def safe_halt_fingerprint(halt: Mapping[str, Any]) -> str:
    """Derive the confirmation token from what is halted, not when.

    ``since`` and ``details`` are deliberately excluded: they change while the
    same condition stays latched, and a token that moves under the operator
    cannot be confirmed.  The token is never stored in state -- a stored copy
    can disagree with the latch it claims to describe, and every reader here can
    recompute it from the latch itself.
    """
    if not isinstance(halt, Mapping):
        raise SafeHaltModelError("safe-halt latch must be a mapping")
    _require_condition_code(halt.get("code"))
    blob = _canonical(_fingerprint_core(halt))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def active_safe_halt(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the active latch from a state mapping, or ``None``.

    A ``safe_halt`` key holding anything other than a mapping with
    ``active is True`` is not a latch.  Notably ``active: false`` and a leftover
    empty dict both read as "not halted", so a strategy that cleared a latch by
    flipping the flag rather than deleting the key still behaves correctly.
    """
    if not isinstance(state, Mapping):
        return None
    halt = state.get("safe_halt")
    if not isinstance(halt, Mapping) or halt.get("active") is not True:
        return None
    return dict(halt)


def is_latched(state: Mapping[str, Any]) -> bool:
    return active_safe_halt(state) is not None


def require_active_safe_halt(state: Mapping[str, Any]) -> dict[str, Any]:
    halt = active_safe_halt(state)
    if halt is None:
        raise SafeHaltModelError("refusing to resume: safe_halt is not active")
    return halt


def cleared_fingerprints(events: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Collect every fingerprint already cleared in one strategy's ledger.

    Each strategy reads its own ledger with its own reader; only this folding
    step is shared, so "clearing the same latch twice appends a second row" can
    no longer be true in one strategy and false in another.
    """
    found: set[str] = set()
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if event.get("event_type") != SAFE_HALT_CLEARED_EVENT:
            continue
        fingerprint = event.get("halt_fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            found.add(fingerprint)
    return frozenset(found)


def assert_not_already_cleared(fingerprint: str, events: Iterable[Mapping[str, Any]]) -> None:
    if fingerprint in cleared_fingerprints(events):
        raise SafeHaltModelError("refusing to resume: this exact safe_halt was already cleared")


def resume_preview(halt: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe one active latch and the token needed to clear it."""
    fingerprint = safe_halt_fingerprint(halt)
    assert_not_already_cleared(fingerprint, events)
    return {
        "code": halt.get("code"),
        "reason": halt.get("reason"),
        "halt_since": halt.get("since"),
        "evidence": dict(halt.get("evidence") or {}),
        "confirmation_token": fingerprint,
        "state_file_touched": False,
        "ledger_event_to_append": SAFE_HALT_CLEARED_EVENT,
    }


def check_confirmation(halt: Mapping[str, Any], token: str | None) -> str:
    """Validate an operator-supplied token against the current latch.

    A token from a *different* halt, or from this halt before its evidence
    changed, is rejected -- the operator confirmed something they are no longer
    looking at.
    """
    expected = safe_halt_fingerprint(halt)
    if (token or "").strip() != expected:
        raise SafeHaltModelError(
            "refusing to resume: --confirm token does not match the current safe_halt "
            f"(expected {expected}); re-run the preview and copy the token"
        )
    return expected


def safe_halt_cleared_fields(
    halt: Mapping[str, Any],
    *,
    method: str,
    cleared_at: str | None = None,
    reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the identical ledger row every strategy appends when clearing.

    ``method`` records *who or what* cleared it -- an operator confirmation, or
    an automatic clear for a condition the catalog marks ``automatic``.
    """
    if not isinstance(method, str) or not method:
        raise SafeHaltModelError("safe-halt cleared method is required")
    fields = {
        "halt_code": halt.get("code"),
        "halt_reason": halt.get("reason"),
        "halt_since": halt.get("since"),
        "halt_fingerprint": safe_halt_fingerprint(halt),
        "halt_evidence": dict(halt.get("evidence") or {}),
        "cleared_at": cleared_at or utc_now_iso(),
        "method": method,
        "reason": reason or f"safe_halt cleared ({method})",
    }
    fields.update(extra)
    return fields
