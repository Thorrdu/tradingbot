from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from pionex_client import PionexClient, ApiResponse


class PerpClient(PionexClient):
    """Thin wrapper over PionexClient for Perpetual Futures symbols.

    Differences vs spot client:
    - Normalizes symbols to the PERP format, e.g. BTCUSDT → BTC_USDT_PERP
    - Uses `size` for MARKET BUY and SELL (Perp contracts) instead of `amount` for BUY
    - Keeps the same signing and base paths; trading endpoint remains `/api/v1/trade/order`
    """

    def _normalize_symbol(self, symbol: str) -> str:  # type: ignore[override]
        s = symbol.strip().upper()
        # UI route format like "SOL.PERP_USDT" → API expects "SOL_USDT_PERP"
        if ".PERP_USDT" in s:
            base = s.split(".")[0]
            return f"{base}_USDT_PERP"
        # Remove dashes and dots defensively
        s = s.replace("-", "").replace(".", "")
        # Already normalized
        if s.endswith("_USDT_PERP"):
            return s
        # SPOT-like no-underscore: BTCUSDT → BTC_USDT_PERP
        if s.endswith("USDT") and "_" not in s:
            base = s[:-4]
            return f"{base}_USDT_PERP"
        # Underscored spot form: BTC_USDT → BTC_USDT_PERP
        if s.endswith("_USDT") and not s.endswith("_USDT_PERP"):
            return f"{s}_PERP"
        return s

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Optional[float] = None,
        amount: Optional[float] = None,
    ) -> ApiResponse:  # type: ignore[override]
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

        self.rate_limiter.wait("ip", weight=1)
        self.rate_limiter.wait("account", weight=1)

        payload: Dict[str, Any] = {
            "symbol": self._normalize_symbol(symbol),
            "side": side.upper(),
            "type": "MARKET",
        }

        # For PERP, use `size` for both BUY and SELL
        if quantity is None:
            return ApiResponse(ok=False, data=None, error="quantity (size) required for PERP MARKET order")
        payload["size"] = str(quantity)

        path = "/api/v1/trade/order"
        url = f"{self.base_url}{path}"
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
                if r.status_code == 429:
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
                    return ApiResponse(ok=False, data=data, error=err or "result_false")
                if isinstance(data, dict):
                    inner = data.get("data") if isinstance(data.get("data"), dict) else None
                    if isinstance(inner, dict):
                        slim = {
                            "orderId": inner.get("orderId"),
                            "clientOrderId": inner.get("clientOrderId"),
                        }
                        return ApiResponse(ok=True, data=slim, error=None)
                return ApiResponse(ok=True, data=data, error=None)
            except Exception as exc:  # noqa: BLE001
                return ApiResponse(ok=False, data=None, error=str(exc))


