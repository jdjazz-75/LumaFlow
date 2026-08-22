# LumaFlow v1.0 (2026-08-07)
# Installe les dependances (paquet Python lumaflow en mode editable, dependances npm) puis
# construit et lance le serveur LumaFlow (http://127.0.0.1:8000). A executer depuis PowerShell.
#
# Pas de $ErrorActionPreference = "Stop" ici : sous PowerShell 5.1, ça transforme toute ligne
# stderr d'un executable natif (pip, npm, et surtout la banniere de demarrage d'uvicorn) en
# erreur fatale qui interromprait le script au moment meme ou le serveur demarre. Les echecs
# reels sont detectes explicitement via $LASTEXITCODE ci-dessous.
Set-Location -Path $PSScriptRoot

function Test-CommandExists($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "=== LumaFlow : installation et lancement ===" -ForegroundColor Cyan

if (-not (Test-CommandExists "python")) {
    Write-Host "Erreur : Python 3.11+ introuvable dans le PATH." -ForegroundColor Red
    Write-Host "Installez-le depuis https://www.python.org/downloads/ puis relancez ce script." -ForegroundColor Red
    exit 1
}

if (-not (Test-CommandExists "npm")) {
    Write-Host "Erreur : Node.js/npm introuvable dans le PATH." -ForegroundColor Red
    Write-Host "Installez-le depuis https://nodejs.org/ puis relancez ce script." -ForegroundColor Red
    exit 1
}

Write-Host "`n[1/3] Installation du paquet Python lumaflow (mode editable)..." -ForegroundColor Yellow
python -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Echec de 'pip install -e .'" -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/3] Installation et construction de l'interface web..." -ForegroundColor Yellow
Push-Location "web"
try {
    if (-not (Test-Path "node_modules")) {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "Echec de 'npm install'" }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Echec de 'npm run build'" }
}
finally {
    Pop-Location
}

Write-Host "`n[3/3] Lancement du serveur LumaFlow (http://127.0.0.1:8000)..." -ForegroundColor Yellow
Write-Host "Le navigateur s'ouvrira automatiquement. Fermez cette fenetre ou faites Ctrl+C pour arreter le serveur.`n" -ForegroundColor Cyan
lumaflow
