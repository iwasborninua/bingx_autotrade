import argparse
import asyncio
from decimal import Decimal
from typing import Any

from app import config
from app.bingx.client import BingXClient, BingXCredentials
from app.services.bingx_trader import (
    ORDER_TYPE_MARKET,
    POSITION_LONG,
    POSITION_SHORT,
    position_pnl,
    position_quantity,
    validate_crypto_only_contract,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit or close open non-crypto BingX positions.")
    parser.add_argument("--close", action="store_true", help="Close non-crypto positions by market order.")
    parser.add_argument("--yes", action="store_true", help="Required together with --close.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.close and not args.yes:
        raise SystemExit("--close requires --yes")

    client = BingXClient(
        BingXCredentials(config.BINGX_API, config.BINGX_SECRET),
        base_url=config.BINGX_BASE_URL,
        demo=config.BINGX_DEMO,
    )
    try:
        await audit_or_close_non_crypto_positions(client, close=args.close)
    finally:
        await client.close()


async def audit_or_close_non_crypto_positions(client: BingXClient, *, close: bool) -> None:
    positions = [position for position in await client.open_positions() if position_quantity(position, default=Decimal("0")) > 0]
    contracts = {str(contract.get("symbol")): contract for contract in await client.contracts()}
    non_crypto = []

    for position in positions:
        symbol = str(position.get("symbol"))
        contract = contracts.get(symbol) or fallback_contract(symbol)
        try:
            validate_crypto_only_contract(contract, symbol)
        except Exception as exc:
            non_crypto.append((position, contract, str(exc)))

    print(f"positions={len(positions)} non_crypto={len(non_crypto)} mode={'close' if close else 'dry-run'}")
    for position, contract, reason in non_crypto:
        symbol = str(position.get("symbol"))
        quantity = position_quantity(position, default=Decimal("0"))
        print(
            f"NON_CRYPTO symbol={symbol} display={contract.get('displayName')} asset={contract.get('asset')} "
            f"side={position.get('positionSide')} qty={quantity} margin={position.get('initialMargin') or position.get('margin')} "
            f"pnl={position_pnl(position)} reason={reason}"
        )
        if close:
            await close_position(client, position)


async def close_position(client: BingXClient, position: dict[str, Any]) -> None:
    symbol = str(position.get("symbol"))
    position_side = str(position.get("positionSide") or "").upper()
    if position_side == POSITION_SHORT:
        side = "BUY"
    else:
        side = "SELL"
        position_side = POSITION_LONG

    quantity = position_quantity(position, default=Decimal("0"))
    response = await client.place_order(
        symbol=symbol,
        side=side,
        position_side=position_side,
        order_type=ORDER_TYPE_MARKET,
        quantity=quantity,
    )
    print(f"CLOSED symbol={symbol} qty={quantity} response={response}")


def fallback_contract(symbol: str) -> dict[str, str]:
    return {
        "symbol": symbol,
        "asset": symbol.split("-", 1)[0],
        "displayName": symbol,
    }


if __name__ == "__main__":
    asyncio.run(main())
