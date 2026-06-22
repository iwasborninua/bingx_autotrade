import asyncio
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app import config
from app.bingx.client import BingXClient, BingXCredentials
from app.db import connect
from app.market_data.coinalyze_client import CoinalyzeClient
from app.market_data.symbol_mapping import build_symbol_mappings
from app.own_strategy.feature_builder import build_features
from app.own_strategy.rs_pullback_v1 import Candle, OpenInterestPoint, R_MODEL, STRATEGY_NAME, build_signal, filter_skip_reason
from app.repositories import market_data_repository, own_signal_repository, trade_repository
from app.services.fear_greed_service import sync_daily_fear_greed_index
from app.services.bingx_trader import (
    POSITION_LONG,
    actual_entry_price_from_open,
    actual_margin_from_position,
    bounded_leverage,
    calculate_volume,
    ensure_margin_type,
    extract_id,
    extract_order_id,
    find_exchange_position,
    format_exception,
    get_contract,
    make_client_order_id,
    place_stop_loss_order,
    place_take_profit_order,
    position_quantity,
    validate_contract,
)


async def run_own_strategy_scanner(*, dry_run: bool = False) -> None:
    if not config.OWN_STRATEGY_ENABLED:
        print("OWN STRATEGY disabled: OWN_STRATEGY_ENABLED=false")
        return
    if config.OWN_STRATEGY_NAME != STRATEGY_NAME:
        raise RuntimeError(f"Unsupported OWN_STRATEGY_NAME={config.OWN_STRATEGY_NAME}")

    connection = await connect()
    bingx_client = BingXClient(
        BingXCredentials(config.BINGX_API, config.BINGX_SECRET),
        base_url=config.BINGX_BASE_URL,
        demo=config.BINGX_DEMO,
        public_max_requests_per_minute=config.BINGX_MARKET_MAX_REQUESTS_PER_MINUTE,
    )
    coinalyze_client = CoinalyzeClient(
        api_key=config.COINALYZE_API_KEY,
        base_url=config.COINALYZE_BASE_URL,
        max_requests_per_minute=config.COINALYZE_MAX_REQUESTS_PER_MINUTE,
        reserve_requests=config.COINALYZE_REQUEST_RESERVE,
    )
    try:
        await own_signal_repository.ensure_own_strategy_tables(connection)
        await market_data_repository.ensure_market_data_tables(connection)
        await trade_repository.ensure_trades_table(connection)
        if not own_trading_capabilities_ok(bingx_client):
            print("RS_PULLBACK_V1 requires exchange-side SL management. Auto trading disabled.")
            return
        fill_watcher_task = None
        if not dry_run:
            fill_watcher_task = asyncio.create_task(run_opening_order_watcher())
        while True:
            await sync_fear_greed_for_own_mode(connection)
            if dry_run:
                await sync_opening_own_trades(connection, bingx_client)
            await scan_once(connection, bingx_client, coinalyze_client)
            if dry_run:
                return
            await asyncio.sleep(config.OWN_SCAN_INTERVAL_SECONDS)
    finally:
        if "fill_watcher_task" in locals() and fill_watcher_task:
            fill_watcher_task.cancel()
            try:
                await fill_watcher_task
            except asyncio.CancelledError:
                pass
        connection.close()
        await bingx_client.close()
        await coinalyze_client.close()


def own_trading_capabilities_ok(client: BingXClient) -> bool:
    if config.PAPER_TRADING or not config.OWN_AUTO_TRADE_ENABLED:
        return True
    return (
        getattr(client, "supports_stop_loss_orders", False)
        and getattr(client, "supports_place_stop_order", False)
        and getattr(client, "supports_cancel_stop_order", False)
    )


async def run_opening_order_watcher() -> None:
    connection = await connect()
    client = BingXClient(
        BingXCredentials(config.BINGX_API, config.BINGX_SECRET),
        base_url=config.BINGX_BASE_URL,
        demo=config.BINGX_DEMO,
        public_max_requests_per_minute=config.BINGX_MARKET_MAX_REQUESTS_PER_MINUTE,
    )
    try:
        while True:
            try:
                await sync_opening_own_trades(connection, client)
            except Exception as exc:
                print(f"OWN OPENING WATCHER ERROR: {exc}")
            await asyncio.sleep(config.OWN_ORDER_FILL_CHECK_INTERVAL_SECONDS)
    finally:
        connection.close()
        await client.close()


