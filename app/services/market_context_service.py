from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.bingx.client import BingXClient


BTC_SYMBOL = "BTC-USDT"


async def btc_change_1h_before_entry(client: BingXClient, signal_time: datetime | None) -> Decimal | None:
    if signal_time is None:
        return None

    entry_time = next_minute(signal_time)
    factor_end = entry_time - timedelta(milliseconds=1)
    factor_start = entry_time - timedelta(minutes=70)
    candles = await client.klines(
        symbol=BTC_SYMBOL,
        interval="1m",
        start_time=to_ms(factor_start),
        end_time=to_ms(factor_end),
        limit=100,
    )
    normalized = sorted(
        (normalize_candle(row) for row in candles),
        key=lambda row: row["time"],
    )
    normalized = [row for row in normalized if row["time"] < entry_time]
    if len(normalized) < 61:
        return None

    current = normalized[-1]
    target_time = current["time"] - timedelta(hours=1)
    previous = max((row for row in normalized if row["time"] <= target_time), key=lambda row: row["time"], default=None)
    if previous is None or previous["close"] == 0:
        return None

    return (current["close"] - previous["close"]) / previous["close"] * Decimal("100")


def next_minute(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    floored = value.replace(second=0, microsecond=0)
    if value == floored:
        return floored
    return floored + timedelta(minutes=1)


def to_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.astimezone(timezone.utc).timestamp() * 1000)


def normalize_candle(row: dict) -> dict:
    return {
        "time": datetime.fromtimestamp(int(row["time"]) / 1000, tz=timezone.utc),
        "close": Decimal(str(row["close"])),
    }
