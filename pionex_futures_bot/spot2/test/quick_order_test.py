from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Optional, Any, Dict
from pathlib import Path

# Ensure project root is on sys.path when running as a script
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _try_load_env_files() -> None:
    """Load environment variables from .env files if present.
    Preference order:
    - pionex_futures_bot/.env (package-local)
    - project root .env
    """
    # Try python-dotenv if available
    env_candidates = [
        Path(__file__).resolve().parents[2] / ".env",  # pionex_futures_bot/.env
        PROJECT_ROOT / ".env",  # repo root .env
    ]
    try:
        from dotenv import load_dotenv  # type: ignore
        for p in env_candidates:
            if p.exists():
                load_dotenv(dotenv_path=str(p), override=False)
    except Exception:
        # Fallback: simple parser KEY=VALUE
        for p in env_candidates:
            try:
                if not p.exists():
                    continue
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip(); v = v.strip()
                        os.environ.setdefault(k, v)
            except Exception:
                continue


def _read_env(key: str, default: str = "") -> str:
    v = os.getenv(key)
    return v if v is not None else default


def _prompt_str(prompt: str, default: Optional[str] = None) -> str:
    s = input(f"{prompt}{' ['+default+']' if default else ''}: ").strip()
    return s or (default or "")


def _prompt_float(prompt: str, default: float) -> float:
    while True:
        s = input(f"{prompt} [{default}]: ").strip() or str(default)
        try:
            return float(s)
        except Exception:
            print("Please enter a number.")


def _choose(prompt: str, choices: list[str], default: str) -> str:
    chs = "/".join(choices)
    while True:
        s = input(f"{prompt} ({chs}) [{default}]: ").strip().lower() or default
        if s in choices:
            return s
        print(f"Invalid choice, pick one of: {chs}")


def _norm_symbol(sym: str) -> str:
    s = sym.strip().upper().replace("-", "_").replace(".", "_")
    if s.endswith("USDT") and "_" not in s:
        s = s.replace("USDT", "_USDT")
    return s


def _print(title: str, data: Any) -> None:
    print(f"\n== {title} ==")
    print(data)


def _get_price(client, symbol: str) -> Optional[float]:
    try:
        r = client.get_price(symbol)
        if getattr(r, "ok", False) and getattr(r, "data", None) and "price" in r.data:
            return float(r.data["price"])  # type: ignore[index]
    except Exception:
        return None
    return None


def _get_quote(symbol: str) -> str:
    s = symbol.replace(".", "_")
    if "_" in s:
        return s.split("_")[-1]
    if s.endswith("USDT"):
        return "USDT"
    return "USDT"


def _get_base(symbol: str) -> str:
    s = symbol.replace(".", "_")
    if "_" in s:
        return s.split("_")[0]
    if s.endswith("USDT"):
        return s[:-4]
    return s


def _get_balance(client, asset: str) -> Optional[float]:
    # Try several balance methods defensively
    for name in [
        "get_balance",
        "get_spot_balance",
        "get_account_balance",
        "balance",
    ]:
        fn = getattr(client, name, None)
        if callable(fn):
            try:
                r = fn(asset)
                # Accept dict or Response-like
                if isinstance(r, dict):
                    for k in ["free", "available", "balance", "amount"]:
                        if k in r:
                            return float(r[k])
                if getattr(r, "ok", False):
                    d = getattr(r, "data", None)
                    if isinstance(d, dict):
                        for k in ["free", "available", "balance", "amount"]:
                            if k in d:
                                return float(d[k])
            except Exception:
                continue
    return None


def _confirm_order(client, symbol: str, order_id: Optional[str]) -> bool:
    if not order_id:
        return False
    fn = getattr(client, "get_order", None)
    if not callable(fn):
        return False
    try:
        r = fn(symbol=symbol, order_id=str(order_id))
        return bool(getattr(r, "ok", False) and getattr(r, "data", None))
    except Exception:
        return False


