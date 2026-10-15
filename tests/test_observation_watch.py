"""f-43 observation watcher: each check sees its event, judges it mechanically, and tells once.

A fake ``Remote`` serves files and journals from dicts, so nothing here touches ssh, a host or Telegram.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("observation_watch", _ROOT / "scripts" / "observation_watch.py")
ow = importlib.util.module_from_spec(_spec)
sys.modules["observation_watch"] = ow     # dataclasses look the module up by name
_spec.loader.exec_module(ow)

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class FakeRemote(ow.Remote):
    def __init__(self, files=None, journals=None):
        super().__init__("unused")
        self.files = dict(files or {})
        self.journals = dict(journals or {})

    def read(self, host, path):
        if path not in ow.ALLOWED_PATHS:
            raise ow.RemoteError("whitelist: " + path)
        try:
            return self.files[(host, path)]
        except KeyError:
            raise ow.RemoteError(f"missing {host}:{path}") from None

    def journal(self, host, unit, since_utc):
        return self.journals.get((host, unit), "")


def put(remote, host, key, name, content, *, jsonl=False):
    text = "\n".join(json.dumps(r) for r in content) + "\n" if jsonl else json.dumps(content)
    remote.files[(host, ow.audit(key, name))] = text


def ctx(remote, previous=None):
    return ow.Context(remote, NOW, previous or {})


def hours_ago(n):
    return iso(NOW - timedelta(hours=n))


# --- read whitelist -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/etc/passwd", "/opt/my-crypto-bot/audit/../../../etc/shadow", "/opt/my-crypto-bot/audit/x.json; rm -rf /",
    "/opt/other-repo/audit/ledger_status.json", "/var/lib/ops-notify/../x.json", "/opt/my-crypto-bot/audit/a b.json",
    "/opt/my-crypto-bot/state/state.json", "/var/lib/portfolio-query/my-crypto-bot/current.json\n",
    # shaped like an allowed file but not one the checks read (review of #183: the whitelist must be the exact list)
    "/opt/my-crypto-bot/audit/private.json", "/opt/ed-seykota-systematic-trend-following/audit/error_requests.jsonl",
    "/var/lib/portfolio-query/seykota-btcusdt-4h/current.json", "/var/lib/ops-notify/other.json",
    "/opt/my-crypto-bot/audit/ledger_status.json\n",
])
def test_remote_refuses_paths_off_the_whitelist(path):
    with pytest.raises(ow.RemoteError):
        ow.Remote("k").read("a1", path)


@pytest.mark.parametrize("unit, since", [("ops-notify", "2026-10-13 04:28:00"), ("a b.service", "2026-10-13 04:28:00"),
                                          ("ops-notify.service", "yesterday"), ("ops-notify.service; id", "2026-10-13 04:28:00"),
                                          ("unrelated.service", "2026-10-13 04:28:00"), ("ssh.service", "2026-10-13 04:28:00"),
                                          ("ops-notify.service", "2026-10-13 04:28:00\n"), ("ops-notify.service", "2026-10-13 04:28:00 --vacuum-size=1")])
def test_remote_refuses_odd_journal_arguments(unit, since):
    with pytest.raises(ow.RemoteError):
        ow.Remote("k").journal("a1", unit, since)


def test_the_ssh_command_is_quoted_and_read_only(monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(ow.subprocess, "run", lambda argv, **kw: calls.append(argv) or Done())
    ow.Remote("/k").read("a1", "/opt/my-crypto-bot/audit/ledger_status.json")
    ow.Remote("/k").journal("a1", "ops-notify.service", "2026-10-13 04:28:00")
    ow.Remote("/k").read("dev", "/var/lib/ops-notify/state.json")
    assert calls[0][-1] == "sudo cat /opt/my-crypto-bot/audit/ledger_status.json"
    assert calls[1][-1] == "sudo journalctl -u ops-notify.service --since '2026-10-13 04:28:00 UTC' --utc --no-pager -q"
    assert calls[2] == ["sudo", "-n", "cat", "/var/lib/ops-notify/state.json"]
    assert "-o" in calls[0] and "BatchMode=yes" in calls[0]


# --- crypto flat (x1) ---------------------------------------------------------------------------------------------

def crypto_remote(*, snapshot_flat=True, positions=(), fetched=None, recon="RECONCILED"):
    r = FakeRemote()
    r.files[("a1", "/var/lib/portfolio-query/my-crypto-bot/current.json")] = json.dumps(
        {"position": {"status": "FLAT"} if snapshot_flat else {"status": "LONG"}})
    put(r, "a1", "mycrypto", "exchange_state.json", {"positions": list(positions), "fetch_status": {"complete": True, "errors": []},
                                                      "fetched_at": fetched or iso(NOW - timedelta(minutes=5)),
                                                      "balance": {"equity": 9.5}})
    put(r, "a1", "mycrypto", "ledger_status.json", {"value": recon})
    put(r, "a1", "mycrypto", "trading_ledger.jsonl",
        [{"event_type": "trade_close", "event_time": hours_ago(3), "event_id": "close-1"}], jsonl=True)
    return r


def test_crypto_flat_is_observed_when_every_source_agrees():
    result = ow.check_crypto_flat(ctx(crypto_remote()))
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable and result.key == "close-1"
    assert "x1" in result.summary


def test_crypto_with_a_position_keeps_waiting():
    r = crypto_remote(snapshot_flat=False, positions=[{"symbol": "BTC_USDT"}])
    assert ow.check_crypto_flat(ctx(r)).state == ow.WAITING


def test_crypto_snapshot_and_exchange_disagreeing_is_a_failure_not_a_pass():
    result = ow.check_crypto_flat(ctx(crypto_remote(snapshot_flat=True, positions=[{"symbol": "BTC_USDT"}])))
    assert result.state == ow.FAILED


def test_crypto_stale_exchange_read_or_unreconciled_ledger_does_not_count_as_flat():
    assert ow.check_crypto_flat(ctx(crypto_remote(fetched=hours_ago(3)))).state == ow.WAITING
    assert ow.check_crypto_flat(ctx(crypto_remote(recon="DIVERGED"))).state == ow.WAITING


# --- sheet tab names (f-26) -----------------------------------------------------------------------------------------

def trade(hours, kind="trade_close", **extra):
    return {"event_type": kind, "event_time": hours_ago(hours), "event_id": f"e{hours}{kind}", **extra}


def tabs_remote(*, trades=None, status=None):
    r = FakeRemote()
    for key in ow.REPOS:
        name = ow.SHEET_NAMES[key]
        put(r, "a1", key, "google_reconcile_status.json",
            (status or {}).get(key, {"sheet_name": name, "value": "RECONCILED", "checked_at": iso(NOW - timedelta(minutes=10)), "note": "ok"}))
        put(r, "a1", key, "trading_ledger.jsonl", (trades or {}).get(key, []), jsonl=True)
    return r


def test_tabs_all_four_with_new_trades_and_reconciled_is_closable():
    r = tabs_remote(trades={k: [trade(5)] for k in ow.REPOS})
    result = ow.check_sheet_tab_names(ctx(r))
    assert result.state == ow.OBSERVED and result.closable and not result.needs_human


def test_tabs_partial_progress_is_reported_but_keeps_waiting():
    r = tabs_remote(trades={"mycrypto": [trade(5)], "momentum": [trade(4)]})
    result = ow.check_sheet_tab_names(ctx(r))
    assert result.state == ow.WAITING and "加密策略" in result.summary and "動能策略" in result.summary and "競賽策略" in result.summary


def test_tabs_old_trades_before_the_switch_do_not_count():
    old = {"event_type": "trade_close", "event_time": "2026-10-01T00:00:00+00:00"}
    assert ow.check_sheet_tab_names(ctx(tabs_remote(trades={k: [old] for k in ow.REPOS}))).state == ow.WAITING


def test_tabs_wrong_sheet_name_fails_at_once():
    bad = {"mycrypto": {"sheet_name": "my-crypto-bot", "value": "RECONCILED", "checked_at": iso(NOW)}}
    result = ow.check_sheet_tab_names(ctx(tabs_remote(status=bad)))
    assert result.state == ow.FAILED and "加密策略" in result.summary


def test_tabs_diverged_is_tolerated_for_two_hours_then_fails():
    div = {"momentum": {"sheet_name": "動能策略", "value": "DIVERGED", "checked_at": iso(NOW), "note": "x"}}
    assert ow.check_sheet_tab_names(ctx(tabs_remote(trades={"momentum": [trade(1)]}, status=div))).state == ow.WAITING
    assert ow.check_sheet_tab_names(ctx(tabs_remote(trades={"momentum": [trade(5)]}, status=div))).state == ow.FAILED


def test_tabs_demo_trades_are_not_real_trades():
    r = tabs_remote(trades={k: [trade(5, execution_mode="DEMO")] for k in ow.REPOS})
    assert ow.check_sheet_tab_names(ctx(r)).state == ow.WAITING


# --- competition fill (e-2), trend add-on (e-5), dev entry (f-7) ----------------------------------------------------------

def test_competition_fill_waits_then_closes_when_the_sheet_agrees():
    r = tabs_remote()
    assert ow.check_competition_fill(ctx(r)).state == ow.WAITING
    put(r, "a1", "btc-competition", "trading_ledger.jsonl", [trade(5, "spot_fill", execution_mode="LIVE")], jsonl=True)
    result = ow.check_competition_fill(ctx(r))
    assert result.state == ow.OBSERVED and result.closable


def test_trend_addon_needs_a_human_to_look_at_the_sheet():
    r = tabs_remote()
    put(r, "a1", "seykota", "trading_ledger.jsonl",
        [trade(9, "trade_open", trade_id="T1"), trade(5, "trade_open", trade_id="T1"), trade(4, "trade_open", trade_id="T2")], jsonl=True)
    result = ow.check_trend_addon(ctx(r))
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable and "T1" in result.evidence[0]


def test_trend_without_an_add_keeps_waiting():
    r = tabs_remote()
    put(r, "a1", "seykota", "trading_ledger.jsonl", [trade(9, "trade_open", trade_id="T1")], jsonl=True)
    assert ow.check_trend_addon(ctx(r)).state == ow.WAITING


def test_dev_entry_must_come_from_a_signal_not_a_manual_test():
    r = FakeRemote()
    put(r, "dev", "seykota", "google_reconcile_status.json", {"value": "RECONCILED", "note": "ok", "checked_at": iso(NOW - timedelta(minutes=10))})
    put(r, "dev", "seykota", "trading_ledger.jsonl", [trade(6, "trade_open", source="add", trade_id="T")], jsonl=True)
    assert ow.check_dev_trend_entry(ctx(r)).state == ow.WAITING
    put(r, "dev", "seykota", "trading_ledger.jsonl", [trade(6, "trade_open", source="entry_signal", trade_id="T")], jsonl=True)
    result = ow.check_dev_trend_entry(ctx(r))
    assert result.state == ow.OBSERVED and result.closable


# --- status alerts (f-23 / f-40 / f-41) and reminders (f-39) --------------------------------------------------------

def line(notices, attempted, sent, failures=0, stamp="Oct 14 03:10:01"):
    return (f"{stamp} fleet ops-notify[1]: 2026-10-14 03:10:01,000 INFO ops_notify.watch ops_notify_watch readings=20 "
            f"notices={notices} attempted={attempted} sent={sent} consecutive_send_failures={failures} state_written=True")


def journal_remote(*lines, state=None):
    r = FakeRemote(journals={("a1", "ops-notify.service"): "\n".join(lines)})
    r.files[("a1", "/var/lib/ops-notify/state.json")] = json.dumps(state if state is not None else {"_export": {}})
    return r


def test_status_alerts_wait_while_every_poll_is_quiet():
    assert ow.check_status_alerts(ctx(journal_remote(line(0, 0, 0), line(0, 0, 0)))).state == ow.WAITING


def test_a_delivered_real_alert_is_observed_but_still_needs_the_phone():
    state = {"momentum:ledger": {"notified_at": "2026-10-14T03:10:02+00:00", "notified_severity": "alert"}, "_export": {}}
    result = ow.check_status_alerts(ctx(journal_remote(line(0, 0, 0), line(1, 1, 1), state=state)))
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable
    assert result.key == "Oct 14 03:10:01"
    # three stages kept apart: the event, the first message's delivery, and the second message that is NOT claimed delivered
    assert result.evidence[0].startswith("事件：") and result.evidence[1].startswith("第一則：") and "momentum:ledger@" in result.evidence[1]
    assert result.evidence[2].startswith("第二則：") and "沒有送達證據" in result.evidence[2]


def test_an_undelivered_alert_or_send_warning_is_a_failure():
    assert ow.check_status_alerts(ctx(journal_remote(line(1, 1, 0)))).state == ow.FAILED
    assert ow.check_status_alerts(ctx(journal_remote(line(0, 0, 0, failures=2)))).state == ow.FAILED
    assert ow.check_status_alerts(ctx(journal_remote(line(1, 1, 1), "WARNING status_ai_send_failed key=x error=Timeout"))).state == ow.FAILED


def reminder_remote(reminders, *journal):
    r = FakeRemote(journals={("a1", "ops-notify.service"): "\n".join(journal)})
    r.files[("a1", "/var/lib/ops-notify/state.json")] = json.dumps({"_reminders": reminders})
    return r


def test_reminders_wait_until_one_has_gone_out_then_remember_it_ended():
    assert ow.check_reminders(ctx(reminder_remote({}))).state == ow.WAITING
    first = ow.check_reminders(ctx(reminder_remote({"momentum:ledger": {"since": "t", "count": 2, "last_at": "t2"}})))
    assert first.state == ow.OBSERVED and first.needs_human and "還在提醒" in first.evidence[0]
    # the alert recovers: the entry disappears, the watcher still remembers it sent 2
    ended = ow.check_reminders(ow.Context(reminder_remote({}), NOW, first.extra))
    assert ended.state == ow.OBSERVED and "已恢復並停止" in ended.evidence[0] and ended.key.endswith(":ended")


def test_a_reminder_send_failure_is_a_failure():
    result = ow.check_reminders(ctx(reminder_remote({}, "WARNING reminder_send_failed channel=telegram error=Timeout")))
    assert result.state == ow.FAILED


# --- event-log checks (f-30, g2, f-35/f-37) -------------------------------------------------------------------------------

def event(code, tier="R3", hours=3, test=False, event_id=None):
    row = {"code": code, "risk_tier": tier, "recorded_at": hours_ago(hours), "event_id": event_id or f"{code}-{hours}"}
    if test:
        row["details"] = {"test": True}
    return row


def events_remote(delivered=None, ai_pending=None, baseline=None, **by_strategy):
    r = FakeRemote()
    for key in ("seykota", "momentum", "btc-competition"):
        put(r, "a1", key, "fleet_event_log.jsonl", by_strategy.get(key, []), jsonl=True)
    export = {key: {"baseline_at": (baseline or {}).get(key, "2026-09-23T19:10:05+00:00"),
                    "delivered": {e: iso(NOW - timedelta(hours=1)) for e in (delivered or {}).get(key, [])},
                    **({"ai_pending": ai_pending[key]} if ai_pending and key in ai_pending else {})}
              for key in ("seykota", "momentum", "btc-competition")}
    r.files[("a1", "/var/lib/ops-notify/state.json")] = json.dumps({"_export": export})
    return r


def test_controlled_test_events_never_count():
    r = events_remote(momentum=[event("LEDGER_PENDING_EXPIRED", test=True), event("PROTECTION_UNVERIFIED", test=True)])
    assert ow.check_pending_expired(ctx(r)).state == ow.WAITING
    assert ow.check_safe_halt_notice(ctx(r)).state == ow.WAITING


def test_a_logged_event_is_not_a_delivered_notice():
    """Review of #183: an event in the log proves the event, not that ops-notify sent it."""
    e = event("LEDGER_PENDING_EXPIRED", hours=3, event_id="p1")
    assert ow.check_pending_expired(ctx(events_remote(momentum=[e]))).state == ow.FAILED          # 3 h old, never delivered
    young = event("LEDGER_PENDING_EXPIRED", hours=0, event_id="p2")
    assert ow.check_pending_expired(ctx(events_remote(momentum=[young]))).state == ow.WAITING     # give ops-notify its poll
    done = ow.check_pending_expired(ctx(events_remote(momentum=[e], delivered={"momentum": ["p1"]})))
    assert done.state == ow.OBSERVED and done.needs_human and not done.closable
    assert "第一則已送出" in done.evidence[0] and "送達要你確認" in done.evidence[0]


