from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app import config


STRATEGY_NAME = "RS_PULLBACK_V1"
DISPLAY_NAME = "Relative Strength Pullback v1"
SIGNAL_SOURCE = "own"
SETUP_TYPE = "LONG_RELATIVE_STRENGTH"
ENTRY_MODEL = "pullback_1_0_atr"
STOP_MODEL = "atr_1_5"
R_MODEL = "model_c_0_75_1_5_2_5r"


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class OpenInterestPoint:
    ts: datetime
    open_interest: Decimal


@dataclass(frozen=True)
class RSPullbackFeatures:
    signal_ts: datetime
    signal_close: Decimal
    relative_strength_1h: Decimal
    price_change_1h: Decimal
    volume_ratio_15m: Decimal
    oi_change_15m: Decimal
    btc_change_1h: Decimal
    atr_value: Decimal


@dataclass(frozen=True)
class RSPullbackSignal:
    strategy_name: str
    signal_source: str
    symbol: str
    bingx_symbol: str
    direction: str
    setup_type: str
    timeframe: str
    signal_ts: datetime
    signal_close: Decimal
    entry_model: str
    entry_price: Decimal
    stop_model: str
    stop_price: Decimal
    risk_price: Decimal
    risk_pct: Decimal
    tp1_price: Decimal
    tp2_price: Decimal
    tp3_price: Decimal
    atr_period: int
    atr_value: Decimal
    relative_strength_1h: Decimal
    price_change_1h: Decimal
    volume_ratio_15m: Decimal
    oi_change_15m: Decimal
    btc_change_1h: Decimal
    features_json: dict[str, Any]
    reason_json: dict[str, Any]


def filter_skip_reason(features: RSPullbackFeatures) -> str | None:
    checks = (
        ("RELATIVE_STRENGTH_TOO_LOW", features.relative_strength_1h, config.RS_PULLBACK_MIN_RELATIVE_STRENGTH_1H),
        ("PRICE_CHANGE_TOO_LOW", features.price_change_1h, config.RS_PULLBACK_MIN_PRICE_CHANGE_1H),
        ("VOLUME_RATIO_TOO_LOW", features.volume_ratio_15m, config.RS_PULLBACK_MIN_VOLUME_RATIO_15M),
        ("OI_CHANGE_TOO_LOW", features.oi_change_15m, config.RS_PULLBACK_MIN_OI_CHANGE_15M),
        ("BTC_CHANGE_TOO_LOW", features.btc_change_1h, config.RS_PULLBACK_MIN_BTC_CHANGE_1H),
    )
    for reason, value, minimum in checks:
        if value < minimum:
            return reason
    return None


def calculate_entry(signal_close: Decimal, atr: Decimal, pullback_mult: Decimal | None = None) -> Decimal:
    mult = pullback_mult if pullback_mult is not None else config.RS_PULLBACK_ENTRY_PULLBACK_ATR_MULT
    return signal_close - (atr * mult)


def calculate_stop(entry: Decimal, atr: Decimal, stop_mult: Decimal | None = None) -> Decimal:
    mult = stop_mult if stop_mult is not None else config.RS_PULLBACK_STOP_ATR_MULT
    return entry - (atr * mult)


def calculate_targets(entry: Decimal, risk: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    return (
        entry + risk * config.RS_PULLBACK_TP1_R,
        entry + risk * config.RS_PULLBACK_TP2_R,
        entry + risk * config.RS_PULLBACK_TP3_R,
    )


def risk_pct(entry: Decimal, stop: Decimal) -> Decimal:
    risk = entry - stop
    if entry <= 0:
        return Decimal("0")
    return (risk / entry * Decimal("100")).quantize(Decimal("0.00000001"))


def validate_risk(entry: Decimal, stop: Decimal) -> str | None:
    risk = entry - stop
    pct = risk_pct(entry, stop)
    if risk <= 0 or pct <= 0:
        return "INVALID_RISK_DISTANCE"
    if pct > config.RS_PULLBACK_MAX_RISK_DISTANCE_PCT:
        return "RISK_DISTANCE_TOO_HIGH"
    return None


def build_signal(symbol: str, bingx_symbol: str, timeframe: str, features: RSPullbackFeatures) -> RSPullbackSignal | None:
    if not config.RS_PULLBACK_ENABLED:
        return None
    if filter_skip_reason(features):
        return None

    entry = calculate_entry(features.signal_close, features.atr_value)
    stop = calculate_stop(entry, features.atr_value)
    risk = entry - stop
    pct = risk_pct(entry, stop)
    if validate_risk(entry, stop):
        return None
    tp1, tp2, tp3 = calculate_targets(entry, risk)

    feature_dict = {
        "relative_strength_1h": str(features.relative_strength_1h),
        "price_change_1h": str(features.price_change_1h),
        "volume_ratio_15m": str(features.volume_ratio_15m),
        "oi_change_15m": str(features.oi_change_15m),
        "btc_change_1h": str(features.btc_change_1h),
        "atr_value": str(features.atr_value),
    }
    return RSPullbackSignal(
        strategy_name=STRATEGY_NAME,
        signal_source=SIGNAL_SOURCE,
        symbol=symbol,
        bingx_symbol=bingx_symbol,
        direction="LONG",
        setup_type=SETUP_TYPE,
        timeframe=timeframe,
        signal_ts=features.signal_ts,
        signal_close=features.signal_close,
        entry_model=ENTRY_MODEL,
        entry_price=entry,
        stop_model=STOP_MODEL,
        stop_price=stop,
        risk_price=risk,
        risk_pct=pct,
        tp1_price=tp1,
        tp2_price=tp2,
        tp3_price=tp3,
        atr_period=config.RS_PULLBACK_ATR_PERIOD,
        atr_value=features.atr_value,
        relative_strength_1h=features.relative_strength_1h,
        price_change_1h=features.price_change_1h,
        volume_ratio_15m=features.volume_ratio_15m,
        oi_change_15m=features.oi_change_15m,
        btc_change_1h=features.btc_change_1h,
        features_json=feature_dict,
        reason_json={"setup": SETUP_TYPE, "display_name": DISPLAY_NAME},
    )


def calculate_atr(candles: list[Candle], period: int) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    selected = candles[-(period + 1):]
    true_ranges: list[Decimal] = []
    for index in range(1, len(selected)):
        current = selected[index]
        previous = selected[index - 1]
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(true_ranges) / Decimal(period)


def move_sl_after_tp1_price(entry: Decimal, risk: Decimal) -> Decimal:
    return entry + risk * config.RS_PULLBACK_MOVE_SL_AFTER_TP1_TO_R


def can_move_stop_up(current_stop: Decimal, new_stop: Decimal, entry: Decimal, initial_stop: Decimal) -> bool:
    return new_stop > current_stop and new_stop >= entry and new_stop >= initial_stop


def max_favorable_r(entry: Decimal, risk: Decimal, max_price_since_entry: Decimal) -> Decimal:
    if risk <= 0:
        return Decimal("0")
    return ((max_price_since_entry - entry) / risk).quantize(Decimal("0.00000001"))
