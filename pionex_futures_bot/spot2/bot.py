from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass
from typing import Optional, Dict

try:
    from .clients.pionex_client import PionexClient  # type: ignore
except Exception:
    from .clients.pionex_client import PionexClient  # type: ignore
from pionex_futures_bot.common.state_store import StateStore
from pionex_futures_bot.common.trade_logger import TradeLogger, TradeSummaryLogger
from pionex_futures_bot.spot2.execution import ExecutionLayer
from pionex_futures_bot.spot2.signals import ZScoreHistory, compute_signal_z, should_enter_by_spread
from pionex_futures_bot.common.strategy import (
    VolatilityState,
    update_volatility_state,
)


@dataclass
class SymbolState:
    last_price: Optional[float] = None
    in_position: bool = False
    side: Optional[str] = None
    quantity: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    order_id: Optional[str] = None
    entry_time: float = 0.0
    max_price_since_entry: float = 0.0


class SpotBotV2:
    def __init__(self, config_path: str = "spot2/config/config.json") -> None:
        import json
        self.config_path = config_path
        self.config = json.loads(open(config_path, "r", encoding="utf-8").read())
        # Logging to console + file (spot2/logs/bot.log)
        self.log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        import logging
        from logging.handlers import TimedRotatingFileHandler
        logging.basicConfig(level=getattr(logging, self.log_level_name, logging.INFO),
                            format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
        self.log = logging.getLogger("spot2")
        try:
            from pathlib import Path as _P
            logs_dir = _P("spot2/logs")
            logs_dir.mkdir(parents=True, exist_ok=True)
            formatter = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s", "%Y-%m-%d %H:%M:%S")
            # File handler
            fh = TimedRotatingFileHandler(str(logs_dir / "bot.log"), when="midnight", backupCount=7, encoding="utf-8")
            fh.setLevel(getattr(logging, self.log_level_name, logging.INFO))
            fh.setFormatter(formatter)
            # Console handler (default INFO)
            ch = logging.StreamHandler()
            ch.setLevel(getattr(logging, self.log_level_name, logging.INFO))
            ch.setFormatter(formatter)
            # Attach to both spot2 and execution loggers
            self.log.addHandler(fh)
            self.log.addHandler(ch)
            exec_logger = logging.getLogger("execution")
            exec_logger.setLevel(getattr(logging, self.log_level_name, logging.INFO))
            exec_logger.addHandler(fh)
            exec_logger.addHandler(ch)
            # Avoid double propagation to root (we provide our own console handler)
            self.log.propagate = False
            exec_logger.propagate = False
        except Exception:
            pass

        # Charger les variables d'environnement depuis .env (racine et dossier module)
        try:
            from dotenv import load_dotenv  # type: ignore
        except Exception:
            load_dotenv = None  # type: ignore
        if load_dotenv:
            try:
                # .env dans la racine de projet (courant)
                load_dotenv(override=False)
                # .env spécifique au dossier spot2/pionex_futures_bot
                from pathlib import Path
                load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
            except Exception:
                pass

        api_key = os.getenv("API_KEY", "")
        api_secret = os.getenv("API_SECRET", "")
        if not api_key or not api_secret:
            self.log.warning("API keys not found in environment; requests to private endpoints will fail (APIKEY_LOST)")
        else:
            # masquage pour debug: 4 premières et 4 dernières
            def _mask(val: str) -> str:
                return f"{val[:4]}…{val[-4:]}" if len(val) > 8 else "***"
            self.log.info("API creds loaded | key=%s secret=%s", _mask(api_key), _mask(api_secret))

        # Client API
        self.client = PionexClient(api_key=api_key,
                                   api_secret=api_secret,
                                   base_url=self.config.get("base_url", os.getenv("PIONEX_BASE_URL", "https://api.pionex.com")),
                                   dry_run=bool(self.config.get("dry_run", True)))

        # Respect config for maker/market behavior (no forcing here)

        # Load symbols trading rules (min/max, precisions)
        import json as _J
        from pathlib import Path as _P
        rules_path = _P(self.config.get("symbols_rules_path", "spot2/config/symbols.json"))
        self._symbol_rules: Dict[str, dict] = {}
        try:
            if rules_path.exists():
                data = _J.loads(rules_path.read_text(encoding="utf-8"))
                arr = data.get("symbols") if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for it in arr:
                    if isinstance(it, dict) and it.get("symbol"):
                        self._symbol_rules[str(it["symbol"]).upper()] = it
            else:
                self.log.warning("symbols rules file not found: %s", str(rules_path))
        except Exception:
            self.log.warning("failed to load symbols rules from %s", str(rules_path))

        # Execution layer
        self.exec = ExecutionLayer(
            self.client,
            prefer_maker=bool(self.config.get("prefer_maker", True)),
            maker_offset_bps=float(self.config.get("maker_offset_bps", 2.0)),
            entry_limit_timeout_sec=int(self.config.get("entry_limit_timeout_sec", 120)),
            exit_limit_timeout_sec=int(self.config.get("exit_limit_timeout_sec", 60)),
            symbol_rules=self._symbol_rules,
        )
        try:
            self.log.info(
                "Maker settings | prefer_maker=%s offset_bps=%.2f entry_timeout=%ss exit_timeout=%ss",
                bool(self.config.get("prefer_maker", True)),
                float(self.config.get("maker_offset_bps", 2.0)),
                int(self.config.get("entry_limit_timeout_sec", 120)),
                int(self.config.get("exit_limit_timeout_sec", 60)),
            )
        except Exception:
            pass

        # Params
        self.symbols = list(self.config.get("symbols", []))
        self.position_usdt = float(self.config.get("position_usdt", 25))
        self.check_interval_sec = int(self.config.get("check_interval_sec", 4))
        self.breakout_lookback_sec = int(self.config.get("breakout_lookback_sec", 60))
        self.breakout_confirm_ticks = int(self.config.get("breakout_confirm_ticks", 2))
        self.ewm_lambda = float(self.config.get("ewm_lambda", 0.94))
        self.z_threshold_contrarian = float(self.config.get("z_threshold_contrarian", 2.6))
        self.entry_max_spread_bps = float(self.config.get("entry_max_spread_bps", 3.0))
        self.dynamic_z_enabled = bool(self.config.get("dynamic_z_enabled", True))
        self.dynamic_z_percentile = float(self.config.get("dynamic_z_percentile", 0.7))
        self.verify_after_trade = bool(self.config.get("verify_after_trade", True))
        # Throttling caps
        self.max_open_trades = int(self.config.get("max_open_trades", 1))
        self.max_open_trades_per_symbol = int(self.config.get("max_open_trades_per_symbol", 1))

        # State
        self._states: Dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        from collections import deque as _dq
        self._vol_state: Dict[str, VolatilityState] = {s: VolatilityState(ewm_var=0.0, window=_dq(maxlen=300)) for s in self.symbols}
        self._z_hist: Dict[str, ZScoreHistory] = {s: ZScoreHistory() for s in self.symbols}
        # Chemins dédiés à spot2
        self.state_store = StateStore(self.config.get("state_file", "spot2/logs/runtime_state.json"))
        self.logger = TradeLogger(self.config.get("log_csv", "spot2/logs/trades.csv"))
        self.summary_logger = TradeSummaryLogger(self.config.get("summary_csv", "spot2/logs/trades_summary.csv"))
        # Closed positions snapshot file (for post-mortem analysis)
        try:
            from pathlib import Path as _P
            self._closed_positions_csv = _P(self.config.get("closed_positions_csv", "spot2/logs/closed_positions.csv"))
            self._closed_positions_csv.parent.mkdir(parents=True, exist_ok=True)
            if not self._closed_positions_csv.exists():
                self._closed_positions_csv.write_text(
                    "time,symbol,side,qty,entry_price,close_price,value_usdt,pnl_usdt,pnl_percent,sl_price,sl_percent,tp_price,tp_percent,trail_stop,trail_percent,peak_percent,hold_sec,reason\n",
                    encoding="utf-8",
                )
        except Exception:
            self._closed_positions_csv = None
        # Concurrency guards and counters
        self._open_trades_lock = threading.Lock()
        self._open_trades_count = 0
        self._symbol_open_count: Dict[str, int] = {s: 0 for s in self.symbols}
        # Global safety flag: halt entries when insufficient funds detected
        self._halt_entries_due_to_funds: bool = False
        self._funds_backoff_sec: int = int(self.config.get("insufficient_funds_backoff_sec", 300))
        self._funds_last_log_ts: float = 0.0
        # Per-symbol halt reason (e.g. notional too small to exit)
        self._halt_reason: Dict[str, str] = {}
        # Initialize state and counters from persisted store to enforce caps immediately
        try:
            persisted = self.state_store.load()
            if isinstance(persisted, dict):
                for sym, data in persisted.items():
                    if sym in self._states and isinstance(data, dict) and data.get("in_position"):
                        st = self._states[sym]
                        st.in_position = True
                        st.side = data.get("side")
                        try:
                            st.quantity = float(data.get("quantity", 0.0))
                            st.entry_price = float(data.get("entry_price", 0.0))
                            st.stop_loss = float(data.get("stop_loss", 0.0)) if data.get("stop_loss") is not None else st.stop_loss
                            st.take_profit = float(data.get("take_profit", 0.0)) if data.get("take_profit") is not None else st.take_profit
                            st.entry_time = float(data.get("entry_time", 0.0))
                            st.max_price_since_entry = float(data.get("max_price_since_entry", st.entry_price or 0.0))
                        except Exception:
                            pass
                        with self._open_trades_lock:
                            self._open_trades_count += 1
                            self._symbol_open_count[sym] = self._symbol_open_count.get(sym, 0) + 1
        except Exception:
            pass

        # Log configuration summary (utile pour valider que les paramètres sont bien lus)
        try:
            self.log.info(
                "Spot2 params | min_hold=%ss hysteresis=%.2f%% sl=%.2f%% tp=%.2f%% trailing: act=%.2f%% retrace=%.2f%% maker_tp=%s maker_trail=%s",
                int(self.config.get("min_hold_sec", 25)),
                float(self.config.get("exit_hysteresis_percent", 0.10)),
                float(self.config.get("stop_loss_percent", 2.0)),
                float(self.config.get("take_profit_percent", 3.0)),
                float(self.config.get("trailing_activation_gain_percent", 2.0)),
                float(self.config.get("trailing_retrace_percent", 0.25)),
                bool(self.config.get("exit_maker_for_tp", True)),
                bool(self.config.get("exit_maker_for_trailing", True)),
            )
        except Exception:
            pass

    # --- Helpers ---
    def _base_asset(self, symbol: str) -> str:
        sym = symbol
        if "_" in sym:
            return sym.split("_")[0]
        if sym.endswith("USDT"):
            return sym[:-4]
        return sym

    def _get_free_base_balance(self, symbol: str) -> float:
        try:
            coin = self._base_asset(symbol).upper()
            r = self.client.get_balances()
            if not r.ok or not r.data:
                return 0.0
            arr = (r.data.get("data") or {}).get("balances") if isinstance(r.data, dict) else None
            if isinstance(arr, list):
                for b in arr:
                    if isinstance(b, dict) and str(b.get("coin","")) == coin:
                        return float(b.get("free", 0.0))
        except Exception:
            return 0.0
        return 0.0

    def _get_free_quote_balance(self, symbol: str) -> float:
        # For now, all are *_USDT pairs
        try:
            r = self.client.get_balances()
            if not r.ok or not r.data:
                return 0.0
            arr = (r.data.get("data") or {}).get("balances") if isinstance(r.data, dict) else None
            if isinstance(arr, list):
                for b in arr:
                    if isinstance(b, dict) and str(b.get("coin","")) == "USDT":
                        return float(b.get("free", 0.0))
        except Exception:
            return 0.0
        return 0.0

    def _record_closed_snapshot(self, *, symbol: str, st: SymbolState, close_price: float, elapsed: float, reason: str) -> None:
        try:
            if not self._closed_positions_csv:
                return
            import math as _m
            # Compute derived values similar to monitor
            qty = float(st.quantity or 0.0)
            entry = float(st.entry_price or 0.0)
            value = (close_price or 0.0) * qty
            pnl_usdt = (close_price - entry) * qty if (st.side or "BUY") == "BUY" else (entry - close_price) * qty
            pnl_pct = ((close_price - entry) / entry * 100.0) if entry > 0 else 0.0
            sl = float(st.stop_loss or 0.0)
            tp = float(st.take_profit or 0.0)
            sl_pct = ((sl / entry - 1.0) * 100.0) if entry > 0 and sl > 0 else 0.0
            tp_pct = ((tp / entry - 1.0) * 100.0) if entry > 0 and tp > 0 else 0.0
            # Trail stop and peak
            retrace = float(self.config.get("trailing_retrace_percent", 0.25))
            peak_px = float(st.max_price_since_entry or 0.0)
            trail_stop = peak_px * (1.0 - retrace / 100.0) if peak_px > 0 else 0.0
            trail_percent = ((trail_stop / entry - 1.0) * 100.0) if entry > 0 and trail_stop > 0 else 0.0
            peak_percent = ((peak_px - entry) / entry * 100.0) if entry > 0 and peak_px > 0 else 0.0
            from datetime import datetime as _dt
            ts = _dt.utcnow().isoformat() + "Z"
            row = (
                f"{ts},{symbol},{st.side or ''},{qty:.6f},{entry:.6f},{close_price:.6f},{value:.6f},{pnl_usdt:.6f},{pnl_pct:.2f},{sl:.6f},{sl_pct:.2f},{tp:.6f},{tp_pct:.2f},{trail_stop:.6f},{trail_percent:.2f},{peak_percent:.2f},{int(elapsed)},{reason}\n"
            )
            with self._closed_positions_csv.open("a", encoding="utf-8") as f:
                f.write(row)
        except Exception:
            pass

    def run(self) -> None:
        threads = []
        # Resume check: log any positions found in state store
        try:
            persisted = self.state_store.load()
            for sym, st in sorted(persisted.items()):
                if isinstance(st, dict) and st.get("in_position"):
                    self.log.info("%s RESUME in_position side=%s qty=%.6f entry=%.6f sl=%.6f tp=%.6f", sym, st.get("side"), float(st.get("quantity",0.0)), float(st.get("entry_price",0.0)), float(st.get("stop_loss",0.0)), float(st.get("take_profit",0.0)))
        except Exception:
            pass
        for s in self.symbols:
            t = threading.Thread(target=self._worker, args=(s,), daemon=True, name=f"{s}-spot2")
            t.start()
            threads.append(t)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    # --- Worker per symbol ---
    def _worker(self, symbol: str) -> None:
        st = self._states[symbol]
        self.log.info("Worker started for %s (spot2)", symbol)
        # Init price
        while st.last_price is None:
            r = self.client.get_price(symbol)
            if r.ok and r.data and "price" in r.data:
                st.last_price = float(r.data["price"])  # type: ignore[arg-type]
                self.log.info("%s initial price set: %.8f", symbol, st.last_price)
            else:
                time.sleep(1)
        price_hist: list[tuple[float, float]] = []
        tick = 0
        while True:
            # Si trop de positions sont ouvertes globalement, geler les symboles sans position
            if self._halt_entries_due_to_funds and not st.in_position:
                now_ts = time.time()
                if now_ts - self._funds_last_log_ts >= max(30, self._funds_backoff_sec):
                    self._funds_last_log_ts = now_ts
                    self.log.warning("%s idle: entries halted due to insufficient funds (backoff %ss)", symbol, self._funds_backoff_sec)
                time.sleep(max(self._funds_backoff_sec, self.check_interval_sec))
                tick += 1
                continue
            with self._open_trades_lock:
                open_count = self._open_trades_count
                max_open = self.max_open_trades
            if open_count >= max_open and not st.in_position:
                # Backoff agressif pour réduire la charge: ne rafraîchit pas les prix
                if (tick % max(1, int(60 / max(1, self.check_interval_sec)))) == 0:
                    self.log.info("%s idle: max_open_trades reached (%d/%d)", symbol, open_count, max_open)
                time.sleep(max(self.check_interval_sec, int(self.config.get("idle_backoff_sec", 24))))
                tick += 1
                continue

            r = self.client.get_price(symbol)
            if not r.ok or not r.data or "price" not in r.data:
                time.sleep(self.check_interval_sec)
                continue
            price = float(r.data["price"])  # type: ignore[arg-type]
            now = time.time()
            # Append current tick to history and trim old samples beyond lookback window (to keep ref moving)
            price_hist.append((now, price))
            cutoff_keep = now - max(self.breakout_lookback_sec * 2, self.breakout_lookback_sec + 10)
            # Remove old samples from the front
            if len(price_hist) > 1:
                try:
                    # fast trim when many stale samples accumulate
                    while len(price_hist) > 0 and price_hist[0][0] < cutoff_keep:
                        price_hist.pop(0)
                except Exception:
                    pass
            cutoff = now - self.breakout_lookback_sec
            ref = price
            for ts, px in reversed(price_hist):
                if ts <= cutoff:
                    ref = px
                    break
            if not st.in_position:
                change_pct = (price - ref) / ref * 100.0
                # update vol and z history (ret based on last observed tick)
                ret_pct = 0.0
                try:
                    prev_px = st.last_price if (st.last_price and st.last_price > 0) else ref
                    ret_pct = (price - prev_px) / prev_px * 100.0 if prev_px > 0 else 0.0
                except Exception:
                    ret_pct = 0.0
                self._vol_state[symbol] = update_volatility_state(state=self._vol_state[symbol], ret=ret_pct, lambda_ewm=self.ewm_lambda)
                sigma = (self._vol_state[symbol].ewm_var ** 0.5) if self._vol_state[symbol].ewm_var > 0 else 0.0
                k_base = self.z_threshold_contrarian
                sig = compute_signal_z(change_pct, sigma, k_base, mode="contrarian")
                self._z_hist[symbol].push(sig.score)
                if self.dynamic_z_enabled:
                    dyn = self._z_hist[symbol].percentile(self.dynamic_z_percentile)
                    eff = max(k_base, dyn)
                    sig = compute_signal_z(change_pct, sigma, eff, mode="contrarian")

                # Simple spread filter using synthetic book
                book = self.exec.get_book_ticker(symbol)
                if book and sig.side == "BUY":
                    spread_bps = (book.ask - book.bid) / ((book.ask + book.bid) / 2.0) * 10000.0
                    if not should_enter_by_spread(spread_bps, self.entry_max_spread_bps):
                        sig = type(sig)(side=None, score=sig.score)

                # confirmation
                if sig.side == "BUY":
                    tick += 1
                else:
                    tick = 0
                should_enter = sig.side == "BUY" and tick >= self.breakout_confirm_ticks
                # Global + per-symbol guardrail with atomic reservation
                can_enter = False
                if should_enter:
                    with self._open_trades_lock:
                        cur_sym = self._symbol_open_count.get(symbol, 0)
                        if cur_sym < self.max_open_trades_per_symbol and self._open_trades_count < self.max_open_trades:
                            self._symbol_open_count[symbol] = cur_sym + 1
                            self._open_trades_count += 1
                            can_enter = True
                if can_enter:
                    # Pre-check: ensure that minimum exit constraints are satisfiable given position_usdt
                    try:
                        # Resolve rules
                        rules = self.exec._resolve_rules(symbol)
                        min_size = float(rules.get("minTradeSize")) if rules.get("minTradeSize") is not None else None
                        min_notional = None
                        for k in ("minAmount", "minTradeAmount", "minNotional"):
                            if rules.get(k) is not None:
                                try:
                                    min_notional = float(rules.get(k)); break
                                except Exception:
                                    pass
                        # Compute max sellable qty from intended entry amount at current price
                        intended_qty = amt / max(price, 1e-12)
                        # Apply size precision and step
                        base_prec = int(rules.get("basePrecision", 6)) if rules.get("basePrecision") is not None else 6
                        if base_prec >= 0:
                            factor = 10 ** base_prec
                            intended_qty = (int(intended_qty * factor)) / factor
                        if min_size is not None and min_size > 0:
                            import math as _m
                            mult = _m.floor(intended_qty / float(min_size))
                            intended_qty = max(0.0, mult * float(min_size))
                        # Conservative notional check with bid/last
                        bid_ref = None
                        try:
                            bk = self.exec.get_book_ticker(symbol)
                            bid_ref = None if not bk else float(bk.bid)
                        except Exception:
                            bid_ref = None
                        price_ref = min(price, bid_ref) if (bid_ref is not None) else price
                        notional_ref = price_ref * intended_qty
                        if (min_size is not None and intended_qty < min_size) or (min_notional is not None and notional_ref < min_notional):
                            self._halt_reason[symbol] = "entry_blocked_min_exit"
                            with self._open_trades_lock:
                                # rollback reservation
                                if self._open_trades_count > 0:
                                    self._open_trades_count -= 1
                                cur_sym = self._symbol_open_count.get(symbol, 0)
                                if cur_sym > 0:
                                    self._symbol_open_count[symbol] = cur_sym - 1
                            self.log.error(
                                "%s entry blocked: position_usdt=%.4f would be too small to exit (qty=%.8f min_size=%s notional_ref=%.6f min_notional=%s)",
                                symbol, amt, intended_qty, str(min_size), notional_ref, str(min_notional)
                            )
                            # Stop this worker loop for that symbol
                            time.sleep(self._funds_backoff_sec)
                            return
                    except Exception:
                        pass
                    # Place entry (respect config: maker/market handled by ExecutionLayer)
                    amt = self.position_usdt
                    pre_free_base = self._get_free_base_balance(symbol)
                    pre_free_quote = self._get_free_quote_balance(symbol)
                    resp = self.exec.place_entry(symbol=symbol, price_hint=price, amount_usdt=amt, client_order_id=None)
                    if resp.get("ok"):
                        st.in_position = True
                        st.side = "BUY"
                        # Default estimate prior to verification
                        st.entry_price = price
                        st.quantity = max(0.0, amt / max(price, 1e-12))
                        st.entry_time = now
                        # Compute baseline SL/TP for display/control
                        stop_loss_percent = float(self.config.get("stop_loss_percent", 2.0))
                        take_profit_percent = float(self.config.get("take_profit_percent", 3.0))
                        st.stop_loss = st.entry_price * (1.0 - stop_loss_percent / 100.0)
                        st.take_profit = st.entry_price * (1.0 + take_profit_percent / 100.0)
                        st.max_price_since_entry = st.entry_price
                        self.state_store.update_symbol(symbol, {"in_position": True, "side": st.side, "quantity": st.quantity, "entry_price": st.entry_price, "entry_time": st.entry_time})
                        # Persist additional fields
                        self.state_store.update_symbol(symbol, {"stop_loss": st.stop_loss, "take_profit": st.take_profit, "max_price_since_entry": st.max_price_since_entry})
                        self.logger.log(event="ENTRY", symbol=symbol, side=st.side, quantity=st.quantity, entry_price=st.entry_price, price=st.entry_price, stop_loss=st.stop_loss, take_profit=st.take_profit)
                        self.log.info("%s ENTRY ok qty=%.6f entry=%.6f sl=%.6f tp=%.6f", symbol, st.quantity, st.entry_price, st.stop_loss, st.take_profit)
                        # Vérification post-trade (ajustement quantité selon fills/balances)
                        try:
                            if self.verify_after_trade and not getattr(self.client, "dry_run", True):
                                data = resp.get("data") or {}
                                order_id = data.get("orderId") if isinstance(data, dict) else None
                                if order_id:
                                    fills = self.client.get_fills_by_order_id(symbol, str(order_id))
                                    if fills.ok and fills.data:
                                        arr = (fills.data.get("data") or {}).get("fills") if isinstance(fills.data, dict) else None
                                        if isinstance(arr, list) and arr:
                                            qsum = 0.0; notional = 0.0; fee_total = 0.0
                                            for f in arr:
                                                try:
                                                    qf = float(f.get("size", 0.0)); pf = float(f.get("price", 0.0))
                                                    fee = f.get("fee")
                                                except Exception:
                                                    qf = 0.0; pf = 0.0; fee = None
                                                qsum += qf; notional += qf * pf
                                                # Fee might be charged in quote or base; if in quote, reduce notional; if in base, reduce qty
                                                try:
                                                    if isinstance(fee, dict):
                                                        fv = float(fee.get("amount", 0.0)); fc = str(fee.get("currency", "")).upper()
                                                        if fc == "USDT":
                                                            fee_total += fv
                                                        elif fc == self._base_asset(symbol).upper():
                                                            qsum = max(0.0, qsum - fv)
                                                    elif fee is not None:
                                                        fv = float(fee); fee_total += fv
                                                except Exception:
                                                    pass
                                            if qsum > 0:
                                                # Only update real obtained quantity; keep entry_price unchanged
                                                st.quantity = qsum
                                                self.state_store.update_symbol(symbol, {"quantity": st.quantity})
                            # Ajustement via delta de balances (source de vérité: variation quote et base)
                            post_free_base = self._get_free_base_balance(symbol)
                            delta_q_base = max(0.0, post_free_base - pre_free_base)
                            if delta_q_base > 0:
                                # Respect basePrecision step
                                rules = self._symbol_rules.get(symbol) or self._symbol_rules.get(symbol.upper()) or {}
                                base_prec = int(rules.get("basePrecision", 6)) if rules.get("basePrecision") is not None else 6
                                if base_prec >= 0:
                                    factor = 10 ** base_prec
                                    delta_q_base = (int(delta_q_base * factor)) / factor
                                if delta_q_base > 0:
                                    # Set quantity to actual obtained; keep entry_price unchanged
                                    new_qty = delta_q_base
                                    self.log.info(
                                        "%s ENTRY balance(base) confirm: qty=%.6f (invested %.4f USDT)",
                                        symbol, new_qty, amt
                                    )
                                    st.quantity = new_qty
                                    self.state_store.update_symbol(symbol, {"quantity": st.quantity})
                        except Exception:
                            pass
                    else:
                        # Handle specific API error codes
                        try:
                            err_txt = str(resp.get("error") or "").upper()
                            code = None
                            data = resp.get("data") if isinstance(resp, dict) else None
                            if isinstance(data, dict):
                                code = str(data.get("code") or "").upper()
                            # Log full request context if available
                            sent = resp.get("_sent") if isinstance(resp, dict) else None
                            if err_txt or code:
                                self.log.error("%s ENTRY failed: code=%s err=%s sent=%s", symbol, code, err_txt, sent)
                            if (code and "TRADE_NOT_ENOUGH_MONEY" in code) or ("TRADE_NOT_ENOUGH_MONEY" in err_txt):
                                self._halt_entries_due_to_funds = True
                                self.log.error("%s ENTRY halted: TRADE_NOT_ENOUGH_MONEY. Halting all new entries.", symbol)
                        except Exception:
                            pass
                        # Release reservations on failure
                        with self._open_trades_lock:
                            if self._open_trades_count > 0:
                                self._open_trades_count -= 1
                            cur_sym = self._symbol_open_count.get(symbol, 0)
                            if cur_sym > 0:
                                self._symbol_open_count[symbol] = cur_sym - 1
            # Manage exits: SL / TP / trailing with maker-preferred for TP/trailing
            if st.in_position:
                elapsed = now - (st.entry_time or now)
                # simple ATR-like thresholds not yet available in v2; use spot1 params if present
                stop_loss_percent = float(self.config.get("stop_loss_percent", 2.0))
                take_profit_percent = float(self.config.get("take_profit_percent", 3.0))
                hysteresis = float(self.config.get("exit_hysteresis_percent", 0.10))
                min_hold = int(self.config.get("min_hold_sec", 25))
                sl_px = st.entry_price * (1.0 - stop_loss_percent / 100.0)
                tp_px = st.entry_price * (1.0 + take_profit_percent / 100.0)
                # Base seuils et seuils effectifs (activés après min_hold)
                sl_trig_base = sl_px * (1.0 - hysteresis / 100.0)
                tp_trig_base = tp_px * (1.0 + hysteresis / 100.0)
                sl_active = elapsed >= min_hold
                tp_active = elapsed >= min_hold
                sl_trig = sl_trig_base if sl_active else 0.0
                tp_trig = tp_trig_base if tp_active else float("inf")
                exit_reason = None
                # Pré-calculs conditions pour journalisation claire
                sl_cond = price <= sl_trig if sl_active else False
                tp_cond = price >= tp_trig if tp_active else False
                trail_act_gain = float(self.config.get("trailing_activation_gain_percent", 2.0))
                trail_retrace = float(self.config.get("trailing_retrace_percent", 0.25))
                gain_from_entry_pct = (st.max_price_since_entry - st.entry_price) / st.entry_price * 100.0 if st.entry_price > 0 else 0.0
                trail_activated = gain_from_entry_pct >= trail_act_gain and elapsed >= min_hold and bool(self.config.get("trailing_enabled", True))
                trail_stop = st.max_price_since_entry * (1.0 - trail_retrace / 100.0) if st.max_price_since_entry > 0 else 0.0
                trail_cond = price <= trail_stop if trail_activated else False
                # Heartbeat/debug for position evaluation
                try:
                    self.log.debug(
                        "%s eval: price=%.6f entry=%.6f sl_px=%.6f tp_px=%.6f sl_trig=%.6f tp_trig=%.6f hold=%ds sl_active=%s tp_active=%s",
                        symbol,
                        price,
                        st.entry_price,
                        sl_px,
                        tp_px,
                        sl_trig,
                        tp_trig,
                        int(elapsed),
                        sl_active,
                        tp_active,
                    )
                    # Log synthétique des conditions de sortie attendues vs observées
                    self.log.debug(
                        "%s exit_check | SL cond=%s (price<=%.6f) | TP cond=%s (price>=%.6f) | TRAIL act=%s (gain=%.2f%%>=%.2f%%) cond=%s (price<=%.6f)",
                        symbol,
                        sl_cond,
                        sl_trig,
                        tp_cond,
                        tp_trig,
                        trail_activated,
                        gain_from_entry_pct,
                        trail_act_gain,
                        trail_cond,
                        trail_stop,
                    )
                    if not sl_active or not tp_active:
                        self.log.debug(
                            "%s hold gate active: remaining=%ds (min_hold=%ds)",
                            symbol,
                            max(0, int(min_hold - elapsed)),
                            min_hold,
                        )
                except Exception:
                    pass
                # Force close signal from state store (set by monitor)
                try:
                    cur = self.state_store.load()
                    ent = cur.get(symbol)
                    if isinstance(ent, dict) and ent.get("force_close"):
                        exit_reason = "FORCE"
                        pre_free = self._get_free_base_balance(symbol)
                        exit_resp = self.exec.place_exit_market(symbol=symbol, side="BUY", quantity=st.quantity)
                        # clear flag immediately to avoid loops
                        ent.pop("force_close", None)
                        cur[symbol] = ent
                        self.state_store.save(cur)
                except Exception:
                    pass
                # Track peak since entry for trailing
                try:
                    if st.max_price_since_entry <= 0.0:
                        st.max_price_since_entry = st.entry_price
                    prev_peak = st.max_price_since_entry
                    st.max_price_since_entry = max(st.max_price_since_entry, price)
                    if st.max_price_since_entry > prev_peak:
                        self.state_store.update_symbol(symbol, {"max_price_since_entry": st.max_price_since_entry})
                except Exception:
                    pass
                if price <= sl_trig:
                    self.log.info("%s SL trigger: price=%.6f <= sl_trig=%.6f (sl_px=%.6f, hold=%ds)", symbol, price, sl_trig, sl_px, int(elapsed))
                    exit_reason = "SL"
                    pre_free = self._get_free_base_balance(symbol)
                    exit_resp = self.exec.place_exit_market(symbol=symbol, side="BUY", quantity=st.quantity)
                elif price >= tp_trig:
                    # TP: maker LIMIT si activé, sinon MARKET
                    exit_reason = "TP"
                    self.log.info(
                        "%s TP trigger: price=%.6f >= tp_trig=%.6f (tp_px=%.6f, hold=%ds) maker_for_tp=%s",
                        symbol,
                        price,
                        tp_trig,
                        tp_px,
                        int(elapsed),
                        bool(self.config.get("exit_maker_for_tp", True)),
                    )
                    if bool(self.config.get("exit_maker_for_tp", True)):
                        pre_free = self._get_free_base_balance(symbol)
                        exit_resp = self.exec.place_exit_limit_maker_sell(symbol=symbol, quantity=st.quantity, min_price=tp_px)
                    else:
                        pre_free = self._get_free_base_balance(symbol)
                        exit_resp = self.exec.place_exit_market(symbol=symbol, side="BUY", quantity=st.quantity)
                else:
                    # Trailing maker (optionnel)
                    if bool(self.config.get("trailing_enabled", True)) and elapsed >= min_hold:
                        gain_from_entry_pct = (st.max_price_since_entry - st.entry_price) / st.entry_price * 100.0 if st.entry_price > 0 else 0.0
                        act_gain = float(self.config.get("trailing_activation_gain_percent", 2.0))
                        retrace = float(self.config.get("trailing_retrace_percent", 0.25))
                        if gain_from_entry_pct >= act_gain:
                            trailing_stop = st.max_price_since_entry * (1.0 - retrace / 100.0)
                            # Log evaluation of trailing window
                            try:
                                self.log.debug(
                                    "%s TRAIL eval: peak=%.6f stop=%.6f price=%.6f gain%%=%.2f act%%=%.2f retrace%%=%.2f",
                                    symbol,
                                    st.max_price_since_entry,
                                    trailing_stop,
                                    price,
                                    gain_from_entry_pct,
                                    act_gain,
                                    retrace,
                                )
                            except Exception:
                                pass
                            if price <= trailing_stop:
                                exit_reason = "TRAIL"
                                self.log.info(
                                    "%s TRAIL trigger: price=%.6f <= stop=%.6f (peak=%.6f, hold=%ds, maker_for_trail=%s)",
                                    symbol,
                                    price,
                                    trailing_stop,
                                    st.max_price_since_entry,
                                    int(elapsed),
                                    bool(self.config.get("exit_maker_for_trailing", True)),
                                )
                                if bool(self.config.get("exit_maker_for_trailing", True)):
                                    pre_free = self._get_free_base_balance(symbol)
                                    exit_resp = self.exec.place_exit_limit_maker_sell(symbol=symbol, quantity=st.quantity, min_price=trailing_stop)
                                else:
                                    pre_free = self._get_free_base_balance(symbol)
                                    exit_resp = self.exec.place_exit_market(symbol=symbol, side="BUY", quantity=st.quantity)
                if exit_reason:
                    pnl = (price - st.entry_price) * st.quantity
                    pnl_percent = (price - st.entry_price) / st.entry_price * 100.0
                    # Estimation executed/residual via delta de balance (hors dry-run)
                    executed_qty = st.quantity
                    residual_qty = 0.0
                    try:
                        post_free = self._get_free_base_balance(symbol)
                        delta = pre_free - post_free
                        if delta > 0:
                            executed_qty = min(st.quantity, max(0.0, delta))
                            residual_qty = max(0.0, st.quantity - executed_qty)
                    except Exception:
                        pass
                    # Finalize only if the exit action actually succeeded
                    ok = False
                    try:
                        ok = bool(exit_resp.get("ok"))  # type: ignore[attr-defined]
                    except Exception:
                        ok = False
                    if ok:
                        self.logger.log(event=f"EXIT_{exit_reason}", symbol=symbol, side=st.side, quantity=st.quantity, price=price, entry_price=st.entry_price, exit_price=price, pnl=pnl, pnl_percent=pnl_percent, reason=exit_reason)
                        self.log.info("%s EXIT %s ok qty=%.6f price=%.6f pnl=%.6f (%.2f%%)", symbol, exit_reason, st.quantity, price, pnl, pnl_percent)
                        # Snapshot closed position for later what-if analysis
                        self._record_closed_snapshot(symbol=symbol, st=st, close_price=price, elapsed=elapsed, reason=exit_reason)
                        self.summary_logger.log_result(symbol=symbol, side=st.side, quantity=st.quantity, executed_qty=executed_qty, residual_qty=residual_qty, entry_price=st.entry_price, exit_price=price, entry_time=st.entry_time, exit_time=now, pnl_usdt=pnl, pnl_percent=pnl_percent, exit_reason=exit_reason)
                        st.in_position = False
                        st.side = None
                        st.quantity = 0.0
                        st.entry_price = 0.0
                        st.entry_time = 0.0
                        st.max_price_since_entry = 0.0
                        self.state_store.clear_symbol(symbol)
                        # Release reservations after successful exit
                        with self._open_trades_lock:
                            if self._open_trades_count > 0:
                                self._open_trades_count -= 1
                            cur_sym = self._symbol_open_count.get(symbol, 0)
                            if cur_sym > 0:
                                self._symbol_open_count[symbol] = cur_sym - 1
                    else:
                        # Exit failed; keep position and log details for retry on next tick
                        try:
                            code = exit_resp.get("error") or getattr(exit_resp, "error", None)
                            sent = exit_resp.get("_sent") if isinstance(exit_resp, dict) else None
                        except Exception:
                            code = None
                        self.log.error("%s EXIT %s failed, keeping position (err=%s, sent=%s)", symbol, exit_reason, code, sent)
                        # If due to notional too small, stop the worker for this symbol to avoid loops
                        if str(code or "").lower().startswith("notional_too_small"):
                            self._halt_reason[symbol] = "exit_blocked_min_notional"
                            self.log.error("%s worker halted: exit blocked by min notional/size", symbol)
                            return
            st.last_price = price
            time.sleep(self.check_interval_sec)


