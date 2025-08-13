from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import math


# Ensure repo root on sys.path (run as script)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _try_load_env_files() -> None:
    env_candidates = [
        Path(__file__).resolve().parents[2] / ".env",  # pionex_futures_bot/.env
        PROJECT_ROOT / ".env",
    ]
    try:
        from dotenv import load_dotenv  # type: ignore
        for p in env_candidates:
            if p.exists():
                load_dotenv(dotenv_path=str(p), override=False)
    except Exception:
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
                        os.environ.setdefault(k.strip(), v.strip())
            except Exception:
                continue


def _norm_symbol(sym: str) -> str:
    s = sym.strip().upper().replace("-", "_").replace(".", "_")
    if s.endswith("USDT") and "_" not in s:
        s = s.replace("USDT", "_USDT")
    return s


def _load_config() -> dict:
    import json
    cfg_path = PROJECT_ROOT / "pionex_futures_bot" / "spot2" / "config" / "config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_first_position() -> Tuple[str, dict]:
    import json
    state_path = PROJECT_ROOT / "pionex_futures_bot" / "spot2" / "logs" / "runtime_state.json"
    d = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    for sym, st in d.items():
        if isinstance(st, dict) and st.get("in_position"):
            return sym, st
    raise RuntimeError("No open position found in runtime_state.json")


def _get_price(client, symbol: str) -> Optional[float]:
    try:
        r = client.get_price(symbol)
        if getattr(r, "ok", False) and getattr(r, "data", None) and "price" in r.data:
            return float(r.data["price"])  # type: ignore[index]
    except Exception:
        return None
    return None


def _fetch_symbol_rules(client, symbol: str) -> dict:
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
                            out = {}
                            for k in ["basePrecision", "quotePrecision", "minTradeSize", "minAmount", "maxTradeSize"]:
                                if k in it:
                                    out[k] = it[k]
                            return out
    except Exception:
        pass
    return {}


