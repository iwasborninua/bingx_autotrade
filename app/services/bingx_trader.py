import asyncio
import html
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app import config
from app.bingx.client import BingXApiError, BingXClient, normalize_contract_symbol
from app.repositories import signal_repository, trade_repository


ORDER_TYPE_MARKET = "MARKET"
POSITION_LONG = "LONG"
POSITION_SHORT = "SHORT"


async def handle_new_signal(
    connection,
    client: BingXClient,
    *,
    signal_id: int,
    external_id: str,
    fields: dict[str, object],
) -> None:
    await trade_repository.ensure_trades_table(connection)
    symbol = str(fields.get("symbol") or "UNKNOWN")
    contract_symbol = normalize_contract_symbol(symbol) if symbol != "UNKNOWN" else "UNKNOWN"

    eligible, reason = await signal_is_eligible(connection, fields, contract_symbol=contract_symbol)
    if not eligible:
        await signal_repository.update_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason=reason,
        )
        print(f"TRADE SKIP signal_id={signal_id} symbol={symbol} contract={contract_symbol}: {reason}")
        return

    direction = str(fields["direction"])
    entry_price = to_decimal(fields["price"])
    sl_price = to_decimal(fields["sl_price"])
    tp1_price = to_decimal(fields["tp1_price"])
    tp2_price = to_decimal(fields["tp2_price"])
    tp3_price = to_decimal(fields["tp3_price"])

    exchange_position = await find_exchange_position(client, contract_symbol, direction=None)
    if exchange_position:
        reason = f"Position already exists on BingX for {contract_symbol}"
        await signal_repository.update_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason=reason,
        )
        print(f"TRADE SKIP signal_id={signal_id} symbol={symbol} contract={contract_symbol}: {reason}")
        return

    try:
        contract = await get_contract(client, contract_symbol)
        validate_contract(contract, contract_symbol)
        leverage = bounded_leverage(contract)
        volume = calculate_volume(contract, entry_price, leverage)
        contract_size = to_decimal(contract.get("contractSize"), default=Decimal("1"))
        fee_rate = to_decimal(contract.get("takerFeeRate"), default=Decimal("0"))
    except Exception as exc:
        await signal_repository.update_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason=str(exc),
        )
        print(f"TRADE SKIP signal_id={signal_id} symbol={symbol} contract={contract_symbol}: {exc}")
        return

    trade_id = await trade_repository.insert_open_trade(
        connection,
        {
            "signal_id": signal_id,
            "external_id": external_id,
            "symbol": symbol,
            "contract_symbol": contract_symbol,
            "direction": direction,
            "status": "OPENING",
            "entry_price": entry_price,
            "avg_entry_price": entry_price,
            "margin_usdt": config.BINGX_MARGIN,
            "original_sl_price": sl_price,
            "initial_sl_price": sl_price,
            "current_sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
            "margin": config.BINGX_MARGIN,
            "leverage": leverage,
            "volume": volume,
            "contract_size": contract_size,
            "fee_rate": fee_rate,
            "break_even_price": break_even_price(direction, entry_price, fee_rate),
        },
    )

    try:
        position_side = POSITION_LONG if direction == "BUY" else POSITION_SHORT
        await ensure_margin_type(client, contract_symbol)
        await client.set_leverage(
            leverage=leverage,
            symbol=contract_symbol,
            side=position_side,
        )
        open_response = await client.place_order(
            symbol=contract_symbol,
            side="BUY" if direction == "BUY" else "SELL",
            position_side=position_side,
            order_type=ORDER_TYPE_MARKET,
            quantity=volume,
            client_order_id=f"sig{signal_id}",
            stop_loss_price=sl_price,
            take_profit_price=tp3_price,
        )
        await asyncio.sleep(1)
        position = await find_exchange_position(client, contract_symbol, direction)
        stop_plan_order_id = await find_stop_plan_order_id(client, contract_symbol, position, open_response)

        await trade_repository.mark_trade_open(
            connection,
            trade_id=trade_id,
            bingx_order_id=extract_id(open_response, "orderId", "order_id"),
            bingx_position_id=extract_id(position, "positionId", "position_id", "id", "positionIdStr"),
            stop_plan_order_id=stop_plan_order_id,
            raw_open_response={"order": open_response, "position": position},
        )
        await signal_repository.update_signal_status(connection, signal_id=signal_id, status="POSITION_OPENED")
        print(f"TRADE OPENED signal_id={signal_id} trade_id={trade_id} symbol={contract_symbol} volume={volume}")
    except Exception as exc:
        reason = format_exception(exc)
        await trade_repository.mark_trade_open_failed(
            connection,
            trade_id=trade_id,
            reason=reason,
            raw_response=getattr(exc, "response", None),
        )
        await signal_repository.update_signal_status(
            connection,
            signal_id=signal_id,
            status="FAILED",
            skip_reason=reason,
        )
        print(f"TRADE OPEN FAILED signal_id={signal_id} trade_id={trade_id}: {reason}")


