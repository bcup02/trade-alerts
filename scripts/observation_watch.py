#!/usr/bin/env python3
"""Observation-area watcher (f-43): watches, read-only, for the events the progress page's 「觀察區」 is waiting for.

The observation area lists things that can only be verified when something happens in production (the next real
status alert, the next real trade, the crypto strategy going flat ...).  Each *check* here knows

  * how to see that the event happened (read-only: files under /opt/<repo>/audit, /var/lib/..., the ops-notify journal,
    the commit a strategy clone on A1 is at, the blobs of cited files in those clones),
  * what "as expected" means mechanically, and what "not as expected" means,
  * whether a mechanical pass is enough to close the item (``closable``) or the operator must still look at a phone
    (``needs_human``).

A run writes ``state.json`` (the result of every check) and sends ONE Telegram message when a check changes into
``observed`` or ``failed`` (never again for the same thing; see ``notified_key``).  The progress-page items are closed
or reopened by Claude when it reads ``state.json`` at the start / end of a session -- this tool decides nothing about the
page, and a script cannot judge what it cannot measure.

Everything here is standard library only and runs unprivileged on the dev host; production (A1) is read over ssh with
``sudo cat`` / ``sudo journalctl`` on a fixed whitelist of paths and units (see ``Remote``).

    python3 scripts/observation_watch.py run          # check everything, notify on changes
    python3 scripts/observation_watch.py run --dry-run
    python3 scripts/observation_watch.py report [--json]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

TAIPEI = timezone(timedelta(hours=8))
A1_SSH_TARGET = "ubuntu@161.33.186.220"
DEFAULT_STATE = Path.home() / ".local" / "state" / "observation-watch" / "state.json"

OBSERVED, WAITING, FAILED, ERROR = "observed", "waiting", "failed", "error"
ERRORS_BEFORE_NOTICE = 3

# --- strategies ---------------------------------------------------------------------------------------------------

REPOS = {
    "seykota": "ed-seykota-systematic-trend-following",
    "momentum": "mexc-4h-momentum-trailing-stop",
    "mycrypto": "my-crypto-bot",
    "btc-competition": "btc-bull-market-competition",
}
SHEET_NAMES = {"seykota": "趨勢策略", "momentum": "動能策略", "mycrypto": "加密策略", "btc-competition": "競賽策略"}
LABELS = SHEET_NAMES  # the glossary's Chinese names are also the sheet tab names


def audit(key: str, name: str) -> str:
    return f"/opt/{REPOS[key]}/audit/{name}"


# --- read-only access ----------------------------------------------------------------------------------------------

class RemoteError(RuntimeError):
    """A read failed (host unreachable, file missing, path not on the whitelist)."""


def _allowed_paths() -> frozenset[str]:
    """Exactly the files the checks below read -- nothing else under /opt, /var/lib or anywhere is readable."""
    paths = {"/var/lib/portfolio-query/my-crypto-bot/current.json", "/var/lib/ops-notify/state.json",
             audit("mycrypto", "exchange_state.json")}
    for key in REPOS:
        paths |= {audit(key, name) for name in ("ledger_status.json", "google_reconcile_status.json", "trading_ledger.jsonl")}
    paths |= {audit(key, "fleet_event_log.jsonl") for key in ("seykota", "momentum", "btc-competition")}
    return frozenset(paths)


ALLOWED_PATHS = _allowed_paths()
#: A1 deploys by pulling ``operations`` in these clones and running the repo's installer, so a clone's HEAD is the
#: commit that was deployed.  Exactly these directories, and only ``rev-parse HEAD``, may be asked.
A1_CLONES = {key: f"/home/ubuntu/src/{name}" for key, name in REPOS.items()}
_SHA40 = re.compile(r"[0-9a-f]{40}")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
_LS_TREE_LINE = re.compile(r"^\d{6} blob ([0-9a-f]{40})\t(.+)$")


def _parse_ls_tree(text: str, source: str = "git ls-tree") -> dict[str, str]:
    """``{path: blob}`` from ``git ls-tree`` output.  A non-empty line that is not ``<mode> blob <sha>\\t<path>`` is an error:
    quietly skipping it would turn "could not read the tree" into "the file is not there" (review of #199)."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _LS_TREE_LINE.match(line)
        if not match:
            raise RemoteError(f"{source}: unrecognised output line {line[:80]!r}")
        found[match.group(2)] = match.group(1)
    return found


ALLOWED_UNITS = frozenset({"ops-notify.service"})
_SINCE_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


class Remote:
    """Reads files and journals on ``a1`` (over ssh) or ``dev`` (this machine, through ``sudo -n``).

    Only whitelisted arguments ever reach a shell: a path must be one of ``ALLOWED_PATHS`` (exact strings), a unit one of
    ``ALLOWED_UNITS``, a time must ``fullmatch`` ``_SINCE_RE``; the remote command is built with ``shlex.quote``.
    (What the unprivileged ssh user may ``sudo`` is a separate, wider permission on the hosts; this class is what keeps
    this tool inside the list above.)"""

    def __init__(self, ssh_key: str | None = None, timeout: int = 60):
        self.ssh_key = ssh_key or os.environ.get("OBSERVATION_WATCH_SSH_KEY") or str(Path.home() / ".ssh" / "oci_a1_key")
        self.timeout = timeout

    def _run(self, host: str, words: list[str]) -> str:
        if host == "a1":
            argv = ["ssh", "-i", self.ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                    "-o", "StrictHostKeyChecking=yes", A1_SSH_TARGET, "sudo " + " ".join(shlex.quote(w) for w in words)]
        elif host == "dev":
            argv = ["sudo", "-n", *words]
        else:
            raise RemoteError(f"unknown host {host!r}")
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RemoteError(f"{host}: {type(exc).__name__}: {exc}") from exc
        if done.returncode != 0:
            raise RemoteError(f"{host}: {' '.join(words[:2])} exit {done.returncode}: {done.stderr.strip()[:120]}")
        return done.stdout

    def read(self, host: str, path: str) -> str:
        if path not in ALLOWED_PATHS:
            raise RemoteError(f"path not on the read whitelist: {path!r}")
        return self._run(host, ["cat", path])

    def git_head(self, host: str, key: str) -> str:
        """The commit the deploy clone of strategy ``key`` is at (A1 only)."""
        if host != "a1" or key not in A1_CLONES:
            raise RemoteError(f"git head not allowed: {host!r} {key!r}")
        directory = A1_CLONES[key]
        sha = self._run(host, ["git", "-c", f"safe.directory={directory}", "-C", directory, "rev-parse", "HEAD"]).strip()
        if not _SHA40.fullmatch(sha):
            raise RemoteError(f"{host}: {key}: unexpected rev-parse output {sha[:60]!r}")
        return sha

    def git_blobs(self, host: str, key: str, paths: list[str]) -> dict[str, str]:
        """``{path: blob sha}`` of ``paths`` in the HEAD of strategy ``key``'s deploy clone on A1; a path the clone does not
        have is simply absent.  Only ``git ls-tree -r HEAD -- <paths>``; every path must look like a repo-relative path."""
        if host != "a1" or key not in A1_CLONES:
            raise RemoteError(f"git blobs not allowed: {host!r} {key!r}")
        bad = [p for p in paths if not _SAFE_PATH.fullmatch(p) or ".." in p.split("/")]
        if bad:
            raise RemoteError(f"git blobs: refusing paths {bad[:3]!r}")
        directory, found = A1_CLONES[key], {}
        for start in range(0, len(paths), 80):
            chunk = paths[start:start + 80]
            if chunk:
                out = self._run(host, ["git", "-c", f"safe.directory={directory}", "-C", directory, "ls-tree", "-r", "HEAD", "--", *chunk])
                found.update(_parse_ls_tree(out, "A1 " + key))
        return found

    def journal(self, host: str, unit: str, since_utc: str) -> str:
        if unit not in ALLOWED_UNITS or not _SINCE_RE.fullmatch(since_utc):
            raise RemoteError(f"journal arguments not allowed: {unit!r} {since_utc!r}")
        return self._run(host, ["journalctl", "-u", unit, "--since", since_utc + " UTC", "--utc", "--no-pager", "-q"])


# --- helpers -----------------------------------------------------------------------------------------------------

def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def taipei(moment: datetime) -> str:
    return moment.astimezone(TAIPEI).strftime("%m/%d %H:%M")


def jsonl(text: str) -> Iterator[dict[str, Any]]:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def load_json(remote: Remote, host: str, path: str) -> dict[str, Any]:
    try:
        data = json.loads(remote.read(host, path))
    except ValueError as exc:
        raise RemoteError(f"{path}: not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise RemoteError(f"{path}: not a JSON object")
    return data


def is_test_event(event: Mapping[str, Any]) -> bool:
    """Controlled tests mark themselves (``details.test`` / ``evidence.test``) and are not what we are waiting for."""
    return any(isinstance(event.get(k), Mapping) and event[k].get("test") is True for k in ("details", "evidence"))


@dataclass
class Context:
    remote: Remote
    now: datetime
    previous: Mapping[str, Any] = field(default_factory=dict)   # this check's stored state from the last run


@dataclass
class Result:
    state: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    needs_human: bool = False      # a mechanical pass is not enough: the operator must look at something (phone, sheet)
    closable: bool = False         # every criterion is mechanical and met: the item can be closed with this evidence
    key: str = ""                  # identifies WHAT was observed; the same key is announced once
    extra: dict[str, Any] = field(default_factory=dict)   # carried to the next run (see ``Context.previous``)


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    covers: tuple[str, ...]        # progress-page item ids this check can close or reopen
    run: Callable[[Context], Result]


# --- checks -------------------------------------------------------------------------------------------------------

def _fresh(moment: datetime | None, now: datetime, minutes: int) -> bool:
    return moment is not None and abs((now - moment).total_seconds()) <= minutes * 60


RECONCILE_GRACE = timedelta(minutes=61)   # a new trade may legitimately be missing from the sheet for 60 minutes


def reconcile_covers(status: Mapping[str, Any], last_trade: datetime, now: datetime) -> str:
    """Did the ledger-vs-sheet check run AFTER the grace period of the newest trade had passed?

    ``covered``  -- it did, and found everything on the sheet (RECONCILED);
    ``diverged`` -- it did, and the sheet disagrees;
    ``pending``  -- it has not (yet) looked at this trade with the grace expired, or its answer is unknown/stale.
    A RECONCILED that predates the trade (or is still inside its grace) proves nothing about it."""
    checked = parse_time(status.get("checked_at"))
    if checked is None or checked < last_trade + RECONCILE_GRACE or not _fresh(checked, now, 90):
        return "pending"
    return {"RECONCILED": "covered", "DIVERGED": "diverged"}.get(str(status.get("value")), "pending")


def check_crypto_flat(ctx: Context) -> Result:
    """x1: the crypto strategy is flat -- the signal to start the Binance move (the user asked to be told)."""
    snap = load_json(ctx.remote, "a1", "/var/lib/portfolio-query/my-crypto-bot/current.json")
    state = load_json(ctx.remote, "a1", audit("mycrypto", "exchange_state.json"))
    recon = load_json(ctx.remote, "a1", audit("mycrypto", "ledger_status.json"))
    snap_flat = (snap.get("position") or {}).get("status") == "FLAT"
    positions = state.get("positions")
    if not isinstance(positions, list):
        return Result(WAITING, "加密策略的交易所讀數沒有持倉欄位，沒辦法判斷是否空手。", [f"keys={sorted(state)[:8]}"])
    exchange_flat = positions == [] and (state.get("fetch_status") or {}).get("complete") is True
    fetched = parse_time(state.get("fetched_at"))
    if not _fresh(fetched, ctx.now, 45):
        return Result(WAITING, "加密策略的交易所讀數太舊，沒辦法判斷是否空手。", [f"fetched_at={state.get('fetched_at')}"])
    if snap_flat != exchange_flat:
        return Result(FAILED, "加密策略的快照與交易所讀數對不上（一個說空手、一個說有持倉）。",
                      [f"快照 position={snap.get('position')}", f"交易所 positions={json.dumps(positions)[:160]}"])
    if not exchange_flat:
        return Result(WAITING, "加密策略還有持倉。", [f"交易所 positions={json.dumps(positions, ensure_ascii=False)[:160]}"])
    if recon.get("value") != "RECONCILED":
        return Result(WAITING, "加密策略空手，但帳本對交易所還不是 RECONCILED。", [f"對帳={recon.get('value')}"])
    ledger = list(jsonl(ctx.remote.read("a1", audit("mycrypto", "trading_ledger.jsonl"))))
    closes = [e for e in ledger if e.get("event_type") == "trade_close"]
    last = closes[-1] if closes else {}
    since = parse_time(last.get("event_time"))
    return Result(OBSERVED, "加密策略現在空手：可以開始 x1（換 Binance）。注意它可能在下一個訊號又進場，要開工請盡快決定。",
                  [f"最近一筆平倉：{taipei(since) if since else '?'}（台北）；帳本、交易所、快照三方都顯示空手，對帳一致。",
                   f"交易所權益 {((state.get('balance') or {}).get('equity'))} USDT"],
                  needs_human=True, key=str(last.get("event_id") or "flat"))


_F26_BASELINE = datetime(2026, 10, 9, 9, 30, tzinfo=timezone.utc)   # 2026-10-09 台北 17:30: tab names switched to Chinese
_TRADE_TYPES = ("trade_open", "trade_close", "spot_fill")


def _trades_after(events: Iterable[dict[str, Any]], after: datetime, types: Iterable[str] = _TRADE_TYPES) -> list[dict[str, Any]]:
    out = []
    for event in events:
        moment = parse_time(event.get("event_time"))
        if event.get("event_type") in types and moment and moment > after and event.get("execution_mode", "LIVE") == "LIVE":
            out.append(event)
    return out


def check_sheet_tab_names(ctx: Context) -> Result:
    """f-26: each strategy's next real trade goes through the Chinese tab name and the ledger-vs-sheet check agrees."""
    ok, waiting, bad, evidence = [], [], [], []
    for key in REPOS:
        status = load_json(ctx.remote, "a1", audit(key, "google_reconcile_status.json"))
        trades = _trades_after(jsonl(ctx.remote.read("a1", audit(key, "trading_ledger.jsonl"))), _F26_BASELINE)
        name = LABELS[key]
        if status.get("sheet_name") != SHEET_NAMES[key]:
            bad.append(name)
            evidence.append(f"{name}：對帳讀的分頁是 {status.get('sheet_name')!r}，應為 {SHEET_NAMES[key]!r}")
            continue
        if not trades:
            waiting.append(name)
            continue
        last = max(parse_time(t["event_time"]) for t in trades)
        verdict = reconcile_covers(status, last, ctx.now)
        if verdict == "covered":
            ok.append(name)
            evidence.append(f"{name}：{len(trades)} 筆新交易（最近 {taipei(last)} 台北），之後的 Google 表對帳（{taipei(parse_time(status['checked_at']))}）一致")
        elif verdict == "diverged":
            bad.append(name)
            evidence.append(f"{name}：最近一筆新交易已過 60 分鐘寬限，之後的 Google 表對帳仍是 DIVERGED")
        else:
            waiting.append(name)
    if bad:
        return Result(FAILED, "新分頁名有策略不符合預期：" + "、".join(bad), evidence, key="bad:" + ",".join(bad))
    if not waiting:
        return Result(OBSERVED, "四支策略的新交易都走新分頁名，帳本對 Google 表一致。", evidence, closable=True, key="all")
    summary = ("已確認：" + "、".join(ok) + "；" if ok else "") + "還在等新交易：" + "、".join(waiting)
    return Result(WAITING, summary, evidence)


def check_competition_fill(ctx: Context) -> Result:
    """e-2: the competition strategy's next real spot fill reaches the sheet as a spot_fill row."""
    events = jsonl(ctx.remote.read("a1", audit("btc-competition", "trading_ledger.jsonl")))
    fills = _trades_after(events, datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc), ("spot_fill",))
    if not fills:
        return Result(WAITING, "競賽策略還沒有新的現貨成交。")
    status = load_json(ctx.remote, "a1", audit("btc-competition", "google_reconcile_status.json"))
    last = max(parse_time(f["event_time"]) for f in fills)
    verdict = reconcile_covers(status, last, ctx.now)
    if verdict == "covered":
        return Result(OBSERVED, "競賽策略有新的現貨成交，成交後的 Google 表對帳一致。",
                      [f"{len(fills)} 筆新成交，最近 {taipei(last)}（台北）；對帳（{taipei(parse_time(status['checked_at']))}）：{status.get('note')}"],
                      closable=True, key=str(len(fills)))
    if verdict == "diverged":
        return Result(FAILED, "競賽策略有新的現貨成交，過了寬限之後 Google 表對帳仍對不上。", [f"對帳：{status.get('note')}"])
    return Result(WAITING, "競賽策略有新成交，等成交寬限期過後的 Google 表對帳。", [f"對帳={status.get('value')}，檢查時間 {status.get('checked_at')}"])


def check_trend_addon(ctx: Context) -> Result:
    """e-5: a trade with a pyramid add on A1 shows the whole-trade entry price and size on the sheet."""
    events = jsonl(ctx.remote.read("a1", audit("seykota", "trading_ledger.jsonl")))
    opens: dict[str, int] = {}
    for event in _trades_after(events, datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc), ("trade_open",)):
        opens[str(event.get("trade_id"))] = opens.get(str(event.get("trade_id")), 0) + 1
    added = sorted(t for t, n in opens.items() if n >= 2)
    if not added:
        return Result(WAITING, "A1 趨勢策略還沒有加碼的交易。")
    status = load_json(ctx.remote, "a1", audit("seykota", "google_reconcile_status.json"))
    last = max(parse_time(e["event_time"]) for e in _trades_after(jsonl(ctx.remote.read("a1", audit("seykota", "trading_ledger.jsonl"))),
                                                               datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc), ("trade_open",)))
    ok = reconcile_covers(status, last, ctx.now) == "covered"
    return Result(OBSERVED if ok else WAITING, "A1 趨勢策略出現加碼的交易：請到 Google 表確認進場價與數量是整筆加權值（機器只能確認對帳一致）。",
                  [f"加碼交易：{', '.join(added)}", f"對帳：{status.get('value')}"], needs_human=True, key=",".join(added))


