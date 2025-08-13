from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _read_tail_lines(path: Path, max_lines: int = 50) -> List[str]:
    try:
        if not path.exists():
            return [f"log file not found: {path}"]
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return lines[-max_lines:]
    except Exception as exc:
        return [f"error reading log: {exc}"]


def render_positions(project_root: Path) -> None:
    state_file = project_root / "spot2" / "logs" / "runtime_state.json"
    state = _read_json(state_file)
    print("Positions (runtime_state.json)\n")
    if not state:
        print("No positions found.")
        return
    header = f"{'Symbol':<12} {'Side':<5} {'Qty':>12} {'Entry':>12} {'SL':>12} {'TP':>12}"
    print(header)
    print("-" * len(header))
    for sym, st in state.items():
        if not isinstance(st, dict):
            continue
        side = (st.get("side") or "").upper()
        qty = float(st.get("quantity", 0.0) or 0.0)
        entry = float(st.get("entry_price", 0.0) or 0.0)
        sl = float(st.get("stop_loss", 0.0) or 0.0)
        tp = float(st.get("take_profit", 0.0) or 0.0)
        print(f"{sym:<12} {side:<5} {qty:>12.6f} {entry:>12.6f} {sl:>12.6f} {tp:>12.6f}")


def render_pairs(project_root: Path) -> None:
    # Very small summary based on trades.csv
    trades_csv = project_root / "spot2" / "logs" / "trades.csv"
    print("Pairs performance (from trades.csv)\n")
    if not trades_csv.exists():
        print("trades.csv not found.")
        return
    try:
        import csv
        rows = list(csv.DictReader(trades_csv.open("r", encoding="utf-8", newline="")))
    except Exception:
        rows = []
    perf: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        perf.setdefault(sym, {"trades": 0, "wins": 0, "pnl": 0.0})
        perf[sym]["trades"] += 1
        try:
            pnl = float(r.get("pnl", 0.0) or 0.0)
            perf[sym]["pnl"] += pnl
            if pnl > 0:
                perf[sym]["wins"] += 1
        except Exception:
            pass
    header = f"{'Symbol':<12} {'Trades':>6} {'Win%':>6} {'PnL':>14}"
    print(header)
    print("-" * len(header))
    for sym, st in sorted(perf.items()):
        trades = int(st["trades"]) or 0
        wins = int(st["wins"]) or 0
        winrate = (100.0 * wins / trades) if trades else 0.0
        pnl = float(st["pnl"]) or 0.0
        print(f"{sym:<12} {trades:>6d} {winrate:>6.1f} {pnl:>14.6f}")


def render_logs(project_root: Path) -> None:
    log_file = project_root / "spot2" / "logs" / "bot.log"
    print(f"Log tail: {log_file}\n")
    for line in _read_tail_lines(log_file, max_lines=50):
        print(line)


HELP_TEXT = """
Spot2 Monitor — Views:
  1: Positions (runtime_state.json)
  2: Pairs performance (trades.csv)
  3: Log tail (spot2/logs/bot.log)
  h: Help
  q: Quit

Type the key then press Enter to switch views. Screen refreshes on each command.
"""


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    view = "h"
    while True:
        _clear()
        print("Spot2 Monitor\n")
        try:
            if view == "1":
                render_positions(project_root)
            elif view == "2":
                render_pairs(project_root)
            elif view == "3":
                render_logs(project_root)
            else:
                print(HELP_TEXT.strip())
        except Exception as exc:
            print(f"Error rendering view: {exc}")
        print("\n[1]Positions  [2]Pairs  [3]Logs  [h]Help  [q]Quit")
        cmd = input("> ").strip().lower()
        if not cmd:
            continue
        if cmd in {"q", "quit", "exit"}:
            break
        if cmd in {"1", "2", "3", "h"}:
            view = cmd
        else:
            # Unknown, show help next
            view = "h"


if __name__ == "__main__":
    main()



