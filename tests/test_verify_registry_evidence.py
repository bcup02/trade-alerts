"""``scripts/verify_registry_evidence.py`` must notice when changing a ``sources``
commit moves a cited line onto different code -- the gap that let 108 citations
point elsewhere on 2026-10-04 while the script said "0 problem(s)".  Each test
builds a throwaway clone with an old and a new commit and compares registries
that cite it.
"""
from __future__ import annotations

import copy
import importlib.util
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("verify_registry_evidence", _ROOT / "scripts" / "verify_registry_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _script()

OLD_BOT = """import os


def alpha():
    value = load()
    return value


def beta():
    value = load()
    return None
"""

# Three lines are inserted at the top, so every cited line shifts by 3; beta()
# also gains a line, and gamma() reuses the text "return None".
NEW_BOT = """import os
import sys
import json


def alpha():
    value = load()
    return value


def beta():
    check()
    value = load()
    return None


def gamma():
    return None
"""


def _git(clone: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin:/usr/local/bin"}
    return subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture()
def clones(tmp_path):
    clone = tmp_path / "bot-repo"
    clone.mkdir()
    _git(clone, "init", "-q")
    (clone / "src").mkdir()
    (clone / "src" / "bot.py").write_text(OLD_BOT, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "old")
    old = _git(clone, "rev-parse", "HEAD")
    (clone / "src" / "bot.py").write_text(NEW_BOT, encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "new")
    new = _git(clone, "rev-parse", "HEAD")
    return tmp_path, old, new


def _registry(commit: str, evidence: str, reason: str | None = None) -> dict:
    status = {"state": "done", "evidence": evidence}
    if reason is not None:
        status["reason"] = reason
    return {
        "sources": {"p": {"repo": "owner/bot-repo", "branch": "operations", "commit": commit}},
        "capabilities": [{"id": "cap.x", "status": {"p": status}}],
        "catalog": [],
    }


def _reader(root: Path, registry: dict):
    def read(project, commit, path):
        content = script._show(root / registry["sources"][project]["repo"].split("/", 1)[1], commit, path)
        return script._lines(content) if content is not None else None
    return read


def _drift(root, old_registry, new_registry):
    return script.drift(old_registry, new_registry, _reader(root, new_registry))


def test_same_line_number_on_a_new_commit_is_flagged_when_the_text_moved(clones):
    root, old, new = clones
    # old line 5 is "value = load()" in alpha(); at the same number in the new commit it is a blank line.
    report = _drift(root, _registry(old, "src/bot.py:5"), _registry(new, "src/bot.py:5"))
    assert report["compared"] == 1
    assert [(m["kind"], m["reason"][:17]) for m in report["mismatches"]] == [("shifted", "line text differs")]


def test_relocated_citation_to_the_same_text_passes(clones):
    root, old, new = clones
    report = _drift(root, _registry(old, "src/bot.py:5"), _registry(new, "src/bot.py:7"))
    assert report["compared"] == 1 and report["mismatches"] == []


def test_same_text_in_a_different_function_is_flagged(clones):
    root, old, new = clones
    # old :11 is "return None" in beta(); new :18 is "return None" in gamma().
    report = _drift(root, _registry(old, "src/bot.py:11"), _registry(new, "src/bot.py:18"))
    # beta()'s "return None" is still in beta() -- the citation now points at the wrong function.
    assert [(m["kind"], m["reason"]) for m in report["mismatches"]] == [("shifted", "same text but in gamma (was beta)")]


def test_unchanged_commit_is_not_compared(clones):
    root, old, _new = clones
    report = _drift(root, _registry(old, "src/bot.py:5"), _registry(old, "src/bot.py:5"))
    assert report == {"mismatches": [], "unpaired": [], "compared": 0, "skipped": 0}


def test_a_citation_that_gains_a_partner_in_another_file_is_unpaired_but_the_rest_still_compare(clones):
    root, old, new = clones
    report = _drift(root, _registry(old, "src/bot.py:5"), _registry(new, "src/bot.py:7 以及 src/other.py:3"))
    assert report["mismatches"] == [] and report["compared"] == 1
    assert report["unpaired"] == [{"where": "capability cap.x", "project": "p", "old": [], "new": ["src/other.py:3"]}]


def test_bare_line_shorthand_and_reason_text_are_compared(clones):
    root, old, new = clones
    report = _drift(root, _registry(old, "src/bot.py:5", "同檔 :6"), _registry(new, "src/bot.py:7", "同檔 :6"))
    # :6 was "return value"; the new :6 is "def alpha():" -- the bare line in the reason is checked.
    assert [(m["old_line"], m["new_line"]) for m in report["mismatches"]] == [(6, 6)]


def test_relocation_moves_citations_in_evidence_and_reason_and_leaves_correct_ones(clones):
    root, old, new = clones
    old_registry = _registry(old, "src/bot.py:5 先載入，:6 再回傳", "見 src/bot.py:11")
    new_registry = copy.deepcopy(old_registry)
    new_registry["sources"]["p"]["commit"] = new
    report = _drift(root, old_registry, new_registry)
    moved, unresolved = script.apply_relocation(report)
    status = new_registry["capabilities"][0]["status"]["p"]
    # :5 -> 7, :6 -> 8 (alpha), :11 "return None" -> 14 (beta, not gamma's :18).
    assert status["evidence"] == "src/bot.py:7 先載入，:8 再回傳"
    assert status["reason"] == "見 src/bot.py:14"
    assert len(moved) == 3 and unresolved == []
    assert _drift(root, old_registry, new_registry)["mismatches"] == []


def test_relocation_reports_what_it_cannot_place(clones):
    root, old, _new = clones
    clone = root / "bot-repo"
    (clone / "src" / "bot.py").write_text(NEW_BOT.replace("def beta():", "def renamed():"), encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "rename")
    renamed = _git(clone, "rev-parse", "HEAD")
    (clone / "src" / "bot.py").write_text("x = 1\n", encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "gone")
    gone = _git(clone, "rev-parse", "HEAD")
    # beta() was renamed: "return None" still exists, but only outside beta -- not guessed.
    report = _drift(root, _registry(old, "src/bot.py:11"), _registry(renamed, "src/bot.py:11"))
    assert [m["kind"] for m in report["mismatches"]] == ["changed"]
    moved, unresolved = script.apply_relocation(report)
    assert moved == [] and unresolved == []  # a function rename is for a human ("changed"), not relocation
    # The cited text no longer exists anywhere.
    report = _drift(root, _registry(old, "src/bot.py:5"), _registry(gone, "src/bot.py:1"))
    assert [m["kind"] for m in report["mismatches"]] == ["changed"]
    moved, unresolved = script.apply_relocation(report)
    assert moved == [] and unresolved == []


def test_baseline_registry_unreadable_fails_the_run(clones, monkeypatch, capsys):
    root, old, _new = clones
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(old, "src/bot.py:5"))
    assert script.main(["--repos-root", str(root), "--against", "no-such-ref-xyz"]) == 1
    assert "cannot read the baseline registry" in capsys.readouterr().out


def test_main_exits_nonzero_on_moved_code_and_zero_when_clean(clones, monkeypatch, capsys):
    root, old, new = clones
    monkeypatch.setattr(script, "baseline_registry", lambda ref: _registry(old, "src/bot.py:5"))
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(new, "src/bot.py:5"))
    assert script.main(["--repos-root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "FAIL [shifted]" in out and "the old line is now :7" in out
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(new, "src/bot.py:7"))
    assert script.main(["--repos-root", str(root)]) == 0
    assert "1 citation(s) compared, 0 shifted, 0 changed" in capsys.readouterr().out


def test_no_compare_skips_the_baseline(clones, monkeypatch):
    root, _old, new = clones
    monkeypatch.setattr(script, "baseline_registry", lambda ref: pytest.fail("baseline must not be read"))
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(new, "src/bot.py:7"))
    assert script.main(["--repos-root", str(root), "--no-compare"]) == 0