def test_a_delivered_mark_from_the_first_baseline_is_not_proof_of_a_send():
    """Review round 2 of #183: when ops-notify first sees a target it marks the notices that already exist as 'delivered'
    WITHOUT sending them.  An event older than that baseline must not be reported as 'first message sent'."""
    e = event("LEDGER_PENDING_EXPIRED", hours=3, event_id="old1")
    after_baseline = events_remote(momentum=[e], delivered={"momentum": ["old1"]},
                                   baseline={"momentum": iso(NOW - timedelta(hours=1))})        # baseline made AFTER the event
    result = ow.check_pending_expired(ctx(after_baseline))
    assert result.state == ow.OBSERVED and result.needs_human and result.key.startswith("unproven:")
    assert "無法證明有送出" in result.evidence[0] and "第一則已送出" not in result.evidence[0]
    assert "請你確認有沒有收到" in result.summary
    # the same event with the baseline made BEFORE it is a genuine delivery
    before = events_remote(momentum=[e], delivered={"momentum": ["old1"]}, baseline={"momentum": iso(NOW - timedelta(hours=5))})
    assert "第一則已送出" in ow.check_pending_expired(ctx(before)).evidence[0]
    # no baseline recorded at all: cannot tell, so it is not claimed either
    no_baseline = events_remote(momentum=[e], delivered={"momentum": ["old1"]}, baseline={"momentum": None})
    assert "無法證明有送出" in ow.check_pending_expired(ctx(no_baseline)).evidence[0]


