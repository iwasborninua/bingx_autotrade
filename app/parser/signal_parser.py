from decimal import Decimal
import re


def parse_signal(text: str) -> dict[str, object]:
    """Parse a Telegram trading signal into columns used by the signals table."""
    open_interest_raw = parse_open_interest_raw(text)

    return {
        "symbol": parse_symbol(text),
        "direction": parse_direction(text),
        "price": parse_decimal(r"Price:\s*\$?([0-9]+(?:\.[0-9]+)?)", text),
        "change_24h": parse_decimal(r"24h Change:\s*([+-]?[0-9]+(?:\.[0-9]+)?)%", text),
        "rsi_14": parse_decimal(r"RSI\s*\(14\):\s*([0-9]+(?:\.[0-9]+)?)", text),
        "market_sentiment": parse_int(r"Market Sentiment:\s*([0-9]+)\s*/\s*100", text),
        "macd": parse_text_line(r"MACD:\s*([^\r\n]+)", text),
        "open_interest_raw": open_interest_raw,
        "open_interest_value": parse_open_interest_value(open_interest_raw),
        "funding_rate": parse_decimal(r"Funding Rate:\s*([+-]?[0-9]+(?:\.[0-9]+)?)%", text),
        "signal_score": parse_decimal(r"Signal Score:\s*([+-]?[0-9]+(?:\.[0-9]+)?)", text),
        "sl_price": parse_decimal(r"Stop Loss:\s*\$?([0-9]+(?:\.[0-9]+)?)", text),
        "sl_percent": parse_decimal(
            r"Stop Loss:\s*\$?[0-9]+(?:\.[0-9]+)?\s*\(([0-9]+(?:\.[0-9]+)?)%\)",
            text,
        ),
        "tp1_price": parse_decimal(r"TP1:\s*\$?([0-9]+(?:\.[0-9]+)?)", text),
        "tp2_price": parse_decimal(r"TP2:\s*\$?([0-9]+(?:\.[0-9]+)?)", text),
        "tp3_price": parse_decimal(r"TP3:\s*\$?([0-9]+(?:\.[0-9]+)?)", text),
    }


def parse_symbol(text: str) -> str | None:
    upper = text.upper()
    setup_match = re.search(r"\b(?:BUY|SELL)\s*-\s*([A-Z0-9]{2,30})\s+PERP\b", upper)
    if setup_match:
        return setup_match.group(1)

    match = re.search(r"\b([A-Z0-9]{2,20})\s*/?\s*USDT\b", upper)
    if not match:
        return None
    return f"{match.group(1)}USDT"


def parse_direction(text: str) -> str | None:
    upper = text.upper()
    if re.search(r"\bBUY\s*-", upper) or re.search(r"\bLONG SETUP\b", upper):
        return "BUY"
    if re.search(r"\bSELL\s*-", upper) or re.search(r"\bSHORT SETUP\b", upper):
        return "SELL"
    return None


def parse_decimal(pattern: str, text: str) -> Decimal | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return Decimal(match.group(1).replace(",", "").replace("+", ""))


def parse_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def parse_text_line(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def parse_open_interest_raw(text: str) -> str | None:
    match = re.search(r"Open Interest:\s*\$?([^\r\n]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def parse_open_interest_value(raw_value: str | None) -> Decimal | None:
    if not raw_value:
        return None

    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMB])?", raw_value.upper())
    if not match:
        return None

    value = Decimal(match.group(1))
    multiplier = {
        "K": Decimal("1000"),
        "M": Decimal("1000000"),
        "B": Decimal("1000000000"),
    }.get(match.group(2), Decimal("1"))
    return value * multiplier
