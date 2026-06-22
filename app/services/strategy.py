from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app import config


@dataclass(frozen=True)
class StrategySettings:
    enable_signal_filters: bool
    allowed_signal_side: str
    enable_rr_tp3_filter: bool
    rr_tp3_min: Decimal
    rr_tp3_max: Decimal
    enable_session_filter: bool
    allowed_sessions: tuple[str, ...]
    enable_btc_change_1h_filter: bool
    btc_change_1h_min: Decimal
    btc_change_1h_max: Decimal
    session_btc_filter_mode: str
    rr_filter_is_required: bool
    tp1_close_percent: Decimal
    tp2_close_percent: Decimal
    tp3_close_percent: Decimal
    stop_move_mode: str
    move_sl_to_be_on_tp1_touch: bool


def settings_from_config() -> StrategySettings:
    return StrategySettings(
        enable_signal_filters=config.ENABLE_SIGNAL_FILTERS,
        allowed_signal_side=config.ALLOWED_SIGNAL_SIDE,
        enable_rr_tp3_filter=config.ENABLE_RR_TP3_FILTER,
        rr_tp3_min=config.RR_TP3_MIN,
        rr_tp3_max=config.RR_TP3_MAX,
        enable_session_filter=config.ENABLE_SESSION_FILTER,
        allowed_sessions=tuple(config.ALLOWED_SESSIONS),
        enable_btc_change_1h_filter=config.ENABLE_BTC_CHANGE_1H_FILTER,
        btc_change_1h_min=config.BTC_CHANGE_1H_MIN,
        btc_change_1h_max=config.BTC_CHANGE_1H_MAX,
        session_btc_filter_mode=config.SESSION_BTC_FILTER_MODE,
        rr_filter_is_required=config.RR_FILTER_IS_REQUIRED,
        tp1_close_percent=config.TP1_CLOSE_PERCENT,
        tp2_close_percent=config.TP2_CLOSE_PERCENT,
        tp3_close_percent=config.TP3_CLOSE_PERCENT,
        stop_move_mode=config.STOP_MOVE_MODE,
        move_sl_to_be_on_tp1_touch=config.MOVE_SL_TO_BE_ON_TP1_TOUCH,
    )


def should_accept_signal(signal: dict[str, Any], settings: StrategySettings) -> tuple[bool, str]:
    if not settings.enable_signal_filters:
        return True, "filters_disabled"

    side = normalized_side(signal.get("side"))
    if side is None:
        return False, "side_missing"
    if settings.allowed_signal_side != "BOTH" and side != settings.allowed_signal_side:
        return False, "side_not_allowed"

    if settings.enable_rr_tp3_filter or settings.rr_filter_is_required:
        rr_tp3 = to_decimal(signal.get("rr_tp3"))
        if rr_tp3 is None:
            return False, "rr_tp3_missing"
        if rr_tp3 < settings.rr_tp3_min or rr_tp3 > settings.rr_tp3_max:
            return False, "rr_tp3_out_of_range"

    session_enabled = settings.enable_session_filter
    btc_enabled = settings.enable_btc_change_1h_filter
    if not session_enabled and not btc_enabled:
        return True, "accepted"

    session_ok = None
    btc_ok = None

    if session_enabled:
        session = signal.get("session")
        if not session:
            session_ok = False
        else:
            session_ok = str(session) in settings.allowed_sessions

    if btc_enabled:
        btc_change = to_decimal(signal.get("btc_change_1h"))
        if btc_change is None:
            btc_ok = False
        else:
            btc_ok = settings.btc_change_1h_min <= btc_change <= settings.btc_change_1h_max

    if session_enabled and btc_enabled:
        if settings.session_btc_filter_mode == "AND":
            accepted = bool(session_ok and btc_ok)
        else:
            accepted = bool(session_ok or btc_ok)
        return (True, "accepted") if accepted else (False, "session_and_btc_filters_failed")

    if session_enabled:
        if signal.get("session") is None:
            return False, "session_missing"
        return (True, "accepted") if session_ok else (False, "session_filter_failed")

    if btc_enabled:
        if to_decimal(signal.get("btc_change_1h")) is None:
            return False, "btc_change_1h_missing"
        return (True, "accepted") if btc_ok else (False, "btc_change_1h_out_of_range")

    return True, "accepted"


def strategy_signal_from_fields(
    fields: dict[str, Any],
    *,
    rr_tp3: Decimal | None,
    signal_time: datetime | None,
) -> dict[str, Any]:
    side = normalized_side(fields.get("side") or fields.get("direction"))
    return {
        "symbol": fields.get("symbol"),
        "side": side,
        "rr_tp3": rr_tp3,
        "session": fields.get("session") or session_for_time(signal_time),
        "btc_change_1h": fields.get("btc_change_1h"),
        "entry_price": fields.get("price"),
        "tp1": fields.get("tp1_price"),
        "tp2": fields.get("tp2_price"),
        "tp3": fields.get("tp3_price"),
        "sl": fields.get("sl_price"),
        "signal_time": signal_time,
    }


def log_signal_filter_decision(signal: dict[str, Any], accepted: bool, reason: str) -> None:
    status = "ACCEPTED" if accepted else "REJECTED"
    print(
        f"{status} {signal.get('symbol') or 'UNKNOWN'} {signal.get('side') or 'UNKNOWN'} "
        f"rr_tp3={format_value(signal.get('rr_tp3'))} "
        f"session={signal.get('session') or 'missing'} "
        f"btc_change_1h={format_value(signal.get('btc_change_1h'))} "
        f"reason={reason}"
    )


def normalized_side(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in {"LONG", "BUY"}:
        return "LONG"
    if text in {"SHORT", "SELL"}:
        return "SHORT"
    return None


def session_for_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    hour = value.astimezone(timezone.utc).hour
    if 0 <= hour <= 7:
        return "Asia"
    if 8 <= hour <= 13:
        return "Europe"
    if 14 <= hour <= 21:
        return "US"
    return "Other"


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_value(value: Any) -> str:
    if value is None:
        return "missing"
    return str(value)