def test_a_second_message_that_stays_owed_for_over_70_minutes_is_a_failure():
    e = event("VERIFIED_CLOSE_REPAIR_RECURRING", hours=5, event_id="r1")
    owed_long = {"momentum": {"r1": hours_ago(3)}}
    assert ow.check_repair_recurring(ctx(events_remote(momentum=[e], delivered={"momentum": ["r1"]}, ai_pending=owed_long))).state == ow.FAILED
    owed_now = {"momentum": {"r1": iso(NOW - timedelta(minutes=10))}}
    still = ow.check_repair_recurring(ctx(events_remote(momentum=[e], delivered={"momentum": ["r1"]}, ai_pending=owed_now)))
    assert still.state == ow.OBSERVED and "第二則還在重試" in still.evidence[0]


def test_safe_halt_notice_ignores_the_other_two_codes_and_lower_tiers():
    r = events_remote(momentum=[event("LEDGER_PENDING_EXPIRED"), event("VERIFIED_CLOSE_REPAIR_RECURRING"), event("X", tier="R2")])
    assert ow.check_safe_halt_notice(ctx(r)).state == ow.WAITING
    e = event("ORDER_STATUS_UNKNOWN", event_id="b1")
    r = events_remote(delivered={"btc-competition": ["b1"]}, **{"btc-competition": [e]})
    result = ow.check_safe_halt_notice(ctx(r))
    assert result.state == ow.OBSERVED and result.needs_human and "競賽策略" in result.evidence[0]


