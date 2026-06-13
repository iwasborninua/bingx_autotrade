import asyncio
from decimal import Decimal
from typing import Any

from app.db import connect
from app.repositories.trade_repository import trade_stats


def percent(pnl: Decimal, margin: Decimal) -> Decimal:
    if margin <= 0:
        return Decimal("0")
    return (pnl / margin * Decimal("100")).quantize(Decimal("0.01"))


def money(value: Any) -> str:
    return f"${to_decimal(value).quantize(Decimal('0.01'))}"


def pct(value: Decimal) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value}%"


def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


async def main() -> None:
    connection = await connect()
    try:
        data = await trade_stats(connection)
    finally:
        connection.close()

    active_pnl = to_decimal(data.get("active_pnl"))
    active_margin = to_decimal(data.get("active_margin"))
    closed_pnl = to_decimal(data.get("closed_pnl"))
    closed_margin = to_decimal(data.get("closed_margin"))
    total_pnl = to_decimal(data.get("total_pnl"))
    total_margin = to_decimal(data.get("total_margin"))

    print("Stats")
    print(f"Total Trades : {int(data.get('total_trades') or 0)}")
    print(f"Active       : {int(data.get('active_trades') or 0)} | PnL {money(active_pnl)} | ROI {pct(percent(active_pnl, active_margin))}")
    print(f"Closed       : {int(data.get('closed_trades') or 0)} | PnL {money(closed_pnl)} | ROI {pct(percent(closed_pnl, closed_margin))}")
    print(f"TP           : {int(data.get('tp_trades') or 0)}")
    print(f"SL           : {int(data.get('sl_trades') or 0)}")
    print(f"All Trades   : PnL {money(total_pnl)} | ROI {pct(percent(total_pnl, total_margin))}")


if __name__ == "__main__":
    asyncio.run(main())
