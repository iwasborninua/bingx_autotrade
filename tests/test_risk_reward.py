from decimal import Decimal
import unittest

from app.services.bingx_trader import make_client_order_id, risk_reward_ratio, stop_close_reason


class RiskRewardRatioTest(unittest.TestCase):
    def test_buy_ratio_uses_tp3_distance_over_sl_distance(self) -> None:
        self.assertEqual(
            risk_reward_ratio("BUY", Decimal("100"), Decimal("90"), Decimal("120")),
            Decimal("2"),
        )

    def test_sell_ratio_uses_tp3_distance_over_sl_distance(self) -> None:
        self.assertEqual(
            risk_reward_ratio("SELL", Decimal("100"), Decimal("110"), Decimal("80")),
            Decimal("2"),
        )

    def test_invalid_geometry_returns_zero(self) -> None:
        self.assertEqual(
            risk_reward_ratio("BUY", Decimal("100"), Decimal("105"), Decimal("120")),
            Decimal("0"),
        )
        self.assertEqual(
            risk_reward_ratio("SELL", Decimal("100"), Decimal("95"), Decimal("80")),
            Decimal("0"),
        )


class StopCloseReasonTest(unittest.TestCase):
    def test_stop_at_tp1_counts_as_tp(self) -> None:
        self.assertEqual(
            stop_close_reason(
                {
                    "direction": "BUY",
                    "current_sl_price": Decimal("110"),
                    "tp1_price": Decimal("110"),
                    "tp1_reached_at": None,
                    "tp2_reached_at": None,
                }
            ),
            "TP1_STOP_TRIGGERED",
        )

    def test_tp2_reached_counts_as_tp2_even_when_stop_triggers(self) -> None:
        self.assertEqual(
            stop_close_reason(
                {
                    "direction": "SELL",
                    "current_sl_price": Decimal("90"),
                    "tp1_price": Decimal("90"),
                    "tp1_reached_at": None,
                    "tp2_reached_at": object(),
                }
            ),
            "TP2_STOP_TRIGGERED",
        )

    def test_initial_stop_counts_as_sl(self) -> None:
        self.assertEqual(
            stop_close_reason(
                {
                    "direction": "BUY",
                    "current_sl_price": Decimal("95"),
                    "tp1_price": Decimal("110"),
                    "tp1_reached_at": None,
                    "tp2_reached_at": None,
                }
            ),
            "STOP_LOSS_REACHED",
        )


class ClientOrderIdTest(unittest.TestCase):
    def test_client_order_id_is_short_and_not_just_signal_id(self) -> None:
        client_order_id = make_client_order_id(signal_id=4, trade_id=3)

        self.assertTrue(client_order_id.startswith("sig4tr3x"))
        self.assertLessEqual(len(client_order_id), 40)
        self.assertNotEqual(client_order_id, "sig4")


if __name__ == "__main__":
    unittest.main()