async def sync_fear_greed_for_own_mode(connection) -> None:
    try:
        await sync_daily_fear_greed_index(connection)
    except Exception as exc:
        print(f"FEAR_GREED WARNING own_mode: {exc}")


async def scan_once(connection, bingx_client: BingXClient, coinalyze_client: CoinalyzeClient) -> None:
    mappings = await load_universe(connection, bingx_client, coinalyze_client)
    btc_candles = await load_bingx_candles(bingx_client, "BTCUSDT", config.OWN_SCAN_TIMEFRAME)
    if not btc_candles:
        print("OWN SCANNER skip: BTCUSDT candles unavailable")
        return
    oi_by_symbol = await load_open_interest_batches(coinalyze_client, mappings, config.OWN_SCAN_TIMEFRAME)

    for mapping in mappings:
        symbol = str(mapping["normalized_symbol"])
        if symbol == "BTCUSDT":
            continue
        try:
            candles = await load_bingx_candles(bingx_client, symbol, config.OWN_SCAN_TIMEFRAME)
            oi = oi_by_symbol.get(str(mapping["coinalyze_symbol"]), [])
            await persist_market_data(connection, symbol, config.OWN_SCAN_TIMEFRAME, candles, oi)
            features, skip_reason = build_features(
                symbol_candles=candles,
                btc_candles=btc_candles,
                open_interest=oi,
                now=datetime.now(timezone.utc),
            )
            if features is None:
                print(f"OWN SIGNAL SKIP symbol={symbol} reason={skip_reason}")
                continue
            filter_reason = filter_skip_reason(features)
            if filter_reason:
                print(f"OWN SIGNAL SKIP symbol={symbol} reason={filter_reason}")
                continue
            signal = build_signal(symbol, str(mapping["bingx_symbol"]), config.OWN_SCAN_TIMEFRAME, features)
            if signal is None:
                print(f"OWN SIGNAL SKIP symbol={symbol} reason=RISK_OR_STRATEGY_DISABLED")
                continue
            signal_id = await own_signal_repository.save_own_signal(connection, signal)
            if signal_id is None:
                continue
            print(
                "OWN SIGNAL "
                f"strategy={signal.strategy_name} symbol={symbol} ts={signal.signal_ts} "
                f"close={signal.signal_close} rs={signal.relative_strength_1h} "
                f"entry={signal.entry_price} sl={signal.stop_price} risk_pct={signal.risk_pct} "
                f"tp1={signal.tp1_price} tp2={signal.tp2_price} tp3={signal.tp3_price}"
            )
            await maybe_execute_signal(connection, bingx_client, signal_id, signal)
        except Exception as exc:
            print(f"OWN SCANNER ERROR symbol={symbol}: {exc}")


async def load_universe(connection, bingx_client: BingXClient, coinalyze_client: CoinalyzeClient) -> list[dict[str, Any]]:
    try:
        contracts = await bingx_client.contracts()
        coinalyze_markets = await coinalyze_client.get_markets()
        mappings = build_symbol_mappings(contracts, coinalyze_markets)
        if config.OWN_SYMBOL_WHITELIST:
            mappings = [item for item in mappings if item["normalized_symbol"] in config.OWN_SYMBOL_WHITELIST]
        mappings.sort(key=lambda item: item["normalized_symbol"])
        total_matched = len(mappings)
        if config.OWN_MAX_SYMBOLS > 0:
            mappings = mappings[: config.OWN_MAX_SYMBOLS]
        await market_data_repository.upsert_symbol_mappings(connection, mappings)
        print(
            "OWN UNIVERSE "
            f"bingx_contracts={len(contracts)} coinalyze_markets={len(coinalyze_markets)} "
            f"matched={total_matched} scanning={len(mappings)} max_symbols={config.OWN_MAX_SYMBOLS}"
        )
        return mappings
    except Exception as exc:
        fallback = await market_data_repository.active_symbol_mappings(connection, config.OWN_MAX_SYMBOLS)
        print(f"OWN UNIVERSE WARNING refresh failed, using db fallback count={len(fallback)}: {exc}")
        return fallback