def check_dev_trend_entry(ctx: Context) -> Result:
    """f-7: the dev host's trend strategy really places a testnet entry on a signal (not a manual test) and records it."""
    events = list(jsonl(ctx.remote.read("dev", audit("seykota", "trading_ledger.jsonl"))))
    entries = [e for e in events if e.get("event_type") == "trade_open" and e.get("source") == "entry_signal"
               and (parse_time(e.get("event_time")) or datetime.min.replace(tzinfo=timezone.utc)) > datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)]
    if not entries:
        return Result(WAITING, "開發機趨勢策略還沒有因進場訊號而下的測試網單。")
    status = load_json(ctx.remote, "dev", audit("seykota", "google_reconcile_status.json"))
    last = max(parse_time(e["event_time"]) for e in entries)
    verdict = reconcile_covers(status, last, ctx.now)
    if verdict == "covered":
        return Result(OBSERVED, "開發機趨勢策略依進場訊號在測試網下單，進場後的帳本對 Google 表對帳一致。",
                      [f"{len(entries)} 筆進場；最近 {taipei(last)}（台北）；對帳（{taipei(parse_time(status['checked_at']))}）：{status.get('note')}"],
                      closable=True, key=str(len(entries)))
    if verdict == "diverged":
        return Result(FAILED, "開發機趨勢策略有進場，過了寬限之後 Google 表對帳仍對不上。", [f"對帳：{status.get('note')}"])
    return Result(WAITING, "開發機趨勢策略有進場，等進場寬限期過後的 Google 表對帳。", [f"對帳={status.get('value')}，檢查時間 {status.get('checked_at')}"])


