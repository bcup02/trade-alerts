"""Append a whole batch of already-serialised ledger lines in one locked write.

A verified-close repair is 4+ events (``reconciliation_evidence_recorded`` /
one ``fill`` per deal / ``trade_close`` / ``position_reconciled_closed``) that
only make sense together. Every project's own ``TradeLedger.append`` writes one
event per ``open("a")`` with no lock and no ``fsync``, so a batch appended event
by event can stop half way -- and Phase 6 runs that batch unattended, against a
ledger that carries real money.

This module takes the batch as **lines a real ledger writer already produced**
rather than building them here, so the on-disk format stays owned by the
project's own ``TradeLedger`` and cannot drift: the caller stages the batch
through its own writer against a scratch path, reads the lines back, and hands
them here.

What this does and does not promise:

  * One ``write`` + ``flush`` + ``fsync`` under an exclusive lock, then a
    read-back that every intended line is present. A crash can still leave a
    torn final line, which ``ledger_reconcile.read_ledger`` already skips --
    so the outcome is "all of it" or "a fragment that reads as nothing".
  * It deliberately does **not** truncate back on failure. The lock here is a
    sibling ``.lock`` file (same mechanism as ``fleet_event_log``), and a
    strategy bot's own ``TradeLedger.append`` takes no lock at all -- so a
    rollback by truncation could discard a concurrent append from the bot.
    A caller that finds a partial batch must treat it as evidence and stop,
    never silently resume: see ``verified_close_backfill.incident_traces``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from .fleet_event_log import exclusive_log_lock


class AtomicAppendError(RuntimeError):
    """Raised when a batch could not be written, or could not be read back
    intact afterwards. Never raised for an empty batch -- that is a no-op."""


def _needs_leading_newline(target: Path) -> bool:
    """True when the file exists, is non-empty, and does not end in a newline."""
    if not target.exists():
        return False
    size = target.stat().st_size
    if size == 0:
        return False
    with target.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) != b"\n"


def append_lines_atomically(path: str | Path, lines: Sequence[str]) -> int:
    """Append every line in ``lines`` in a single locked, fsynced write.

    Each entry must be one complete JSON object with no embedded newline --
    exactly what a ``TradeLedger``-style writer emits per event. Returns the
    number of lines appended (0 for an empty batch).
    """
    if not lines:
        return 0

    encoded: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip("\n")
        if not stripped.strip():
            raise AtomicAppendError(f"batch line {index} is blank")
        if "\n" in stripped:
            raise AtomicAppendError(f"batch line {index} contains an embedded newline")
        try:
            json.loads(stripped)
        except ValueError as exc:
            raise AtomicAppendError(f"batch line {index} is not valid JSON") from exc
        encoded.append(stripped)

    blob = "".join(line + "\n" for line in encoded)
    target = Path(path)
    with exclusive_log_lock(target):
        # An earlier crash can leave a torn final line with no newline. Append
        # straight onto that and the fragment swallows this batch's first event
        # into one corrupt line, losing a real event instead of just the
        # fragment. Start a fresh line first so the fragment stays its own
        # unparseable line, which ``ledger_reconcile.read_ledger`` skips.
        if _needs_leading_newline(target):
            blob = "\n" + blob
        with target.open("a", encoding="utf-8") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        written = target.read_text(encoding="utf-8").splitlines()

    tail = written[-len(encoded):]
    if tail != encoded:
        raise AtomicAppendError(
            f"ledger read-back does not end with the {len(encoded)} appended lines; "
            "the batch may be partially written -- do not retry automatically"
        )
    return len(encoded)


def stage_lines(scratch_path: str | Path) -> list[str]:
    """Read back the lines a staging writer produced at ``scratch_path``.

    Companion to the staging pattern this module expects: point the project's
    own ledger writer at a scratch file, let it build and write the batch in
    its own format, then pass these lines to ``append_lines_atomically``.
    """
    target = Path(scratch_path)
    if not target.exists():
        return []
    return [line for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