# --- state and notification --------------------------------------------------------------------------------------------

def one_check(result_for):
    calls = {"n": 0}

    def run(_ctx):
        calls["n"] += 1
        value = result_for(calls["n"])
        if isinstance(value, Exception):
            raise value
        return value

    return ow.Check("demo", "示範", ("f-x",), run)


def test_an_observation_is_announced_once_and_again_only_after_it_went_back_to_waiting():
    seq = [ow.Result(ow.WAITING, "w"), ow.Result(ow.OBSERVED, "o", ["e"], closable=True, key="k"), ow.Result(ow.OBSERVED, "o", ["e"], closable=True, key="k"),
           ow.Result(ow.WAITING, "w"), ow.Result(ow.OBSERVED, "o", ["e"], closable=True, key="k")]
    check, sent, state = one_check(lambda n: seq[n - 1]), [], {}
    for _ in seq:
        state = {"items": ow.run_checks(ow.Remote("k"), NOW, state, [check])}
        ow.notify(state["items"], lambda text: sent.append(text) or True)
    assert len(sent) == 2 and all("可以結案" in text and "f-x" in text for text in sent)


def test_a_failed_send_is_retried_on_the_next_run():
    check = one_check(lambda n: ow.Result(ow.FAILED, "不符", key="k"))
    state = {"items": ow.run_checks(ow.Remote("k"), NOW, {}, [check])}
    assert ow.notify(state["items"], lambda t: False) == []
    state = {"items": ow.run_checks(ow.Remote("k"), NOW, state, [check])}
    assert ow.notify(state["items"], lambda t: True) == ["demo"]


def test_human_confirmation_is_asked_for_not_assumed():
    entry = ow.run_checks(ow.Remote("k"), NOW, {}, [one_check(lambda n: ow.Result(ow.OBSERVED, "到了", needs_human=True, key="k"))])["demo"]
    text = ow.notice_for(entry)
    assert "需要你確認" in text and "可以結案" not in text


def test_a_broken_check_is_an_error_and_only_announced_after_three_in_a_row():
    check = one_check(lambda n: RuntimeError("boom"))
    state, sent = {}, []
    for _ in range(4):
        state = {"items": ow.run_checks(ow.Remote("k"), NOW, state, [check])}
        ow.notify(state["items"], lambda t: sent.append(t) or True)
    assert state["items"]["demo"]["consecutive_errors"] == 4 and len(sent) == 1 and "壞了" in sent[0]


def test_one_broken_check_does_not_stop_the_others():
    broken = ow.Check("broken", "壞的", ("f-b",), lambda c: (_ for _ in ()).throw(ow.RemoteError("ssh down")))
    fine = ow.Check("fine", "好的", ("f-f",), lambda c: ow.Result(ow.WAITING, "等"))
    items = ow.run_checks(ow.Remote("k"), NOW, {}, [broken, fine])
    assert items["broken"]["state"] == ow.ERROR and items["fine"]["state"] == ow.WAITING


def test_the_telegram_token_is_never_sent_without_both_variables():
    assert ow.send_telegram("x", {}) is False and ow.send_telegram("x", {"TELEGRAM_BOT_TOKEN": "t"}) is False


# --- command line -----------------------------------------------------------------------------------------------------

def test_run_report_and_ack_round_trip(tmp_path, capsys):
    r = crypto_remote(fetched=iso(datetime.now(timezone.utc) - timedelta(minutes=5)))     # main() uses the real clock
    state, sent = tmp_path / "state.json", []
    only = ["--state", str(state), "--only", "crypto-flat"]
    assert ow.main(["run", *only], remote=r, send=lambda t: sent.append(t) or True) == 0
    assert len(sent) == 1 and "需要你確認" in sent[0]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["items"]["crypto-flat"]["state"] == ow.OBSERVED and saved["items"]["crypto-flat"]["notified_key"]
    assert ow.main(["run", *only], remote=r, send=lambda t: sent.append(t) or True) == 0 and len(sent) == 1
    capsys.readouterr()
    assert ow.main(["report", "--state", str(state)]) == 0
    assert "需要你確認" in capsys.readouterr().out
    assert ow.main(["ack", "crypto-flat", "--state", str(state)]) == 0
    capsys.readouterr()
    ow.main(["report", "--state", str(state)])
    assert "已處理" in capsys.readouterr().out
    assert ow.main(["ack", "nope", "--state", str(state)]) == 2


def test_dry_run_neither_sends_nor_saves(tmp_path):
    state, sent = tmp_path / "state.json", []
    ow.main(["run", "--dry-run", "--state", str(state), "--only", "crypto-flat"],
            remote=crypto_remote(fetched=iso(datetime.now(timezone.utc) - timedelta(minutes=5))), send=lambda t: sent.append(t) or True)
    assert sent == [] and not state.exists()