def main() -> None:
    # Lazy imports to avoid heavy deps at import time
    try:
        from pionex_futures_bot.spot2.clients.pionex_client import PionexClient
    except Exception:
        from pionex_futures_bot.spot.clients.pionex_client import PionexClient
    from pionex_futures_bot.spot2.execution import ExecutionLayer

    _try_load_env_files()
    api_key = os.getenv("API_KEY", "")
    api_secret = os.getenv("API_SECRET", "")
    base_url = os.getenv("PIONEX_BASE_URL", "https://api.pionex.com")

    cfg = _load_config()
    sym, st = _load_first_position()
    symbol = _norm_symbol(sym)

    # Config parameters (mirror bot)
    min_hold = int(cfg.get("min_hold_sec", 25))
    hysteresis = float(cfg.get("exit_hysteresis_percent", 0.10))
    sl_pct = float(cfg.get("stop_loss_percent", 2.0))
    tp_pct = float(cfg.get("take_profit_percent", 3.0))
    trail_enabled = bool(cfg.get("trailing_enabled", True))
    trail_act = float(cfg.get("trailing_activation_gain_percent", 2.0))
    trail_retrace = float(cfg.get("trailing_retrace_percent", 0.25))
    maker_for_tp = bool(cfg.get("exit_maker_for_tp", True))
    maker_for_trail = bool(cfg.get("exit_maker_for_trailing", True))

    entry_price = float(st.get("entry_price", 0.0))
    entry_time = float(st.get("entry_time", 0.0))
    max_price_since_entry = float(st.get("max_price_since_entry", entry_price))
    qty = float(st.get("quantity", 0.0))

    client = PionexClient(api_key=api_key, api_secret=api_secret, base_url=base_url, dry_run=False)
    rules = _fetch_symbol_rules(client, symbol)
    exec_layer = ExecutionLayer(
        client,
        prefer_maker=True,
        maker_offset_bps=float(cfg.get("maker_offset_bps", 2.0)),
        entry_limit_timeout_sec=int(cfg.get("entry_limit_timeout_sec", 120)),
        exit_limit_timeout_sec=int(cfg.get("exit_limit_timeout_sec", 60)),
        symbol_rules=rules and {symbol: rules},
    )

    # Helpers for detailed debug before sending orders
    def _unify_min_notional(r: dict) -> Optional[float]:
        for k in ("minAmount", "minTradeAmount", "minNotional"):
            if r.get(k) is not None:
                try:
                    return float(r.get(k))
                except Exception:
                    return None
        return None

    def _book_ask(sym: str) -> Optional[float]:
        try:
            bk = client.get_book_ticker(sym)
            if getattr(bk, "ok", False) and getattr(bk, "data", None):
                d = bk.data
                if isinstance(d, dict) and ("ask" in d or "askPrice" in d):
                    return float(d.get("ask") or d.get("askPrice"))
        except Exception:
            return None
        return None

    def _debug_limit_payload(sym: str, qty_in: float, min_price_hint: float, r: dict) -> tuple[float, float]:
        qp = int(r.get("quotePrecision", 6)) if r.get("quotePrecision") is not None else 6
        bp = int(r.get("basePrecision", 6)) if r.get("basePrecision") is not None else 6
        min_size = float(r.get("minTradeSize")) if r.get("minTradeSize") is not None else None
        min_notional = _unify_min_notional(r)
        ask = _book_ask(sym)
        px_src = max(min_price_hint, (ask if ask is not None else min_price_hint))
        px_rounded = float(f"{px_src:.{qp}f}") if qp >= 0 else px_src
        q_src = float(qty_in)
        if bp >= 0:
            factor = 10 ** bp
            q_rounded = (int(q_src * factor)) / factor
        else:
            q_rounded = q_src
        # Apply step size based on minTradeSize: floor to nearest multiple
        q_step = q_rounded
        if min_size is not None and min_size > 0:
            mult = math.floor(q_rounded / min_size)
            q_step = max(0.0, mult * min_size)
            if bp >= 0:
                factor = 10 ** bp
                q_step = (int(q_step * factor)) / factor
        notional_src = px_src * q_src
        notional_rounded = px_rounded * q_step
        print("-- LIMIT maker debug --")
        print({
            "symbol": sym,
            "ask": ask,
            "min_price_hint": min_price_hint,
            "price_src": px_src,
            "price_rounded": px_rounded,
            "qty_src": q_src,
            "qty_rounded": q_rounded,
            "qty_step": q_step,
            "notional_src": notional_src,
            "notional_rounded": notional_rounded,
            "quotePrecision": qp,
            "basePrecision": bp,
            "minTradeSize": min_size,
            "minNotional": min_notional,
            "payload": {"symbol": sym, "side": "SELL", "type": "LIMIT", "size": f"{q_step}", "price": f"{px_rounded}"},
        })
        if (min_size is not None and q_step < min_size) or (min_notional is not None and notional_rounded < min_notional):
            print("[warn] constraints not satisfied: will likely fallback MARKET")
        return px_rounded, q_step

    # Simulation mode for trailing: progressively rise then drop under trailing stop
    simulate = (input("Simulate trailing (y/n) [y]: ").strip().lower() or "y") == "y"
    sim_price = entry_price
    sim_phase = "rise"
    # target peak slightly above activation gain
    target_peak_gain = trail_act + 0.5
    target_peak = entry_price * (1.0 + target_peak_gain / 100.0) if entry_price > 0 else 0.0
    # drop below trailing stop with a small margin
    drop_below = trail_retrace + 0.3
    target_drop = 0.0

    print(f"Watching position {symbol}: qty={qty:.6f} entry={entry_price:.6f}")
    while True:
        real_price = _get_price(client, symbol)
        if simulate:
            if sim_phase == "rise":
                # Move upward by small steps until target peak reached
                step = max(1e-9, entry_price * 0.001)
                sim_price = min(target_peak, sim_price + step)
                if sim_price >= target_peak:
                    sim_phase = "drop"
                    # compute trailing stop at peak and a drop target below it
                    peak = max(max_price_since_entry, sim_price)
                    target_drop = peak * (1.0 - (drop_below / 100.0))
            else:
                # Drop by small steps until below drop target
                step = max(1e-9, entry_price * 0.001)
                sim_price = max(0.0, sim_price - step)
        pr = sim_price if simulate and sim_price > 0 else real_price
        if pr is None:
            time.sleep(1.0)
            continue
        now = time.time()
        elapsed = now - entry_time if entry_time else 0.0
        # Compute targets
        sl_px = entry_price * (1.0 - sl_pct / 100.0)
        tp_px = entry_price * (1.0 + tp_pct / 100.0)
        sl_active = elapsed >= min_hold
        tp_active = elapsed >= min_hold
        sl_trig = sl_px * (1.0 - hysteresis / 100.0) if sl_active else 0.0
        tp_trig = tp_px * (1.0 + hysteresis / 100.0) if tp_active else float("inf")
        # Track peak
        max_price_since_entry = max(max_price_since_entry, pr)
        gain_from_entry_pct = ((max_price_since_entry - entry_price) / entry_price * 100.0) if entry_price > 0 else 0.0
        trail_activated = trail_enabled and elapsed >= min_hold and (gain_from_entry_pct >= trail_act)
        trail_stop = max_price_since_entry * (1.0 - trail_retrace / 100.0) if trail_activated else 0.0
        # Conditions
        sl_cond = sl_active and (pr <= sl_trig)
        tp_cond = tp_active and (pr >= tp_trig)
        trail_cond = trail_activated and (pr <= trail_stop)

        # Tick report
        print(
            f"tick | price={pr:.6f} hold={int(elapsed)}s | SL px={sl_px:.6f} trig={sl_trig:.6f} act={sl_active} cond={sl_cond} | "
            f"TP px={tp_px:.6f} trig={tp_trig:.6f} act={tp_active} cond={tp_cond} | "
            f"TRAIL peak={max_price_since_entry:.6f} gain%={gain_from_entry_pct:.2f} stop={trail_stop:.6f} act={trail_activated} cond={trail_cond}"
        )

        # Exit when any condition is true, like the bot
        if sl_cond:
            print("SL trigger: placing MARKET close")
            # Use real price at exit time for logs
            print(f"real_price_at_exit={real_price}")
            r = exec_layer.place_exit_market(symbol=symbol, side="BUY", quantity=qty)
            print("Exit response:", r)
            break
        if tp_cond:
            if maker_for_tp:
                print("TP trigger: placing LIMIT maker SELL (min_price=tp_px)")
                print(f"real_price_at_exit={real_price}")
                # Show detailed payload before sending
                px_dbg, q_dbg = _debug_limit_payload(symbol, qty, tp_px, rules or {})
                r = exec_layer.place_exit_limit_maker_sell(symbol=symbol, quantity=q_dbg, min_price=px_dbg)
            else:
                print("TP trigger: placing MARKET close")
                print(f"real_price_at_exit={real_price}")
                r = exec_layer.place_exit_market(symbol=symbol, side="BUY", quantity=qty)
            print("Exit response:", r)
            break
        if trail_cond:
            if maker_for_trail:
                print("TRAIL trigger: placing LIMIT maker SELL (min_price=trail_stop)")
                print(f"real_price_at_exit={real_price}")
                px_dbg, q_dbg = _debug_limit_payload(symbol, qty, trail_stop, rules or {})
                r = exec_layer.place_exit_limit_maker_sell(symbol=symbol, quantity=q_dbg, min_price=px_dbg)
            else:
                print("TRAIL trigger: placing MARKET close")
                print(f"real_price_at_exit={real_price}")
                r = exec_layer.place_exit_market(symbol=symbol, side="BUY", quantity=qty)
            print("Exit response:", r)
            break

        time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)


