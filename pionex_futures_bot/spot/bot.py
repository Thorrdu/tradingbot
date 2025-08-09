from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Deque, Tuple
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
        self.leverage = int(self.config.get("leverage", 1))
        self.position_usdt = float(self.config["position_usdt"])  # per-position target notional
        self.max_open_trades = int(self.config["max_open_trades"])
        self.breakout_change_percent = float(self.config["breakout_change_percent"])
        self.breakout_lookback_sec = int(self.config.get("breakout_lookback_sec", 60))
        self.breakout_confirm_ticks = int(self.config.get("breakout_confirm_ticks", 2))
        self.stop_loss_percent = float(self.config["stop_loss_percent"])
        self.take_profit_percent = float(self.config["take_profit_percent"])
        self.check_interval_sec = int(self.config["check_interval_sec"])
        self.idle_backoff_sec = int(self.config.get("idle_backoff_sec", max(10, self.check_interval_sec * 6)))
        self.cooldown_sec = int(self.config["cooldown_sec"])

        self.logger = TradeLogger(self.config.get("log_csv", "trades.csv"))
        self.state_store = StateStore(self.config.get("state_file", "runtime_state.json"))
        self._states: Dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        self._open_trades_lock = threading.Lock()
        self._open_trades_count = 0
        # Per-symbol price history for lookback computations
        history_len = max(300, int(max(1, self.breakout_lookback_sec) / max(1, self.check_interval_sec)) * 5)
        self._price_history: Dict[str, Deque[Tuple[float, float]]] = {s: deque(maxlen=history_len) for s in self.symbols}

        self.log.info(
            "SpotBot initialized | symbols=%s position_usdt=%s max_open_trades=%s interval=%ss cooldown=%ss dry_run=%s",
            ",".join(self.symbols),
            self.position_usdt,
            self.max_open_trades,
            self.check_interval_sec,
            self.cooldown_sec,
            bool(self.config.get("dry_run", True)),
        )

    def _can_open_more(self) -> bool:
        with self._open_trades_lock:
            return self._open_trades_count < self.max_open_trades

    def _on_open(self) -> None:
        with self._open_trades_lock:
            self._open_trades_count += 1

    def _on_close(self) -> None:
        with self._open_trades_lock:
            if self._open_trades_count > 0:
                self._open_trades_count -= 1

    def _round_quantity(self, quantity: float) -> float:
        return max(round(quantity, 6), 0.0)

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

                should_enter = provisional_side is not None and state.confirm_streak >= self.breakout_confirm_ticks
                if should_enter and provisional_side:
                    quantity = self._round_quantity(self.position_usdt / price)
                    if quantity <= 0:
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
                state.last_price = price
                time.sleep(self.check_interval_sec)
                tick += 1
                continue

            # Manage open position (same heartbeat/logging style as original bot)
            state.last_price = price
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


