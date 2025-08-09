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


def _run_perp(config_path: str) -> None:
    from pionex_futures_bot.perp.bot import PerpBot

    _chdir_to_project_root()
    bot = PerpBot(config_path=config_path)
    bot.run()


def _print_config_example(kind: str) -> None:
    example_path = Path(__file__).resolve().parent / ("config/perp_config.json" if kind == "perp" else "config/config.json")
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
        description="CLI unifiée pour exécuter les bots Spot et PERP",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_spot = sub.add_parser("spot", help="Démarrer le bot Spot")
    p_spot.add_argument("--config", default="config/config.json", help="Chemin du fichier de configuration Spot")
    p_spot.add_argument("--print-config", action="store_true", help="Affiche un exemple de configuration et sort")

    p_perp = sub.add_parser("perp", help="Démarrer le bot PERP")
    p_perp.add_argument("--config", default="config/perp_config.json", help="Chemin du fichier de configuration PERP")
    p_perp.add_argument("--print-config", action="store_true", help="Affiche un exemple de configuration et sort")

    args = parser.parse_args()

    if args.cmd == "spot":
        if args.print_config:
            _print_config_example("spot")
            return
        _run_spot(args.config)
    elif args.cmd == "perp":
        if args.print_config:
            _print_config_example("perp")
            return
        _run_perp(args.config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()


