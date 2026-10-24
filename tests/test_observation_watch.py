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
            raise ow.RemoteFileMissing(f"missing {host}:{path}") from None

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
    "/opt/my-crypto-bot/state/state.json.bak-x5-kill", "/opt/my-crypto-bot/state/../state/state.json", "/opt/my-crypto-bot/state/",
    "/opt/btc-bull-market-competition/state/state.json", "/var/lib/portfolio-query/my-crypto-bot/current.json\n",
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
    assert result.evidence[0].startswith("事件：") and result.evidence[1].startswith("第一則：") and "momentum:ledger " in result.evidence[1] and "（台北）" in result.evidence[1]
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
    assert ended.state == ow.OBSERVED and "已停止提醒" in ended.evidence[0] and ended.key.endswith(":ended")


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


def test_a_check_removed_from_the_registry_leaves_no_orphan_state():
    # a check retired from CHECKS (e.g. crypto-flat/x1, 2026-10-22) must not keep showing up in state.json forever
    fine = ow.Check("fine", "好的", ("f-f",), lambda c: ow.Result(ow.WAITING, "等"))
    state = {"items": {"retired": {"id": "retired", "state": ow.OBSERVED, "key": "k", "acked_key": "observed:k"}}}
    items = ow.run_checks(ow.Remote("k"), NOW, state, [fine])
    assert "retired" not in items and items.keys() == {"fine"}


def test_the_telegram_token_is_never_sent_without_both_variables():
    assert ow.send_telegram("x", {}) is False and ow.send_telegram("x", {"TELEGRAM_BOT_TOKEN": "t"}) is False


@pytest.fixture
def demo_check(monkeypatch):
    """A stand-in check for the command-line tests: it is OBSERVED and needs a human on every run, so run/report/ack,
    the lock and the senders can be exercised without depending on any real check's data.  ``main()`` calls
    ``run_checks`` with its default check list (bound when the function was defined), so the list is replaced here."""
    check = ow.Check("demo", "示範項目", ("f-demo",), lambda c: ow.Result(ow.OBSERVED, "到了", needs_human=True, key="k"))
    real = ow.run_checks
    monkeypatch.setattr(ow, "run_checks", lambda remote, now, previous, checks=None, only=None: real(remote, now, previous, (check,), only))
    return check


# --- f-70 batch 1: dev trend reconcile, health publishers, dust convert --------------------------------------------------

def _status_file(value, minutes_ago=10, note="n"):
    return {"value": value, "checked_at": iso(NOW - timedelta(minutes=minutes_ago)), "note": note}


def test_dev_trend_reconcile_waits_while_diverged_and_tells_once_it_is_reconciled():
    r = FakeRemote()
    put(r, "dev", "seykota", "ledger_status.json", _status_file("DIVERGED", note="18 exchange fill(s) not recorded in the ledger"))
    waiting = ow.check_dev_trend_reconcile(ctx(r))
    assert waiting.state == ow.WAITING and "DIVERGED" in waiting.summary
    put(r, "dev", "seykota", "ledger_status.json", _status_file("RECONCILED"))
    done = ow.check_dev_trend_reconcile(ctx(r))
    assert done.state == ow.OBSERVED and not done.needs_human and not done.closable and done.key == "reconciled"
    assert "dev-trend-entry" in " ".join(done.evidence)


def test_dev_trend_reconcile_raises_on_a_stale_or_missing_status():
    r = FakeRemote()
    put(r, "dev", "seykota", "ledger_status.json", _status_file("RECONCILED", minutes_ago=200))
    with pytest.raises(ow.RemoteError):
        ow.check_dev_trend_reconcile(ctx(r))
    with pytest.raises(ow.RemoteError):
        ow.check_dev_trend_reconcile(ctx(FakeRemote()))


def _publish_remote(a1=None, dev=None):
    r = FakeRemote()
    for host, state in (("a1", a1), ("dev", dev)):
        r.files[(host, ow.HEALTH_PUBLISH_STATE)] = json.dumps(state if state is not None else
                                                              {"consecutive_failures": 0, "last_error": None,
                                                               "last_success_at": iso(NOW - timedelta(minutes=4))})
    return r


def test_health_publish_starts_a_streak_and_announces_it_only_after_72_hours():
    first = ow.check_health_publish(ctx(_publish_remote()))
    assert first.state == ow.WAITING and first.extra["healthy_since"] == iso(NOW)
    early = ow.check_health_publish(ctx(_publish_remote(), {"healthy_since": iso(NOW - timedelta(hours=71)), "last_seen": iso(NOW - timedelta(minutes=30))}))
    assert early.state == ow.WAITING and early.extra["healthy_since"] == iso(NOW - timedelta(hours=71)) and early.extra["last_seen"] == iso(NOW)
    done = ow.check_health_publish(ctx(_publish_remote(), {"healthy_since": iso(NOW - timedelta(hours=73)), "last_seen": iso(NOW - timedelta(minutes=30))}))
    assert done.state == ow.OBSERVED and done.closable and not done.needs_human and done.key == "stable"
    assert done.extra["healthy_since"] == iso(NOW - timedelta(hours=73))


def test_health_publish_restarts_the_streak_when_either_host_is_not_healthy():
    stale = {"consecutive_failures": 0, "last_error": None, "last_success_at": iso(NOW - timedelta(minutes=40))}
    one_bad = ow.check_health_publish(ctx(_publish_remote(dev=stale), {"healthy_since": iso(NOW - timedelta(hours=100)), "last_seen": iso(NOW - timedelta(minutes=30))}))
    assert one_bad.state == ow.WAITING and one_bad.extra == {}
    failing = {"consecutive_failures": 1, "last_error": "x", "last_success_at": iso(NOW - timedelta(minutes=4))}
    assert ow.check_health_publish(ctx(_publish_remote(a1=failing))).state == ow.WAITING


def test_health_publish_three_failures_in_a_row_is_failed_and_unreadable_state_is_an_error():
    bad = {"consecutive_failures": 3, "last_error": "x", "last_success_at": iso(NOW - timedelta(hours=1))}
    failed = ow.check_health_publish(ctx(_publish_remote(dev=bad)))
    assert failed.state == ow.FAILED and failed.key == "failing-dev"
    for broken in ({"consecutive_failures": "0"}, {"consecutive_failures": True}, {"consecutive_failures": -1}, {}):
        with pytest.raises(ow.RemoteError):
            ow.check_health_publish(ctx(_publish_remote(a1=broken)))
    with pytest.raises(ow.RemoteError):
        ow.check_health_publish(ctx(FakeRemote()))


def test_health_publish_streak_survives_between_runs():
    check = next(c for c in ow.CHECKS if c.id == "health-publish")
    items = ow.run_checks(_publish_remote(), NOW, {}, [check])
    assert items["health-publish"]["extra"]["healthy_since"] == iso(NOW)
    state = {"items": items}
    for step in range(1, 145):                 # one run every 30 minutes for 72 hours
        moment = NOW + timedelta(minutes=30 * step)
        state = {"items": ow.run_checks(_healthy_publish_at(moment), moment, state, [check])}
        assert state["items"]["health-publish"]["state"] == (ow.OBSERVED if step == 144 else ow.WAITING), step
    assert state["items"]["health-publish"]["closable"] and state["items"]["health-publish"]["key"] == "stable"


def _healthy_publish_at(moment):
    r = FakeRemote()
    for host in ("a1", "dev"):
        r.files[(host, ow.HEALTH_PUBLISH_STATE)] = json.dumps({"consecutive_failures": 0, "last_error": None, "last_success_at": iso(moment - timedelta(minutes=3))})
    return r


def test_health_publish_a_run_that_could_not_read_ends_the_streak_even_though_the_error_keeps_the_old_extra():
    """Review of #304 (BLOCK-304-01): healthy -> unreadable -> healthy again must not count the unobserved stretch."""
    check = next(c for c in ow.CHECKS if c.id == "health-publish")
    state = {"items": ow.run_checks(_healthy_publish_at(NOW), NOW, {}, [check])}
    broken_at = NOW + timedelta(hours=25)
    state = {"items": ow.run_checks(FakeRemote(), broken_at, state, [check])}                    # the files cannot be read
    assert state["items"]["health-publish"]["state"] == ow.ERROR
    assert state["items"]["health-publish"]["extra"]["healthy_since"] == iso(NOW)                 # run_checks keeps a failed run's extra
    back = NOW + timedelta(hours=73)
    state = {"items": ow.run_checks(_healthy_publish_at(back), back, state, [check])}
    entry = state["items"]["health-publish"]
    assert entry["state"] == ow.WAITING and not entry["closable"] and entry["extra"]["healthy_since"] == iso(back)


def test_health_publish_a_gap_longer_than_one_run_restarts_the_streak_and_a_normal_cadence_does_not():
    prev = {"healthy_since": iso(NOW - timedelta(hours=100))}
    for gap, restarted in ((30, False), (45, False), (46, True), (120, True)):
        result = ow.check_health_publish(ctx(_publish_remote(), {**prev, "last_seen": iso(NOW - timedelta(minutes=gap))}))
        assert (result.extra["healthy_since"] == iso(NOW)) == restarted, gap
    no_seen = ow.check_health_publish(ctx(_publish_remote(), prev))                                # an old record without last_seen
    assert no_seen.extra["healthy_since"] == iso(NOW)


def _dust_rows(hours=3, mode="LIVE", test=False):
    base = {"event_type": "capital_flow", "event_time": hours_ago(hours), "execution_mode": mode}
    rows = [{**base, "event_id": "o1", "kind": "dust_convert_out", "asset": "ETH", "amount": 0.001},
            {**base, "event_id": "i1", "kind": "dust_convert_in", "asset": "USDT", "amount": 3.0}]
    if test:
        rows = [{**row, "details": {"test": True}} for row in rows]
    return rows


def _dust_remote(rows=(), attempt=None, ledger="RECONCILED", ledger_minutes=20):
    r = FakeRemote()
    put(r, "a1", "btc-competition", "trading_ledger.jsonl", list(rows), jsonl=True)
    put(r, "a1", "btc-competition", "ledger_status.json", _status_file(ledger, ledger_minutes))
    if attempt is not None:
        r.files[("a1", ow.DUST_ATTEMPT_PATH)] = json.dumps(attempt)
    return r


