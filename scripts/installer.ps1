<#
.SYNOPSIS
    Installe le strict minimum de MyMaestro : uv et les dépendances Python du serveur.
.DESCRIPTION
    Vérifie Windows 64 bits et le pilote NVIDIA, installe uv s'il manque, lance `uv sync --frozen` dans server/,
    contrôle que l'interface est construite (ui/dist), puis propose de lancer DEMARRER-MYMAESTRO.bat.
    Les moteurs d'IA (Maestro, ffmpeg, DLSS 5, Bonsai, Claude) ne sont PAS installés ici : ils se téléchargent
    depuis l'écran « Moteurs » de MyMaestro.
#>
$ErrorActionPreference = 'Stop'
$Racine = Split-Path $PSScriptRoot -Parent

function Arreter([string]$Message) {
    Write-Host "[!] $Message" -ForegroundColor Red
    exit 1
}

# 1. Windows 64 bits uniquement.
if (-not [Environment]::Is64BitOperatingSystem) {
    Arreter "MyMaestro exige un Windows 64 bits."
}

# 2. Pilote NVIDIA (le mode démo reste possible sans GPU).
if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    if ($env:MYMAESTRO_MOTEURS_REELS -eq 'aucun') {
        Write-Host "[!] Pilote NVIDIA introuvable : poursuite en mode démo (moteurs simulés)." -ForegroundColor Yellow
    } else {
        Write-Host "[!] Pilote NVIDIA introuvable (nvidia-smi)." -ForegroundColor Yellow
        Write-Host "    Installe le pilote NVIDIA pour utiliser les moteurs réels."
        Write-Host "    Sans GPU, pour le mode démo : dans une console, set MYMAESTRO_MOTEURS_REELS=aucun"
        Write-Host "    puis relance INSTALLER.bat depuis cette même console."
        Arreter "Installation interrompue : pilote NVIDIA introuvable."
    }
}

# 3. uv, s'il manque.
$DossierUv = Join-Path $env:USERPROFILE '.local\bin'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installation de uv..."
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Arreter "Installation de uv impossible : $($_.Exception.Message)"
    }
}
if (($env:PATH -split ';') -notcontains $DossierUv) {
    $env:PATH = "$DossierUv;$env:PATH"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Arreter "uv reste introuvable après son installation. Ouvre un nouveau terminal et relance INSTALLER.bat."
}

# 4. Dépendances du serveur.
Write-Host "Installation des dépendances du serveur (uv sync --frozen)..."
Push-Location (Join-Path $Racine 'server')
try {
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) { Arreter "uv sync a échoué (code $LASTEXITCODE)." }
} finally {
    Pop-Location
}

# 5. Interface construite.
if (-not (Test-Path -LiteralPath (Join-Path $Racine 'ui\dist\index.html'))) {
    Write-Host "[!] L'interface n'est pas construite (ui\dist\index.html introuvable)." -ForegroundColor Yellow
    Write-Host "    Télécharge l'archive de la release (interface déjà construite) ou construis l'interface :"
    Write-Host "    cd ui ; npm ci ; npm run build"
    Arreter "Installation interrompue : interface non construite."
}

Write-Host ""
Write-Host "Installation terminée. Les moteurs d'IA s'installent depuis l'écran « Moteurs » de MyMaestro." -ForegroundColor Green
$Reponse = Read-Host "Lancer MyMaestro maintenant ? (O/n)"
if ($Reponse -eq '' -or $Reponse -match '^[oOyY]') {
    Start-Process -FilePath (Join-Path $Racine 'DEMARRER-MYMAESTRO.bat') -WorkingDirectory $Racine
}
