from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

from pionex_client import PionexClient
from strategy import compute_breakout_signal, compute_sl_tp_prices
from trade_logger import TradeLogger


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
    last_exit_time: float = 0.0  # for cooldown


class FuturesBot:
    def __init__(self, config_path: str = "config.json") -> None:
        # Configure logging as early as possible
        log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, log_level_name, logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.log = logging.getLogger("futures_bot")

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
        self.leverage = int(self.config["leverage"])
        self.position_usdt = float(self.config["position_usdt"])  # per-position target notional
        self.max_open_trades = int(self.config["max_open_trades"])
        self.breakout_change_percent = float(self.config["breakout_change_percent"])
        self.stop_loss_percent = float(self.config["stop_loss_percent"])
        self.take_profit_percent = float(self.config["take_profit_percent"])
        self.check_interval_sec = int(self.config["check_interval_sec"])
        self.cooldown_sec = int(self.config["cooldown_sec"])

        self.logger = TradeLogger(self.config.get("log_csv", "trades.csv"))
        self._states: Dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        self._open_trades_lock = threading.Lock()
        self._open_trades_count = 0

        self.log.info(
            "Bot initialized | symbols=%s leverage=%s position_usdt=%s max_open_trades=%s interval=%ss cooldown=%ss dry_run=%s",
            ",".join(self.symbols),
            self.leverage,
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
        # Conservative rounding to 6 decimals to avoid over-size; adjust per symbol if needed
        return max(round(quantity, 6), 0.0)

    def _worker(self, symbol: str) -> None:
        state = self._states[symbol]
        thread_name = f"{symbol}-worker"
        threading.current_thread().name = thread_name
        self.log.info("Worker started for %s", symbol)

        # Initialize last price
        while state.last_price is None:
            resp = self.client.get_price(symbol)
            if resp.ok and resp.data and "price" in resp.data:
                state.last_price = float(resp.data["price"])  # type: ignore[arg-type]
                self.log.info("%s initial price set: %.8f", symbol, state.last_price)
            else:
                self.log.warning("%s price init failed: %s", symbol, getattr(resp, "error", None))
                time.sleep(1)

        # Heartbeat cadence based on check interval (~60s)
        tick = 0
        heartbeat_every = max(1, int(60 / max(1, self.check_interval_sec)))

        # Main loop
        while True:
            price_resp = self.client.get_price(symbol)
            if not price_resp.ok or not price_resp.data or "price" not in price_resp.data:
                self.log.warning("%s price fetch failed: %s", symbol, getattr(price_resp, "error", None))
                time.sleep(self.check_interval_sec)
                tick += 1
                continue
            price = float(price_resp.data["price"])  # type: ignore[arg-type]

            now = time.time()

            if not state.in_position:
                # cooldown check
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

                sig = compute_breakout_signal(
                    last_price=state.last_price,
                    current_price=price,
                    breakout_change_percent=self.breakout_change_percent,
                )
                change_pct = (price - state.last_price) / state.last_price * 100.0
                self.log.debug(
                    "%s delta=%.4f%% last=%.8f cur=%.8f sig=%s",
                    symbol,
                    change_pct,
                    state.last_price,
                    price,
                    sig,
                )
                if sig.should_enter and sig.side:
                    # position sizing
                    quantity = self._round_quantity(self.position_usdt / price)
                    if quantity <= 0:
                        self.log.warning("%s quantity computed <= 0; skipping entry", symbol)
                        state.last_price = price
                        time.sleep(self.check_interval_sec)
                        tick += 1
                        continue

                    self.log.info("%s ENTRY signal side=%s qty=%.6f price=%.8f", symbol, sig.side, quantity, price)
                    if sig.side == "BUY":
                        order = self.client.place_market_order(
                            symbol=symbol,
                            side=sig.side,
                            amount=self.position_usdt,
                        )
                    else:
                        order = self.client.place_market_order(
                            symbol=symbol,
                            side=sig.side,
                            quantity=quantity,
                        )
                    if order.ok:
                        entry_price = price
                        sl, tp = compute_sl_tp_prices(
                            entry_price=entry_price,
                            side=sig.side,
                            stop_loss_percent=self.stop_loss_percent,
                            take_profit_percent=self.take_profit_percent,
                        )
                        state.in_position = True
                        state.side = sig.side
                        state.quantity = quantity
                        state.entry_price = entry_price
                        state.stop_loss = sl
                        state.take_profit = tp
                        state.order_id = (
                            str(order.data.get("orderId")) if order.data else None  # type: ignore[union-attr]
                        )
                        self._on_open()
                        self.logger.log(
                            event="entry",
                            symbol=symbol,
                            side=sig.side,
                            quantity=quantity,
                            price=entry_price,
                            stop_loss=sl,
                            take_profit=tp,
                            order_id=state.order_id,
                            reason="breakout",
                            meta={"leverage": self.leverage},
                        )
                        self.log.info(
                            "%s ENTRY ok order_id=%s sl=%.8f tp=%.8f", symbol, state.order_id, sl, tp
                        )
                    else:
                        self.log.error("%s ENTRY failed: %s", symbol, order.error)
                        self.logger.log(
                            event="error",
                            symbol=symbol,
                            reason=f"order_failed: {order.error}",
                        )
                # update last price for next delta calc
                state.last_price = price
                time.sleep(self.check_interval_sec)
                tick += 1
                continue

            # Manage open position
            if state.in_position and state.side:
                if state.side == "BUY":
                    hit_sl = price <= state.stop_loss
                    hit_tp = price >= state.take_profit
                else:  # SELL
                    hit_sl = price >= state.stop_loss
                    hit_tp = price <= state.take_profit

                if hit_sl or hit_tp:
                    self.log.info(
                        "%s EXIT trigger side=%s price=%.8f reason=%s",
                        symbol,
                        state.side,
                        price,
                        "take_profit" if hit_tp else "stop_loss",
                    )
                    close_resp = self.client.close_position(
                        symbol=symbol,
                        side=state.side,
                        quantity=state.quantity,
                    )
                    if close_resp.ok:
                        pnl = (price - state.entry_price) * state.quantity
                        if state.side == "SELL":
                            pnl = -pnl
                        self.logger.log(
                            event="exit",
                            symbol=symbol,
                            side=state.side,
                            quantity=state.quantity,
                            price=price,
                            order_id=state.order_id,
                            pnl=pnl,
                            reason="take_profit" if hit_tp else "stop_loss",
                        )
                        self.log.info("%s EXIT ok pnl=%.6f", symbol, pnl)
                    else:
                        self.log.error("%s EXIT failed: %s", symbol, close_resp.error)
                        self.logger.log(
                            event="error",
                            symbol=symbol,
                            reason=f"close_failed: {close_resp.error}",
                        )
                    # reset state regardless; avoid stuck positions in dry-run
                    state.in_position = False
                    state.side = None
                    state.quantity = 0.0
                    state.entry_price = 0.0
                    state.stop_loss = 0.0
                    state.take_profit = 0.0
                    state.order_id = None
                    state.last_exit_time = time.time()
                    self._on_close()
                # always refresh last price
                state.last_price = price
                time.sleep(self.check_interval_sec)
                tick += 1
                continue

    def run(self) -> None:
        threads = []
        for symbol in self.symbols:
            t = threading.Thread(target=self._worker, args=(symbol,), daemon=True)
            t.start()
            threads.append(t)
        self.log.info("Bot running with %d worker(s)", len(threads))
        # keep main thread alive
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            self.log.info("Stopping bot...")


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    os.chdir(project_dir)
    bot = FuturesBot()
    bot.run() 