async def load_bingx_candles(client: BingXClient, symbol: str, timeframe: str) -> list[Candle]:
    limit = max(config.RS_PULLBACK_ATR_PERIOD + 25, 60)
    rows = await client.klines(symbol=symbol, interval=timeframe, limit=limit)
    candles = [parse_bingx_candle(row) for row in rows]
    candles = [candle for candle in candles if candle is not None]
    candles.sort(key=lambda candle: candle.ts)
    if config.OWN_USE_CLOSED_CANDLES_ONLY and len(candles) > 1:
        candles = candles[:-1]
    return candles


async def load_open_interest(
    client: CoinalyzeClient,
    mapping: dict[str, Any],
    timeframe: str,
) -> list[OpenInterestPoint]:
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp())
    rows = await client.get_open_interest(str(mapping["coinalyze_symbol"]), timeframe, start_ts, end_ts)
    points = [parse_oi_point(row) for row in rows]
    points = [point for point in points if point is not None]
    points.sort(key=lambda point: point.ts)
    return points


async def load_open_interest_batches(
    client: CoinalyzeClient,
    mappings: list[dict[str, Any]],
    timeframe: str,
) -> dict[str, list[OpenInterestPoint]]:
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp())
    symbols = [str(mapping["coinalyze_symbol"]) for mapping in mappings if mapping.get("coinalyze_symbol")]
    result: dict[str, list[OpenInterestPoint]] = {}
    batch_size = max(config.COINALYZE_OI_BATCH_SIZE, 1)
    for batch in chunks(symbols, batch_size):
        try:
            raw_by_symbol = await client.get_open_interest_many(batch, timeframe, start_ts, end_ts)
        except Exception as exc:
            print(f"OWN SCANNER OI BATCH ERROR symbols={len(batch)} first={batch[0] if batch else ''}: {exc}")
            continue
        for coinalyze_symbol, rows in raw_by_symbol.items():
            points = [parse_oi_point(row) for row in rows]
            parsed = [point for point in points if point is not None]
            parsed.sort(key=lambda point: point.ts)
            result[coinalyze_symbol] = parsed
        print(
            "OWN SCANNER OI batch "
            f"requested={len(batch)} returned={len(raw_by_symbol)} "
            f"loaded_total={len(result)}/{len(symbols)}"
        )
    print(f"OWN SCANNER OI batches loaded symbols={len(result)}/{len(symbols)} batch_size={batch_size}")
    return result


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


async def persist_market_data(
    connection,
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    open_interest: list[OpenInterestPoint],
) -> None:
    await market_data_repository.upsert_candles(
        connection,
        [
            {
                "symbol": symbol,
                "exchange": "BINGX",
                "timeframe": timeframe,
                "ts": candle.ts,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "source": "bingx",
            }
            for candle in candles
        ],
    )
    await market_data_repository.upsert_open_interest(
        connection,
        [
            {
                "symbol": symbol,
                "exchange": "BINGX",
                "timeframe": timeframe,
                "ts": point.ts.replace(tzinfo=None) if point.ts.tzinfo else point.ts,
                "open_interest": point.open_interest,
                "source": "coinalyze",
            }
            for point in open_interest
        ],
    )


async def maybe_execute_signal(connection, bingx_client: BingXClient, signal_id: int, signal) -> None:
    if config.PAPER_TRADING:
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason="PAPER_TRADING_ENABLED",
        )
        print(f"OWN REAL ORDER SKIP own_signal_id={signal_id} symbol={signal.symbol}: PAPER_TRADING=true")
        return
    if not config.AUTO_TRADE_ENABLED or not config.OWN_AUTO_TRADE_ENABLED:
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason="AUTO_TRADE_DISABLED",
        )
        return
    if config.KILL_SWITCH:
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason="KILL_SWITCH",
        )
        return
    if await trade_repository.active_trade_for_symbol(connection, signal.bingx_symbol):
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason="DUPLICATE_SYMBOL",
        )
        return
    if await trade_repository.count_open_trades(connection) >= config.BINGX_LIMIT_OPENED_POSITIONS:
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason="GLOBAL_OPEN_POSITION_LIMIT",
        )
        return
    if await count_own_open_or_opening(connection) >= config.OWN_MAX_OPEN_POSITIONS:
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="SKIPPED",
            skip_reason="OWN_OPEN_POSITION_LIMIT",
        )
        return

    await place_real_limit_order(connection, bingx_client, signal_id, signal)


