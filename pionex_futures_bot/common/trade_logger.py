from __future__ import annotations

from pathlib import Path
import csv
from datetime import datetime
from typing import Optional, Dict, Any, List


class TradeLogger:
    DEFAULT_FIELDS: List[str] = [
        "timestamp",
        "event",
        "symbol",
        "side",
        "quantity",
        "entry_price",
        "price",
        "exit_price",
        "stop_loss",
        "take_profit",
        "order_id",
        "pnl",
        "pnl_percent",
        "reason",
        "hold_sec",
        "high_watermark",
        "low_watermark",
        "entry_signal",
        "entry_signal_score",
        "entry_change_pct",
        "entry_z",
        "meta",
    ]

    def __init__(self, csv_path: str = "trades.csv") -> None:
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.fieldnames = self._ensure_header()

    def _ensure_header(self) -> List[str]:
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.DEFAULT_FIELDS)
                writer.writeheader()
            return list(self.DEFAULT_FIELDS)
        # Existing file: read header and merge with new fields
        try:
            with self.csv_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                existing = list(reader.fieldnames or [])
        except Exception:
            existing = []
        merged = existing.copy()
        for k in self.DEFAULT_FIELDS:
            if k not in merged:
                merged.append(k)
        return merged

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
        pnl_percent: Optional[float] = None,
        reason: Optional[str] = None,
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        hold_sec: Optional[float] = None,
        high_watermark: Optional[float] = None,
        low_watermark: Optional[float] = None,
        entry_signal: Optional[str] = None,
        entry_signal_score: Optional[float] = None,
        entry_change_pct: Optional[float] = None,
        entry_z: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        row: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "event": event,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "price": price,
            "exit_price": exit_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "order_id": order_id,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "reason": reason,
            "hold_sec": hold_sec,
            "high_watermark": high_watermark,
            "low_watermark": low_watermark,
            "entry_signal": entry_signal,
            "entry_signal_score": entry_signal_score,
            "entry_change_pct": entry_change_pct,
            "entry_z": entry_z,
            "meta": str(meta) if meta else None,
        }
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(row)


class TradeSummaryLogger:
    DEFAULT_FIELDS: List[str] = [
        "entry_ts",
        "exit_ts",
        "hold_sec",
        "symbol",
        "side",
        "quantity",
        "executed_qty",
        "residual_qty",
        "entry_price",
        "exit_price",
        "pnl_usdt",
        "pnl_percent",
        "exit_reason",
        "mode",
        "z_threshold",
        "alpha_sl",
        "beta_tp",
        "atr_window_sec",
        "breakout_change_percent",
        "breakout_lookback_sec",
        "breakout_confirm_ticks",
        "entry_change_pct",
        "entry_z",
        "high_watermark",
        "low_watermark",
        "entry_signal",
        "entry_signal_score",
        "sl_price",
        "tp_price",
    ]

    def __init__(self, csv_path: str = "trades_summary.csv") -> None:
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.fieldnames = self._ensure_header()

    def _ensure_header(self) -> List[str]:
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.DEFAULT_FIELDS)
                writer.writeheader()
            return list(self.DEFAULT_FIELDS)
        try:
            with self.csv_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                existing = list(reader.fieldnames or [])
        except Exception:
            existing = []
        merged = existing.copy()
        for k in self.DEFAULT_FIELDS:
            if k not in merged:
                merged.append(k)
        return merged

    def log_result(
        self,
        *,
        symbol: str,
        side: Optional[str],
        quantity: float,
        executed_qty: float,
        residual_qty: float,
        entry_price: float,
        exit_price: float,
        entry_time: float,
        exit_time: float,
        pnl_usdt: float,
        pnl_percent: float,
        exit_reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        row: Dict[str, Any] = {
            "entry_ts": datetime.utcfromtimestamp(entry_time).isoformat(timespec="seconds") + "Z" if entry_time else None,
            "exit_ts": datetime.utcfromtimestamp(exit_time).isoformat(timespec="seconds") + "Z",
            "hold_sec": round(max(0.0, exit_time - (entry_time or exit_time)), 1),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "executed_qty": executed_qty,
            "residual_qty": residual_qty,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_usdt": pnl_usdt,
            "pnl_percent": pnl_percent,
            "exit_reason": exit_reason,
            "mode": meta.get("mode") if meta else None,
            "z_threshold": meta.get("z_threshold") if meta else None,
            "alpha_sl": meta.get("alpha_sl") if meta else None,
            "beta_tp": meta.get("beta_tp") if meta else None,
            "atr_window_sec": meta.get("atr_window_sec") if meta else None,
            "breakout_change_percent": meta.get("breakout_change_percent") if meta else None,
            "breakout_lookback_sec": meta.get("breakout_lookback_sec") if meta else None,
            "breakout_confirm_ticks": meta.get("breakout_confirm_ticks") if meta else None,
            "entry_change_pct": meta.get("entry_change_pct") if meta else None,
            "entry_z": meta.get("entry_z") if meta else None,
            "high_watermark": meta.get("high_watermark") if meta else None,
            "low_watermark": meta.get("low_watermark") if meta else None,
            "entry_signal": meta.get("entry_signal") if meta else None,
            "entry_signal_score": meta.get("entry_signal_score") if meta else None,
            "sl_price": meta.get("sl_price") if meta else None,
            "tp_price": meta.get("tp_price") if meta else None,
        }
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(row)

