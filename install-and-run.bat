@echo off
setlocal

rem LumaFlow v1.0 (2026-08-07)
rem Installe les dependances (paquet Python lumaflow en mode editable, dependances npm) puis
rem construit et lance le serveur LumaFlow (http://127.0.0.1:8000). A executer depuis l'Invite de
rem commandes (cmd.exe).

cd /d "%~dp0"

echo === LumaFlow : installation et lancement ===

where python >nul 2>&1
if errorlevel 1 (
    echo Erreur : Python 3.11+ introuvable dans le PATH.
    echo Installez-le depuis https://www.python.org/downloads/ puis relancez ce script.
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo Erreur : Node.js/npm introuvable dans le PATH.
    echo Installez-le depuis https://nodejs.org/ puis relancez ce script.
    exit /b 1
)

echo.
echo [1/3] Installation du paquet Python lumaflow (mode editable)...
python -m pip install -e .
if errorlevel 1 (
    echo Echec de "pip install -e ."
    exit /b 1
)

echo.
echo [2/3] Installation et construction de l'interface web...
cd web
if not exist node_modules (
    call npm install
    if errorlevel 1 (
        echo Echec de "npm install"
        cd ..
        exit /b 1
    )
)
call npm run build
if errorlevel 1 (
    echo Echec de "npm run build"
    cd ..
    exit /b 1
)
cd ..

echo.
echo [3/3] Lancement du serveur LumaFlow (http://127.0.0.1:8000)...
echo Le navigateur s'ouvrira automatiquement. Fermez cette fenetre ou faites Ctrl+C pour arreter le serveur.
echo.
lumaflow

endlocal
