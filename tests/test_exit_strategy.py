import asyncio
from decimal import Decimal

from app.services.bingx_trader import maybe_close_partial_take_profit


class FakeClient:
    def __init__(self) -> None:
        self.orders = []

    async def place_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"order": kwargs}


def test_zero_tp1_tp2_percent_does_not_create_partial_close_orders():
    client = FakeClient()
    trade = {
        "id": 1,
        "contract_symbol": "BTC-USDT",
        "direction": "BUY",
        "volume": Decimal("1"),
        "tp1_price": Decimal("100"),
        "tp2_price": Decimal("110"),
        "tp1_closed_at": None,
        "tp2_closed_at": None,
    }
    position = {"availableAmt": "1"}

    asyncio.run(
        maybe_close_partial_take_profit(
            connection=None,
            client=client,
            trade=trade,
            position=position,
            current_price=Decimal("120"),
        )
    )

    assert client.orders == []