async def place_real_limit_order(connection, bingx_client: BingXClient, signal_id: int, signal) -> None:
    try:
        contract = await get_contract(bingx_client, signal.bingx_symbol)
        contract_symbol = str(contract.get("symbol") or signal.bingx_symbol)
        validate_contract(contract, contract_symbol)
        leverage = bounded_leverage(contract)
        volume = calculate_volume(contract, signal.entry_price, leverage)
        contract_size = Decimal(str(contract.get("contractSize") or "1"))
        fee_rate = Decimal(str(contract.get("makerFeeRate") or contract.get("takerFeeRate") or "0"))
    except Exception as exc:
        reason = format_exception(exc)
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="ORDER_FAILED",
            skip_reason=reason,
        )
        print(f"OWN ORDER PRECHECK FAILED own_signal_id={signal_id} symbol={signal.symbol}: {reason}")
        return

    trade_id = await trade_repository.insert_open_trade(
        connection,
        {
            "signal_id": None,
            "source_signal_id": signal_id,
            "signal_source": "own",
            "strategy_name": signal.strategy_name,
            "setup_type": signal.setup_type,
            "external_id": make_own_external_id(signal_id),
            "symbol": signal.symbol,
            "contract_symbol": contract_symbol,
            "direction": "BUY",
            "status": "OPENING",
            "entry_model": signal.entry_model,
            "stop_model": signal.stop_model,
            "r_model": R_MODEL,
            "entry_price": signal.entry_price,
            "avg_entry_price": signal.entry_price,
            "margin_usdt": config.BINGX_MARGIN,
            "original_sl_price": signal.stop_price,
            "initial_sl_price": signal.stop_price,
            "initial_stop_price": signal.stop_price,
            "current_sl_price": signal.stop_price,
            "current_stop_price": signal.stop_price,
            "tp1_price": signal.tp1_price,
            "tp2_price": signal.tp2_price,
            "tp3_price": signal.tp3_price,
            "risk_price": signal.risk_price,
            "risk_pct": signal.risk_pct,
            "margin": config.BINGX_MARGIN,
            "leverage": leverage,
            "volume": volume,
            "contract_size": contract_size,
            "fee_rate": fee_rate,
            "protection_status": "NO_PROTECTION",
            "sl_move_status": "NOT_REQUIRED",
        },
    )
    try:
        await ensure_margin_type(bingx_client, contract_symbol)
        await bingx_client.set_leverage(leverage=leverage, symbol=contract_symbol, side=POSITION_LONG)
        order = await bingx_client.place_order(
            symbol=contract_symbol,
            side="BUY",
            position_side=POSITION_LONG,
            order_type="LIMIT",
            quantity=volume,
            price=signal.entry_price,
            client_order_id=make_client_order_id(signal_id=signal_id, trade_id=trade_id),
        )
        order_id = extract_order_id(order)
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                UPDATE trades
                SET bingx_order_id=%s,
                    raw_open_response=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (order_id, trade_repository.to_json({"entry_order": order}), trade_id),
            )
        await own_signal_repository.update_own_signal_status(connection, signal_id=signal_id, status="ORDER_PLACED")
        print(
            f"OWN LIMIT ORDER PLACED own_signal_id={signal_id} trade_id={trade_id} "
            f"symbol={contract_symbol} price={signal.entry_price} volume={volume} order_id={order_id}"
        )
    except Exception as exc:
        reason = format_exception(exc)
        await trade_repository.mark_trade_open_failed(connection, trade_id=trade_id, reason=reason, raw_response=getattr(exc, "response", None))
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=signal_id,
            status="ORDER_FAILED",
            skip_reason=reason,
        )
        print(f"OWN LIMIT ORDER FAILED own_signal_id={signal_id} trade_id={trade_id}: {reason}")


