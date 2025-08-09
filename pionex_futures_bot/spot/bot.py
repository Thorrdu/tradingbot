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

from dotenv import load_dotenv

from pionex_futures_bot.clients import PionexClient
from pionex_futures_bot.common.strategy import compute_breakout_signal, compute_sl_tp_prices
from pionex_futures_bot.common.trade_logger import TradeLogger
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
        self.min_hold_sec = int(self.config.get("min_hold_sec", 10))
        self.exit_hysteresis_percent = float(self.config.get("exit_hysteresis_percent", 0.05))

        self.logger = TradeLogger(self.config.get("log_csv", "trades.csv"))
        self.state_store = StateStore(self.config.get("state_file", "runtime_state.json"))
        self._states: Dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        self._open_trades_lock = threading.Lock()
        self._open_trades_count = 0
        self._symbol_open_count: Dict[str, int] = {s: 0 for s in self.symbols}
        # Per-symbol price history for lookback computations
        history_len = max(300, int(max(1, self.breakout_lookback_sec) / max(1, self.check_interval_sec)) * 5)
        self._price_history: Dict[str, Deque[Tuple[float, float]]] = {s: deque(maxlen=history_len) for s in self.symbols}

        # Load SPOT symbol trading rules (precision/min dump) from cache or API
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

        # Resume state from previous run if available
        try:
            persisted = self.state_store.load()
            for sym, st in self._states.items():
                ps = persisted.get(sym, {}) if isinstance(persisted, dict) else {}
                if isinstance(ps, dict):
                    st.in_position = bool(ps.get("in_position", False))
                    st.side = ps.get("side")
                    try:
                        st.quantity = float(ps.get("quantity", 0.0))
                        st.entry_price = float(ps.get("entry_price", 0.0))
                        st.stop_loss = float(ps.get("stop_loss", 0.0))
                        st.take_profit = float(ps.get("take_profit", 0.0))
                        st.last_exit_time = float(ps.get("last_exit_time", 0.0))
                    except Exception:
                        pass
                    st.order_id = ps.get("order_id")
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
        rules = self._spot_rules.get(norm) or {}
        min_dump_str = rules.get("minTradeDumping") or rules.get("minTradeSize")
        max_dump_str = rules.get("maxTradeDumping") or rules.get("maxTradeSize")
        step = 10 ** (-6)
        min_dump = 0.0
        max_dump: Optional[float] = None
        try:
            if isinstance(min_dump_str, str) and min_dump_str.strip() != "":
                min_dump = float(min_dump_str)
                if "." in min_dump_str:
                    decimals = len(min_dump_str.split(".")[-1])
                else:
                    decimals = 0
                step = 10 ** (-decimals)
            if isinstance(max_dump_str, str) and max_dump_str.strip() != "":
                max_dump = float(max_dump_str)
        except Exception:
            pass
        return (step, min_dump, max_dump)

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

            price_resp = self.client.get_price(symbol)
            if not price_resp.ok or not price_resp.data or "price" not in price_resp.data:
                self.log.warning("%s price fetch failed: %s", symbol, getattr(price_resp, "error", None))
                time.sleep(self.check_interval_sec)
                tick += 1
                continue
            price = float(price_resp.data["price"])  # type: ignore[arg-type]

            now = time.time()

            if not state.in_position:
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

                # Contrarian breakout side based on lookback
                provisional_side: Optional[str] = None
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
                    if provisional_side == "BUY":
                        order = self.client.place_market_order(symbol=symbol, side=provisional_side, amount=self.position_usdt)
                    else:
                        order = self.client.place_market_order(symbol=symbol, side=provisional_side, quantity=quantity)
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

                        sl, tp = compute_sl_tp_prices(
                            entry_price=entry_price,
                            side=provisional_side,  # type: ignore[arg-type]
                            stop_loss_percent=self.stop_loss_percent,
                            take_profit_percent=self.take_profit_percent,
                        )
                        state.in_position = True
                        state.side = provisional_side
                        state.quantity = entry_qty
                        state.entry_price = entry_price
                        state.stop_loss = sl
                        state.take_profit = tp
                        state.order_id = (order.data or {}).get("orderId") if hasattr(order, "data") else None
                        state.entry_time = time.time()
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

            # Manage open position: check SL/TP and exit if hit
            state.last_price = price
            exit_reason: Optional[str] = None
            if state.side == "BUY":
                # Apply hysteresis and min hold
                if (time.time() - state.entry_time) >= self.min_hold_sec:
                    sl_trigger = state.stop_loss * (1.0 - self.exit_hysteresis_percent / 100.0)
                    tp_trigger = state.take_profit * (1.0 + self.exit_hysteresis_percent / 100.0)
                else:
                    sl_trigger = 0.0  # disable
                    tp_trigger = float("inf")  # disable
                # Per-tick debug of exit evaluation
                elapsed = time.time() - (state.entry_time or 0.0)
                hit_sl_dbg = price <= sl_trigger
                hit_tp_dbg = price >= tp_trigger
                self.log.debug(
                    "%s open: price=%.8f entry=%.8f sl=%.8f tp=%.8f sl_trig=%.8f tp_trig=%.8f hold=%.1fs/%ss hit_sl=%s hit_tp=%s",
                    symbol,
                    price,
                    state.entry_price,
                    state.stop_loss,
                    state.take_profit,
                    sl_trigger,
                    tp_trigger,
                    elapsed,
                    self.min_hold_sec,
                    hit_sl_dbg,
                    hit_tp_dbg,
                )
                if price <= sl_trigger:
                    exit_reason = "SL"
                elif price >= tp_trigger:
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
                    # Clear persistent state and mark cooldown
                    state.in_position = False
                    state.side = None
                    state.quantity = 0.0
                    state.entry_price = 0.0
                    state.stop_loss = 0.0
                    state.take_profit = 0.0
                    state.order_id = None
                    state.last_exit_time = time.time()
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


