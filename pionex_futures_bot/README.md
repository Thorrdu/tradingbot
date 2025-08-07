# Pionex Futures Bot (Breakout Contrarien)

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

## Lancer le bot

```powershell
cd C:\laragon\www\trading\pionex_futures_bot
py bot.py
```

Les logs de trades seront écrits dans `trades.csv`.

## Monitoring (PowerShell)

- État du job
```powershell
Get-Job -Name PionexBot | Format-List Name,State,HasMoreData,PSBeginTime,PSEndTime
```

- Démarrer en arrière‑plan (avec logs)
```powershell
cd C:\laragon\www\trading\pionex_futures_bot
Start-Job -Name PionexBot -ScriptBlock {
  Set-Location 'C:\laragon\www\trading\pionex_futures_bot'
  . .\.venv\Scripts\Activate.ps1
  py bot.py *> 'bot_dryrun.log'
}
```

- Arrêter/Nettoyer le job (sans conditionnel)
```powershell
Stop-Job -Name PionexBot -Force -ErrorAction SilentlyContinue
Remove-Job -Name PionexBot -Force -ErrorAction SilentlyContinue
```

- Logs (tail et live)
```powershell
cd C:\laragon\www\trading\pionex_futures_b
Get-Content .\bot_dryrun.log -Tail 80
Get-Content .\bot_dryrun.log -Wait -Tail 50
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

Remarque: Les endpoints utilisés imitent une API de style MBX (signature HMAC-SHA256). Vérifiez les spécifications Pionex réelles et adaptez `pionex_client.py` si nécessaire. 