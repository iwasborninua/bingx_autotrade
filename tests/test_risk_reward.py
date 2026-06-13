from decimal import Decimal
import unittest

from app.services.bingx_trader import risk_reward_ratio


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


if __name__ == "__main__":
    unittest.main()