def test_every_check_has_a_unique_id_and_names_the_items_it_covers():
    ids = [c.id for c in ow.CHECKS]
    assert len(ids) == len(set(ids))
    assert all(c.covers and c.title for c in ow.CHECKS)
    covered = {i for c in ow.CHECKS for i in c.covers}
    assert {"phase-sync1", "phase-sync4", "f-23", "f-26", "f-30", "f-35", "f-37", "f-39", "f-40", "f-41", "e-2", "e-5", "f-7", "phase-g2", "phase-x1"} <= covered


# --- deployment files ----------------------------------------------------------------------------------------------

def test_the_service_has_no_secret_and_the_installer_never_prints_one():
    service = (_ROOT / "deploy" / "observation-watch" / "observation-watch.service").read_text(encoding="utf-8")
    installer = (_ROOT / "deploy" / "observation-watch" / "install.sh").read_text(encoding="utf-8")
    timer = (_ROOT / "deploy" / "observation-watch" / "observation-watch.timer").read_text(encoding="utf-8")
    assert "EnvironmentFile=/etc/observation-watch/watch.env" in service and "TELEGRAM" not in service
    assert "ExecStart=/usr/bin/python3 /opt/observation-watch/observation_watch.py run" in service
    assert "NoNewPrivileges=true" not in service          # sudo needs it; the reason is written next to the unit
    assert "OnCalendar=*:0/30" in timer
    # the token is copied by grep into a root-only file; no echo/cat of its value anywhere
    assert "umask 077" in installer and "chmod 600 /etc/observation-watch/watch.env" in installer
    assert not any(w in installer for w in ("echo $TELEGRAM", 'echo "$TELEGRAM', "cat /etc/ops-notify"))


# --- the reconcile must come AFTER the trade's grace period (review of #183, BLOCK-01/02) -------------------------------

def _status(checked_minutes_ago, value="RECONCILED", name="動能策略"):
    return {"sheet_name": name, "value": value, "checked_at": iso(NOW - timedelta(minutes=checked_minutes_ago)), "note": "ok"}


@pytest.mark.parametrize("trade_minutes_ago, checked_minutes_ago", [
    (30, 5),      # the reconcile ran 25 minutes AFTER the trade, still inside its 60-minute grace: proves nothing yet
    (30, 40),     # a RECONCILED from before the trade
])
def test_tabs_a_reconcile_that_predates_the_grace_of_the_trade_is_not_evidence(trade_minutes_ago, checked_minutes_ago):
    r = tabs_remote(trades={"momentum": [{"event_type": "trade_close", "event_time": iso(NOW - timedelta(minutes=trade_minutes_ago))}]},
                    status={"momentum": _status(checked_minutes_ago)})
    out = ow.check_sheet_tab_names(ctx(r))
    assert out.state == ow.WAITING and not out.summary.startswith("已確認：動能策略")
    assert not any(line.startswith("動能策略") for line in out.evidence)        # no 'confirmed' line was written for it


def test_tabs_the_example_from_the_review_does_not_close():
    # 12:00 reconcile ok; 12:10 a trade; 12:15 the watcher runs: the old RECONCILED must not count for the new trade
    now = datetime(2026, 10, 14, 12, 15, tzinfo=timezone.utc)
    r = FakeRemote()
    for key in ow.REPOS:
        trade_time = datetime(2026, 10, 14, 12, 10, tzinfo=timezone.utc)
        put(r, "a1", key, "trading_ledger.jsonl", [{"event_type": "trade_close", "event_time": iso(trade_time)}], jsonl=True)
        put(r, "a1", key, "google_reconcile_status.json",
            {"sheet_name": ow.SHEET_NAMES[key], "value": "RECONCILED", "checked_at": "2026-10-14T12:00:00+00:00", "note": "ok"})
    result = ow.check_sheet_tab_names(ow.Context(r, now, {}))
    assert result.state == ow.WAITING and not result.closable


def test_tabs_closes_only_after_a_reconcile_that_ran_past_the_grace_of_the_newest_trade():
    t = NOW - timedelta(hours=3)
    good = {"momentum": _status(30), "seykota": _status(30, name="趨勢策略"), "mycrypto": _status(30, name="加密策略"),
            "btc-competition": _status(30, name="競賽策略")}
    r = tabs_remote(trades={k: [{"event_type": "trade_close", "event_time": iso(t)}] for k in ow.REPOS}, status=good)
    assert ow.check_sheet_tab_names(ctx(r)).closable
    assert ow.reconcile_covers(_status(30), t, NOW) == "covered"
    assert ow.reconcile_covers(_status(30, "DIVERGED"), t, NOW) == "diverged"
    assert ow.reconcile_covers(_status(30, "UNKNOWN"), t, NOW) == "pending"
    assert ow.reconcile_covers({"value": "RECONCILED"}, t, NOW) == "pending"                    # no checked_at
    assert ow.reconcile_covers(_status(300), t, NOW) == "pending"                               # stale (older than 90 min)
    assert ow.reconcile_covers(_status(30), NOW - timedelta(minutes=50), NOW) == "pending"      # trade still inside its grace


def test_competition_and_dev_entry_also_wait_for_a_reconcile_after_the_grace():
    r = tabs_remote()
    put(r, "a1", "btc-competition", "trading_ledger.jsonl", [trade(0, "spot_fill", execution_mode="LIVE")], jsonl=True)
    put(r, "a1", "btc-competition", "google_reconcile_status.json", _status(5, name="競賽策略"))
    assert ow.check_competition_fill(ctx(r)).state == ow.WAITING                                # RECONCILED, but older than the grace
    d = FakeRemote()
    put(d, "dev", "seykota", "trading_ledger.jsonl", [trade(0, "trade_open", source="entry_signal", trade_id="T")], jsonl=True)
    put(d, "dev", "seykota", "google_reconcile_status.json", _status(5, name="趨勢策略"))
    assert ow.check_dev_trend_entry(ctx(d)).state == ow.WAITING


