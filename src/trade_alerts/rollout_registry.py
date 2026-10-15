"""Fleet rollout registry: which fleet capability each strategy actually has.

The error catalog says what *should* happen for every condition; this registry
says, per strategy, whether it does yet.  It exists because the fleet kept
ending up with features built for one strategy of four and never written down
anywhere, found only months later by auditing all the code.  The rule it
enforces: a capability or catalog behaviour a strategy does not have is listed
as ``pending`` (with the phase it lands in and why) or ``n/a`` (with why) --
never silently missing.

``done`` means present on the branch the live host deploys from
(``operations``), at the commit recorded in ``sources`` -- merged to
development or running on the dev host is still ``pending``.  File:line
evidence refers to that commit, so it stays reproducible as the branches move;
``scripts/verify_registry_evidence.py`` checks every such reference against
local clones of the four repos (cross-repo, so not part of CI).

``registry_problems`` is the executable form of that rule.  trade-alerts' own
tests call it; a strategy repo's tests call :func:`project_rows` to check the
rows that make claims about itself.  The human page
``docs/guides/fleet-rollout-register.html`` is generated from the same file.
"""
from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from .fleet_event_log import PROJECT_CODE_PREFIXES

REGISTRY_VERSION = "fleet-rollout-registry/v1"
PACKAGED_REGISTRY_NAME = "fleet-rollout-registry.json"
#: The four strategies; ``fleet`` is a catalog prefix for cross-repo
#: conditions, not a strategy that can have a capability.
STRATEGY_PROJECTS = tuple(project for project in PROJECT_CODE_PREFIXES if project != "fleet")
STATES = ("done", "pending", "n/a")
#: ``done`` means present where the live host deploys from -- not merely
#: merged to development or running on the dev host.
LIVE_BRANCH = "operations"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
#: A pending cell that waits for a deployment names the commit it waits for (``awaits_commit``); the observation
#: watch (scripts/observation_watch.py, check ``registry-awaits``) compares it with what is running on A1 and says
#: when the cell must flip.  Without it "flips after it is deployed" is a promise only memory keeps (2026-10-15: 38
#: cells that had been live on A1 since 10-04 still said "not on the live host yet").
AWAITS_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_DEPLOY_PROMISE = re.compile(r"上正式機後改已做|上 A1 後改已做|上線後改已做|部署後改已做|還沒上正式機|尚未部署|未部署|未發版")
#: Length caps of the prose in a cell (phase-sync4).  They sit just above what the registry held when they were introduced
#: (2026-10-15: longest evidence 586, limit 206, pending/n-a reason 348), so a cell cannot grow back into the paragraph that
#: made the pages hard to read: the long A1 verification text lives in docs/registry-a1-checks.json, a limit is one sentence.
MAX_EVIDENCE_CHARS, MAX_LIMIT_CHARS, MAX_REASON_CHARS = 700, 300, 450
_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_OWNER = {prefix: project for project, prefix in PROJECT_CODE_PREFIXES.items()}


