$ErrorActionPreference = "Stop"
$Repo = "lightcomc/codex-chat-transformer"
$Branch = "main"
$CodexDir = if ($env:CODEX_DIR) { $env:CODEX_DIR } else { Join-Path $env:USERPROFILE ".codex" }
$Files = @(
    "codex_manager_gui.py",
    "codex_chat_transformer.py",
    "codex_manager.cmd",
    "codex_manager.ps1",
    "providers_template.json"
)

Write-Host "=== Codex Chat Transformer Installer ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python not found. Install: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $CodexDir | Out-Null

foreach ($f in $Files) {
    Write-Host "Downloading $f..."
    $url = "https://raw.githubusercontent.com/$Repo/$Branch/$f"
    $out = Join-Path $CodexDir $f
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
}

Write-Host ""
Write-Host "Installed to $CodexDir\" -ForegroundColor Green
Write-Host "Run: $CodexDir\codex_manager.cmd" -ForegroundColor Green