def test_dust_convert_waits_without_real_conversion_rows_and_ignores_test_and_demo_rows():
    assert ow.check_dust_convert(ctx(_dust_remote())).state == ow.WAITING
    assert ow.check_dust_convert(ctx(_dust_remote(_dust_rows(test=True)))).state == ow.WAITING
    assert ow.check_dust_convert(ctx(_dust_remote(_dust_rows(mode="DEMO")))).state == ow.WAITING
    nothing = ow.check_dust_convert(ctx(_dust_remote(attempt={"day": "2026-10-25", "status": "nothing_offered", "at": iso(NOW)})))
    assert nothing.state == ow.WAITING and "nothing_offered" in nothing.summary


@pytest.mark.parametrize("status", ["needs_review", "failed", "partial"])
def test_dust_convert_failure_statuses_are_failed_and_told_once_per_day_and_status(status):
    result = ow.check_dust_convert(ctx(_dust_remote(attempt={"day": "2026-10-25", "status": status, "detail": "d", "at": iso(NOW)})))
    assert result.state == ow.FAILED and result.key == f"2026-10-25-{status}"


def test_dust_convert_a_converting_record_is_only_failed_when_it_has_been_stuck():
    fresh = {"day": "2026-10-25", "status": "converting", "at": iso(NOW - timedelta(minutes=5))}
    assert ow.check_dust_convert(ctx(_dust_remote(attempt=fresh))).state == ow.WAITING
    stuck = {**fresh, "at": iso(NOW - timedelta(minutes=45))}
    assert ow.check_dust_convert(ctx(_dust_remote(attempt=stuck))).state == ow.FAILED


def test_dust_convert_first_real_conversion_is_observed_but_still_needs_the_operator_to_compare_with_binance():
    done = {"day": "2026-10-25", "status": "done", "detail": "x", "at": iso(NOW - timedelta(hours=3))}
    result = ow.check_dust_convert(ctx(_dust_remote(_dust_rows(), done)))
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable and result.key == "1-1"
    assert ow.check_dust_convert(ctx(_dust_remote(_dust_rows(), {**done, "status": "converting", "at": iso(NOW)}))).state == ow.WAITING
    assert ow.check_dust_convert(ctx(_dust_remote(_dust_rows(), done, ledger_minutes=170))).state == ow.WAITING     # not reconciled after the grace yet
    assert ow.check_dust_convert(ctx(_dust_remote(_dust_rows(), done, ledger="DIVERGED"))).state == ow.FAILED


def test_f70_batch1_checks_are_registered_and_read_only_whitelisted():
    ids = {c.id: c for c in ow.CHECKS}
    assert ids["dev-trend-reconcile"].covers == ("f-7",) and ids["health-publish"].covers == ("f-45",) and ids["dust-convert"].covers == ("f-66",)
    assert ow.HEALTH_PUBLISH_STATE in ow.ALLOWED_PATHS and ow.DUST_ATTEMPT_PATH in ow.ALLOWED_PATHS
    assert ow.audit("seykota", "ledger_status.json") in ow.ALLOWED_PATHS and ow.audit("btc-competition", "ledger_status.json") in ow.ALLOWED_PATHS


# --- command line -----------------------------------------------------------------------------------------------------

def test_run_report_and_ack_round_trip(tmp_path, capsys, demo_check):
    r = FakeRemote()
    state, sent = tmp_path / "state.json", []
    only = ["--state", str(state), "--only", "demo"]
    assert ow.main(["run", *only], remote=r, send=lambda t: sent.append(t) or True) == 0
    assert len(sent) == 1 and "需要你確認" in sent[0]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["items"]["demo"]["state"] == ow.OBSERVED and saved["items"]["demo"]["notified_key"]
    assert ow.main(["run", *only], remote=r, send=lambda t: sent.append(t) or True) == 0 and len(sent) == 1
    capsys.readouterr()
    assert ow.main(["report", "--state", str(state)]) == 0
    assert "需要你確認" in capsys.readouterr().out
    assert ow.main(["ack", "demo", "--state", str(state)]) == 0
    capsys.readouterr()
    ow.main(["report", "--state", str(state)])
    assert "已處理" in capsys.readouterr().out
    assert ow.main(["ack", "nope", "--state", str(state)]) == 2


def test_dry_run_neither_sends_nor_saves(tmp_path, demo_check):
    state, sent = tmp_path / "state.json", []
    ow.main(["run", "--dry-run", "--state", str(state), "--only", "demo"],
            remote=FakeRemote(), send=lambda t: sent.append(t) or True)
    assert sent == [] and not state.exists()


def test_every_check_has_a_unique_id_and_names_the_items_it_covers():
    ids = [c.id for c in ow.CHECKS]
    assert len(ids) == len(set(ids))
    assert all(c.covers and c.title for c in ow.CHECKS)
    covered = {i for c in ow.CHECKS for i in c.covers}
    assert {"phase-sync1", "phase-sync4", "f-23", "f-26", "f-30", "f-35", "f-37", "f-39", "f-40", "f-41", "e-2", "e-5", "f-7", "phase-g2", "phase-x5b"} <= covered


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
    env_fill = (_ROOT / "deploy" / "observation-watch" / "watch_env.sh").read_text(encoding="utf-8")
    assert "umask 077" in env_fill and 'chmod 600 "$WATCH_ENV"' in installer and "WATCH_ENV=/etc/observation-watch/watch.env" in installer
    assert 'source "$SRC/deploy/observation-watch/watch_env.sh"' in installer and "ensure_watch_env /etc/ops-notify/ops-notify.env" in installer
    for text in (installer, env_fill):
        assert not any(w in text for w in ("echo $TELEGRAM", 'echo "$TELEGRAM', "cat /etc/ops-notify", "echo $line", 'echo "$line"', "echo $LINE", 'echo "$LINE'))
    # LINE is the primary channel and Telegram the fallback: both pairs are copied, LINE is required
    for var in ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_RECIPIENT_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        assert var in env_fill
    assert "no LINE settings for the watcher" in env_fill and "LINE" not in service


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

