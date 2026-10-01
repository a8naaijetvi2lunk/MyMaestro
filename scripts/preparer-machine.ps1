<#
.SYNOPSIS
    Prépare la machine avant MyMaestro : libère la mémoire engagée et le GPU.
.DESCRIPTION
    Détecte les applications gourmandes (liste de data/config.json → applications_a_fermer ; par défaut Chrome, Blender,
    Discord et l'overlay NVIDIA), Docker Desktop et la VM WSL, et Bonsai lancé à la main (port 8088). Affiche ce qui sera fermé et la mémoire engagée disponible, demande confirmation,
    puis ferme proprement, et de force ce qui résiste au bout de 10 s. Un Maestro lancé à la main (port 7860) est
    seulement signalé, car il peut être en plein rendu.
.PARAMETER Oui
    Ferme sans demander confirmation.
.PARAMETER Simulation
    Affiche seulement ce qui serait fermé ; rien n'est fermé.
#>
param([switch]$Oui, [switch]$Simulation)

$ErrorActionPreference = 'Continue'
$DelaiFermetureS = 10

# Configuration : data/config.json (ou MYMAESTRO_DONNEES\config.json) → applications_a_fermer, sinon les défauts.
$DossierDonnees = if ($env:MYMAESTRO_DONNEES) { $env:MYMAESTRO_DONNEES } else { Join-Path (Split-Path $PSScriptRoot -Parent) 'data' }
$Config = $null
$FichierConfig = Join-Path $DossierDonnees 'config.json'
try { $Config = Get-Content -Raw -Encoding UTF8 $FichierConfig -ErrorAction Stop | ConvertFrom-Json } catch {
    if (Test-Path -LiteralPath $FichierConfig) { Write-Warning "$FichierConfig illisible, réglages par défaut : $($_.Exception.Message)" }
}

# Présence de la clé (et non véracité) : une liste vide ou un 0 sont des réglages valides, comme côté Python.
$CleConfig = if ($Config) { @($Config.PSObject.Properties.Name) } else { @() }

# Noms EXACTS des processus : blender-mcp et docker-mcp (serveurs MCP de Claude Code) ne sont pas visés.
$MargeBrute = if ($env:MYMAESTRO_MARGE_MEMOIRE_GO) { $env:MYMAESTRO_MARGE_MEMOIRE_GO } elseif ($CleConfig -contains 'marge_memoire_go' -and $null -ne $Config.marge_memoire_go) { $Config.marge_memoire_go } else { 55 }
$MargeExigeeGo = 0.0
if (-not [double]::TryParse([string]$MargeBrute, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$MargeExigeeGo)) {
    Write-Warning "Marge de mémoire non numérique ('$MargeBrute') : 55 Go retenus."
    $MargeExigeeGo = 55.0
}
$Applications = @(
    @{ Nom = 'Chrome'; Processus = @('chrome') },
    @{ Nom = 'Blender'; Processus = @('blender') },
    @{ Nom = 'Discord'; Processus = @('Discord') },
    @{ Nom = 'Overlay NVIDIA'; Processus = @('NVIDIA Overlay') }
)
if ($CleConfig -contains 'applications_a_fermer' -and $null -ne $Config.applications_a_fermer) {
    $Applications = @($Config.applications_a_fermer | Where-Object { $_.nom -and $_.processus } |
        ForEach-Object { @{ Nom = [string]$_.nom; Processus = @($_.processus | ForEach-Object { [string]$_ }) } })
}
$ProcessusDocker = @('Docker Desktop', 'com.docker.backend', 'com.docker.build')

function MemoireDisponibleGo {
    $os = Get-CimInstance Win32_OperatingSystem
    return [math]::Round($os.FreeVirtualMemory / 1MB, 1)  # Ko -> Go (mémoire engagée encore disponible)
}

function MemoireDe([string[]] $noms) {
    $total = (Get-Process -Name $noms -ErrorAction SilentlyContinue | Measure-Object PrivateMemorySize64 -Sum).Sum
    if (-not $total) { return '' }
    if ($total -ge 1GB) { return '{0:N1} Go' -f ($total / 1GB) }
    return '{0:N0} Mo' -f ($total / 1MB)
}

function DistributionsWslActives {
    $sortie = & wsl.exe --list --running --quiet 2>$null
    return @($sortie | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
}

function PortEcoute([int] $port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function FermerProcessus([string[]] $noms) {
    $fenetres = 0
    foreach ($p in @(Get-Process -Name $noms -ErrorAction SilentlyContinue)) {
        if ($p.MainWindowHandle -ne 0) { [void]$p.CloseMainWindow(); $fenetres++ }
    }
    if ($fenetres -gt 0) {
        $limite = (Get-Date).AddSeconds($DelaiFermetureS)
        while ((Get-Process -Name $noms -ErrorAction SilentlyContinue) -and (Get-Date) -lt $limite) { Start-Sleep -Milliseconds 500 }
    }
    $restants = @(Get-Process -Name $noms -ErrorAction SilentlyContinue)
    if ($restants.Count -eq 0) { return 'fermé' }
    $restants | Stop-Process -Force -ErrorAction SilentlyContinue
    return 'fermé de force'
}

function FermerProcessusParId([int[]] $identifiants) {
    if (-not $identifiants -or $identifiants.Count -eq 0) { return 'rien à fermer' }
    $fenetres = 0
    foreach ($p in @(Get-Process -Id $identifiants -ErrorAction SilentlyContinue)) {
        if ($p.MainWindowHandle -ne 0) { [void]$p.CloseMainWindow(); $fenetres++ }
    }
    if ($fenetres -gt 0) {
        $limite = (Get-Date).AddSeconds($DelaiFermetureS)
        while ((Get-Process -Id $identifiants -ErrorAction SilentlyContinue) -and (Get-Date) -lt $limite) { Start-Sleep -Milliseconds 500 }
    }
    $restants = @(Get-Process -Id $identifiants -ErrorAction SilentlyContinue)
    if ($restants.Count -eq 0) { return 'fermé' }
    $restants | Stop-Process -Force -ErrorAction SilentlyContinue
    return 'fermé de force'
}

# --- Détection ---------------------------------------------------------------------------------------

$aFermer = New-Object System.Collections.Generic.List[object]
foreach ($app in $Applications) {
    if (Get-Process -Name $app.Processus -ErrorAction SilentlyContinue) {
        $aFermer.Add(@{ Nom = $app.Nom; Detail = MemoireDe $app.Processus; Type = 'processus'; Processus = $app.Processus })
    }
}
$dockerActif = [bool](Get-Process -Name $ProcessusDocker -ErrorAction SilentlyContinue)
$distributions = DistributionsWslActives
if ($dockerActif -or $distributions.Count -gt 0) {
    $detail = MemoireDe @('vmmem', 'vmmemWSL')
    if ($distributions.Count -gt 0) { $detail = "$detail · distributions en cours : $($distributions -join ', ')".Trim(' ·') }
    $aFermer.Add(@{ Nom = 'Docker Desktop et VM WSL'; Detail = $detail; Type = 'docker' })
}
# Le port 8088 n'est proposé à la fermeture que si son propriétaire est llama-server (Bonsai) ; sinon on le signale seulement.
$proprietaires8088 = @(Get-NetTCPConnection -LocalPort 8088 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
$bonsaiPids = @()
foreach ($idProprietaire in $proprietaires8088) {
    $processusPort = Get-Process -Id $idProprietaire -ErrorAction SilentlyContinue
    if ($processusPort -and $processusPort.ProcessName -eq 'llama-server') { $bonsaiPids += $idProprietaire }
    elseif ($processusPort) { Write-Host ("port 8088 occupé par {0} (non fermé)" -f $processusPort.ProcessName) -ForegroundColor Yellow }
}
if ($bonsaiPids.Count -gt 0) { $aFermer.Add(@{ Nom = 'Bonsai lancé à la main (port 8088)'; Detail = 'llama-server en écoute sur le port'; Type = 'bonsai' }) }
$maestroManuel = PortEcoute 7860

$avant = MemoireDisponibleGo
Write-Host ''
Write-Host '=== Préparation de la machine pour MyMaestro ===' -ForegroundColor Cyan
Write-Host ("Mémoire engagée disponible : {0} Go (MyMaestro en exige {1} pour démarrer Maestro)" -f $avant, $MargeExigeeGo)
if ($maestroManuel) {
    Write-Host '[!] Un Maestro lancé à la main écoute sur le port 7860 : ferme-le toi-même (il peut être en plein rendu).' -ForegroundColor Yellow
}
if ($aFermer.Count -eq 0) {
    Write-Host 'Rien à fermer.' -ForegroundColor Green
    exit 0
}
Write-Host ''
Write-Host 'Applications à fermer :'
foreach ($cible in $aFermer) {
    $suffixe = if ($cible.Detail) { " ($($cible.Detail))" } else { '' }
    Write-Host ("  - {0}{1}" -f $cible.Nom, $suffixe)
}
Write-Host "Fermeture propre d'abord, de force au bout de $DelaiFermetureS s. Les conteneurs Docker et les distributions WSL seront arrêtés." -ForegroundColor DarkGray

if ($Simulation) {
    Write-Host 'Simulation : rien n''est fermé.' -ForegroundColor Yellow
    exit 0
}
if (-not $Oui) {
    $reponse = Read-Host 'Fermer ces applications ? (O/n)'
    if ($reponse -match '^\s*n') {
        Write-Host "Rien n'est fermé." -ForegroundColor Yellow
        exit 0
    }
}

# --- Fermeture ---------------------------------------------------------------------------------------

foreach ($cible in $aFermer) {
    switch ($cible.Type) {
        'processus' { $resultat = FermerProcessus $cible.Processus }
        'docker' {
            if ($dockerActif) {
                & docker desktop stop 2>$null | Out-Null
                [void](FermerProcessus $ProcessusDocker)
            }
            & wsl.exe --shutdown 2>$null | Out-Null
            $resultat = 'arrêtés'
        }
        'bonsai' {
            [void](FermerProcessusParId $bonsaiPids)
            $resultat = if (PortEcoute 8088) { 'toujours actif : arrête-le à la main' } else { 'arrêté' }
        }
    }
    Write-Host ("  {0} : {1}" -f $cible.Nom, $resultat)
}

Start-Sleep -Seconds 2
$apres = MemoireDisponibleGo
Write-Host ''
Write-Host ("Mémoire engagée disponible : {0} Go (+{1:N1} Go)" -f $apres, ($apres - $avant))
if ($apres -lt $MargeExigeeGo) {
    Write-Host "[!] Toujours sous les $MargeExigeeGo Go exigés : MyMaestro refusera de démarrer Maestro. Ferme d'autres applications." -ForegroundColor Yellow
} else {
    Write-Host 'Machine prête.' -ForegroundColor Green
}
exit 0
