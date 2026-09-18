"""Fleet rollout registry: which fleet capability each strategy actually has.

The error catalog says what *should* happen for every condition; this registry
says, per strategy, whether it does yet.  It exists because the fleet kept
ending up with features built for one strategy of four and never written down
anywhere, found only months later by auditing all the code.  The rule it
enforces: a capability or catalog behaviour a strategy does not have is listed
as ``pending`` (with the phase it lands in and why) or ``n/a`` (with why) --
never silently missing.

``registry_problems`` is the executable form of that rule.  trade-alerts' own
tests call it; a strategy repo's tests call :func:`project_rows` to check the
rows that make claims about itself.  The human page
``docs/guides/fleet-rollout-register.html`` is generated from the same file.
"""
from __future__ import annotations

import json
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
    if state == "pending":
        if not text("reason"):
            problems.append(f"{where}: pending without a reason")
        if status.get("phase") not in phases:
            problems.append(f"{where}: pending phase {status.get('phase')!r} is not a registered phase")
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