def _fetch_symbol_rules(client, symbol: str) -> dict:
    # Try to fetch market symbols and extract rule entry for symbol
    try:
        fn = getattr(client, "get_market_symbols", None)
        if callable(fn):
            r = fn(market_type="SPOT")
            if getattr(r, "ok", False) and isinstance(getattr(r, "data", None), dict):
                lst = r.data.get("symbols")  # type: ignore[attr-defined]
                if isinstance(lst, list):
                    norm = _norm_symbol(symbol)
                    alt = norm.replace("_", "")
                    for it in lst:
                        code = str(it.get("symbol") or it.get("code") or it.get("name") or "").upper().replace("-","_")
                        if code in {norm, alt}:
                            # Map to what ExecutionLayer expects
                            out = {}
                            for k in ["basePrecision", "quotePrecision", "minTradeSize", "minAmount", "maxTradeSize"]:
                                if k in it:
                                    out[k] = it[k]
                            # Optional tickSize if exists
                            if "tickSize" in it:
                                out["tickSize"] = it["tickSize"]
                            return out
    except Exception:
        pass
    return {}


def _state_paths() -> tuple[Path, Path]:
    # project_root/pionex_futures_bot
    pkg_root = Path(__file__).resolve().parents[2]
    logs_dir = pkg_root / "spot2" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir, logs_dir / "runtime_state.json"


def _load_state(path: Path) -> dict:
    try:
        if path.exists():
            import json
            return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return {}