_NOTICE_LINE = re.compile(r"notices=(\d+) attempted=(\d+) sent=(\d+) consecutive_send_failures=(\d+)")
_NOTIFY_FAILURES = re.compile(r"status_ai_send_failed|status_ai_dropped|status_ai_render_failed|reminder_send_failed|reminders_unavailable")
_A1_STATUS_BASELINE = "2026-10-13 04:28:00"   # f-41 deployed to A1 at 台北 12:28


def check_status_alerts(ctx: Context) -> Result:
    """f-23 / f-40 / f-41: the first real status alert on A1.

    Three different things are kept apart: the EVENT (a poll with notices>0), the FIRST message's delivery (the poll's
    sent=attempted and the state file's notified_at) and the SECOND message, whose success ops-notify does not log at all
    (only failures) -- so it is never claimed delivered; the operator confirms it on the phone."""
    base = parse_time(_A1_STATUS_BASELINE.replace(" ", "T") + "+00:00")
    text = ctx.remote.journal("a1", "ops-notify.service", _A1_STATUS_BASELINE)
    real, failures = [], []
    for line in text.splitlines():
        match = _NOTICE_LINE.search(line)
        if match:
            notices, attempted, delivered, consecutive = map(int, match.groups())
            if notices > 0:
                real.append((line[:15], notices, attempted, delivered))
            if delivered < attempted or consecutive > 0:
                failures.append(line.strip()[:160])
        elif _NOTIFY_FAILURES.search(line):
            failures.append(line.strip()[:160])
    if failures:
        return Result(FAILED, "A1 的維運通知有送不出去的紀錄。", failures[:4], key="failures:" + str(len(failures)))
    if not real:
        return Result(WAITING, "A1 自 f-41 部署後還沒有真實的狀態告警。")
    state = load_json(ctx.remote, "a1", "/var/lib/ops-notify/state.json")
    told = sorted((k, v["notified_at"]) for k, v in state.items()
                  if not k.startswith("_") and isinstance(v, Mapping) and (parse_time(v.get("notified_at")) or base) > base)
    first = real[0]
    return Result(OBSERVED, "A1 出現真實的狀態告警。第一則送出有日誌與狀態檔證據；第二則的送達沒有證據，要你在手機確認第二則帶著指令、貼上能跑。",
                  [f"事件：{len(real)} 輪日誌有通知（第一輪 {first[0]}，UTC）",
                   f"第一則：該輪通知 {first[1]}、嘗試 {first[2]}、送出 {first[3]}；" + (
                       "狀態檔送出時間 " + "、".join(f"{k}@{t}" for k, t in told[:3]) if told else "狀態檔已沒有送出時間（可能已恢復清除）"),
                   "第二則：日誌沒有送失敗的紀錄，但成功不會被記錄，所以沒有送達證據"],
                  needs_human=True, key=first[0])


