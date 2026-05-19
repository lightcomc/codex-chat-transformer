#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Install: https://www.python.org/downloads/" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

python "$ScriptDir/codex_manager_gui.py" @args
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Error occurred. Press Enter to close." -ForegroundColor Red
    Read-Host
}
