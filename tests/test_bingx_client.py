from decimal import Decimal
import unittest

from app.bingx.client import BingXClient


class RecordingBingXClient(BingXClient):
    def __init__(self) -> None:
        super().__init__(credentials=None)
        self.requests = []

    async def _private_post(self, path, payload):
        self.requests.append((path, payload))
        return {"orderId": "test-order"}


class BingXClientOrderPayloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_position_stop_order_uses_close_position_with_quantity(self) -> None:
        client = RecordingBingXClient()

        await client.place_order(
            symbol="BTCUSDT",
            side="SELL",
            position_side="LONG",
            order_type="STOP_MARKET",
            quantity=Decimal("0.002"),
            stop_price=Decimal("50000"),
            close_position=True,
            working_type="MARK_PRICE",
        )

        path, payload = client.requests[0]
        self.assertEqual(path, "/openApi/swap/v2/trade/order")
        self.assertEqual(payload["symbol"], "BTC-USDT")
        self.assertEqual(payload["type"], "STOP_MARKET")
        self.assertEqual(payload["quantity"], Decimal("0.002"))
        self.assertEqual(payload["stopPrice"], Decimal("50000"))
        self.assertEqual(payload["closePosition"], "true")
        self.assertEqual(payload["workingType"], "MARK_PRICE")


if __name__ == "__main__":
    unittest.main()
