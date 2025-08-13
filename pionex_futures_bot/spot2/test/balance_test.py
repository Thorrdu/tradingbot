from __future__ import annotations

import os
import sys
from typing import Any, Dict, Iterable, Optional
from pathlib import Path


# Ensure repo root on sys.path (run as script)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _try_load_env_files() -> None:
    # Try python-dotenv; fallback to simple parser
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


def _get_price(client, symbol: str) -> Optional[float]:
    try:
        sym = _norm_symbol(symbol)
        # Pionex API attend généralement format "BASE_USDT" sans tirets
        r = client.get_price(sym)
        if getattr(r, "ok", False) and getattr(r, "data", None) and "price" in r.data:
            return float(r.data["price"])  # type: ignore[index]
    except Exception:
        return None
    return None


def _norm_symbol(sym: str) -> str:
    s = sym.strip().upper().replace("-", "_").replace(".", "_")
    if s.endswith("USDT") and "_" not in s:
        s = s.replace("USDT", "_USDT")
    return s


def _asset_list_from_markets(client) -> list[str]:
    # Try get SPOT symbols and extract bases and USDT
    assets: set[str] = set()
    fn = getattr(client, "get_market_symbols", None)
    if callable(fn):
        try:
            r = fn(market_type="SPOT")
            if getattr(r, "ok", False) and isinstance(getattr(r, "data", None), dict):
                lst = r.data.get("symbols")  # type: ignore[attr-defined]
                if isinstance(lst, list):
                    for it in lst:
                        code = str(it.get("symbol") or it.get("code") or it.get("name") or "").upper()
                        code = code.replace("-", "_")
                        base = code.split("_")[0] if "_" in code else code.replace("USDT", "")
                        if base:
                            assets.add(base)
                    assets.add("USDT")
        except Exception:
            pass
    return sorted(assets)


META_KEYS = {"result", "code", "message", "timestamp", "success", "error"}


def _extract_balances(obj: Any) -> Optional[dict[str, float]]:
    # Accept a wide variety of shapes and normalize to {asset: free}
    if obj is None:
        return None
    if isinstance(obj, dict) and obj and all(isinstance(k, str) for k in obj.keys()):
        # If looks like envelope, drill into 'data' or known containers
        lower_keys = {k.lower() for k in obj.keys()}
        if (lower_keys & META_KEYS) and ("data" in obj or "balances" in obj or "assets" in obj):
            inner = obj.get("data") or obj.get("balances") or obj.get("assets")
            return _extract_balances(inner)
        # Specific container: { balances: [ { coin, free, ... }, ... ] }
        if "balances" in obj and isinstance(obj["balances"], list):
            out: dict[str, float] = {}
            for it in obj["balances"]:
                if not isinstance(it, dict):
                    continue
                coin = str(it.get("coin") or it.get("asset") or it.get("currency") or "").upper()
                try:
                    free = float(it.get("free") or it.get("available") or it.get("balance") or it.get("amount") or 0.0)
                except Exception:
                    free = 0.0
                if coin:
                    out[coin] = free
            if out:
                return out
        # Heuristic: keys are assets, values numbers or dicts
        out: dict[str, float] = {}
        for k, v in obj.items():
            key_up = k.upper()
            if key_up.lower() in META_KEYS:
                continue
            try:
                if isinstance(v, (int, float)):
                    # Ignore obviously non-asset numeric keys like timestamps, result flags
                    if key_up.isalpha() or key_up in {"USDT", "BTC", "ETH"} or len(key_up) <= 6:
                        out[key_up] = float(v)
                elif isinstance(v, dict):
                    for kk in ("free", "available", "balance", "amount"):
                        if kk in v:
                            out[key_up] = float(v[kk])
                            break
            except Exception:
                continue
        if out:
            return out
    if isinstance(obj, (list, tuple)):
        out: dict[str, float] = {}
        for it in obj:
            if not isinstance(it, dict):
                continue
            asset = (it.get("asset") or it.get("currency") or it.get("symbol") or it.get("code") or "").upper()
            free = None
            for kk in ("free", "available", "balance", "amount"):
                if kk in it:
                    try:
                        free = float(it[kk])
                        break
                    except Exception:
                        pass
            if asset and free is not None:
                out[asset] = free
        if out:
            return out
    return None


