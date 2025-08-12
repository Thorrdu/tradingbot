from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Deque, Tuple
from collections import deque


@dataclass(frozen=True)
class Signal:
    side: Optional[str]
    score: float


class ZScoreHistory:
    def __init__(self, maxlen: int = 600) -> None:
        self.values: Deque[float] = deque(maxlen=maxlen)

    def push(self, z_abs: float) -> None:
        self.values.append(max(0.0, float(z_abs)))

    def percentile(self, p: float) -> float:
        arr = sorted(self.values)
        if not arr:
            return 0.0
        p = min(0.999, max(0.0, p))
        k = int(p * (len(arr) - 1))
        return arr[k]


def compute_signal_z(change_pct: float, sigma: float, k_base: float, mode: str) -> Signal:
    z = (change_pct / sigma) if sigma > 1e-9 else 0.0
    if mode == "contrarian":
        if z <= -k_base:
            return Signal(side="BUY", score=abs(z))
        if z >= k_base:
            return Signal(side="SELL", score=abs(z))
    else:  # momentum
        if z >= k_base:
            return Signal(side="BUY", score=abs(z))
        if z <= -k_base:
            return Signal(side="SELL", score=abs(z))
    return Signal(side=None, score=0.0)


def should_enter_by_spread(spread_bps: float, max_spread_bps: float) -> bool:
    return spread_bps <= max(0.0, max_spread_bps)


