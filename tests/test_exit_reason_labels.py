"""f-56: the receiver's Chinese 出場原因 labels are generated from the glossary and cannot drift from it."""
import importlib.util
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sync_receiver_exit_reasons", _ROOT / "scripts" / "sync_receiver_exit_reasons.py")
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)


def test_receiver_block_matches_glossary():
    text = sync.RECEIVER.read_text(encoding="utf-8")
    assert sync.current_block(text) == sync.render_block(), "run scripts/sync_receiver_exit_reasons.py"


def test_receiver_labels_parse_back_to_glossary():
    block = sync.current_block(sync.RECEIVER.read_text(encoding="utf-8"))
    pairs = dict(re.findall(r'^\s+("[^"]+"): ("[^"]+"),?$', block, re.M))
    parsed = {json.loads(k): json.loads(v) for k, v in pairs.items()}
    assert parsed == sync.labels()


def test_every_code_has_a_distinct_chinese_name_per_entry():
    entries = [e for e in json.loads(sync.GLOSSARY.read_text(encoding="utf-8"))["entries"] if e["category"] == sync.CATEGORY]
    assert len(entries) >= 28
    assert len({e["zh"] for e in entries}) == len(entries)
    assert all(re.fullmatch(r"[a-z0-9_]+", code) for e in entries for code in e["en"])


def test_receiver_correction_labels_equal_glossary_and_correction_module():
    from trade_alerts.trade_correction import REASON_LABELS_ZH

    text = sync.RECEIVER.read_text(encoding="utf-8")
    assert sync.current_block(text, sync.CBEGIN, sync.CEND) == sync.render_correction_block(), "run scripts/sync_receiver_exit_reasons.py"
    assert sync.labels(sync.CORRECTION_CATEGORY) == REASON_LABELS_ZH
