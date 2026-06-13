from decimal import Decimal
import re


SIGNED_DECIMAL = r"([+-]?[0-9]+(?:\.[0-9]+)?)"


def parse_signal(text: str) -> dict[str, object]:
    """Parse a Telegram trading signal into columns used by the signals table."""
    open_interest_raw = parse_open_interest_raw(text)

    return {
        "symbol": parse_symbol(text),
        "direction": parse_direction(text),
        "price": parse_price(rf"Price:\s*\$?{SIGNED_DECIMAL}", text),
        "change_24h": parse_decimal(rf"24h Change:\s*{SIGNED_DECIMAL}%", text),
        "rsi_14": parse_decimal(rf"RSI\s*\(14\):\s*{SIGNED_DECIMAL}", text),
        "market_sentiment": parse_int(r"Market Sentiment:\s*([0-9]+)\s*/\s*100", text),
        "macd": parse_text_line(r"MACD:\s*([^\r\n]+)", text),
        "open_interest_raw": open_interest_raw,
        "open_interest_value": parse_open_interest_value(open_interest_raw),
        "funding_rate": parse_decimal(rf"Funding Rate:\s*{SIGNED_DECIMAL}%", text),
        "signal_score": parse_decimal(rf"Signal Score:\s*{SIGNED_DECIMAL}", text),
        "sl_price": parse_price(rf"Stop Loss:\s*\$?{SIGNED_DECIMAL}", text),
        "sl_percent": parse_decimal(
            rf"Stop Loss:\s*\$?{SIGNED_DECIMAL}\s*\(([0-9]+(?:\.[0-9]+)?)%\)",
            text,
            group=2,
        ),
        "tp1_price": parse_price(rf"TP1:\s*\$?{SIGNED_DECIMAL}", text),
        "tp2_price": parse_price(rf"TP2:\s*\$?{SIGNED_DECIMAL}", text),
        "tp3_price": parse_price(rf"TP3:\s*\$?{SIGNED_DECIMAL}", text),
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


def parse_decimal(pattern: str, text: str, *, group: int = 1) -> Decimal | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return Decimal(match.group(group).replace(",", "").replace("+", ""))


def parse_price(pattern: str, text: str, *, group: int = 1) -> Decimal | None:
    value = parse_decimal(pattern, text, group=group)
    if value is None:
        return None
    return abs(value)


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
