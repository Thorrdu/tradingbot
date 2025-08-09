# Pionex Bots (Spot & PERP)

A small, pragmatic trading toolkit for Pionex. It contains two simple automated bots (Spot and Perpetual Futures) that place contrarian breakout trades with strict risk controls. Designed to run safely on a home PC or VPS (Windows first), with unified CLI, dry-run by default, and centralized logs.

## Key features
- Unified CLI: `python -m pionex_futures_bot {spot|perp} --config <path>` (with `--print-config`)
- Dry-run first: no real orders until you explicitly disable it in the config
- Simple, explainable strategy: contrarian breakout with fixed SL/TP
- Resilience: lightweight state persistence per symbol to resume after restart
- Backoff & rate limiting to be API friendly
- Centralized outputs: logs, CSVs, and runtime state under `pionex_futures_bot/logs/`

## Quick Start

- Windows
```powershell
cd C:\laragon\www\trading\pionex_futures_bot
py -m venv .venv; . .\.venv\Scripts\Activate.ps1
pip install -r .\requirements.txt
Copy-Item .\env.example .\.env -Force  # fill API_KEY / API_SECRET
cd ..
py -m pionex_futures_bot spot --config .\pionex_futures_bot\config\config.json
```

- Debian
```bash
cd /path/to/trading/pionex_futures_bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
[ -f .env ] || cp env.example .env   # then fill API_KEY / API_SECRET
cd ..
python -m pionex_futures_bot spot --config ./pionex_futures_bot/config/config.json
```

### Logging / Debug

- Windows PowerShell (session courante):
```powershell
$env:LOG_LEVEL = "DEBUG"
py -m pionex_futures_bot spot --config .\pionex_futures_bot\config\config.json
# ou PERP
$env:LOG_LEVEL = "DEBUG"; py -m pionex_futures_bot perp --config .\pionex_futures_bot\config\perp_config.json
```

- Debian Bash (session courante):
```bash
export LOG_LEVEL=DEBUG
python -m pionex_futures_bot spot --config ./pionex_futures_bot/config/config.json
# ou PERP
export LOG_LEVEL=DEBUG; python -m pionex_futures_bot perp --config ./pionex_futures_bot/config/perp_config.json
```

- Via fichier `.env` (persistant): éditez `pionex_futures_bot/.env` et ajoutez:
```
LOG_LEVEL=DEBUG
```
Les scripts `run.ps1` et `run.sh` chargent l’environnement et écrivent les logs dans `pionex_futures_bot/logs/`.

## Getting Started

### 1) Install (Windows PowerShell)
```powershell
cd C:\laragon\www\trading\pionex_futures_bot
py -m venv .venv
. .\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -r .\requirements.txt
Copy-Item .\env.example .\.env -Force  # fill API_KEY / API_SECRET
```

### 1bis) Install (Debian Bash)
```bash
cd /path/to/trading/pionex_futures_bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp env.example .env   # then fill API_KEY / API_SECRET
```

### 2) Configuration files
Configuration lives in `pionex_futures_bot/config/`:
- Spot: `pionex_futures_bot/config/config.json`
- Perp: `pionex_futures_bot/config/perp_config.json`

Quick reference dump any time:
```powershell
py -m pionex_futures_bot spot --print-config
py -m pionex_futures_bot perp --print-config
```

### 3) Run
Run from the repository root (`C:\laragon\www\trading` on Windows):

- Windows
```powershell
# Spot
py -m pionex_futures_bot spot --config .\pionex_futures_bot\config\config.json
# Perp
py -m pionex_futures_bot perp --config .\pionex_futures_bot\config\perp_config.json
```

- Debian
```bash
python -m pionex_futures_bot spot --config ./pionex_futures_bot/config/config.json
python -m pionex_futures_bot perp --config ./pionex_futures_bot/config/perp_config.json
```

### Optional wrappers
- Windows (jobs + logs):
```powershell
# Start
.\scripts\run.ps1 -Mode spot -Action start
.\scripts\run.ps1 -Mode perp -Action start
# Tail
.\scripts\run.ps1 -Mode spot -Action tail
.\scripts\run.ps1 -Mode perp -Action tail
# Stop
.\scripts\run.ps1 -Mode spot -Action stop
.\scripts\run.ps1 -Mode perp -Action stop
```
- Debian (nohup + logs):
```bash
# Start
./scripts/run.sh spot start
./scripts/run.sh perp start
# Tail
./scripts/run.sh spot tail
./scripts/run.sh perp tail
# Stop
./scripts/run.sh spot stop
./scripts/run.sh perp stop
```

