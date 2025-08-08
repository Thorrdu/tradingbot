# Journal d’opérations — Pionex Futures Bot (Windows PowerShell)

## Objectif
Tests prudents en mode dry-run, puis montée progressive. Capital disponible: ~169 USDT. Ne pas engager tout le solde d’un coup.

## Environnement
- OS: Windows
- Shell: PowerShell
- Python: utiliser `py` pour créer le venv, puis exécuter via `py` et installer via `pip` après activation.
- Venv: `.venv`

## Configuration actuelle (réduite pour test)
- `position_usdt`: 25
- `max_open_trades`: 1
- `dry_run`: true
- Paires: BTCUSDT, ETHUSDT, SOLUSDT
- SL/TP: -2% / +3%
- Cooldown: 300s

## Procédures PowerShell (simples)
- Créer/activer venv:
  ```powershell
  cd C:\laragon\www\trading\pionex_futures_bot
  py -m venv .venv
  .\.venv\Scripts\Activate.ps1
  py -m pip install --upgrade pip
  pip install -r .\requirements.txt
  ```
- Copier l’environnement:
  ```powershell
  Copy-Item .\env.example .\.env -Force
  ```
- Lancer le bot (avant‑plan):
  ```powershell
  py bot.py
  ```
- Lancer le bot (arrière‑plan + logs):
  ```powershell
  Start-Job -Name PionexBot -ScriptBlock {
    Set-Location 'C:\laragon\www\trading\pionex_futures_bot'
    . .\.venv\Scripts\Activate.ps1
    py bot.py *> 'bot_dryrun.log'
  }
  ```
- Lire les logs:
  ```powershell
  Get-Content .\bot_dryrun.log -Tail 80
  ```
- Lire le CSV des trades:
  ```powershell
  if (Test-Path .\trades.csv) { Get-Content .\trades.csv -Tail 10 } else { 'trades.csv not found' }
  ```
- Arrêter le bot (job):
  ```powershell
  if (Get-Job -Name PionexBot -ErrorAction SilentlyContinue) {
    Stop-Job -Name PionexBot -Force
    Remove-Job -Name PionexBot -Force
  }
  ```

## Erreurs fréquentes et corrections
- Syntaxes Bash (e.g. `| cat`, `<< 'PY'`) → utiliser uniquement des cmdlets PowerShell.
- Exécuter hors venv → activer d’abord `.\.venv\Scripts\Activate.ps1`, puis utiliser `py`/`pip`.

## Routine de test (sécurisée)
1) Garder `dry_run=true`.
2) Démarrer en arrière‑plan et surveiller les logs/CSV.
3) Si stable, passer `dry_run=false` avec `position_usdt<=25`, `max_open_trades=1`.

## Historique (résumé)
- Création structure, config prudente, simplification des commandes avec `.venv` et utilisation stricte de `py`/`pip`.

## Robustesse & reprise
- Persistance locale: `runtime_state.json` conserve l’état minimal par symbole (position ouverte, côté, qty, entry, SL/TP, order_id, last_exit_time).
- Réconciliation API (best‑effort): au démarrage, si absence d’état local, le bot consulte les fills récents (`GET /api/v1/trade/fills`) pour inférer une position ouverte.
- Limiteur de débit: 10 req/s (IP et compte) avec backoff exponentiel sur 429/5xx.
- Économie d’appels quand `max_open_trades` atteint: `idle_backoff_sec` pour les symboles sans position.

### Paramètres utiles (`config.json`)
- `idle_backoff_sec`: backoff quand le symbole n’est pas en position et que la limite globale est atteinte. Défaut: `max(10, 6 * check_interval_sec)`.
- `log_csv`: fichier de journal des trades.
- `state_file`: fichier de persistance (défaut: `runtime_state.json`).

### Niveaux de logs
- Session PowerShell:
  ```powershell
  $env:LOG_LEVEL='DEBUG'
  py bot.py
  ```
- En job:
  ```powershell
  Start-Job -Name PionexBot -ScriptBlock {
    Set-Location 'C:\laragon\www\trading\pionex_futures_bot'
    . .\.venv\Scripts\Activate.ps1
    $env:LOG_LEVEL='DEBUG'
    py bot.py *> 'bot_dryrun.log'
  }
  ```

### Monitoring rapide
- État du job:
  ```powershell
  Get-Job -Name PionexBot | Format-List Name,State,HasMoreData,PSBeginTime,PSEndTime
  ```
- Logs (tail/live):
  ```powershell
  Get-Content .\bot_dryrun.log -Tail 80
  Get-Content .\bot_dryrun.log -Wait -Tail 50
  ```
- Dernières lignes CSV:
  ```powershell
  Get-Content .\trades.csv -Tail 10
  ```
- Arrêt/nettoyage:
  ```powershell
  Stop-Job -Name PionexBot -Force -ErrorAction SilentlyContinue
  Remove-Job -Name PionexBot -Force -ErrorAction SilentlyContinue
  ```
