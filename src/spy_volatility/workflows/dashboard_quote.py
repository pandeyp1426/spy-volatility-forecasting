"""Read the most recent completed regular-session SPY minute bar for display."""
import json
import math
from datetime import datetime, timezone

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf


def quote_from_bars(bars, now):
    now = pd.Timestamp(now).tz_convert("UTC")
    calendar = mcal.get_calendar("NYSE").schedule(now.date() - pd.Timedelta(days=12), now.date())
    sessions = calendar[calendar.market_open < now]
    if bars.empty or bars.index.tz is None or sessions.empty:
        raise ValueError("No timestamped SPY minute prices")
    latest = sessions.iloc[-1]
    for _, session in sessions.iloc[::-1].iterrows():
        end = min(now.floor("min"), session.market_close)
        prices = bars.loc[(bars.index >= session.market_open) & (bars.index < end), "Close"].sort_index()
        if prices.empty:
            continue
        price = float(prices.iloc[-1])
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid SPY minute close")
        as_of = prices.index[-1].tz_convert("UTC") + pd.Timedelta(minutes=1)
        return {"price": price, "as_of": as_of.isoformat(), "fetched_at": now.isoformat(),
                "market_open": bool(latest.market_open <= now < latest.market_close),
                "delayed": min(now, latest.market_close) - as_of > pd.Timedelta(minutes=15)}
    raise ValueError("No completed regular-session SPY minute bar in the provider response")


def main():
    bars = yf.Ticker("SPY").history(period="5d", interval="1m", prepost=False,
                                    auto_adjust=False, actions=False, timeout=12)
    print(json.dumps(quote_from_bars(bars, datetime.now(timezone.utc)), allow_nan=False))


if __name__ == "__main__":
    main()
