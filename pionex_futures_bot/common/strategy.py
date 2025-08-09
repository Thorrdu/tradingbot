from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple


Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class Signal:
    should_enter: bool
    side: Side | None


def compute_breakout_signal(
    *,
    last_price: float,
    current_price: float,
    breakout_change_percent: float,
) -> Signal:
    change_pct = (current_price - last_price) / last_price * 100.0
    # Contrarian logic: dump -> BUY, pump -> SELL
    if change_pct <= -breakout_change_percent:
        return Signal(should_enter=True, side="BUY")
    if change_pct >= breakout_change_percent:
        return Signal(should_enter=True, side="SELL")
    return Signal(should_enter=False, side=None)


def compute_sl_tp_prices(
    *,
    entry_price: float,
    side: Side,
    stop_loss_percent: float,
    take_profit_percent: float,
) -> Tuple[float, float]:
    if side == "BUY":
        sl = entry_price * (1.0 - stop_loss_percent / 100.0)
        tp = entry_price * (1.0 + take_profit_percent / 100.0)
    else:  # SELL
        sl = entry_price * (1.0 + stop_loss_percent / 100.0)
        tp = entry_price * (1.0 - take_profit_percent / 100.0)
    return (sl, tp)


