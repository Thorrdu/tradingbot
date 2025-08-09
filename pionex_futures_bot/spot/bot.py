from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Deque, Tuple, Any
from collections import deque
import logging
from logging.handlers import TimedRotatingFileHandler


class _ImportantOnlyFilter(logging.Filter):
    """Filter to keep only important records in file logs.

    Allows:
    - WARNING/ERROR/CRITICAL always
    - INFO records containing key trading events: ENTRY / EXIT / initialized / Resumed / Stopping / Started
    """

    KEYWORDS = (
        "ENTRY",
        "EXIT",
        "initialized",
        "Resumed",
        "Stopping",
        "Started",
    )

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        return any(k in msg for k in self.KEYWORDS)

from dotenv import load_dotenv

from pionex_futures_bot.clients import PionexClient
from pionex_futures_bot.common.strategy import (
    compute_breakout_signal,
    compute_sl_tp_prices,
    VolatilityState,
    update_volatility_state,
    compute_zscore_breakout,
    compute_atr_sl_tp,
)
from pionex_futures_bot.common.trade_logger import TradeLogger, TradeSummaryLogger
from pionex_futures_bot.common.state_store import StateStore


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
    last_exit_time: float = 0.0
    # Signal confirmation helpers (not persisted):
    confirm_streak: int = 0
    last_signal_side: Optional[str] = None
    entry_time: float = 0.0
    max_price_since_entry: float = 0.0