def test_a_second_run_while_one_is_running_does_nothing(tmp_path, capsys, demo_check):
    import fcntl
    state = tmp_path / "state.json"
    with open(state.with_suffix(".lock"), "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sent = []
        assert ow.main(["run", "--state", str(state), "--only", "demo"], remote=FakeRemote(), send=lambda t: sent.append(t) or True) == 0
    assert sent == [] and not state.exists() and "另一個偵測正在跑" in capsys.readouterr().out


def test_a_state_file_that_cannot_be_saved_is_reported_and_the_repeat_is_documented(tmp_path, monkeypatch, capsys, demo_check):
    state, sent = tmp_path / "state.json", []
    r = FakeRemote()
    monkeypatch.setattr(ow, "save_state", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    code = ow.main(["run", "--state", str(state), "--only", "demo"], remote=r, send=lambda t: sent.append(t) or True)
    assert code == 1 and len(sent) == 1 and "下一輪可能重複發送" in capsys.readouterr().err


# --- the state is read only after the lock is held (review of #183 round 3) ----------------------------------------------

@pytest.mark.parametrize("argv", [["run", "--only", "demo"], ["ack", "demo"]])
def test_the_state_is_loaded_while_the_lock_is_held(tmp_path, monkeypatch, argv, demo_check):
    import fcntl
    state = tmp_path / "state.json"
    ow.save_state(state, {"items": {"demo": {"state": ow.WAITING, "key": "k"}}})
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
    ow.main([*argv, "--state", str(state)], remote=FakeRemote(), send=lambda t: True)
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

import os
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


# --- review of #199: an unreadable ls-tree answer must not become "nothing drifted" -----------------------------------

def test_an_unparseable_ls_tree_line_is_an_error_not_a_missing_file():
    good = "100644 blob " + "a" * 40 + "\tsrc/a.py"
    assert ow._parse_ls_tree(good + "\n\n") == {"src/a.py": "a" * 40}
    for bad in ("unrecognized ls-tree output", good + "\nfatal: not a tree", "100644 tree " + "a" * 40 + "\tsrc", "100644 blob xyz\tsrc/a.py"):
        with pytest.raises(ow.RemoteError, match="unrecognised"):
            ow._parse_ls_tree(bad)


def test_the_review_scenario_garbage_from_the_sources_tree_is_an_error(repos, monkeypatch):
    """Registry cites src/a.py, the sources commit exists, ls-tree exits 0 with output nobody can parse, and A1 holds another blob."""
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _write(myc, {"src/a.py": "one"})
    _publish_registry(repos, _drift_registry(c1, ["src/a.py"]))
    real_git = ow._git

    def fake_git(repo, *args, **kw):
        if "ls-tree" in args and repo.name == ow.REPOS["mycrypto"]:
            return subprocess.CompletedProcess(args, 0, stdout="unrecognized ls-tree output\n", stderr="")
        return real_git(repo, *args, **kw)
    monkeypatch.setattr(ow, "_git", fake_git)
    remote = Blobs({"src/a.py": "f" * 40})
    with pytest.raises(ow.RemoteError, match="unrecognised"):
        ow.check_registry_drift(ctx(remote))
    state = ow.run_checks(remote, NOW, {}, checks=[c for c in ow.CHECKS if c.id == "registry-drift"])
    assert state["registry-drift"]["state"] == ow.ERROR and remote.asked == []


def test_garbage_from_a1_is_an_error_and_so_is_an_answer_about_other_files(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _write(myc, {"src/a.py": "one", "src/b.py": "two"})
    _publish_registry(repos, _drift_registry(c1, ["src/a.py"]))

    class Garbage(Blobs):
        def git_blobs(self, host, key, paths):
            raise ow.RemoteError("A1 mycrypto: unrecognised output line 'oops'")
    with pytest.raises(ow.RemoteError, match="unrecognised"):
        ow.check_registry_drift(ctx(Garbage({})))
    class Chatty(Blobs):
        def git_blobs(self, host, key, paths):
            return {**super().git_blobs(host, key, paths), "src/zzz.py": "1" * 40}
    with pytest.raises(ow.RemoteError, match="not asked for"):
        ow.check_registry_drift(ctx(Chatty({"src/a.py": "2" * 40})))
    remote = ow.Remote("k")
    import types
    remote._run = types.MethodType(lambda self, host, words: "not an ls-tree line\n", remote)
    with pytest.raises(ow.RemoteError, match="unrecognised"):
        remote.git_blobs("a1", "mycrypto", ["src/a.py"])


def test_citations_that_all_miss_the_sources_commit_are_an_error_not_all_clear(repos):
    myc = repos / ow.REPOS["mycrypto"]
    c1 = _write(myc, {"src/other.py": "x"})
    _publish_registry(repos, _drift_registry(c1, ["src/a.py"]))              # neither src/a.py nor src/b.py exists at c1
    with pytest.raises(ow.RemoteError, match="一個都找不到"):
        ow.check_registry_drift(ctx(Blobs({})))


def test_the_unit_lets_the_watcher_fetch_every_clone_it_refreshes():
    """Regression: ProtectHome=read-only made `git fetch` fail on FETCH_HEAD, so registry-awaits/-drift reported broken."""
    unit = (Path(__file__).resolve().parents[1] / "deploy" / "observation-watch" / "observation-watch.service").read_text(encoding="utf-8")
    writable = " ".join(line.split("=", 1)[1] for line in unit.splitlines() if line.startswith("ReadWritePaths="))
    for name in ("trade-alerts", *ow.REPOS.values()):
        assert f"-/home/@WATCH_USER@/{name}/.git" in writable.split(), name


# --- x5b: the dev crypto strategy opens a testnet position by itself ----------------------------------------------------

X5B_NOW = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
STATE_PATH = "/opt/my-crypto-bot/state/state.json"


def x5b_ctx(remote, previous=None):
    return ow.Context(remote, X5B_NOW, previous or {})


def x5b_ev(hours, kind, **extra):
    stamp = iso(X5B_NOW - timedelta(hours=hours))
    return {"event_type": kind, "event_time": stamp, "event_id": f"x{hours}{kind}", "execution_mode": "DEMO", **extra}


def x5b_remote(events, *, state=None, reconcile="RECONCILED"):
    r = FakeRemote()
    put(r, "dev", "mycrypto", "trading_ledger.jsonl", events, jsonl=True)
    put(r, "dev", "mycrypto", "google_reconcile_status.json",
        {"value": reconcile, "checked_at": iso(X5B_NOW - timedelta(minutes=5)), "note": "n"})
    if state is not None:
        r.files[("dev", STATE_PATH)] = json.dumps(state)
    return r


def test_the_dev_crypto_state_file_is_the_only_new_readable_path():
    assert STATE_PATH in ow.ALLOWED_PATHS
    assert STATE_PATH == f"/opt/{ow.REPOS['mycrypto']}/state/state.json"


@pytest.mark.parametrize("events", [
    [],
    [x5b_ev(2, "trade_open", source="x5b_test", trade_id="T")],                     # the hand-made duplicate-send test rows
    [x5b_ev(2, "trade_open", source="position_recovered", trade_id="T")],            # an adoption is not an entry on a signal
    [dict(x5b_ev(2, "trade_open", source="entry_signal", trade_id="T"), execution_mode="LIVE")],
    [dict(x5b_ev(2, "trade_open", source="entry_signal", trade_id="T"), event_time="2026-10-18T07:00:00+00:00")],   # before the baseline
])
def test_x5b_waits_until_the_strategy_enters_by_itself(events):
    result = ow.check_dev_crypto_x5b(x5b_ctx(x5b_remote(events)))
    assert result.state == ow.WAITING


def test_x5b_reports_the_first_own_entry_once_and_needs_a_person():
    r = x5b_remote([x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1")],
                   state={"trade_id": "T1", "stop_plan_order_id": 111})
    result = ow.check_dev_crypto_x5b(x5b_ctx(r))
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable
    assert "可以開始 x5b" in result.summary and "還沒看到停損移動" in result.summary and "T1" in result.evidence[0]
    assert result.extra["stops"] == {"T1": ["111"]}


def x5b_state(order, price):
    return {"trade_id": "T1", "stop_plan_order_id": order, "active_stop_price": price}


def x5b_run(events, order, price, previous=None):
    return ow.check_dev_crypto_x5b(x5b_ctx(x5b_remote(events, state=x5b_state(order, price)), previous))


def test_x5b_sees_a_moved_stop_as_a_new_order_id_with_a_tighter_price_between_runs():
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1", side="short")]
    first = x5b_run(events, 111, 86190.9)
    second = x5b_run(events, 222, 85000.0, first.extra)              # a short's stop moved down
    assert "停損已移動過" in second.summary and second.key != first.key
    again = x5b_run(events, 222, 85000.0, second.extra)
    assert again.key == second.key                       # the same observation is announced once (notify keys on it)


def test_x5b_a_long_moves_its_stop_up():
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1", side="long")]
    first = x5b_run(events, 111, 70000.0)
    assert "停損已移動過" in x5b_run(events, 222, 71000.0, first.extra).summary
    assert "還沒看到停損移動" in x5b_run(events, 222, 69000.0, first.extra).summary


def test_x5b_a_replaced_and_restored_stop_is_not_a_move():
    """10/20: a dry-run replaced the short's stop (86190.9 -> 82943.09) and restored it under a new id (86190.9)."""
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1", side="short")]
    first = x5b_run(events, 111, 86190.9)
    restored = x5b_run(events, 222, 86190.9, first.extra)            # a new id at the same price
    assert "還沒看到停損移動" in restored.summary and restored.key == first.key
    looser = x5b_run(events, 333, 90000.0, restored.extra)           # a new id at a looser price
    assert "還沒看到停損移動" in looser.summary
    after = x5b_run(events, 444, 88000.0, looser.extra)              # tightening again counts from the new baseline
    assert "停損已移動過" in after.summary


def test_x5b_the_price_baseline_follows_an_unchanged_order_id():
    """BLOCK-260-01: same id, the price changed in between, then the id changes to a price that is looser than that."""
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1", side="short")]
    r1 = x5b_run(events, 111, 86190.9)
    r2 = x5b_run(events, 111, 82943.09, r1.extra)
    assert r2.extra["prices"] == {"T1": 82943.09}
    r3 = x5b_run(events, 222, 85000.0, r2.extra)                      # looser than the last price seen: not a move
    assert "還沒看到停損移動" in r3.summary and r3.extra["stops"] == {"T1": ["111"]}


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", None, "x"])
def test_x5b_a_non_finite_or_missing_price_is_ignored(bad):
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1", side="short")]
    r1 = x5b_run(events, 111, 86190.9)
    r2 = x5b_run(events, 222, bad, r1.extra)
    assert "還沒看到停損移動" in r2.summary and r2.extra["prices"] == {"T1": 86190.9}


def test_x5b_old_memory_without_prices_never_counts_the_next_id_change_as_a_move():
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1", side="short")]
    result = x5b_run(events, 222, 80000.0, {"stops": {"T1": ["111"]}})   # the memory written before prices were kept
    assert "還沒看到停損移動" in result.summary and result.extra["prices"] == {"T1": 80000.0}


def test_x5b_a_move_needs_a_known_side_and_price():
    no_side = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1")]
    first = x5b_run(no_side, 111, 86190.9)
    assert "還沒看到停損移動" in x5b_run(no_side, 222, 85000.0, first.extra).summary
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1", side="short")]
    first = ow.check_dev_crypto_x5b(x5b_ctx(x5b_remote(events, state={"trade_id": "T1", "stop_plan_order_id": 111})))
    second = ow.check_dev_crypto_x5b(x5b_ctx(x5b_remote(events, state={"trade_id": "T1", "stop_plan_order_id": 222}), first.extra))
    assert "還沒看到停損移動" in second.summary


def test_x5b_an_unmoved_stop_or_another_trades_stop_is_not_a_move():
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1")]
    r = x5b_remote(events, state={"trade_id": "T1", "stop_plan_order_id": 111})
    prev = {"stops": {"OLD": ["1", "2"]}}                # an unrelated trade with two stop ids
    result = ow.check_dev_crypto_x5b(x5b_ctx(r, prev))
    assert "還沒看到停損移動" in result.summary
    assert set(result.extra["stops"]) == {"T1"}          # and it is dropped, not carried for ever


def test_x5b_all_three_observed_is_still_not_closable_by_the_machine():
    events = [x5b_ev(3, "trade_open", source="entry_signal", trade_id="T1"),
              x5b_ev(1, "trade_close", source="native_stop_reconciled", trade_id="T1")]
    r = x5b_remote(events, state={"trade_id": "T1", "stop_plan_order_id": 222})
    result = ow.check_dev_crypto_x5b(x5b_ctx(r, {"stops": {"T1": ["111", "222"]}, "last_ids": {"T1": "222"}}))
    assert result.state == ow.OBSERVED and result.needs_human and not result.closable
    assert "三項都觀察到" in result.summary and result.key.startswith("entry|move|stop|")


def test_x5b_a_close_by_the_hand_made_test_or_another_source_is_not_a_stop_trigger():
    events = [x5b_ev(3, "trade_open", source="entry_signal", trade_id="T1"),
              x5b_ev(1, "trade_close", source="exit_signal", trade_id="T1"),
              x5b_ev(1, "trade_close", source="native_stop_reconciled", trade_id="OTHER")]
    result = ow.check_dev_crypto_x5b(x5b_ctx(x5b_remote(events)))
    assert "停損還沒觸發" in result.summary


def test_x5b_a_missing_state_file_when_flat_is_not_an_error():
    events = [x5b_ev(3, "trade_open", source="entry_signal", trade_id="T1"),
              x5b_ev(1, "trade_close", source="native_stop_reconciled", trade_id="T1")]
    result = ow.check_dev_crypto_x5b(x5b_ctx(x5b_remote(events)))       # no state file served
    assert result.state == ow.OBSERVED and "停損已觸發" in result.summary


def test_x5b_fails_when_the_sheet_disagrees_after_the_grace():
    events = [x5b_ev(3, "trade_open", source="entry_signal", trade_id="T1")]
    result = ow.check_dev_crypto_x5b(x5b_ctx(x5b_remote(events, reconcile="DIVERGED")))
    assert result.state == ow.FAILED


class _FailingRead(FakeRemote):
    def __init__(self, error, **kw):
        super().__init__(**kw)
        self.error = error

    def read(self, host, path):
        if path == STATE_PATH:
            raise self.error
        return super().read(host, path)


@pytest.mark.parametrize("message", [
    "dev: cat /opt/my-crypto-bot/state/state.json exit 1: cat: /opt/my-crypto-bot/state/state.json: Permission denied",
    "dev: sudo -n exit 1: sudo: a password is required",
    "dev: TimeoutExpired: timed out after 60 seconds",
    "a1: cat /x exit 255: ssh: connect to host port 22: Connection timed out",
])
def test_x5b_an_unreadable_state_file_is_an_error_not_a_flat_strategy(message):
    events = [x5b_ev(2, "trade_open", source="entry_signal", trade_id="T1")]
    base = x5b_remote(events)
    r = _FailingRead(ow.RemoteError(message), files=base.files)
    with pytest.raises(ow.RemoteError):
        ow.check_dev_crypto_x5b(x5b_ctx(r))
    state = ow.run_checks(r, X5B_NOW, {}, checks=[c for c in ow.CHECKS if c.id == "dev-crypto-x5b"])
    assert state["dev-crypto-x5b"]["state"] == ow.ERROR           # shown as a broken check, never as "no stop move yet"


@pytest.mark.parametrize("stderr, returncode, expected", [
    ("cat: /opt/my-crypto-bot/state/state.json: No such file or directory\n", 1, ow.RemoteFileMissing),
    ("cat: /opt/my-crypto-bot/state/state.json: Permission denied\n", 1, ow.RemoteError),
    ("cat: /other/path: No such file or directory\n", 1, ow.RemoteError),              # a different file named in the message
    ("Warning: Identity file k not accessible: No such file or directory.\n", 255, ow.RemoteError),   # ssh, not cat
    ("sudo: a password is required\n", 1, ow.RemoteError),
])
def test_only_a_cat_that_says_the_file_is_missing_counts_as_missing(monkeypatch, stderr, returncode, expected):
    import subprocess
    monkeypatch.setattr(ow.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], returncode, "", stderr))
    with pytest.raises(ow.RemoteError) as caught:
        ow.Remote("k")._run("dev", ["cat", STATE_PATH])
    assert type(caught.value) is expected


# --- f-26: a strategy confirmed earlier is not dropped for a moment the check cannot speak (carry-over) ---------------------

def _covered_before(key="momentum", hours_ago_=1, last_trade_hours_ago=5):
    return {"covered": {key: {"at": iso(NOW - timedelta(hours=hours_ago_)), "last_trade": iso(NOW - timedelta(hours=last_trade_hours_ago))}}}


def _tabs_with_momentum(*, status, trade_ago_minutes=300):
    st = {"momentum": status, "seykota": _status(30, name="趨勢策略"), "mycrypto": _status(30, name="加密策略"), "btc-competition": _status(30, name="競賽策略")}
    trades = {"momentum": [{"event_type": "trade_close", "event_time": iso(NOW - timedelta(minutes=trade_ago_minutes))}],
              "mycrypto": [trade(5)], "btc-competition": [trade(5)]}
    return tabs_remote(trades=trades, status=st)


def test_tabs_a_google_read_that_failed_keeps_a_confirmed_strategy_listed_with_the_reason():
    r = _tabs_with_momentum(status=_status(5, "UNKNOWN"))
    out = ow.check_sheet_tab_names(ctx(r, _covered_before()))
    assert out.state == ow.WAITING and not out.closable
    assert "動能策略（本輪讀不到 Google 表，沿用" in out.summary and "還在等新交易：趨勢策略" in out.summary
    assert any(line.startswith("動能策略：這一輪對帳讀不到 Google 表（UNKNOWN）") for line in out.evidence)
    assert out.extra["covered"]["momentum"]["at"] == iso(NOW - timedelta(hours=1))                    # the bound does not slide


def test_tabs_a_new_trade_inside_its_grace_does_not_count_as_confirmed_but_the_earlier_confirmation_stays():
    # the 10/14 review example: the old RECONCILED must not count for the NEW trade -- it is listed as carried, never as covered
    r = _tabs_with_momentum(status=_status(5), trade_ago_minutes=30)
    out = ow.check_sheet_tab_names(ctx(r, _covered_before()))
    assert out.state == ow.WAITING and not out.closable
    assert "動能策略（新交易在對帳寬限內，沿用" in out.summary
    assert any("還不算已確認" in line for line in out.evidence if line.startswith("動能策略"))
    assert not any("筆新交易（最近" in line and line.startswith("動能策略") for line in out.evidence)   # no 'covered' line for it


def test_tabs_the_carry_expires_after_three_hours():
    r = _tabs_with_momentum(status=_status(5, "UNKNOWN"))
    out = ow.check_sheet_tab_names(ctx(r, _covered_before(hours_ago_=ow.F26_CARRY_HOURS + 1)))
    assert "已確認：動能策略" not in out.summary and "動能策略" in out.summary.split("還在等新交易：")[1]
    assert "momentum" not in out.extra["covered"]


def test_tabs_nothing_is_carried_for_a_strategy_that_was_never_confirmed_or_whose_reconcile_stopped():
    r = _tabs_with_momentum(status=_status(5, "UNKNOWN"))
    assert "動能策略" in ow.check_sheet_tab_names(ctx(r, {})).summary.split("還在等新交易：")[1]            # no memory
    stale = _tabs_with_momentum(status=_status(300))                                                    # the check itself stopped
    out = ow.check_sheet_tab_names(ctx(stale, _covered_before()))
    assert "動能策略" in out.summary.split("還在等新交易：")[1] and "momentum" not in out.extra["covered"]


def test_tabs_a_diverged_answer_after_the_grace_or_a_wrong_tab_still_fails_at_once_even_if_confirmed_before():
    div = {"sheet_name": "動能策略", "value": "DIVERGED", "checked_at": iso(NOW - timedelta(minutes=5)), "note": "x"}
    assert ow.check_sheet_tab_names(ctx(_tabs_with_momentum(status=div), _covered_before())).state == ow.FAILED
    wrong = {"sheet_name": "mexc", "value": "RECONCILED", "checked_at": iso(NOW - timedelta(minutes=5))}
    assert ow.check_sheet_tab_names(ctx(_tabs_with_momentum(status=wrong), _covered_before())).state == ow.FAILED


def test_tabs_a_carried_strategy_never_lets_the_item_close_and_a_fresh_cover_restarts_the_clock():
    allfour = {k: [trade(5)] for k in ow.REPOS}
    good = {"momentum": _status(5, "UNKNOWN"), "seykota": _status(30, name="趨勢策略"), "mycrypto": _status(30, name="加密策略"), "btc-competition": _status(30, name="競賽策略")}
    carried = ow.check_sheet_tab_names(ctx(tabs_remote(trades=allfour, status=good), _covered_before()))
    assert carried.state == ow.WAITING and not carried.closable and "沿用的確認要等下一輪對帳重新確認後才能結案" in carried.summary
    fresh = {**good, "momentum": _status(30)}
    closed = ow.check_sheet_tab_names(ctx(tabs_remote(trades=allfour, status=fresh), _covered_before()))
    assert closed.state == ow.OBSERVED and closed.closable
    assert closed.extra["covered"]["momentum"]["at"] == iso(NOW)


def test_tabs_the_memory_survives_through_run_checks():
    only = [c for c in ow.CHECKS if c.id == "sheet-tab-names"]
    first = ow.run_checks(_tabs_with_momentum(status=_status(30)), NOW - timedelta(hours=1), {}, only)
    assert "momentum" in first["sheet-tab-names"]["extra"]["covered"]
    second = ow.run_checks(_tabs_with_momentum(status=_status(5, "UNKNOWN")), NOW, {"items": first}, only)
    assert "動能策略（本輪讀不到 Google 表" in second["sheet-tab-names"]["summary"]


def test_tabs_pending_reason_names_why_the_check_cannot_speak():
    t = NOW - timedelta(hours=3)
    assert ow.reconcile_pending_reason(_status(30, "UNKNOWN"), t, NOW) == "unknown"
    assert ow.reconcile_pending_reason(_status(30), NOW - timedelta(minutes=40), NOW) == "grace"
    assert ow.reconcile_pending_reason(_status(300), t, NOW) == "stale"
    assert ow.reconcile_pending_reason({"value": "RECONCILED"}, t, NOW) == "stale"


# review of #252: the carry needs a confirmation in the PAST, and only an answer the check can read counts as "in the grace"

def test_tabs_a_confirmation_dated_in_the_future_is_never_carried():
    future = {"covered": {"momentum": {"at": iso(NOW + timedelta(hours=48)), "last_trade": iso(NOW - timedelta(hours=1))}}}
    r = _tabs_with_momentum(status=_status(5, "UNKNOWN"))
    out = ow.check_sheet_tab_names(ctx(r, future))
    assert "動能策略" in out.summary.split("還在等新交易：")[1] and "momentum" not in out.extra["covered"]
    just_ahead = {"covered": {"momentum": {"at": iso(NOW + timedelta(seconds=1)), "last_trade": iso(NOW)}}}
    assert "momentum" not in ow.check_sheet_tab_names(ctx(r, just_ahead)).extra["covered"]


@pytest.mark.parametrize("answer", [{"value": "ERROR"}, {"value": "something-new"}, {"value": None}, {}])
def test_tabs_an_unreadable_answer_inside_the_grace_is_stale_not_grace(answer):
    status = {**_status(5), **answer}
    if not answer:
        status.pop("value")
    assert ow.reconcile_pending_reason(status, NOW - timedelta(minutes=30), NOW) == "stale"
    out = ow.check_sheet_tab_names(ctx(_tabs_with_momentum(status=status, trade_ago_minutes=30), _covered_before()))
    assert "動能策略" in out.summary.split("還在等新交易：")[1] and "momentum" not in out.extra["covered"]


def test_tabs_known_answers_inside_the_grace_still_count_as_grace():
    for value in ("RECONCILED", "DIVERGED"):
        assert ow.reconcile_pending_reason(_status(5, value), NOW - timedelta(minutes=30), NOW) == "grace"


@pytest.mark.parametrize("memory", [None, "text", ["a"], 7, {"covered": "x"}, {"covered": ["a"]}, {"covered": {"momentum": "x"}}, {"covered": {"momentum": {"at": "not a time"}}},
                                    {"covered": {"momentum": {"at": 12345}}}, {"covered": {"momentum": None}}])
def test_tabs_a_damaged_memory_is_no_memory_and_never_an_error(memory):
    previous = memory if isinstance(memory, dict) else {"covered": memory}
    out = ow.check_sheet_tab_names(ctx(_tabs_with_momentum(status=_status(5, "UNKNOWN")), previous))
    assert out.state == ow.WAITING and "動能策略" in out.summary.split("還在等新交易：")[1]


# --- messages go to LINE first; Telegram only after LINE failed for two runs in a row --------------------------------------

class _Reply:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_send_line_needs_both_variables_and_pushes_a_text_message_with_the_bearer_token(monkeypatch):
    assert ow.send_line("x", {}) is False and ow.send_line("x", {"LINE_CHANNEL_ACCESS_TOKEN": "t"}) is False
    assert ow.send_line("x", {"LINE_RECIPIENT_ID": "U1"}) is False
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["auth"], seen["body"], seen["timeout"] = request.full_url, request.get_header("Authorization"), json.loads(request.data), timeout
        return _Reply(200)

    monkeypatch.setattr(ow.urllib.request, "urlopen", fake_urlopen)
    env = {"LINE_CHANNEL_ACCESS_TOKEN": "secret-token", "LINE_RECIPIENT_ID": "U123"}
    assert ow.send_line("哈囉" + "x" * 6000, env) is True
    assert seen["url"] == "https://api.line.me/v2/bot/message/push" and seen["auth"] == "Bearer secret-token"
    assert seen["body"]["to"] == "U123" and seen["body"]["messages"][0]["type"] == "text"
    assert len(seen["body"]["messages"][0]["text"]) == ow.LINE_TEXT_LIMIT and seen["timeout"] == 20


def test_send_line_failures_are_false_and_never_raise_or_leak_the_token(monkeypatch):
    env = {"LINE_CHANNEL_ACCESS_TOKEN": "secret-token", "LINE_RECIPIENT_ID": "U123"}

    def quota(request, timeout):
        raise ow.urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(ow.urllib.request, "urlopen", quota)
    assert ow.send_line("x", env) is False
    monkeypatch.setattr(ow.urllib.request, "urlopen", lambda request, timeout: _Reply(500))
    assert ow.send_line("x", env) is False
    monkeypatch.setattr(ow.urllib.request, "urlopen", lambda request, timeout: (_ for _ in ()).throw(OSError("no network " + "secret-token")))
    assert ow.send_line("x", env) is False


def _failing_run(state, send, fallback):
    check = one_check(lambda n: ow.Result(ow.OBSERVED, "到了", needs_human=True, key="k"))
    state = {"items": ow.run_checks(ow.Remote("k"), NOW, state, [check])}
    return state, ow.notify(state["items"], send, fallback)


def test_a_message_that_reaches_line_never_touches_telegram():
    lines, telegrams = [], []
    state, sent = _failing_run({}, lambda t: lines.append(t) or True, lambda t: telegrams.append(t) or True)
    assert sent == ["demo"] and len(lines) == 1 and telegrams == []
    assert state["items"]["demo"]["send_failures"] is None and state["items"]["demo"]["notified_key"]


def test_telegram_is_used_only_after_line_failed_two_runs_in_a_row_and_says_why():
    telegrams, state = [], {}
    state, sent = _failing_run(state, lambda t: False, lambda t: telegrams.append(t) or True)
    assert sent == [] and telegrams == [] and state["items"]["demo"]["send_failures"]["n"] == 1      # one failure: LINE is tried again
    state, sent = _failing_run(state, lambda t: False, lambda t: telegrams.append(t) or True)
    assert sent == ["demo"] and len(telegrams) == 1
    assert telegrams[0].startswith("（LINE 送不出去，改用 Telegram 發這一則）") and "需要你確認" in telegrams[0]
    assert state["items"]["demo"]["notified_key"] and state["items"]["demo"]["send_failures"] is None
    state, sent = _failing_run(state, lambda t: False, lambda t: telegrams.append(t) or True)
    assert sent == [] and len(telegrams) == 1                                                       # told once, not again


def test_when_both_channels_fail_the_message_is_not_marked_sent_and_tries_again():
    state = {}
    for run in (1, 2, 3):
        state, sent = _failing_run(state, lambda t: False, lambda t: False)
        assert sent == [] and not state["items"]["demo"]["notified_key"]
        assert state["items"]["demo"]["send_failures"]["n"] == run
    state, sent = _failing_run(state, lambda t: True, lambda t: False)
    assert sent == ["demo"]


def test_the_failure_count_belongs_to_one_message_and_restarts_for_a_different_one():
    state, telegrams = {}, []
    state, _ = _failing_run(state, lambda t: False, lambda t: telegrams.append(t) or True)
    changed = one_check(lambda n: ow.Result(ow.OBSERVED, "另一件事", needs_human=True, key="other"))
    state = {"items": ow.run_checks(ow.Remote("k"), NOW, state, [changed])}
    ow.notify(state["items"], lambda t: False, lambda t: telegrams.append(t) or True)
    assert telegrams == [] and state["items"]["demo"]["send_failures"] == {"key": "observed:other", "n": 1}


def test_main_sends_to_line_by_default_and_falls_back_to_telegram(monkeypatch, tmp_path, demo_check):
    lines, telegrams = [], []
    monkeypatch.setattr(ow, "send_line", lambda t: lines.append(t) or True)
    monkeypatch.setattr(ow, "send_telegram", lambda t: telegrams.append(t) or True)
    r = FakeRemote()
    state = tmp_path / "state.json"
    assert ow.main(["run", "--state", str(state), "--only", "demo"], remote=r) == 0
    assert len(lines) == 1 and "需要你確認" in lines[0] and telegrams == []
    # a failing LINE for two runs sends the Telegram copy
    lines.clear()
    monkeypatch.setattr(ow, "send_line", lambda t: lines.append(t) and False)
    state2 = tmp_path / "state2.json"
    for _ in range(2):
        ow.main(["run", "--state", str(state2), "--only", "demo"], remote=r)
    assert len(lines) == 2 and len(telegrams) == 1 and telegrams[0].startswith("（LINE 送不出去")


# --- review of #254: a damaged counter or a sender that raises never stops the round --------------------------------------

@pytest.mark.parametrize("stored", ["invalid", -3, None, True, 1.5, 10**9, [], {"key": "observed:k"}, {"n": 1}, {"key": "observed:k", "n": "2"}, "text", 7])
def test_a_damaged_failure_counter_counts_as_no_failures_and_the_round_goes_on(stored):
    check = one_check(lambda n: ow.Result(ow.OBSERVED, "到了", needs_human=True, key="k"))
    other = ow.Check("other", "另一個", ("f-o",), lambda c: ow.Result(ow.FAILED, "不符", key="o"))
    items = ow.run_checks(ow.Remote("k"), NOW, {}, [check, other])
    items["demo"]["send_failures"] = stored if not isinstance(stored, dict) else {**stored}
    telegrams = []
    sent = ow.notify(items, lambda t: False, lambda t: telegrams.append(t) or True)
    assert items["demo"]["send_failures"] == {"key": "observed:k", "n": 1} and items["other"]["send_failures"] == {"key": "failed:o", "n": 1}
    assert sent == [] and telegrams == []                                              # one failure each, no Telegram yet; nothing raised


def test_a_well_formed_counter_still_reaches_the_fallback():
    check = one_check(lambda n: ow.Result(ow.OBSERVED, "到了", needs_human=True, key="k"))
    items = ow.run_checks(ow.Remote("k"), NOW, {}, [check])
    items["demo"]["send_failures"] = {"key": "observed:k", "n": 1}
    telegrams = []
    assert ow.notify(items, lambda t: False, lambda t: telegrams.append(t) or True) == ["demo"] and len(telegrams) == 1


def test_a_sender_that_raises_is_a_failed_attempt_and_the_other_messages_still_go_out():
    first = one_check(lambda n: ow.Result(ow.OBSERVED, "到了", needs_human=True, key="k"))
    second = ow.Check("second", "第二個", ("f-s",), lambda c: ow.Result(ow.FAILED, "不符", key="s"))
    items = ow.run_checks(ow.Remote("k"), NOW, {}, [first, second])
    seen = []

    def line(text):
        seen.append(text)
        if "到了" in text:
            raise RuntimeError("token-secret-in-an-exception")
        return True

    assert ow.notify(items, line) == ["second"] and len(seen) == 2
    assert items["demo"]["send_failures"] == {"key": "observed:k", "n": 1} and not items["demo"]["notified_key"]
    items["demo"]["send_failures"] = {"key": "observed:k", "n": 1}
    assert ow.notify(items, line, lambda t: (_ for _ in ()).throw(OSError("boom"))) == []          # a raising fallback is a failure too
    assert items["demo"]["send_failures"] == {"key": "observed:k", "n": 2}


# --- the installer's env fill (deploy/observation-watch/watch_env.sh), run against temp files, no systemd ------------------

def _fill(tmp_path, *, ops=None, watch=None):
    ops_file, watch_file = tmp_path / "ops-notify.env", tmp_path / "watch.env"
    if ops is not None:
        ops_file.write_text("\n".join(ops) + "\n", encoding="utf-8")
    if watch is not None:
        watch_file.write_text("\n".join(watch) + "\n", encoding="utf-8")
    script = f'source "{_ROOT}/deploy/observation-watch/watch_env.sh"; ensure_watch_env "{ops_file}" "{watch_file}"'
    run = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return run, watch_file


LINE = ["LINE_CHANNEL_ACCESS_TOKEN=line-secret-value", "LINE_RECIPIENT_ID=U-recipient-secret"]
TELEGRAM = ["TELEGRAM_BOT_TOKEN=telegram-secret-value", "TELEGRAM_CHAT_ID=123456"]


def _no_secret(run):
    assert not any(v in run.stdout + run.stderr for v in ("line-secret-value", "U-recipient-secret", "telegram-secret-value", "123456"))


def test_env_fill_line_complete_and_the_ops_file_missing_installs_with_only_a_warning(tmp_path):
    run, watch = _fill(tmp_path, ops=None, watch=LINE)                          # review B1: LINE there, no Telegram, source unreadable
    assert run.returncode == 0 and "WARNING: no Telegram settings" in run.stderr
    assert watch.read_text(encoding="utf-8").splitlines() == LINE
    _no_secret(run)


def test_env_fill_without_any_line_setting_fails(tmp_path):
    run, _ = _fill(tmp_path, ops=None, watch=[])
    assert run.returncode == 1 and "INSTALL_FAILED" in run.stderr
    run, _ = _fill(tmp_path, ops=TELEGRAM, watch=[])                           # the source exists but has no LINE
    assert run.returncode == 1 and "no LINE settings for the watcher" in run.stderr
    _no_secret(run)


def test_env_fill_copies_missing_values_from_the_ops_file_without_showing_them(tmp_path):
    run, watch = _fill(tmp_path, ops=[*LINE, *TELEGRAM, "OTHER=x"], watch=None)
    assert run.returncode == 0 and "WARNING" not in run.stderr
    assert watch.read_text(encoding="utf-8").splitlines() == [*LINE, *TELEGRAM]
    assert oct(watch.stat().st_mode & 0o777) == "0o600"
    assert "Copied LINE_CHANNEL_ACCESS_TOKEN" in run.stdout
    _no_secret(run)


def test_env_fill_is_idempotent_and_never_overwrites_an_existing_value(tmp_path):
    run, watch = _fill(tmp_path, ops=[*LINE, *TELEGRAM], watch=["LINE_CHANNEL_ACCESS_TOKEN=already-here", "LINE_RECIPIENT_ID=U-already"])
    assert run.returncode == 0
    first = watch.read_text(encoding="utf-8").splitlines()
    assert first[:2] == ["LINE_CHANNEL_ACCESS_TOKEN=already-here", "LINE_RECIPIENT_ID=U-already"] and first[2:] == TELEGRAM
    again, _ = _fill(tmp_path, ops=[*LINE, *TELEGRAM])
    assert again.returncode == 0 and watch.read_text(encoding="utf-8").splitlines() == first


def test_env_fill_copies_what_exists_when_the_source_lacks_only_telegram(tmp_path):
    run, watch = _fill(tmp_path, ops=LINE, watch=None)
    assert run.returncode == 0 and "WARNING: no Telegram settings" in run.stderr
    assert watch.read_text(encoding="utf-8").splitlines() == LINE


# --- P3: installing on a new host (fleet-standby-1, WATCH_USER=ubuntu) -------------------------------------------------

def _preflight(home, a1="161.33.186.220", path_prefix=None):
    # same shell options as install.sh: a failure inside the preflight would end the script before CONTINUES
    script = (f'set -euo pipefail; source "{_ROOT}/deploy/observation-watch/watch_preflight.sh"; '
              f'watch_preflight "{home}" {a1} oci_a1_key; echo "N=$WATCH_PREFLIGHT_WARNINGS"; echo INSTALL_CONTINUES')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={**os.environ, "PATH": f"{path_prefix}:{os.environ['PATH']}"} if path_prefix else None)


def test_preflight_on_an_empty_home_warns_about_every_missing_piece_and_still_succeeds(tmp_path):
    run = _preflight(tmp_path)
    assert run.returncode == 0 and "N=6" in run.stdout                    # 5 clones + known_hosts (no key file: nothing to check)
    assert run.stderr.count("WARNING: no clone") == 5 and "not in known_hosts" in run.stderr


def test_preflight_clean_home_has_no_warnings(tmp_path):
    for repo in ("trade-alerts", "ed-seykota-systematic-trend-following", "mexc-4h-momentum-trailing-stop", "my-crypto-bot", "btc-bull-market-competition"):
        (tmp_path / repo / ".git").mkdir(parents=True)
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    key = ssh / "oci_a1_key"
    key.write_text("not a real key\n", encoding="utf-8")
    key.chmod(0o600)
    (ssh / "known_hosts").write_text("161.33.186.220 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFakeFakeFakeFakeFakeFakeFakeFakeFakeFake\n", encoding="utf-8")
    run = _preflight(tmp_path)
    assert run.returncode == 0 and "N=0" in run.stdout and run.stderr == ""


def test_preflight_flags_a_key_readable_by_others_and_never_prints_the_key(tmp_path):
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    key = ssh / "oci_a1_key"
    key.write_text("SECRET-KEY-BODY\n", encoding="utf-8")
    key.chmod(0o644)
    run = _preflight(tmp_path)
    assert "has mode 644" in run.stderr and "SECRET-KEY-BODY" not in run.stdout + run.stderr


def test_installer_runs_the_preflight_with_the_target_users_home_and_does_not_stop_on_warnings():
    installer = (_ROOT / "deploy" / "observation-watch" / "install.sh").read_text(encoding="utf-8")
    assert 'source "$SRC/deploy/observation-watch/watch_preflight.sh"' in installer
    assert 'watch_preflight "$HOME_DIR" 161.33.186.220 oci_a1_key' in installer
    assert "A1_SSH_TARGET" not in installer and "161.33.186.220" in (_ROOT / "scripts" / "observation_watch.py").read_text(encoding="utf-8")


def test_unit_template_has_no_hard_coded_account_so_any_watch_user_works():
    unit = (_ROOT / "deploy" / "observation-watch" / "observation-watch.service").read_text(encoding="utf-8")
    assert "ai001" not in unit and unit.count("@WATCH_USER@") >= 7
    for user in ("ubuntu", "ai001"):
        rendered = unit.replace("@WATCH_USER@", user)
        assert f"User={user}" in rendered.splitlines() and f"ReadWritePaths=/home/{user}/.local/state/observation-watch" in rendered.splitlines()
        assert "@" not in rendered.replace("/home/", "")


@pytest.mark.parametrize("stat_body", ["exit 1", "echo garbage", "echo"])
def test_preflight_survives_a_failing_or_garbage_stat_under_set_e(tmp_path, stat_body):
    """Review #256 BLOCK-256-01: stat failing must be a warning; the install must still reach its next step."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "stat").write_text(f"#!/bin/sh\n{stat_body}\n", encoding="utf-8")
    (stubs / "stat").chmod(0o755)
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    key = home / ".ssh" / "oci_a1_key"
    key.write_text("SECRET-KEY-BODY\n", encoding="utf-8")
    run = _preflight(home, path_prefix=str(stubs))
    assert run.returncode == 0 and "INSTALL_CONTINUES" in run.stdout and "cannot read the mode" in run.stderr
    assert "N=7" in run.stdout                                  # 5 clones + known_hosts + unreadable mode
    assert "SECRET-KEY-BODY" not in run.stdout + run.stderr


def test_the_preflight_is_called_from_the_installer_before_any_install_step_and_under_set_e():
    installer = (_ROOT / "deploy" / "observation-watch" / "install.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in installer
    assert installer.index("watch_preflight \"$HOME_DIR\"") < installer.index("install -d -m 755 /opt/observation-watch")


# --- 2026-10-23: the reminders notice says WHICH alert, in Taipei time, and what to look for on Telegram -----------------

FIRST_NOTICE = "2026-10-22T11:10:00+00:00"       # 台北 10/22 19:10


def _reminders_result(value="STALE", count=12, ended=False):
    remote = reminder_remote({"mycrypto:runtime": {"since": FIRST_NOTICE, "count": count, "last_at": "2026-10-23T05:10:00+00:00"}})
    remote.files[("a1", "/var/lib/ops-notify/state.json")] = json.dumps({
        "_reminders": {"mycrypto:runtime": {"since": FIRST_NOTICE, "count": count, "last_at": "2026-10-23T05:10:00+00:00"}},
        "mycrypto:runtime": {"value": value, "severity": "warn" if value else "ok"}})
    first = ow.check_reminders(ctx(remote))
    if not ended:
        return first
    return ow.check_reminders(ow.Context(reminder_remote({}), NOW, first.extra))


def test_the_reminders_notice_names_the_error_in_taipei_time_and_says_what_to_look_for_on_telegram():
    result = _reminders_result()
    text = "\n".join([result.summary, *result.evidence])
    assert "ERR-048" in result.summary and "加密策略的運行狀態軸（ERR-048 策略停止回報" in result.evidence[0]
    assert "10/22 19:10" in result.evidence[0] and "12 次" in result.evidence[0] and "10/23 16:10" in result.evidence[0]   # 12th by schedule (08:10 UTC); the state file's last_at is only the last sample
    assert "2026-" not in text and "+00:00" not in text and "UTC" not in text                    # no raw ISO / UTC anywhere
    assert "【ERR-0xx】" in result.evidence[1] and "第 N 次提醒" in result.evidence[1] and "1 排到 12" in result.evidence[1]
    # nominal schedule: 30 min x 6, then every 3 hours (ops_notify.reminders)
    assert "第 1 次 10/22 19:40" in result.evidence[2] and "第 6 次 10/22 22:10" in result.evidence[2]
    assert "第 7 次 10/23 01:10" in result.evidence[2] and "第 12 次 10/23 16:10" in result.evidence[2]


def test_the_reminder_error_code_is_exact_when_the_value_is_known_and_lists_the_candidates_when_it_is_not():
    assert "ERR-045" in ow._reminder_errors("runtime", "ERROR") and "ERR-048" not in ow._reminder_errors("runtime", "SAFE_HALT")
    assert ow._reminder_errors("runtime", "UNAVAILABLE").startswith("ERR-048")
    both = ow._reminder_errors("runtime", None)
    assert "ERR-048" in both and "ERR-045" in both
    assert ow._reminder_errors("ledger", "DIVERGED").startswith("ERR-043") and ow._reminder_errors("google", None).startswith("ERR-044")
    # the episode was seen live with a stale reading, then ended: the ended notice still knows which error it was
    ended = _reminders_result(ended=True)
    assert "ERR-048" in ended.summary and "已停止提醒" in ended.evidence[0]


def test_the_reminder_error_codes_are_the_ones_the_axes_table_announces():
    spec = importlib.util.spec_from_file_location("render_guides_for_axes", _ROOT / "scripts" / "render_guides.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_guides_for_axes"] = module
    spec.loader.exec_module(module)
    catalog = json.loads((_ROOT / "src" / "trade_alerts" / "catalog" / "fleet-error-catalog-v2.json").read_text(encoding="utf-8"))
    by_code = {e["code"]: e["error_id"] for e in catalog["entries"]}
    axes = {key: [by_code[c] for c in codes] for _name, key, _meaning, codes in module.OPS_NOTIFY_AXES}
    for axis, options in ow._AXIS_ERRORS.items():
        for code, _title in options:
            assert code in axes[axis], (axis, code, axes[axis])
    assert set(ow._AXIS_ERRORS) == set(axes) and set(ow._AXIS_NAMES) == set(axes)


def test_times_shown_to_the_operator_are_taipei_time_whatever_the_source_zone():
    assert ow.taipei_text("2026-10-23T05:10:00+00:00") == "10/23 13:10（台北）"
    assert ow.taipei_text("2026-10-23T05:10:00Z") == "10/23 13:10（台北）"
    assert ow.taipei_text("2026-10-23T13:10:00+08:00") == "10/23 13:10（台北）"
    assert ow.taipei_text(None) == "（沒有）" and ow.taipei_text("not a time") == "not a time"
    assert ow.a1_journal_time("Oct 13 06:00:04", 2026) == "10/13 05:00（台北）"                  # the A1 journal runs on Tokyo time
    assert ow.a1_journal_time("garbage", 2026) == "garbage"


def test_the_status_alert_notice_shows_taipei_time_not_utc():
    remote = journal_remote(line(1, 2, 2))
    remote.files[("a1", "/var/lib/ops-notify/state.json")] = json.dumps(
        {"momentum:ledger": {"notified_at": "2026-10-23T00:50:00.991201+00:00"}})
    result = ow.check_status_alerts(ctx(remote))
    text = "\n".join(result.evidence)
    assert "UTC" not in text and "+00:00" not in text and "（台北）" in text


# --- f-70 batch 2: A1 stability, f-63 one entry a day, x5 stop, f-38 ------------------------------------------------------

B2_NOW = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)


def b2_ctx(remote, previous=None, now=B2_NOW):
    return ow.Context(remote, now, previous or {})


OPS_STATE = "/var/lib/ops-notify/state.json"
_AXIS_VALUES = {"runtime": "HEALTHY", "ledger": "RECONCILED", "google": "RECONCILED", "export": "OK", "units": "OK"}


def ops_readings(now=B2_NOW, **overrides):
    """ops-notify's per-axis readings for the four strategies and the host clock; ``overrides`` maps ``target:axis`` to a dict."""
    state = {}
    for target in (*ow.REPOS, "host"):
        for axis, value in (_AXIS_VALUES.items() if target != "host" else [("clock", "OK")]):
            state[f"{target}:{axis}"] = {"severity": "ok", "value": value,
                                         "checked_at": None if axis == "units" else iso(now - timedelta(minutes=5))}
    for key, patch in overrides.items():
        state[key.replace("__", ":")] = {**state[key.replace("__", ":")], **patch}
    return state


def ops_remote(now=B2_NOW, **overrides):
    r = FakeRemote()
    r.files[("a1", OPS_STATE)] = json.dumps({**ops_readings(now, **overrides), "_meta": {"consecutive_send_failures": 0}})
    return r


def test_a1_stable_starts_a_streak_and_announces_after_72_hours_only():
    first = ow.check_a1_stable(b2_ctx(ops_remote()))
    assert first.state == ow.WAITING and first.extra["healthy_since"] == iso(B2_NOW)
    prev = {"last_seen": iso(B2_NOW - timedelta(minutes=30))}
    early = ow.check_a1_stable(b2_ctx(ops_remote(), {**prev, "healthy_since": iso(B2_NOW - timedelta(hours=71))}))
    done = ow.check_a1_stable(b2_ctx(ops_remote(), {**prev, "healthy_since": iso(B2_NOW - timedelta(hours=73))}))
    assert early.state == ow.WAITING and not early.closable
    assert done.state == ow.OBSERVED and done.closable and not done.needs_human and done.key == "stable"
    assert "資金費同步" in done.summary                                                    # says what it did not read


@pytest.mark.parametrize("override", [
    {"mycrypto__runtime": {"severity": "critical", "value": "STALE"}},
    {"momentum__ledger": {"severity": "warn", "value": "DIVERGED"}},
    {"seykota__units": {"severity": "critical", "value": "FAILED"}},
    {"host__clock": {"value": "UNSYNCED"}},                                                # severity ok but not a healthy value
])
def test_a1_stable_any_unhealthy_reading_restarts_the_streak(override):
    prev = {"healthy_since": iso(B2_NOW - timedelta(hours=100)), "last_seen": iso(B2_NOW - timedelta(minutes=30))}
    result = ow.check_a1_stable(b2_ctx(ops_remote(**override), prev))
    assert result.state == ow.WAITING and not result.closable and "healthy_since" not in result.extra


def test_a1_stable_a_stale_reading_or_a_missing_target_is_an_error_not_a_pass():
    stale = ops_remote(**{"mycrypto__export": {"checked_at": iso(B2_NOW - timedelta(hours=3))}})
    with pytest.raises(ow.RemoteError):
        ow.check_a1_stable(b2_ctx(stale))
    r = FakeRemote()
    r.files[("a1", OPS_STATE)] = json.dumps({k: v for k, v in ops_readings().items() if not k.startswith("mycrypto")})
    with pytest.raises(ow.RemoteError):
        ow.check_a1_stable(b2_ctx(r))
    with pytest.raises(ow.RemoteError):
        ow.check_a1_stable(b2_ctx(FakeRemote()))


def test_a1_stable_a_run_that_could_not_read_ends_the_streak_over_a_144_run_cadence():
    check = next(c for c in ow.CHECKS if c.id == "a1-stable")
    state = {"items": ow.run_checks(ops_remote(B2_NOW), B2_NOW, {}, [check])}
    for step in range(1, 145):                                                            # one run every 30 minutes for 72 hours
        moment = B2_NOW + timedelta(minutes=30 * step)
        state = {"items": ow.run_checks(ops_remote(moment), moment, state, [check])}
        assert state["items"]["a1-stable"]["state"] == (ow.OBSERVED if step == 144 else ow.WAITING), step
    # healthy -> unreadable -> healthy again: the unobserved stretch is not counted
    state = {"items": ow.run_checks(ops_remote(B2_NOW), B2_NOW, {}, [check])}
    state = {"items": ow.run_checks(FakeRemote(), B2_NOW + timedelta(hours=25), state, [check])}
    assert state["items"]["a1-stable"]["state"] == ow.ERROR
    back = B2_NOW + timedelta(hours=73)
    entry = ow.run_checks(ops_remote(back), back, state, [check])["a1-stable"]
    assert entry["state"] == ow.WAITING and entry["extra"]["healthy_since"] == iso(back)


def test_the_stable_check_reads_no_new_path():
    assert OPS_STATE in ow.ALLOWED_PATHS and "/var/lib/ops-notify/state.json" == OPS_STATE


# f-63: one entry a day

def crypto_entry(day_hours_ago, trade_id, *, mode="LIVE", source="entry_signal", kind="trade_open", **extra):
    return {"event_type": kind, "event_time": iso(B2_NOW - timedelta(hours=day_hours_ago)), "event_id": f"{kind}-{trade_id}",
            "trade_id": trade_id, "execution_mode": mode, "source": source, **extra}


def crypto_remote(events, *, state=None, reconcile="RECONCILED", ledger_minutes=5):
    r = FakeRemote()
    put(r, "a1", "mycrypto", "trading_ledger.jsonl", events, jsonl=True)
    put(r, "a1", "mycrypto", "ledger_status.json", {"value": reconcile, "checked_at": iso(B2_NOW - timedelta(minutes=ledger_minutes)), "note": "n"})
    if state is not None:
        r.files[("a1", STATE_PATH)] = json.dumps(state)
    return r


@pytest.mark.parametrize("events", [
    [],
    [crypto_entry(2, "OLD", ) | {"event_time": "2026-10-22T06:24:00+00:00"}],               # before the reopening
    [crypto_entry(2, "T", mode="DEMO")],
    [crypto_entry(2, "T", source="backfilled_historical_trade")],
])
def test_one_entry_a_day_waits_without_a_countable_entry(events):
    assert ow.check_crypto_one_entry_a_day(b2_ctx(crypto_remote(events))).state == ow.WAITING


def test_one_entry_a_day_two_trades_on_one_utc_day_fails_at_once():
    events = [crypto_entry(2.5, "AAAAAAAA1"), crypto_entry(2, "BBBBBBBB2")]              # 00:30 and 01:00 UTC on 10/26
    result = ow.check_crypto_one_entry_a_day(b2_ctx(crypto_remote(events)))
    assert result.state == ow.FAILED and result.key == "2026-10-26" and "AAAAAAAA" in result.evidence[0]


def test_one_entry_a_day_a_pyramid_add_of_the_same_trade_is_not_a_second_entry():
    events = [crypto_entry(2.5, "T1"), crypto_entry(2, "T1")]
    assert ow.check_crypto_one_entry_a_day(b2_ctx(crypto_remote(events))).state == ow.WAITING


def test_one_entry_a_day_is_closable_only_after_the_entry_day_is_over():
    today = [crypto_entry(2, "T1")]                                                        # 01:00 UTC 10/26, "now" is 03:00 the same day
    waiting = ow.check_crypto_one_entry_a_day(b2_ctx(crypto_remote(today)))
    assert waiting.state == ow.WAITING and "UTC 午夜" in waiting.summary
    yesterday = [crypto_entry(10, "T1")]                                                   # 17:00 UTC 10/25
    done = ow.check_crypto_one_entry_a_day(b2_ctx(crypto_remote(yesterday)))
    assert done.state == ow.OBSERVED and done.closable and not done.needs_human and done.key == "2026-10-25"
    assert "沒有，還沒測到出場後同日再進場" in done.evidence[1]
    with_close = yesterday + [crypto_entry(9, "T1", kind="trade_close", source="trend_reversal")]
    assert "2026-10-25" in ow.check_crypto_one_entry_a_day(b2_ctx(crypto_remote(with_close))).evidence[1]


# x5: stop trigger and trailing stop on A1

def crypto_stop_state(order, price, trade="T1"):
    return {"trade_id": trade, "stop_plan_order_id": order, "active_stop_price": price}


def stop_run(events, order, price, previous=None, **kw):
    return ow.check_crypto_stop(b2_ctx(crypto_remote(events, state=crypto_stop_state(order, price), **kw), previous))


SHORT = [crypto_entry(40, "T1", side="short") | {"event_time": "2026-10-22T06:24:00+00:00"}]    # opened BEFORE the reopening, still held


def test_crypto_stop_waits_and_remembers_the_first_order_id():
    first = stop_run(SHORT, 111, 86800.0)
    assert first.state == ow.WAITING and first.extra["stops"] == {"T1": ["111"]}


def test_crypto_stop_sees_a_tightened_short_stop_as_a_move_and_never_closes():
    first = stop_run(SHORT, 111, 86800.0)
    second = stop_run(SHORT, 222, 85000.0, first.extra)
    assert second.state == ow.OBSERVED and second.needs_human and not second.closable and second.key == "move"
    assert "空窗" in second.summary
    assert stop_run(SHORT, 222, 85000.0, second.extra).key == "move"                       # announced once
    replaced = stop_run(SHORT, 333, 86800.0, first.extra)                                  # a new id with the same price is not a move
    assert replaced.state == ow.WAITING


def stop_close(hours, trade="T1", source="native_stop_reconciled", mode="LIVE"):
    return crypto_entry(hours, trade, kind="trade_close", source=source, mode=mode)


def test_crypto_stop_a_trigger_counts_only_once_the_reconcile_after_it_agrees():
    close = SHORT + [stop_close(2)]                                                         # 01:00 UTC; grace over at 02:01
    assert stop_run(close, 111, 86800.0, reconcile="RECONCILED").key == "stop"
    pending = stop_run(close, 111, 86800.0, reconcile="RECONCILED", ledger_minutes=90)       # checked 01:30: inside the grace / stale
    assert pending.state == ow.WAITING
    bad = stop_run(close, 111, 86800.0, reconcile="DIVERGED")
    assert bad.state == ow.FAILED and bad.key == "diverged:1"


@pytest.mark.parametrize("closing", [
    stop_close(2, source="trend_reversal"), stop_close(2, mode="DEMO"),
    crypto_entry(2, "T1", kind="trade_close", source="native_stop_price_estimate") | {"event_time": "2026-10-23T07:00:00+00:00"},   # before the reopening
])
def test_crypto_stop_other_closes_are_not_a_trigger(closing):
    assert stop_run(SHORT + [closing], 111, 86800.0).state == ow.WAITING


def test_crypto_stop_both_stages_have_their_own_key():
    first = stop_run(SHORT, 111, 86800.0)
    both = stop_run(SHORT + [stop_close(2)], 222, 85000.0, first.extra)
    assert both.key == "move|stop"


def test_crypto_stop_a_missing_state_file_is_flat_and_an_unreadable_one_is_an_error():
    r = crypto_remote(SHORT)                                                                 # no state file: flat
    assert ow.check_crypto_stop(b2_ctx(r)).state == ow.WAITING
    r.files[("a1", STATE_PATH)] = "not json"
    with pytest.raises(ow.RemoteError):
        ow.check_crypto_stop(b2_ctx(r))


# f-38: momentum safe-halt notice

def halt_remote(*, sent_after_minutes=None, delivered_extra=None, export_severity="ok", recorded_hours=2, baseline="2026-09-23T19:10:05+00:00",
                ai_pending=None, test=False):
    ev = event("PROTECTION_UNVERIFIED", hours=recorded_hours, test=test, event_id="E1")
    r = events_remote(momentum=[ev], baseline={"momentum": baseline}, ai_pending=ai_pending)
    state = json.loads(r.files[("a1", OPS_STATE)])
    if sent_after_minutes is not None:
        state["_export"]["momentum"]["delivered"] = {"E1": iso(NOW_AT(recorded_hours) + timedelta(minutes=sent_after_minutes))}
    else:
        state["_export"]["momentum"]["delivered"] = {}
    state["momentum:export"] = {"severity": export_severity, "value": "OK" if export_severity == "ok" else "STALE"}
    r.files[("a1", OPS_STATE)] = json.dumps(state)
    return r


def NOW_AT(hours):
    return NOW - timedelta(hours=hours)


def test_momentum_halt_waits_without_a_real_event_and_ignores_test_events_and_other_strategies():
    assert ow.check_momentum_halt_notice(ctx(events_remote())).state == ow.WAITING
    assert ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=3, test=True))).state == ow.WAITING
    other = events_remote(seykota=[event("PROTECTION_UNVERIFIED", event_id="S1")])
    assert ow.check_momentum_halt_notice(ctx(other)).state == ow.WAITING


