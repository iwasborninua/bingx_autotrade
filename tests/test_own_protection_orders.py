from decimal import Decimal
import unittest

from app.bingx.client import BingXClient
from app.services.bingx_trader import place_stop_loss_order, place_take_profit_order


class RecordingProtectionClient(BingXClient):
    def __init__(self) -> None:
        super().__init__(credentials=None)
        self.requests = []

    async def _private_post(self, path, payload):
        self.requests.append((path, payload))
        return {"order": {"orderId": "protect-1"}}


class ProtectionOrderTest(unittest.IsolatedAsyncioTestCase):
    async def test_place_stop_loss_order_uses_exchange_side_stop_market(self) -> None:
        client = RecordingProtectionClient()

        order_id = await place_stop_loss_order(
            client,
            symbol="ID-USDT",
            side="SELL",
            quantity=Decimal("284"),
            stop_price=Decimal("0.0338575"),
            position_side="LONG",
        )

        _, payload = client.requests[0]
        self.assertEqual(order_id, "protect-1")
        self.assertEqual(payload["symbol"], "ID-USDT")
        self.assertEqual(payload["side"], "SELL")
        self.assertEqual(payload["positionSide"], "LONG")
        self.assertEqual(payload["type"], "STOP_MARKET")
        self.assertEqual(payload["stopPrice"], Decimal("0.0338575"))
        self.assertEqual(payload["closePosition"], "true")

    async def test_place_take_profit_order_uses_exchange_side_tp3(self) -> None:
        client = RecordingProtectionClient()

        order_id = await place_take_profit_order(
            client,
            symbol="ID-USDT",
            side="SELL",
            quantity=Decimal("284"),
            take_profit_price=Decimal("0.03850375"),
            position_side="LONG",
        )

        _, payload = client.requests[0]
        self.assertEqual(order_id, "protect-1")
        self.assertEqual(payload["type"], "TAKE_PROFIT_MARKET")
        self.assertEqual(payload["stopPrice"], Decimal("0.03850375"))
        self.assertEqual(payload["closePosition"], "true")


if __name__ == "__main__":
    unittest.main()