# --- one run at a time; a message that was sent but not remembered (review of #183) -----------------------------------------

def test_a_second_run_while_one_is_running_does_nothing(tmp_path, capsys):
    import fcntl
    state = tmp_path / "state.json"
    with open(state.with_suffix(".lock"), "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sent = []
        assert ow.main(["run", "--state", str(state), "--only", "crypto-flat"], remote=crypto_remote(), send=lambda t: sent.append(t) or True) == 0
    assert sent == [] and not state.exists() and "另一個偵測正在跑" in capsys.readouterr().out


def test_a_state_file_that_cannot_be_saved_is_reported_and_the_repeat_is_documented(tmp_path, monkeypatch, capsys):
    state, sent = tmp_path / "state.json", []
    r = crypto_remote(fetched=iso(datetime.now(timezone.utc) - timedelta(minutes=5)))
    monkeypatch.setattr(ow, "save_state", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    code = ow.main(["run", "--state", str(state), "--only", "crypto-flat"], remote=r, send=lambda t: sent.append(t) or True)
    assert code == 1 and len(sent) == 1 and "下一輪可能重複發送" in capsys.readouterr().err


# --- the state is read only after the lock is held (review of #183 round 3) ----------------------------------------------

@pytest.mark.parametrize("argv", [["run", "--only", "crypto-flat"], ["ack", "crypto-flat"]])
def test_the_state_is_loaded_while_the_lock_is_held(tmp_path, monkeypatch, argv):
    import fcntl
    state = tmp_path / "state.json"
    ow.save_state(state, {"items": {"crypto-flat": {"state": ow.WAITING, "key": "k"}}})
    seen = []
    real_load = ow.load_state

    def probe(path):
        # if the lock were free here, another run could save between this read and our own lock
        with open(state.with_suffix(".lock"), "w") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append("lock was free")
            except OSError:
                seen.append("lock held")
        return real_load(path)

    monkeypatch.setattr(ow, "load_state", probe)
    ow.main([*argv, "--state", str(state)], remote=crypto_remote(), send=lambda t: True)
    assert seen == ["lock held"]


def test_a_run_that_waited_behind_another_decides_from_what_that_one_saved(tmp_path):
    # ack blocks on the lock; the holder saves a newer state before letting go; ack must act on the newer one
    import fcntl, threading, time
    state = tmp_path / "state.json"
    ow.save_state(state, {"items": {"crypto-flat": {"state": ow.WAITING, "key": "old"}}})
    held = open(state.with_suffix(".lock"), "w")
    fcntl.flock(held, fcntl.LOCK_EX)
    codes = []
    t = threading.Thread(target=lambda: codes.append(ow.main(["ack", "crypto-flat", "--state", str(state)])))
    t.start()
    time.sleep(0.3)                                    # ack is now waiting for the lock
    ow.save_state(state, {"items": {"crypto-flat": {"state": ow.WAITING, "key": "new"}}})
    fcntl.flock(held, fcntl.LOCK_UN)
    held.close()
    t.join(5)
    assert codes == [0] and ow.load_state(state)["items"]["crypto-flat"]["acked_key"] == f"{ow.WAITING}:new"


# --- registry cells waiting for a deployment (phase-sync1) ---------------------------------------------------------

import subprocess


def _git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _commit(repo, name):
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _registry(awaits):
    """A registry with one pending capability cell per (project, commit) in ``awaits`` and one rule cell."""
    return {"capabilities": [{"id": "x.cap", "status": {p: {"state": "pending", "phase": "p", "reason": "r", "awaits_commit": c}
                                                       for p, c in awaits.items()}}],
            "catalog": [{"code": "MYC.X", "behaviour": {"mycrypto": {"state": "done", "evidence": "e"}},
                         "emits_event": {"mycrypto": {"state": "pending", "phase": "p", "reason": "r",
                                                      "awaits_commit": awaits.get("mycrypto", "")}}}]}


class GitHeads(FakeRemote):
    def __init__(self, heads):
        super().__init__()
        self.heads = heads

    def git_head(self, host, key):
        return self.heads[key]


@pytest.fixture()
def repos(tmp_path, monkeypatch):
    root = tmp_path / "home"
    for name in ("trade-alerts", ow.REPOS["mycrypto"], ow.REPOS["seykota"]):
        (root / name).mkdir(parents=True)
        _git(root / name, "init", "-q")
    monkeypatch.setenv("OBSERVATION_WATCH_REPOS_ROOT", str(root))
    monkeypatch.setenv("OBSERVATION_WATCH_REGISTRY_REF", "HEAD")
    return root


def _publish_registry(root, registry):
    ta = root / "trade-alerts"
    target = ta / ow.REGISTRY_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(registry), encoding="utf-8")
    _git(ta, "add", "-A")
    _git(ta, "commit", "-q", "-m", "registry")


def test_a_cell_whose_awaited_commit_is_running_on_a1_is_flagged(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1, c2 = _commit(myc, "a"), _commit(myc, "b")
    c3 = _commit(myc, "c")
    _publish_registry(repos, _registry({"mycrypto": c2}))
    result = ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c3})))      # A1 is past the awaited commit
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable
    assert "2 格" in result.summary and any("x.cap / mycrypto" in e for e in result.evidence)
    assert any("MYC.X emits_event" in e for e in result.evidence) and c2[:7] in result.evidence[0]
    assert ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c2}))).state == ow.OBSERVED     # exactly the awaited commit
    assert c1 != c2


def test_a_cell_whose_awaited_commit_is_not_on_a1_yet_keeps_waiting(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1, c2 = _commit(myc, "a"), _commit(myc, "b")
    _publish_registry(repos, _registry({"mycrypto": c2}))
    result = ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c1})))      # A1 is one commit behind
    assert result.state == ow.WAITING and not result.needs_human and "2 格在等部署" in result.summary


def test_a_commit_on_another_branch_is_not_deployed(repos):
    """Ancestry, not the commit's existence: A1 at c1 does not contain a side branch's commit."""
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _commit(myc, "a")
    _git(myc, "checkout", "-q", "-b", "side")
    side = _commit(myc, "s")
    _git(myc, "checkout", "-q", "-")
    _publish_registry(repos, _registry({"mycrypto": side}))
    assert ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c1}))).state == ow.WAITING


