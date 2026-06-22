import json
import re
from typing import Any

from app import config
from app.bingx.client import normalize_contract_symbol


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("-", "").replace("_", "").replace("PERP", "").split(".")[0]


def base_quote_from_bingx(contract: dict[str, Any]) -> tuple[str, str]:
    display = str(contract.get("displayName") or contract.get("symbol") or "").upper().replace(" ", "")
    if "-" in display:
        base, quote = display.split("-", 1)
        return base, quote
    symbol = normalize_symbol(str(contract.get("symbol") or ""))
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    return symbol, "USDT"


def base_quote_from_coinalyze(market: dict[str, Any]) -> tuple[str, str]:
    symbol = str(market.get("symbol") or "").upper()
    base = str(market.get("base_asset") or market.get("base") or "").upper()
    quote = str(market.get("quote_asset") or market.get("quote") or "").upper()
    if base and quote:
        return base, quote
    match = re.match(r"([A-Z0-9]+)USDT", symbol.replace("_", ""))
    if match:
        return match.group(1), "USDT"
    return normalize_symbol(symbol), "USDT"


def build_symbol_mappings(
    bingx_contracts: list[dict[str, Any]],
    coinalyze_markets: list[dict[str, Any]],
    blacklist: set[str] | None = None,
) -> list[dict[str, Any]]:
    blacklist = blacklist if blacklist is not None else config.OWN_SYMBOL_BLACKLIST
    coinalyze_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for market in coinalyze_markets:
        base, quote = base_quote_from_coinalyze(market)
        if quote == "USDT":
            coinalyze_by_pair[(base, quote)] = market

    mappings = []
    for contract in bingx_contracts:
        base, quote = base_quote_from_bingx(contract)
        normalized = f"{base}{quote}"
        if quote != "USDT" or normalized in blacklist:
            continue
        coinalyze_market = coinalyze_by_pair.get((base, quote))
        if not coinalyze_market:
            continue
        mappings.append(
            {
                "normalized_symbol": normalized,
                "bingx_symbol": normalize_contract_symbol(normalized),
                "coinalyze_symbol": coinalyze_market.get("symbol"),
                "base_asset": base,
                "quote_asset": quote,
                "market_type": "perpetual",
                "is_active": True,
                "is_crypto": True,
                "raw_bingx_json": json.dumps(contract, ensure_ascii=False, default=str),
                "raw_coinalyze_json": json.dumps(coinalyze_market, ensure_ascii=False, default=str),
            }
        )
    return mappings