def test_momentum_halt_delivered_in_time_with_a_healthy_export_is_closable():
    result = ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=11)))
    assert result.state == ow.OBSERVED and result.closable and not result.needs_human and result.key == "E1"
    assert "沒有直接讀檔案時間" in result.evidence[0]                                         # the proxy is stated


def test_momentum_halt_a_late_or_missing_notice_or_a_broken_export_fails():
    assert ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=16))).state == ow.FAILED
    assert ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=None))).state == ow.FAILED          # 2 h and never sent
    broken = ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=3, export_severity="critical")))
    assert broken.state == ow.FAILED and "匯出檔軸" in broken.summary
    stuck = ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=3, ai_pending={"momentum": {"E1": iso(NOW - timedelta(minutes=80))}})))
    assert stuck.state == ow.FAILED


def test_momentum_halt_a_fresh_event_is_waiting_and_a_baseline_mark_is_not_proof():
    assert ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=None, recorded_hours=0))).state == ow.WAITING
    marked = ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=0, baseline=iso(NOW))))
    assert marked.state == ow.OBSERVED and marked.needs_human and not marked.closable


def test_batch2_checks_are_registered_with_their_items():
    ids = {c.id: c for c in ow.CHECKS}
    assert ids["a1-stable"].covers == ("phase-x8", "f-63", "phase-x5")
    assert ids["crypto-one-entry-a-day"].covers == ("f-63",) and ids["crypto-stop"].covers == ("phase-x5",)
    assert ids["momentum-halt-notice"].covers == ("f-38",)


