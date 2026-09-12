from trade_alerts.investor import taipei_time


def test_taipei_time_converts_utc_iso_to_taipei_local():
    assert taipei_time("2026-08-19T08:00:00Z") == "2026-08-19 16:00"


def test_taipei_time_missing_value_returns_placeholder():
    assert taipei_time(None) == "時間未提供"
    assert taipei_time("") == "時間未提供"


def test_taipei_time_unparseable_value_returns_placeholder():
    assert taipei_time("not-a-timestamp") == "時間未提供"
