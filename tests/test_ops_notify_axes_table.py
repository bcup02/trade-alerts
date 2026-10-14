"""f-44: the risk register explains what an ops-notify 「軸」 is, and the table cannot fall behind the catalog."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from trade_alerts.fleet_event_log import load_error_catalog

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "guides" / "fleet-risk-register.html"


def _render_guides():
    spec = importlib.util.spec_from_file_location("render_guides", ROOT / "scripts" / "render_guides.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_ops_notify_catalog_code_is_in_the_axes_table_exactly_once():
    module = _render_guides()
    listed = [code for _name, _key, _meaning, codes in module.OPS_NOTIFY_AXES for code in codes]
    catalog_codes = [e["code"] for e in load_error_catalog()["entries"] if e["code"].startswith("FLEET.OPS_")]
    assert sorted(listed) == sorted(catalog_codes)


def test_the_page_has_the_table_with_each_axis_and_its_error_numbers():
    html = PAGE.read_text(encoding="utf-8")
    section = html[html.index('id="axes"'):html.index('id="filters"')]
    module = _render_guides()
    ids = {e["code"]: e["error_id"] for e in load_error_catalog()["entries"]}
    for name, key, meaning, codes in module.OPS_NOTIFY_AXES:
        row = re.search(rf"<tr><td><b>{re.escape(name)}</b>.*?</tr>", section, re.S)
        assert row, name
        assert key in row.group(0) and meaning in row.group(0)
        for code in codes:
            assert ids[code] in row.group(0), (name, code)
    assert "沒有軸" in section                      # says that errors the strategy detects itself have no axis
    assert "health.json" in section


def test_the_generated_page_is_current():
    module = _render_guides()
    assert PAGE.read_text(encoding="utf-8") == module.rendered_pages()[PAGE]
