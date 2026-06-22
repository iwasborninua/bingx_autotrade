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
    paper_pnl = to_decimal(data.get("paper_active_pnl"))
    paper_margin = to_decimal(data.get("paper_active_margin"))
    total_pnl = to_decimal(data.get("total_pnl"))
    total_margin = to_decimal(data.get("total_margin"))

    print(title)
    print(f"Total Trades : {int(data.get('total_trades') or 0)}")
    print(
        f"Active       : {int(data.get('active_trades') or 0)} | "
        f"Margin {money(active_margin)} | "
        f"PnL {money(active_pnl)} | "
        f"ROI {pct(percent(active_pnl, active_margin))}"
    )
    print(f"Opening      : {int(data.get('opening_trades') or 0)}")
    print(
        f"Paper Active : {int(data.get('paper_active_trades') or 0)} | "
        f"Margin {money(paper_margin)} | "
        f"PnL {money(paper_pnl)} | "
        f"ROI {pct(percent(paper_pnl, paper_margin))}"
    )
    print(
        f"Closed       : {int(data.get('closed_trades') or 0)} | "
        f"Margin {money(closed_margin)} | "
        f"PnL {money(closed_pnl)} | "
        f"ROI {pct(percent(closed_pnl, closed_margin))}"
    )
    print(f"Reached TP1  : {int(data.get('reached_tp1_trades') or 0)}")
    print(f"Reached TP2  : {int(data.get('reached_tp2_trades') or 0)}")
    print(f"Reached TP3  : {int(data.get('reached_tp3_trades') or 0)}")
    print(f"Full TP3     : {int(data.get('full_tp3_trades') or 0)}")
    print(f"TP1 Stop     : {int(data.get('tp1_stop_trades') or 0)}")
    print(f"TP2 Stop     : {int(data.get('tp2_stop_trades') or 0)}")
    print(f"Closed BE    : {int(data.get('be_closed_trades') or 0)}")
    print(f"SL before TP1: {int(data.get('sl_before_tp1_trades') or 0)}")
    print(f"User closed  : {int(data.get('user_closed_trades') or 0)}")
    print(f"Active in TP1: {int(data.get('active_reached_tp1_trades') or 0)}")
    print(
        f"All Trades   : Margin {money(total_margin)} | "
        f"PnL {money(total_pnl)} | "
        f"ROI {pct(percent(total_pnl, total_margin))}"
    )


if __name__ == "__main__":
    asyncio.run(main())
