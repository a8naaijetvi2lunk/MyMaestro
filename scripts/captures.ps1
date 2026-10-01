<#
.SYNOPSIS
    Reproduit les captures d'écran de la documentation (docs/captures/*.png).
.DESCRIPTION
    Lance MyMaestro en mode démo (MYMAESTRO_MOTEURS_REELS=aucun) dans un dossier de données jetable,
    puis photographie chaque écran avec Chrome sans interface. Le serveur est arrêté et le dossier
    jetable supprimé même en cas d'erreur. Le dossier data/ de l'utilisateur n'est jamais touché.
    Les images sont d'abord écrites dans le dossier jetable : docs/captures n'est modifié que si
    tous les écrans ont réussi.
.PARAMETER Chrome
    Chemin de chrome.exe (par défaut : installation standard, sinon Get-Command chrome).
.PARAMETER Port
    Port local du serveur de démo (le port suivant sert au débogage de Chrome).
#>
param(
    [string]$Chrome = "",
    [int]$Port = 7911
)

$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $PSScriptRoot
$sortie = Join-Path $racine "docs\captures"

# Chrome : chemin fourni, installation standard, sinon le PATH.
if (-not $Chrome) {
    $standard = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    if (Test-Path $standard) {
        $Chrome = $standard
    } else {
        $commande = Get-Command chrome -ErrorAction SilentlyContinue
        if ($commande) { $Chrome = $commande.Source }
    }
}
if (-not $Chrome -or -not (Test-Path $Chrome)) {
    throw "Chrome est introuvable : passer -Chrome <chemin vers chrome.exe>."
}

# Les ports doivent être libres : un autre serveur déjà là répondrait à notre place (et on photographierait ses données).
function Assert-PortLibre([int]$numero) {
    $ecoute = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $numero)
    try {
        $ecoute.Start()
    } catch {
        throw "Le port $numero est déjà utilisé : libérer le port ou passer -Port <autre port>."
    } finally {
        try { $ecoute.Stop() } catch { }
    }
}
Assert-PortLibre $Port
Assert-PortLibre ($Port + 1)

$projet = "demo-nuit-blanche"
$recette = "recette-clip-nuit"
# Chaque écran porte un repère de contenu : le texte attendu (sans tenir compte de la casse) doit être affiché,
# dans le texte de la page ou dans la valeur d'un champ de saisie.
$ecrans = @(
    @{ Fichier = "01-projets.png";      Route = "#/projets";                      Repere = "Nuit blanche" },
    @{ Fichier = "02-ecriture.png";     Route = "#/projets/$projet/ecriture";     Repere = "Toit sous la pluie" },
    @{ Fichier = "03-prompts.png";      Route = "#/projets/$projet/prompts";      Repere = "Slow lateral" },
    @{ Fichier = "04-timeline.png";     Route = "#/projets/$projet/video";        Repere = "chanson.wav" },
    @{ Fichier = "05-recette.png";      Route = "#/recettes/$recette";            Repere = "Clip de nuit" },
    @{ Fichier = "06-file.png";         Route = "#/file";                         Repere = "Voie GPU" },
    @{ Fichier = "07-moteurs.png";      Route = "#/moteurs";                      Repere = "Carte graphique" },
    @{ Fichier = "08-bibliotheque.png"; Route = "#/bibliotheque";                 Repere = "Lina" }
)

$horodatage = Get-Date -Format "yyyyMMdd-HHmmss"
$jetable = Join-Path $env:TEMP "mymaestro-captures-$horodatage"
$processus = $null
$chromeProc = $null
$socket = $null
$ancien = @{
    Donnees = $env:MYMAESTRO_DONNEES
    Projets = $env:MYMAESTRO_PROJETS
    Medias  = $env:MYMAESTRO_MEDIAS
    Moteurs = $env:MYMAESTRO_MOTEURS_REELS
}