def check_reminders(ctx: Context) -> Result:
    """f-39: an unresolved status alert is re-sent on Telegram (30 min, then 3 h) and stops when it recovers."""
    state = load_json(ctx.remote, "a1", "/var/lib/ops-notify/state.json")
    reminders = state.get("_reminders") if isinstance(state.get("_reminders"), Mapping) else {}
    seen: dict[str, Any] = dict(ctx.previous.get("seen") or {})
    for key, entry in reminders.items():
        if isinstance(entry, Mapping) and isinstance(entry.get("count"), int):
            old = seen.get(key, {})
            seen[key] = {"since": entry.get("since"), "max_count": max(entry["count"], old.get("max_count", 0)),
                         "last_at": entry.get("last_at"), "ended": False}
    for key, old in seen.items():
        if key not in reminders:
            old["ended"] = True
    text = ctx.remote.journal("a1", "ops-notify.service", "2026-10-13 02:54:00")
    failures = [l.strip()[:160] for l in text.splitlines() if _NOTIFY_FAILURES.search(l)]
    extra = {"seen": seen}
    if failures:
        return Result(FAILED, "A1 的 Telegram 提醒有送不出去的紀錄。", failures[:4], key="failures:" + str(len(failures)), extra=extra)
    sent = {k: v for k, v in seen.items() if v.get("max_count", 0) >= 1}
    if not sent:
        return Result(WAITING, "A1 還沒有進入持續提醒的告警。", extra=extra)
    ended = [k for k, v in sent.items() if v.get("ended")]
    evidence = [f"{k}：提醒 {v['max_count']} 次，最後一次 {v.get('last_at')}，{'已恢復並停止' if v.get('ended') else '還在提醒'}" for k, v in sent.items()]
    return Result(OBSERVED, "A1 的持續提醒已送出" + ("，恢復後也停了。" if ended else "（還沒恢復，等它恢復才能確認會停）。")
                  + "請確認 Telegram 收到的次數與間隔。", evidence, needs_human=True, key=",".join(sorted(sent)) + (":ended" if ended else ""), extra=extra)


