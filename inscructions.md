# Instructions d’exécution — Pionex Futures Bot (Windows PowerShell)

## Pré‑requis
- Projet: `C:\laragon\www\trading\pionex_futures_bot`
- Fichier d’environnement: `pionex_futures_bot\.env` (API_KEY, API_SECRET)
- Config prudente: `pionex_futures_bot\config.json` (par défaut `dry_run: true`, `position_usdt: 25`, `max_open_trades: 1`)

## 1) Activer le venv (ou le créer si absent)
```powershell
# Se placer dans le dossier du bot
cd C:\laragon\www\trading\pionex_futures_bot

# Créer le venv simplement
py -m venv .venv

# Activer le venv pour la session courante
.\.venv\Scripts\Activate.ps1

# Mettre pip à jour et installer les dépendances (dans le venv)
py -m pip install --upgrade pip
pip install -r .\requirements.txt
```

Astuce: si l’activation échoue à cause de l’ExecutionPolicy, lancer temporairement:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
Puis relancer `.\.venv\Scripts\Activate.ps1`.

## 2) Démarrer le bot (avant‑plan)
```powershell
cd C:\laragon\www\trading\pionex_futures_bot
py bot.py
```

## 3) Démarrer le bot (arrière‑plan + logs)
```powershell
cd C:\laragon\www\trading\pionex_futures_bot
Start-Job -Name PionexBot -ScriptBlock {
  Set-Location 'C:\laragon\www\trading\pionex_futures_bot'
  . .\.venv\Scripts\Activate.ps1
  py bot.py *> 'bot_dryrun.log'
}
```

## 4) Vérifier les logs et le CSV
```powershell
Get-Content .\bot_dryrun.log -Tail 120
if (Test-Path .\trades.csv) { Get-Content .\trades.csv -Tail 10 } else { 'trades.csv not found' }
```

## 5) Arrêter le bot (mode job)
```powershell
if (Get-Job -Name PionexBot -ErrorAction SilentlyContinue) {
  Stop-Job -Name PionexBot -Force
  Remove-Job -Name PionexBot -Force
}
```

## 6) Passer en réel (plus tard, prudemment)
- Éditer `pionex_futures_bot\config.json`:
  - `dry_run: false`
  - `position_usdt`: 15–25 (au début)
  - `max_open_trades: 1`
- Relancer le bot (avant‑plan ou arrière‑plan).

## 7) Rappels utiles
- Procédures détaillées: `pionex_futures_bot\OPERATIONS.md`
- Redémarrer rapidement en arrière‑plan:
```powershell
# Stop puis relance
if (Get-Job -Name PionexBot -ErrorAction SilentlyContinue) { Stop-Job -Name PionexBot -Force; Remove-Job -Name PionexBot -Force }
Start-Job -Name PionexBot -ScriptBlock {
  Set-Location 'C:\laragon\www\trading\pionex_futures_bot'
  . .\.venv\Scripts\Activate.ps1
  py bot.py *> 'bot_dryrun.log'
}
```
