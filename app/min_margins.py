import argparse
import asyncio
import csv
import sys
from decimal import Decimal, ROUND_UP
from typing import Any

from app import config
from app.bingx.client import BingXClient


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'), rounding=ROUND_UP)}"


def quantity_notional(contract: dict[str, Any], price: Decimal) -> Decimal:
    min_quantity = to_decimal(
        contract.get("tradeMinQuantity")
        or contract.get("minVol")
        or contract.get("minQty")
        or contract.get("tradeMinLimit")
    )
    return min_quantity * price


def min_order_notional(contract: dict[str, Any], price: Decimal) -> Decimal:
    min_usdt = to_decimal(contract.get("tradeMinUSDT") or contract.get("minNotional"))
    return max(min_usdt, quantity_notional(contract, price))


def min_margin(contract: dict[str, Any], price: Decimal, leverage: int) -> Decimal:
    if leverage <= 0:
        raise ValueError("Leverage must be greater than 0")
    return min_order_notional(contract, price) / Decimal(leverage)


def is_open_crypto_usdt_contract(contract: dict[str, Any]) -> bool:
    symbol = str(contract.get("symbol") or "")
    if not symbol.endswith("-USDT"):
        return False
    if str(contract.get("currency") or "").upper() != "USDT":
        return False
    if str(contract.get("apiStateOpen", "true")).lower() != "true":
        return False
    return str(contract.get("status") or "1") in {"1", "TRADING", "ENABLED"}


async def load_rows(leverage: int) -> list[dict[str, Any]]:
    async with BingXClient(base_url=config.BINGX_BASE_URL, demo=config.BINGX_DEMO) as client:
        contracts = await client.contracts()
        prices = {str(row.get("symbol")): to_decimal(row.get("price")) for row in await client.prices()}

    rows = []
    for contract in contracts:
        if not is_open_crypto_usdt_contract(contract):
            continue
        symbol = str(contract.get("symbol"))
        price = prices.get(symbol)
        if not price:
            continue
        notional = min_order_notional(contract, price)
        rows.append(
            {
                "symbol": symbol,
                "price": price,
                "min_quantity": to_decimal(contract.get("tradeMinQuantity")),
                "min_order_usdt": notional,
                "min_margin": notional / Decimal(leverage),
            }
        )
    return sorted(rows, key=lambda row: (row["min_margin"], row["symbol"]))


def print_rows(rows: list[dict[str, Any]], *, leverage: int, limit: int | None) -> None:
    shown = rows[:limit] if limit else rows
    print(f"BingX USDT Futures Minimum Margin, leverage={leverage}x")
    print(f"Pairs: {len(rows)}")
    print()
    print(f"{'Symbol':<24} {'Min Margin':>12} {'Min Order':>12} {'Min Qty':>16} {'Price':>16}")
    for row in shown:
        print(
            f"{row['symbol']:<24} "
            f"{money(row['min_margin']):>12} "
            f"{money(row['min_order_usdt']):>12} "
            f"{str(row['min_quantity']):>16} "
            f"{str(row['price']):>16}"
        )


def print_csv(rows: list[dict[str, Any]], *, limit: int | None) -> None:
    shown = rows[:limit] if limit else rows
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=["symbol", "min_margin", "min_order_usdt", "min_quantity", "price"],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in shown:
        writer.writerow(
            {
                "symbol": row["symbol"],
                "min_margin": format(row["min_margin"], "f"),
                "min_order_usdt": format(row["min_order_usdt"], "f"),
                "min_quantity": format(row["min_quantity"], "f"),
                "price": format(row["price"], "f"),
            }
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Print minimum margin for BingX USDT futures crypto pairs.")
    parser.add_argument("--leverage", type=int, default=config.BINGX_LEVERAGE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--format", choices=("table", "csv"), default="table")
    args = parser.parse_args()

    rows = await load_rows(args.leverage)
    if args.format == "csv":
        print_csv(rows, limit=args.limit)
    else:
        print_rows(rows, leverage=args.leverage, limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())