async def sync_opening_own_trades(connection, bingx_client: BingXClient) -> None:
    trades = await trade_repository.opening_own_trades(connection)
    for trade in trades:
        try:
            await sync_one_opening_own_trade(connection, bingx_client, trade)
        except Exception as exc:
            print(f"OWN OPENING SYNC ERROR trade_id={trade.get('id')} symbol={trade.get('contract_symbol')}: {exc}")


async def sync_one_opening_own_trade(connection, bingx_client: BingXClient, trade: dict[str, Any]) -> None:
    created_at = parse_trade_time(trade.get("created_at"))
    if created_at and datetime.now(timezone.utc) - created_at >= timedelta(hours=config.RS_PULLBACK_TTL_HOURS):
        cancel_response = None
        try:
            if trade.get("bingx_order_id"):
                cancel_response = await bingx_client.cancel_order(
                    symbol=trade["contract_symbol"],
                    order_id=trade["bingx_order_id"],
                )
        finally:
            await trade_repository.mark_trade_cancelled(
                connection,
                trade_id=trade["id"],
                reason="EXPIRED_NOT_FILLED",
                raw_response=cancel_response,
            )
            if trade.get("source_signal_id"):
                await own_signal_repository.update_own_signal_status(
                    connection,
                    signal_id=int(trade["source_signal_id"]),
                    status="EXPIRED_NOT_FILLED",
                )
            print(f"OWN LIMIT ORDER EXPIRED trade_id={trade['id']} symbol={trade['contract_symbol']}")
        return

    position = await find_exchange_position(bingx_client, trade["contract_symbol"], "BUY")
    if not position:
        return

    actual_entry = actual_entry_price_from_open(position, {"orderId": trade.get("bingx_order_id")}, default=trade["entry_price"])
    risk = Decimal(str(trade.get("risk_price") or "0"))
    if risk <= 0:
        risk = Decimal(str(trade["entry_price"])) - Decimal(str(trade["initial_sl_price"]))
    stop_price = actual_entry - risk
    tp1_price = actual_entry + risk * config.RS_PULLBACK_TP1_R
    tp2_price = actual_entry + risk * config.RS_PULLBACK_TP2_R
    tp3_price = actual_entry + risk * config.RS_PULLBACK_TP3_R
    quantity = position_quantity(position, default=Decimal(str(trade["volume"])))
    log_protection_event(
        "ORDER_FILLED",
        trade_id=trade["id"],
        symbol=trade["contract_symbol"],
        qty=quantity,
        entry_price=actual_entry,
        new_sl=stop_price,
        tp3_price=tp3_price,
        bingx_response=position,
    )

    try:
        log_protection_event(
            "SL_PLACE_ATTEMPT",
            trade_id=trade["id"],
            symbol=trade["contract_symbol"],
            qty=quantity,
            entry_price=actual_entry,
            new_sl=stop_price,
        )
        stop_order_id = await place_stop_loss_order(
            bingx_client,
            symbol=trade["contract_symbol"],
            side="SELL",
            quantity=quantity,
            stop_price=stop_price,
            position_side=POSITION_LONG,
        )
        log_protection_event(
            "SL_PLACED",
            trade_id=trade["id"],
            symbol=trade["contract_symbol"],
            qty=quantity,
            entry_price=actual_entry,
            new_sl=stop_price,
            exchange_sl_order_id=stop_order_id,
        )
    except Exception as exc:
        reason = format_exception(exc)
        log_protection_event(
            "SL_PLACE_FAILED",
            trade_id=trade["id"],
            symbol=trade["contract_symbol"],
            qty=quantity,
            entry_price=actual_entry,
            new_sl=stop_price,
            error=reason,
        )
        await mark_protection_failed(connection, trade["id"], reason)
        print(f"OWN PROTECTION FAILED trade_id={trade['id']} symbol={trade['contract_symbol']}: {reason}")
        if config.RS_PULLBACK_CLOSE_IF_SL_PLACE_FAILED:
            close_response = await bingx_client.place_order(
                symbol=trade["contract_symbol"],
                side="SELL",
                position_side=POSITION_LONG,
                order_type="MARKET",
                quantity=quantity,
            )
            await trade_repository.close_trade(
                connection,
                trade_id=trade["id"],
                reason="PROTECTION_FAILED_CLOSE",
                raw_close_response={"stop_error": reason, "close_order": close_response},
                close_price=actual_entry,
            )
            log_protection_event(
                "PROTECTION_FAILED_CLOSE",
                trade_id=trade["id"],
                symbol=trade["contract_symbol"],
                qty=quantity,
                entry_price=actual_entry,
                new_sl=stop_price,
                bingx_response=close_response,
                error=reason,
            )
            print(f"OWN EMERGENCY CLOSED trade_id={trade['id']} symbol={trade['contract_symbol']}")
        return

    tp_order_id = None
    try:
        log_protection_event(
            "TP_PLACE_ATTEMPT",
            trade_id=trade["id"],
            symbol=trade["contract_symbol"],
            qty=quantity,
            entry_price=actual_entry,
            tp3_price=tp3_price,
        )
        tp_order_id = await place_take_profit_order(
            bingx_client,
            symbol=trade["contract_symbol"],
            side="SELL",
            quantity=quantity,
            take_profit_price=tp3_price,
            position_side=POSITION_LONG,
        )
        log_protection_event(
            "TP_PLACED",
            trade_id=trade["id"],
            symbol=trade["contract_symbol"],
            qty=quantity,
            entry_price=actual_entry,
            tp3_price=tp3_price,
            exchange_tp_order_id=tp_order_id,
        )
    except Exception as exc:
        log_protection_event(
            "TP_PLACE_FAILED",
            trade_id=trade["id"],
            symbol=trade["contract_symbol"],
            qty=quantity,
            entry_price=actual_entry,
            tp3_price=tp3_price,
            error=format_exception(exc),
        )
        print(f"OWN TP3 WARNING trade_id={trade['id']} symbol={trade['contract_symbol']}: {format_exception(exc)}")

    await trade_repository.mark_trade_open(
        connection,
        trade_id=trade["id"],
        bingx_order_id=str(trade.get("bingx_order_id") or ""),
        bingx_position_id=extract_id(position, "positionId", "position_id", "id", "positionIdStr"),
        stop_plan_order_id=stop_order_id,
        avg_entry_price=actual_entry,
        margin=actual_margin_from_position(position),
        break_even_price=None,
        raw_open_response={"position": position, "stop_loss_order_id": stop_order_id, "take_profit_order_id": tp_order_id},
    )
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE trades
            SET initial_sl_price=%s,
                initial_stop_price=%s,
                current_sl_price=%s,
                current_stop_price=%s,
                tp1_price=%s,
                tp2_price=%s,
                tp3_price=%s,
                exchange_sl_order_id=COALESCE(%s, exchange_sl_order_id),
                exchange_tp_order_id=COALESCE(%s, exchange_tp_order_id),
                protection_status='INITIAL_SL_PLACED',
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (
                trade_repository.to_db_value(stop_price),
                trade_repository.to_db_value(stop_price),
                trade_repository.to_db_value(stop_price),
                trade_repository.to_db_value(stop_price),
                trade_repository.to_db_value(tp1_price),
                trade_repository.to_db_value(tp2_price),
                trade_repository.to_db_value(tp3_price),
                stop_order_id,
                tp_order_id,
                trade["id"],
            ),
        )
    if trade.get("source_signal_id"):
        await own_signal_repository.update_own_signal_status(
            connection,
            signal_id=int(trade["source_signal_id"]),
            status="FILLED",
        )
    print(
        f"OWN LIMIT FILLED SL PLACED trade_id={trade['id']} symbol={trade['contract_symbol']} "
        f"entry={actual_entry} sl={stop_price} sl_order_id={stop_order_id} tp_order_id={tp_order_id}"
    )