async def monitor_open_trades(connection, client: BingXClient) -> None:
    await trade_repository.ensure_trades_table(connection)
    while True:
        try:
            await sync_open_trades(connection, client)
            if config.BINGX_LOG_STATS_EACH_CHECK:
                await log_trade_stats(connection)
        except Exception as exc:
            print(f"TRADE MONITOR ERROR: {exc}")
        await asyncio.sleep(config.BINGX_POSITION_CHECK_INTERVAL_SECONDS)


async def ensure_margin_type(client: BingXClient, contract_symbol: str) -> None:
    margin_type = config.BINGX_MARGIN_TYPE
    if margin_type not in {"ISOLATED", "CROSSED", "SEPARATE_ISOLATED"}:
        raise ValueError(f"Unsupported BINGX_MARGIN_TYPE: {margin_type}")

    try:
        await client.set_margin_type(symbol=contract_symbol, margin_type=margin_type)
    except BingXApiError as exc:
        message = clean_error_text(str(exc)).lower()
        if exc.code == 109400 and ("positions" in message or "pending orders" in message):
            print(
                f"TRADE WARNING symbol={contract_symbol}: cannot change margin type to {margin_type} "
                "because there are existing positions or pending orders"
            )
            return
        raise


async def log_trade_stats(connection) -> None:
    stats = await trade_repository.trade_stats(connection)
    active_pnl = to_decimal(stats.get("active_pnl"))
    active_margin = to_decimal(stats.get("active_margin"))
    closed_pnl = to_decimal(stats.get("closed_pnl"))
    closed_margin = to_decimal(stats.get("closed_margin"))
    total_pnl = to_decimal(stats.get("total_pnl"))
    total_margin = to_decimal(stats.get("total_margin"))

    print(
        "STATS "
        f"total={int(stats.get('total_trades') or 0)} "
        f"active={int(stats.get('active_trades') or 0)} "
        f"closed={int(stats.get('closed_trades') or 0)} "
        f"tp={int(stats.get('tp_trades') or 0)} "
        f"sl={int(stats.get('sl_trades') or 0)} "
        f"active_pnl={format_money(active_pnl)} "
        f"active_roi={format_percent(percent(active_pnl, active_margin))} "
        f"closed_pnl={format_money(closed_pnl)} "
        f"closed_roi={format_percent(percent(closed_pnl, closed_margin))} "
        f"total_pnl={format_money(total_pnl)} "
        f"total_roi={format_percent(percent(total_pnl, total_margin))}"
    )


async def sync_open_trades(connection, client: BingXClient) -> None:
    trades = await trade_repository.active_trades(connection)
    if not trades:
        return

    exchange_positions = await client.open_positions()
    for trade in trades:
        try:
            await sync_one_open_trade(connection, client, trade, exchange_positions)
        except Exception as exc:
            print(
                f"TRADE MONITOR TRADE ERROR trade_id={trade.get('id')} "
                f"symbol={trade.get('contract_symbol')}: {exc}"
            )


