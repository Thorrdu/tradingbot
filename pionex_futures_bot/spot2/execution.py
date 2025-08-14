from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
import time
import json


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

        # Pending maker orders store (JSON) for monitoring UI
        from pathlib import Path as _P
        # Anchor to this module directory to avoid cwd-dependent paths
        base_dir = _P(__file__).resolve().parent
        self._pending_path = base_dir / "logs" / "pending_orders.json"
        try:
            self._pending_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Internal cache for symbol rules fetched from API
        self._rules_cache: Dict[str, dict] = {}

    # ---- Rules resolution ----------------------------------------------------
    def _resolve_rules(self, symbol: str) -> dict:
        sym_u = symbol.upper()
        sym_n = self.client._normalize_symbol(symbol)
        # Start from provided rules
        base = dict(self.symbol_rules.get(sym_u) or self.symbol_rules.get(sym_n) or {})
        # If critical fields missing, try fetch from API once
        needed = {"basePrecision", "quotePrecision", "minTradeSize", "minAmount", "minTradeAmount", "minNotional"}
        if not (needed & set(base.keys())):
            if sym_n in self._rules_cache:
                base.update(self._rules_cache[sym_n])
            else:
                try:
                    fn = getattr(self.client, "get_market_symbols", None)
                    if callable(fn):
                        resp = fn(market_type="SPOT", symbols=[sym_n])
                        if getattr(resp, "ok", False) and isinstance(getattr(resp, "data", None), dict):
                            arr = resp.data.get("symbols")  # type: ignore[attr-defined]
                            if isinstance(arr, list) and arr:
                                row = arr[0]
                                parsed = {}
                                for k in [
                                    "basePrecision", "quotePrecision", "minTradeSize", "maxTradeSize",
                                    "minAmount", "minTradeAmount", "minNotional", "tickSize",
                                ]:
                                    if k in row:
                                        parsed[k] = row[k]
                                self._rules_cache[sym_n] = parsed
                                base.update(parsed)
                except Exception:
                    pass
        return base

    # ---- Pending orders helpers --------------------------------------------
    def _load_pending(self) -> dict:
        try:
            if self._pending_path.exists():
                return json.loads(self._pending_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {}

    def _save_pending(self, data: dict) -> None:
        try:
            self._pending_path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        except Exception:
            pass

    def _add_pending(self, *, order_id: str, symbol: str, side: str, kind: str, price: float, size: float, timeout_sec: int) -> None:
        try:
            now = time.time()
            data = self._load_pending()
            data[str(order_id)] = {
                "symbol": symbol,
                "side": side,
                "kind": kind,  # entry|exit
                "price": float(price),
                "size": float(size),
                "placed_at": now,
                "timeout_sec": int(timeout_sec),
            }
            self._save_pending(data)
        except Exception:
            pass

    def _remove_pending(self, order_id: str) -> None:
        try:
            data = self._load_pending()
            if str(order_id) in data:
                del data[str(order_id)]
                self._save_pending(data)
        except Exception:
            pass

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
                return {"ok": getattr(resp, "ok", False), "data": getattr(resp, "data", None), "error": getattr(resp, "error", None), "_sent": {"symbol": symbol, "side": side, "type": "LIMIT", "size": size, "price": price, "clientOrderId": client_order_id}}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "_sent": {"symbol": symbol, "side": side, "type": "LIMIT", "size": size, "price": price, "clientOrderId": client_order_id}}
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
        # apply symbol constraints if available (precision, min/max)
        try:
            rules = self.symbol_rules.get(symbol.upper()) or self.symbol_rules.get(self.client._normalize_symbol(symbol)) or {}
            min_size = float(rules.get("minTradeSize")) if rules.get("minTradeSize") is not None else None
            max_size = float(rules.get("maxTradeSize")) if rules.get("maxTradeSize") is not None else None
            # amountPrecision is for MARKET amount; basePrecision is qty precision
            base_prec = int(rules.get("basePrecision", 6)) if rules.get("basePrecision") is not None else 6
            quote_prec = int(rules.get("quotePrecision", 2)) if rules.get("quotePrecision") is not None else 2
            # round price to quote precision (tick size)
            if quote_prec >= 0:
                px = float(f"{px:.{quote_prec}f}")
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
        if lim.get("ok") and lim.get("data"):
            # Track pending and wait fill with timeout
            order_id = None
            try:
                order_id = str(lim["data"].get("orderId"))
            except Exception:
                order_id = None
            if order_id:
                self._add_pending(order_id=order_id, symbol=symbol, side="BUY", kind="entry", price=px, size=size, timeout_sec=self.entry_limit_timeout_sec)
                if self._wait_filled(symbol=symbol, order_id=order_id, timeout_sec=self.entry_limit_timeout_sec):
                    self._remove_pending(order_id)
                    return lim
                # Not filled within timeout: try to cancel and confirm status to avoid double fills
                try:
                    cancel = getattr(self.client, "cancel_order", None)
                    if callable(cancel):
                        cancel(symbol=symbol, order_id=order_id)
                except Exception:
                    pass
                # Post-cancel confirmation window: poll for a short period to ensure not filled
                try:
                    get_order = getattr(self.client, "get_order", None)
                    if callable(get_order):
                        t_confirm = time.time() + 3.0
                        while time.time() < t_confirm:
                            time.sleep(0.2)
                            orr = get_order(symbol=symbol, order_id=order_id)
                            if getattr(orr, "ok", False) and getattr(orr, "data", None):
                                data = orr.data  # type: ignore[attr-defined]
                                status = str(data.get("status", "")).upper()
                                filled = float(data.get("filledSize", 0.0) or 0.0)
                                need = float(data.get("size", size) or size)
                                if status == "CLOSED" or (need > 0 and filled >= need):
                                    self._remove_pending(order_id)
                                    return lim
                                if status == "CANCELED":
                                    break
                except Exception:
                    pass
                self._remove_pending(order_id)
        # fallback MARKET
        log.debug("entry: fallback MARKET")
        # Ensure amount respects minAmount when available
        try:
            rules = self.symbol_rules.get(symbol.upper()) or self.symbol_rules.get(self.client._normalize_symbol(symbol)) or {}
            min_amount = float(rules.get("minAmount")) if rules.get("minAmount") is not None else None
            if min_amount is not None and amount_usdt < min_amount:
                amount_usdt = min_amount
        except Exception:
            pass
        r = self.client.place_market_order(symbol=symbol, side="BUY", amount=amount_usdt, client_order_id=client_order_id)
        log.debug("entry.market resp ok=%s data=%s err=%s", getattr(r, 'ok', None), getattr(r, 'data', None), getattr(r, 'error', None))
        return {"ok": r.ok, "data": getattr(r, "data", None), "error": getattr(r, "error", None)}

    def place_exit_market(self, *, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        # Clamp size by dump rules if available
        import logging
        log = logging.getLogger("execution")
        try:
            rules = self._resolve_rules(symbol)
            # Base precision and minimum trade size enforcement
            base_prec = int(rules.get("basePrecision", 6)) if rules.get("basePrecision") is not None else 6
            if base_prec >= 0:
                factor = 10 ** base_prec
                quantity = (int(quantity * factor)) / factor
            min_size = float(rules.get("minTradeSize")) if rules.get("minTradeSize") is not None else None
            if min_size is not None and quantity < min_size:
                log.error("exit.market size too small: symbol=%s qty=%.8f < minTradeSize=%.8f", symbol, quantity, float(min_size))
                return {"ok": False, "error": "size_too_small", "data": None}
            # Optional dumping limits if provided by rules
            min_dump = float(rules.get("minTradeDumping")) if rules.get("minTradeDumping") is not None else None
            max_dump = float(rules.get("maxTradeDumping")) if rules.get("maxTradeDumping") is not None else None
            if min_dump is not None and quantity < min_dump:
                quantity = min_dump
            if max_dump is not None and quantity > max_dump:
                quantity = max_dump
        except Exception:
            pass
        log.info("exit.market: symbol=%s side=%s qty=%.8f", symbol, side, quantity)
        r = self.client.close_position(symbol=symbol, side=side, quantity=quantity)
        log.debug("exit.market resp ok=%s data=%s err=%s", getattr(r, 'ok', None), getattr(r, 'data', None), getattr(r, 'error', None))
        return {"ok": r.ok, "data": getattr(r, "data", None), "error": getattr(r, "error", None), "_sent": {"symbol": symbol, "side": side, "type": "MARKET", "size": quantity}}

    # --- Exit attempts with maker LIMIT and timeout fallback ---
    def _wait_filled(self, *, symbol: str, order_id: str, timeout_sec: int) -> bool:
        import logging
        log = logging.getLogger("execution")
        t0 = time.time()
        get_order = getattr(self.client, "get_order", None)
        if not callable(get_order):
            return False
        last_log = 0.0
        while time.time() - t0 < max(1, timeout_sec):
            try:
                resp = get_order(symbol=symbol, order_id=order_id)
                if getattr(resp, "ok", False) and getattr(resp, "data", None):
                    data = resp.data  # type: ignore[attr-defined]
                    status = str(data.get("status", "")).upper()
                    filled_size = float(data.get("filledSize", 0.0) or 0.0)
                    size = float(data.get("size", filled_size) or 0.0)
                    now = time.time()
                    # Log au plus une fois par seconde pour suivi
                    if now - last_log >= 1.0:
                        last_log = now
                        log.debug(
                            "exit.limit poll: symbol=%s oid=%s status=%s filled=%.8f/%.8f",
                            symbol,
                            order_id,
                            status,
                            filled_size,
                            size,
                        )
                    if status == "CLOSED" or (size > 0 and filled_size >= size):
                        log.info("exit.limit filled: symbol=%s oid=%s", symbol, order_id)
                        return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def place_exit_limit_maker_sell(self, *, symbol: str, quantity: float, min_price: float) -> Dict[str, Any]:
        import logging
        log = logging.getLogger("execution")
        # Price at least best ask to be maker, and not below min_price target
        book = self.get_book_ticker(symbol)
        ask = None if not book else float(book.ask)
        px = max(min_price, (ask or min_price))
        # Round price/size per rules and enforce min notional and min size
        try:
            rules = self._resolve_rules(symbol)
            quote_prec = int(rules.get("quotePrecision", 6)) if rules.get("quotePrecision") is not None else 6
            base_prec = int(rules.get("basePrecision", 6)) if rules.get("basePrecision") is not None else 6
            min_size = float(rules.get("minTradeSize")) if rules.get("minTradeSize") is not None else None
            # Normalize possible min notional keys from API
            min_amount = None
            for key in ("minAmount", "minTradeAmount", "minNotional"):
                if rules.get(key) is not None:
                    try:
                        min_amount = float(rules.get(key))
                        break
                    except Exception:
                        pass
            if quote_prec >= 0:
                px = float(f"{px:.{quote_prec}f}")
            if base_prec >= 0:
                factor = 10 ** base_prec
                quantity = (int(quantity * factor)) / factor
            # Enforce step by minTradeSize: floor to nearest multiple
            if min_size is not None and min_size > 0:
                try:
                    import math as _m
                    mult = _m.floor(quantity / float(min_size))
                    quantity = max(0.0, mult * float(min_size))
                    if base_prec >= 0:
                        factor = 10 ** base_prec
                        quantity = (int(quantity * factor)) / factor
                except Exception:
                    pass
            # Check constraints; fallback to MARKET if constraints cannot be met
            # Use a conservative reference price (min(limit_px, bid)) for notional validation
            ref_bid = None
            try:
                bk = self.get_book_ticker(symbol)
                ref_bid = None if not bk else float(bk.bid)
            except Exception:
                ref_bid = None
            price_ref = min(px, ref_bid) if (ref_bid is not None) else px
            if (min_size is not None and quantity < min_size) or (min_amount is not None and (price_ref * quantity) < min_amount):
                log.info("exit.limit maker -> fallback: constraint not met (qty=%.8f min_size=%s notional=%.8f min_notional=%s)", quantity, str(min_size), px*quantity, str(min_amount))
                # If even MARKET would fail (ref using bid), surface error
                if (min_size is not None and quantity < min_size) or (min_amount is not None and (price_ref * quantity) < min_amount):
                    return {"ok": False, "error": "notional_too_small", "data": {"qty": quantity, "price_ref": price_ref, "min_size": min_size, "min_notional": min_amount}}
                return self.place_exit_market(symbol=symbol, side="BUY", quantity=quantity)
        except Exception:
            pass
        # Place LIMIT SELL
        log.info("exit.limit maker: symbol=%s qty=%.8f px=%.8f timeout=%ss", symbol, quantity, px, self.exit_limit_timeout_sec)
        res = self._place_limit(symbol=symbol, side="SELL", price=px, size=quantity, client_order_id=None)
        log.debug("exit.limit resp ok=%s data=%s err=%s", res.get('ok'), res.get('data'), res.get('error'))
        if res.get("ok") and res.get("data"):
            order_id = None
            data = res.get("data")
            try:
                order_id = str(data.get("orderId"))
            except Exception:
                order_id = None
            if order_id:
                self._add_pending(order_id=order_id, symbol=symbol, side="SELL", kind="exit", price=px, size=quantity, timeout_sec=self.exit_limit_timeout_sec)
                if self._wait_filled(symbol=symbol, order_id=order_id, timeout_sec=self.exit_limit_timeout_sec):
                    self._remove_pending(order_id)
                    return res
            # Cancel if not filled
            try:
                cancel = getattr(self.client, "cancel_order", None)
                if callable(cancel) and order_id:
                    log.info("exit.limit cancel: symbol=%s oid=%s (timeout)", symbol, order_id)
                    cancel(symbol=symbol, order_id=order_id)
            except Exception:
                pass
            if order_id:
                self._remove_pending(order_id)
        # Fallback MARKET close
        log.info("exit.fallback: MARKET close symbol=%s qty=%.8f", symbol, quantity)
        return self.place_exit_market(symbol=symbol, side="BUY", quantity=quantity)