def _a1_event_logs() -> list[tuple[str, str]]:
    return [(key, audit(key, "fleet_event_log.jsonl")) for key in ("seykota", "momentum", "btc-competition")]


def _real_events(ctx: Context, after: datetime, *, codes: set[str] | None = None, not_codes: set[str] = frozenset(),
                 tiers: set[str] | None = None) -> list[tuple[str, dict[str, Any]]]:
    found = []
    for key, path in _a1_event_logs():
        for event in jsonl(ctx.remote.read("a1", path)):
            moment = parse_time(event.get("recorded_at"))
            if not moment or moment <= after or is_test_event(event):
                continue
            code = str(event.get("code") or "")
            if codes is not None and code not in codes:
                continue
            if code in not_codes or (tiers is not None and event.get("risk_tier") not in tiers):
                continue
            found.append((key, event))
    return found


EVENT_NOTICE_OVERDUE = timedelta(minutes=40)    # ops-notify polls every 10 minutes
SECOND_MESSAGE_OVERDUE = timedelta(minutes=70)


def _strategy_event_result(ctx: Context, events: list[tuple[str, dict[str, Any]]], *, seen: str, ask: str) -> Result:
    """A real strategy event is not 'notified' because it is in the event log: ops-notify's ``_export[...]['delivered']``
    says when the first message went out and ``ai_pending`` that a second one is still owed.  Keeps the three stages apart:
    the event, the delivery evidence, and what only the operator can confirm."""
    state = load_json(ctx.remote, "a1", "/var/lib/ops-notify/state.json")
    exported = state.get("_export") if isinstance(state.get("_export"), Mapping) else {}
    evidence, overdue, undelivered, unproven = [], [], [], []
    for key, event in events[:5]:
        target = exported.get(key) if isinstance(exported.get(key), Mapping) else {}
        delivered = (target.get("delivered") or {}).get(event.get("event_id"))
        owed = (target.get("ai_pending") or {}).get(event.get("event_id"))
        at = parse_time(event.get("recorded_at"))
        baseline = parse_time(target.get("baseline_at"))
        label = f"{LABELS[key]}：{event.get('code')}（事件 {taipei(at)} 台北）"
        if delivered and (baseline is None or at <= baseline):
            # ops-notify marks every notice that already exists when it first sees a target as 'delivered' WITHOUT sending
            # (export_relay.py, to avoid re-sending old notices); such a mark is not evidence that anything went out.
            unproven.append(label)
            evidence.append(label + "；第一則：無法證明有送出（這則事件早於維運通知首次建立基準的時間，"
                                    "送出紀錄是當時的略過標記，不是實際送出）")
        elif not delivered:
            (overdue if ctx.now - at > EVENT_NOTICE_OVERDUE else undelivered).append(label)
            evidence.append(label + "；第一則：維運通知還沒有送出紀錄")
        elif owed and ctx.now - (parse_time(owed) or ctx.now) > SECOND_MESSAGE_OVERDUE:
            overdue.append(label)
            evidence.append(label + f"；第二則送失敗重試中，自 {owed} 起")
        else:
            evidence.append(label + f"；第一則已送出（維運通知記錄 {delivered}）" + ("；第二則還在重試" if owed else "；第二則沒有欠送紀錄，但送達要你確認"))
    key = str(events[0][1].get("event_id"))
    if overdue:
        return Result(FAILED, "事件已記錄，但維運通知超過預期時間沒有送出（或第二則一直送不出去）。", evidence, key="overdue:" + key)
    if undelivered:
        return Result(WAITING, "事件已記錄，等維運通知下一輪送出。", evidence)
    if unproven:
        return Result(OBSERVED, seen + "但維運通知有沒有送出無法從紀錄證明，請你確認有沒有收到。", evidence, needs_human=True, key="unproven:" + key)
    return Result(OBSERVED, seen + ask, evidence, needs_human=True, key=key)


def check_pending_expired(ctx: Context) -> Result:
    """f-30: a reconcile marker/batch older than 24 h is announced once (ERR-060 / ERR-061) with usable steps."""
    events = _real_events(ctx, datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc), codes={"LEDGER_PENDING_EXPIRED"})
    if not events:
        return Result(WAITING, "A1 還沒有超過 24 小時沒結清的對帳標記或調倉批次。")
    return _strategy_event_result(ctx, events, seen="A1 出現了「對帳標記超過 24 小時」的通知事件。", ask="請確認通知只來一次、結清步驟可用。")


def check_repair_recurring(ctx: Context) -> Result:
    """g2: the same strategy auto-repaired twice in 7 days -> one 'this keeps happening' notice."""
    events = _real_events(ctx, datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc), codes={"VERIFIED_CLOSE_REPAIR_RECURRING"})
    if not events:
        return Result(WAITING, "A1 還沒有「自動補寫一直在發生」的通知事件。")
    return _strategy_event_result(ctx, events, seen="A1 出現了「自動補寫一直在發生」的通知事件。", ask="請確認通知內容與只發一次。")