async def sync_one_open_trade(
    connection,
    client: BingXClient,
    trade: dict[str, Any],
    exchange_positions: list[dict[str, Any]],
) -> None:
    position = find_matching_position(exchange_positions, trade)
    current_price = await current_market_price(client, trade["contract_symbol"])
    pnl = position_pnl(position) if position else None
    if pnl is None:
        pnl = calculate_pnl(trade, current_price, position)
    roi = calculate_roi(trade, pnl)

    if not position:
        reason = await infer_missing_position_reason(client, trade, current_price)
        close_result = await closed_trade_result_from_history(client, trade, current_price)
        close_price = close_result.get("close_price") or current_price
        realized_pnl = close_result.get("realized_pnl")
        if realized_pnl is None:
            realized_pnl = pnl
        realized_roi = calculate_roi(trade, realized_pnl)
        await trade_repository.close_trade(
            connection,
            trade_id=trade["id"],
            reason=reason,
            raw_close_response=close_result.get("raw_history"),
            close_price=close_price,
            realized_roi=realized_roi,
            realized_pnl=realized_pnl,
        )
        print(
            f"TRADE CLOSED trade_id={trade['id']} symbol={trade['contract_symbol']} "
            f"reason={reason} pnl={realized_pnl}"
        )
        return

    if reached_price(trade["direction"], current_price, trade["tp3_price"]):
        close_response = await client.place_order(
            symbol=trade["contract_symbol"],
            side="SELL" if trade["direction"] == "BUY" else "BUY",
            position_side=POSITION_LONG if trade["direction"] == "BUY" else POSITION_SHORT,
            order_type=ORDER_TYPE_MARKET,
            quantity=trade["volume"],
        )
        await asyncio.sleep(1)
        close_result = await closed_trade_result_from_history(client, trade, current_price)
        close_price = close_result.get("close_price") or current_price
        realized_pnl = close_result.get("realized_pnl")
        if realized_pnl is None:
            realized_pnl = pnl
        realized_roi = calculate_roi(trade, realized_pnl)
        await trade_repository.close_trade(
            connection,
            trade_id=trade["id"],
            reason="TP3_REACHED",
            raw_close_response={"close_order": close_response, "history": close_result.get("raw_history")},
            close_price=close_price,
            realized_roi=realized_roi,
            realized_pnl=realized_pnl,
        )
        print(
            f"TRADE CLOSED trade_id={trade['id']} symbol={trade['contract_symbol']} "
            f"reason=TP3_REACHED pnl={realized_pnl}"
        )
        return

    await maybe_move_stop_loss(connection, client, trade, current_price, roi, pnl)
    await trade_repository.update_trade_market(connection, trade_id=trade["id"], price=current_price, roi=roi, pnl=pnl)


async def signal_is_eligible(
    connection,
    fields: dict[str, object],
    *,
    contract_symbol: str | None = None,
) -> tuple[bool, str | None]:
    signal_score = to_decimal(fields.get("signal_score"), default=None)
    if signal_score is None:
        return False, "Signal score is missing"
    if signal_score < config.MIN_SIGNAL_SCORE:
        return False, f"Signal score {signal_score} is below minimum {config.MIN_SIGNAL_SCORE}"

    for key in ("price", "sl_price", "tp1_price", "tp2_price", "tp3_price"):
        value = to_decimal(fields.get(key), default=None)
        if value is None:
            return False, f"{key} is missing"
        if value <= 0:
            return False, f"{key} must be greater than 0"

    ratio = risk_reward_ratio(
        direction=str(fields["direction"]),
        entry=to_decimal(fields["price"]),
        stop_loss=to_decimal(fields["sl_price"]),
        take_profit=to_decimal(fields["tp3_price"]),
    )
    if ratio < config.BINGX_RISK_REWARD_RATIO:
        return False, f"Risk/reward {ratio} is below minimum {config.BINGX_RISK_REWARD_RATIO}"

    open_trades = await trade_repository.count_open_trades(connection)
    if open_trades >= config.BINGX_LIMIT_OPENED_POSITIONS:
        return False, f"Open trades limit reached: {open_trades}/{config.BINGX_LIMIT_OPENED_POSITIONS}"

    if contract_symbol:
        existing_trade = await trade_repository.active_trade_for_symbol(connection, contract_symbol)
        if existing_trade:
            return False, f"Open trade already exists for {contract_symbol}: trade_id={existing_trade['id']}"

    if config.BINGX_MARGIN <= 0:
        return False, "BINGX_MARGIN must be greater than 0"

    return True, None


