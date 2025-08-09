param(
  [Parameter(Mandatory=$true)][ValidateSet('spot','perp')] [string]$Mode,
  [Parameter(Mandatory=$false)][ValidateSet('start','stop','tail')] [string]$Action = 'start',
  [Parameter(Mandatory=$false)] [string]$Config
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path $PSScriptRoot -Parent
$project = Join-Path $repoRoot 'pionex_futures_bot'
Set-Location $repoRoot

if (-not (Test-Path '.\.venv\Scripts\Activate.ps1')) {
  py -m venv .\.venv
}
. .\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip | Out-Null
if (Test-Path '.\requirements.txt') { pip install -r .\requirements.txt | Out-Null }

if (-not (Test-Path (Join-Path $project '.\.env')) -and (Test-Path (Join-Path $project '.\env.example'))) {
  Copy-Item (Join-Path $project '.\env.example') (Join-Path $project '.\.env') -Force
}

if (-not $Config) {
  $Config = if ($Mode -eq 'perp') { (Join-Path $project 'config\perp_config.json') } else { (Join-Path $project 'config\config.json') }
} else {
  if (-not [System.IO.Path]::IsPathRooted($Config)) {
    try { $Config = (Resolve-Path $Config).Path } catch { $Config = (Join-Path $repoRoot $Config) }
  }
}

$logsDir = Join-Path $project 'logs'
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }

$jobName = if ($Mode -eq 'spot') { 'PionexSpot' } else { 'PionexPerp' }
$logFile = if ($Mode -eq 'spot') { Join-Path $logsDir 'bot_dryrun.log' } else { Join-Path $logsDir 'perp_bot.log' }

if ($Action -eq 'start') {
  Write-Host "Launching $Mode with config: $Config"
  Start-Job -Name $jobName -ScriptBlock {
    param($Repo, $Cfg, $ModeInner, $LogPath)
    Set-Location $Repo
    . .\pionex_futures_bot\.venv\Scripts\Activate.ps1
    if ($ModeInner -eq 'spot') {
      py -m pionex_futures_bot spot --config $Cfg *> $LogPath
    } else {
      py -m pionex_futures_bot perp --config $Cfg *> $LogPath
    }
  } -ArgumentList $repoRoot, $Config, $Mode, $logFile | Out-Null
  Write-Host "Started job '$jobName'. Logs: $logFile"
} elseif ($Action -eq 'stop') {
  if (Get-Job -Name $jobName -ErrorAction SilentlyContinue) {
    Stop-Job -Name $jobName -Force
    Remove-Job -Name $jobName -Force
    Write-Host "Stopped job '$jobName'"
  } else {
    Write-Host "No job named '$jobName'"
  }
} elseif ($Action -eq 'tail') {
  if (Test-Path $logFile) {
    Get-Content $logFile -Wait -Tail 80
  } else {
    Write-Host "Log file not found: $logFile"
  }
}


