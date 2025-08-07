from __future__ import annotations

from pathlib import Path
import csv
from datetime import datetime
from typing import Optional, Dict, Any


class TradeLogger:
    def __init__(self, csv_path: str = "trades.csv") -> None:
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self) -> None:
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "event",
                        "symbol",
                        "side",
                        "quantity",
                        "price",
                        "stop_loss",
                        "take_profit",
                        "order_id",
                        "pnl",
                        "reason",
                        "meta",
                    ],
                )
                writer.writeheader()

    def log(
        self,
        *,
        event: str,
        symbol: str,
        side: Optional[str] = None,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_id: Optional[str] = None,
        pnl: Optional[float] = None,
        reason: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "event": event,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "order_id": order_id,
            "pnl": pnl,
            "reason": reason,
            "meta": str(meta) if meta else None,
        }
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=list(row.keys()),
            )
            writer.writerow(row) 