async def maybe_move_stop_loss(
    connection,
    client: BingXClient,
    trade: dict[str, Any],
    current_price: Decimal,
    roi: Decimal | None,
    pnl: Decimal | None,
) -> None:
    direction = trade["direction"]
    next_stop = None
    reached_column = None

    if trade.get("tp2_reached_at") is None and reached_price(direction, current_price, trade["tp2_price"]):
        next_stop = fee_adjusted_stop(direction, trade["tp1_price"], trade["fee_rate"])
        reached_column = "tp2_reached_at"
    elif trade.get("break_even_moved_at") is None and (
        reached_price(direction, current_price, trade["tp1_price"]) or (roi is not None and roi >= Decimal("100"))
    ):
        next_stop = break_even_price(direction, trade["entry_price"], trade["fee_rate"])
        reached_column = "break_even_moved_at"

    if next_stop is None or reached_column is None:
        return

    if not improves_stop(direction, trade["current_sl_price"], next_stop):
        return

    stop_plan_order_id = trade.get("stop_plan_order_id")
    if stop_plan_order_id:
        print(
            f"TRADE WARNING trade_id={trade['id']}: BingX stop replacement is not implemented, "
            "only DB SL is updated"
        )
    else:
        print(f"TRADE WARNING trade_id={trade['id']}: stop_plan_order_id is missing, only DB SL is updated")

    await trade_repository.update_trade_stop(
        connection,
        trade_id=trade["id"],
        stop_price=next_stop,
        reached_column=reached_column,
        roi=roi,
        pnl=pnl,
        price=current_price,
    )
    print(f"TRADE SL MOVED trade_id={trade['id']} stop={next_stop} reason={reached_column}")


async def get_contract(client: BingXClient, contract_symbol: str) -> dict[str, Any]:
    contracts = await client.contracts(contract_symbol)
    for contract in contracts:
        if str(contract.get("symbol")) == contract_symbol:
            return contract
    if contracts:
        return contracts[0]
    raise ValueError(f"Contract {contract_symbol} was not found")


def validate_contract(contract: dict[str, Any], contract_symbol: str) -> None:
    api_open = str(contract.get("apiStateOpen", "true")).lower()
    if contract.get("apiAllowed") is False or contract.get("enableTrade") is False or api_open == "false":
        raise ValueError(f"Contract {contract_symbol} does not allow API trading")
    status = str(contract.get("status") or contract.get("state") or "TRADING").upper()
    if status not in {"TRADING", "ONLINE", "0", "1"}:
        raise ValueError(f"Contract {contract_symbol} is not enabled")


def bounded_leverage(contract: dict[str, Any]) -> int:
    min_leverage = int(contract.get("minLeverage") or 1)
    max_leverage = int(
        contract.get("maxLeverage")
        or contract.get("maxLongLeverage")
        or contract.get("maxShortLeverage")
        or config.BINGX_LEVERAGE
    )
    return max(min_leverage, min(config.BINGX_LEVERAGE, max_leverage))


