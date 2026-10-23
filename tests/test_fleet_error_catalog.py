"""The fleet error catalog is data the Phase 4 queue will be built on, so the
invariants that make it usable are asserted here rather than left to review.

The formal JSON Schema check needs ``jsonschema``, which is deliberately not a
dependency of this library (nothing at runtime reads the catalog).  The
structural invariants below run unconditionally and are what actually matters:
a schema can say "risk_tier is one of five strings", it cannot say "a
MECHANICAL verdict must not end up in a tier that notifies a human".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = _ROOT / "src" / "trade_alerts" / "catalog" / "fleet-error-catalog-v2.json"
SCHEMA_PATH = _ROOT / "schemas" / "fleet-error-catalog-v2.schema.json"


@pytest.fixture(scope="module")
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_matches_its_json_schema(catalog):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(catalog))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


def test_codes_are_unique(catalog):
    codes = [entry["code"] for entry in catalog["entries"]]
    assert len(codes) == len(set(codes))


def test_every_entry_names_a_known_project(catalog):
    known = set(catalog["projects"])
    assert {entry["project"] for entry in catalog["entries"]} <= known


def test_code_prefix_agrees_with_project(catalog):
    prefix_for = {
        "seykota": "SEY", "momentum": "MOM", "mycrypto": "MYC",
        "btc-competition": "BTC", "fleet": "FLEET",
    }
    for entry in catalog["entries"]:
        assert entry["code"].split(".", 1)[0] == prefix_for[entry["project"]], entry["code"]


def test_mechanical_verdicts_never_reach_a_notifying_tier(catalog):
    """The governing test of the whole project: if a human cannot decide
    anything different, the condition must not be able to page one.  In v2 the
    two silent tiers are R0 (log) and R1 (automatic), so MECHANICAL is limited
    to those and the tiers that can reach a human (R2 once escalated, R3) are
    reserved for JUDGEMENT."""
    tiers = catalog["risk_tiers"]
    for entry in catalog["entries"]:
        tier = tiers[entry["risk_tier"]]
        if entry["verdict"] == "MECHANICAL":
            assert not tier["notifies"], entry["code"]
        else:
            assert tier["notifies"], entry["code"]


def test_v2_tier_semantics(catalog):
    """fleet-error-catalog/v2 (2026-09-18): R0 log, R1 automatic and silent, R2
    automatic with escalation after ``escalate_after`` failures, R3 human only.
    v1's after-the-fact audit notice is gone: an R1 action has no second
    option, so telling someone about it asks nothing of them."""
    tiers = catalog["risk_tiers"]
    assert set(tiers) == {"R0", "R1", "R2", "R3"}
    assert (tiers["R0"]["notifies"], tiers["R0"]["auto_executes"]) == (False, False)
    assert (tiers["R1"]["notifies"], tiers["R1"]["auto_executes"]) == (False, True)
    assert (tiers["R2"]["notifies"], tiers["R2"]["auto_executes"]) == (True, True)
    assert (tiers["R3"]["notifies"], tiers["R3"]["auto_executes"]) == (True, False)
    assert all("audit_notice" not in tier for tier in tiers.values())


def test_only_r2_escalates_and_it_says_after_how_many_failures(catalog):
    tiers = catalog["risk_tiers"]
    assert isinstance(tiers["R2"].get("escalate_after"), int) and tiers["R2"]["escalate_after"] >= 1
    assert [name for name, tier in tiers.items() if "escalate_after" in tier] == ["R2"]


def test_retired_codes_are_never_reused(catalog):
    """A retired code stays retired: an entry may keep one only while its call
    site still exists and is on its way out, and its own reason must say so."""
    retired = {item["code"]: item for item in catalog["retired_codes"]}
    assert retired, "v2 retires at least the v1 proposal codes"
    live = {entry["code"] for entry in catalog["entries"]}
    for code in retired.keys() & live:
        assert "until" in retired[code]["reason"].lower() or "直到" in retired[code]["reason"], code


def test_only_judgement_conditions_latch_after_phase_4(catalog):
    """A latch stops a strategy from trading.  Nothing whose verdict is
    MECHANICAL may keep one."""
    for entry in catalog["entries"]:
        if entry["current"]["latch"] and entry["verdict"] == "MECHANICAL":
            assert entry["resume"] == "automatic", entry["code"]


def test_latching_conditions_declare_a_resume_path(catalog):
    """seykota's original defect was eight latch reasons and no way back.
    Every condition that can latch must name how it is cleared."""
    for entry in catalog["entries"]:
        if entry["current"]["latch"]:
            assert entry["resume"] != "n/a", entry["code"]


def test_r0_conditions_do_not_burn_a_unit_exit_code(catalog):
    """An exit code is a notification channel.  An R0 condition that still
    exits non-zero is notifying through systemd behind the catalog's back --
    allowed only while the change is still scheduled for a later phase."""
    for entry in catalog["entries"]:
        if entry["risk_tier"] == "R0" and entry["current"]["unit_exit"]:
            assert entry["lands_in_phase"] > 3, entry["code"]


def test_sources_look_like_file_line_references(catalog):
    for entry in catalog["entries"]:
        for source in entry["sources"]:
            path, _, line = source.rpartition(":")
            assert path and line.isdigit(), source


def test_operator_messages_have_all_three_parts(catalog):
    """An operator_message is what a phone shows when the condition pages
    someone.  A missing "what", "direction" or step list would send a message
    that says something is wrong without saying what to do -- exactly the
    notification the whole project set out to stop sending.  Checked here as
    well as in the schema because jsonschema is optional."""
    for entry in catalog["entries"]:
        message = entry.get("operator_message")
        if message is None:
            continue
        assert set(message) <= {"what", "direction", "steps", "ai_prompt"}, entry["code"]
        assert isinstance(message["what"], str) and message["what"].strip(), entry["code"]
        assert isinstance(message["direction"], str) and message["direction"].strip(), entry["code"]
        assert isinstance(message["steps"], list) and message["steps"], entry["code"]
        for step in message["steps"]:
            assert isinstance(step, str) and step.strip(), entry["code"]


def test_every_entry_has_an_operator_message(catalog):
    """v2: every entry, not just the ones already wired to ops-notify -- the
    generated risk register page reads its plain-language text from here, and
    "write it when the strategy is connected" is how v1 ended up with 3 of 33."""
    for entry in catalog["entries"]:
        assert "operator_message" in entry, entry["code"]


def test_tiers_that_reach_a_human_carry_an_ai_prompt(catalog):
    """An R2 escalation or an R3 stop hands the operator a problem the machine
    could not solve; the message must include a prompt an AI can use to trace
    the root cause, not just "go look"."""
    for entry in catalog["entries"]:
        prompt = entry["operator_message"].get("ai_prompt")
        if entry["risk_tier"] in ("R2", "R3"):
            assert isinstance(prompt, str) and prompt.strip(), entry["code"]
        else:
            assert prompt is None, entry["code"]


def test_packaged_catalog_is_the_file_the_tests_read():
    from trade_alerts import load_error_catalog

    assert load_error_catalog() == json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_both_proposed_codes_are_retired_and_removed_together(catalog):
    """The two repair bots' v1 "propose only" code was catalogued symmetrically
    (a missing seykota entry once hid its bot from the register); since v2-W6
    put the shared repair runner on the live host, both entries are gone and
    both codes stay in retired_codes so they are never reused."""
    codes = {"MOM.VERIFIED_CLOSE_PROPOSED", "SEY.VERIFIED_CLOSE_PROPOSED"}
    assert not codes & {entry["code"] for entry in catalog["entries"]}
    assert codes <= {item["code"] for item in catalog["retired_codes"]}


def test_error_ids_are_dense_unique_and_never_reused(catalog):
    """e1: every entry has a fixed ERR-NNN number, one fleet-wide sequence.
    Every number from ERR-001 up to error_ids_issued appears exactly once
    across entries and retired_codes -- so deleting an entry without moving
    its number to retired_codes, reusing a retired number, or skipping ahead
    all fail here."""
    import re

    live = [entry["error_id"] for entry in catalog["entries"]]
    retired = [item["error_id"] for item in catalog["retired_codes"] if "error_id" in item]
    issued = catalog["error_ids_issued"]
    for number in live + retired:
        assert re.fullmatch(r"ERR-\d{3}", number), number
    assert len(live + retired) == len(set(live + retired)), "an error number is used twice"
    assert sorted(live + retired) == [f"ERR-{n:03d}" for n in range(1, issued + 1)]


def test_error_id_is_shown_on_both_register_pages(catalog):
    from importlib import util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = util.spec_from_file_location("render_guides", root / "scripts" / "render_guides.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pages = {path.name: html for path, html in module.rendered_pages().items()}
    first = catalog["entries"][0]
    risk_data = json.loads(re.search(r'<script type="application/json" id="data">\n(.*?)\n</script>', pages["fleet-risk-register.html"], re.S)
                           .group(1).replace("<\\/", "</"))
    assert any(e["error_id"] == first["error_id"] and e["code"] == first["code"] for e in risk_data["entries"])
    assert f'{first["error_id"]} · {first["code"]}' in pages["fleet-rollout-register.html"]


def test_retiring_an_entry_keeps_its_error_id_in_retired_codes(catalog):
    """#87 review follow-up: the positive case. Moving a live entry (with its
    error_id) into retired_codes keeps the sequence valid; dropping the number
    on the way out, or giving it to a new entry, does not."""
    import copy
    import re

    def valid(cat):
        live = [e["error_id"] for e in cat["entries"]]
        retired = [i["error_id"] for i in cat["retired_codes"] if "error_id" in i]
        ids = live + retired
        return (all(re.fullmatch(r"ERR-\d{3}", n) for n in ids) and len(ids) == len(set(ids))
                and sorted(ids) == [f"ERR-{n:03d}" for n in range(1, cat["error_ids_issued"] + 1)])

    cat = copy.deepcopy(catalog)
    gone = cat["entries"].pop(3)
    assert not valid(cat), "a retired entry that drops its number must fail"
    cat["retired_codes"].append({"code": gone["code"], "retired_in": "fleet-error-catalog/v2",
                                 "reason": "test", "error_id": gone["error_id"]})
    assert valid(cat)
    cat["entries"].append({**cat["entries"][0], "code": "FLEET.TEST_REUSE", "error_id": gone["error_id"]})
    assert not valid(cat), "reusing a retired number must fail"


# --- f-35: the steps an operator pastes into a terminal must run as written on the production host ----------------
#
# 2026-10-11: the A1 controlled test showed notices telling the operator to run `python src/...`,
# `seykota-resume preview` or `systemctl start ...`.  On A1 there is no `python`, the resume tools live only in each
# strategy's .venv/bin (not on PATH) and must run as the strategy's service account from /opt/<repo> (root/ubuntu would
# change the state file's owner), and systemctl needs sudo.

import re  # noqa: E402

_TOOL_HOMES = {
    "seykota": ("ed-seykota-systematic-trend-following", "seykota"),
    "momentum": ("mexc-4h-momentum-trailing-stop", "mexc-momentum"),
    "btc-competition": ("btc-bull-market-competition", "btc-competition"),
}
_TOOL_WORDS = re.compile(r"resume|safe_halt_resume\.py|append_trade_correction\.py|reconcile_apply\.py")


def _command_spans(entry):
    for number, step in enumerate(entry["operator_message"]["steps"], start=1):
        for span in re.findall(r"`([^`]+)`", step):
            yield number, span


def _allowed_homes(entry):
    # the fleet-level "strategy halted" entry (ERR-045) lists every strategy's own tool
    homes = list(_TOOL_HOMES.values()) if entry["project"] == "fleet" else [_TOOL_HOMES.get(entry["project"])]
    return [h for h in homes if h]


def test_pasted_commands_run_as_the_service_account_from_the_repo_directory(catalog):
    problems = []
    for entry in catalog["entries"]:
        for number, span in _command_spans(entry):
            where = f"{entry['error_id']} step {number}"
            if span.startswith("python ") or span.startswith("python3 "):
                problems.append(f"{where}: bare python (no such command on A1; use the repo's .venv/bin/python): {span[:70]}")
            if span.startswith("systemctl"):
                problems.append(f"{where}: systemctl without sudo: {span[:70]}")
            if not _TOOL_WORDS.search(span):
                continue
            homes = _allowed_homes(entry)
            ok = any(
                span.startswith(f"cd /opt/{repo} && sudo -u {svc} .venv/bin/")
                or span.startswith(f"sudo -u {svc} bash -c 'cd /opt/{repo} && ")
                for repo, svc in homes
            )
            if not ok:
                problems.append(f"{where}: tool command is not `cd /opt/<repo> && sudo -u <service account> .venv/bin/...`: {span[:80]}")
    assert not problems, "\n".join(problems)


def test_steps_name_the_host_with_the_glossary_wording(catalog):
    # Until trading-main is retired the glossary forbids a bare 「正式機」 for a host (fleet-glossary.json).
    problems = []
    for entry in catalog["entries"]:
        text = json.dumps(entry["operator_message"], ensure_ascii=False)
        for found in re.finditer("正式機", text):
            around = text[max(0, found.start() - 14):found.end() + 4]
            if "A1 正式機（新）" not in around and "trading-main 正式機（舊）" not in around:
                problems.append(f"{entry['error_id']}: {around!r}")
    assert not problems, "\n".join(problems)


def test_bash_c_commands_carry_their_flags_inside_the_quotes(catalog):
    # Review #173 BLOCK-173-01: "append --apply --confirm to the same command" after a `bash -c '...'` preview puts the
    # flags after the closing quote, where bash hands them to the shell ($0, $1), not to the tool -- the tool then
    # silently previews again.  A span that wraps the tool in `bash -c '...'` must end with the closing quote, and a
    # step may not tell the operator to "add to the end of the same command".
    problems = []
    for entry in catalog["entries"]:
        for number, step in enumerate(entry["operator_message"]["steps"], start=1):
            where = f"{entry['error_id']} step {number}"
            if "同一個指令最後加上" in step or "同一個指令最後加" in step:
                problems.append(f"{where}: tells the operator to append flags to a command; give the full command")
            for span in re.findall(r"`([^`]+)`", step):
                if "bash -c '" in span and not span.endswith("'"):
                    problems.append(f"{where}: bash -c span has text after the closing quote: ...{span[-40:]}")
    assert not problems, "\n".join(problems)


def test_correction_tool_steps_give_both_the_preview_and_the_apply_command_and_say_closed_only(catalog):
    # append_trade_correction.py only accepts a CLOSED trade that has a trade_open (trade_alerts.trade_correction):
    # an operator on an open position must be told not to run it (review #173 BLOCK-173-02).
    for error_id in ("ERR-007", "ERR-037"):
        entry = next(e for e in catalog["entries"] if e["error_id"] == error_id)
        text = " ".join(entry["operator_message"]["steps"])
        spans = [s for s in re.findall(r"`([^`]+)`", text) if "append_trade_correction.py" in s]
        assert len(spans) == 2, (error_id, spans)
        preview, apply_ = spans
        assert "--apply" not in preview and "--confirm" not in preview
        assert apply_.endswith(' --apply --confirm "<確認碼>"\'')        # inside the closing quote
        assert apply_.replace(' --apply --confirm "<確認碼>"', "") == preview
        assert "已平倉" in text
    err037 = next(e for e in catalog["entries"] if e["error_id"] == "ERR-037")
    text037 = " ".join(err037["operator_message"]["steps"])
    assert "trade_close" in text037 and "還開著" in text037 and "不要硬做" in text037


# --- f-37: a placeholder the operator must replace is ONE quoted word -------------------------------------------------
#
# 2026-10-12 (ops-notify #49 review): an unquoted `<確認碼>` is an input redirection in bash -- pasting it as written
# fails with "No such file or directory".  The f-35 tests only split the command with shlex, which does not judge that.

import subprocess  # noqa: E402


def _outside_quotes(script):
    """Characters of ``script`` that bash sees outside any quote (backslash escapes honoured)."""
    out, quote, i = [], None, 0
    while i < len(script):
        c = script[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(script):
                i += 2
                continue
            if c == quote:
                quote = None
        elif c == "\\" and i + 1 < len(script):
            i += 2                                       # an escaped character is a literal, not syntax
            continue
        elif c in "'\"":
            quote = c
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _inner_script(span):
    """The script handed to ``bash -c '...'`` (the outer quotes are single), or None."""
    if "bash -c '" not in span or not span.endswith("'"):
        return None
    return span.split("bash -c '", 1)[1][:-1]


def _placeholder_problems(span):
    problems = []
    for text in (span, _inner_script(span)):
        if text is None:
            continue
        bare = _outside_quotes(text)
        # a `bash -c '...'` span: everything inside the outer single quotes is the inner script, checked on its own
        if "<" in bare or ">" in bare:
            problems.append(f"unquoted < or > (a redirection in bash): {span[:90]}")
        parsed = subprocess.run(["bash", "-n", "-c", text], capture_output=True, text=True)
        if parsed.returncode != 0:
            problems.append(f"bash -n refuses it ({parsed.stderr.strip()[:60]}): {span[:90]}")
    return problems


def test_every_pasted_command_is_valid_bash_and_has_no_unquoted_placeholder(catalog):
    problems = []
    for entry in catalog["entries"]:
        for number, span in _command_spans(entry):
            if re.search(r"sudo|\.venv/bin|cd /opt|systemctl|journalctl", span):
                problems += [f"{entry['error_id']} step {number}: {p}" for p in _placeholder_problems(span)]
    assert not problems, "\n".join(problems)


def test_the_catalog_does_have_quoted_placeholders_to_check(catalog):
    # a guard that sees no placeholder at all would pass for the wrong reason
    spans = [s for e in catalog["entries"] for _n, s in _command_spans(e) if "<" in s]
    assert len(spans) >= 10 and all("<確認碼>" in s or "<交易編號>" in s or "<金額>" in s for s in spans)
    assert any(_inner_script(s) is not None for s in spans)


@pytest.mark.parametrize("span", [
    "cd /opt/x && sudo -u u .venv/bin/t resume --confirm <確認碼> --exchange-verified",                  # the f-35 mistake
    "cd /opt/x && sudo -u u .venv/bin/t --confirm <確認碼>",
    "sudo -u u bash -c 'cd /opt/x && .venv/bin/python s.py --trade-id <交易編號> --reason \"r\"'",       # nested, unquoted
    "cd /opt/x && sudo -u u .venv/bin/t --confirm '<確認碼>",                                          # unbalanced quote
    "cd /opt/x && sudo -u u .venv/bin/t --out > /tmp/x",                                              # a real redirection
    "cd /opt/x && sudo -u u .venv/bin/t --a \\<b\\> <c>",
])
def test_the_placeholder_check_rejects_what_fails_in_bash(span):
    assert _placeholder_problems(span) != []


@pytest.mark.parametrize("span", [
    'cd /opt/x && sudo -u u .venv/bin/t resume --confirm "<確認碼>" --exchange-verified',
    "cd /opt/x && sudo -u u .venv/bin/t resume --confirm '<確認碼>'",
    "sudo -u u bash -c 'cd /opt/x && .venv/bin/python s.py --trade-id \"<交易編號>\" --reason \"<原因>\"'",
    "cd /opt/x && sudo -u u .venv/bin/t --a \\<b\\>",
])
def test_the_placeholder_check_accepts_quoted_or_escaped_placeholders(span):
    assert _placeholder_problems(span) == []


def test_a_quoted_placeholder_reaches_the_tool_as_one_argument():
    # run the real shell on the shape the catalog now uses, with printf in place of the tool
    out = subprocess.run(["bash", "-c", 'printf "%s\\n" resume --confirm "<確認碼>" --exchange-verified'],
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.split("\n")[:4] == ["resume", "--confirm", "<確認碼>", "--exchange-verified"]
    bad = subprocess.run(["bash", "-c", "printf %s resume --confirm <確認碼>"], capture_output=True, text=True)
    assert bad.returncode != 0


# --- f-41: the status alerts' second message carries read-only commands that run as pasted on A1 --------------------
#
# 2026-10-13: the main message of ERR-043/044/046/047/048/049 only says "look at which strategy / service"; the pasteable
# commands that ops-notify used to hardcode (f-36) were lost when f-40 switched it to the catalog's text.  The operator
# decided the commands belong in the SECOND message (the paste-to-AI one), so they live in `ai_prompt`.

_STATUS_AI_CODES = ("ERR-043", "ERR-044", "ERR-046", "ERR-047", "ERR-048", "ERR-049")
_FLEET_REPOS = {"ed-seykota-systematic-trend-following", "mexc-4h-momentum-trailing-stop", "my-crypto-bot",
                "btc-bull-market-competition"}
# Anything not on this list is not a read-only command we vouch for: only look, never change.
_READ_ONLY_SPAN = re.compile(
    r"^sudo (?:"
    r"cat /opt/(?P<cat_repo>[a-z0-9-]+)/audit/(?:ledger_status|google_reconcile_status)\.json"
    r"|ls -l --time-style=full-iso /opt/(?P<ls_repo>[a-z0-9-]+)/audit/ops_export\.json"
    r"|cat /var/lib/clock-health/clock_status\.json"
    r"|journalctl (?:-u [a-z0-9-]+\.service -n \d{1,3}|-p err -n \d{1,3}) --no-pager"
    r"|systemctl (?:status [a-z0-9-]+(?:\.(?:service|timer))?|list-timers|list-units --state=failed) --no-pager"
    r"|chronyc tracking)$")


def _read_only_match(span):
    """The one place a span is judged against the whitelist: the WHOLE span must match (f-42: fullmatch, not `match` + `$`)."""
    return _READ_ONLY_SPAN.fullmatch(span)


def _ai_spans(entry):
    return re.findall(r"`([^`]+)`", entry["operator_message"].get("ai_prompt") or "")


def test_status_alert_second_messages_carry_commands(catalog):
    by_id = {e["error_id"]: e for e in catalog["entries"]}
    for error_id in _STATUS_AI_CODES:
        assert _ai_spans(by_id[error_id]), f"{error_id}: the paste-to-AI message has no pasteable command"


def test_status_alert_commands_are_read_only_and_name_real_paths(catalog):
    problems = []
    for entry in catalog["entries"]:
        if entry["error_id"] not in _STATUS_AI_CODES:
            continue
        for span in _ai_spans(entry):
            matched = _read_only_match(span)
            if not matched:
                problems.append(f"{entry['error_id']}: not a vouched read-only command: {span[:90]}")
                continue
            repo = matched.group("cat_repo") or matched.group("ls_repo")
            if repo and repo not in _FLEET_REPOS:
                problems.append(f"{entry['error_id']}: unknown repo directory /opt/{repo}")
    assert not problems, "\n".join(problems)


def test_status_alert_commands_are_valid_bash_with_no_unquoted_placeholder(catalog):
    problems = []
    for entry in catalog["entries"]:
        if entry["error_id"] in _STATUS_AI_CODES:
            problems += [f"{entry['error_id']}: {p}" for span in _ai_spans(entry) for p in _placeholder_problems(span)]
    assert not problems, "\n".join(problems)


def test_other_ai_prompts_are_not_loaded_with_unvetted_commands(catalog):
    # Only the six status alerts were given commands; a command appearing in any other prompt must come with its own review.
    for entry in catalog["entries"]:
        if entry["error_id"] not in _STATUS_AI_CODES:
            assert not _ai_spans(entry), f"{entry['error_id']}: a command in ai_prompt needs its own vetting"


def test_second_message_renders_the_commands():
    from trade_alerts.ops_export import render_ai_text
    entry = [e for e in json.loads((CATALOG_PATH).read_text(encoding="utf-8"))["entries"] if e["error_id"] == "ERR-046"][0]
    text = render_ai_text({"project": "fleet", "code": "FLEET.OPS_UNIT_FAILED", "event_id": "e1", "evidence": {}}, entry)
    assert "sudo systemctl list-units --state=failed --no-pager" in text and text.splitlines()[0].startswith("【ERR-046】")


def test_the_read_only_whitelist_matches_the_whole_span_not_a_prefix_with_a_trailing_newline():
    # f-42 (review of #180): `$` also matches just before a final newline, so `re.match(... $)` would let
    # "sudo cat /opt/x/audit/ledger_status.json\n" through.  fullmatch must reject it, and still accept the plain command.
    good = "sudo cat /opt/mexc-4h-momentum-trailing-stop/audit/ledger_status.json"
    assert _read_only_match(good)
    assert not _read_only_match(good + "\n")
    assert not _read_only_match(good + " ; rm -rf /")
