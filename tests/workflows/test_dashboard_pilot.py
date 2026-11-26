import pandas as pd
import pytest

from spy_volatility.workflows.dashboard_pilot import eligible_origin, trigger_times
from spy_volatility.workflows.dashboard_quote import quote_from_bars


def test_scheduled_closes_follow_thanksgiving_and_pilot_containment():
    times = trigger_times(pd.Timestamp("2026-11-22T05:00Z"))
    assert times[:5] == [f"2026-11-{day}T{hour}:05:00+00:00" for day, hour in
                         [(23, 21), (24, 21), (25, 21), (27, 18), (30, 21)]]
    assert len(times) == 22
    assert times[-1] == "2026-12-23T21:05:00+00:00"


@pytest.mark.parametrize(("instant", "latest", "expected"), [
    ("2026-11-27T17:59Z", False, None),
    ("2026-11-27T18:05Z", False, "2026-11-27"),
    ("2026-11-27T20:01Z", False, None),
    ("2026-11-22T05:00Z", False, None),
    ("2026-11-22T05:00Z", True, "2026-11-20"),
    ("2026-12-24T18:05Z", True, None),
    ("2027-01-04T21:05Z", True, None),
])
def test_eligibility_respects_close_deadline_and_study(instant, latest, expected):
    assert eligible_origin(pd.Timestamp(instant), latest=latest) == expected


def test_quote_excludes_after_hours_and_marks_missing_recent_session():
    bars = pd.DataFrame({"Close": [500, 501, 520]}, index=pd.to_datetime(
        ["2026-11-27T17:58Z", "2026-11-27T17:59Z", "2026-11-27T18:00Z"]))
    weekend = quote_from_bars(bars, "2026-11-28T16:00Z")
    assert weekend["price"] == 501 and not weekend["market_open"] and not weekend["delayed"]
    assert weekend["as_of"] == "2026-11-27T18:00:00+00:00"
    intraday = quote_from_bars(bars, "2026-11-27T17:59:50Z")
    assert intraday["price"] == 500 and intraday["market_open"]
    assert quote_from_bars(bars, "2026-11-30T16:00Z")["delayed"]