def calculate_volume(contract: dict[str, Any], entry_price: Decimal, leverage: int) -> Decimal:
    quantity_precision = int(contract.get("quantityPrecision") or contract.get("volumePrecision") or 0)
    vol_unit = to_decimal(contract.get("volUnit"), default=Decimal(1).scaleb(-quantity_precision))
    min_vol = to_decimal(contract.get("minVol") or contract.get("minQty") or contract.get("tradeMinQuantity"), default=vol_unit)
    max_vol = to_decimal(contract.get("maxVol") or contract.get("maxQty") or contract.get("tradeMaxQuantity"), default=None)

    raw_volume = (config.BINGX_MARGIN * Decimal(leverage)) / entry_price
    volume = floor_to_unit(raw_volume, vol_unit)
    if volume < min_vol:
        raise ValueError(f"Calculated volume {volume} is below minVol {min_vol}")
    if max_vol is not None and volume > max_vol:
        volume = floor_to_unit(max_vol, vol_unit)
    return volume


async def find_exchange_position(
    client: BingXClient,
    contract_symbol: str,
    direction: str | None,
) -> dict[str, Any] | None:
    positions = await client.open_positions(contract_symbol)
    if direction is None:
        return positions[0] if positions else None
    return find_matching_position(
        positions,
        {
            "contract_symbol": contract_symbol,
            "direction": direction,
            "bingx_position_id": None,
        },
    )


def find_matching_position(positions: list[dict[str, Any]], trade: dict[str, Any]) -> dict[str, Any] | None:
    target_id = str(trade.get("bingx_position_id") or "")
    target_type = POSITION_LONG if trade["direction"] == "BUY" else POSITION_SHORT
    for position in positions:
        if str(position.get("symbol")) != trade["contract_symbol"]:
            continue
        if target_id and str(extract_id(position, "positionId", "position_id", "id", "positionIdStr")) == target_id:
            return position
        position_type = str(position.get("positionSide") or position.get("side") or target_type).upper()
        if position_type == target_type:
            return position
    return None


async def find_stop_plan_order_id(
    client: BingXClient,
    contract_symbol: str,
    position: dict[str, Any] | None,
    open_response: Any,
) -> str | None:
    response_id = extract_id(open_response, "stopPlanOrderId", "stop_plan_order_id", "stopLossOrderId")
    if response_id:
        return response_id
    return None


async def current_market_price(client: BingXClient, contract_symbol: str) -> Decimal:
    data = await client.price(contract_symbol)
    return to_decimal(data.get("price") or data.get("markPrice") or data.get("lastPrice"))


async def infer_missing_position_reason(client: BingXClient, trade: dict[str, Any], current_price: Decimal) -> str:
    if reached_price(trade["direction"], current_price, trade["tp3_price"]):
        return "TP3_REACHED"
    if stop_reached(trade["direction"], current_price, trade["current_sl_price"]):
        return stop_close_reason(trade)

    return "USER_CLOSED_OR_EXCHANGE_CLOSED"


def stop_close_reason(trade: dict[str, Any]) -> str:
    direction = str(trade["direction"])
    current_stop = to_decimal(trade.get("current_sl_price"), default=None)
    tp1_price = to_decimal(trade.get("tp1_price"), default=None)

    if trade.get("tp2_reached_at") is not None:
        return "TP2_STOP_TRIGGERED"
    if current_stop is not None and tp1_price is not None and reached_price(direction, current_stop, tp1_price):
        return "TP1_STOP_TRIGGERED"
    if trade.get("tp1_reached_at") is not None:
        return "TP1_STOP_TRIGGERED"

    return "STOP_LOSS_REACHED"


