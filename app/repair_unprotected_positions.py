import argparse
import asyncio
from decimal import Decimal
from typing import Any

from app import config
from app.bingx.client import BingXClient, BingXCredentials
from app.db import connect
from app.repositories import trade_repository
from app.services.bingx_trader import (
    ORDER_TYPE_MARKET,
    POSITION_LONG,
    POSITION_SHORT,
    calculate_roi,
    count_protective_orders,
    extract_order_id,
    flatten_order_list,
    position_pnl,
    position_quantity,
    to_decimal,
)


PROTECTIVE_TYPES = {"STOP_MARKET", "TAKE_PROFIT_MARKET"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit or close BingX positions without TP/SL protection.")
    parser.add_argument("--close", action="store_true", help="Close unprotected positions by market order.")
    parser.add_argument("--protect", action="store_true", help="Put TP/SL on unprotected positions, freeing slots by canceling other TP orders.")
    parser.add_argument("--yes", action="store_true", help="Required together with --close.")
    parser.add_argument("--exchange-tpsl-limit", type=int, default=200, help="Real BingX TP/SL order limit.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.close and args.protect:
        raise SystemExit("Use either --close or --protect, not both")
    if (args.close or args.protect) and not args.yes:
        raise SystemExit("--close/--protect requires --yes")

    client = BingXClient(
        BingXCredentials(config.BINGX_API, config.BINGX_SECRET),
        base_url=config.BINGX_BASE_URL,
        demo=config.BINGX_DEMO,
    )
    connection = await connect()
    try:
        await repair_unprotected_positions(
            connection,
            client,
            close=args.close,
            protect=args.protect,
            exchange_tpsl_limit=args.exchange_tpsl_limit,
        )
    finally:
        await connection.ensure_closed()
        await client.close()


async def repair_unprotected_positions(
    connection,
    client: BingXClient,
    *,
    close: bool,
    protect: bool,
    exchange_tpsl_limit: int,
) -> None:
    positions = [position for position in await client.open_positions() if position_quantity(position, default=Decimal("0")) > 0]
    open_orders = flatten_order_list(await client.open_orders())
    orders_by_symbol = group_protective_orders(open_orders)
    latest_trades = await latest_trades_by_symbol(connection, [str(position.get("symbol")) for position in positions])

    unprotected = []
    for position in positions:
        symbol = str(position.get("symbol"))
        orders = orders_by_symbol.get(symbol, [])
        types = {str(order.get("type") or "").upper() for order in orders}
        if "STOP_MARKET" not in types or "TAKE_PROFIT_MARKET" not in types:
            unprotected.append((position, latest_trades.get(symbol), "STOP_MARKET" not in types, "TAKE_PROFIT_MARKET" not in types))

    mode = "close" if close else "protect" if protect else "dry-run"
    print(
        f"positions={len(positions)} protective_orders={count_protective_orders(open_orders)} "
        f"unprotected={len(unprotected)} mode={mode}"
    )

    missing_orders = sum(int(missing_sl) + int(missing_tp) for _, _, missing_sl, missing_tp in unprotected)
    free_slots = exchange_tpsl_limit - count_protective_orders(open_orders)
    tp_orders_to_cancel = max(0, missing_orders - free_slots)
    if unprotected:
        print(f"missing_protective_orders={missing_orders} free_slots={free_slots} tp_orders_to_cancel={tp_orders_to_cancel}")

    for position, trade, missing_sl, missing_tp in unprotected:
        symbol = str(position.get("symbol"))
        quantity = position_quantity(position, default=Decimal("0"))
        pnl = position_pnl(position)
        trade_id = trade.get("id") if trade else None
        print(
            f"UNPROTECTED symbol={symbol} side={position.get('positionSide')} qty={quantity} "
            f"margin={position.get('initialMargin') or position.get('margin')} pnl={pnl} "
            f"trade_id={trade_id} status={trade.get('status') if trade else None} "
            f"missing_sl={missing_sl} missing_tp={missing_tp}"
        )
        if close:
            await close_position(connection, client, position, trade)

    if protect:
        await protect_positions(
            connection,
            client,
            unprotected=unprotected,
            open_orders=open_orders,
            orders_by_symbol=orders_by_symbol,
            tp_orders_to_cancel=tp_orders_to_cancel,
        )


async def close_position(
    connection,
    client: BingXClient,
    position: dict[str, Any],
    trade: dict[str, Any] | None,
) -> None:
    symbol = str(position.get("symbol"))
    position_side = str(position.get("positionSide") or "").upper()
    if position_side == POSITION_SHORT:
        side = "BUY"
        direction = "SELL"
    else:
        side = "SELL"
        direction = "BUY"
        position_side = POSITION_LONG

    quantity = position_quantity(position, default=Decimal("0"))
    close_response = await client.place_order(
        symbol=symbol,
        side=side,
        position_side=position_side,
        order_type=ORDER_TYPE_MARKET,
        quantity=quantity,
    )
    print(f"CLOSED symbol={symbol} qty={quantity} response={close_response}")

    if not trade:
        return

    pnl = position_pnl(position)
    margin = to_decimal(position.get("initialMargin") or position.get("margin"), default=trade.get("margin"))
    roi = calculate_roi({**trade, "direction": direction, "margin": margin}, pnl) if pnl is not None else None
    await trade_repository.close_trade(
        connection,
        trade_id=int(trade["id"]),
        reason="UNPROTECTED_POSITION_EMERGENCY_CLOSED",
        raw_close_response={"position": position, "close_order": close_response},
        close_price=to_decimal(position.get("markPrice") or position.get("lastPrice") or position.get("avgPrice"), default=None),
        realized_roi=roi,
        realized_pnl=pnl,
    )


async def protect_positions(
    connection,
    client: BingXClient,
    *,
    unprotected: list[tuple[dict[str, Any], dict[str, Any] | None, bool, bool]],
    open_orders: list[dict[str, Any]],
    orders_by_symbol: dict[str, list[dict[str, Any]]],
    tp_orders_to_cancel: int,
) -> None:
    unprotected_symbols = {str(position.get("symbol")) for position, _, _, _ in unprotected}
    cancel_candidates = take_profit_cancel_candidates(open_orders, orders_by_symbol, exclude_symbols=unprotected_symbols)
    if len(cancel_candidates) < tp_orders_to_cancel:
        raise RuntimeError(f"Need to cancel {tp_orders_to_cancel} TP orders, found only {len(cancel_candidates)} candidates")

    for order in cancel_candidates[:tp_orders_to_cancel]:
        symbol = str(order.get("symbol"))
        order_id = extract_order_id(order)
        if not order_id:
            raise RuntimeError(f"Cannot extract order id for TP order: {order}")
        await client.cancel_order(symbol=symbol, order_id=order_id)
        print(f"CANCELED_TP symbol={symbol} order_id={order_id}")

    for position, trade, missing_sl, missing_tp in unprotected:
        if not trade:
            print(f"SKIP_PROTECT symbol={position.get('symbol')}: trade row not found")
            continue
        await protect_one_position(connection, client, position, trade, missing_sl=missing_sl, missing_tp=missing_tp)


async def protect_one_position(
    connection,
    client: BingXClient,
    position: dict[str, Any],
    trade: dict[str, Any],
    *,
    missing_sl: bool,
    missing_tp: bool,
) -> None:
    symbol = str(position.get("symbol"))
    position_side = str(position.get("positionSide") or "").upper()
    direction = "SELL" if position_side == POSITION_SHORT else "BUY"
    if position_side not in {POSITION_LONG, POSITION_SHORT}:
        position_side = POSITION_LONG
    close_side = "SELL" if direction == "BUY" else "BUY"
    quantity = position_quantity(position, default=to_decimal(trade["volume"]))
    stop_response = None
    tp_response = None

    if missing_sl:
        stop_response = await client.place_order(
            symbol=symbol,
            side=close_side,
            position_side=position_side,
            order_type="STOP_MARKET",
            quantity=quantity,
            stop_price=trade["current_sl_price"],
            close_position=True,
            working_type="MARK_PRICE",
        )
        print(f"PLACED_SL symbol={symbol} stop={trade['current_sl_price']} response={stop_response}")

    if missing_tp:
        tp_response = await client.place_order(
            symbol=symbol,
            side=close_side,
            position_side=position_side,
            order_type="TAKE_PROFIT_MARKET",
            quantity=quantity,
            stop_price=trade["tp3_price"],
            close_position=True,
            working_type="MARK_PRICE",
        )
        print(f"PLACED_TP symbol={symbol} tp={trade['tp3_price']} response={tp_response}")

    await mark_trade_repaired_open(
        connection,
        trade=trade,
        position=position,
        stop_plan_order_id=extract_order_id(stop_response) if stop_response is not None else trade.get("stop_plan_order_id"),
        raw_response={"position": position, "repair_stop_loss": stop_response, "repair_take_profit": tp_response},
    )


async def mark_trade_repaired_open(
    connection,
    *,
    trade: dict[str, Any],
    position: dict[str, Any],
    stop_plan_order_id: str | None,
    raw_response: dict[str, Any],
) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE trades
            SET status='OPEN',
                close_reason=NULL,
                stop_plan_order_id=COALESCE(%s, stop_plan_order_id),
                bingx_position_id=COALESCE(%s, bingx_position_id),
                avg_entry_price=COALESCE(%s, avg_entry_price),
                margin=COALESCE(%s, margin),
                raw_open_response=%s,
                opened_at=COALESCE(opened_at, CURRENT_TIMESTAMP),
                closed_at=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (
                stop_plan_order_id,
                position.get("positionId") or position.get("position_id") or position.get("id") or position.get("positionIdStr"),
                position.get("avgPrice") or position.get("averagePrice") or position.get("holdAvgPrice"),
                position.get("initialMargin") or position.get("margin"),
                trade_repository.to_json(raw_response),
                trade["id"],
            ),
        )


def take_profit_cancel_candidates(
    open_orders: list[dict[str, Any]],
    orders_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    exclude_symbols: set[str],
) -> list[dict[str, Any]]:
    symbols_with_stop = {
        symbol
        for symbol, orders in orders_by_symbol.items()
        if any(str(order.get("type") or "").upper() == "STOP_MARKET" for order in orders)
    }
    candidates = []
    for order in open_orders:
        symbol = str(order.get("symbol"))
        order_type = str(order.get("type") or "").upper()
        status = str(order.get("status") or "").upper()
        if symbol in exclude_symbols:
            continue
        if symbol not in symbols_with_stop:
            continue
        if order_type == "TAKE_PROFIT_MARKET" and (not status or status in {"NEW", "PENDING"}):
            candidates.append(order)
    return candidates


def group_protective_orders(open_orders: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in open_orders:
        order_type = str(order.get("type") or "").upper()
        status = str(order.get("status") or "").upper()
        if order_type not in PROTECTIVE_TYPES or (status and status not in {"NEW", "PENDING"}):
            continue
        grouped.setdefault(str(order.get("symbol")), []).append(order)
    return grouped


async def latest_trades_by_symbol(connection, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}

    placeholders = ", ".join(["%s"] * len(symbols))
    async with connection.cursor() as cursor:
        await cursor.execute(
            f"""
            SELECT *
            FROM trades
            WHERE contract_symbol IN ({placeholders})
            ORDER BY id DESC
            """,
            tuple(symbols),
        )
        columns = [column[0] for column in cursor.description]
        rows = await cursor.fetchall()

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        trade = dict(zip(columns, row))
        latest.setdefault(str(trade["contract_symbol"]), trade)
    return latest


if __name__ == "__main__":
    asyncio.run(main())