def _get_all_balances(client) -> Optional[dict[str, float]]:
    # Try multiple method names and response shapes
    method_names = [
        "get_balances",
        "get_spot_balances",
        "get_all_balances",
        "get_balance",  # sometimes no-arg returns list
        "account_balances",
    ]
    for name in method_names:
        fn = getattr(client, name, None)
        if not callable(fn):
            continue
        try:
            r = fn()  # try no-arg
            if isinstance(r, dict):
                # Try to unwrap common envelopes
                b = _extract_balances(r)
                if b:
                    return b
            # Response-like
            if getattr(r, "ok", None) is not None:
                data = getattr(r, "data", None)
                b = _extract_balances(data)
                if b:
                    return b
        except TypeError:
            # Likely requires asset argument – skip
            continue
        except Exception:
            continue
    return None


def _get_balance_asset(client, asset: str) -> Optional[float]:
    # Preferred: fetch aggregated balances then select this asset
    gb = getattr(client, "get_balances", None)
    if callable(gb):
        try:
            r = gb()
            data = None
            if isinstance(r, dict):
                data = r
            elif getattr(r, "ok", False):
                data = getattr(r, "data", None)
            # Unwrap common envelopes
            if isinstance(data, dict):
                inner = data.get("data") if isinstance(data.get("data"), dict) else data
                balances = inner.get("balances") if isinstance(inner, dict) else None
                if isinstance(balances, list):
                    tgt = asset.upper()
                    for it in balances:
                        if not isinstance(it, dict):
                            continue
                        coin = str(it.get("coin") or it.get("asset") or it.get("currency") or "").upper()
                        if coin == tgt:
                            try:
                                return float(it.get("free") or it.get("available") or it.get("balance") or it.get("amount") or 0.0)
                            except Exception:
                                return None
        except Exception:
            pass
    # Fallback: per-asset endpoints if exposed by client
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
                if isinstance(r, dict):
                    for k in ("free", "available", "balance", "amount"):
                        if k in r:
                            return float(r[k])
                if getattr(r, "ok", False):
                    d = getattr(r, "data", None)
                    if isinstance(d, dict):
                        for k in ("free", "available", "balance", "amount"):
                            if k in d:
                                return float(d[k])
            except Exception:
                continue
    return None


def main() -> None:
    try:
        from pionex_futures_bot.spot2.clients.pionex_client import PionexClient
    except Exception:
        from pionex_futures_bot.spot.clients.pionex_client import PionexClient  # fallback

    _try_load_env_files()
    api_key = os.getenv("API_KEY", "")
    api_secret = os.getenv("API_SECRET", "")
    base_url = os.getenv("PIONEX_BASE_URL", "https://api.pionex.com")

    client = PionexClient(api_key=api_key, api_secret=api_secret, base_url=base_url, dry_run=False)

    print("Balance test — list all non-zero assets or a specific asset.")
    mode = input("Mode (all/asset) [all]: ").strip().lower() or "all"
    if mode == "asset":
        asset = input("Asset (e.g., USDT, BTC): ").strip().upper() or "USDT"
        bal = _get_balance_asset(client, asset)
        print({asset: bal})
        return

    # Mode ALL
    balances = _get_all_balances(client)
    if balances is None:
        # Fallback: derive asset list from markets and query one by one
        print("No direct 'all balances' endpoint found; iterating assets from markets...")
        assets = _asset_list_from_markets(client)
        out: dict[str, float] = {}
        for a in assets:
            bal = _get_balance_asset(client, a)
            if bal is not None and bal > 0:
                out[a] = bal
        balances = out

    if not balances:
        print("No balances or unable to fetch balances.")
        return

    # Try compute USDT value using spot prices where available
    print("\nBalances (non-zero):")
    total_usdt = 0.0
    for asset, free in sorted(balances.items()):
        if free <= 0:
            continue
        val = None
        if asset == "USDT":
            val = free
        else:
            pr = _get_price(client, f"{asset}_USDT")
            if pr:
                val = pr * free
        if val is not None:
            total_usdt += val
            print(f"- {asset}: {free:.8f} (~{val:.4f} USDT)")
        else:
            print(f"- {asset}: {free:.8f}")
    print(f"\nEstimated total (USDT): {total_usdt:.4f}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)