async def closed_trade_result_from_history(
    client: BingXClient,
    trade: dict[str, Any],
    fallback_price: Decimal,
) -> dict[str, Any]:
    start_time = trade_time_ms(trade.get("opened_at") or trade.get("created_at"), minutes_before=10)
    end_time = int(time.time() * 1000)
    raw_history: dict[str, Any] = {}

    income_rows = []
    try:
        income_data = await client.income(
            symbol=trade["contract_symbol"],
            income_type="REALIZED_PNL",
            start_time=start_time,
            end_time=end_time,
            limit=100,
        )
        income_rows = flatten_order_list(income_data)
        raw_history["income"] = income_data
    except BingXApiError as exc:
        raw_history["income_error"] = {"code": exc.code, "message": str(exc)}

    income_pnl = sum_decimal_fields(income_rows, "income", "amount", "incomeAmount", "realizedPnl", "realizedProfit")
    if income_rows and income_pnl is not None:
        return {
            "realized_pnl": income_pnl,
            "close_price": last_price_from_rows(income_rows) or fallback_price,
            "raw_history": raw_history,
        }

    fill_rows = []
    for name, loader in (
        ("all_fill_orders", client.all_fill_orders),
        ("fill_history", client.fill_history),
        ("all_orders", client.all_orders),
    ):
        try:
            data = await loader(symbol=trade["contract_symbol"], start_time=start_time, end_time=end_time, limit=100)
            rows = flatten_order_list(data)
            raw_history[name] = data
            fill_rows.extend(rows)
        except BingXApiError as exc:
            raw_history[f"{name}_error"] = {"code": exc.code, "message": str(exc)}

    matching_rows = rows_for_trade(fill_rows, trade)
    history_pnl = sum_decimal_fields(
        matching_rows,
        "realizedPnl",
        "realizedPNL",
        "realizedProfit",
        "profit",
        "pnl",
    )
    return {
        "realized_pnl": history_pnl,
        "close_price": last_price_from_rows(matching_rows) or fallback_price,
        "raw_history": raw_history,
    }


def risk_reward_ratio(direction: str, entry: Decimal, stop_loss: Decimal, take_profit: Decimal) -> Decimal:
    if direction == "BUY":
        risk = entry - stop_loss
        reward = take_profit - entry
    else:
        risk = stop_loss - entry
        reward = entry - take_profit

    if risk <= 0 or reward <= 0:
        return Decimal("0")
    return reward / risk


def position_pnl(position: dict[str, Any] | None) -> Decimal | None:
    if not position:
        return None
    return first_decimal_field(
        position,
        "unrealizedProfit",
        "unrealizedPnl",
        "unrealizedPNL",
        "unrealizedPnl",
        "pnl",
        "profit",
        "floatingProfit",
    )


def calculate_pnl(trade: dict[str, Any], current_price: Decimal, position: dict[str, Any] | None) -> Decimal:
    entry = (
        to_decimal(position.get("avgPrice") or position.get("averagePrice") or position.get("holdAvgPrice"), default=trade["entry_price"])
        if position
        else trade["entry_price"]
    )
    volume = (
        to_decimal(position.get("positionAmt") or position.get("availableAmt") or position.get("holdVol"), default=trade["volume"])
        if position
        else trade["volume"]
    )
    contract_size = (
        to_decimal(position.get("contractSize"), default=trade.get("contract_size") or Decimal("1"))
        if position
        else to_decimal(trade.get("contract_size"), default=Decimal("1"))
    )
    direction_factor = Decimal("1") if trade["direction"] == "BUY" else Decimal("-1")
    pnl = (current_price - entry) * direction_factor * volume * contract_size
    return pnl.quantize(Decimal("0.000000000001"))


def calculate_roi(trade: dict[str, Any], pnl: Decimal | None) -> Decimal | None:
    if pnl is None:
        return None
    margin = to_decimal(trade["margin"])
    if margin <= 0:
        return None
    return (pnl / margin * Decimal("100")).quantize(Decimal("0.00000001"))


def percent(pnl: Decimal, margin: Decimal) -> Decimal:
    if margin <= 0:
        return Decimal("0")
    return (pnl / margin * Decimal("100")).quantize(Decimal("0.01"))