# --- review of #306 (BLOCK-306-01 / 02, f-38 export axis) ----------------------------------------------------------------------

LONG_STREAK = {"healthy_since": iso(B2_NOW - timedelta(hours=100)), "last_seen": iso(B2_NOW - timedelta(minutes=30))}


def test_the_stability_check_needs_exactly_the_21_required_readings():
    assert len(ow.REQUIRED_READINGS) == 21 and len(set(ow.REQUIRED_READINGS)) == 21
    assert set(ow.REQUIRED_READINGS) == set(ops_readings())


@pytest.mark.parametrize("axis", ow.REQUIRED_READINGS)
def test_a1_stable_any_single_missing_reading_is_an_error_never_a_streak(axis):
    """BLOCK-306-01: the target is still there, only one of its axes is not -- with a 100-hour streak stored it must not close."""
    state = ops_readings()
    del state[axis]
    r = FakeRemote()
    r.files[("a1", OPS_STATE)] = json.dumps(state)
    with pytest.raises(ow.RemoteError):
        ow.check_a1_stable(b2_ctx(r, LONG_STREAK))


def test_a1_stable_five_runtime_readings_alone_cannot_close():
    state = {k: v for k, v in ops_readings().items() if k.endswith(":runtime") or k == "host:clock"}
    r = FakeRemote()
    r.files[("a1", OPS_STATE)] = json.dumps(state)
    with pytest.raises(ow.RemoteError):
        ow.check_a1_stable(b2_ctx(r, LONG_STREAK))


