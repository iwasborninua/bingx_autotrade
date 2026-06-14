from decimal import Decimal
import unittest

from app.services.bingx_trader import (
    actual_entry_price_from_open,
    break_even_price,
    current_stop_loss_order,
    extract_order_id,
    infer_missing_position_reason_from_price,
    is_missing_order_error,
    latest_order,
    make_client_order_id,
    risk_reward_ratio,
    stop_order_id_from_trade,
    stop_close_reason,
)
from app.bingx.client import BingXApiError


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


class MissingPositionReasonTest(unittest.TestCase):
    def test_manual_or_exchange_close_is_recorded_when_price_did_not_hit_targets(self) -> None:
        reason = infer_missing_position_reason_from_price(
            {
                "direction": "BUY",
                "current_sl_price": Decimal("95"),
                "tp3_price": Decimal("120"),
                "tp1_price": Decimal("110"),
                "tp1_reached_at": None,
                "tp2_reached_at": None,
            },
            Decimal("101"),
        )

        self.assertEqual(reason, "USER_CLOSED_OR_EXCHANGE_CLOSED")

    def test_missing_position_at_stop_price_records_stop_reason(self) -> None:
        reason = infer_missing_position_reason_from_price(
            {
                "direction": "SELL",
                "current_sl_price": Decimal("105"),
                "tp3_price": Decimal("80"),
                "tp1_price": Decimal("90"),
                "tp1_reached_at": None,
                "tp2_reached_at": None,
            },
            Decimal("106"),
        )

        self.assertEqual(reason, "STOP_LOSS_REACHED")


class EntryPriceTest(unittest.TestCase):
    def test_actual_entry_price_prefers_position_avg_price(self) -> None:
        price = actual_entry_price_from_open(
            {"avgPrice": "0.41894"},
            {"order": {"avgPrice": "0.41895"}},
            default=Decimal("0.414"),
        )

        self.assertEqual(price, Decimal("0.41894"))

    def test_break_even_uses_actual_average_entry(self) -> None:
        self.assertEqual(
            break_even_price("BUY", Decimal("0.41894"), Decimal("0.0005")),
            Decimal("0.41935894"),
        )


class StopOrderIdTest(unittest.TestCase):
    def test_extract_order_id_reads_nested_bingx_order_response(self) -> None:
        self.assertEqual(
            extract_order_id({"order": {"orderId": 123456}}),
            "123456",
        )

    def test_stop_order_id_reads_raw_open_response(self) -> None:
        self.assertEqual(
            stop_order_id_from_trade(
                {
                    "raw_open_response": '{"stop_loss":{"order":{"orderId":987654}}}',
                }
            ),
            "987654",
        )


class OrderSelectionTest(unittest.TestCase):
    def test_latest_order_prefers_highest_update_time(self) -> None:
        self.assertEqual(
            latest_order([{"orderId": 1, "updateTime": 10}, {"orderId": 2, "updateTime": 20}])["orderId"],
            2,
        )

    def test_current_stop_loss_order_filters_shared_open_orders(self) -> None:
        order = current_stop_loss_order(
            {"contract_symbol": "BTC-USDT", "direction": "BUY", "stop_plan_order_id": None},
            [
                {"symbol": "ETH-USDT", "side": "SELL", "positionSide": "LONG", "type": "STOP_MARKET", "orderId": 1},
                {"symbol": "BTC-USDT", "side": "SELL", "positionSide": "LONG", "type": "STOP_MARKET", "orderId": 2},
            ],
        )

        self.assertEqual(order["orderId"], 2)


class MissingOrderErrorTest(unittest.TestCase):
    def test_order_not_exist_is_recoverable_for_stop_replacement(self) -> None:
        self.assertTrue(is_missing_order_error(BingXApiError("order not exist", code=109400)))


class ClientOrderIdTest(unittest.TestCase):
    def test_client_order_id_is_short_and_not_just_signal_id(self) -> None:
        client_order_id = make_client_order_id(signal_id=4, trade_id=3)

        self.assertTrue(client_order_id.startswith("sig4tr3x"))
        self.assertLessEqual(len(client_order_id), 40)
        self.assertNotEqual(client_order_id, "sig4")


if __name__ == "__main__":
    unittest.main()
