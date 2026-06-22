from datetime import datetime, timezone
from decimal import Decimal

from app import config
from app.own_strategy.rs_pullback_v1 import Candle, OpenInterestPoint, RSPullbackFeatures, calculate_atr


def build_features(
    *,
    symbol_candles: list[Candle],
    btc_candles: list[Candle],
    open_interest: list[OpenInterestPoint],
    now: datetime | None = None,
) -> tuple[RSPullbackFeatures | None, str | None]:
    if len(symbol_candles) < max(config.RS_PULLBACK_ATR_PERIOD + 1, 21, 5):
        return None, "MISSING_CANDLES"
    if len(btc_candles) < 5:
        return None, "MISSING_BTC_CANDLES"
    if len(open_interest) < 1:
        return None, "MISSING_OI"
    if len(open_interest) < 2:
        return None, "MISSING_PREVIOUS_OI"

    current = symbol_candles[-1]
    close_4_ago = symbol_candles[-5].close
    btc_current = btc_candles[-1]
    btc_close_4_ago = btc_candles[-5].close
    if close_4_ago <= 0 or btc_close_4_ago <= 0:
        return None, "INVALID_CANDLE_PRICE"

    current_oi = open_interest[-1]
    previous_oi = open_interest[-2]
    check_time = now or datetime.now(timezone.utc)
    oi_ts = current_oi.ts if current_oi.ts.tzinfo else current_oi.ts.replace(tzinfo=timezone.utc)
    staleness_minutes = (check_time - oi_ts).total_seconds() / 60
    if staleness_minutes > config.RS_PULLBACK_MAX_OI_STALENESS_MINUTES:
        return None, "STALE_OI"
    if current_oi.open_interest <= 0:
        return None, "MISSING_OI"
    if previous_oi.open_interest <= 0:
        return None, "MISSING_PREVIOUS_OI"

    atr = calculate_atr(symbol_candles, config.RS_PULLBACK_ATR_PERIOD)
    if atr is None or atr <= 0:
        return None, "MISSING_ATR"

    avg_volume = sum(candle.volume for candle in symbol_candles[-21:-1]) / Decimal("20")
    if avg_volume <= 0:
        return None, "INVALID_VOLUME"

    price_change_1h = percent_change(current.close, close_4_ago)
    btc_change_1h = percent_change(btc_current.close, btc_close_4_ago)
    oi_change_15m = percent_change(current_oi.open_interest, previous_oi.open_interest)

    return RSPullbackFeatures(
        signal_ts=current.ts,
        signal_close=current.close,
        relative_strength_1h=price_change_1h - btc_change_1h,
        price_change_1h=price_change_1h,
        volume_ratio_15m=current.volume / avg_volume,
        oi_change_15m=oi_change_15m,
        btc_change_1h=btc_change_1h,
        atr_value=atr,
    ), None


def percent_change(current: Decimal, previous: Decimal) -> Decimal:
    if previous <= 0:
        return Decimal("0")
    return ((current - previous) / previous * Decimal("100")).quantize(Decimal("0.00000001"))
