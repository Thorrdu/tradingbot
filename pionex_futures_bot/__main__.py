from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _chdir_to_project_root() -> None:
    # Assure un cwd stable: dossier contenant ce package
    pkg_dir = Path(__file__).resolve().parent
    project_dir = pkg_dir
    os.chdir(project_dir)


def _run_spot(config_path: str) -> None:
    from pionex_futures_bot.spot.bot import SpotBot

    _chdir_to_project_root()
    bot = SpotBot(config_path=config_path)
    bot.run()


# PERP bot removed


def _print_config_example(kind: str) -> None:
    example_path = Path(__file__).resolve().parent / ("config/config.json")
    try:
        print(example_path.read_text(encoding="utf-8"))
    except Exception:
        data = {
            "base_url": "https://api.pionex.com",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "position_usdt": 25,
            "max_open_trades": 1,
            "breakout_change_percent": 0.35,
            "stop_loss_percent": 2.0,
            "take_profit_percent": 3.0,
            "check_interval_sec": 3,
            "cooldown_sec": 300,
            "idle_backoff_sec": 15,
            "dry_run": True,
            "log_csv": "trades.csv",
            "state_file": "runtime_state.json",
        }
        print(json.dumps(data, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pionex_futures_bot",
        description="CLI pour exécuter le bot Spot",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_spot = sub.add_parser("spot", help="Démarrer le bot Spot")
    p_spot.add_argument("--config", default="config/config.json", help="Chemin du fichier de configuration Spot")
    p_spot.add_argument("--print-config", action="store_true", help="Affiche un exemple de configuration et sort")

    p_utils = sub.add_parser("symbols", help="Fetch and store market symbols (SPOT/PERP)")
    p_utils.add_argument("--type", choices=["SPOT", "PERP"], help="Market type to fetch")
    p_utils.add_argument("--out", default="config/symbols.json", help="Output JSON path")

    p_stats = sub.add_parser("stats", help="Compute trading statistics from summary CSV")
    p_stats.add_argument("--file", default="logs/trades_summary.csv", help="Summary CSV file (default: logs/trades_summary.csv)")
    p_stats.add_argument("--symbol", default=None, help="Filter by symbol (e.g., BTC_USDT)")
    p_stats.add_argument("--since-hours", type=int, default=None, help="Only include trades with exit_ts within the last N hours")
    p_stats.add_argument("--top", type=int, default=5, help="Show top N and bottom N pairs by PnL and winrate")

    args = parser.parse_args()

    if args.cmd == "spot":
        if args.print_config:
            _print_config_example("spot")
            return
        _run_spot(args.config)
    elif args.cmd == "symbols":
        from pionex_futures_bot.clients import PionexClient
        _chdir_to_project_root()
        client = PionexClient(api_key="", api_secret="", base_url=os.getenv("PIONEX_BASE_URL", "https://api.pionex.com"), dry_run=True)
        resp = client.get_market_symbols(market_type=args.type)
        if not resp.ok or not resp.data or not isinstance(resp.data.get("symbols"), list):
            print("Failed to fetch symbols:", resp.error)
            return
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "type": args.type or "ALL",
            "fetched_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "symbols": resp.data["symbols"],
        }
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"Saved {len(resp.data['symbols'])} symbols to {out_path}")
    elif args.cmd == "stats":
        import csv
        from datetime import datetime, timedelta
        _chdir_to_project_root()
        csv_path = Path(args.file)
        if not csv_path.exists():
            print(f"Summary CSV not found: {csv_path}")
            return
        def parse_ts(s: str | None) -> datetime | None:
            if not s:
                return None
            try:
                # Accept ...Z suffix
                return datetime.fromisoformat(s.replace("Z", ""))
            except Exception:
                return None
        since_dt: datetime | None = None
        if args.since_hours and args.since_hours > 0:
            since_dt = datetime.utcnow() - timedelta(hours=args.since_hours)
        total = 0.0
        won = 0.0
        lost = 0.0
        n = 0
        n_win = 0
        n_loss = 0
        n_be = 0
        hold_sum = 0.0
        by_reason: dict[str, int] = {}
        by_symbol: dict[str, dict[str, float]] = {}
        with csv_path.open("r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                sym = (row.get("symbol") or "").strip()
                if args.symbol and sym != args.symbol:
                    continue
                exit_ts = parse_ts(row.get("exit_ts"))
                if since_dt and (not exit_ts or exit_ts < since_dt):
                    continue
                try:
                    pnl = float(row.get("pnl_usdt") or 0.0)
                    hold = float(row.get("hold_sec") or 0.0)
                except Exception:
                    continue
                n += 1
                total += pnl
                hold_sum += hold
                reason = (row.get("exit_reason") or "").strip() or "UNKNOWN"
                by_reason[reason] = by_reason.get(reason, 0) + 1
                if pnl > 0:
                    n_win += 1
                    won += pnl
                elif pnl < 0:
                    n_loss += 1
                    lost += abs(pnl)
                else:
                    n_be += 1
                # Per-symbol aggregates
                s = by_symbol.setdefault(sym, {"trades": 0.0, "wins": 0.0, "pnl": 0.0})
                s["trades"] += 1
                s["pnl"] += pnl
                if pnl > 0:
                    s["wins"] += 1
        def fmt_dur(s: float) -> str:
            sec = int(round(max(0.0, s)))
            h, rem = divmod(sec, 3600)
            m, s2 = divmod(rem, 60)
            if h:
                return f"{h}h{m:02}m{s2:02}s"
            if m:
                return f"{m}m{s2:02}s"
            return f"{s:.1f}s"
        avg_hold = hold_sum / n if n else 0.0
        win_rate = (n_win / n * 100.0) if n else 0.0
        print("=== Trading statistics ===")
        print(f"File: {csv_path}")
        if args.symbol:
            print(f"Symbol: {args.symbol}")
        if since_dt:
            print(f"Since: last {args.since_hours}h (>= {since_dt.isoformat()}Z)")
        print(f"Trades: {n}  |  Wins: {n_win}  Losses: {n_loss}  BE: {n_be}  |  Win rate: {win_rate:.2f}%")
        print(f"Total PnL: {total:.4f} USDT  |  Won: {won:.4f}  Lost: -{lost:.4f}")
        print(f"Average hold: {fmt_dur(avg_hold)}")
        if by_reason:
            print("By reason:")
            for k, v in sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"  {k}: {v}")
        # Leaderboards by symbol
        if by_symbol:
            rows = []
            for s, agg in by_symbol.items():
                t = int(agg.get("trades", 0))
                w = float(agg.get("wins", 0))
                pnl_sum = float(agg.get("pnl", 0))
                wr = (w / t * 100.0) if t else 0.0
                rows.append((s, t, wr, pnl_sum))
            # Sorts
            top_n = max(1, int(args.top))
            print("Top by PnL:")
            for s, t, wr, pnl_sum in sorted(rows, key=lambda x: (-x[3], x[0]))[:top_n]:
                print(f"  {s}: pnl={pnl_sum:.4f} USDT | trades={t} | winrate={wr:.2f}%")
            print("Bottom by PnL:")
            for s, t, wr, pnl_sum in sorted(rows, key=lambda x: (x[3], x[0]))[:top_n]:
                print(f"  {s}: pnl={pnl_sum:.4f} USDT | trades={t} | winrate={wr:.2f}%")
            print("Top by Winrate (min 3 trades):")
            filt = [r for r in rows if r[1] >= 3]
            for s, t, wr, pnl_sum in sorted(filt, key=lambda x: (-x[2], -x[3], x[0]))[:top_n]:
                print(f"  {s}: winrate={wr:.2f}% | trades={t} | pnl={pnl_sum:.4f} USDT")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()


