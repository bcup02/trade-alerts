#!/usr/bin/env python3
"""Keep the Apps Script receiver's exit-reason labels equal to the glossary's 「帳本來源代碼」 category.

The glossary (``fleet-glossary.json``) is the single source of truth for the Chinese name of every ledger ``source`` code.
The receiver shows column P (出場原因) in Chinese by looking a code up in ``EXIT_REASON_ZH``; that block between the
BEGIN/END markers is generated from the glossary:

    python scripts/sync_receiver_exit_reasons.py            # rewrite the block
    python scripts/sync_receiver_exit_reasons.py --check    # exit 1 when the receiver is out of date (CI runs this as a test)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
RECEIVER = _ROOT / "apps_script" / "google_ledger_receiver.gs"
GLOSSARY = _ROOT / "src" / "trade_alerts" / "catalog" / "fleet-glossary.json"
CATEGORY = "帳本來源代碼"
BEGIN, END = "// BEGIN EXIT_REASON_ZH", "// END EXIT_REASON_ZH"
CORRECTION_CATEGORY = "帳本更正原因代碼"
CBEGIN, CEND = "// BEGIN CORRECTION_REASON_ZH", "// END CORRECTION_REASON_ZH"


def labels(category: str = CATEGORY) -> dict[str, str]:
    """``{code: Chinese name}`` from a glossary category."""
    entries = json.loads(GLOSSARY.read_text(encoding="utf-8"))["entries"]
    out: dict[str, str] = {}
    for entry in entries:
        if entry.get("category") != category:
            continue
        for code in entry["en"]:
            if code in out:
                raise ValueError(f"ledger source code {code!r} appears twice in the glossary")
            out[code] = entry["zh"]
    return out


def render_block() -> str:
    body = ",\n".join(f"  {json.dumps(code)}: {json.dumps(zh, ensure_ascii=False)}" for code, zh in sorted(labels().items()))
    return (f"{BEGIN} (generated from trade-alerts fleet-glossary.json by scripts/sync_receiver_exit_reasons.py -- do not edit by hand)\n"
            f"const EXIT_REASON_ZH = {{\n{body}\n}};\n{END}")


def render_correction_block() -> str:
    body = ",\n".join(f"  {json.dumps(code)}: {json.dumps(zh, ensure_ascii=False)}"
                      for code, zh in sorted(labels(CORRECTION_CATEGORY).items()))
    return (f"{CBEGIN} (generated from trade-alerts fleet-glossary.json by scripts/sync_receiver_exit_reasons.py -- do not edit by hand)\n"
            f"const CORRECTION_REASON_ZH = {{\n{body}\n}};\n{CEND}")


def current_block(text: str, begin: str = BEGIN, end: str = END) -> str:
    match = re.search(re.escape(begin) + r".*?" + re.escape(end), text, re.S)
    if not match:
        raise ValueError("EXIT_REASON_ZH markers not found in the receiver")
    return match.group(0)


def main(argv: list[str]) -> int:
    text = RECEIVER.read_text(encoding="utf-8")
    fresh, cfresh = render_block(), render_correction_block()
    if "--check" in argv:
        if current_block(text) != fresh or current_block(text, CBEGIN, CEND) != cfresh:
            print("receiver EXIT_REASON_ZH is out of date; run scripts/sync_receiver_exit_reasons.py")
            return 1
        return 0
    text = text.replace(current_block(text), fresh).replace(current_block(text, CBEGIN, CEND), cfresh)
    RECEIVER.write_text(text, encoding="utf-8")
    print(f"wrote {len(labels())} source labels and {len(labels(CORRECTION_CATEGORY))} correction labels")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
