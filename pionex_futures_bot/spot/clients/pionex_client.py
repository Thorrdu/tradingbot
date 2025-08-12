from __future__ import annotations

import hmac
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional
import logging
import os
import time
from collections import deque
import json

import requests


@dataclass
class ApiResponse:
    ok: bool
    data: Optional[Dict[str, Any]]
    error: Optional[str]


class _RateLimiter:
    """Simple sliding-window limiter for 10 req/sec per scope.

    Scopes:
    - 'ip': all endpoints share 10 rps
    - 'account': private endpoints share 10 rps
    """

    def __init__(self, max_per_sec: int = 10) -> None:
        self.max_per_sec = max_per_sec
        self.scope_to_events: Dict[str, deque[float]] = {
            "ip": deque(),
            "account": deque(),
        }

    def wait(self, scope: str, weight: int = 1) -> None:
        now = time.time()
        window_start = now - 1.0
        q = self.scope_to_events[scope]
        # Drop old events
        while q and q[0] < window_start:
            q.popleft()
        # If not enough capacity, sleep until capacity becomes available
        while len(q) + weight > self.max_per_sec:
            # Next capacity time is when the oldest event expires
            oldest = q[0]
            sleep_for = max(0.0, oldest + 1.01 - time.time())
            if sleep_for > 0:
                time.sleep(sleep_for)
            # Recompute window
            now = time.time()
            window_start = now - 1.0
            while q and q[0] < window_start:
                q.popleft()
        # Consume tokens
        for _ in range(weight):
            q.append(time.time())


class PionexClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str,
        dry_run: bool = False,
        timeout_sec: int = 10,
        api_key_header: str = "PIONEX-KEY",
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.dry_run = dry_run
        self.timeout_sec = timeout_sec
        self.session = requests.Session()
        self.api_key_header = api_key_header
        if self.api_key:
            self.session.headers.update({self.api_key_header: self.api_key})
        log_level_name = os.getenv("LOG_LEVEL", "INFO").upper() if "LOG_LEVEL" in os.environ else "INFO"
        self.log = logging.getLogger("pionex_client")
        self.log.setLevel(getattr(logging, log_level_name, logging.INFO))
        self.rate_limiter = _RateLimiter(max_per_sec=10)

    def _hmac_hex(self, payload: str) -> str:
        return hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _build_signature(
        self,
        *,
        method: str,
        path: str,
        query_params: Dict[str, str],
        body_str: str | None = None,
    ) -> str:
        # Build canonical query string in ASCII ascending order
        query_items = sorted(query_params.items(), key=lambda kv: kv[0])
        qs = "&".join(f"{k}={v}" for k, v in query_items)
        path_url = f"{path}?{qs}" if qs else path
        # Per Authentication spec: METHOD + PATH_URL (+ body for POST/DELETE)
        sign_payload = f"{method.upper()}{path_url}"
        if body_str:
            sign_payload = f"{sign_payload}{body_str}"
        return self._hmac_hex(sign_payload)

    def _signed_get(self, path: str, params: Dict[str, Any]) -> ApiResponse:
        """Private GET with timestamp and signature.
        Returns ApiResponse with JSON on success.
        """
        self.rate_limiter.wait("ip", weight=1)
        self.rate_limiter.wait("account", weight=1)
        url = f"{self.base_url}{path}"
        timestamp_ms = str(int(time.time() * 1000))
        qp: Dict[str, str] = {k: str(v) for k, v in params.items()}
        qp["timestamp"] = timestamp_ms
        signature = self._build_signature(method="GET", path=path, query_params=qp, body_str=None)
        headers = {
            self.api_key_header: self.api_key,
            "PIONEX-SIGNATURE": signature,
        }
        try:
            self.log.debug("GET %s params=%s", url, qp)
            r = self.session.get(url, params=qp, headers=headers, timeout=self.timeout_sec)
            if r.status_code == 429:
                return ApiResponse(ok=False, data=None, error="rate_limited")
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("result") is False:
                # Surface business error as not ok
                code = data.get("code")
                message = data.get("message")
                err = f"{code or ''} {message or ''}".strip()
                return ApiResponse(ok=False, data=data, error=err or "result_false")
            return ApiResponse(ok=True, data=data, error=None)
        except Exception as exc:  # noqa: BLE001
            return ApiResponse(ok=False, data=None, error=str(exc))

    def get_price(self, symbol: str) -> ApiResponse:
        """Fetch latest price using documented endpoints with fallbacks.
        References: Markets → Get 24hr Ticker, Get Book Ticker, Get Trades
        """
        # Prefer documented symbol format BTC_USDT, keep original as fallback
        normalized = self._normalize_symbol(symbol)
        candidate_symbols = [normalized]
        if normalized != symbol:
            candidate_symbols.append(symbol)

        endpoints = [
            {"path": "/api/v1/market/tickers", "kind": "tickers"},
            {"path": "/api/v1/market/bookTickers", "kind": "book"},
            {"path": "/api/v1/market/trades", "kind": "trades"},
        ]
        last_error: Optional[str] = None
        # Public endpoint: apply IP limiter only
        self.rate_limiter.wait("ip", weight=1)
        for ep in endpoints:
            for sym in candidate_symbols:
                try:
                    url = f"{self.base_url}{ep['path']}"
                    self.log.debug("GET %s symbol=%s", url, sym)
                    params: Dict[str, Any] = {"symbol": sym}
                    if ep["kind"] == "trades":
                        params["limit"] = 1
                    r = self.session.get(url, params=params, timeout=self.timeout_sec)
                    if r.status_code != 200:
                        last_error = f"HTTP {r.status_code} for {url}?symbol={sym} body={r.text[:200]}"
                        continue
                    data = r.json()
                    price: Optional[float] = None
                    kind = ep.get("kind")
                    # tickers → { data: { tickers: [ { close, ... } ] } }
                    if kind == "tickers" and isinstance(data, dict):
                        container = data.get("data") if isinstance(data.get("data"), dict) else data
                        arr = container.get("tickers") if isinstance(container, dict) else None
                        if isinstance(arr, list) and arr:
                            first = arr[0]
                            if isinstance(first, dict):
                                if "close" in first:
                                    price = float(first["close"])
                                elif "lastPrice" in first:
                                    price = float(first["lastPrice"])
                    # bookTickers → { data: { tickers: [ { bidPrice, askPrice } ] } }
                    if kind == "book" and price is None and isinstance(data, dict):
                        container = data.get("data") if isinstance(data.get("data"), dict) else data
                        arr = container.get("tickers") if isinstance(container, dict) else None
                        if isinstance(arr, list) and arr:
                            first = arr[0]
                            if isinstance(first, dict):
                                bid = first.get("bidPrice")
                                ask = first.get("askPrice")
                                if bid is not None and ask is not None:
                                    price = (float(bid) + float(ask)) / 2.0
                    # trades → { data: { trades: [ { price } ] } }
                    if kind == "trades" and price is None and isinstance(data, dict):
                        trades_container = data.get("data") if isinstance(data.get("data"), dict) else data
                        trades_list = trades_container.get("trades") if isinstance(trades_container, dict) else None
                        if isinstance(trades_list, list) and len(trades_list) > 0:
                            first = trades_list[0]
                            if isinstance(first, dict) and "price" in first:
                                price = float(first["price"])
                    if price is not None:
                        return ApiResponse(ok=True, data={"price": price}, error=None)
                    last_error = f"Unexpected ticker format for {url}?symbol={sym}: {data}"
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
        self.log.error("get_price failed for %s: %s", symbol, last_error)
        return ApiResponse(ok=False, data=None, error=last_error or "unknown_error")

    def get_book_ticker(self, symbol: str) -> ApiResponse:
        """Return best bid/ask using bookTickers endpoint when possible.
        Success payload: { "bid": float, "ask": float }
        """
        try:
            self.rate_limiter.wait("ip", weight=1)
            sym = self._normalize_symbol(symbol)
            url = f"{self.base_url}/api/v1/market/bookTickers"
            r = self.session.get(url, params={"symbol": sym}, timeout=self.timeout_sec)
            if r.status_code != 200:
                return ApiResponse(ok=False, data=None, error=f"HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            container = data.get("data") if isinstance(data, dict) else data
            arr = container.get("tickers") if isinstance(container, dict) else None
            if isinstance(arr, list) and arr:
                first = arr[0]
                bid = float(first.get("bidPrice")) if first.get("bidPrice") is not None else None
                ask = float(first.get("askPrice")) if first.get("askPrice") is not None else None
                if bid is not None and ask is not None:
                    return ApiResponse(ok=True, data={"bid": bid, "ask": ask}, error=None)
            return ApiResponse(ok=False, data=None, error="unexpected_response")
        except Exception as exc:  # noqa: BLE001
            return ApiResponse(ok=False, data=None, error=str(exc))

    def get_market_symbols(self, market_type: str | None = None, symbols: list[str] | None = None) -> ApiResponse:
        """Fetch market symbols from Common → Market Data.

        Docs: GET /api/v1/common/symbols
        - market_type: "SPOT" or "PERP" (optional)
        - symbols: list of specific symbols to query (optional)
        Returns ApiResponse with { data: { symbols: [...] } } or a simplified list under data["symbols"] on success.
        """
        try:
            self.rate_limiter.wait("ip", weight=5)
            url = f"{self.base_url}/api/v1/common/symbols"
            params: Dict[str, Any] = {}
            if market_type:
                params["type"] = market_type.upper()
            if symbols:
                params["symbols"] = ",".join(symbols)
            r = self.session.get(url, params=params, timeout=self.timeout_sec)
            if r.status_code != 200:
                return ApiResponse(ok=False, data=None, error=f"HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            # Normalize payload to a list of dicts with a 'symbol' key
            arr = None
            if isinstance(data, dict):
                inner = data.get("data") if isinstance(data.get("data"), dict) else data
                if isinstance(inner, dict) and isinstance(inner.get("symbols"), list):
                    arr = inner.get("symbols")
            if not isinstance(arr, list):
                return ApiResponse(ok=False, data=None, error="unexpected_response")
            return ApiResponse(ok=True, data={"symbols": arr}, error=None)
        except Exception as exc:  # noqa: BLE001
            return ApiResponse(ok=False, data=None, error=str(exc))

    def _normalize_symbol(self, symbol: str) -> str:
        if "_" in symbol:
            return symbol
        if symbol.endswith("USDT"):
            return f"{symbol[:-4]}_USDT"
        return symbol

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Optional[float] = None,
        amount: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> ApiResponse:
        if self.dry_run:
            return ApiResponse(
                ok=True,
                data={
                    "dry_run": True,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "amount": amount,
                    "orderId": str(int(time.time() * 1000)),
                    "price": None,
                },
                error=None,
            )
        # Private endpoint: apply both IP and ACCOUNT limiters
        self.rate_limiter.wait("ip", weight=1)
        self.rate_limiter.wait("account", weight=1)
        # Build request for documented endpoint
        payload: Dict[str, Any] = {
            "symbol": self._normalize_symbol(symbol),
            "side": side.upper(),
            "type": "MARKET",
        }
        if client_order_id:
            payload["clientOrderId"] = str(client_order_id)
        if side.upper() == "BUY":
            if amount is None and quantity is not None:
                # Fallback: treat quantity as amount if not provided
                amount = quantity
            if amount is None:
                return ApiResponse(ok=False, data=None, error="amount required for MARKET BUY")
            payload["amount"] = str(amount)
        else:  # SELL
            if quantity is None:
                return ApiResponse(ok=False, data=None, error="quantity (size) required for MARKET SELL")
            payload["size"] = str(quantity)

        path = "/api/v1/trade/order"
        url = f"{self.base_url}{path}"
        # Authentication: add timestamp in query and sign
        timestamp_ms = str(int(time.time() * 1000))
        query_params: Dict[str, str] = {"timestamp": timestamp_ms}
        body_str = json.dumps(payload, separators=(",", ":"))
        signature = self._build_signature(method="POST", path=path, query_params=query_params, body_str=body_str)
        headers = {
            self.api_key_header: self.api_key,
            "PIONEX-SIGNATURE": signature,
            "Content-Type": "application/json",
        }
        attempt = 0
        while True:
            try:
                self.log.debug("POST %s?timestamp=%s json=%s", url, timestamp_ms, payload)
                r = self.session.post(url, params=query_params, data=body_str, headers=headers, timeout=self.timeout_sec)
                self.log.debug("RESP %s %s", r.status_code, (r.text or '')[:500])
                if r.status_code == 429:
                    # Backoff on rate limit
                    attempt += 1
                    sleep_s = min(60, 2 ** attempt)
                    self.log.warning("429 received, backing off %ss (attempt=%s)", sleep_s, attempt)
                    time.sleep(sleep_s)
                    continue
                if r.status_code >= 500:
                    attempt += 1
                    sleep_s = min(10, 2 ** attempt)
                    self.log.warning("Server error %s, retrying in %ss", r.status_code, sleep_s)
                    time.sleep(sleep_s)
                    continue
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and data.get("result") is False:
                    code = data.get("code")
                    message = data.get("message")
                    err = f"{code or ''} {message or ''}".strip()
                    self.log.error("order_rejected code=%s message=%s", code, message)
                    return ApiResponse(ok=False, data=data, error=err or "result_false")
                # Extract the essential identifiers for callers
                if isinstance(data, dict):
                    inner = data.get("data") if isinstance(data.get("data"), dict) else None
                    if isinstance(inner, dict):
                        slim = {
                            "orderId": inner.get("orderId"),
                            "clientOrderId": inner.get("clientOrderId"),
                        }
                        if not slim.get("orderId"):
                            self.log.warning("order_created_without_id payload=%s", inner)
                        return ApiResponse(ok=True, data=slim, error=None)
                return ApiResponse(ok=True, data=data, error=None)
            except Exception as exc:  # noqa: BLE001
                return ApiResponse(ok=False, data=None, error=str(exc))

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        size: float,
        price: float,
        client_order_id: Optional[str] = None,
        ioc: bool = False,
    ) -> ApiResponse:
        """Place a LIMIT order. Size is required for both BUY and SELL.
        Docs: POST /api/v1/trade/order with type=LIMIT, size, price, IOC optional.
        """
        if self.dry_run:
            return ApiResponse(
                ok=True,
                data={
                    "dry_run": True,
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "price": price,
                    "orderId": str(int(time.time() * 1000)),
                    "IOC": bool(ioc),
                },
                error=None,
            )
        self.rate_limiter.wait("ip", weight=1)
        self.rate_limiter.wait("account", weight=1)
        path = "/api/v1/trade/order"
        url = f"{self.base_url}{path}"
        timestamp_ms = str(int(time.time() * 1000))
        payload: Dict[str, Any] = {
            "symbol": self._normalize_symbol(symbol),
            "side": side.upper(),
            "type": "LIMIT",
            "size": str(size),
            "price": str(price),
            "IOC": bool(ioc),
        }
        if client_order_id:
            payload["clientOrderId"] = str(client_order_id)
        query_params = {"timestamp": timestamp_ms}
        signature = self._build_signature(method="POST", path=path, query_params=query_params, body_str=json.dumps(payload, separators=(",", ":")))
        headers = {
            self.api_key_header: self.api_key,
            "PIONEX-SIGNATURE": signature,
            "Content-Type": "application/json",
        }
        try:
            self.log.debug("POST %s payload=%s", url, payload)
            r = self.session.post(url, params=query_params, data=json.dumps(payload), headers=headers, timeout=self.timeout_sec)
            if r.status_code == 429:
                return ApiResponse(ok=False, data=None, error="rate_limited")
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("result") is False:
                code = data.get("code")
                message = data.get("message")
                err = f"{code or ''} {message or ''}".strip()
                return ApiResponse(ok=False, data=data, error=err or "result_false")
            return ApiResponse(ok=True, data=data.get("data") if isinstance(data, dict) else data, error=None)
        except Exception as exc:  # noqa: BLE001
            return ApiResponse(ok=False, data=None, error=str(exc))

    def get_order(self, *, symbol: str, order_id: str) -> ApiResponse:
        try:
            self.rate_limiter.wait("ip", weight=1)
            self.rate_limiter.wait("account", weight=1)
            url = f"{self.base_url}/api/v1/trade/order"
            params = {"symbol": self._normalize_symbol(symbol), "orderId": order_id, "timestamp": str(int(time.time() * 1000))}
            signature = self._build_signature(method="GET", path="/api/v1/trade/order", query_params=params, body_str=None)
            headers = {self.api_key_header: self.api_key, "PIONEX-SIGNATURE": signature}
            r = self.session.get(url, params=params, headers=headers, timeout=self.timeout_sec)
            self.log.debug("GET %s params=%s -> %s %s", url, params, r.status_code, (r.text or '')[:500])
            if r.status_code != 200:
                return ApiResponse(ok=False, data=None, error=f"HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            if isinstance(data, dict) and data.get("result") is False:
                code = data.get("code")
                message = data.get("message")
                err = f"{code or ''} {message or ''}".strip()
                return ApiResponse(ok=False, data=data, error=err or "result_false")
            return ApiResponse(ok=True, data=data.get("data") if isinstance(data, dict) else data, error=None)
        except Exception as exc:  # noqa: BLE001
            return ApiResponse(ok=False, data=None, error=str(exc))

    def cancel_order(self, *, symbol: str, order_id: str) -> ApiResponse:
        try:
            self.rate_limiter.wait("ip", weight=1)
            self.rate_limiter.wait("account", weight=1)
            url = f"{self.base_url}/api/v1/trade/order"
            payload = {"symbol": self._normalize_symbol(symbol), "orderId": order_id}
            params = {"timestamp": str(int(time.time() * 1000))}
            signature = self._build_signature(method="DELETE", path="/api/v1/trade/order", query_params=params, body_str=json.dumps(payload))
            headers = {self.api_key_header: self.api_key, "PIONEX-SIGNATURE": signature, "Content-Type": "application/json"}
            r = self.session.delete(url, params=params, data=json.dumps(payload), headers=headers, timeout=self.timeout_sec)
            if r.status_code != 200:
                return ApiResponse(ok=False, data=None, error=f"HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            ok = bool(data.get("result")) if isinstance(data, dict) else True
            return ApiResponse(ok=ok, data=data, error=None if ok else "cancel_failed")
        except Exception as exc:  # noqa: BLE001
            return ApiResponse(ok=False, data=None, error=str(exc))

    # ---- Private data helpers -------------------------------------------------

    def get_open_orders(self, symbol: str) -> ApiResponse:
        path = "/api/v1/trade/openOrders"
        params: Dict[str, Any] = {"symbol": self._normalize_symbol(symbol)}
        return self._signed_get(path, params)

    def get_fills(
        self,
        symbol: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
    ) -> ApiResponse:
        """Get fills for a symbol.

        Compliant with docs: GET /api/v1/trade/fills accepts symbol (required),
        and optional startTime/endTime in milliseconds. No 'limit' parameter.
        """
        path = "/api/v1/trade/fills"
        params: Dict[str, Any] = {"symbol": self._normalize_symbol(symbol)}
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        return self._signed_get(path, params)

    def get_fills_by_order_id(self, symbol: str, order_id: str) -> ApiResponse:
        """Get fills for a specific order id.

        Docs: GET /api/v1/trade/fillsByOrderId (parameters: symbol, orderId)
        Returns ApiResponse with { data: { fills: [...] } } on success.
        """
        path = "/api/v1/trade/fillsByOrderId"
        params: Dict[str, Any] = {
            "symbol": self._normalize_symbol(symbol),
            "orderId": order_id,
        }
        return self._signed_get(path, params)

    def get_balances(self) -> ApiResponse:
        """Fetch account balances (trading account).

        Docs: GET /api/v1/account/balances (Permission: Read)
        Returns ApiResponse with { data: { balances: [ { coin, free, frozen } ] } }
        """
        path = "/api/v1/account/balances"
        params: Dict[str, Any] = {}
        return self._signed_get(path, params)

    def infer_position_from_fills(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        """Heuristic: compute net size from recent fills to estimate open position.

        Returns dict with keys: in_position, side, quantity, entry_price.
        """
        out = {"in_position": False, "side": None, "quantity": 0.0, "entry_price": 0.0}
        try:
            # The REST API does not support 'limit' for fills; we can bound by time if desired.
            # For now, request latest fills without time filters and process client-side.
            fills_resp = self.get_fills(symbol)
            if not fills_resp.ok or not fills_resp.data:
                return out
            data = fills_resp.data.get("data") if isinstance(fills_resp.data, dict) else None
            fills = data.get("fills") if isinstance(data, dict) else None
            if not isinstance(fills, list):
                return out
            # If a limit was provided by caller, trim locally to the most recent N fills
            if isinstance(limit, int) and limit > 0 and len(fills) > limit:
                fills = fills[:limit]
            net_qty = 0.0
            last_price = 0.0
            for f in fills:
                if not isinstance(f, dict):
                    continue
                side = f.get("side")
                size = f.get("size")
                price = f.get("price")
                try:
                    qty = float(size) if size is not None else 0.0
                    px = float(price) if price is not None else 0.0
                except Exception:
                    continue
                if side == "BUY":
                    net_qty += qty
                    last_price = px
                elif side == "SELL":
                    net_qty -= qty
                    last_price = px
            if abs(net_qty) > 0.0:
                out["in_position"] = True
                out["side"] = "BUY" if net_qty > 0 else "SELL"
                out["quantity"] = abs(net_qty)
                out["entry_price"] = last_price
            return out
        except Exception:
            return out

    def close_position(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
    ) -> ApiResponse:
        # For simplicity, closing is placing the opposite side MARKET order (size only)
        opposite_side = "SELL" if side.upper() == "BUY" else "BUY"
        return self.place_market_order(symbol=symbol, side=opposite_side, quantity=quantity)


if __name__ == "__main__":
    # Minimal CLI de test pour vérifier la récupération de prix et la signature (dry-run pour les ordres)
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        load_dotenv = None  # type: ignore

    if load_dotenv:
        load_dotenv()

    base_url = os.getenv("PIONEX_BASE_URL", "https://api.pionex.com")
    api_key = os.getenv("API_KEY", "")
    api_secret = os.getenv("API_SECRET", "")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    client = PionexClient(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        dry_run=True,
    )

    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        r = client.get_price(sym)
        if r.ok:
            print(f"price[{sym}] = {r.data['price']}")
        else:
            print(f"price[{sym}] ERROR: {r.error}")

    # Exemple d'ordre dry-run (ne touche pas l'API)
    order = client.place_market_order(symbol="BTCUSDT", side="BUY", amount=10)
    print("dry_run_order:", order.ok, order.data or order.error)