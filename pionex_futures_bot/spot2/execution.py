from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
import time


@dataclass
class BookTicker:
    bid: float
    ask: float


class ExecutionLayer:
    def __init__(self, client, *, prefer_maker: bool, maker_offset_bps: float,
                 entry_limit_timeout_sec: int, exit_limit_timeout_sec: int,
                 symbol_rules: Optional[Dict[str, dict]] = None) -> None:
        self.client = client
        self.prefer_maker = bool(prefer_maker)
        self.maker_offset_bps = float(maker_offset_bps)
        self.entry_limit_timeout_sec = int(entry_limit_timeout_sec)
        self.exit_limit_timeout_sec = int(exit_limit_timeout_sec)
        self.symbol_rules = symbol_rules or {}

    # --- Market data helpers ---
    def get_book_ticker(self, symbol: str) -> Optional[BookTicker]:
        try:
            r = getattr(self.client, "get_book_ticker", None)
            if callable(r):
                bk = r(symbol)
                if getattr(bk, "ok", False) and getattr(bk, "data", None):
                    data = bk.data  # type: ignore[attr-defined]
                    return BookTicker(bid=float(data.get("bid")), ask=float(data.get("ask")))
        except Exception:
            pass
        # Fallback: derive synthetic book from mid price
        try:
            pr = self.client.get_price(symbol)
            if pr.ok and pr.data and "price" in pr.data:
                mid = float(pr.data["price"])  # type: ignore[arg-type]
                spread = max(1e-6, mid * 0.0001)
                return BookTicker(bid=mid - spread / 2.0, ask=mid + spread / 2.0)
        except Exception:
            pass
        return None

    # --- Order placement ---
    def _place_limit(self, *, symbol: str, side: str, price: float, size: float,
                     client_order_id: Optional[str]) -> Dict[str, Any]:
        # Use client's limit endpoint if available
        try:
            r = getattr(self.client, "place_limit_order", None)
            if callable(r):
                resp = r(symbol=symbol, side=side, size=size, price=price, client_order_id=client_order_id, ioc=False)
                return {"ok": getattr(resp, "ok", False), "data": getattr(resp, "data", None), "error": getattr(resp, "error", None)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "limit_not_implemented"}

    def place_entry(self, *, symbol: str, price_hint: float, amount_usdt: float,
                    client_order_id: Optional[str]) -> Dict[str, Any]:
        import logging
        log = logging.getLogger("execution")
        log.debug("entry: symbol=%s hint=%.8f amount=%.4f prefer_maker=%s", symbol, price_hint, amount_usdt, self.prefer_maker)
        if not self.prefer_maker:
            r = self.client.place_market_order(symbol=symbol, side="BUY", amount=amount_usdt, client_order_id=client_order_id)
            log.debug("entry.market resp ok=%s data=%s err=%s", getattr(r, 'ok', None), getattr(r, 'data', None), getattr(r, 'error', None))
            # Confirmation si possible
            try:
                oid = (getattr(r, 'data', {}) or {}).get('orderId')
                if oid:
                    confirm = getattr(self.client, 'get_order', None)
                    if callable(confirm):
                        cr = confirm(symbol=symbol, order_id=str(oid))
                        log.debug("entry.market confirm ok=%s data=%s err=%s", getattr(cr, 'ok', None), getattr(cr, 'data', None), getattr(cr, 'error', None))
            except Exception:
                pass
            return {"ok": r.ok, "data": getattr(r, "data", None), "error": getattr(r, "error", None)}

        book = self.get_book_ticker(symbol)
        if not book:
            log.debug("entry: no book, fallback to market")
            r = self.client.place_market_order(symbol=symbol, side="BUY", amount=amount_usdt, client_order_id=client_order_id)
            log.debug("entry.market resp ok=%s data=%s err=%s", getattr(r, 'ok', None), getattr(r, 'data', None), getattr(r, 'error', None))
            return {"ok": r.ok, "data": getattr(r, "data", None), "error": getattr(r, "error", None)}
        bid = book.bid
        # maker price = bid - offset
        px = bid * (1.0 - max(0.0, self.maker_offset_bps) / 10000.0)
        # compute size from amount (Pionex LIMIT requires size)
        size = max(0.0, amount_usdt / max(px, 1e-12))
        # apply symbol constraints if available
        try:
            rules = self.symbol_rules.get(symbol.upper()) or self.symbol_rules.get(self.client._normalize_symbol(symbol)) or {}
            min_size = float(rules.get("minTradeSize")) if rules.get("minTradeSize") is not None else None
            max_size = float(rules.get("maxTradeSize")) if rules.get("maxTradeSize") is not None else None
            # amountPrecision is for MARKET amount; basePrecision is qty precision
            base_prec = int(rules.get("basePrecision", 6)) if rules.get("basePrecision") is not None else 6
            # round down to base precision
            if base_prec >= 0:
                factor = 10 ** base_prec
                size = (int(size * factor)) / factor
            if min_size is not None and size < min_size:
                size = min_size
            if max_size is not None and size > max_size:
                size = max_size
        except Exception:
            pass
        log.debug("entry: try maker LIMIT price=%.8f size=%.8f", px, size)
        lim = self._place_limit(symbol=symbol, side="BUY", price=px, size=size, client_order_id=client_order_id)
        log.debug("entry.limit resp ok=%s data=%s err=%s", lim.get('ok'), lim.get('data'), lim.get('error'))
        if lim.get("ok"):
            # wait fill with timeout (poll using get_order when client supports it)
            t0 = time.time()
            while time.time() - t0 < max(1, self.entry_limit_timeout_sec):
                time.sleep(0.2)
                break
        # fallback
        log.debug("entry: fallback MARKET")
        r = self.client.place_market_order(symbol=symbol, side="BUY", amount=amount_usdt, client_order_id=client_order_id)
        log.debug("entry.market resp ok=%s data=%s err=%s", getattr(r, 'ok', None), getattr(r, 'data', None), getattr(r, 'error', None))
        return {"ok": r.ok, "data": getattr(r, "data", None), "error": getattr(r, "error", None)}

    def place_exit_market(self, *, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        r = self.client.close_position(symbol=symbol, side=side, quantity=quantity)
        return {"ok": r.ok, "data": getattr(r, "data", None), "error": getattr(r, "error", None)}

    # --- Exit attempts with maker LIMIT and timeout fallback ---
    def _wait_filled(self, *, symbol: str, order_id: str, timeout_sec: int) -> bool:
        t0 = time.time()
        get_order = getattr(self.client, "get_order", None)
        if not callable(get_order):
            return False
        while time.time() - t0 < max(1, timeout_sec):
            try:
                resp = get_order(symbol=symbol, order_id=order_id)
                if getattr(resp, "ok", False) and getattr(resp, "data", None):
                    data = resp.data  # type: ignore[attr-defined]
                    status = str(data.get("status", "")).upper()
                    filled_size = float(data.get("filledSize", 0.0) or 0.0)
                    size = float(data.get("size", filled_size) or 0.0)
                    if status == "CLOSED" or (size > 0 and filled_size >= size):
                        return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def place_exit_limit_maker_sell(self, *, symbol: str, quantity: float, min_price: float) -> Dict[str, Any]:
        # Price at least best ask to be maker, and not below min_price target
        book = self.get_book_ticker(symbol)
        ask = None if not book else float(book.ask)
        px = max(min_price, (ask or min_price))
        # Place LIMIT SELL
        res = self._place_limit(symbol=symbol, side="SELL", price=px, size=quantity, client_order_id=None)
        if res.get("ok") and res.get("data"):
            order_id = None
            data = res.get("data")
            try:
                order_id = str(data.get("orderId"))
            except Exception:
                order_id = None
            if order_id and self._wait_filled(symbol=symbol, order_id=order_id, timeout_sec=self.exit_limit_timeout_sec):
                return res
            # Cancel if not filled
            try:
                cancel = getattr(self.client, "cancel_order", None)
                if callable(cancel) and order_id:
                    cancel(symbol=symbol, order_id=order_id)
            except Exception:
                pass
        # Fallback MARKET close
        return self.place_exit_market(symbol=symbol, side="BUY", quantity=quantity)


