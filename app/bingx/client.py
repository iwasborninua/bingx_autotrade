import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx


BINGX_BASE_URL = "https://open-api.bingx.com"


class BingXApiError(RuntimeError):
    """Raised when BingX returns an unsuccessful API response."""

    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
        path: str | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.response = response or {}


@dataclass(frozen=True)
class BingXCredentials:
    """API credentials for BingX swap endpoints."""

    api_key: str
    secret_key: str


class BingXClient:
    """Small async wrapper around BingX USDT perpetual swap REST API."""

    def __init__(
        self,
        credentials: BingXCredentials | None = None,
        *,
        base_url: str = BINGX_BASE_URL,
        demo: bool = False,
        recv_window: int = 10_000,
        timeout: float = 10.0,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.demo = demo
        self.recv_window = recv_window
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "BingXClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def server_time(self) -> int:
        data = await self._public_get("/openApi/swap/v2/server/time")
        return int(data.get("serverTime") or data.get("time") or 0)

    async def contracts(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": normalize_contract_symbol(symbol)} if symbol else None
        data = await self._public_get("/openApi/swap/v2/quote/contracts", params=params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("contracts"), list):
            return data["contracts"]
        return []

    async def price(self, symbol: str) -> dict[str, Any]:
        return await self._public_get("/openApi/swap/v2/quote/price", params={"symbol": normalize_contract_symbol(symbol)})

    async def prices(self) -> list[dict[str, Any]]:
        data = await self._public_get("/openApi/swap/v2/quote/price")
        return data if isinstance(data, list) else []

    async def account_balance(self, asset: str = "USDT") -> Any:
        return await self._private_get("/openApi/swap/v2/user/balance", params={"asset": asset.upper()})

    async def open_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": normalize_contract_symbol(symbol)} if symbol else None
        data = await self._private_get("/openApi/swap/v2/user/positions", params=params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("positions", "positionList", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    async def income(
        self,
        *,
        symbol: str | None = None,
        income_type: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._private_get(
            "/openApi/swap/v2/user/income",
            params=compact_dict(
                {
                    "symbol": normalize_contract_symbol(symbol) if symbol else None,
                    "incomeType": income_type,
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": limit,
                }
            ),
        )

    async def all_orders(
        self,
        *,
        symbol: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._private_get(
            "/openApi/swap/v2/trade/allOrders",
            params=compact_dict(
                {
                    "symbol": normalize_contract_symbol(symbol),
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": limit,
                }
            ),
        )

    async def all_fill_orders(
        self,
        *,
        symbol: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._private_get(
            "/openApi/swap/v2/trade/allFillOrders",
            params=compact_dict(
                {
                    "symbol": normalize_contract_symbol(symbol),
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": limit,
                }
            ),
        )

    async def fill_history(
        self,
        *,
        symbol: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> Any:
        return await self._private_get(
            "/openApi/swap/v2/trade/fillHistory",
            params=compact_dict(
                {
                    "symbol": normalize_contract_symbol(symbol),
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": limit,
                }
            ),
        )

    async def open_orders(self, *, symbol: str | None = None, order_type: str | None = None) -> Any:
        return await self._private_get(
            "/openApi/swap/v2/trade/openOrders",
            params=compact_dict(
                {
                    "symbol": normalize_contract_symbol(symbol) if symbol else None,
                    "type": order_type,
                }
            ),
        )

    async def set_leverage(self, *, symbol: str, side: str, leverage: int) -> Any:
        return await self._private_post(
            "/openApi/swap/v2/trade/leverage",
            {
                "symbol": normalize_contract_symbol(symbol),
                "side": side.upper(),
                "leverage": leverage,
            },
        )

    async def set_margin_type(self, *, symbol: str, margin_type: str) -> Any:
        return await self._private_post(
            "/openApi/swap/v2/trade/marginType",
            {
                "symbol": normalize_contract_symbol(symbol),
                "marginType": margin_type.upper(),
            },
        )

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        order_type: str,
        quantity: Decimal | int | float | str | None = None,
        price: Decimal | int | float | str | None = None,
        stop_price: Decimal | int | float | str | None = None,
        stop_loss_price: Decimal | int | float | str | None = None,
        take_profit_price: Decimal | int | float | str | None = None,
        close_position: bool | None = None,
        working_type: str | None = None,
        client_order_id: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "symbol": normalize_contract_symbol(symbol),
            "side": side.upper(),
            "positionSide": position_side.upper(),
            "type": order_type.upper(),
        }
        if quantity is not None:
            payload["quantity"] = quantity
        if price is not None:
            payload["price"] = price
        if stop_price is not None:
            payload["stopPrice"] = stop_price
        if close_position is not None:
            payload["closePosition"] = str(close_position).lower()
        if working_type:
            payload["workingType"] = working_type.upper()
        if client_order_id:
            payload["clientOrderID"] = client_order_id
        if stop_loss_price is not None:
            payload["stopLoss"] = to_json(
                {
                    "type": "STOP_MARKET",
                    "stopPrice": decimal_to_json_number(stop_loss_price),
                    "price": decimal_to_json_number(stop_loss_price),
                    "workingType": "MARK_PRICE",
                }
            )
        if take_profit_price is not None:
            payload["takeProfit"] = to_json(
                {
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": decimal_to_json_number(take_profit_price),
                    "price": decimal_to_json_number(take_profit_price),
                    "workingType": "MARK_PRICE",
                }
            )
        return await self._private_post("/openApi/swap/v2/trade/order", payload)

    async def cancel_order(self, *, symbol: str, order_id: int | str | None = None, client_order_id: str | None = None) -> Any:
        return await self._private_delete(
            "/openApi/swap/v2/trade/order",
            compact_dict(
                {
                    "symbol": normalize_contract_symbol(symbol),
                    "orderId": order_id,
                    "clientOrderID": client_order_id,
                }
            ),
        )

    async def _public_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._http.get(path, params=compact_dict(params or {}))
        return self._unwrap_response(response, path=path)

    async def _private_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        signed = self._signed_params(params or {})
        response = await self._http.get(path, params=signed, headers=self._auth_headers())
        return self._unwrap_response(response, path=path)

    async def _private_post(self, path: str, payload: dict[str, Any]) -> Any:
        signed = self._signed_params(payload)
        response = await self._http.post(path, params=signed, headers=self._auth_headers())
        return self._unwrap_response(response, path=path)

    async def _private_delete(self, path: str, payload: dict[str, Any]) -> Any:
        signed = self._signed_params(payload)
        response = await self._http.delete(path, params=signed, headers=self._auth_headers())
        return self._unwrap_response(response, path=path)

    def _signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.credentials:
            raise RuntimeError("BingX credentials are required for private endpoints")

        signed = compact_dict(params)
        signed["timestamp"] = int(time.time() * 1000)
        query = canonical_query(signed)
        signature = hmac.new(
            self.credentials.secret_key.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        ordered = {key: signed[key] for key in sorted(signed)}
        ordered["signature"] = signature
        return ordered

    def _auth_headers(self) -> dict[str, str]:
        if not self.credentials:
            raise RuntimeError("BingX credentials are required for private endpoints")
        return {"X-BX-APIKEY": self.credentials.api_key}

    @staticmethod
    def _unwrap_response(response: httpx.Response, *, path: str) -> Any:
        try:
            data = response.json()
        except ValueError:
            data = {"msg": response.text}

        if not isinstance(data, dict):
            if response.is_error:
                raise BingXApiError(
                    f"BingX API HTTP {response.status_code}",
                    code=response.status_code,
                    path=path,
                    response={"data": data},
                )
            return data

        if response.is_error:
            raise BingXApiError(
                data.get("msg") or data.get("message") or f"BingX API HTTP {response.status_code}",
                code=data.get("code") or response.status_code,
                path=path,
                response=data,
            )

        code = str(data.get("code", "0"))
        if code not in {"0", ""}:
            raise BingXApiError(
                data.get("msg") or data.get("message") or "BingX API request failed",
                code=data.get("code"),
                path=path,
                response=data,
            )

        if "data" in data and data["data"] is not None:
            return data["data"]
        return data


def normalize_contract_symbol(symbol: str) -> str:
    """Convert signal symbols like BTCUSDT to BingX contract symbols like BTC-USDT."""
    symbol = symbol.upper().strip().replace("_", "-")
    if "-" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}-USDT"
    return symbol


def compact_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {key: decimal_to_string(value) for key, value in values.items() if value is not None}


def canonical_query(params: dict[str, Any]) -> str:
    return "&".join(f"{key}={decimal_to_string(value)}" for key, value in sorted(params.items()))


def to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=decimal_to_string)


def decimal_to_string(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def decimal_to_json_number(value: Any) -> int | float | str:
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." not in text:
            return int(text)
        return float(text)
    return value