def test_no_cell_names_a_commit_means_nothing_to_compare(repos):
    _commit(repos / ow.REPOS["mycrypto"], "a")
    _publish_registry(repos, {"capabilities": [], "catalog": []})
    result = ow.check_registry_awaits(ctx(GitHeads({})))
    assert result.state == ow.WAITING and "沒有東西要比對" in result.summary


def test_an_unknown_awaited_commit_is_an_error_not_a_pass(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _commit(myc, "a")
    _publish_registry(repos, _registry({"mycrypto": "deadbeef" * 5}))
    with pytest.raises(ow.RemoteError, match="找不到"):
        ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c1})))
    state = ow.run_checks(GitHeads({"mycrypto": c1}), NOW, {}, checks=[c for c in ow.CHECKS if c.id == "registry-awaits"])
    assert state["registry-awaits"]["state"] == ow.ERROR      # the loop turns it into an error entry that is announced after repeats


def test_a_missing_registry_ref_is_an_error(repos, monkeypatch):
    monkeypatch.setenv("OBSERVATION_WATCH_REGISTRY_REF", "no-such-ref")
    _commit(repos / "trade-alerts", "a")
    with pytest.raises(ow.RemoteError, match="cannot read the registry"):
        ow.check_registry_awaits(ctx(GitHeads({})))


def test_awaiting_cells_only_counts_pending_cells_with_a_commit():
    reg = _registry({"mycrypto": "abc1234"})
    reg["capabilities"].append({"id": "y", "status": {"seykota": {"state": "pending", "phase": "p", "reason": "r"},
                                                      "momentum": {"state": "done", "evidence": "e"}}})
    labels = [c[0] for c in ow.awaiting_cells(reg)]
    assert labels == ["能力 x.cap / mycrypto", "規則 MYC.X emits_event / mycrypto"]


def test_git_head_asks_only_for_rev_parse_in_the_listed_a1_clones(monkeypatch):
    seen = []
    remote = ow.Remote("k")
    monkeypatch.setattr(remote, "_run", lambda host, words: seen.append((host, words)) or ("a" * 40 + "\n"))
    assert remote.git_head("a1", "mycrypto") == "a" * 40
    host, words = seen[0]
    assert host == "a1" and words[-2:] == ["rev-parse", "HEAD"] and words[words.index("-C") + 1] == "/home/ubuntu/src/my-crypto-bot"
    for bad_host, bad_key in (("dev", "mycrypto"), ("a1", "ops-notify"), ("a1", "../../etc"), ("a1", "my-crypto-bot")):
        with pytest.raises(ow.RemoteError):
            remote.git_head(bad_host, bad_key)
    assert len(seen) == 1                                                                   # nothing reached the shell for the refused ones
    monkeypatch.setattr(remote, "_run", lambda host, words: "not a sha; rm -rf /\n")
    with pytest.raises(ow.RemoteError, match="unexpected"):
        remote.git_head("a1", "mycrypto")


def test_a_failed_fetch_of_the_registry_clone_is_an_error_not_an_empty_answer(repos):
    """Review of #193: with a stale origin/main (no awaiting cells) and the fetch failing, the check must not say
    "nothing to compare"."""
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _commit(myc, "a")
    _publish_registry(repos, {"capabilities": [], "catalog": []})           # the stale copy: nothing awaits
    _git(repos / "trade-alerts", "remote", "add", "origin", str(repos / "no-such-remote"))   # a fetch from it fails
    with pytest.raises(ow.RemoteError, match="cannot refresh"):
        ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c1})))
    state = ow.run_checks(GitHeads({"mycrypto": c1}), NOW, {}, checks=[c for c in ow.CHECKS if c.id == "registry-awaits"])
    assert state["registry-awaits"]["state"] == ow.ERROR


def test_a_failed_fetch_of_a_strategy_clone_is_not_fatal_when_the_commit_is_known(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1, c2 = _commit(myc, "a"), _commit(myc, "b")
    _publish_registry(repos, _registry({"mycrypto": c2}))
    _git(myc, "remote", "add", "origin", str(repos / "no-such-remote"))
    assert ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c2}))).state == ow.OBSERVED
    assert ow._refresh(myc) is False and ow._refresh(repos / "trade-alerts") is None


def test_observed_also_lists_the_cells_still_waiting(repos):
    myc, sey = repos / ow.REPOS["mycrypto"], repos / ow.REPOS["seykota"]
    c1 = _commit(myc, "a")
    s1, s2 = _commit(sey, "s"), _commit(sey, "t")
    reg = _registry({"mycrypto": c1})
    reg["capabilities"][0]["status"]["seykota"] = {"state": "pending", "phase": "p", "reason": "r", "awaits_commit": s2}
    _publish_registry(repos, reg)
    result = ow.check_registry_awaits(ctx(GitHeads({"mycrypto": c1, "seykota": s1})))   # seykota's awaited commit is not on A1
    assert result.state == ow.OBSERVED
    assert any(e.startswith("（仍在等）") and "seykota" in e for e in result.evidence)
    assert not any("seykota" in e for e in result.evidence if not e.startswith("（仍在等）"))


# --- registry cells whose cited files changed on A1 (phase-sync4) --------------------------------------------------

def _drift_registry(src_commit, cites):
    """A registry whose mycrypto sources is ``src_commit`` and with one done capability cell citing ``cites``."""
    return {"sources": {"mycrypto": {"commit": src_commit}},
            "capabilities": [{"id": "x.cap", "status": {"mycrypto": {"state": "done", "evidence": "；".join(f"{c}:12 x" for c in cites)},
                                                      "seykota": {"state": "pending", "phase": "p", "reason": "src/never.py:1 is ignored"}}}],
            "catalog": [{"code": "MYC.X", "behaviour": {"mycrypto": {"state": "done", "evidence": "src/b.py:3 y"}},
                         "emits_event": {"mycrypto": {"state": "pending", "phase": "p", "reason": "src/c.py:3 ignored"}}}]}


