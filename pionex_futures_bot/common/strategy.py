from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple, Deque
from collections import deque


Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class Signal:
    should_enter: bool
    side: Side | None
    score: float | None = None


def compute_breakout_signal(
    *,
    last_price: float,
    current_price: float,
    breakout_change_percent: float,
) -> Signal:
    change_pct = (current_price - last_price) / last_price * 100.0
    # Contrarian logic: dump -> BUY, pump -> SELL
    if change_pct <= -breakout_change_percent:
        return Signal(should_enter=True, side="BUY", score=abs(change_pct))
    if change_pct >= breakout_change_percent:
        return Signal(should_enter=True, side="SELL", score=abs(change_pct))
    return Signal(should_enter=False, side=None, score=None)


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


@dataclass
class VolatilityState:
    ewm_var: float
    window: Deque[float]


def update_volatility_state(
    *,
    state: VolatilityState,
    ret: float,
    lambda_ewm: float = 0.94,
    max_window: int = 300,
) -> VolatilityState:
    # EWM variance update
    var = lambda_ewm * state.ewm_var + (1.0 - lambda_ewm) * (ret * ret)
    window = state.window
    window.append(ret)
    if len(window) > max_window:
        window.popleft()
    return VolatilityState(ewm_var=var, window=window)


def compute_zscore_breakout(
    *,
    change_pct: float,
    vol_state: VolatilityState,
    k_threshold: float,
    mode: Literal["contrarian", "momentum"] = "contrarian",
) -> Signal:
    sigma = (vol_state.ewm_var ** 0.5) if vol_state.ewm_var > 0 else 0.0
    z = (change_pct / sigma) if sigma > 1e-9 else 0.0
    if mode == "contrarian":
        if z <= -k_threshold:
            return Signal(should_enter=True, side="BUY", score=abs(z))
        if z >= k_threshold:
            return Signal(should_enter=True, side="SELL", score=abs(z))
    else:  # momentum
        if z >= k_threshold:
            return Signal(should_enter=True, side="BUY", score=abs(z))
        if z <= -k_threshold:
            return Signal(should_enter=True, side="SELL", score=abs(z))
    return Signal(should_enter=False, side=None, score=None)


def compute_atr_sl_tp(
    *,
    entry_price: float,
    side: Side,
    atr_abs: float,
    alpha_sl: float = 1.8,
    beta_tp: float = 2.6,
) -> Tuple[float, float]:
    if side == "BUY":
        sl = entry_price - alpha_sl * atr_abs
        tp = entry_price + beta_tp * atr_abs
    else:
        sl = entry_price + alpha_sl * atr_abs
        tp = entry_price - beta_tp * atr_abs
    return (sl, tp)


