import asyncio
from decimal import Decimal
from typing import Any

from app.db import connect
from app.repositories.trade_repository import trade_stats, trade_stats_by_topic


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
        by_topic = await trade_stats_by_topic(connection)
    finally:
        connection.close()

    print_stats_block("All Topics", data)
    if by_topic:
        print()
        print("By Topic")
        for row in by_topic:
            print()
            print_stats_block(f"Topic {row.get('topic_id')}", row)


def print_stats_block(title: str, data: dict[str, Any]) -> None:
    active_pnl = to_decimal(data.get("active_pnl"))
    active_margin = to_decimal(data.get("active_margin"))
    closed_pnl = to_decimal(data.get("closed_pnl"))
    closed_margin = to_decimal(data.get("closed_margin"))
    total_pnl = to_decimal(data.get("total_pnl"))
    total_margin = to_decimal(data.get("total_margin"))

    print(title)
    print(f"Total Trades : {int(data.get('total_trades') or 0)}")
    print(f"Active       : {int(data.get('active_trades') or 0)} | PnL {money(active_pnl)} | ROI {pct(percent(active_pnl, active_margin))}")
    print(f"Closed       : {int(data.get('closed_trades') or 0)} | PnL {money(closed_pnl)} | ROI {pct(percent(closed_pnl, closed_margin))}")
    print(f"TP           : {int(data.get('tp_trades') or 0)}")
    print(f"SL           : {int(data.get('sl_trades') or 0)}")
    print(f"Reached TP1  : {int(data.get('reached_tp1_trades') or 0)}")
    print(f"Closed BE    : {int(data.get('be_closed_trades') or 0)}")
    print(f"SL before TP1: {int(data.get('sl_before_tp1_trades') or 0)}")
    print(f"Active in TP1: {int(data.get('active_reached_tp1_trades') or 0)}")
    print(f"All Trades   : PnL {money(total_pnl)} | ROI {pct(percent(total_pnl, total_margin))}")


if __name__ == "__main__":
    asyncio.run(main())