def check_safe_halt_notice(ctx: Context) -> Result:
    """f-35 / f-37: the first real R3 strategy notice on A1 -- its pasted commands must run as written."""
    events = _real_events(ctx, datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc), tiers={"R3"},
                          not_codes={"LEDGER_PENDING_EXPIRED", "VERIFIED_CLOSE_REPAIR_RECURRING"})
    if not events:
        return Result(WAITING, "A1 自 f-37 部署後還沒有真實的 R3 策略通知。")
    return _strategy_event_result(ctx, events, seen="A1 出現真實的 R3 策略通知。", ask="請照通知步驟貼一次確認指令，確認能跑（只用預覽，不要解除）。")


# --- registry cells waiting for a deployment (phase-sync1) -----------------------------------------------------------

REGISTRY_RELATIVE = "src/trade_alerts/catalog/fleet-rollout-registry.json"


def repos_root() -> Path:
    return Path(os.environ.get("OBSERVATION_WATCH_REPOS_ROOT") or Path.home())


def _git(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def _refresh(repo: Path) -> bool | None:
    """Fetch when the clone has an ``origin``: True = refreshed, False = the fetch failed, None = no origin to fetch.

    Callers decide what a failure means: the registry's own clone must be fresh (a stale ``origin/main`` could be
    missing the very cells this check exists for), while a strategy clone only has to contain the awaited commit,
    which ``cat-file`` and ``merge-base`` check explicitly."""
    if _git(repo, "remote", "get-url", "origin").returncode != 0:
        return None
    return _git(repo, "fetch", "-q", "origin").returncode == 0


def awaiting_cells(registry: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """``(cell label, strategy key, commit)`` for every pending cell that names the commit it waits for."""
    cells = []
    for capability in registry.get("capabilities") or []:
        for project, status in (capability.get("status") or {}).items():
            if status.get("state") == "pending" and status.get("awaits_commit"):
                cells.append((f"能力 {capability['id']} / {project}", project, status["awaits_commit"]))
    for row in registry.get("catalog") or []:
        for aspect in ("behaviour", "emits_event"):
            for project, status in (row.get(aspect) or {}).items():
                if status.get("state") == "pending" and status.get("awaits_commit"):
                    cells.append((f"規則 {row['code']} {aspect} / {project}", project, status["awaits_commit"]))
    return cells


def check_registry_awaits(ctx: Context) -> Result:
    """phase-sync1: a registry cell that still says "pending until <commit> is deployed" while A1 already runs that commit.

    "done" means running on A1, and nothing used to notice when that became true: on 2026-10-15 a rereading found 38
    cells that had been live since 10-04.  A cell that waits for a deployment names the commit (``awaits_commit``);
    this check asks A1 which commit each strategy's deploy clone is at and whether the awaited commit is part of it."""
    root = repos_root()
    # Reading an old origin/main here would answer "nothing to compare" about a registry that may already hold the cells this
    # check is for (review of #193): a registry that cannot be refreshed is an error (see _load_registry).
    registry = _load_registry(root)
    cells = awaiting_cells(registry)
    if not cells:
        return Result(WAITING, "登記冊沒有帶『等哪個提交』的未做格子，沒有東西要比對。")
    heads: dict[str, str] = {}
    due, open_ = [], []
    for label, project, commit in cells:
        repo = root / REPOS[project]
        if project not in heads:
            heads[project] = ctx.remote.git_head("a1", project)
            _refresh(repo)
        known = _git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0
        if not known:
            raise RemoteError(f"{label}: 等的提交 {commit} 在 {repo} 找不到（寫錯或還沒推上遠端？）")
        deployed = _git(repo, "merge-base", "--is-ancestor", commit, heads[project])
        if deployed.returncode not in (0, 1):
            raise RemoteError(f"{label}: merge-base 出錯：{deployed.stderr.strip()[:120]}")
        (due if deployed.returncode == 0 else open_).append(f"{label}：等 {commit[:7]}，A1 現在 {heads[project][:7]}")
    if due:
        return Result(OBSERVED, f"登記冊有 {len(due)} 格還寫未做，但它們在等的提交已經在 A1 上跑了：該改已做（並重發登記冊）。",
                      due + [f"（仍在等）{o}" for o in open_], needs_human=True, key=",".join(sorted(d.split("：")[0] for d in due)))
    return Result(WAITING, f"登記冊有 {len(open_)} 格在等部署，等的提交都還沒上 A1。", open_)


# --- files the registry cites that changed on A1 since the registry's sources commit (phase-sync4) ------------------

#: The same shape trade-alerts' verify_registry_evidence.py recognises as a file citation.
_CITED_FILE = re.compile(r"(?<![\w./-])((?:(?:src|scripts|tools|tests|docs|deploy)/[\w./-]+\.\w+)|[\w-]+\.py)(?::\d+)?")


def cited_files(registry: Mapping[str, Any]) -> dict[str, dict[str, list[str]]]:
    """``{project: {path: [cell labels]}}`` for every file a ``done`` cell cites (a done claim is what drift can falsify)."""
    out: dict[str, dict[str, list[str]]] = {}

    def add(label: str, project: str, status: Mapping[str, Any]) -> None:
        if status.get("state") != "done":
            return
        for match in _CITED_FILE.finditer(str(status.get("evidence", ""))):
            labels = out.setdefault(project, {}).setdefault(match.group(1), [])
            if label not in labels:
                labels.append(label)

    for capability in registry.get("capabilities") or []:
        for project, status in (capability.get("status") or {}).items():
            add(f"能力 {capability['id']}", project, status)
    for row in registry.get("catalog") or []:
        for aspect in ("behaviour", "emits_event"):
            for project, status in (row.get(aspect) or {}).items():
                add(f"規則 {row['code']} {aspect}", project, status)
    return out


def _load_registry(root: Path) -> dict[str, Any]:
    ta = root / "trade-alerts"
    if _refresh(ta) is False:
        raise RemoteError(f"cannot refresh {ta} (git fetch failed): the registry on origin/main may be out of date")
    shown = _git(ta, "show", f"{os.environ.get('OBSERVATION_WATCH_REGISTRY_REF', 'origin/main')}:{REGISTRY_RELATIVE}")
    if shown.returncode != 0:
        raise RemoteError(f"cannot read the registry from {ta}: {shown.stderr.strip()[:120]}")
    return json.loads(shown.stdout)


def _blobs_at(repo: Path, commit: str, paths: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for start in range(0, len(paths), 80):
        chunk = paths[start:start + 80]
        done = _git(repo, "ls-tree", "-r", commit, "--", *chunk)
        if done.returncode != 0:
            raise RemoteError(f"git ls-tree {commit[:7]} in {repo}: {done.stderr.strip()[:120]}")
        found.update(_parse_ls_tree(done.stdout, f"git ls-tree {commit[:7]} in {repo.name}"))
    return found


def check_registry_drift(ctx: Context) -> Result:
    """phase-sync4: a file a ``done`` cell cites differs on A1 from the registry's ``sources`` commit.

    The cell's file:line evidence points at the ``sources`` commit; once the file on A1 is a different version, the line may
    have moved and the claim may no longer hold (10-04 and 10-15: cells stayed "done" or "pending" while the code under
    them changed).  This compares, for every cited file, the blob in the A1 deploy clone's HEAD with the blob at ``sources``;
    a difference means the cell needs re-verifying (and ``sources`` moving on, the f-27 way)."""
    root = repos_root()
    registry = _load_registry(root)
    drifted: list[tuple[str, str, str, str, list[str]]] = []
    checked = 0
    for project, files in sorted(cited_files(registry).items()):
        source = (registry.get("sources") or {}).get(project) or {}
        commit = source.get("commit")
        if not commit:
            raise RemoteError(f"{project}: the registry has no sources commit")
        repo = root / REPOS[project]
        _refresh(repo)
        if _git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
            raise RemoteError(f"{project}: sources commit {commit[:7]} not found in {repo}")
        paths = sorted(files)
        at_sources = _blobs_at(repo, commit, paths)
        asked = [p for p in paths if p in at_sources]
        on_a1 = ctx.remote.git_blobs("a1", project, asked)
        stray = sorted(set(on_a1) - set(asked))
        if stray:
            raise RemoteError(f"{project}: A1 answered about files that were not asked for: {stray[:3]!r}")
        for path in paths:
            if path not in at_sources:
                continue                       # the citation names no file in that repo (verify_registry_evidence reports those)
            checked += 1
            if on_a1.get(path) != at_sources[path]:
                a1_blob = on_a1.get(path)
                drifted.append((project, path, a1_blob[:7] if a1_blob else "（A1 上沒有這個檔案）", at_sources[path][:7], files[path]))
    if checked == 0 and cited_files(registry):
        # every cited file is missing at the sources commit: that is a wrong sources commit or an unreadable tree, not "no drift"
        raise RemoteError("登記冊引用了檔案，但在 sources 提交上一個都找不到：sources 提交或引用寫法有問題，沒辦法比對")
    if not drifted:
        return Result(WAITING, f"登記冊引用的 {checked} 個檔案，在 A1 部署複本上都和 sources 提交是同一份。")
    cells = {label for *_, labels in drifted for label in labels}
    evidence = [f"{project}／{path}：A1 {a1}，sources {src}；影響 {len(labels)} 格：" + "；".join(labels[:3]) + ("…" if len(labels) > 3 else "")
                for project, path, a1, src, labels in drifted]
    return Result(OBSERVED, f"登記冊引用的 {checked} 個檔案裡，{len(drifted)} 個在 A1 上和 sources 提交不一樣，影響 {len(cells)} 格："
                  "行號可能位移、說法可能不再成立，要重驗並把 sources 換到 A1 現行版。",
                  evidence, needs_human=True, key=",".join(f"{p}:{path}:{a1}" for p, path, a1, _, _ in drifted))


CHECKS: tuple[Check, ...] = (
    Check("crypto-flat", "加密策略空手（開工 x1 的訊號）", ("phase-x1",), check_crypto_flat),
    Check("sheet-tab-names", "四支策略的新交易走新分頁名", ("f-26",), check_sheet_tab_names),
    Check("competition-fill", "競賽策略現貨成交送上表", ("e-2",), check_competition_fill),
    Check("trend-addon", "A1 趨勢策略加碼交易", ("e-5",), check_trend_addon),
    Check("dev-trend-entry", "開發機趨勢策略依訊號進場", ("f-7",), check_dev_trend_entry),
    Check("status-alerts", "A1 第一則真實狀態告警", ("f-23", "f-40", "f-41"), check_status_alerts),
    Check("reminders", "A1 持續提醒", ("f-39",), check_reminders),
    Check("pending-expired", "對帳標記逾時通知", ("f-30",), check_pending_expired),
    Check("repair-recurring", "自動補寫重複發生通知", ("phase-g2",), check_repair_recurring),
    Check("safe-halt-notice", "A1 第一則真實 R3 策略通知", ("f-35", "f-37"), check_safe_halt_notice),
    Check("registry-awaits", "登記冊等部署的格子：等的提交已上 A1", ("phase-sync1",), check_registry_awaits),
    Check("registry-drift", "登記冊引用的檔案在 A1 上已和 sources 提交不同", ("phase-sync4",), check_registry_drift),
)


# --- state, notification ----------------------------------------------------------------------------------------

def run_checks(remote: Remote, now: datetime, previous: Mapping[str, Any], checks: Iterable[Check] = CHECKS,
               only: str | None = None) -> dict[str, dict[str, Any]]:
    items = dict(previous.get("items") or {})
    for check in checks:
        if only and check.id != only:
            continue
        old = dict(items.get(check.id) or {})
        try:
            result = check.run(Context(remote, now, old.get("extra") or {}))
            errors = 0
        except Exception as exc:  # noqa: BLE001 -- a broken check must show up as an error, never stop the others
            errors = int(old.get("consecutive_errors", 0)) + 1
            result = Result(ERROR, f"檢查本身出錯（連續 {errors} 次）：{type(exc).__name__}: {str(exc)[:140]}",
                            extra=old.get("extra") or {})
        entry = {"id": check.id, "title": check.title, "covers": list(check.covers), "state": result.state,
                 "summary": result.summary, "evidence": result.evidence, "needs_human": result.needs_human,
                 "closable": result.closable, "key": result.key, "checked_at": now.isoformat(timespec="seconds"),
                 "consecutive_errors": errors, "extra": result.extra,
                 "since": old.get("since") if old.get("state") == result.state and old.get("since") else now.isoformat(timespec="seconds"),
                 "notified_key": old.get("notified_key"), "acked_key": old.get("acked_key")}
        if result.state == WAITING:
            entry["notified_key"] = None        # the next time it is observed, tell again
        items[check.id] = entry
    return items


def notice_for(entry: Mapping[str, Any]) -> str | None:
    """The one message for this entry, or None when there is nothing new to say."""
    state, key = entry["state"], f"{entry['state']}:{entry.get('key', '')}"
    if state == ERROR and entry.get("consecutive_errors", 0) < ERRORS_BEFORE_NOTICE:
        return None
    if state not in (OBSERVED, FAILED, ERROR) or entry.get("notified_key") == key:
        return None
    covers = "、".join(entry["covers"])
    if state == OBSERVED:
        head = f"【觀察區】{covers}：" + ("條件已到，機器查證全部通過，可以結案" if entry.get("closable") and not entry.get("needs_human")
                                          else "條件已到，需要你確認")
        tail = ("我下次開工讀到後會附證據結案。" if entry.get("closable") and not entry.get("needs_human")
                else "確認後在對話裡告訴我，我再結案。")
    elif state == FAILED:
        head, tail = f"【觀察區失敗】{covers}：不符合預期", "我開工讀到後會重開這一項、加進等待決定並查原因。"
    else:
        head, tail = f"【觀察區】{covers}：自動檢查壞了", "我開工讀到後會修。"
    lines = [head, entry["summary"], *(f"・{e}" for e in entry.get("evidence", [])[:4]), tail]
    return "\n".join(lines)


def send_telegram(text: str, env: Mapping[str, str] = os.environ) -> bool:
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=20) as reply:
            return json.load(reply).get("ok") is True
    except Exception:  # noqa: BLE001 -- the token must never reach a log; a failed send is retried next run
        return False


def notify(items: dict[str, dict[str, Any]], send: Callable[[str], bool]) -> list[str]:
    sent = []
    for entry in items.values():
        text = notice_for(entry)
        if text and send(text):
            entry["notified_key"] = f"{entry['state']}:{entry.get('key', '')}"
            sent.append(entry["id"])
    return sent


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def report(state: Mapping[str, Any]) -> str:
    rows = [f"檢查時間：{state.get('checked_at', '（還沒跑過）')}"]
    for entry in (state.get("items") or {}).values():
        if entry["state"] == OBSERVED and entry.get("acked_key") == f"{entry['state']}:{entry.get('key', '')}":
            rows.append(f"✓ 已處理 {'／'.join(entry['covers'])}（{entry['title']}）")
            continue
        flag = {"observed": "✔ 已觀察到", "waiting": "… 等待中", "failed": "✘ 失敗", "error": "! 檢查壞了"}[entry["state"]]
        extra = "（可結案）" if entry.get("closable") and not entry.get("needs_human") and entry["state"] == OBSERVED else \
                "（需要你確認）" if entry.get("needs_human") and entry["state"] == OBSERVED else ""
        rows.append(f"{flag}{extra} {'／'.join(entry['covers'])}：{entry['summary']}")
        rows += [f"    {e}" for e in entry.get("evidence", [])[:4]] if entry["state"] != WAITING else []
    return "\n".join(rows)


def main(argv: list[str] | None = None, remote: Remote | None = None, send: Callable[[str], bool] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("run", "report", "ack"), nargs="?", default="run")
    parser.add_argument("check_id", nargs="?", help="ack: the check whose current result has been dealt with")
    parser.add_argument("--state", type=Path, default=Path(os.environ.get("OBSERVATION_WATCH_STATE", DEFAULT_STATE)))
    parser.add_argument("--dry-run", action="store_true", help="check, print, but do not send or save")
    parser.add_argument("--only", help="run only this check id")
    parser.add_argument("--json", action="store_true", help="report: print the state as JSON")
    args = parser.parse_args(argv)
    if args.command == "report":
        previous = load_state(args.state)
        print(json.dumps(previous, ensure_ascii=False, indent=2) if args.json else report(previous))
        return 0
    args.state.parent.mkdir(parents=True, exist_ok=True)
    # The state is read only after the lock is held: a run that waited behind another one must decide from what
    # that run saved, not from what it read earlier (otherwise a message already sent could be sent again).
    with open(args.state.with_suffix(".lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if args.command == "ack" else fcntl.LOCK_NB))
        except OSError:
            print("另一個偵測正在跑，這一輪略過。")
            return 0
        previous = load_state(args.state)
        if args.command == "ack":
            entry = (previous.get("items") or {}).get(args.check_id or "")
            if not entry:
                print(f"沒有這個檢查：{args.check_id}", file=sys.stderr)
                return 2
            entry["acked_key"] = f"{entry['state']}:{entry.get('key', '')}"
            save_state(args.state, previous)
            print(f"已標記處理完：{args.check_id}（{entry['acked_key']}）")
            return 0
        now = datetime.now(timezone.utc)
        state = {"checked_at": now.isoformat(timespec="seconds"),
                 "items": run_checks(remote or Remote(), now, previous, only=args.only)}
        if args.only:   # keep the other checks' stored results
            state["items"] = {**(previous.get("items") or {}), **state["items"]}
        if not args.dry_run:
            notify(state["items"], send or send_telegram)
            try:
                save_state(args.state, state)
            except OSError as exc:
                # Known limit: a message already sent is not remembered, so the next run may send it again.
                print(f"狀態檔存不進去（{exc}）：已發出的通知沒有記下來，下一輪可能重複發送。", file=sys.stderr)
                return 1
        print(report(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