def _save_state(path: Path, data: dict) -> None:
    try:
        import json
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    # Lazy imports from project to avoid heavy deps at module import
    try:
        from pionex_futures_bot.spot2.clients.pionex_client import PionexClient
    except Exception:
        from pionex_futures_bot.spot.clients.pionex_client import PionexClient  # fallback
    from pionex_futures_bot.spot2.execution import ExecutionLayer

    _try_load_env_files()
    api_key = _read_env("API_KEY")
    api_secret = _read_env("API_SECRET")
    base_url = _read_env("PIONEX_BASE_URL", "https://api.pionex.com")

    print("Simple Spot2 order test — this will place a BUY order (dry-run if your client supports it).")
    symbol = _norm_symbol(_prompt_str("Symbol (e.g., BTC_USDT)", "BTC_USDT"))
    amount_usdt = _prompt_float("Amount (USDT)", 25.0)
    mode = _choose("Order type", ["maker", "market"], "market")

    # Initialize client (prefer dry-run if supported by client)
    client = PionexClient(api_key=api_key, api_secret=api_secret, base_url=base_url, dry_run=False)

    # Baseline balances
    quote = _get_quote(symbol)
    base = _get_base(symbol)
    bal_quote_before = _get_balance(client, quote)
    bal_base_before = _get_balance(client, base)
    _print("Balances before", {"quote": {quote: bal_quote_before}, "base": {base: bal_base_before}})

    logs_dir, state_path = _state_paths()

    # Execution helpers
    exec_layer = ExecutionLayer(
        client,
        prefer_maker=False,
        maker_offset_bps=5.0,
        entry_limit_timeout_sec=300,  # wait up to 5 minutes for maker fill
        exit_limit_timeout_sec=300,
        symbol_rules={},
    )

    price_hint = _get_price(client, symbol) or 0.0
    _print("Price hint", price_hint)

    res: Dict[str, Any] = {"ok": False}
    order_id: Optional[str] = None
    filled: bool = False
    canceled: bool = False
    filled_price: Optional[float] = None
    filled_qty: Optional[float] = None

    print(f"Placing BUY {mode.upper()} order: {symbol} amount={amount_usdt} USDT")
    if mode == "market":
        r = client.place_market_order(symbol=symbol, side="BUY", amount=amount_usdt, client_order_id=None)
        res = {"ok": getattr(r, "ok", False), "data": getattr(r, "data", None), "error": getattr(r, "error", None)}
        _print("Place order response", res)
        try:
            data = res.get("data") if isinstance(res, dict) else None
            if isinstance(data, dict):
                order_id = data.get("orderId") or data.get("clientOrderId") or None
        except Exception:
            order_id = None
        filled = bool(res.get("ok"))
        # Try retrieve fills
        if order_id:
            ok = _confirm_order(client, symbol, order_id)
            print(f"Confirmed via get_order: {ok} (order_id={order_id})")
    else:
        # Maker: compute price and size roughly as ExecutionLayer would
        book = exec_layer.get_book_ticker(symbol)
        if not book:
            print("No book ticker available; aborting maker test")
            sys.exit(1)
        bid = float(book.bid)
        # Use symbol rules to respect precision and min/max
        rules = _fetch_symbol_rules(client, symbol)
        quote_prec = int(rules.get("quotePrecision", 6)) if rules.get("quotePrecision") is not None else 6
        base_prec = int(rules.get("basePrecision", 6)) if rules.get("basePrecision") is not None else 6
        min_size = float(rules.get("minTradeSize")) if rules.get("minTradeSize") is not None else None
        min_amount = float(rules.get("minAmount")) if rules.get("minAmount") is not None else None
        # maker offset 5 bps below bid
        raw_px = bid * (1.0 - 5.0 / 10000.0)
        px = float(f"{raw_px:.{quote_prec}f}") if quote_prec >= 0 else raw_px
        raw_size = max(0.0, amount_usdt / max(px, 1e-12))
        if base_prec >= 0:
            factor = 10 ** base_prec
            raw_size = (int(raw_size * factor)) / factor
        size = raw_size
        if min_size is not None and size < min_size:
            size = min_size
        if min_amount is not None and (px * size) < min_amount:
            # bump size to reach min notional
            size = min_amount / max(px, 1e-12)
            if base_prec >= 0:
                factor = 10 ** base_prec
                size = (int(size * factor)) / factor
        # Place using ExecutionLayer's internal helper to match client signature
        li = exec_layer._place_limit(symbol=symbol, side="BUY", price=px, size=size, client_order_id=None)  # type: ignore[attr-defined]
        _print("Place limit response", li)
        if li.get("ok") and isinstance(li.get("data"), dict):
            order_id = str(li["data"].get("orderId"))
            # Wait up to 300s for fill
            t0 = time.time()
            last_log = 0.0
            while time.time() - t0 < 300:
                time.sleep(1.0)
                fn = getattr(client, "get_order", None)
                if not callable(fn):
                    break
                try:
                    oo = fn(symbol=symbol, order_id=str(order_id))
                    if getattr(oo, "ok", False) and getattr(oo, "data", None):
                        d = oo.data  # type: ignore[attr-defined]
                        status = str(d.get("status", "")).upper()
                        filled_size = float(d.get("filledSize", 0.0) or 0.0)
                        sz = float(d.get("size", 0.0) or 0.0) or size
                        ap = d.get("avgFillPrice") or d.get("price")
                        if ap is not None:
                            try:
                                filled_price = float(ap)
                            except Exception:
                                pass
                        if time.time() - last_log >= 5.0:
                            last_log = time.time()
                            print(f"poll: status={status} filled={filled_size}/{sz}")
                        if status == "CLOSED" or (sz > 0 and filled_size >= sz):
                            filled = True
                            filled_qty = filled_size if filled_size > 0 else sz
                            break
                except Exception:
                    continue
            if not filled:
                # Cancel after 300s
                print("timeout: canceling LIMIT order")
                try:
                    cancel = getattr(client, "cancel_order", None)
                    if callable(cancel):
                        cancel(symbol=symbol, order_id=str(order_id))
                        canceled = True
                except Exception:
                    pass

    # Balances after
    time.sleep(1.0)
    bal_quote_after = _get_balance(client, quote)
    bal_base_after = _get_balance(client, base)
    _print("Balances after", {"quote": {quote: bal_quote_after}, "base": {base: bal_base_after}})

    # Save position to runtime_state if executed
    if filled:
        entry_px = filled_price or (_get_price(client, symbol) or price_hint or 0.0)
        qty = filled_qty
        if qty is None:
            if entry_px > 0:
                qty = amount_usdt / entry_px
            else:
                qty = 0.0
        _, state_file = _state_paths()
        st = _load_state(state_file)
        st[symbol] = {
            "in_position": True,
            "side": "BUY",
            "quantity": float(qty or 0.0),
            "entry_price": float(entry_px or 0.0),
            "entry_time": time.time(),
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "max_price_since_entry": float(entry_px or 0.0),
        }
        _save_state(state_file, st)
        print(f"Position recorded in {state_file}")
    elif canceled:
        print("Order not filled within 60s and canceled; no position recorded.")

    # Verification output similar to initial version
    if mode == "market":
        order_id = order_id or None
        ok = _confirm_order(client, symbol, order_id) if order_id else False
        print(f"Confirmed via get_order: {ok} (order_id={order_id})")

    # Post balances
    # Basic heuristic: if not dry-run and API returns ok, expect quote decrease or base increase
    if res.get("ok") and bal_quote_before is not None and bal_quote_after is not None:
        if bal_quote_after < bal_quote_before:
            print("Balance check: quote decreased — OK")
        else:
            print("Balance check: quote not decreased (may be dry-run or pending maker)")
    else:
        print("Balance check skipped (missing data or dry-run)")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)