try {
    New-Item -ItemType Directory -Force -Path $jetable | Out-Null
    $projetsJetables = Join-Path $jetable "projets"
    $mediasJetables = Join-Path $jetable "medias"
    $brouillon = Join-Path $jetable "captures"
    New-Item -ItemType Directory -Force -Path $projetsJetables | Out-Null
    New-Item -ItemType Directory -Force -Path $mediasJetables | Out-Null
    New-Item -ItemType Directory -Force -Path $brouillon | Out-Null

    $env:MYMAESTRO_DONNEES = $jetable
    $env:MYMAESTRO_PROJETS = $projetsJetables
    $env:MYMAESTRO_MEDIAS = $mediasJetables
    $env:MYMAESTRO_MOTEURS_REELS = "aucun"

    $processus = Start-Process -FilePath "uv" `
        -ArgumentList @("run", "uvicorn", "mymaestro.app:app", "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory (Join-Path $racine "server") -WindowStyle Hidden -PassThru

    # Attente du serveur : 60 s au plus, mesurées à l'horloge (une requête lente ne rallonge pas l'attente).
    $url = "http://127.0.0.1:$Port"
    $pret = $false
    $chrono = [Diagnostics.Stopwatch]::StartNew()
    while ($chrono.Elapsed.TotalSeconds -lt 60) {
        if ($processus.HasExited) { throw "Le serveur s'est arrêté prématurément (code $($processus.ExitCode))." }
        try {
            $reponse = Invoke-WebRequest -Uri "$url/api/sante" -UseBasicParsing -TimeoutSec 2
            if ($reponse.StatusCode -eq 200) { $pret = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $pret) { throw "Le serveur n'a pas répondu sur $url/api/sante en 60 s." }

    # Le serveur qui répond doit être le nôtre, en mode démo : jamais de captures d'un moteur réel ni du data/ de l'utilisateur.
    $moteurs = Invoke-RestMethod -Uri "$url/api/moteurs" -TimeoutSec 10
    if ($moteurs.mode_demo -ne $true -or $processus.HasExited) {
        throw "Le serveur sur $url n'est pas notre serveur de démo (mode_demo absent ou processus arrêté) : captures annulées."
    }

    # Chrome sans interface, piloté par son protocole de débogage (aucune dépendance) : `--screenshot` seul photographie
    # la page dès l'événement load, avant que les données de l'API arrivent, et `--virtual-time-budget` ne rend jamais la
    # main (le flux d'événements SSE de l'interface garde une requête ouverte). On attend donc que « Chargement… » ait disparu.
    $portDebug = $Port + 1
    $profil = Join-Path $jetable "profil-chrome"
    $chromeProc = Start-Process -FilePath $Chrome -PassThru -WindowStyle Hidden -ArgumentList @(
        "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1600,1000",
        "--remote-debugging-port=$portDebug", "--user-data-dir=$profil", "about:blank")

    $pretChrome = $false
    for ($i = 0; $i -lt 30 -and -not $pretChrome; $i++) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$portDebug/json/version" -TimeoutSec 2 | Out-Null
            $pretChrome = $true
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $pretChrome) { throw "Chrome n'a pas ouvert son port de débogage ($portDebug)." }

    $script:idCdp = 0

    # Chaque appel au protocole de débogage a 30 s : un Chrome figé ne bloque pas le script.
    function Invoke-Cdp([string]$methode, [hashtable]$params = @{}) {
        $script:idCdp++
        $moi = $script:idCdp
        $delai = New-Object Threading.CancellationTokenSource 30000
        try {
            $json = @{ id = $moi; method = $methode; params = $params } | ConvertTo-Json -Depth 6 -Compress
            $octets = [Text.Encoding]::UTF8.GetBytes($json)
            $socket.SendAsync([ArraySegment[byte]]::new($octets), [Net.WebSockets.WebSocketMessageType]::Text, $true,
                $delai.Token).Wait()
            $tampon = New-Object byte[] 65536
            while ($true) {
                $flux = New-Object IO.MemoryStream
                do {
                    $lu = $socket.ReceiveAsync([ArraySegment[byte]]::new($tampon), $delai.Token).Result
                    $flux.Write($tampon, 0, $lu.Count)
                } until ($lu.EndOfMessage)
                $message = [Text.Encoding]::UTF8.GetString($flux.ToArray()) | ConvertFrom-Json
                if ($message.id -eq $moi) {
                    if ($message.error) { throw "CDP $methode : $($message.error.message)" }
                    return $message.result
                }
            }
        } catch [AggregateException] {
            throw "CDP $methode : pas de réponse de Chrome en 30 s ($($_.Exception.InnerException.Message))."
        } finally {
            $delai.Dispose()
        }
    }

    foreach ($ecran in $ecrans) {
        $png = Join-Path $brouillon $ecran.Fichier
        # Un onglet neuf par écran, refermé ensuite : l'interface garde un flux SSE ouvert, et Chrome plafonne à six
        # connexions par hôte, donc le septième écran d'un même onglet ne pourrait plus interroger l'API.
        $onglet = Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:$portDebug/json/new?about:blank"
        $socket = New-Object System.Net.WebSockets.ClientWebSocket
        $connexion = New-Object Threading.CancellationTokenSource 30000
        try { $socket.ConnectAsync([Uri]$onglet.webSocketDebuggerUrl, $connexion.Token).Wait() } finally { $connexion.Dispose() }
        # Fenêtre de 1600×1000 exactement, quel que soit le cadre de la fenêtre Chrome sans interface.
        Invoke-Cdp "Emulation.setDeviceMetricsOverride" @{ width = 1600; height = 1000; deviceScaleFactor = 1; mobile = $false } | Out-Null
        Invoke-Cdp "Page.navigate" @{ url = "$url/$($ecran.Route)" } | Out-Null

        # Attente de l'écran rendu : 20 s au plus. Rendu = plus de « Chargement », le repère attendu affiché
        # (texte de la page ou valeur d'un champ) et aucun « API injoignable » ; puis une pause pour les transitions.
        $repere = (ConvertTo-Json -InputObject $ecran.Repere -Compress).ToLower()
        $expression = "(function(){var t=document.body?document.body.innerText:'';" +
            "document.querySelectorAll('textarea,input').forEach(function(c){t+=' '+c.value});" +
            "t=t.toLowerCase();return t.indexOf('chargement…')<0&&location.hash!==''" +
            "&&t.indexOf('api injoignable')<0&&t.indexOf($repere)>=0})()"
        $rendu = $false
        for ($i = 0; $i -lt 40 -and -not $rendu; $i++) {
            Start-Sleep -Milliseconds 500
            $etat = Invoke-Cdp "Runtime.evaluate" @{ returnByValue = $true; expression = $expression }
            $rendu = [bool]$etat.result.value
        }
        if (-not $rendu) {
            $texte = (Invoke-Cdp "Runtime.evaluate" @{ returnByValue = $true; expression = "document.body.innerText" }).result.value
            throw "L'écran $($ecran.Fichier) ne s'est pas rendu en 20 s avec le repère « $($ecran.Repere) » ($($ecran.Route)). Texte affiché : $texte"
        }
        Start-Sleep -Seconds 4

        $image = Invoke-Cdp "Page.captureScreenshot" @{ format = "png" }
        [IO.File]::WriteAllBytes($png, [Convert]::FromBase64String($image.data))
        $socket.Dispose()
        $socket = $null
        Invoke-RestMethod -Uri "http://127.0.0.1:$portDebug/json/close/$($onglet.id)" | Out-Null
        Write-Host ("{0} : {1} Ko" -f $ecran.Fichier, [math]::Round((Get-Item $png).Length / 1KB))
    }

    # Tous les écrans ont réussi : seulement maintenant, les images remplacent celles de la documentation.
    New-Item -ItemType Directory -Force -Path $sortie | Out-Null
    foreach ($ecran in $ecrans) {
        Move-Item -LiteralPath (Join-Path $brouillon $ecran.Fichier) -Destination (Join-Path $sortie $ecran.Fichier) -Force
    }
}
finally {
    if ($socket) { $socket.Dispose() }
    if ($chromeProc -and -not $chromeProc.HasExited) {
        & taskkill /PID $chromeProc.Id /T /F | Out-Null
    }
    if ($processus -and -not $processus.HasExited) {
        & taskkill /PID $processus.Id /T /F | Out-Null
    }
    $env:MYMAESTRO_DONNEES = $ancien.Donnees
    $env:MYMAESTRO_PROJETS = $ancien.Projets
    $env:MYMAESTRO_MEDIAS = $ancien.Medias
    $env:MYMAESTRO_MOTEURS_REELS = $ancien.Moteurs
    # Garde-fou : on ne supprime que le dossier jetable créé ci-dessus.
    if ($jetable -like "*\mymaestro-captures-*" -and (Test-Path $jetable)) {
        Start-Sleep -Seconds 1
        Remove-Item -LiteralPath $jetable -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $jetable) { Write-Warning "Le dossier jetable n'a pas pu être supprimé : $jetable (à effacer à la main)." }
    }
}
