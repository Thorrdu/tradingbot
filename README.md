# Pionex Bot (Spot)

Petit toolkit pragmatique pour Pionex. Il contient un bot Spot automatisé qui place des trades contrarians sur breakout, avec contrôles de risque stricts. Conçu pour tourner en sécurité sur PC ou VPS (Windows en priorité), CLI simple, dry‑run par défaut et logs centralisés.

## Points clés
- CLI: `python -m pionex_futures_bot spot --config <path>` (option `--print-config`)
- Dry‑run par défaut: aucun ordre réel tant que non désactivé dans la config
- Stratégie simple: breakout contrarian avec SL/TP fixes
- Résilience: persistance légère de l'état par symbole
- Backoff et rate limiting
- Sorties centralisées: logs, CSVs, états sous `pionex_futures_bot/logs/`

## Démarrage rapide

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
$env:LOG_LEVEL = "DEBUG"; py -m pionex_futures_bot spot --config .\pionex_futures_bot\config\config.json
```

- Debian Bash (session courante):
```bash
export LOG_LEVEL=DEBUG; python -m pionex_futures_bot spot --config ./pionex_futures_bot/config/config.json
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

### 2) Fichiers de configuration
Les configurations sont dans `pionex_futures_bot/config/`:
- Spot: `pionex_futures_bot/config/config.json`

Affichage de la config à tout moment:
```powershell
py -m pionex_futures_bot spot --print-config
```

### 3) Lancer
Depuis la racine du dépôt (`C:\\laragon\\www\\trading` sous Windows):

- Windows
```powershell
py -m pionex_futures_bot spot --config .\pionex_futures_bot\config\config.json
```

- Debian
```bash
python -m pionex_futures_bot spot --config ./pionex_futures_bot/config/config.json
```

### Wrappers optionnels
- Windows (jobs + logs):
```powershell
# Start
.\scripts\run.ps1 -Mode spot -Action start
# Tail
.\scripts\run.ps1 -Mode spot -Action tail
# Stop
.\scripts\run.ps1 -Mode spot -Action stop
```
- Debian (nohup + logs):
```bash
# Start
./scripts/run.sh spot start
# Tail
./scripts/run.sh spot tail
# Stop
./scripts/run.sh spot stop
```

## Stratégie (aperçu)
- Entry: breakout on the last check interval. If price dumps beyond `breakout_change_percent`, the bot BUYs; if it pumps above it, the bot SELLs (contrarian logic).
- Sizing: `position_usdt` notional; quantity computed from current price.
- Risk: fixed SL/TP from `stop_loss_percent` / `take_profit_percent`.
- Throttling: `max_open_trades` caps concurrent positions; `cooldown_sec` applies after an exit; `idle_backoff_sec` reduces market polling when the global cap is hit.

## Référence configuration (Spot)

- base_url: hôte API, défaut `https://api.pionex.com`.
- symbols: tableau de symboles, ex. `BTC_USDT`, `ETH_USDT`, `SOL_USDT`.
- leverage: indicateur optionnel (SPOT). N'affecte que la taille.
- position_usdt: notionnel par entrée (USDT).
- max_open_trades: plafond global de positions ouvertes.
- breakout_change_percent: variation absolue pour déclencher l'entrée (ex. 0.35 = ±0.35%).
- stop_loss_percent / take_profit_percent: distances fixes depuis le prix d'entrée.
- check_interval_sec: intervalle de polling.
- cooldown_sec: délai minimal après une sortie avant ré‑entrée.
- idle_backoff_sec: lorsque `max_open_trades` est atteint, dormir plus longtemps.
- dry_run: true/false. Conserver true jusqu'à pleine confiance.
- log_csv: chemin CSV des trades.
- state_file: chemin JSON de l'état runtime.

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
  - Haute volatilité: réduire légèrement `breakout_change_percent` et/ou augmenter `take_profit_percent`.

- Practical workflow
  1) Dry-run 1–3 days; inspect `logs/*bot.log` and `logs/*trades.csv`.
  2) Adjust 1 parameter at a time; document outcomes.
  3) When swapping to live: keep small `position_usdt`, `max_open_trades=1`.

## Sorties et logs
Tous les artefacts runtime sont sous `pionex_futures_bot/logs/`.
- Spot: `bot_dryrun.log`, `trades.csv`, `runtime_state.json`

CSV columns: timestamp, event, symbol, side, quantity, price, stop_loss, take_profit, order_id, pnl, reason, meta.

## Safety checklist
- Start with `dry_run=true`.
- Tail logs and inspect CSVs to validate behavior.
- Switch to real trading only after confirming stability; keep small `position_usdt` initially.

## Troubleshooting
- PowerShell activation errors: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- No price data: check connectivity, symbol normalization, and `base_url`
- 429/5xx: built-in exponential backoff; reduce frequency or wait

## Structure du projet
```
trading/
  README.md
  docs/
    pionex_futures_bot_setup.md
  pionex_futures_bot/
    clients/
    common/
    spot/
    config/
      config.json
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