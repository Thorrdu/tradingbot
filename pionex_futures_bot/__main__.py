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
    p_spot.add_argument("--config", default="spot/config/config.json", help="Chemin du fichier de configuration Spot")
    p_spot.add_argument("--print-config", action="store_true", help="Affiche un exemple de configuration et sort")

    # Nouveau bot spot2 (expérimental)
    p_spot2 = sub.add_parser("spot2", help="Démarrer le bot Spot v2 (maker + filtres + z dynamique)")
    p_spot2.add_argument("--config", default="spot2/config/config.json", help="Chemin du fichier de configuration Spot2")
    p_spot2.add_argument("--print-config", action="store_true", help="Affiche un exemple de configuration et sort")
    # Monitoring CLI pour spot2
    p_spot2mon = sub.add_parser("spot2-monitor", help="Dashboard et monitoring du bot Spot v2 (rich)")
    p_spot2mon.add_argument("--summary", default="spot2/logs/trades_summary.csv", help="CSV de synthèse des trades")
    p_spot2mon.add_argument("--state", default="spot2/logs/runtime_state.json", help="Fichier d'état runtime")
    p_spot2mon.add_argument("--trades", default="spot2/logs/trades.csv", help="CSV détaillé des événements")
    p_spot2mon.add_argument("--interval", type=int, default=2, help="Intervalle de rafraîchissement (s)")
    p_spot2mon.add_argument("--view", choices=["dashboard","pairs","positions","trades","reasons","alerts"], default="dashboard", help="Vue initiale")
    p_spot2mon.add_argument("--window-trades", type=int, default=30, help="Fenêtre de trades pour les statistiques/alertes")

    p_utils = sub.add_parser("symbols", help="Fetch and store market symbols (SPOT/PERP)")
    p_utils.add_argument("--type", choices=["SPOT", "PERP"], help="Market type to fetch")
    p_utils.add_argument("--out", default="config/symbols.json", help="Output JSON path")

    p_stats = sub.add_parser("stats", help="Compute trading statistics from summary CSV")
    p_stats.add_argument("--file", default="logs/trades_summary.csv", help="Summary CSV file (default: logs/trades_summary.csv)")
    p_stats.add_argument("--symbol", default=None, help="Filter by symbol (e.g., BTC_USDT)")
    p_stats.add_argument("--since-hours", type=int, default=None, help="Only include trades with exit_ts within the last N hours")
    p_stats.add_argument("--top", type=int, default=5, help="Deprecated: ignored (pairs table shows all)")
    p_stats.add_argument("--last", type=int, default=None, help="List the last N trades with details")
    p_stats.add_argument("--top-trades", type=int, default=None, help="Show top N best and worst trades as tables (default 5)")
    p_stats.add_argument("--watch", action="store_true", help="Auto-refresh view with open positions and totals")
    p_stats.add_argument("--state", default="logs/runtime_state.json", help="Path to runtime state JSON (default: logs/runtime_state.json)")
    p_stats.add_argument("--interval", type=int, default=3, help="Refresh interval in seconds for --watch")
    import os as _os
    p_stats.add_argument("--base-url", default=_os.getenv("PIONEX_BASE_URL", "https://api.pionex.com"), help="API base URL for price lookups")

    args = parser.parse_args()

    if args.cmd == "spot":
        if args.print_config:
            _print_config_example("spot")
            return
        _run_spot(args.config)
    elif args.cmd == "spot2":
        if args.print_config:
            _print_config_example("spot")
            return
        # Lancement du nouveau bot
        _chdir_to_project_root()
        from pionex_futures_bot.spot2.bot import SpotBotV2
        bot = SpotBotV2(config_path=args.config)
        bot.run()
    elif args.cmd == "spot2-monitor":
        # CLI monitoring riche
        _chdir_to_project_root()
        try:
            from rich.live import Live
            from rich.table import Table
            from rich.layout import Layout
            from rich.panel import Panel
            from rich.console import Console
            from rich.align import Align
        except Exception:
            print("Installez 'rich' pour le monitoring: pip install rich")
            return
        from datetime import datetime
        import time
        import csv, json as _J
        summary_path = Path(args.summary)
        state_path = Path(args.state)
        trades_path = Path(args.trades)
        # API client for live price lookups (read-only, dry-run)
        try:
            from pionex_futures_bot.spot2.clients.pionex_client import PionexClient as _MonClient  # type: ignore
        except Exception:
            from pionex_futures_bot.spot.clients.pionex_client import PionexClient as _MonClient  # type: ignore
        mon_client = _MonClient(api_key=os.getenv("API_KEY",""), api_secret=os.getenv("API_SECRET",""), base_url=os.getenv("PIONEX_BASE_URL","https://api.pionex.com"), dry_run=True)

        def fmt_dur(s: float) -> str:
            s = max(0.0, float(s))
            m, sec = divmod(int(s), 60)
            h, m = divmod(m, 60)
            return f"{h}h{m:02}m{sec:02}s" if h else (f"{m}m{sec:02}s" if m else f"{sec}s")

        def load_summary():
            stats = {"n":0,"wins":0,"losses":0,"be":0,"total":0.0}
            pairs = {}
            recent: list[dict[str, str]] = []
            reasons: dict[str,int] = {}
            # Pour les alertes: fenêtre des N derniers trades globaux
            window = max(1, int(getattr(args, "window_trades", 30)))
            window_rows: list[dict[str,str]] = []
            try:
                with summary_path.open("r", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    rows = list(r)
                    for row in rows:
                        sym = (row.get("symbol") or "").strip()
                        pnl = float(row.get("pnl_usdt") or 0.0)
                        stats["n"] += 1
                        stats["total"] += pnl
                        if pnl>0: stats["wins"] += 1
                        elif pnl<0: stats["losses"] += 1
                        else: stats["be"] += 1
                        reasons[row.get("exit_reason","UNKNOWN")] = reasons.get(row.get("exit_reason","UNKNOWN"),0)+1
                        d = pairs.setdefault(sym,{"trades":0,"pnl":0.0,"wins":0})
                        d["trades"] += 1; d["pnl"] += pnl; d["wins"] += (1 if pnl>0 else 0)
                    # last 10 by exit_ts
                    def _key(rr):
                        try:
                            return datetime.fromisoformat((rr.get("exit_ts") or "").replace("Z",""))
                        except Exception:
                            return datetime.min
                    rows.sort(key=_key)
                    recent = rows[-10:]
                    window_rows = rows[-window:]
            except Exception:
                pass
            return stats, pairs, recent, reasons, window_rows

        def load_state():
            try:
                if state_path.exists():
                    return _J.loads(state_path.read_text(encoding="utf-8")) or {}
            except Exception:
                return {}
            return {}

        def filter_pairs(pairs: dict[str, dict], sym: str | None) -> dict[str, dict]:
            if sym:
                return {k: v for k, v in pairs.items() if k == sym}
            return pairs

        def filter_state(state: dict[str, dict], sym: str | None) -> dict[str, dict]:
            if sym:
                return {k: v for k, v in state.items() if k == sym}
            return state

        def shortcuts_footer(current_symbol: str | None) -> Align:
            suf = f" | Filtre: {current_symbol}" if current_symbol else ""
            txt = "Raccourcis: Dashboard (d)  Pairs (p)  Positions (o)  Trades (t)  Reasons (r)  Alerts (a)  Control (c)  Filter (f)  Clear (F)  Quit (q)" + suf
            return Align.center(txt, vertical="middle")

        def render_dashboard():
            stats, pairs, recent, reasons, _ = load_summary()
            state = load_state()
            # Top panel
            top = Table.grid()
            wr = (stats["wins"]/stats["n"]*100.0) if stats["n"] else 0.0
            top.add_row(f"Trades: {stats['n']}  Wins: {stats['wins']}  Losses: {stats['losses']}  BE: {stats['be']}  Winrate: {wr:.2f}%")
            top.add_row(f"PnL total: {stats['total']:.4f} USDT")
            # Pairs: mode compact ou tableau
            pairs_use = filter_pairs(pairs, getattr(args, 'symbol', None)) or {}
            if getattr(args, 'compact', False):
                grid = Table.grid(expand=True)
                grid.add_column(ratio=1); grid.add_column(ratio=1); grid.add_column(ratio=1)
                tiles = []
                # Construire un set de symboles pertinent
                sym_set = set(pairs_use.keys()) | set(load_state().keys())
                syms = sorted(sym_set)
                for sym in syms:
                    d = pairs.get(sym, {"trades":0,"wins":0,"pnl":0.0})
                    t = int(d.get('trades',0)); w=int(d.get('wins',0)); pnl=float(d.get('pnl',0.0))
                    wr = (w/t*100.0) if t else 0.0
                    ev = (pnl/t) if t else 0.0
                    tbl = Table(show_header=False, box=None)
                    tbl.add_row("Trades:", str(t))
                    tbl.add_row("Winrate:", f"{wr:.1f}%")
                    tbl.add_row("EV/trade:", f"{ev:.4f}")
                    tbl.add_row("Total:", f"{pnl:.4f}")
                    tiles.append(Panel(tbl, title=f"{sym}"))
                row = []
                for i,p in enumerate(tiles,1):
                    row.append(p)
                    if len(row)==3:
                        grid.add_row(*row); row=[]
                if row:
                    while len(row)<3: row.append(Panel(""))
                    grid.add_row(*row)
                tbl_pairs = grid
            else:
                tbl_pairs = Table(title="Pairs", header_style="bold green")
                tbl_pairs.add_column("Symbol")
                tbl_pairs.add_column("Trades", justify="right")
                tbl_pairs.add_column("Winrate", justify="right")
                tbl_pairs.add_column("EV/trade", justify="right")
                tbl_pairs.add_column("Total", justify="right")
                for sym,d in sorted(pairs_use.items(), key=lambda kv: (-kv[1]['pnl'], kv[0])):
                    t = d['trades']; wrp = (d['wins']/t*100.0) if t else 0.0
                    ev = (d['pnl']/t) if t else 0.0
                    tbl_pairs.add_row(sym, str(t), f"{wrp:.1f}%", f"{ev:.4f}", f"{d['pnl']:.4f}")
            # Open positions
            tbl_pos = Table(title="Positions ouvertes", header_style="bold yellow")
            tbl_pos.add_column("Symbol")
            tbl_pos.add_column("Side")
            tbl_pos.add_column("Qty", justify="right")
            tbl_pos.add_column("Entry", justify="right")
            tbl_pos.add_column("Price", justify="right")
            tbl_pos.add_column("Value", justify="right")
            tbl_pos.add_column("PnL", justify="right")
            tbl_pos.add_column("PnL %", justify="right")
            tbl_pos.add_column("SL", justify="right")
            tbl_pos.add_column("SL %", justify="right")
            tbl_pos.add_column("TP", justify="right")
            tbl_pos.add_column("TP %", justify="right")
            tbl_pos.add_column("Trail stop", justify="right")
            tbl_pos.add_column("Trail %", justify="right")
            tbl_pos.add_column("Peak %", justify="right")
            tbl_pos.add_column("Hold", justify="right")
            open_count = 0
            for sym, st in sorted(filter_state(state, getattr(args,'symbol', None)).items()):
                if not isinstance(st, dict) or not st.get("in_position"): continue
                open_count += 1
                try:
                    from datetime import timezone as _tz
                    now_ts = datetime.now(_tz.utc).timestamp()
                except Exception:
                    now_ts = datetime.utcnow().timestamp()
                hold = fmt_dur(max(0.0, (now_ts - float(st.get("entry_time",0.0))))) if st.get("entry_time") else "-"
                # Live price
                pr_val = None
                try:
                    r = mon_client.get_price(sym)
                    if r.ok and r.data and "price" in r.data:
                        pr_val = float(r.data["price"])  # type: ignore[arg-type]
                except Exception:
                    pr_val = None
                entry = float(st.get('entry_price',0.0))
                qty = float(st.get('quantity',0.0))
                val_usdt = 0.0; pnl_usdt = 0.0; pnl_pct = 0.0
                if pr_val and entry:
                    val_usdt = pr_val * qty
                    pnl_usdt = (pr_val - entry) * qty if (st.get('side') or 'BUY') == 'BUY' else (entry - pr_val) * qty
                    pnl_pct = ((pr_val - entry)/entry*100.0) if (st.get('side') or 'BUY') == 'BUY' else ((entry - pr_val)/entry*100.0)
                try:
                    peak_pct = 0.0
                    if entry>0 and float(st.get('max_price_since_entry',0.0))>0:
                        peak_pct = (float(st.get('max_price_since_entry')) - entry) / entry * 100.0
                except Exception:
                    peak_pct = 0.0
                # SL/TP percent from entry and trailing stop
                sl = float(st.get('stop_loss',0.0)); tp = float(st.get('take_profit',0.0))
                sl_pct = ((sl/entry - 1.0)*100.0) if entry>0 and sl>0 else 0.0
                tp_pct = ((tp/entry - 1.0)*100.0) if entry>0 and tp>0 else 0.0
                # Derive trailing stop from peak and retrace config if applicable
                trail_stop = 0.0; trail_pct = 0.0
                try:
                    from json import loads as _loads
                    cfg = _J.loads(Path('pionex_futures_bot/spot2/config/config.json').read_text(encoding='utf-8')) if Path('pionex_futures_bot/spot2/config/config.json').exists() else {}
                    retrace = float(cfg.get('trailing_retrace_percent', 0.25))
                    peak_px = float(st.get('max_price_since_entry', 0.0))
                    if peak_px > 0:
                        trail_stop = peak_px * (1.0 - retrace/100.0)
                        if entry>0:
                            trail_pct = (trail_stop/entry - 1.0)*100.0
                except Exception:
                    trail_stop = 0.0; trail_pct = 0.0
                tbl_pos.add_row(
                    sym,
                    str(st.get("side","")),
                    f"{qty:.6f}",
                    f"{entry:.6f}",
                    f"{(pr_val if pr_val is not None else 0.0):.6f}",
                    f"{val_usdt:.2f}",
                    f"{pnl_usdt:.4f}",
                    f"{pnl_pct:.2f}%",
                    f"{sl:.6f}",
                    f"{sl_pct:.2f}%",
                    f"{tp:.6f}",
                    f"{tp_pct:.2f}%",
                    f"{trail_stop:.6f}",
                    f"{trail_pct:.2f}%",
                    f"{peak_pct:.2f}%",
                    hold,
                )
            # Recent trades
            tbl_last = Table(title="Derniers trades", header_style="bold cyan")
            tbl_last.add_column("Exit time")
            tbl_last.add_column("Symbol")
            tbl_last.add_column("Side")
            tbl_last.add_column("PnL", justify="right")
            tbl_last.add_column("Hold", justify="right")
            for row in recent:
                try:
                    pnl = float(row.get("pnl_usdt") or 0.0)
                    hold = float(row.get("hold_sec") or 0.0)
                except Exception:
                    pnl = 0.0; hold = 0.0
                tbl_last.add_row(str(row.get("exit_ts")), str(row.get("symbol")), str(row.get("side")), f"{pnl:.4f}", fmt_dur(hold))
            # Layout
            lay = Layout()
            lay.split_column(
                Layout(Panel(top, title="Spot2 Totaux", style="bold cyan"), size=5),
                Layout(tbl_pos, size=10),
                Layout(tbl_pairs, ratio=1),
                Layout(tbl_last, size=10),
                Layout(shortcuts_footer(getattr(args,'symbol',None)), size=1),
            )
            return lay

        def render_pairs_only():
            _, pairs, _, _, _ = load_summary()
            tbl = Table(title="Pairs - détails", header_style="bold green")
            tbl.add_column("Symbol"); tbl.add_column("Trades", justify="right"); tbl.add_column("Wins", justify="right"); tbl.add_column("Winrate", justify="right"); tbl.add_column("EV/trade", justify="right"); tbl.add_column("Total", justify="right")
            for sym,d in sorted(pairs.items(), key=lambda kv: (-kv[1]['pnl'], kv[0])):
                t=d['trades']; w=d['wins']; wr=(w/t*100.0) if t else 0.0; ev=(d['pnl']/t) if t else 0.0
                tbl.add_row(sym, str(t), str(w), f"{wr:.2f}%", f"{ev:.4f}", f"{d['pnl']:.4f}")
            return Layout(Panel(tbl, title="Pairs"))

        def render_positions_only():
            state = load_state()
            tbl = Table(title="Positions ouvertes", header_style="bold yellow")
            tbl.add_column("Symbol"); tbl.add_column("Side"); tbl.add_column("Qty", justify="right"); tbl.add_column("Entry", justify="right"); tbl.add_column("Price", justify="right"); tbl.add_column("Value", justify="right"); tbl.add_column("PnL", justify="right"); tbl.add_column("PnL %", justify="right"); tbl.add_column("SL", justify="right"); tbl.add_column("SL %", justify="right"); tbl.add_column("TP", justify="right"); tbl.add_column("TP %", justify="right"); tbl.add_column("Peak %", justify="right"); tbl.add_column("Hold", justify="right")
            for sym, st in sorted(state.items()):
                if not isinstance(st, dict) or not st.get("in_position"): continue
                try:
                    from datetime import timezone as _tz
                    now_ts = datetime.now(_tz.utc).timestamp()
                except Exception:
                    now_ts = datetime.utcnow().timestamp()
                hold = fmt_dur(max(0.0, (now_ts - float(st.get("entry_time",0.0))))) if st.get("entry_time") else "-"
                pr_val = None
                try:
                    r = mon_client.get_price(sym)
                    if r.ok and r.data and "price" in r.data:
                        pr_val = float(r.data["price"])  # type: ignore[arg-type]
                except Exception:
                    pr_val = None
                entry = float(st.get('entry_price',0.0)); qty = float(st.get('quantity',0.0))
                val_usdt = 0.0; pnl_usdt = 0.0; pnl_pct = 0.0
                if pr_val and entry:
                    val_usdt = pr_val * qty
                    pnl_usdt = (pr_val - entry) * qty if (st.get('side') or 'BUY') == 'BUY' else (entry - pr_val) * qty
                    pnl_pct = ((pr_val - entry)/entry*100.0) if (st.get('side') or 'BUY') == 'BUY' else ((entry - pr_val)/entry*100.0)
                sl = float(st.get('stop_loss',0.0)); tp = float(st.get('take_profit',0.0))
                sl_pct = ((sl/entry - 1.0)*100.0) if entry>0 and sl>0 else 0.0
                tp_pct = ((tp/entry - 1.0)*100.0) if entry>0 and tp>0 else 0.0
                try:
                    peak_pct = 0.0
                    if entry>0 and float(st.get('max_price_since_entry',0.0))>0:
                        peak_pct = (float(st.get('max_price_since_entry')) - entry) / entry * 100.0
                except Exception:
                    peak_pct = 0.0
                tbl.add_row(sym, str(st.get("side","")), f"{qty:.6f}", f"{entry:.6f}", f"{(pr_val if pr_val is not None else 0.0):.6f}", f"{val_usdt:.2f}", f"{pnl_usdt:.4f}", f"{pnl_pct:.2f}%", f"{sl:.6f}", f"{sl_pct:.2f}%", f"{tp:.6f}", f"{tp_pct:.2f}%", f"{peak_pct:.2f}%", hold)
            return Layout(Panel(tbl, title="Positions"))

        def render_trades_only():
            _, _, recent, _, _ = load_summary()
            tbl = Table(title="Derniers trades", header_style="bold cyan")
            tbl.add_column("Exit time"); tbl.add_column("Symbol"); tbl.add_column("Side"); tbl.add_column("PnL", justify="right"); tbl.add_column("Hold", justify="right"); tbl.add_column("Reason")
            for row in recent:
                try:
                    pnl = float(row.get("pnl_usdt") or 0.0); hold = float(row.get("hold_sec") or 0.0)
                except Exception:
                    pnl = 0.0; hold = 0.0
                tbl.add_row(str(row.get("exit_ts")), str(row.get("symbol")), str(row.get("side")), f"{pnl:.4f}", fmt_dur(hold), str(row.get("exit_reason")))
            return Layout(Panel(tbl, title="Trades"))

        def render_reasons_only():
            _, _, _, reasons, _ = load_summary()
            tbl = Table(title="Sorties par raison", header_style="bold magenta")
            tbl.add_column("Reason"); tbl.add_column("Count", justify="right")
            for k,v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
                tbl.add_row(str(k), str(v))
            out = Layout(); out.split_column(Layout(Panel(tbl, title="Exit reasons"), ratio=1), Layout(shortcuts_footer(getattr(args,'symbol',None)), size=1))
            return out

        def render_alerts_only():
            # Génère des alertes simples sur fenêtre des N derniers trades
            _, _, _, _, window_rows = load_summary()
            # Agrégats par paire
            by_sym: dict[str, dict[str, float]] = {}
            for row in window_rows:
                sym = (row.get("symbol") or "").strip()
                pnl = 0.0
                try:
                    pnl = float(row.get("pnl_usdt") or 0.0)
                except Exception:
                    pnl = 0.0
                reason = (row.get("exit_reason") or "").strip() or "UNKNOWN"
                d = by_sym.setdefault(sym, {"n":0.0, "wins":0.0, "pnl":0.0, "sl":0.0})
                d["n"] += 1
                d["pnl"] += pnl
                if pnl>0: d["wins"] += 1
                if reason == "SL": d["sl"] += 1
            # Règles: EV/trade<0 avec n>=5, SL rate>60% si n>=5
            alerts: list[tuple[str, str, float]] = []  # (symbol, message, score)
            for sym, d in by_sym.items():
                n = int(d.get("n",0.0)); wins = float(d.get("wins",0.0)); pnl = float(d.get("pnl",0.0)); slc = float(d.get("sl",0.0))
                if n >= 5:
                    ev = pnl / n if n else 0.0
                    wr = wins / n * 100.0
                    slr = slc / n * 100.0
                    if ev < 0.0:
                        alerts.append((sym, f"EV/trade négatif ({ev:.4f} USDT)", abs(ev)))
                    if slr >= 60.0:
                        alerts.append((sym, f"Taux SL élevé ({slr:.1f}%)", slr))
                    if wr <= 35.0:
                        alerts.append((sym, f"Winrate faible ({wr:.1f}%)", 100.0-wr))
            # Table
            tbl = Table(title=f"Alerts fenêtre {getattr(args,'window_trades',30)} trades", header_style="bold red")
            tbl.add_column("Symbol"); tbl.add_column("Alerte"); tbl.add_column("Score", justify="right")
            for sym, msg, sc in sorted(alerts, key=lambda t: -t[2]):
                tbl.add_row(sym, msg, f"{sc:.2f}")
            out = Layout(); out.split_column(Layout(Panel(tbl, title="Alerts"), ratio=1), Layout(shortcuts_footer(getattr(args,'symbol',None)), size=1))
            return out

            tbl.add_column("Reason"); tbl.add_column("Count", justify="right")
            for k,v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
                tbl.add_row(str(k), str(v))
            return Layout(Panel(tbl, title="Exit reasons"))

        console = Console()
        def render_view(current: str):
            if current == "dashboard":
                return render_dashboard()
            if current == "pairs":
                return render_pairs_only()
            if current == "positions":
                return render_positions_only()
            if current == "trades":
                return render_trades_only()
            if current == "reasons":
                return render_reasons_only()
            if current == "alerts":
                return render_alerts_only()
            return render_dashboard()

        current_view = str(getattr(args, "view", "dashboard"))
        current_symbol = str(getattr(args, "symbol", "") or "") or None
        cmd_buffer = ""
        with Live(render_view(current_view), console=console, refresh_per_second=max(1, int(1/max(0.001, args.interval)))) as live:
            try:
                while True:
                    time.sleep(max(1, int(args.interval)))
                    # Gestion des entrées clavier (Windows: msvcrt)
                    try:
                        import msvcrt  # type: ignore
                        if msvcrt.kbhit():
                            ch = msvcrt.getwch()
                            if not ch:
                                pass
                            else:
                                c = str(ch).lower()
                                if c == 'q':
                                    break
                                elif c == 'd': current_view = 'dashboard'
                                elif c == 'p': current_view = 'pairs'
                                elif c == 'o': current_view = 'positions'
                                elif c == 't': current_view = 'trades'
                                elif c == 'r': current_view = 'reasons'
                                elif c == 'a': current_view = 'alerts'
                                elif c == 'c': current_view = 'control'
                                elif c == 'f':
                                    # Prompt simple: tapez le symbole et Enter
                                    cmd_buffer = ""
                                    current_view = 'control'
                                elif c == 'f'.upper():
                                    current_symbol = None
                            # Mode contrôle: capture de ligne
                            if current_view == 'control':
                                line_chars = []
                                while msvcrt.kbhit():
                                    x = msvcrt.getwch()
                                    if x == '\r':
                                        break
                                    line_chars.append(x)
                                if line_chars:
                                    cmd_buffer += ''.join(line_chars)
                                if cmd_buffer.endswith('\n') or cmd_buffer.endswith('\r'):
                                    cmd_buffer = cmd_buffer.strip()
                                # Commandes: close:SYMBOL ou filter:SYMBOL
                                if cmd_buffer.lower().startswith('close:'):
                                    sym = cmd_buffer.split(':',1)[1].strip().upper()
                                    # Ecrire un drapeau force_close dans le fichier d'état pour que le bot clôture au prochain tick
                                    try:
                                        import json as _J
                                        cur = load_state()
                                        ent = cur.get(sym, {}) if isinstance(cur, dict) else {}
                                        ent['force_close'] = True
                                        cur[sym] = ent
                                        state_path.write_text(_J.dumps(cur, separators=(',',':')), encoding='utf-8')
                                    except Exception:
                                        pass
                                    cmd_buffer = ""
                                elif cmd_buffer.lower().startswith('filter:'):
                                    current_symbol = cmd_buffer.split(':',1)[1].strip().upper()
                                    setattr(args, 'symbol', current_symbol)
                                    cmd_buffer = ""
                    except Exception:
                        # Environnements non Windows: pas d'inputs, on reste sur --view
                        pass
                    live.update(render_view(current_view))
            except KeyboardInterrupt:
                return
    elif args.cmd == "symbols":
        # Utilise le client de spot2 par défaut pour l'endpoint public
        try:
            from pionex_futures_bot.spot2.clients.pionex_client import PionexClient  # type: ignore
        except Exception:
            from pionex_futures_bot.spot.clients.pionex_client import PionexClient  # type: ignore
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
        # Keep values as float for simplicity; cast to int when displaying
        by_symbol: dict[str, dict[str, float]] = {}
        def load_totals() -> None:
            nonlocal total, won, lost, n, n_win, n_loss, n_be, hold_sum, by_reason, by_symbol
            total = won = lost = hold_sum = 0.0
            n = n_win = n_loss = n_be = 0
            by_reason = {}
            by_symbol = {}
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
                    s = by_symbol.setdefault(
                        sym,
                        {"trades": 0.0, "wins": 0.0, "pnl": 0.0, "tp": 0.0, "sl": 0.0, "trail": 0.0},
                    )
                    s["trades"] += 1
                    s["pnl"] += pnl
                    if pnl > 0:
                        s["wins"] += 1
                    # Count exit reasons per symbol
                    if reason == "TP":
                        s["tp"] += 1
                    elif reason == "SL":
                        s["sl"] += 1
                    elif reason in {"TRAIL", "MICRO_TRAIL", "GAIN_TRAIL"}:
                        s["trail"] += 1

        load_totals()
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
                pnl_avg = (pnl_sum / t) if t else 0.0
                tp_c = int(agg.get("tp", 0))
                sl_c = int(agg.get("sl", 0))
                trail_c = int(agg.get("trail", 0))
                rows.append((s, t, wr, pnl_avg, pnl_sum, tp_c, sl_c, trail_c))
            # Single pairs recap table, sorted by PnL desc
            try:
                from rich.table import Table
                from rich.console import Console
                console = Console()
                tbl_pairs = Table(title="Pairs summary (sorted by total PnL)", show_header=True, header_style="bold green")
                tbl_pairs.add_column("Symbol")
                tbl_pairs.add_column("Trades", justify="right")
                tbl_pairs.add_column("Winrate", justify="right")
                tbl_pairs.add_column("PnL avg (USDT)", justify="right")
                tbl_pairs.add_column("Total (USDT)", justify="right")
                tbl_pairs.add_column("TP", justify="right")
                tbl_pairs.add_column("SL", justify="right")
                tbl_pairs.add_column("TRAIL", justify="right")
                for s, t, wr, pnl_avg, pnl_sum, tp_c, sl_c, trail_c in sorted(rows, key=lambda x: (-x[4], x[0])):
                    tbl_pairs.add_row(s, str(t), f"{wr:.2f}%", f"{pnl_avg:.4f}", f"{pnl_sum:.4f}", str(tp_c), str(sl_c), str(trail_c))
                console.print(tbl_pairs)
            except Exception:
                print("Pairs summary (sorted by total PnL):")
                for s, t, wr, pnl_avg, pnl_sum, tp_c, sl_c, trail_c in sorted(rows, key=lambda x: (-x[4], x[0])):
                    print(
                        f"  {s}: avg={pnl_avg:.4f} USDT | total={pnl_sum:.4f} USDT | trades={t} | winrate={wr:.2f}% | TP={tp_c} SL={sl_c} TRAIL={trail_c}"
                    )

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

        # Remove single best/worst panels in favor of tables below
        pass

        # Top N best/worst trades as tables
        if all_trades:
            N = int(args.top_trades) if (getattr(args, "top_trades", None) and args.top_trades > 0) else 5
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

        # Live watch mode (auto-refresh)
        if args.watch:
            try:
                from rich.live import Live
                from rich.layout import Layout
                from rich.align import Align
                from rich.text import Text
            except Exception:
                print("Install 'rich' to enable --watch UI: pip install rich")
                return

            # Lazy import to avoid heavy deps at top
            from pionex_futures_bot.spot2.clients import PionexClient

            state_path = Path(args.state)
            client = PionexClient(api_key="", api_secret="", base_url=args.base_url, dry_run=True)

            def render_once():
                # Load totals fresh
                load_totals()
                win_rate = (n_win / n * 100.0) if n else 0.0
                avg_hold = hold_sum / n if n else 0.0
                # Load state
                state = {}
                try:
                    import json as _J
                    if state_path.exists():
                        state = _J.loads(state_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    state = {}
                # Build open positions table
                tbl_pos = Table(title="Open positions", header_style="bold yellow")
                tbl_pos.add_column("Symbol")
                tbl_pos.add_column("Side")
                tbl_pos.add_column("Qty", justify="right")
                tbl_pos.add_column("Entry", justify="right")
                tbl_pos.add_column("Price", justify="right")
                tbl_pos.add_column("SL", justify="right")
                tbl_pos.add_column("TP", justify="right")
                tbl_pos.add_column("PnL (USDT)", justify="right")
                tbl_pos.add_column("PnL %", justify="right")
                tbl_pos.add_column("Hold", justify="right")
                open_count = 0
                for sym, st in sorted(state.items()):
                    try:
                        if not isinstance(st, dict) or not st.get("in_position"):
                            continue
                        open_count += 1
                        side = st.get("side") or ""
                        qty = float(st.get("quantity") or 0.0)
                        entry = float(st.get("entry_price") or 0.0)
                        sl = float(st.get("stop_loss") or 0.0)
                        tp = float(st.get("take_profit") or 0.0)
                        et = float(st.get("entry_time") or 0.0)
                        # Price
                        pr = None
                        r = client.get_price(sym)
                        if r.ok and r.data and "price" in r.data:
                            pr = float(r.data["price"])  # type: ignore[arg-type]
                        pnl = 0.0
                        pnlp = 0.0
                        hold = "-"
                        if pr and entry and qty:
                            if (side or "BUY") == "BUY":
                                pnl = (pr - entry) * qty
                                pnlp = (pr - entry) / entry * 100.0
                            else:
                                pnl = (entry - pr) * qty
                                pnlp = (entry - pr) / entry * 100.0
                        if et:
                            hold = fmt_dur(max(0.0, (datetime.utcnow() - datetime.utcfromtimestamp(et)).total_seconds()))
                        tbl_pos.add_row(
                            sym,
                            str(side),
                            f"{qty:.6f}",
                            f"{entry:.6f}",
                            f"{(pr if pr is not None else 0.0):.6f}",
                            f"{sl:.6f}",
                            f"{tp:.6f}",
                            f"{pnl:.4f}",
                            f"{pnlp:.2f}%",
                            hold,
                        )
                    except Exception:
                        continue
                # Totals panel
                try:
                    from rich.panel import Panel
                    totals = Panel.fit(
                        f"Open: {open_count}\nTrades: {n}  Wins: {n_win}  Losses: {n_loss}  BE: {n_be}\nWin rate: {win_rate:.2f}%\nPnL: {total:.4f} USDT (Won {won:.4f} / Lost -{lost:.4f})\nAvg hold: {fmt_dur(avg_hold)}",
                        title="Totals", style="bold cyan")
                except Exception:
                    totals = Text("Totals")
                lay = Layout()
                lay.split_column(
                    Layout(totals, size=7),
                    Layout(tbl_pos, ratio=1),
                )
                return lay

            try:
                from rich.console import Console
                console = Console()
                with Live(render_once(), console=console, refresh_per_second=max(1, int(1 / max(0.001, args.interval)) )) as live:
                    import time as _t
                    while True:
                        _t.sleep(max(1, int(args.interval)))
                        live.update(render_once())
            except KeyboardInterrupt:
                return

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