class SpotBot:
    def __init__(self, config_path: str = "config/config.json") -> None:
        log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, log_level_name, logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.log = logging.getLogger("spot_bot")

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        load_dotenv(override=False)
        api_key = os.getenv("API_KEY", "")
        api_secret = os.getenv("API_SECRET", "")

        self.client = PionexClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=self.config["base_url"],
            dry_run=bool(self.config.get("dry_run", True)),
        )

        # File logging into logs/ directory
        try:
            logs_dir = Path(self.config.get("log_dir", "logs"))
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / ("bot_dryrun.log" if bool(self.config.get("dry_run", True)) else "bot.log")
            fh = TimedRotatingFileHandler(str(log_file), when="midnight", backupCount=7, encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            fh.setLevel(logging.INFO)
            fh.addFilter(_ImportantOnlyFilter())
            # Avoid duplicate addition on hot-reload
            if not any(isinstance(h, TimedRotatingFileHandler) and getattr(h, 'baseFilename', '') == fh.baseFilename for h in self.log.handlers):
                self.log.addHandler(fh)
        except Exception:
            # If file handler fails, we continue with console logging only
            pass

        self.symbols = list(self.config["symbols"])  # copy
        # Optional: validate symbols against cached list if present
        try:
            from pathlib import Path as _P
            import json as _J
            sym_cache = _P("config/symbols.json")
            if sym_cache.exists():
                cache = _J.loads(sym_cache.read_text(encoding="utf-8"))
                cache_syms = {str(s.get("symbol", "")).upper() for s in cache.get("symbols", []) if isinstance(s, dict)}
                bad = [s for s in self.symbols if self.client._normalize_symbol(s) not in cache_syms]
                if bad:
                    self.log.warning("Some SPOT symbols may be invalid vs cache: %s", ",".join(bad))
        except Exception:
            pass
        self.leverage = int(self.config.get("leverage", 1))
        self.position_usdt = float(self.config["position_usdt"])  # per-position target notional
        self.max_open_trades = int(self.config["max_open_trades"])
        self.max_open_trades_per_symbol = int(self.config.get("max_open_trades_per_symbol", 1))
        self.breakout_change_percent = float(self.config["breakout_change_percent"])
        self.breakout_lookback_sec = int(self.config.get("breakout_lookback_sec", 60))
        self.breakout_confirm_ticks = int(self.config.get("breakout_confirm_ticks", 2))
        self.stop_loss_percent = float(self.config["stop_loss_percent"])
        self.take_profit_percent = float(self.config["take_profit_percent"])
        self.check_interval_sec = int(self.config["check_interval_sec"])
        self.idle_backoff_sec = int(self.config.get("idle_backoff_sec", max(10, self.check_interval_sec * 6)))
        self.cooldown_sec = int(self.config["cooldown_sec"])
        self.force_min_sell = bool(self.config.get("force_min_sell", True))
        self.sweep_dust_on_start = bool(self.config.get("sweep_dust_on_start", True))
        self.sweep_dust_heartbeat_sec = int(self.config.get("sweep_dust_heartbeat_sec", 900))
        self._last_sweep_ts: float = 0.0
        self.min_hold_sec = int(self.config.get("min_hold_sec", 10))
        self.exit_hysteresis_percent = float(self.config.get("exit_hysteresis_percent", 0.05))
        # Advanced mode
        self.signal_mode = str(self.config.get("mode", "contrarian")).lower()  # contrarian|momentum|auto
        self.k_threshold = float(self.config.get("z_threshold", 2.0))
        # Auto-mode switching based on recent stats
        self.auto_mode_enabled = bool(self.config.get("auto_mode_enabled", self.signal_mode == "auto"))
        self.auto_mode_window_trades = int(self.config.get("auto_mode_window_trades", 20))
        self.auto_switch_low_winrate = float(self.config.get("auto_switch_low_winrate", 45.0))
        self.auto_switch_high_winrate = float(self.config.get("auto_switch_high_winrate", 55.0))
        self.auto_mode_refresh_sec = int(self.config.get("auto_mode_refresh_sec", 300))
        self.z_threshold_contrarian = float(self.config.get("z_threshold_contrarian", self.k_threshold))
        self.z_threshold_momentum = float(self.config.get("z_threshold_momentum", max(2.0, self.k_threshold - 0.3)))
        self.ewm_lambda = float(self.config.get("ewm_lambda", 0.94))
        self.atr_window_sec = int(self.config.get("atr_window_sec", 300))
        self.alpha_sl = float(self.config.get("alpha_sl", 1.8))
        self.beta_tp = float(self.config.get("beta_tp", 2.6))
        # Trailing / pullback
        self.trailing_enabled = bool(self.config.get("trailing_enabled", True))
        self.trailing_activation_gain_percent = float(self.config.get("trailing_activation_gain_percent", 1.0))
        self.trailing_retrace_percent = float(self.config.get("trailing_retrace_percent", 0.20))
        self.trailing_atr_mult = float(self.config.get("trailing_atr_mult", 1.0))
        self.tp_pullback_confirm = bool(self.config.get("tp_pullback_confirm", True))
        self.tp_pullback_retrace_percent = float(self.config.get("tp_pullback_retrace_percent", 0.15))
        # Buy alignment to step to reduce sell dust
        self.buy_align_step = bool(self.config.get("buy_align_step", True))
        self.buy_align_bias_bps = float(self.config.get("buy_align_bias_bps", 5.0))
        # Risk control
        self.max_daily_loss_usdt = float(self.config.get("max_daily_loss_usdt", 0.0))  # 0 disables
        self.max_consecutive_losses = int(self.config.get("max_consecutive_losses", 0))  # 0 disables
        self.cooloff_sec = int(self.config.get("cooloff_sec", 0))
        self._day_pnl = 0.0
        self._consec_losses = 0
        self._cooloff_until = 0.0
        self._cooloff_reason: str = ""
        self.epsilon_pnl_usdt = float(self.config.get("epsilon_pnl_usdt", 0.05))
        self.epsilon_pnl_percent = float(self.config.get("epsilon_pnl_percent", 0.10))

        self.logger = TradeLogger(self.config.get("log_csv", "trades.csv"))
        self.summary_logger = TradeSummaryLogger(self.config.get("log_summary_csv", "logs/trades_summary.csv"))
        self.state_store = StateStore(self.config.get("state_file", "runtime_state.json"))
        self._states: Dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        self._open_trades_lock = threading.Lock()
        self._open_trades_count = 0
        self._symbol_open_count: Dict[str, int] = {s: 0 for s in self.symbols}
        # Per-symbol price history for lookback computations
        history_len = max(300, int(max(1, self.breakout_lookback_sec) / max(1, self.check_interval_sec)) * 5)
        self._price_history: Dict[str, Deque[Tuple[float, float]]] = {s: deque(maxlen=history_len) for s in self.symbols}
        # Volatility per symbol
        self._vol_state: Dict[str, VolatilityState] = {s: VolatilityState(ewm_var=0.0, window=deque(maxlen=300)) for s in self.symbols}
        # Track recent outcomes per symbol (for possible auto-regime)
        self._recent_outcomes: Dict[str, Deque[str]] = {s: deque(maxlen=20) for s in self.symbols}
        # Per-symbol mode cache for auto switching
        self._symbol_mode: Dict[str, str] = {s: ("contrarian" if self.signal_mode != "momentum" else "momentum") for s in self.symbols}
        self._last_mode_eval_ts: float = 0.0
        self._summary_csv_path: str = str(self.config.get("log_summary_csv", "logs/trades_summary.csv"))

    def _evaluate_auto_modes_from_csv(self) -> None:
        if not self.auto_mode_enabled:
            return
        now_ts = time.time()
        if (now_ts - self._last_mode_eval_ts) < max(30, self.auto_mode_refresh_sec):
            return
        self._last_mode_eval_ts = now_ts
        try:
            import csv
            from datetime import datetime, timedelta
            path = Path(self._summary_csv_path)
            if not path.exists():
                return
            cutoff = None  # by default use window by count
            # Load all rows and build per-symbol lists of last N trades
            per_sym: Dict[str, Deque[float]] = {s: deque(maxlen=self.auto_mode_window_trades) for s in self.symbols}
            with path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            # Iterate in reverse chronological order by exit_ts
            rows.sort(key=lambda r: (r.get("exit_ts") or ""))
            for row in rows:
                sym = (row.get("symbol") or "").strip()
                if sym not in per_sym:
                    continue
                try:
                    pnl = float(row.get("pnl_usdt") or 0.0)
                except Exception:
                    continue
                per_sym[sym].append(pnl)
            for sym, pnl_list in per_sym.items():
                if len(pnl_list) == 0:
                    continue
                n = len(pnl_list)
                wins = sum(1 for v in pnl_list if v > 0)
                win_rate = 100.0 * wins / n
                prev_mode = self._symbol_mode.get(sym, "contrarian")
                if win_rate < self.auto_switch_low_winrate:
                    self._symbol_mode[sym] = "momentum"
                elif win_rate > self.auto_switch_high_winrate:
                    self._symbol_mode[sym] = "contrarian"
                # Log only when changed
                if self._symbol_mode[sym] != prev_mode:
                    self.log.info("%s auto-mode switch: %s -> %s (win_rate=%.2f%% over %d trades)", sym, prev_mode, self._symbol_mode[sym], win_rate, n)
        except Exception as exc:
            self.log.debug("auto-mode eval error: %s", exc)

        # Load SPOT symbol trading rules (precision/min dump) from cache or API
        # Defensive init to avoid AttributeError if called before population
        self._spot_rules: Dict[str, Dict[str, Any]] = {}
        try:
            from pathlib import Path as _P
            import json as _J
            cache_paths = [
                _P("config/symbols_spot.json"),
                _P("config/symbols.json"),
            ]
            loaded = False
            for p in cache_paths:
                if p.exists():
                    blob = _J.loads(p.read_text(encoding="utf-8"))
                    arr = blob.get("symbols", []) if isinstance(blob, dict) else []
                    if isinstance(arr, list):
                        for item in arr:
                            if not isinstance(item, dict):
                                continue
                            sym = str(item.get("symbol", "")).upper()
                            if sym:
                                self._spot_rules[sym] = item
                        loaded = True
                        break
            if not loaded:
                # On-demand fetch only for configured symbols (keeps it light)
                resp = self.client.get_market_symbols(market_type="SPOT", symbols=[self.client._normalize_symbol(s) for s in self.symbols])
                if resp.ok and resp.data and isinstance(resp.data.get("symbols"), list):
                    for item in resp.data["symbols"]:
                        if isinstance(item, dict) and item.get("symbol"):
                            self._spot_rules[str(item["symbol"]).upper()] = item
        except Exception as _e:
            self.log.debug("Failed to load SPOT rules: %s", _e)

        # Resume state from previous run if available (supports cross-profile resume)
        try:
            # Primary state file
            persisted = self.state_store.load()
            if not isinstance(persisted, dict):
                persisted = {}
            # Also try alternative state files so we can resume when switching profiles
            alt_states: list[dict] = []
            try:
                primary_state_path = Path(self.config.get("state_file", "logs/runtime_state.json"))
                # Common alternates
                alternates = [
                    Path("logs/runtime_state.json"),
                    Path("logs/runtime_state_trending.json"),
                ]
                # Add derived alternate (swap between trending and default)
                if "trending" in str(primary_state_path):
                    alternates.insert(0, Path("logs/runtime_state.json"))
                else:
                    alternates.insert(0, Path("logs/runtime_state_trending.json"))
                # Load distinct existing files except the primary one
                seen = set([str(primary_state_path.resolve()) if primary_state_path.exists() else str(primary_state_path)])
                for p in alternates:
                    try:
                        if p.exists():
                            rp = str(p.resolve())
                            if rp in seen:
                                continue
                            seen.add(rp)
                            from pionex_futures_bot.common.state_store import StateStore as _SS
                            alt = _SS(p).load()
                            if isinstance(alt, dict):
                                alt_states.append(alt)
                                try:
                                    self.log.info("Alt state loaded: %s (keys=%d)", rp, len(alt.keys()))
                                except Exception:
                                    pass
                    except Exception:
                        continue
            except Exception:
                pass
            resumed_count = 0
            for sym, st in self._states.items():
                # Try multiple key variants to maximize resume compatibility
                key_variants = []
                try:
                    norm = self.client._normalize_symbol(sym)
                except Exception:
                    norm = sym
                key_variants.extend([sym, norm])
                try:
                    key_variants.append(sym.replace("_", ""))
                    key_variants.append(norm.replace("_", ""))
                except Exception:
                    pass
                ps = {}
                for k in key_variants:
                    if isinstance(persisted, dict) and k in persisted and isinstance(persisted[k], dict):
                        ps = persisted[k]
                        break
                if (not ps) and alt_states:
                    # Pull first match from alternates if present
                    for alt in alt_states:
                        found = None
                        for k in key_variants:
                            if k in alt and isinstance(alt[k], dict):
                                found = alt[k]
                                break
                        if found:
                            ps = found
                            break
                if isinstance(ps, dict):
                    st.in_position = bool(ps.get("in_position", False))
                    st.side = ps.get("side")
                    try:
                        st.quantity = float(ps.get("quantity", 0.0))
                        st.entry_price = float(ps.get("entry_price", 0.0))
                        st.stop_loss = float(ps.get("stop_loss", 0.0))
                        st.take_profit = float(ps.get("take_profit", 0.0))
                        st.last_exit_time = float(ps.get("last_exit_time", 0.0))
                        st.entry_time = float(ps.get("entry_time", 0.0))
                    except Exception:
                        pass
                    st.order_id = ps.get("order_id")
                    # Backfill entry_time if missing for an open position (pre-upgrade state)
                    if st.in_position and (not isinstance(ps.get("entry_time", None), (int, float)) or st.entry_time <= 0.0):
                        st.entry_time = time.time()
                        try:
                            self.state_store.update_symbol(
                                sym,
                                {
                                    "entry_time": st.entry_time,
                                },
                            )
                            self.log.debug("%s resume: backfilled entry_time", sym)
                        except Exception:
                            pass
                    if st.in_position:
                        resumed_count += 1
                        # Reflect resumed positions in counters to prevent over-opening
                        try:
                            with self._open_trades_lock:
                                self._open_trades_count += 1
                                self._symbol_open_count[sym] = self._symbol_open_count.get(sym, 0) + 1
                            self.log.info(
                                "%s resume: in_position side=%s qty=%.6f entry=%.8f sl=%.8f tp=%.8f",
                                sym,
                                st.side,
                                st.quantity,
                                st.entry_price,
                                st.stop_loss,
                                st.take_profit,
                            )
                        except Exception:
                            pass
            # Startup resume summary
            try:
                prim = str(primary_state_path)
                prim_keys = len(persisted.keys()) if isinstance(persisted, dict) else 0
                self.log.info("State resume | primary=%s (keys=%d) resumed=%d symbols", prim, prim_keys, resumed_count)
            except Exception:
                pass
            # Initialize open trades counter from resumed state
            self._open_trades_count = sum(1 for st in self._states.values() if st.in_position)
            for sym, st in self._states.items():
                self._symbol_open_count[sym] = 1 if st.in_position else 0
            if self._open_trades_count:
                self.log.info("Resumed %d open trade(s) from state store", self._open_trades_count)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("Failed to resume state: %s", exc)

        self.log.info(
            "SpotBot initialized | symbols=%s position_usdt=%s max_open_trades=%s interval=%ss cooldown=%ss dry_run=%s",
            ",".join(self.symbols),
            self.position_usdt,
            self.max_open_trades,
            self.check_interval_sec,
            self.cooldown_sec,
            bool(self.config.get("dry_run", True)),
        )
        self.log.info(
            "SpotBot params | breakout=±%.2f%% lookback=%ss confirm_ticks=%d min_hold=%ss hysteresis=%.2f%% force_min_sell=%s caps: per_symbol=%d",
            self.breakout_change_percent,
            self.breakout_lookback_sec,
            self.breakout_confirm_ticks,
            self.min_hold_sec,
            self.exit_hysteresis_percent,
            self.force_min_sell,
            self.max_open_trades_per_symbol,
        )

    def _format_duration(self, seconds: float) -> str:
        try:
            s = max(0.0, float(seconds))
            total = int(round(s))
            hours, rem = divmod(total, 3600)
            minutes, secs = divmod(rem, 60)
            if hours > 0:
                return f"{hours}h{minutes:02}m{secs:02}s"
            if minutes > 0:
                return f"{minutes}m{secs:02}s"
            return f"{s:.1f}s"
        except Exception:
            return f"{seconds}s"

    def _can_open_more(self) -> bool:
        with self._open_trades_lock:
            return self._open_trades_count < self.max_open_trades

    def _try_reserve_open_slot(self) -> bool:
        """Atomiquement, réserve un slot d'ouverture si disponible.
        Retourne True si réservé, False sinon.
        """
        with self._open_trades_lock:
            if self._open_trades_count < self.max_open_trades:
                self._open_trades_count += 1
                return True
            return False

    def _on_open(self) -> None:
        with self._open_trades_lock:
            self._open_trades_count += 1

    def _on_close(self) -> None:
        with self._open_trades_lock:
            if self._open_trades_count > 0:
                self._open_trades_count -= 1

    def _try_reserve_symbol_slot(self, symbol: str) -> bool:
        with self._open_trades_lock:
            current = self._symbol_open_count.get(symbol, 0)
            if current < self.max_open_trades_per_symbol:
                self._symbol_open_count[symbol] = current + 1
                return True
            return False

    def _release_symbol_slot(self, symbol: str) -> None:
        with self._open_trades_lock:
            current = self._symbol_open_count.get(symbol, 0)
            if current > 0:
                self._symbol_open_count[symbol] = current - 1

    def _round_quantity(self, quantity: float) -> float:
        return max(round(quantity, 6), 0.0)

    def _parse_spot_rules(self, symbol: str) -> Tuple[float, float, Optional[float]]:
        """Return (step, min_dump, max_dump) for MARKET SELL from cached rules.
        step is inferred from the decimals of minTradeDumping (or minTradeSize) when present.
        """
        norm = self.client._normalize_symbol(symbol)
        rules_map = getattr(self, "_spot_rules", {}) or {}
        rules = rules_map.get(norm) or {}
        min_dump_str = rules.get("minTradeDumping") or rules.get("minTradeSize")
        max_dump_str = rules.get("maxTradeDumping") or rules.get("maxTradeSize")
        # Default fine step
        step = 10 ** (-6)
        min_dump = 0.0
        max_dump: Optional[float] = None
        try:
            # basePrecision can constrain decimal places for base asset
            base_prec = rules.get("basePrecision")
            if isinstance(base_prec, (int, float)):
                try:
                    step = max(step, 10 ** (-int(base_prec)))
                except Exception:
                    pass
            if isinstance(min_dump_str, str) and min_dump_str.strip() != "":
                min_dump = float(min_dump_str)
                if "." in min_dump_str:
                    decimals = len(min_dump_str.split(".")[-1])
                else:
                    decimals = 0
                step = max(step, 10 ** (-decimals))
            if isinstance(max_dump_str, str) and max_dump_str.strip() != "":
                max_dump = float(max_dump_str)
        except Exception:
            pass
        return (step, min_dump, max_dump)

    def _sell_dust_if_any(self, symbol: str) -> None:
        try:
            free_bal = self._get_free_base_balance(symbol)
            step, min_dump, _ = self._parse_spot_rules(symbol)
            if free_bal >= max(min_dump, step):
                qty = self._normalize_spot_sell_quantity(symbol, free_bal, free_balance=free_bal, force_min_if_possible=True)
                if qty > 0:
                    try:
                        import uuid
                        cid = str(uuid.uuid4())
                    except Exception:
                        cid = None
                    resp = self.client.place_market_order(symbol=symbol, side="SELL", quantity=qty, client_order_id=cid)
                    if resp.ok:
                        self.log.info("%s dust sweep: sold %.8f", symbol, qty)
                    else:
                        self.log.warning("%s dust sweep failed: %s", symbol, getattr(resp, "error", None))
        except Exception as exc:
            self.log.debug("%s dust sweep error: %s", symbol, exc)

    def _get_free_base_balance(self, symbol: str) -> float:
        try:
            norm = self.client._normalize_symbol(symbol)
            base = norm.split("_")[0]
            resp = self.client.get_balances()
            if not resp.ok or not resp.data:
                return 0.0
            balances = resp.data.get("data", {}).get("balances", []) if isinstance(resp.data, dict) else []
            for b in balances:
                if isinstance(b, dict) and str(b.get("coin", "")).upper() == base.upper():
                    return float(b.get("free", 0.0))
        except Exception:
            return 0.0
        return 0.0

    def _get_free_quote_balance(self) -> float:
        try:
            resp = self.client.get_balances()
            if not resp.ok or not resp.data:
                return 0.0
            balances = resp.data.get("data", {}).get("balances", []) if isinstance(resp.data, dict) else []
            for b in balances:
                if isinstance(b, dict) and str(b.get("coin", "")).upper() == "USDT":
                    return float(b.get("free", 0.0))
        except Exception:
            return 0.0
        return 0.0

    def _parse_spot_buy_rules(self, symbol: str) -> Tuple[int, float]:
        """Return (amount_precision, min_amount_usdt) for MARKET BUY."""
        try:
            norm = self.client._normalize_symbol(symbol)
            rules = (getattr(self, "_spot_rules", {}) or {}).get(norm) or {}
            amount_precision = int(rules.get("amountPrecision", 2))
            min_amount_str = rules.get("minAmount")
            min_amount = float(min_amount_str) if isinstance(min_amount_str, str) and min_amount_str.strip() != "" else 0.0
            return (amount_precision, min_amount)
        except Exception:
            return (2, 0.0)

    def _normalize_spot_buy_amount(self, symbol: str, budget_usdt: float, price: float) -> float:
        """Compute a MARKET BUY amount that:
        - aligns the implied quantity to base step to reduce sell dust
        - respects amountPrecision and minAmount
        - caps to free USDT and applies a small negative bias
        Returns 0.0 if not feasible (e.g., below minAmount or no funds).
        """
        free_usdt = self._get_free_quote_balance()
        if free_usdt <= 0 or price <= 0:
            return 0.0
        # Reserve tiny buffer (fees/slippage)
        bias = max(0.0, self.buy_align_bias_bps) / 10000.0
        spend = min(budget_usdt, free_usdt) * (1.0 - bias)
        step, min_dump, _ = self._parse_spot_rules(symbol)
        # Align quantity to step
        qty_raw = spend / price
        if step > 0:
            import math
            qty_target = math.floor(qty_raw / step) * step
        else:
            qty_target = qty_raw
        # Ensure not below minimal sell size for future exit
        qty_target = max(qty_target, max(min_dump, step))
        amount_aligned = qty_target * price
        # Enforce amount precision and minAmount
        amount_precision, min_amount = self._parse_spot_buy_rules(symbol)
        try:
            factor = 10 ** int(amount_precision)
            amount_aligned = int(amount_aligned * factor) / factor
        except Exception:
            pass
        if amount_aligned < (min_amount or 0.0):
            # Try using exact minAmount if funds allow
            if free_usdt >= (min_amount or 0.0) > 0:
                amount_aligned = float(min_amount)
            else:
                return 0.0
        # Final cap by free balance
        amount_aligned = min(amount_aligned, free_usdt)
        return max(0.0, amount_aligned)

    def _normalize_spot_sell_quantity(self, symbol: str, quantity: float, *, free_balance: float, force_min_if_possible: bool) -> float:
        """Normalize sell size to exchange filters for SPOT market.

        Uses minTradeDumping as step and minimum for MARKET SELL, and maxTradeDumping as cap.
        Caps by free balance. If floored<min but free>=min and force_min_if_possible, returns min.
        If still <min, returns 0.0 (skip).
        """
        try:
            step, min_dump, max_dump = self._parse_spot_rules(symbol)
            # cap by free balance
            capped = min(quantity, max(free_balance, 0.0))
            # floor to step
            if step > 0:
                floored = (int(capped / step)) * step
            else:
                floored = capped
            # round to step decimals
            if step >= 1:
                floored = float(int(floored))
            else:
                import math
                decimals = int(round(-math.log10(step)))
                floored = round(floored, decimals)

            if floored < max(min_dump, 0.0):
                # if we can sell exactly min_dump within free balance and feature enabled
                if force_min_if_possible and free_balance >= min_dump and min_dump > 0:
                    floored = min_dump
                else:
                    return 0.0

            if max_dump is not None and floored > max_dump:
                floored = max_dump
            return max(floored, 0.0)
        except Exception:
            q = self._round_quantity(min(quantity, max(free_balance, 0.0)))
            return q if q > 0 else 0.0

    def _worker(self, symbol: str) -> None:
        state = self._states[symbol]
        threading.current_thread().name = f"{symbol}-spot"
        self.log.info("Worker started for %s", symbol)

        # Resume: omitted for brevity in this refactor; same as previous bot implementation
        # Initialize last price
        while state.last_price is None:
            resp = self.client.get_price(symbol)
            if resp.ok and resp.data and "price" in resp.data:
                state.last_price = float(resp.data["price"])  # type: ignore[arg-type]
                self.log.info("%s initial price set: %.8f", symbol, state.last_price)
            else:
                self.log.warning("%s price init failed: %s", symbol, getattr(resp, "error", None))
                time.sleep(1)

        tick = 0
        heartbeat_every = max(1, int(60 / max(1, self.check_interval_sec)))

        while True:
            if (not state.in_position) and (not self._can_open_more()):
                if tick % heartbeat_every == 0:
                    self.log.info("%s heartbeat: max_open_trades reached, skipping price fetch for %ss", symbol, self.idle_backoff_sec)
                time.sleep(self.idle_backoff_sec)
                tick += 1
                continue

            # Periodic dust sweep when not in position (optional)
            if (not state.in_position) and self.sweep_dust_on_start:
                now_ts = time.time()
                if (now_ts - self._last_sweep_ts) >= max(60, self.sweep_dust_heartbeat_sec):
                    self._sell_dust_if_any(symbol)
                    self._last_sweep_ts = now_ts

            price_resp = self.client.get_price(symbol)
            if not price_resp.ok or not price_resp.data or "price" not in price_resp.data:
                self.log.warning("%s price fetch failed: %s", symbol, getattr(price_resp, "error", None))
                time.sleep(self.check_interval_sec)
                tick += 1
                continue
            price = float(price_resp.data["price"])  # type: ignore[arg-type]

            now = time.time()

            if not state.in_position:
                # During cool-off, do not open new positions but keep managing existing ones
                if self._cooloff_until and now < self._cooloff_until:
                    state.last_price = price
                    if tick % heartbeat_every == 0:
                        self.log.info("%s heartbeat: cool-off active (%ds left), price=%.8f", symbol, int(self._cooloff_until - now), price)
                    time.sleep(self.check_interval_sec)
                    tick += 1
                    continue
                if state.last_exit_time and (now - state.last_exit_time) < self.cooldown_sec:
                    state.last_price = price
                    if tick % heartbeat_every == 0:
                        self.log.info("%s heartbeat: cooldown active, price=%.8f", symbol, price)
                    time.sleep(self.check_interval_sec)
                    tick += 1
                    continue

                if not self._can_open_more():
                    state.last_price = price
                    if tick % heartbeat_every == 0:
                        self.log.info("%s heartbeat: max_open_trades reached, price=%.8f", symbol, price)
                    time.sleep(self.check_interval_sec)
                    tick += 1
                    continue

                # Maintain price history and compute lookback delta
                hist = self._price_history[symbol]
                hist.append((now, price))
                threshold_time = now - self.breakout_lookback_sec
                old_price: Optional[float] = None
                for ts, px in reversed(hist):
                    if ts <= threshold_time:
                        old_price = px
                        break
                if old_price is None:
                    old_price = state.last_price if state.last_price is not None else price
                change_pct = (price - float(old_price)) / float(old_price) * 100.0
                # Update vol state with per-tick return (always update)
                ret_pct = (price - (state.last_price or price)) / (state.last_price or price) * 100.0
                self._vol_state[symbol] = update_volatility_state(state=self._vol_state[symbol], ret=ret_pct, lambda_ewm=self.ewm_lambda)

                # Signal by mode: z-score or legacy percent
                if self.signal_mode in ("contrarian", "momentum", "auto"):
                    # Auto-mode: refresh from CSV periodically and use per-symbol mode
                    if self.signal_mode == "auto":
                        self._evaluate_auto_modes_from_csv()
                    mode_use = (self._symbol_mode.get(symbol, "contrarian") if self.signal_mode == "auto" else self.signal_mode)
                    # Simple regime adapter (auto): if last 10 entries TP rate < 45% → momentum, >55% → contrarian
                    # Placeholder: keep as configured for now; can be extended with real stats collector
                    z_k = self.z_threshold_contrarian if mode_use == "contrarian" else self.z_threshold_momentum
                    sig = compute_zscore_breakout(
                        change_pct=change_pct,
                        vol_state=self._vol_state[symbol],
                        k_threshold=z_k,
                        mode=mode_use,
                    )
                    provisional_side = sig.side
                else:
                    provisional_side = None
                    if change_pct <= -self.breakout_change_percent:
                        provisional_side = "BUY"
                    elif change_pct >= self.breakout_change_percent:
                        provisional_side = "SELL"

                # Confirmation over N ticks
                if provisional_side is None:
                    state.confirm_streak = 0
                    state.last_signal_side = None
                else:
                    if state.last_signal_side == provisional_side:
                        state.confirm_streak += 1
                    else:
                        state.last_signal_side = provisional_side
                        state.confirm_streak = 1

                # Detailed per-tick diagnostics (visible with LOG_LEVEL=DEBUG)
                self.log.debug(
                    "%s price=%.8f ref=%.8f delta=%.4f%% thresh=±%.2f%% lookback=%ss streak=%d side=%s",
                    symbol,
                    price,
                    float(old_price),
                    change_pct,
                    self.breakout_change_percent,
                    self.breakout_lookback_sec,
                    state.confirm_streak,
                    provisional_side,
                )

                should_enter = provisional_side is not None and state.confirm_streak >= self.breakout_confirm_ticks
                # For SPOT, only BUY opens a position. SELL is handled by exit logic.
                if should_enter and provisional_side == "BUY":
                    # Per-symbol cap first
                    if not self._try_reserve_symbol_slot(symbol):
                        state.last_price = price
                        if tick % heartbeat_every == 0:
                            self.log.info("%s heartbeat: per-symbol cap reached (%d)", symbol, self.max_open_trades_per_symbol)
                        time.sleep(self.check_interval_sec)
                        tick += 1
                        continue
                    # Double garde: si le plafond global est atteint entre-temps, abandonner l'entrée
                    if not self._try_reserve_open_slot():
                        # Libère la réservation par symbole
                        self._release_symbol_slot(symbol)
                        state.last_price = price
                        if tick % heartbeat_every == 0:
                            self.log.info("%s heartbeat: slot unavailable at entry time (max_open_trades)", symbol)
                        time.sleep(self.check_interval_sec)
                        tick += 1
                        continue
                    quantity = self._round_quantity(self.position_usdt / price)
                    if quantity <= 0:
                        # Libère le slot réservé inutilement
                        self._on_close()
                        self._release_symbol_slot(symbol)
                        state.last_price = price
                        time.sleep(self.check_interval_sec)
                        tick += 1
                        continue
                    self.log.info("%s ENTRY signal side=%s qty=%.6f price=%.8f", symbol, provisional_side, quantity, price)
                    client_id = None
                    try:
                        import uuid
                        client_id = str(uuid.uuid4())
                    except Exception:
                        client_id = None
                    if provisional_side == "BUY":
                        # Check minAmount from rules (fallback to position_usdt)
                        min_amount = None
                        try:
                            rules = self._spot_rules.get(self.client._normalize_symbol(symbol)) or {}
                            if rules.get("minAmount") is not None:
                                min_amount = float(rules.get("minAmount"))
                        except Exception:
                            min_amount = None
                        # Compute a safe aligned amount
                        buy_amount = self._normalize_spot_buy_amount(symbol, max(self.position_usdt, min_amount or 0.0), price)
                        if buy_amount <= 0:
                            self.log.warning("%s ENTRY skipped: cannot meet minAmount or insufficient USDT", symbol)
                            # Free reserved slots
                            self._on_close()
                            self._release_symbol_slot(symbol)
                            state.last_price = price
                            time.sleep(self.check_interval_sec)
                            tick += 1
                            continue
                        order = self.client.place_market_order(symbol=symbol, side=provisional_side, amount=buy_amount, client_order_id=client_id)
                    else:
                        order = self.client.place_market_order(symbol=symbol, side=provisional_side, quantity=quantity, client_order_id=client_id)
                    if not order.ok:
                        self.log.error("%s ENTRY failed: %s", symbol, order.error)
                        # Libère le slot réservé car l'ordre a échoué
                        self._on_close()
                        self._release_symbol_slot(symbol)
                    else:
                        # Determine actual entry quantity and price using fills if possible
                        entry_price = price
                        entry_qty = quantity if provisional_side == "SELL" else self._round_quantity(self.position_usdt / price)
                        try:
                            # In live mode, refine using fills if available
                            if not bool(self.config.get("dry_run", True)):
                                # Prefer fills by the just-created order id if available
                                created_order_id = (order.data or {}).get("orderId") if hasattr(order, "data") else None
                                if created_order_id:
                                    fills_resp = self.client.get_fills_by_order_id(symbol, created_order_id)
                                    if fills_resp.ok and fills_resp.data:
                                        data = fills_resp.data.get("data") if isinstance(fills_resp.data, dict) else None
                                        fills = data.get("fills") if isinstance(data, dict) else None
                                        if isinstance(fills, list) and fills:
                                            qty_sum = 0.0
                                            notional = 0.0
                                            for f in fills:
                                                try:
                                                    qf = float(f.get("size", 0.0))
                                                    pf = float(f.get("price", 0.0))
                                                except Exception:
                                                    qf = 0.0
                                                    pf = 0.0
                                                qty_sum += qf
                                                notional += qf * pf
                                            if qty_sum > 0:
                                                entry_qty = self._round_quantity(qty_sum)
                                                entry_price = notional / qty_sum
                                else:
                                    inferred = self.client.infer_position_from_fills(symbol)
                                    if inferred.get("in_position") and inferred.get("side") == provisional_side:
                                        q = float(inferred.get("quantity", entry_qty))
                                        px = float(inferred.get("entry_price", entry_price))
                                        if q > 0:
                                            entry_qty = self._round_quantity(q)
                                        if px > 0:
                                            entry_price = px
                        except Exception:
                            pass

                        # ATR-like absolute move from price history in atr_window_sec
                        atr_window = max(2, int(self.atr_window_sec / max(1, self.check_interval_sec)))
                        diffs = []
                        try:
                            hist_list = list(self._price_history[symbol])
                            for i in range(max(1, len(hist_list) - atr_window), len(hist_list)):
                                if i > 0:
                                    diffs.append(abs(hist_list[i][1] - hist_list[i - 1][1]))
                            atr_abs = sum(diffs) / len(diffs) if diffs else entry_price * (self.stop_loss_percent / 100.0)
                        except Exception:
                            atr_abs = entry_price * (self.stop_loss_percent / 100.0)
                        sl, tp = compute_atr_sl_tp(
                            entry_price=entry_price,
                            side=provisional_side,  # type: ignore[arg-type]
                            atr_abs=atr_abs,
                            alpha_sl=self.alpha_sl,
                            beta_tp=self.beta_tp,
                        )
                        state.in_position = True
                        state.side = provisional_side
                        state.quantity = entry_qty
                        state.entry_price = entry_price
                        state.stop_loss = sl
                        state.take_profit = tp
                        state.order_id = (order.data or {}).get("orderId") if hasattr(order, "data") else None
                        state.entry_time = time.time()
                        state.max_price_since_entry = entry_price
                        state.confirm_streak = 0
                        state.last_signal_side = None
                        # Le slot global et le slot symbole sont déjà réservés, ne pas ré-incrémenter
                        # Persist and log
                        self.state_store.update_symbol(
                            symbol,
                            {
                                "in_position": True,
                                "side": state.side,
                                "quantity": state.quantity,
                                "entry_price": state.entry_price,
                                "stop_loss": state.stop_loss,
                                "take_profit": state.take_profit,
                                "order_id": state.order_id,
                                "last_exit_time": state.last_exit_time,
                                "entry_time": state.entry_time,
                            },
                        )
                        self.log.info(
                            "%s ENTRY set: entry=%.8f qty=%.6f sl=%.8f tp=%.8f min_hold=%ss hysteresis=%.2f%%",
                            symbol,
                            state.entry_price,
                            state.quantity,
                            state.stop_loss,
                            state.take_profit,
                            self.min_hold_sec,
                            self.exit_hysteresis_percent,
                        )
                        self.logger.log(
                            event="ENTRY",
                            symbol=symbol,
                            side=state.side,
                            quantity=state.quantity,
                            price=state.entry_price,
                            stop_loss=state.stop_loss,
                            take_profit=state.take_profit,
                            order_id=state.order_id,
                            reason="breakout",
                        )
                state.last_price = price
                time.sleep(self.check_interval_sec)
                tick += 1
                continue

            # Always update volatility state while open
            try:
                ret_pct_open = (price - (state.last_price or price)) / (state.last_price or price) * 100.0
                self._vol_state[symbol] = update_volatility_state(state=self._vol_state[symbol], ret=ret_pct_open, lambda_ewm=self.ewm_lambda)
            except Exception:
                pass
            # Manage open position: check SL/TP and exit if hit
            state.last_price = price
            exit_reason: Optional[str] = None
            if state.side == "BUY":
                # Apply hysteresis and min hold using the same 'now' as the rest of the loop
                elapsed = (now - state.entry_time) if (state.entry_time and state.entry_time > 0.0) else 0.0
                if elapsed >= self.min_hold_sec:
                    sl_trigger = state.stop_loss * (1.0 - self.exit_hysteresis_percent / 100.0)
                    tp_trigger = state.take_profit * (1.0 + self.exit_hysteresis_percent / 100.0)
                else:
                    sl_trigger = 0.0  # disable
                    tp_trigger = float("inf")  # disable
                # Per-tick debug of exit evaluation
                hit_sl_dbg = price <= sl_trigger
                hit_tp_dbg = price >= tp_trigger
                self.log.debug(
                    "%s open: price=%.8f entry=%.8f sl=%.8f tp=%.8f sl_trig=%.8f tp_trig=%.8f hold=%s/%s hit_sl=%s hit_tp=%s",
                    symbol,
                    price,
                    state.entry_price,
                    state.stop_loss,
                    state.take_profit,
                    sl_trigger,
                    tp_trigger,
                    self._format_duration(elapsed),
                    self._format_duration(float(self.min_hold_sec)),
                    hit_sl_dbg,
                    hit_tp_dbg,
                )
                # Track max price since entry
                try:
                    if price > 0:
                        state.max_price_since_entry = max(state.max_price_since_entry or state.entry_price, price)
                except Exception:
                    pass
                # Optional trailing/pullback logic
                if self.trailing_enabled and elapsed >= self.min_hold_sec and (state.max_price_since_entry > state.entry_price):
                    gain_pct_from_entry = (state.max_price_since_entry - state.entry_price) / state.entry_price * 100.0
                    if gain_pct_from_entry >= self.trailing_activation_gain_percent:
                        # Compute ATR-like absolute
                        atr_window = max(2, int(self.atr_window_sec / max(1, self.check_interval_sec)))
                        diffs = []
                        try:
                            hist_list = list(self._price_history[symbol])
                            for i in range(max(1, len(hist_list) - atr_window), len(hist_list)):
                                if i > 0:
                                    diffs.append(abs(hist_list[i][1] - hist_list[i - 1][1]))
                            atr_abs_cur = (sum(diffs) / len(diffs)) if diffs else (state.entry_price * (self.stop_loss_percent / 100.0))
                        except Exception:
                            atr_abs_cur = state.entry_price * (self.stop_loss_percent / 100.0)
                        trailing_stop_pullback = state.max_price_since_entry * (1.0 - self.trailing_retrace_percent / 100.0)
                        trailing_stop_atr = state.max_price_since_entry - self.trailing_atr_mult * atr_abs_cur
                        trailing_stop = max(trailing_stop_pullback, trailing_stop_atr)
                        if price <= trailing_stop and exit_reason is None:
                            exit_reason = "TRAIL"
                            self.log.info(
                                "%s TRAIL trigger: max=%.8f trail=%.8f price=%.8f gain=%.4f%%",
                                symbol,
                                state.max_price_since_entry,
                                trailing_stop,
                                price,
                                gain_pct_from_entry,
                            )
                if price <= sl_trigger:
                    exit_reason = "SL"
                elif price >= tp_trigger:
                    if self.tp_pullback_confirm and (state.max_price_since_entry > 0):
                        retrace_pct = (state.max_price_since_entry - price) / state.max_price_since_entry * 100.0
                        if retrace_pct >= self.tp_pullback_retrace_percent:
                            exit_reason = "TP"
                        else:
                            # wait for pullback confirmation
                            pass
                    else:
                        exit_reason = "TP"
            elif state.side == "SELL":
                if price >= state.stop_loss:
                    exit_reason = "SL"
                elif price <= state.take_profit:
                    exit_reason = "TP"

            # Periodic debug while managing open position
            if tick % heartbeat_every == 0:
                try:
                    if state.side == "BUY":
                        dist_sl = price - state.stop_loss
                        dist_tp = state.take_profit - price
                    else:
                        dist_sl = state.stop_loss - price
                        dist_tp = price - state.take_profit
                    self.log.debug(
                        "%s manage: side=%s price=%.8f sl=%.8f tp=%.8f dSL=%.8f dTP=%.8f",
                        symbol,
                        state.side,
                        price,
                        state.stop_loss,
                        state.take_profit,
                        dist_sl,
                        dist_tp,
                    )
                except Exception:
                    pass

            if exit_reason is not None:
                self.log.info("%s EXIT trigger: reason=%s price=%.8f side=%s", symbol, exit_reason, price, state.side)
                free_bal = self._get_free_base_balance(symbol)
                step, min_dump, max_dump = self._parse_spot_rules(symbol)
                sell_qty = self._normalize_spot_sell_quantity(symbol, state.quantity, free_balance=free_bal, force_min_if_possible=self.force_min_sell)
                if sell_qty <= 0:
                    self.log.error("%s EXIT %s skipped: qty below rules or balance (qty=%.8f free=%.8f)", symbol, exit_reason, state.quantity, free_bal)
                    time.sleep(self.check_interval_sec)
                    tick += 1
                    continue
                self.log.debug(
                    "%s EXIT normalize: req_qty=%.8f free=%.8f -> sell_qty=%.8f step=%.g min=%.8f max=%s",
                    symbol,
                    state.quantity,
                    free_bal,
                    sell_qty,
                    step,
                    min_dump,
                    ("%.8f" % max_dump) if (max_dump is not None) else "None",
                )
                close_resp = self.client.close_position(symbol=symbol, side=state.side or "BUY", quantity=sell_qty)
                if not close_resp.ok:
                    self.log.error("%s EXIT %s failed: %s", symbol, exit_reason, close_resp.error)
                else:
                    pnl = 0.0
                    try:
                        if (state.side or "BUY") == "BUY":
                            pnl = (price - state.entry_price) * state.quantity
                        else:
                            pnl = (state.entry_price - price) * state.quantity
                        # Apply epsilon threshold to ignore dust-level residuals
                        try:
                            pnl_pct_abs = abs((price - state.entry_price) / state.entry_price * 100.0)
                            if abs(pnl) < self.epsilon_pnl_usdt and pnl_pct_abs < self.epsilon_pnl_percent:
                                pnl = 0.0
                        except Exception:
                            pass
                    except Exception:
                        pnl = 0.0

                    self.logger.log(
                        event=f"EXIT_{exit_reason}",
                        symbol=symbol,
                        side=state.side,
                        quantity=state.quantity,
                        price=price,
                        order_id=(close_resp.data or {}).get("orderId") if hasattr(close_resp, "data") else None,
                        pnl=pnl,
                        reason=exit_reason,
                    )
                    # Summarize trade for analysis
                    try:
                        pnl_percent = ((price - state.entry_price) / state.entry_price * 100.0) if (state.side == "BUY") else ((state.entry_price - price) / state.entry_price * 100.0)
                        # Infer executed and residual qty from balances and rules
                        executed_qty = state.quantity
                        residual_qty = 0.0
                        try:
                            free_bal = self._get_free_base_balance(symbol)
                            # residual approximated as balance post-exit (if side BUY) below precision step
                            if state.side == "BUY":
                                step, _, _ = self._parse_spot_rules(symbol)
                                # Estimate expected remaining dust after sell
                                residual_qty = max(0.0, round(free_bal % max(step, 1e-12), 12))
                        except Exception:
                            residual_qty = 0.0
                        self.summary_logger.log_result(
                            symbol=symbol,
                            side=state.side,
                            quantity=state.quantity,
                            executed_qty=executed_qty,
                            residual_qty=residual_qty,
                            entry_price=state.entry_price,
                            exit_price=price,
                            entry_time=state.entry_time,
                            exit_time=time.time(),
                            pnl_usdt=pnl,
                            pnl_percent=pnl_percent,
                            exit_reason=exit_reason,
                            meta={
                                "mode": self.signal_mode,
                                "z_threshold": self.k_threshold,
                                "alpha_sl": self.alpha_sl,
                                "beta_tp": self.beta_tp,
                                "atr_window_sec": self.atr_window_sec,
                                "breakout_change_percent": self.breakout_change_percent,
                                "breakout_lookback_sec": self.breakout_lookback_sec,
                                "breakout_confirm_ticks": self.breakout_confirm_ticks,
                            },
                        )
                    except Exception:
                        pass
                    # Update daily loss and streaks
                    try:
                        self._day_pnl += pnl
                        self._recent_outcomes[symbol].append("WIN" if pnl > 0 else "LOSS")
                        if pnl >= 0:
                            self._consec_losses = 0
                        else:
                            self._consec_losses += 1
                        # Apply caps
                        if self.max_daily_loss_usdt and self._day_pnl <= -abs(self.max_daily_loss_usdt):
                            self._cooloff_until = time.time() + max(self.cooloff_sec, 1800)
                            self._cooloff_reason = "daily_loss"
                            dur = int(self._cooloff_until - time.time())
                            self.log.warning("Daily loss cap reached: entering cool-off for %ss", dur)
                            self.log.info(
                                "Cool-off started: reason=%s duration=%ds day_pnl=%.2f consec_losses=%d",
                                self._cooloff_reason,
                                dur,
                                self._day_pnl,
                                self._consec_losses,
                            )
                        if self.max_consecutive_losses and self._consec_losses >= self.max_consecutive_losses:
                            self._cooloff_until = time.time() + max(self.cooloff_sec, 900)
                            self._cooloff_reason = "consec_losses"
                            dur = int(self._cooloff_until - time.time())
                            self.log.warning("Consecutive losses cap reached: entering cool-off for %ss", dur)
                            self.log.info(
                                "Cool-off started: reason=%s duration=%ds day_pnl=%.2f consec_losses=%d",
                                self._cooloff_reason,
                                dur,
                                self._day_pnl,
                                self._consec_losses,
                            )
                    except Exception:
                        pass
                    # Clear persistent state and mark cooldown
                    state.in_position = False
                    state.side = None
                    state.quantity = 0.0
                    state.entry_price = 0.0
                    state.stop_loss = 0.0
                    state.take_profit = 0.0
                    state.order_id = None
                    state.last_exit_time = time.time()
                    state.entry_time = 0.0
                    self._on_close()
                    self._release_symbol_slot(symbol)
                    self.state_store.clear_symbol(symbol)

            time.sleep(self.check_interval_sec)
            tick += 1

    def run(self) -> None:
        threads = []
        for symbol in self.symbols:
            t = threading.Thread(target=self._worker, args=(symbol,), daemon=True)
            t.start()
            threads.append(t)
        self.log.info("SpotBot running with %d worker(s)", len(threads))
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            self.log.info("Stopping SpotBot...")


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent.parent
    os.chdir(project_dir)
    bot = SpotBot()
    bot.run()


