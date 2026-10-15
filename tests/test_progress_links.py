"""phase-sync3: progress items that name registry cells are checked against the registry (both directions)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_progress_links", _ROOT / "scripts" / "check_progress_links.py")
cpl = importlib.util.module_from_spec(_spec)
sys.modules["check_progress_links"] = cpl
_spec.loader.exec_module(cpl)


def registry(cap_states=None, rule_states=None):
    cap_states = cap_states or {"seykota": "done", "momentum": "pending", "mycrypto": "n/a", "btc-competition": "done"}
    rule_states = rule_states or {"behaviour": "done", "emits_event": "pending"}

    def status(state):
        return {"state": state, **({"evidence": "e"} if state == "done" else {"reason": "r"})}
    return {
        "capabilities": [{"id": "x.cap", "status": {p: status(s) for p, s in cap_states.items()}}],
        "catalog": [{"code": "SEY.RULE", "behaviour": {"seykota": status(rule_states["behaviour"])},
                     "emits_event": {"seykota": status(rule_states["emits_event"])}}],
    }


def item(status, *links, id="i-1"):
    return {"id": id, "title": "t", "status": status, "registry": list(links)}


def test_a_done_item_with_a_pending_linked_cell_is_an_error():
    problems = cpl.link_problems([item("done", "cap:x.cap")], registry())
    assert len(problems) == 1 and "已完成" in problems[0] and "momentum" in problems[0]


def test_a_done_item_whose_linked_cells_are_all_done_or_na_is_fine():
    assert cpl.link_problems([item("done", "cap:x.cap@seykota,mycrypto,btc-competition")], registry()) == []


@pytest.mark.parametrize("status", ["todo", "active", "waiting"])
def test_an_open_item_whose_cells_are_all_finished_should_be_closed(status):
    problems = cpl.link_problems([item(status, "cap:x.cap@seykota,mycrypto")], registry())
    assert len(problems) == 1 and "該結案了" in problems[0]
    assert cpl.link_problems([item(status, "cap:x.cap")], registry()) == []        # momentum still pending: open is right


def test_an_item_on_the_watch_list_is_open_on_purpose():
    items = [item("active", "cap:x.cap@seykota", id="w-1")]
    assert cpl.link_problems(items, registry()) != []
    assert cpl.link_problems(items, registry(), watch_ids={"w-1"}) == []
    done_but_pending = [item("done", "cap:x.cap", id="w-1")]                        # the watch list does not excuse a premature "done"
    assert cpl.link_problems(done_but_pending, registry(), watch_ids={"w-1"}) != []


def test_skipped_items_and_items_without_links_are_not_checked():
    assert cpl.link_problems([item("skipped", "cap:x.cap")], registry()) == []
    assert cpl.link_problems([{"id": "p", "title": "t", "status": "done"}], registry()) == []


def test_rule_links_can_name_one_aspect():
    reg = registry()
    assert cpl.link_problems([item("done", "rule:SEY.RULE")], reg) != []                       # emits_event is pending
    assert cpl.link_problems([item("done", "rule:SEY.RULE#behaviour")], reg) == []
    assert cpl.link_problems([item("done", "rule:SEY.RULE#emits_event")], reg) != []
    assert cpl.link_problems([item("done", "cap:x.cap#behaviour")], reg) != []                 # an aspect only exists on rules


@pytest.mark.parametrize("link", ["cap:no.such", "rule:NO.SUCH", "cap:x.cap@nobody", "cap x.cap", "x.cap", "cap:x.cap@", "rule:SEY.RULE#nothing",
                                  "rule:SEY.RULE@momentum"])
def test_a_link_that_points_at_nothing_is_an_error_not_a_silent_pass(link):
    problems = cpl.link_problems([item("done", link)], registry())
    assert problems and "已完成" not in problems[0]


def test_registry_must_be_a_non_empty_list_of_strings():
    for bad in ([], "cap:x.cap", [1], None, {}, 0, ""):
        items = [{"id": "i", "title": "t", "status": "done", "registry": bad}]
        assert any("registry 要是非空的字串清單" in p for p in cpl.link_problems(items, registry())), bad
    assert cpl.link_problems([{"id": "i", "title": "t", "status": "done"}], registry()) == []     # no field at all: nothing to check


PAGE = '''<script>
  var ITEMS = [
    {id:"old-1", section:"a", level:1, title:"old literal line", status:"done"},
    {"id": "f-1", "section": "f", "title": "linked and done", "status": "done", "registry": ["cap:x.cap@seykota"]},
    {"id": "f-2", "section": "f", "title": "linked, open", "status": "active", "registry": ["cap:x.cap"]},
  ];
  var WATCH = [
    {"id": "f-2", "note": "waiting"},
  ];
</script>'''


def test_items_and_watch_ids_are_read_from_the_page_and_literal_lines_are_skipped():
    items = cpl.extract_items(PAGE)
    assert [i["id"] for i in items] == ["f-1", "f-2"]
    assert cpl.extract_watch_ids(PAGE) == {"f-2"}
    assert cpl.link_problems(items, registry(), cpl.extract_watch_ids(PAGE)) == []
    with pytest.raises(ValueError):
        cpl.extract_items("<html>no items here</html>")


def test_cli_exit_codes(tmp_path, capsys):
    reg_file, page = tmp_path / "registry.json", tmp_path / "page.html"
    real = json.loads((_ROOT / "src/trade_alerts/catalog/fleet-rollout-registry.json").read_text(encoding="utf-8"))
    reg_file.write_text(json.dumps(real), encoding="utf-8")
    cap = next(c for c in real["capabilities"] if any(s["state"] == "pending" for s in c["status"].values()))
    pending_project = next(p for p, s in cap["status"].items() if s["state"] == "pending")
    done_cap = next(c for c in real["capabilities"] if all(s["state"] in ("done", "n/a") for s in c["status"].values()))

    def run(status, link):
        page.write_text('var ITEMS = [\n    {"id": "z", "title": "t", "status": "%s", "registry": ["%s"]},\n  ];\n' % (status, link), encoding="utf-8")
        return cpl.main([str(page), "--registry", str(reg_file)])

    assert run("done", f"cap:{done_cap['id']}") == 0
    assert run("done", f"cap:{cap['id']}@{pending_project}") == 1
    assert "已完成" in capsys.readouterr().out
    assert run("active", f"cap:{done_cap['id']}") == 1
    assert run("active", "cap:does.not.exist") == 1


# --- review of #197: three ways a link used to check nothing --------------------------------------------------------

def test_a_multi_line_json_item_is_read_and_checked():
    """BLOCK-1: the parser only took one-line items ending in `},`; any other layout was silently skipped."""
    page = '''var ITEMS = [
    {
      "id": "f-23e",
      "title": "t",
      "status": "done",
      "registry": ["cap:x.cap@momentum"]
    }
  ];'''
    items = cpl.extract_items(page)
    assert [i["id"] for i in items] == ["f-23e"]
    problems = cpl.link_problems(items, registry())
    assert len(problems) == 1 and "已完成" in problems[0]
    compact = 'var ITEMS = [\n    {"id": "a", "status": "done", "registry": ["cap:x.cap@seykota"]}\n  ];'   # no trailing comma either
    assert [i["id"] for i in cpl.extract_items(compact)] == ["a"]


def test_an_item_with_registry_that_cannot_be_read_is_an_error_not_a_pass():
    js_literal = 'var ITEMS = [\n    {id:"old", status:"done", registry:["cap:x.cap"]},\n    {"id": "ok", "status": "done", "registry": ["cap:x.cap@seykota"]},\n  ];'
    broken = 'var ITEMS = [\n    {"id": "bad", "status": "done", "registry": ["cap:x.cap@seykota"],},\n    {"id": "ok", "status": "done", "registry": ["cap:x.cap@seykota"]},\n  ];'
    with pytest.raises(ValueError, match="registry"):
        cpl.extract_items(broken)
    with pytest.raises(ValueError, match="registry"):                          # BLOCK (second review): unquoted keys carrying registry
        cpl.extract_items(js_literal)


def test_the_word_registry_inside_a_text_is_not_a_field():
    page = 'var ITEMS = [\n    {"id": "a", "status": "done", "detail": "進度項目加 \\"registry\\": 欄", "registry": ["cap:x.cap@seykota"]},\n  ];'
    assert [i["id"] for i in cpl.extract_items(page)] == ["a"]


def test_every_strategy_a_link_names_must_have_a_cell():
    """BLOCK-2: `@seykota,momentum` with a cell only for seykota used to pass on the one cell that existed."""
    reg = {"capabilities": [{"id": "x.cap", "status": {"seykota": {"state": "done", "evidence": "e"}}}], "catalog": []}
    problems = cpl.link_problems([item("done", "cap:x.cap@seykota,momentum")], reg)
    assert len(problems) == 1 and "momentum" in problems[0] and "沒有格子" in problems[0]
    rules = registry()
    problems = cpl.link_problems([item("done", "rule:SEY.RULE#behaviour@seykota,momentum")], rules)
    assert len(problems) == 1 and "momentum" in problems[0]
    # the cells that do exist are still compared
    problems = cpl.link_problems([item("done", "rule:SEY.RULE#emits_event@seykota,momentum")], rules)
    assert any("已完成" in p for p in problems) and any("momentum" in p for p in problems)
    # without a scope a rule simply means its owners
    assert cpl.link_problems([item("done", "rule:SEY.RULE#behaviour")], rules) == []


@pytest.mark.parametrize("status", ["don", "", None, "Done", "finished"])
def test_an_unknown_or_missing_status_is_an_error(status):
    """BLOCK-3: a mistyped status matched neither branch and the link was never compared."""
    problems = cpl.link_problems([{"id": "x", "title": "t", "status": status, "registry": ["cap:x.cap@momentum"]}], registry())
    assert any("不是已知的值" in p for p in problems)
    assert cpl.link_problems([{"id": "x", "title": "t", "registry": ["cap:x.cap@momentum"]}], registry())      # no status at all


def test_skipped_is_a_known_status_and_still_has_its_links_validated():
    assert cpl.link_problems([item("skipped", "cap:x.cap")], registry()) == []
    assert cpl.link_problems([item("skipped", "cap:no.such")], registry()) != []


def test_watch_ids_are_read_from_multi_line_entries_and_ignore_other_text():
    page = 'var WATCH = [\n    {\n      "id": "w-1",\n      "note": "text with {\\"id\\": \\"fake\\"} inside"\n    },\n  ];'
    assert cpl.extract_watch_ids(page) == {"w-1"}


def test_cli_reports_an_unreadable_item_and_exits_1(tmp_path, capsys):
    page = tmp_path / "page.html"
    page.write_text('var ITEMS = [\n    {"id": "bad", "registry": ["cap:x.cap"],},\n  ];\n', encoding="utf-8")
    assert cpl.main([str(page), "--registry", str(_ROOT / "src/trade_alerts/catalog/fleet-rollout-registry.json")]) == 1
    assert "讀不懂" in capsys.readouterr().out


def test_js_literal_items_without_registry_are_still_fine_but_with_registry_are_errors():
    plain = 'var ITEMS = [\n    {id:"old", status:"done", title:"x"},\n    {"id": "ok", "status": "done"},\n  ];'
    assert [i["id"] for i in cpl.extract_items(plain)] == ["ok"]
    for literal in ('{id:"f-23e", status:"done", registry:["cap:x.cap@momentum"]},',
                    '{ id: "f-23e", status: "done",\n      registry : ["cap:x.cap@momentum"] },',
                    '{"id": "q", "registry":["cap:x.cap"]}, {id:"f", status:"done", registry:["cap:x.cap"]},'):
        with pytest.raises(ValueError, match="registry"):
            cpl.extract_items("var ITEMS = [\n    " + literal + "\n  ];")


def test_a_registry_null_is_an_invalid_value_not_a_missing_field(tmp_path, capsys):
    items = [{"id": "f-23e", "title": "t", "status": "done", "registry": None}]
    assert any("非空的字串清單" in p for p in cpl.link_problems(items, registry()))
    f = tmp_path / "items.json"
    f.write_text(json.dumps(items), encoding="utf-8")
    reg = tmp_path / "registry.json"
    reg.write_text((_ROOT / "src/trade_alerts/catalog/fleet-rollout-registry.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert cpl.main(["--items-json", str(f), "--registry", str(reg)]) == 1
    assert "其中 1 項連了登記冊格子" in capsys.readouterr().out