def format_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def format_percent(value: Decimal) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value}%"


def rows_for_trade(rows: list[dict[str, Any]], trade: dict[str, Any]) -> list[dict[str, Any]]:
    order_id = str(trade.get("bingx_order_id") or "")
    external_id = str(trade.get("external_id") or "")
    signal_id = str(trade.get("signal_id") or "")
    client_ids = {value for value in (external_id, f"sig{signal_id}" if signal_id else "") if value}
    filtered = []
    for row in rows:
        if str(row.get("symbol") or "") != str(trade["contract_symbol"]):
            continue
        row_order_id = str(row.get("orderId") or row.get("order_id") or "")
        row_client_id = str(row.get("clientOrderID") or row.get("clientOrderId") or row.get("client_order_id") or "")
        if order_id and row_order_id == order_id:
            filtered.append(row)
        elif row_client_id and row_client_id in client_ids:
            filtered.append(row)
        elif not order_id and not client_ids:
            filtered.append(row)
    return filtered or [row for row in rows if str(row.get("symbol") or "") == str(trade["contract_symbol"])]


def sum_decimal_fields(rows: list[dict[str, Any]], *keys: str) -> Decimal | None:
    total = Decimal("0")
    found = False
    for row in rows:
        value = first_decimal_field(row, *keys)
        if value is not None:
            total += value
            found = True
    return total.quantize(Decimal("0.000000000001")) if found else None


def first_decimal_field(row: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return to_decimal(value, default=None)
    return None


def last_price_from_rows(rows: list[dict[str, Any]]) -> Decimal | None:
    for row in reversed(rows):
        price = first_decimal_field(row, "price", "avgPrice", "averagePrice", "executedPrice", "fillPrice")
        if price is not None:
            return price
    return None


def trade_time_ms(value: Any, *, minutes_before: int = 0) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000) - (minutes_before * 60 * 1000)


def break_even_price(direction: str, entry_price: Decimal, fee_rate: Decimal) -> Decimal:
    fee_multiplier = Decimal("1") + (fee_rate * Decimal("2"))
    if direction == "BUY":
        return entry_price * fee_multiplier
    return entry_price / fee_multiplier


def fee_adjusted_stop(direction: str, price: Decimal, fee_rate: Decimal) -> Decimal:
    fee_multiplier = Decimal("1") + (fee_rate * Decimal("2"))
    if direction == "BUY":
        return price * fee_multiplier
    return price / fee_multiplier


def reached_price(direction: str, current_price: Decimal, target_price: Decimal) -> bool:
    if direction == "BUY":
        return current_price >= target_price
    return current_price <= target_price


def stop_reached(direction: str, current_price: Decimal, stop_price: Decimal) -> bool:
    if direction == "BUY":
        return current_price <= stop_price
    return current_price >= stop_price


def improves_stop(direction: str, current_stop: Decimal, next_stop: Decimal) -> bool:
    if direction == "BUY":
        return next_stop > current_stop
    return next_stop < current_stop


def floor_to_unit(value: Decimal, unit: Decimal) -> Decimal:
    if unit <= 0:
        return value
    return (value / unit).to_integral_value(rounding=ROUND_DOWN) * unit


def flatten_order_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("resultList", "data", "list", "rows", "orders", "fill_orders", "fill_history_orders", "income"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def extract_id(data: Any, *keys: str) -> str | None:
    if isinstance(data, (str, int)):
        return str(data)
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def to_decimal(value: Any, default: Decimal | None = Decimal("0")) -> Decimal | None:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def format_exception(exc: Exception) -> str:
    if isinstance(exc, BingXApiError):
        details = clean_error_text(exc.response.get("message") or str(exc))
        path = f" path={exc.path}" if exc.path else ""
        return f"BingX API error code={exc.code}{path}: {details}"
    return clean_error_text(str(exc))


def clean_error_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:255]
