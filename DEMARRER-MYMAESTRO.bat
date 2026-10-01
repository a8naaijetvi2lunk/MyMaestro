@echo off
REM Lanceur MyMaestro : sert l'interface buildee et l'API sur http://127.0.0.1:7900
REM Texte en ASCII volontairement : la console Windows affiche mal les accents.
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
if not exist "ui\dist\index.html" (
  echo [!] Interface non construite. Lance d'abord : cd ui ^&^& npm run build
  pause
  exit /b 1
)
REM Libere la memoire engagee et le GPU (applications de data/config.json, Docker/WSL, Bonsai manuel...) : detection, confirmation, fermeture.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\preparer-machine.ps1"
echo MyMaestro demarre sur http://127.0.0.1:7900
start "" "http://127.0.0.1:7900"
cd server
uv run uvicorn mymaestro.app:app --host 127.0.0.1 --port 7900 --timeout-graceful-shutdown 3
pause
