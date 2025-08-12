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
        # Logging minimal
        self.log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        import logging
        logging.basicConfig(level=getattr(logging, self.log_level_name, logging.INFO),
                            format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
        self.log = logging.getLogger("spot2")

        # Client API
        self.client = PionexClient(api_key=os.getenv("API_KEY", ""),
                                   api_secret=os.getenv("API_SECRET", ""),
                                   base_url=self.config.get("base_url", os.getenv("PIONEX_BASE_URL", "https://api.pionex.com")),
                                   dry_run=bool(self.config.get("dry_run", True)))

        # Execution layer
        self.exec = ExecutionLayer(
            self.client,
            prefer_maker=bool(self.config.get("prefer_maker", True)),
            maker_offset_bps=float(self.config.get("maker_offset_bps", 2.0)),
            entry_limit_timeout_sec=int(self.config.get("entry_limit_timeout_sec", 3)),
            exit_limit_timeout_sec=int(self.config.get("exit_limit_timeout_sec", 2)),
        )

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

        # State
        self._states: Dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        from collections import deque as _dq
        self._vol_state: Dict[str, VolatilityState] = {s: VolatilityState(ewm_var=0.0, window=_dq(maxlen=300)) for s in self.symbols}
        self._z_hist: Dict[str, ZScoreHistory] = {s: ZScoreHistory() for s in self.symbols}
        # Chemins dédiés à spot2
        self.state_store = StateStore(self.config.get("state_file", "spot2/logs/runtime_state.json"))
        self.logger = TradeLogger(self.config.get("log_csv", "spot2/logs/trades.csv"))
        self.summary_logger = TradeSummaryLogger(self.config.get("summary_csv", "spot2/logs/trades_summary.csv"))

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
            r = self.client.get_price(symbol)
            if not r.ok or not r.data or "price" not in r.data:
                time.sleep(self.check_interval_sec)
                continue
            price = float(r.data["price"])  # type: ignore[arg-type]
            now = time.time()
            price_hist.append((now, price))
            cutoff = now - self.breakout_lookback_sec
            ref = price
            for ts, px in reversed(price_hist):
                if ts <= cutoff:
                    ref = px
                    break
            change_pct = (price - ref) / ref * 100.0
            # update vol and z history
            ret_pct = (price - (st.last_price or price)) / (st.last_price or price) * 100.0
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
            if should_enter and not st.in_position:
                # Place maker-preferred entry
                amt = self.position_usdt
                pre_free = self._get_free_base_balance(symbol)
                resp = self.exec.place_entry(symbol=symbol, price_hint=price, amount_usdt=amt, client_order_id=None)
                if resp.get("ok"):
                    st.in_position = True
                    st.side = "BUY"
                    st.entry_price = price
                    st.quantity = max(0.0, amt / price)
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
                                        qsum = 0.0; notional = 0.0
                                        for f in arr:
                                            try:
                                                qf = float(f.get("size", 0.0)); pf = float(f.get("price", 0.0))
                                            except Exception:
                                                qf = 0.0; pf = 0.0
                                            qsum += qf; notional += qf * pf
                                        if qsum > 0:
                                            st.quantity = qsum
                                            st.entry_price = (notional / qsum) if notional > 0 else st.entry_price
                                            self.state_store.update_symbol(symbol, {"quantity": st.quantity, "entry_price": st.entry_price})
                        # Ajustement via delta de balance (couvre résidus/fees)
                        post_free = self._get_free_base_balance(symbol)
                        delta_q = max(0.0, post_free - pre_free)
                        if delta_q > 0 and abs(delta_q - st.quantity) > 1e-12:
                            self.log.info("%s ENTRY balance adjust: qty %.6f -> %.6f (delta=%+.6f)", symbol, st.quantity, delta_q, delta_q - st.quantity)
                            st.quantity = delta_q
                            self.state_store.update_symbol(symbol, {"quantity": st.quantity})
                    except Exception:
                        pass
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
                sl_trig = sl_px * (1.0 - hysteresis / 100.0) if elapsed >= min_hold else 0.0
                tp_trig = tp_px * (1.0 + hysteresis / 100.0) if elapsed >= min_hold else float("inf")
                exit_reason = None
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
                    exit_reason = "SL"
                    pre_free = self._get_free_base_balance(symbol)
                    exit_resp = self.exec.place_exit_market(symbol=symbol, side="BUY", quantity=st.quantity)
                elif price >= tp_trig:
                    # TP: maker LIMIT si activé, sinon MARKET
                    exit_reason = "TP"
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
                            if price <= trailing_stop:
                                exit_reason = "TRAIL"
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
                    self.logger.log(event=f"EXIT_{exit_reason}", symbol=symbol, side=st.side, quantity=st.quantity, price=price, entry_price=st.entry_price, exit_price=price, pnl=pnl, pnl_percent=pnl_percent, reason=exit_reason)
                    self.log.info("%s EXIT %s qty=%.6f price=%.6f pnl=%.6f (%.2f%%)", symbol, exit_reason, st.quantity, price, pnl, pnl_percent)
                    self.summary_logger.log_result(symbol=symbol, side=st.side, quantity=st.quantity, executed_qty=executed_qty, residual_qty=residual_qty, entry_price=st.entry_price, exit_price=price, entry_time=st.entry_time, exit_time=now, pnl_usdt=pnl, pnl_percent=pnl_percent, exit_reason=exit_reason)
                    st.in_position = False
                    st.side = None
                    st.quantity = 0.0
                    st.entry_price = 0.0
                    st.entry_time = 0.0
                    st.max_price_since_entry = 0.0
                    self.state_store.clear_symbol(symbol)
            st.last_price = price
            time.sleep(self.check_interval_sec)