def load_rollout_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Read the registry -- by default the copy shipped inside this package."""
    if path is None:
        raw = resources.files("trade_alerts").joinpath("catalog", PACKAGED_REGISTRY_NAME).read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("registry_version") != REGISTRY_VERSION:
        raise ValueError(f"not a {REGISTRY_VERSION} document")
    return payload


def _status_problems(where: str, status: Any, phases: Mapping[str, Any]) -> list[str]:
    if not isinstance(status, Mapping):
        return [f"{where}: status is not an object"]
    state = status.get("state")
    if state not in STATES:
        return [f"{where}: unknown state {state!r}"]

    def text(key: str) -> bool:
        value = status.get(key)
        return isinstance(value, str) and bool(value.strip())

    problems = []
    if state == "done" and not text("evidence"):
        problems.append(f"{where}: done without evidence")
    if state == "done":
        if text("evidence") and len(status["evidence"]) > MAX_EVIDENCE_CHARS:
            problems.append(f"{where}: evidence is {len(status['evidence'])} characters (max {MAX_EVIDENCE_CHARS}) -- "
                            "keep what the code does and the file:line citations; put the A1 verification text in docs/registry-a1-checks.json "
                            "and the caveat in `limit`")
        if "verified_at" in status and not (isinstance(status["verified_at"], str) and _DATE.fullmatch(status["verified_at"])):
            problems.append(f"{where}: verified_at must be a YYYY-MM-DD date, got {status['verified_at']!r}")
        if "limit" in status:
            if not text("limit"):
                problems.append(f"{where}: limit must be a non-empty string")
            elif len(status["limit"]) > MAX_LIMIT_CHARS:
                problems.append(f"{where}: limit is {len(status['limit'])} characters (max {MAX_LIMIT_CHARS}) -- one sentence")
    else:
        for field in ("verified_at", "limit"):
            if field in status:
                problems.append(f"{where}: {field} only belongs on a done cell")
        if text("reason") and len(status["reason"]) > MAX_REASON_CHARS:
            problems.append(f"{where}: reason is {len(status['reason'])} characters (max {MAX_REASON_CHARS})")
    if state == "pending":
        if not text("reason"):
            problems.append(f"{where}: pending without a reason")
        if status.get("phase") not in phases:
            problems.append(f"{where}: pending phase {status.get('phase')!r} is not a registered phase")
        awaits = status.get("awaits_commit")
        if awaits is not None and not (isinstance(awaits, str) and AWAITS_COMMIT.fullmatch(awaits)):
            problems.append(f"{where}: awaits_commit must be a 7-40 character lowercase hex commit, got {awaits!r}")
        elif awaits is None and text("reason") and _DEPLOY_PROMISE.search(status["reason"]):
            problems.append(f"{where}: the reason promises a deployment ({_DEPLOY_PROMISE.search(status['reason']).group(0)!r}) "
                            "but names no commit -- add awaits_commit so the watch can tell when the cell must flip")
    elif "awaits_commit" in status:
        problems.append(f"{where}: awaits_commit only belongs on a pending cell")
    if state == "n/a" and not text("reason"):
        problems.append(f"{where}: n/a without a reason")
    return problems


def owners(code: str) -> tuple[str, ...]:
    """Which strategies a catalog code is about: its prefix's project, or all
    four for a ``FLEET.`` code."""
    project = _OWNER.get(code.split(".", 1)[0])
    if project is None:
        raise ValueError(f"unknown catalog prefix in {code!r}")
    return STRATEGY_PROJECTS if project == "fleet" else (project,)


def registry_problems(registry: Mapping[str, Any], catalog: Mapping[str, Any]) -> list[str]:
    """Every way the registry fails its rule; empty means consistent."""
    problems: list[str] = []
    if registry.get("registry_version") != REGISTRY_VERSION:
        problems.append(f"registry_version is not {REGISTRY_VERSION}")
    if registry.get("catalog_version") != catalog.get("catalog_version"):
        problems.append(f"registry is for {registry.get('catalog_version')!r}, catalog is {catalog.get('catalog_version')!r}")
    projects = registry.get("projects") or {}
    if set(projects) != set(STRATEGY_PROJECTS):
        problems.append(f"projects must be exactly {sorted(STRATEGY_PROJECTS)}, got {sorted(projects)}")
    phases = registry.get("phases") or {}
    sources = registry.get("sources") or {}
    if set(sources) != set(STRATEGY_PROJECTS):
        problems.append(f"sources must list exactly {sorted(STRATEGY_PROJECTS)}, got {sorted(sources)}")
    for project, source in sources.items():
        if not isinstance(source, Mapping):
            problems.append(f"sources / {project}: not an object")
            continue
        if not (isinstance(source.get("repo"), str) and source["repo"].count("/") == 1):
            problems.append(f"sources / {project}: repo must be owner/name")
        if source.get("branch") != LIVE_BRANCH:
            problems.append(f"sources / {project}: branch must be {LIVE_BRANCH!r} (what the live host runs), got {source.get('branch')!r}")
        if not (isinstance(source.get("commit"), str) and _COMMIT.match(source["commit"])):
            problems.append(f"sources / {project}: commit must be a full 40-character SHA")

    seen_ids: set[str] = set()
    for capability in registry.get("capabilities") or []:
        cid = capability.get("id")
        if not cid or cid in seen_ids:
            problems.append(f"capability id missing or duplicated: {cid!r}")
        seen_ids.add(cid)
        for key in ("title", "description"):
            if not (isinstance(capability.get(key), str) and capability[key].strip()):
                problems.append(f"capability {cid}: missing {key}")
        status = capability.get("status") or {}
        if set(status) != set(STRATEGY_PROJECTS):
            problems.append(f"capability {cid}: must list all four strategies, got {sorted(status)}")
        for project, value in status.items():
            problems += _status_problems(f"capability {cid} / {project}", value, phases)

    entries = {entry["code"]: entry for entry in catalog.get("entries") or []}
    rows = {row.get("code"): row for row in registry.get("catalog") or []}
    for code in sorted(entries.keys() - rows.keys()):
        problems.append(f"catalog entry {code} has no registry row")
    for code in sorted(rows.keys() - entries.keys()):
        problems.append(f"registry row {code} is not in the catalog")
    retired = {item.get("code") for item in catalog.get("retired_codes") or []}
    for code, row in rows.items():
        if code not in entries:
            continue
        expected = set(owners(code))
        for key in ("behaviour", "emits_event"):
            status = row.get(key) or {}
            if set(status) != expected:
                problems.append(f"{code} {key}: must list exactly {sorted(expected)}, got {sorted(status)}")
            for project, value in status.items():
                problems += _status_problems(f"{code} {key} / {project}", value, phases)
        if code in retired:
            for project, value in (row.get("behaviour") or {}).items():
                if isinstance(value, Mapping) and value.get("state") != "pending":
                    problems.append(f"{code} is retired but its behaviour for {project} is not pending replacement")

    cap_by_id = {capability.get("id"): capability for capability in registry.get("capabilities") or []}
    for i, change in enumerate(registry.get("recent_changes") or []):
        where = f"recent_changes[{i}]"
        if not isinstance(change, Mapping):
            problems.append(f"{where}: not an object")
            continue
        kind, cid = change.get("kind"), change.get("id")
        change_type = change.get("type", "completed")
        if change_type not in ("completed", "added", "updated"):
            problems.append(f"{where}: type must be completed, added or updated, got {change_type!r}")
            continue
        if kind == "cap":
            row_or_cap = cap_by_id.get(cid)
            missing_msg = f"{where}: capability {cid!r} not found"
        elif kind == "rule":
            row_or_cap = rows.get(cid)
            missing_msg = f"{where}: catalog code {cid!r} not found"
        else:
            problems.append(f"{where}: kind must be cap or rule, got {kind!r}")
            continue
        if row_or_cap is None:
            problems.append(missing_msg)
            continue
        if change_type in ("added", "updated"):
            # added: a brand-new row/capability this edit introduced; updated:
            # an existing one whose content (not its state) this edit changed.
            # Nothing to check it against, only that it (and its optional
            # project) are real.
            project = change.get("project")
            if project is not None and project not in STRATEGY_PROJECTS:
                problems.append(f"{where}: project {project!r} is not a known strategy")
            continue
        project = change.get("project")
        if project not in STRATEGY_PROJECTS:
            problems.append(f"{where}: type=completed needs a valid project, got {project!r}")
            continue
        if kind == "cap":
            state = ((row_or_cap.get("status") or {}).get(project) or {}).get("state")
        else:
            aspect = change.get("aspect")
            if aspect not in ("behaviour", "emits_event"):
                problems.append(f"{where}: type=completed rule entries need aspect behaviour/emits_event, got {aspect!r}")
                continue
            state = ((row_or_cap.get(aspect) or {}).get(project) or {}).get("state")
        if state not in ("done", "n/a"):
            problems.append(f"{where}: {cid} / {project} is {state!r}, not done/n-a -- a type=completed entry must point at what just became true")
    return problems


def project_rows(registry: Mapping[str, Any], project: str) -> dict[str, dict[str, Any]]:
    """Everything the registry claims about one strategy, for that strategy's
    own tests: ``{"capability:<id>": status, "<code>:behaviour": status,
    "<code>:emits_event": status}``."""
    if project not in STRATEGY_PROJECTS:
        raise ValueError(f"unknown strategy project {project!r}")
    rows: dict[str, dict[str, Any]] = {}
    for capability in registry.get("capabilities") or []:
        rows[f"capability:{capability['id']}"] = dict(capability["status"][project])
    for row in registry.get("catalog") or []:
        for key in ("behaviour", "emits_event"):
            if project in (row.get(key) or {}):
                rows[f"{row['code']}:{key}"] = dict(row[key][project])
    return rows