class Blobs(FakeRemote):
    def __init__(self, blobs):
        super().__init__()
        self.blobs, self.asked = blobs, []

    def git_blobs(self, host, key, paths):
        self.asked.append((host, key, list(paths)))
        return {p: self.blobs[p] for p in paths if p in self.blobs}


def _write(repo, files):
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    return _git(repo, "rev-parse", "HEAD")


def _blob(repo, commit, path):
    return _git(repo, "rev-parse", f"{commit}:{path}")


def test_cited_files_are_the_files_of_done_cells_only():
    reg = _drift_registry("abc1234", ["src/a.py"])
    found = ow.cited_files(reg)
    assert set(found) == {"mycrypto"}                                        # the pending seykota cell and pending rule aspect add nothing
    assert set(found["mycrypto"]) == {"src/a.py", "src/b.py"}
    assert found["mycrypto"]["src/a.py"] == ["能力 x.cap"] and found["mycrypto"]["src/b.py"] == ["規則 MYC.X behaviour"]


def test_a_cited_file_that_differs_on_a1_from_the_sources_commit_is_flagged(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _write(myc, {"src/a.py": "one", "src/b.py": "stable"})
    _publish_registry(repos, _drift_registry(c1, ["src/a.py"]))
    a_old, b = _blob(myc, c1, "src/a.py"), _blob(myc, c1, "src/b.py")
    same = Blobs({"src/a.py": a_old, "src/b.py": b})
    assert ow.check_registry_drift(ctx(same)).state == ow.WAITING and "2 個檔案" in ow.check_registry_drift(ctx(same)).summary
    changed = Blobs({"src/a.py": "f" * 40, "src/b.py": b})                       # A1 has another version of a.py
    result = ow.check_registry_drift(ctx(changed))
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable
    assert len(result.evidence) == 1 and "src/a.py" in result.evidence[0] and "能力 x.cap" in result.evidence[0]
    assert "1 個在 A1 上和 sources 提交不一樣，影響 1 格" in result.summary
    assert changed.asked == [("a1", "mycrypto", ["src/a.py", "src/b.py"])] * 1 or changed.asked[0][2] == ["src/a.py", "src/b.py"]


def test_a_file_missing_on_a1_is_drift_and_a_file_missing_at_sources_is_not(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _write(myc, {"src/a.py": "one"})
    _publish_registry(repos, _drift_registry(c1, ["src/a.py", "src/not_in_that_repo.py"]))
    gone = Blobs({})                                                         # A1 has no src/a.py at all
    result = ow.check_registry_drift(ctx(gone))
    assert result.state == ow.OBSERVED and any("A1 上沒有這個檔案" in e for e in result.evidence)
    assert not any("not_in_that_repo" in e for e in result.evidence)         # not a file of that repo: left to verify_registry_evidence
    assert gone.asked[0][2] == ["src/a.py"]                                  # and not even asked about


def test_the_drift_key_changes_when_a1_moves_again_so_it_is_announced_again(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _write(myc, {"src/a.py": "one", "src/b.py": "b"})
    _publish_registry(repos, _drift_registry(c1, ["src/a.py"]))
    b = _blob(myc, c1, "src/b.py")
    first = ow.check_registry_drift(ctx(Blobs({"src/a.py": "1" * 40, "src/b.py": b})))
    again = ow.check_registry_drift(ctx(Blobs({"src/a.py": "1" * 40, "src/b.py": b})))
    later = ow.check_registry_drift(ctx(Blobs({"src/a.py": "2" * 40, "src/b.py": b})))
    assert first.key == again.key and first.key != later.key


def test_an_unknown_sources_commit_is_an_error(repos):
    _commit(repos / ow.REPOS["mycrypto"], "a")
    _publish_registry(repos, _drift_registry("deadbeef" * 5, ["src/a.py"]))
    with pytest.raises(ow.RemoteError, match="sources commit"):
        ow.check_registry_drift(ctx(Blobs({})))


def test_a_registry_that_cannot_be_refreshed_is_an_error_here_too(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _write(myc, {"src/a.py": "one"})
    _publish_registry(repos, _drift_registry(c1, ["src/a.py"]))
    _git(repos / "trade-alerts", "remote", "add", "origin", str(repos / "no-such-remote"))
    with pytest.raises(ow.RemoteError, match="cannot refresh"):
        ow.check_registry_drift(ctx(Blobs({})))


def test_git_blobs_asks_only_for_ls_tree_of_safe_paths_in_the_listed_clones(monkeypatch):
    seen = []
    remote = ow.Remote("k")
    sha = "a" * 40
    monkeypatch.setattr(remote, "_run", lambda host, words: seen.append((host, words)) or f"100644 blob {sha}\tsrc/a.py\n")
    assert remote.git_blobs("a1", "mycrypto", ["src/a.py", "src/zzz.py"]) == {"src/a.py": sha}
    host, words = seen[0]
    assert host == "a1" and words[words.index("ls-tree"):words.index("ls-tree") + 3] == ["ls-tree", "-r", "HEAD"]
    assert words[words.index("--") + 1:] == ["src/a.py", "src/zzz.py"] and words[words.index("-C") + 1] == "/home/ubuntu/src/my-crypto-bot"
    for bad in (["../etc/passwd"], ["src/../../x"], ["-rf"], ["a b"], ["a;id"], ["a\nb"], ["/abs/path"], [""], ["$(id)"], ["src/a.py", "--output=/x"]):
        with pytest.raises(ow.RemoteError):
            remote.git_blobs("a1", "mycrypto", bad)
    for host, key in (("dev", "mycrypto"), ("a1", "ops-notify"), ("a1", "../x")):
        with pytest.raises(ow.RemoteError):
            remote.git_blobs(host, key, ["src/a.py"])
    assert len(seen) == 1
    many = [f"src/f{i}.py" for i in range(200)]
    monkeypatch.setattr(remote, "_run", lambda host, words: seen.append((host, words)) or "")
    remote.git_blobs("a1", "mycrypto", many)
    assert len(seen) == 1 + 3                                                # chunks of 80
