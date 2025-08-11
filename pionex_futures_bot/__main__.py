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
    p_stats.add_argument("--last", type=int, default=None, help="List the last N trades with details")
    p_stats.add_argument("--top-trades", type=int, default=None, help="Show top N best and worst trades as tables")

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
        def _try_float(v: object) -> float | None:
            try:
                if v is None:
                    return None
                return float(v)
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
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel
            console = Console()
            console.print(Panel.fit("Trading statistics", style="bold cyan"))
            meta_tbl = Table(box=None, show_header=False)
            meta_tbl.add_row("File", str(csv_path))
            if args.symbol:
                meta_tbl.add_row("Symbol", str(args.symbol))
            if since_dt:
                meta_tbl.add_row("Since", f"last {args.since_hours}h (>= {since_dt.isoformat()}Z)")
            meta_tbl.add_row("Trades", f"{n}  |  Wins: {n_win}  Losses: {n_loss}  BE: {n_be}  |  Win rate: {win_rate:.2f}%")
            meta_tbl.add_row("PnL", f"Total {total:.4f} USDT  |  Won: {won:.4f}  Lost: -{lost:.4f}")
            meta_tbl.add_row("Avg hold", f"{fmt_dur(avg_hold)}")
            console.print(meta_tbl)
            if by_reason:
                tbl = Table(title="By exit reason", show_header=True, header_style="bold magenta")
                tbl.add_column("Reason")
                tbl.add_column("Count", justify="right")
                for k, v in sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0])):
                    tbl.add_row(k, str(v))
                console.print(tbl)
        except Exception:
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
            top_n = max(1, int(args.top))
            try:
                from rich.table import Table
                from rich.console import Console
                console = Console()
                tbl_top = Table(title=f"Top {top_n} by PnL", show_header=True, header_style="bold green")
                tbl_top.add_column("Symbol")
                tbl_top.add_column("Trades", justify="right")
                tbl_top.add_column("Winrate", justify="right")
                tbl_top.add_column("PnL (USDT)", justify="right")
                for s, t, wr, pnl_sum in sorted(rows, key=lambda x: (-x[3], x[0]))[:top_n]:
                    tbl_top.add_row(s, str(t), f"{wr:.2f}%", f"{pnl_sum:.4f}")
                console.print(tbl_top)

                tbl_bot = Table(title=f"Bottom {top_n} by PnL", show_header=True, header_style="bold red")
                tbl_bot.add_column("Symbol")
                tbl_bot.add_column("Trades", justify="right")
                tbl_bot.add_column("Winrate", justify="right")
                tbl_bot.add_column("PnL (USDT)", justify="right")
                for s, t, wr, pnl_sum in sorted(rows, key=lambda x: (x[3], x[0]))[:top_n]:
                    tbl_bot.add_row(s, str(t), f"{wr:.2f}%", f"{pnl_sum:.4f}")
                console.print(tbl_bot)
            except Exception:
                print("Top by PnL:")
                for s, t, wr, pnl_sum in sorted(rows, key=lambda x: (-x[3], x[0]))[:top_n]:
                    print(f"  {s}: pnl={pnl_sum:.4f} USDT | trades={t} | winrate={wr:.2f}%")
                print("Bottom by PnL:")
                for s, t, wr, pnl_sum in sorted(rows, key=lambda x: (x[3], x[0]))[:top_n]:
                    print(f"  {s}: pnl={pnl_sum:.4f} USDT | trades={t} | winrate={wr:.2f}%")

        # Best / Worst individual trades (from summary CSV)
        # We re-read the CSV to keep it simple and gather necessary fields
        best_trade = None
        worst_trade = None
        all_trades: list[dict[str, object]] = []
        with csv_path.open("r", encoding="utf-8") as f:
            r = __import__("csv").DictReader(f)
            for row in r:
                sym = (row.get("symbol") or "").strip()
                if args.symbol and sym != args.symbol:
                    continue
                exit_ts = parse_ts(row.get("exit_ts"))
                if since_dt and (not exit_ts or exit_ts < since_dt):
                    continue
                try:
                    pnl = float(row.get("pnl_usdt") or 0.0)
                except Exception:
                    continue
                payload = {
                    "symbol": sym,
                    "side": (row.get("side") or "").strip(),
                    "entry_ts": (row.get("entry_ts") or "").strip(),
                    "exit_ts": (row.get("exit_ts") or "").strip(),
                    "entry_price": _try_float(row.get("entry_price")),
                    "exit_price": _try_float(row.get("exit_price")),
                    "pnl_usdt": pnl,
                    "pnl_percent": _try_float(row.get("pnl_percent")),
                    "hold_sec": _try_float(row.get("hold_sec")),
                    "sl_price": _try_float(row.get("sl_price")),
                    "tp_price": _try_float(row.get("tp_price")),
                    "high_watermark": _try_float(row.get("high_watermark")),
                    "low_watermark": _try_float(row.get("low_watermark")),
                    "entry_signal": (row.get("entry_signal") or "").strip(),
                    "entry_signal_score": _try_float(row.get("entry_signal_score")),
                }
                if best_trade is None or pnl > best_trade[0]:
                    best_trade = (pnl, payload)
                if worst_trade is None or pnl < worst_trade[0]:
                    worst_trade = (pnl, payload)
                payload_copy = dict(payload)
                payload_copy["pnl_usdt"] = pnl
                all_trades.append(payload_copy)

        if best_trade:
            pnl, bt = best_trade
            try:
                from rich.panel import Panel
                from rich.console import Console
                console = Console()
                console.print(Panel.fit(
                    f"Best trade: {bt['symbol']} {bt['side']}\nPnL {pnl:.4f} USDT ({(bt['pnl_percent'] or 0.0):.2f}%)  Hold {fmt_dur(bt['hold_sec'] or 0)}\nEntry {bt['entry_price']} → Exit {bt['exit_price']}  SL {bt['sl_price']}  TP {bt['tp_price']}\nHigh {bt['high_watermark']}  Low {bt['low_watermark']}  Signal {bt['entry_signal']} (score {bt['entry_signal_score']})\nTime {bt.get('entry_ts')} → {bt.get('exit_ts')}",
                    title="Best trade", style="bold green"))
            except Exception:
                print("Best trade:")
                print(f"  {bt['symbol']} {bt['side']} pnl={pnl:.4f} USDT ({(bt['pnl_percent'] or 0.0):.2f}%) hold={fmt_dur(bt['hold_sec'] or 0)}")
                print(f"  entry={bt['entry_price']} -> exit={bt['exit_price']}  sl={bt['sl_price']} tp={bt['tp_price']}")
                print(f"  high={bt['high_watermark']} low={bt['low_watermark']} signal={bt['entry_signal']} score={bt['entry_signal_score']}")
                if bt.get("entry_ts") and bt.get("exit_ts"):
                    print(f"  time: {bt['entry_ts']} -> {bt['exit_ts']}")
        if worst_trade:
            pnl, wt = worst_trade
            try:
                from rich.panel import Panel
                from rich.console import Console
                console = Console()
                console.print(Panel.fit(
                    f"Worst trade: {wt['symbol']} {wt['side']}\nPnL {pnl:.4f} USDT ({(wt['pnl_percent'] or 0.0):.2f}%)  Hold {fmt_dur(wt['hold_sec'] or 0)}\nEntry {wt['entry_price']} → Exit {wt['exit_price']}  SL {wt['sl_price']}  TP {wt['tp_price']}\nHigh {wt['high_watermark']}  Low {wt['low_watermark']}  Signal {wt['entry_signal']} (score {wt['entry_signal_score']})\nTime {wt.get('entry_ts')} → {wt.get('exit_ts')}",
                    title="Worst trade", style="bold red"))
            except Exception:
                print("Worst trade:")
                print(f"  {wt['symbol']} {wt['side']} pnl={pnl:.4f} USDT ({(wt['pnl_percent'] or 0.0):.2f}%) hold={fmt_dur(wt['hold_sec'] or 0)}")
                print(f"  entry={wt['entry_price']} -> exit={wt['exit_price']}  sl={wt['sl_price']} tp={wt['tp_price']}")
                print(f"  high={wt['high_watermark']} low={wt['low_watermark']} signal={wt['entry_signal']} score={wt['entry_signal_score']}")
                if wt.get("entry_ts") and wt.get("exit_ts"):
                    print(f"  time: {wt['entry_ts']} -> {wt['exit_ts']}")

        # Top N best/worst trades as tables
        if args.top_trades and args.top_trades > 0 and all_trades:
            N = int(args.top_trades)
            # Sort copies by pnl_usdt
            best_list = sorted(all_trades, key=lambda d: float(d.get("pnl_usdt") or 0.0), reverse=True)[:N]
            worst_list = sorted(all_trades, key=lambda d: float(d.get("pnl_usdt") or 0.0))[:N]
            try:
                from rich.table import Table
                from rich.console import Console
                console = Console()
                def render_table(title: str, data: list[dict[str, object]], style: str) -> None:
                    tbl = Table(title=title, header_style=style)
                    tbl.add_column("Exit time")
                    tbl.add_column("Symbol")
                    tbl.add_column("Side")
                    tbl.add_column("PnL (USDT)", justify="right")
                    tbl.add_column("PnL %", justify="right")
                    tbl.add_column("Hold", justify="right")
                    tbl.add_column("Entry → Exit")
                    tbl.add_column("SL / TP")
                    tbl.add_column("High / Low")
                    tbl.add_column("Signal (score)")
                    for row in data:
                        pnl = float(row.get("pnl_usdt") or 0.0)
                        pp = float(row.get("pnl_percent") or 0.0)
                        tbl.add_row(
                            str(row.get("exit_ts")),
                            str(row.get("symbol")),
                            str(row.get("side")),
                            f"{pnl:.4f}",
                            f"{pp:.2f}%",
                            fmt_dur(float(row.get("hold_sec") or 0.0)),
                            f"{row.get('entry_price')} → {row.get('exit_price')}",
                            f"{row.get('sl_price')} / {row.get('tp_price')}",
                            f"{row.get('high_watermark')} / {row.get('low_watermark')}",
                            f"{row.get('entry_signal')} ({row.get('entry_signal_score')})",
                        )
                    console.print(tbl)
                render_table(f"Top {len(best_list)} best trades", best_list, "bold green")
                render_table(f"Top {len(worst_list)} worst trades", worst_list, "bold red")
            except Exception:
                print(f"Top {N} best trades:")
                for row in best_list:
                    pnl = float(row.get("pnl_usdt") or 0.0)
                    pp = float(row.get("pnl_percent") or 0.0)
                    print(f"  {row.get('exit_ts')} | {row.get('symbol')} {row.get('side')} pnl={pnl:.4f} USDT ({pp:.2f}%) hold={fmt_dur(float(row.get('hold_sec') or 0.0))}")
                print(f"Top {N} worst trades:")
                for row in worst_list:
                    pnl = float(row.get("pnl_usdt") or 0.0)
                    pp = float(row.get("pnl_percent") or 0.0)
                    print(f"  {row.get('exit_ts')} | {row.get('symbol')} {row.get('side')} pnl={pnl:.4f} USDT ({pp:.2f}%) hold={fmt_dur(float(row.get('hold_sec') or 0.0))}")

        # Last N trades with details
        if args.last and args.last > 0:
            print(f"Last {args.last} trades:")
            rows = []
            with csv_path.open("r", encoding="utf-8") as f:
                r = __import__("csv").DictReader(f)
                for row in r:
                    sym = (row.get("symbol") or "").strip()
                    if args.symbol and sym != args.symbol:
                        continue
                    exit_ts = parse_ts(row.get("exit_ts"))
                    if since_dt and (not exit_ts or exit_ts < since_dt):
                        continue
                    rows.append(row)
            # Sort by exit time ascending then take last N
            def _key(r):
                dt = parse_ts(r.get("exit_ts"))
                return dt or __import__("datetime").datetime.min
            rows.sort(key=_key)
            tail = rows[-int(args.last):]
            try:
                from rich.table import Table
                from rich.console import Console
                console = Console()
                tbl = Table(title=f"Last {len(tail)} trades", header_style="bold cyan")
                tbl.add_column("Exit time")
                tbl.add_column("Symbol")
                tbl.add_column("Side")
                tbl.add_column("PnL (USDT)", justify="right")
                tbl.add_column("PnL %", justify="right")
                tbl.add_column("Hold", justify="right")
                tbl.add_column("Entry → Exit")
                tbl.add_column("SL / TP")
                tbl.add_column("High / Low")
                tbl.add_column("Signal (score)")
                for row in tail:
                    try:
                        pnl = float(row.get("pnl_usdt") or 0.0)
                    except Exception:
                        pnl = 0.0
                    pp = _try_float(row.get("pnl_percent")) or 0.0
                    tbl.add_row(
                        str(row.get('exit_ts')),
                        str(row.get('symbol')),
                        str(row.get('side')),
                        f"{pnl:.4f}",
                        f"{pp:.2f}%",
                        fmt_dur(_try_float(row.get('hold_sec')) or 0),
                        f"{row.get('entry_price')} → {row.get('exit_price')}",
                        f"{row.get('sl_price')} / {row.get('tp_price')}",
                        f"{row.get('high_watermark')} / {row.get('low_watermark')}",
                        f"{row.get('entry_signal')} ({row.get('entry_signal_score')})",
                    )
                console.print(tbl)
            except Exception:
                for row in tail:
                    try:
                        pnl = float(row.get("pnl_usdt") or 0.0)
                    except Exception:
                        pnl = 0.0
                    pp = _try_float(row.get("pnl_percent")) or 0.0
                    print(f"  {row.get('exit_ts')} | {row.get('symbol')} {row.get('side')} pnl={pnl:.4f} USDT ({pp:.2f}%) hold={fmt_dur(_try_float(row.get('hold_sec')) or 0)}")
                    print(f"    entry={row.get('entry_price')} -> exit={row.get('exit_price')}  sl={row.get('sl_price')} tp={row.get('tp_price')}")
                    print(f"    high={row.get('high_watermark')} low={row.get('low_watermark')} signal={row.get('entry_signal')} score={row.get('entry_signal_score')}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()


