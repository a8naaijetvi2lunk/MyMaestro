@echo off
REM Installeur MyMaestro : installe uv et les dependances du serveur. Les moteurs d'IA s'installent ensuite depuis l'ecran Moteurs.
REM Texte en ASCII volontairement : la console Windows affiche mal les accents.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\installer.ps1"
pause