## Strategy (overview)
- Entry: breakout on the last check interval. If price dumps beyond `breakout_change_percent`, the bot BUYs; if it pumps above it, the bot SELLs (contrarian logic).
- Sizing: `position_usdt` notional; quantity computed from current price.
- Risk: fixed SL/TP from `stop_loss_percent` / `take_profit_percent`.
- Throttling: `max_open_trades` caps concurrent positions; `cooldown_sec` applies after an exit; `idle_backoff_sec` reduces market polling when the global cap is hit.

## Configuration reference
Applies to both Spot and PERP unless stated otherwise.

- base_url: API host, default `https://api.pionex.com`.
- symbols: array of symbols, e.g. `BTCUSDT`, `ETHUSDT`, `SOLUSDT`.
  - The PERP client normalizes UI formats like `SOL.PERP_USDT` and `BTC_USDT` to the API format `*_USDT_PERP`.
- leverage (Spot only): optional leverage indicator. Real leverage behavior depends on the venue; here it only affects sizing if used.
- position_usdt: target notional per entry (USDT).
- max_open_trades: global cap on open positions across all symbols.
- breakout_change_percent: absolute percent move between checks to trigger entry (e.g., 0.35 means ±0.35%).
- stop_loss_percent / take_profit_percent: fixed distances from entry price for SL/TP.
- check_interval_sec: polling interval for price checks and management.
- cooldown_sec: minimum time after exit before re-entry on the same symbol.
- idle_backoff_sec: when not in position and `max_open_trades` reached, sleep longer to save requests.
- dry_run: true/false. Keep true until you fully trust behavior.
- log_csv: CSV trade log path (e.g., `logs/trades.csv`, `logs/perp_trades.csv`).
- state_file: runtime state JSON path (e.g., `logs/runtime_state.json`, `logs/perp_state.json`).

## Parameter tuning tips

- Sensitivity vs noise
  - Lower `breakout_change_percent` → more signals, more noise. Higher → fewer but stronger signals.
  - Start with: majors (BTC/ETH): 0.35–0.50; fast alts (SOL/DOGE): 0.45–0.70.

- Polling and budget
  - `check_interval_sec`: 3–5s for responsive scalping; increase if hitting rate limits.
  - `idle_backoff_sec`: keep `max(10, 6×check_interval_sec)` to reduce calls when `max_open_trades` is reached.

- Risk/Reward
  - `stop_loss_percent`: 1.5–2.5; `take_profit_percent`: 2.5–4.0 (common starting pair: 2.0 / 3.0).
  - If too many small losses → raise `breakout_change_percent` or widen SL slightly; if exits miss moves → widen TP a bit.

- Capital allocation
  - `position_usdt`: 15–25 to validate; scale slowly after 1–2 stable weeks.
  - `max_open_trades`: keep 1 while validating; then 2 if capital and risk allow.

- Cooldown
  - `cooldown_sec` (e.g., 300s) prevents rapid re-entries after an exit; increase in choppy regimes.

- Market regimes
  - Low volatility/flat: raise `breakout_change_percent`, lower `check_interval_sec` priority; consider fewer symbols.
  - High volatility/trending: slightly reduce `breakout_change_percent` and/or increase `take_profit_percent`.

- PERP specifics
  - Symbols are normalized to `*_USDT_PERP`. Sizing uses `position_usdt / price` for `quantity`.
  - Keep `dry_run=true` first; confirm order flow in logs/CSV before live.

- Practical workflow
  1) Dry-run 1–3 days; inspect `logs/*bot.log` and `logs/*trades.csv`.
  2) Adjust 1 parameter at a time; document outcomes.
  3) When swapping to live: keep small `position_usdt`, `max_open_trades=1`.

## Outputs and logs
All runtime artifacts are under `pionex_futures_bot/logs/`.
- Spot: `bot_dryrun.log`, `trades.csv`, `runtime_state.json`
- PERP: `perp_bot.log`, `perp_trades.csv`, `perp_state.json`

CSV columns: timestamp, event, symbol, side, quantity, price, stop_loss, take_profit, order_id, pnl, reason, meta.

## Safety checklist
- Start with `dry_run=true`.
- Tail logs and inspect CSVs to validate behavior.
- Switch to real trading only after confirming stability; keep small `position_usdt` initially.

## Troubleshooting
- PowerShell activation errors: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- No price data: check connectivity, symbol normalization, and `base_url`
- 429/5xx: built-in exponential backoff; reduce frequency or wait

## Project structure
```
trading/
  README.md
  docs/
    pionex_futures_bot_setup.md
  pionex_futures_bot/
    clients/
    common/
    spot/
    perp/
    config/
      config.json
      perp_config.json
    logs/
    __main__.py
    requirements.txt
    env.example
  scripts/
    run.ps1
    run.sh
```

## Support

If this project is helpful, you can support me on Ko‑fi: [ko-fi.com/thorrdu](https://ko-fi.com/thorrdu).