@pytest.mark.parametrize("reading", [
    {"checked_at": None}, {"checked_at": ""}, {"checked_at": "garbage"}, {"checked_at": iso(B2_NOW - timedelta(hours=3))},
    {"checked_at": iso(B2_NOW + timedelta(hours=3))}, "not an object", None,
])
@pytest.mark.parametrize("axis", ["mycrypto__runtime", "momentum__ledger", "seykota__google", "btc-competition__export", "host__clock"])
def test_a1_stable_a_timestamped_axis_without_a_usable_checked_at_is_an_error(axis, reading):
    """BLOCK-306-02: only the units axis may lack ``checked_at``; every other one must have a parseable fresh time."""
    state = ops_readings()
    state[axis.replace("__", ":")] = reading if not isinstance(reading, dict) else {**state[axis.replace("__", ":")], **reading}
    if reading is None:
        state[axis.replace("__", ":")] = None
    r = FakeRemote()
    r.files[("a1", OPS_STATE)] = json.dumps(state)
    with pytest.raises(ow.RemoteError):
        ow.check_a1_stable(b2_ctx(r, LONG_STREAK))


def test_a1_stable_only_the_units_axis_may_lack_a_timestamp_and_a_bad_one_there_still_fails():
    ok = ow.check_a1_stable(b2_ctx(ops_remote(), LONG_STREAK))
    assert ok.state == ow.OBSERVED and ow._NO_TIMESTAMP_AXES == {"units"}
    for bad in ("garbage", iso(B2_NOW - timedelta(hours=3))):
        with pytest.raises(ow.RemoteError):
            ow.check_a1_stable(b2_ctx(ops_remote(**{"momentum__units": {"checked_at": bad}}), LONG_STREAK))
    assert ops_readings()["seykota:units"]["checked_at"] is None                        # the fixture really models the by-design gap


@pytest.mark.parametrize("reading", [None, {}, {"value": "OK"}, {"severity": None, "value": "OK"}, {"severity": 1}, "ok"])
def test_momentum_halt_a_missing_or_severity_less_export_reading_is_an_error_not_closable(reading):
    r = halt_remote(sent_after_minutes=3)
    state = json.loads(r.files[("a1", OPS_STATE)])
    if reading is None:
        del state["momentum:export"]
    else:
        state["momentum:export"] = reading
    r.files[("a1", OPS_STATE)] = json.dumps(state)
    with pytest.raises(ow.RemoteError):
        ow.check_momentum_halt_notice(ctx(r))


def test_momentum_halt_only_an_ok_export_severity_closes():
    for severity in ("warn", "critical", "OK", ""):
        assert ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=3, export_severity=severity))).state == ow.FAILED, severity
    assert ow.check_momentum_halt_notice(ctx(halt_remote(sent_after_minutes=3))).closable
