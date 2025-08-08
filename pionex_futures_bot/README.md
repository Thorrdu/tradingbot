# Pionex Trading Bots — Spot et PERP (Breakout Contrarien)

Prérequis: Python 3.10+.

## Installation rapide (Windows PowerShell)

```powershell
cd C:\laragon\www\trading
py -m venv pionex_futures_bot\.venv
.\pionex_futures_bot\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -r pionex_futures_bot\requirements.txt
Copy-Item pionex_futures_bot\env.example pionex_futures_bot\.env -Force
```

Éditez `pionex_futures_bot\.env` et placez vos clés API.

## Configuration

- Fichier: `pionex_futures_bot\config.json`
- Champs clés: `symbols`, `position_usdt`, `max_open_trades`, `breakout_change_percent`, `stop_loss_percent`, `take_profit_percent`, `cooldown_sec`, `dry_run`.

Par défaut `dry_run` est à `true` pour éviter tout ordre réel.

## Lancer le bot Spot

```powershell
cd C:\laragon\www\trading\pionex_futures_bot
py bot.py
```

Les logs de trades seront écrits dans `trades.csv`.

## Lancer le bot PERP (Futures)

```powershell
cd C:\laragon\www\trading\pionex_futures_bot
py perp_bot.py
```

Configuration dédiée: `pionex_futures_bot\perp_config.json` (par défaut `dry_run=true`).
Le client `perp_client.py` normalise automatiquement les symboles UI (`SOL.PERP_USDT`, `BTCUSDT`, `BTC_USDT`) vers le format API `*_USDT_PERP`.

## Monitoring (PowerShell)

- État du job
```powershell
Get-Job -Name PionexBot | Format-List Name,State,HasMoreData,PSBeginTime,PSEndTime
```

- Démarrer le bot Spot en arrière‑plan (avec logs)
```powershell
cd C:\laragon\www\trading\pionex_futures_bot
Start-Job -Name PionexBot -ScriptBlock {
  Set-Location 'C:\laragon\www\trading\pionex_futures_bot'
  . .\.venv\Scripts\Activate.ps1
  py bot.py *> 'bot_dryrun.log'
}
```

- Démarrer le bot PERP en arrière‑plan (avec logs)
```powershell
cd C:\laragon\www\trading\pionex_futures_bot
Start-Job -Name PionexPerp -ScriptBlock {
  Set-Location 'C:\laragon\www\trading\pionex_futures_bot'
  . .\.venv\Scripts\Activate.ps1
  py perp_bot.py *> 'perp_bot.log'
}
```

- Arrêter/Nettoyer les jobs (sans conditionnel)
```powershell
Stop-Job -Name PionexBot -Force -ErrorAction SilentlyContinue
Remove-Job -Name PionexBot -Force -ErrorAction SilentlyContinue
Stop-Job -Name PionexPerp -Force -ErrorAction SilentlyContinue
Remove-Job -Name PionexPerp -Force -ErrorAction SilentlyContinue
```

- Logs (tail et live)
```powershell
cd C:\laragon\www\trading\pionex_futures_b
Get-Content .\bot_dryrun.log -Tail 80
Get-Content .\bot_dryrun.log -Wait -Tail 50
Get-Content .\perp_bot.log -Tail 80
Get-Content .\perp_bot.log -Wait -Tail 50
```

- Rechercher des erreurs dans le log
```powershell
Select-String -Path .\bot_dryrun.log -Pattern 'error|exception|traceback' -CaseSensitive:$false
```

- Voir les dernières lignes du CSV
```powershell
Get-Content .\trades.csv -Tail 10
Get-Item .\trades.csv | Select-Object Name,Length,LastWriteTime
```

## Pourquoi `.venv` ? Puis-je le renommer ?
- `.venv` est un nom conventionnel compatible avec plusieurs IDE (auto‑détection) et « caché » sur certains outils.
- Vous pouvez le renommer (ex: `env`, `myenv`). Dans ce cas, adaptez simplement les chemins:
  - Création: `py -m venv .monenv`
  - Activation: `.\.monenv\Scripts\Activate.ps1`
  - Exécution: `py bot.py`

Remarques:
- Les endpoints utilisent une signature HMAC-SHA256.
- Spot: voir `pionex_client.py`.
- PERP: voir `perp_client.py` qui envoie les ordres MARKET via `/api/v1/trade/order` avec `symbol=*_USDT_PERP` et `size`.

## Robustesse & reprise après incident

- Persistance locale d’état (`runtime_state.json`) via `StateStore`:
  - Sauvegarde à l’entrée de position: `in_position`, `side`, `quantity`, `entry_price`, `stop_loss`, `take_profit`, `order_id`, `last_exit_time`.
  - Reprise au redémarrage: rechargement par symbole et remise en cohérence du compteur global de positions.
- Réconciliation côté API (best-effort): au redémarrage, si aucune persistance locale, le bot tente d’inférer une position ouverte à partir des derniers fills (`GET /api/v1/trade/fills`).
- Rate limit: limiteur 10 req/s par IP/compte, backoff exponentiel sur 429/5xx.
- Backoff symbole hors position quand `max_open_trades` atteint: évite des appels marché inutiles.

### Paramètres utiles (dans `config.json`)
- `idle_backoff_sec`: délai d’attente quand `max_open_trades` est atteint et que le symbole n’est pas en position (défaut: 6× `check_interval_sec`, min 10s).
- `dry_run`: true/false.
- `breakout_change_percent`, `check_interval_sec`.