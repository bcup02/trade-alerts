"""`trade_alerts.__version__` 必須等於 pyproject.toml 的版本。

`__version__` 曾經停在 0.30.20，而 pyproject 已經發到 0.30.32（PR #357 審閱 BLOCK-357-01 發現）：使用 `trade_alerts.__version__` 的版本檢查與除錯資訊
會和實際發布的 tag 不一樣。之後每次改 pyproject 的版本都要同步改它，這個測試擋住再次分岔。
"""
from __future__ import annotations

import re
from pathlib import Path

import trade_alerts

_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml 找不到 version"
    return match.group(1)


def test_package_dunder_version_matches_pyproject():
    assert trade_alerts.__version__ == _pyproject_version()


def test_the_version_is_a_plain_semver_triplet():
    assert re.fullmatch(r"\d+\.\d+\.\d+", trade_alerts.__version__)