async def count_own_open_or_opening(connection) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            SELECT COUNT(*)
            FROM trades
            WHERE signal_source='own'
              AND strategy_name='RS_PULLBACK_V1'
              AND status IN ('OPENING', 'OPEN')
            """
        )
        row = await cursor.fetchone()
    return int(row[0] or 0)


def parse_trade_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def make_own_external_id(signal_id: int) -> str:
    return f"own:{signal_id}:{int(time.time() * 1000) % 1_000_000_000_000}"


async def mark_protection_failed(connection, trade_id: int, reason: str) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE trades
            SET protection_status='PROTECTION_FAILED',
                close_reason='PROTECTION_FAILED_CLOSE',
                error_message=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (reason, trade_id),
        )


def log_protection_event(event: str, **fields: Any) -> None:
    log_dir = config.BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    parts = [datetime.now(timezone.utc).isoformat(), event]
    for key, value in fields.items():
        if value is not None:
            parts.append(f"{key}={value}")
    Path(log_dir / "own_strategy_protection.log").open("a", encoding="utf-8").write(" ".join(parts) + "\n")


async def record_paper_trade(connection, signal_id: int, signal) -> None:
    existing = await trade_repository.active_trade_for_symbol(connection, signal.bingx_symbol)
    if existing is None:
        existing = await trade_repository.paper_trade_for_symbol(connection, signal.bingx_symbol)
    if existing and config.OWN_BLOCK_DUPLICATE_SYMBOL:
        return
    notional = config.BINGX_MARGIN * Decimal(config.BINGX_LEVERAGE)
    volume = notional / signal.entry_price if signal.entry_price > 0 else Decimal("0")
    try:
        await trade_repository.insert_open_trade(
            connection,
            {
                "signal_id": None,
                "source_signal_id": signal_id,
                "signal_source": "own",
                "strategy_name": signal.strategy_name,
                "setup_type": signal.setup_type,
                "external_id": make_own_external_id(signal_id),
                "symbol": signal.symbol,
                "contract_symbol": signal.bingx_symbol,
                "direction": "BUY",
                "status": "PAPER_ORDER",
                "entry_model": signal.entry_model,
                "stop_model": signal.stop_model,
                "r_model": R_MODEL,
                "entry_price": signal.entry_price,
                "avg_entry_price": signal.entry_price,
                "margin_usdt": config.BINGX_MARGIN,
                "original_sl_price": signal.stop_price,
                "initial_sl_price": signal.stop_price,
                "initial_stop_price": signal.stop_price,
                "current_sl_price": signal.stop_price,
                "current_stop_price": signal.stop_price,
                "tp1_price": signal.tp1_price,
                "tp2_price": signal.tp2_price,
                "tp3_price": signal.tp3_price,
                "risk_price": signal.risk_price,
                "risk_pct": signal.risk_pct,
                "margin": config.BINGX_MARGIN,
                "leverage": config.BINGX_LEVERAGE,
                "volume": volume,
                "contract_size": Decimal("1"),
                "fee_rate": Decimal("0"),
                "protection_status": "NO_PROTECTION",
                "sl_move_status": "NOT_REQUIRED",
            },
        )
    except Exception as exc:
        if "Duplicate entry" not in str(exc) and "1062" not in str(exc):
            raise


def parse_bingx_candle(row: Any) -> Candle | None:
    if isinstance(row, dict):
        ts = row.get("time") or row.get("openTime") or row.get("t")
        open_ = row.get("open") or row.get("o")
        high = row.get("high") or row.get("h")
        low = row.get("low") or row.get("l")
        close = row.get("close") or row.get("c")
        volume = row.get("volume") or row.get("v") or 0
    elif isinstance(row, (list, tuple)) and len(row) >= 6:
        ts, open_, high, low, close, volume = row[:6]
    else:
        return None
    ts_int = int(ts)
    if ts_int > 10_000_000_000:
        ts_int //= 1000
    return Candle(
        ts=datetime.fromtimestamp(ts_int, tz=timezone.utc).replace(tzinfo=None),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def parse_oi_point(row: Any) -> OpenInterestPoint | None:
    if not isinstance(row, dict):
        return None
    ts = row.get("t") or row.get("time") or row.get("timestamp")
    value = row.get("o") or row.get("open_interest") or row.get("openInterest") or row.get("c")
    if ts is None or value is None:
        return None
    ts_int = int(ts)
    if ts_int > 10_000_000_000:
        ts_int //= 1000
    return OpenInterestPoint(
        ts=datetime.fromtimestamp(ts_int, tz=timezone.utc),
        open_interest=Decimal(str(value)),
    )
