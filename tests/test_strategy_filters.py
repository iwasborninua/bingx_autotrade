from decimal import Decimal

from app.services.strategy import StrategySettings, should_accept_signal


def settings(**overrides):
    values = {
        "enable_signal_filters": True,
        "allowed_signal_side": "LONG",
        "enable_rr_tp3_filter": True,
        "rr_tp3_min": Decimal("0.8"),
        "rr_tp3_max": Decimal("1.5"),
        "enable_session_filter": True,
        "allowed_sessions": ("Asia",),
        "enable_btc_change_1h_filter": True,
        "btc_change_1h_min": Decimal("-1"),
        "btc_change_1h_max": Decimal("0"),
        "session_btc_filter_mode": "OR",
        "rr_filter_is_required": True,
        "tp1_close_percent": Decimal("0"),
        "tp2_close_percent": Decimal("0"),
        "tp3_close_percent": Decimal("100"),
        "stop_move_mode": "move_sl_to_be_after_tp1",
        "move_sl_to_be_on_tp1_touch": True,
    }
    values.update(overrides)
    return StrategySettings(**values)


def test_accepts_long_rr_and_asia_session():
    accepted, reason = should_accept_signal(
        {"side": "LONG", "rr_tp3": Decimal("1.2"), "session": "Asia", "btc_change_1h": Decimal("2")},
        settings(),
    )
    assert accepted is True
    assert reason == "accepted"


def test_accepts_long_rr_and_btc_change_when_session_fails():
    accepted, reason = should_accept_signal(
        {"side": "LONG", "rr_tp3": Decimal("1.2"), "session": "Europe", "btc_change_1h": Decimal("-0.5")},
        settings(),
    )
    assert accepted is True
    assert reason == "accepted"


def test_rejects_short_signal():
    accepted, reason = should_accept_signal(
        {"side": "SHORT", "rr_tp3": Decimal("1.2"), "session": "Asia", "btc_change_1h": Decimal("-0.5")},
        settings(),
    )
    assert accepted is False
    assert reason == "side_not_allowed"


def test_rejects_rr_out_of_range():
    accepted, reason = should_accept_signal(
        {"side": "LONG", "rr_tp3": Decimal("2.4"), "session": "Asia", "btc_change_1h": Decimal("-0.5")},
        settings(),
    )
    assert accepted is False
    assert reason == "rr_tp3_out_of_range"


def test_rejects_when_session_and_btc_filters_fail():
    accepted, reason = should_accept_signal(
        {"side": "LONG", "rr_tp3": Decimal("1.2"), "session": "Europe", "btc_change_1h": Decimal("1")},
        settings(),
    )
    assert accepted is False
    assert reason == "session_and_btc_filters_failed"


def test_disabled_filters_accept():
    accepted, reason = should_accept_signal(
        {"side": "SHORT"},
        settings(enable_signal_filters=False),
    )
    assert accepted is True
    assert reason == "filters_disabled"
