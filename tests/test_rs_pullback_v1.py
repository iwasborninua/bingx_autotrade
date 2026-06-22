from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from app.own_strategy.feature_builder import build_features
from app.own_strategy.rs_pullback_v1 import (
    Candle,
    OpenInterestPoint,
    RSPullbackFeatures,
    build_signal,
    calculate_entry,
    calculate_stop,
    calculate_targets,
    filter_skip_reason,
    move_sl_after_tp1_price,
    validate_risk,
)


class RSPullbackCalculationTest(unittest.TestCase):
    def test_filters_accept_only_when_all_thresholds_pass(self) -> None:
        features = RSPullbackFeatures(
            signal_ts=datetime(2026, 1, 1),
            signal_close=Decimal("100"),
            relative_strength_1h=Decimal("2"),
            price_change_1h=Decimal("1.5"),
            volume_ratio_15m=Decimal("1.8"),
            oi_change_15m=Decimal("1"),
            btc_change_1h=Decimal("-0.5"),
            atr_value=Decimal("2"),
        )

        self.assertIsNone(filter_skip_reason(features))
        self.assertIsNotNone(
            filter_skip_reason(
                RSPullbackFeatures(
                    **{**features.__dict__, "relative_strength_1h": Decimal("1.99")}
                )
            )
        )

    def test_entry_stop_and_targets(self) -> None:
        entry = calculate_entry(Decimal("100"), Decimal("2"), Decimal("1.0"))
        stop = calculate_stop(entry, Decimal("2"), Decimal("1.5"))
        tp1, tp2, tp3 = calculate_targets(entry, entry - stop)

        self.assertEqual(entry, Decimal("98.0"))
        self.assertEqual(stop, Decimal("95.0"))
        self.assertEqual(entry - stop, Decimal("3.0"))
        self.assertEqual(tp1, Decimal("100.250"))
        self.assertEqual(tp2, Decimal("102.50"))
        self.assertEqual(tp3, Decimal("105.50"))

    def test_risk_cap(self) -> None:
        self.assertEqual(validate_risk(Decimal("100"), Decimal("90")), "RISK_DISTANCE_TOO_HIGH")

    def test_build_signal_long_relative_strength_only(self) -> None:
        signal = build_signal(
            "ETHUSDT",
            "ETH-USDT",
            "15m",
            RSPullbackFeatures(
                signal_ts=datetime(2026, 1, 1),
                signal_close=Decimal("100"),
                relative_strength_1h=Decimal("2.1"),
                price_change_1h=Decimal("1.6"),
                volume_ratio_15m=Decimal("2.0"),
                oi_change_15m=Decimal("1.1"),
                btc_change_1h=Decimal("-0.4"),
                atr_value=Decimal("2"),
            ),
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(signal.setup_type, "LONG_RELATIVE_STRENGTH")
        self.assertEqual(signal.entry_model, "pullback_1_0_atr")

    def test_move_sl_after_tp1_to_half_r(self) -> None:
        self.assertEqual(move_sl_after_tp1_price(Decimal("98"), Decimal("3")), Decimal("99.5"))


class RSPullbackFeatureBuilderTest(unittest.TestCase):
    def test_missing_oi_skips_signal(self) -> None:
        features, reason = build_features(
            symbol_candles=sample_candles(),
            btc_candles=sample_candles(close_start=Decimal("100")),
            open_interest=[],
            now=datetime.now(timezone.utc),
        )

        self.assertIsNone(features)
        self.assertEqual(reason, "MISSING_OI")

    def test_stale_oi_skips_signal(self) -> None:
        now = datetime.now(timezone.utc)
        features, reason = build_features(
            symbol_candles=sample_candles(),
            btc_candles=sample_candles(close_start=Decimal("100")),
            open_interest=[
                OpenInterestPoint(now - timedelta(hours=1, minutes=15), Decimal("100")),
                OpenInterestPoint(now - timedelta(hours=1), Decimal("102")),
            ],
            now=now,
        )

        self.assertIsNone(features)
        self.assertEqual(reason, "STALE_OI")

    def test_oi_change_15m_is_calculated(self) -> None:
        now = datetime.now(timezone.utc)
        features, reason = build_features(
            symbol_candles=sample_candles(),
            btc_candles=sample_candles(close_start=Decimal("100")),
            open_interest=[
                OpenInterestPoint(now - timedelta(minutes=15), Decimal("100")),
                OpenInterestPoint(now, Decimal("102")),
            ],
            now=now,
        )

        self.assertIsNone(reason)
        self.assertEqual(features.oi_change_15m, Decimal("2.00000000"))


def sample_candles(close_start: Decimal = Decimal("100")) -> list[Candle]:
    start = datetime(2026, 1, 1)
    candles = []
    for index in range(30):
        close = close_start + Decimal(index)
        candles.append(
            Candle(
                ts=start + timedelta(minutes=15 * index),
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100") if index < 29 else Decimal("200"),
            )
        )
    return candles


if __name__ == "__main__":
    unittest.main()
