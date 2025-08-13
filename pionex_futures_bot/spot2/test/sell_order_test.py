from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional, Any, Dict

# Ensure repo root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _try_load_env_files() -> None:
    env_candidates = [
        Path(__file__).resolve().parents[2] / ".env",
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


def _norm_symbol(sym: str) -> str:
    s = sym.strip().upper().replace("-", "_").replace(".", "_")
    if s.endswith("USDT") and "_" not in s:
        s = s.replace("USDT", "_USDT")
    return s


def main() -> None:
    try:
        from pionex_futures_bot.spot2.clients.pionex_client import PionexClient
    except Exception:
        from pionex_futures_bot.spot.clients.pionex_client import PionexClient
    from pionex_futures_bot.spot2.execution import ExecutionLayer

    _try_load_env_files()
    api_key = os.getenv("API_KEY", "")
    api_secret = os.getenv("API_SECRET", "")
    base_url = os.getenv("PIONEX_BASE_URL", "https://api.pionex.com")

    symbol = _norm_symbol(_prompt_str("Symbol (e.g., BTC_USDT)", "BTC_USDT"))
    qty = _prompt_float("Quantity to SELL (base asset)", 0.001)
    mode = (_prompt_str("Order type (maker/market)", "maker").lower())

    client = PionexClient(api_key=api_key, api_secret=api_secret, base_url=base_url, dry_run=False)

    # Execution layer with conservative timeouts for exit
    exec_layer = ExecutionLayer(
        client,
        prefer_maker=True,
        maker_offset_bps=2.0,
        entry_limit_timeout_sec=60,
        exit_limit_timeout_sec=120,
        symbol_rules={},
    )

    if mode == "market":
        r = exec_layer.place_exit_market(symbol=symbol, side="BUY", quantity=qty)
        print("MARKET SELL (close) resp:", r)
        return

    # Maker LIMIT close like the bot (SELL LIMIT with min_price pass-through)
    # We approximate min_price with current price to attempt maker at/above ask
    pr = None
    try:
        px = client.get_price(symbol)
        if getattr(px, "ok", False) and getattr(px, "data", None) and "price" in px.data:
            pr = float(px.data["price"])  # type: ignore[index]
    except Exception:
        pr = None
    min_price = pr or 0.0
    res = exec_layer.place_exit_limit_maker_sell(symbol=symbol, quantity=qty, min_price=min_price)
    print("LIMIT maker SELL resp:", res)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)