def test_changed_lines_fail_until_a_human_accepts_them_but_shifted_ones_never_pass(clones, monkeypatch, capsys):
    root, old, _new = clones
    clone = root / "bot-repo"
    (clone / "src" / "bot.py").write_text(OLD_BOT.replace("value = load()", "value = load(retry=True)", 1), encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "edit in place")
    edited = _git(clone, "rev-parse", "HEAD")
    monkeypatch.setattr(script, "baseline_registry", lambda ref: _registry(old, "src/bot.py:5 、 src/bot.py:6"))
    # :5 was edited in place (a human has to read it); :6 is unchanged.
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(edited, "src/bot.py:5 、 src/bot.py:6"))
    assert script.main(["--repos-root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "FAIL [changed]" in out and "value = load(retry=True)" in out
    assert script.main(["--repos-root", str(root), "--accept-changed"]) == 0
    assert "note [changed, accepted]" in capsys.readouterr().out
    # A shifted citation is not accepted by the flag.
    monkeypatch.setattr(script, "baseline_registry", lambda ref: _registry(old, "src/bot.py:5"))
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(_new, "src/bot.py:5"))
    assert script.main(["--repos-root", str(root), "--accept-changed"]) == 1


def test_several_equal_lines_in_the_function_is_for_a_human_not_a_wrong_citation(clones):
    root, old, _new = clones
    clone = root / "bot-repo"
    many = OLD_BOT.replace("    return None\n", "    log()\n    return None\n    return None\n    return None\n")
    (clone / "src" / "bot.py").write_text(many, encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "repeated lines")
    repeated = _git(clone, "rev-parse", "HEAD")
    # old :11 is beta()'s only "return None"; beta() now holds three, and :11 is "log()": no single place to move it to.
    report = _drift(root, _registry(old, "src/bot.py:11"), _registry(repeated, "src/bot.py:11"))
    assert [m["kind"] for m in report["mismatches"]] == ["changed"]


# --- review of #156 (BLOCK): scopes, unpaired cells, unreadable sources, relocation -------------------


def _make(tmp_path, old_src, new_src):
    clone = tmp_path / "bot-repo"
    clone.mkdir()
    _git(clone, "init", "-q")
    (clone / "src").mkdir()
    (clone / "src" / "bot.py").write_text(old_src, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "old")
    old = _git(clone, "rev-parse", "HEAD")
    (clone / "src" / "bot.py").write_text(new_src, encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "new")
    return tmp_path, old, _git(clone, "rev-parse", "HEAD")


def _kinds(report):
    return [(m["kind"], m["target"]) for m in report["mismatches"]]


def test_same_named_methods_of_different_classes_are_different_scopes(tmp_path):
    old_src = "class A:\n    def run(self):\n        send()\nclass B:\n    def run(self):\n        send()\n"
    root, old, new = _make(tmp_path, old_src, "# inserted\n" + old_src)
    # old :3 is A.run's send(); new :7 is B.run's send() -- the same text in the same method *name*.
    report = _drift(root, _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:7"))
    assert report["mismatches"][0]["reason"] == "same text but in B.run (was A.run)"
    assert _kinds(report) == [("shifted", 4)]
    assert _drift(root, _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:4"))["mismatches"] == []


def test_a_citation_after_a_nested_function_ends_stays_in_the_outer_function(tmp_path):
    root, old, new = _make(tmp_path, "def outer():\n    if active:\n        send()\n",
                           "def outer():\n    def inner():\n        other()\n    if active:\n        send()\n")
    report = _drift(root, _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:5"))
    assert report["compared"] == 1 and report["mismatches"] == []


def test_a_multi_line_signature_and_a_decorator_belong_to_their_function(tmp_path):
    sig = "def alpha(\n    a,\n):\n    pass\n\ndef beta(\n    b,\n):\n    pass\n"
    root, old, new = _make(tmp_path, sig, "# x\n" + sig)
    # the closing "):" of alpha moved from :3 to :4; :9 is beta's
    assert _drift(root, _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:4"))["mismatches"] == []
    assert _kinds(_drift(root, _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:9"))) == [("shifted", 4)]


def test_a_decorator_line_belongs_to_the_function_it_decorates(tmp_path):
    deco = "@dec\ndef alpha():\n    pass\n\n@dec\ndef beta():\n    pass\n"
    root, old, new = _make(tmp_path, deco, "# x\n" + deco)
    # old :1 is alpha's "@dec"; new :6 is beta's "@dec"
    assert _kinds(_drift(root, _registry(old, "src/bot.py:1"), _registry(new, "src/bot.py:6"))) == [("shifted", 2)]


def test_a_wrong_citation_cannot_hide_behind_an_extra_citation_in_the_same_cell(tmp_path, monkeypatch, capsys):
    root, old, new = _make(tmp_path, "def alpha():\n    send()\n", "# inserted\ndef alpha():\n    send()\n")
    old_reg, new_reg = _registry(old, "src/bot.py:2"), _registry(new, "src/bot.py:2 src/bot.py:3")
    report = _drift(root, old_reg, new_reg)
    # the file is cited once before and twice now: nothing is guessed, the whole cell is left for a human
    assert report["mismatches"] == []
    assert report["unpaired"] == [{"where": "capability cap.x", "project": "p", "old": ["src/bot.py:2"],
                                   "new": ["src/bot.py:2", "src/bot.py:3"]}]
    monkeypatch.setattr(script, "baseline_registry", lambda ref: old_reg)
    monkeypatch.setattr(script, "load_rollout_registry", lambda: new_reg)
    assert script.main(["--repos-root", str(root), "--accept-changed"]) == 1  # no flag but a human's own waves it through
    assert "FAIL [unpaired]" in capsys.readouterr().out


def test_overlapping_old_and_new_line_numbers_are_paired_by_what_they_cite(tmp_path):
    # Lines were inserted above; the author re-pointed :2 -> :3 and :3 -> :4.  Pairing identical numbers first
    # would compare old :3 with new :3 (the old :2 statement) and call a correct registry wrong.
    root, old, new = _make(tmp_path, "def f():\n    first()\n    second()\n", "def f():\n    zero()\n    first()\n    second()\n")
    report = _drift(root, _registry(old, "src/bot.py:2 src/bot.py:3"), _registry(new, "src/bot.py:3 src/bot.py:4"))
    assert report["compared"] == 2 and report["mismatches"] == [] and report["unpaired"] == []


def test_unpaired_cells_fail_until_a_human_accepts_them(tmp_path, monkeypatch, capsys):
    root, old, new = _make(tmp_path, "def alpha():\n    send()\n", "def alpha():\n    send()\n# tail\n")
    old_reg, new_reg = _registry(old, "src/bot.py:2"), _registry(new, "src/bot.py:2 src/bot.py:1")
    monkeypatch.setattr(script, "baseline_registry", lambda ref: old_reg)
    monkeypatch.setattr(script, "load_rollout_registry", lambda: new_reg)
    assert script.main(["--repos-root", str(root)]) == 1
    assert "FAIL [unpaired]" in capsys.readouterr().out
    assert script.main(["--repos-root", str(root), "--accept-unpaired"]) == 0
    assert "note [unpaired, accepted]" in capsys.readouterr().out


def test_an_old_commit_that_cannot_be_read_is_not_a_success(clones, monkeypatch, capsys):
    root, _old, new = clones
    missing = "0" * 40
    report = _drift(root, _registry(missing, "src/bot.py:3"), _registry(new, "src/bot.py:3"))
    assert [m["kind"] for m in report["mismatches"]] == ["changed"]
    assert "not readable at the old commit" in report["mismatches"][0]["reason"]
    monkeypatch.setattr(script, "baseline_registry", lambda ref: _registry(missing, "src/bot.py:3"))
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(new, "src/bot.py:3"))
    assert script.main(["--repos-root", str(root)]) == 1
    assert script.main(["--repos-root", str(root), "--accept-changed"]) == 0
    capsys.readouterr()


def test_a_file_at_neither_commit_is_skipped_for_the_other_checks_to_report(clones):
    root, old, new = clones
    report = _drift(root, _registry(old, "src/nowhere.py:3"), _registry(new, "src/nowhere.py:3"))
    assert report["skipped"] == 1 and report["mismatches"] == []


EQUAL_BRANCHES = "def f():\n    if buy:\n        send()\n    if sell:\n        send()\n"


@pytest.mark.parametrize("new_src", [
    "def f():\n    if sell:\n        audit()\n        send()\n",                          # two equal lines become one
    "def f():\n    if sell:\n        audit()\n        send()\n    if buy:\n        send()\n",  # equally many, branches reordered
])
def test_equal_lines_in_different_branches_are_never_relocated(tmp_path, new_src, monkeypatch):
    root, old, new = _make(tmp_path, EQUAL_BRANCHES, new_src)
    old_reg, new_reg = _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:3")
    report = _drift(root, old_reg, new_reg)
    assert _kinds(report) == [("changed", None)]
    assert script.apply_relocation(report) == ([], [])
    assert new_reg["capabilities"][0]["status"]["p"]["evidence"] == "src/bot.py:3"
    # and through main(): nothing is written, and the run does not come out clean
    registry_file = tmp_path / "registry.json"
    registry_file.write_text("sentinel", encoding="utf-8")
    monkeypatch.setattr(script, "REGISTRY_PATH", registry_file)
    monkeypatch.setattr(script, "baseline_registry", lambda ref: old_reg)
    monkeypatch.setattr(script, "load_rollout_registry", lambda: new_reg)
    assert script.main(["--repos-root", str(root), "--relocate"]) == 1
    assert registry_file.read_text(encoding="utf-8") == "sentinel"


def test_relocate_rewrites_the_registry_file_only_when_something_moved(clones, monkeypatch):
    root, old, new = clones
    registry_file = root / "registry.json"
    registry_file.write_text("sentinel", encoding="utf-8")
    monkeypatch.setattr(script, "REGISTRY_PATH", registry_file)
    monkeypatch.setattr(script, "baseline_registry", lambda ref: _registry(old, "src/bot.py:5"))
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(new, "src/bot.py:5"))
    assert script.main(["--repos-root", str(root), "--relocate"]) == 0
    assert '"evidence": "src/bot.py:7"' in registry_file.read_text(encoding="utf-8")


def test_lines_split_on_newline_only_like_grep_and_ast():
    assert script._lines("a\x0c\nb\u2028c\r\nd\n") == ["a\x0c", "b\u2028c", "d"]
    assert script._lines("") == []


# --- review of #156, second round: citations keep their identity -------------------------------------

BUY_SELL = "def f():\n    buy()\n    sell()\n"
BUY_SELL_SHIFTED = "def f():\n    zero()\n    buy()\n    sell()\n"


def test_two_citations_are_relocated_each_to_its_own_line_never_swapped(tmp_path):
    root, old, new = _make(tmp_path, BUY_SELL, BUY_SELL_SHIFTED)
    old_reg = _registry(old, "買入見 src/bot.py:2；賣出見 src/bot.py:3")
    new_reg = _registry(new, "買入見 src/bot.py:2；賣出見 src/bot.py:3")
    report = _drift(root, old_reg, new_reg)
    assert _kinds(report) == [("shifted", 3), ("shifted", 4)]
    moved, unresolved = script.apply_relocation(report)
    assert new_reg["capabilities"][0]["status"]["p"]["evidence"] == "買入見 src/bot.py:3；賣出見 src/bot.py:4"
    assert len(moved) == 2 and unresolved == []
    assert _drift(root, old_reg, new_reg)["mismatches"] == []


def test_citations_that_were_swapped_are_caught_not_waved_through(tmp_path):
    root, old, new = _make(tmp_path, BUY_SELL, BUY_SELL_SHIFTED)
    report = _drift(root, _registry(old, "買入見 src/bot.py:2；賣出見 src/bot.py:3"),
                    _registry(new, "買入見 src/bot.py:4；賣出見 src/bot.py:3"))
    assert len(report["mismatches"]) == 2  # buy now points at sell(), sell at buy()


def test_same_named_functions_in_different_branches_are_not_one_function(tmp_path):
    src = ("def outer():\n    if buy:\n        def inner():\n            buy_only()\n            send()\n"
           "    else:\n        def inner():\n            sell_only()\n            send()\n")
    root, old, new = _make(tmp_path, src, "# inserted\n" + src)
    # old :5 is the buy branch's send(); new :10 is the sell branch's
    report = _drift(root, _registry(old, "src/bot.py:5"), _registry(new, "src/bot.py:10"))
    assert [m["kind"] for m in report["mismatches"]] == ["changed"] and "not a unique definition" in report["mismatches"][0]["reason"]
    assert [m["kind"] for m in _drift(root, _registry(old, "src/bot.py:5"), _registry(new, "src/bot.py:6"))["mismatches"]] == ["changed"]


def test_the_bodies_of_different_multi_line_lambdas_are_not_the_module(tmp_path):
    src = "buy = (lambda:\n    send()\n)\nsell = (lambda:\n    send()\n)\n"
    root, old, new = _make(tmp_path, src, "# inserted\n" + src)
    report = _drift(root, _registry(old, "src/bot.py:2"), _registry(new, "src/bot.py:6"))  # buy's send() -> sell's send()
    assert [m["kind"] for m in report["mismatches"]] == ["changed"]


def test_a_citation_that_slid_onto_another_equal_line_of_the_function_is_caught(tmp_path):
    root, old, new = _make(tmp_path, EQUAL_BRANCHES, "# inserted\n" + EQUAL_BRANCHES)
    # old :3 is the buy branch's send(); new :4 is still the buy branch's, new :6 is the sell branch's
    assert _drift(root, _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:4"))["mismatches"] == []
    report = _drift(root, _registry(old, "src/bot.py:3"), _registry(new, "src/bot.py:6"))
    assert [m["kind"] for m in report["mismatches"]] == ["changed"]
    assert "not the same one of them" in report["mismatches"][0]["reason"]


def test_no_compare_numbers_lines_by_newline_only_through_the_real_reader(tmp_path, monkeypatch, capsys):
    root, _old, new = _make(tmp_path, "# a\nx = 1\n", "# a\u2028b\nx = 1\n")
    monkeypatch.setattr(script, "load_rollout_registry", lambda: _registry(new, "src/bot.py:3"))
    # the file has two lines (a U+2028 is not a line break for grep or ast); str.splitlines used to say three
    assert script.main(["--repos-root", str(root), "--no-compare"]) == 1
    assert "line past end of file (2 lines)" in capsys.readouterr().out
