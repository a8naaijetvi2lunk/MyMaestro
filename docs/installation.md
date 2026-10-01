# Installation

MyMaestro est une application locale pour Windows. Elle se compose d'un serveur Python (FastAPI) et d'une interface React déjà construite dans la release. Les moteurs d'IA qu'elle pilote ne sont pas dans l'archive : ils s'installent depuis l'écran « Moteurs ».

## Prérequis

| Élément | Détail |
|---|---|
| Système | Windows 10 ou 11, 64 bits |
| GPU | NVIDIA. 12 Go de VRAM recommandés : le projet a été développé et mesuré sur une carte de 12 Go |
| Mémoire engagée | 64 Go de RAM, ou un grand fichier d'échange. Les gros rendus vidéo font monter la mémoire engagée d'environ 50 Go au-dessus du repos ; MyMaestro exige une marge de 55 Go avant de démarrer Maestro (réglable, voir plus bas) |
| Disque | Environ 170 Go pour les moteurs et leurs modèles (voir le tableau par moteur ci-dessous : environ 110 Go à l'installation de Maestro, plus environ 50 Go au premier usage de H3, FlashVSR, MMAudio et Whisper), plus la place des projets. Chaque rendu existe deux fois : dans le projet et dans le dossier de sortie de Maestro |
| Python | Installé par `uv` (Python 3.12 pour le serveur) |
| Abonnement Claude | Facultatif : l'écriture et les prompts passent par Claude (Opus) par défaut ; sans Claude, Bonsai les prend. Sans aucun des deux, l'écriture est bloquée |

Pour construire l'interface vous-même (et non depuis la release), Node.js et npm sont nécessaires : `cd ui && npm ci && npm run build`.

## Étapes

1. Téléchargez la dernière release (l'interface y est déjà construite) et décompressez-la où vous voulez (un disque avec beaucoup de place de préférence).
2. Lancez `INSTALLER.bat`. Il refuse un Windows 32 bits, exige le pilote NVIDIA (`nvidia-smi`, sauf en mode démo : voir plus bas), installe `uv` s'il manque, installe les dépendances Python du serveur (`uv sync --frozen`), vérifie que `ui/dist/index.html` existe, puis propose de lancer MyMaestro. Si l'interface n'est pas construite (archive du dépôt au lieu de la release) : `cd ui ; npm ci ; npm run build`.
3. Lancez `DEMARRER-MYMAESTRO.bat`. Le lanceur :
   - propose de fermer les applications gourmandes (voir « Applications à fermer ») ;
   - démarre le serveur sur http://127.0.0.1:7900 et ouvre cette adresse dans le navigateur.
4. Ouvrez l'écran « Moteurs ». Au premier lancement, si un moteur requis manque (et hors mode démo), MyMaestro vous y amène une fois par session. Chaque carte donne l'état du moteur (Absent, Installé, Installé (externe), Version différente, Incomplet, Installation…), la version attendue, l'espace nécessaire et un bouton : « Installer », « Réessayer », « Réinstaller » ou, pour Claude installé mais déconnecté, « Se connecter ». Le moteur est téléchargé à une version épinglée, son empreinte (sha256) est vérifiée, puis il est installé dans `moteurs/<moteur>`, avec une barre de progression (indéterminée tant que la progression n'est pas connue), un bouton « Annuler » (qui arrête aussi la commande d'installation en cours, avec ses sous-processus) et, en cas d'échec, le chemin du journal (`data/journaux/installation-<moteur>-*.log`). Une seule installation tourne à la fois. Une installation réussie supprime le dossier `.telechargements/` du moteur (les archives devenues inutiles). Après une installation réussie, redémarrez MyMaestro pour qu'il pilote le moteur : tant que ce n'est pas fait, un job qui vise ce moteur est refusé avec le message « vient d'être installé : redémarre MyMaestro ». Maestro et ffmpeg sont requis pour produire des clips ; les autres sont facultatifs (voir [`moteurs.md`](moteurs.md)).

Claude s'installe avec l'installeur officiel d'Anthropic (dans le profil de l'utilisateur) ; la connexion se termine dans un terminal ouvert par le bouton « Se connecter », et l'écran relit l'état quand vous revenez sur l'onglet.

Un moteur désigné par une variable d'environnement (`MYMAESTRO_MAESTRO_APP`, `MYMAESTRO_DLSS5`, `MYMAESTRO_BONSAI`) est « externe » : considéré comme installé, jamais modifié ni réinstallé.

### Tailles par moteur

Le téléchargement et l'espace disque nécessaire sont deux chiffres différents : l'espace nécessaire (`espace_mo` du manifeste) est contrôlé avant de démarrer et compte aussi ce que l'installation écrit (extraction, environnement Python, modèles préchargés). Une reprise (« Réessayer ») ne redemande que ce qui reste.

| Moteur | Téléchargement | Espace disque nécessaire |
|---|---|---|
| ffmpeg | 0,15 Go | 0,5 Go |
| Maestro | l'archive, les dépendances Python et les modèles préchargés (Qwen ≈ 31 Go, LTX-2.3 ≈ 44 Go, assets ≈ 5 Go) ; au premier usage, H3 ≈ 34 Go, FlashVSR ≈ 4 Go, MMAudio ≈ 11 Go et Whisper ≈ 0,5 Go | environ 110 Go (plus environ 50 Go au premier usage) |
| DLSS 5 | 0,5 Go | 3 Go |
| Bonsai | ≈ 7,9 Go | 9,5 Go |
| Claude | faible (CLI, installeur officiel d'Anthropic) | 0,5 Go |

Pour essayer l'application sans GPU, dans une même console :

```bat
set MYMAESTRO_MOTEURS_REELS=aucun
INSTALLER.bat
```

Sans pilote NVIDIA, `INSTALLER.bat` poursuit alors en mode démo au lieu de s'arrêter. Répondez `O` à sa question finale (« Lancer MyMaestro maintenant ? ») : il démarre MyMaestro dans une nouvelle fenêtre, qui hérite de la variable. Ne lancez pas `DEMARRER-MYMAESTRO.bat` en plus : cela démarrerait un second serveur.

Tous les moteurs d'IA sont alors simulés, mais ffmpeg reste nécessaire (dans `moteurs/ffmpeg` ou sur le PATH) pour l'envoi de la chanson, les clips simulés et l'export. Les projets de démonstration sont consultables.

## Où sont les choses

| Dossier | Contenu |
|---|---|
| `moteurs/<moteur>` | Les moteurs installés : `maestro`, `ffmpeg`, `dlss5`, `bonsai` |
| `data/` | Base SQLite (`mymaestro.sqlite3`), `config.json`, médias, journaux (`data/journaux/`) |
| `projets/` | Les médias de chaque projet |
| `ui/dist` | L'interface construite |

`data/` et `projets/` ne sont pas dans Git et ne sont jamais touchés par une mise à jour des moteurs.

## `data/config.json`

Le fichier est créé au premier lancement s'il n'existe pas ; un fichier existant n'est jamais écrasé. Un fichier illisible, ou qui n'est pas un objet JSON, est ignoré avec un avertissement dans le journal du serveur.

| Clé | Rôle | Défaut |
|---|---|---|
| `moteurs` | Dossier de chaque moteur : `{"maestro": "…", "ffmpeg": "…", "dlss5": "…", "bonsai": "…"}`. Une clé absente garde le dossier par défaut | `moteurs/<moteur>` dans le dossier de MyMaestro |
| `marge_memoire_go` | Marge de mémoire engagée exigée avant de démarrer Maestro, en Go | `55` |
| `vram_mo` | VRAM de la carte forcée, en Mo (entier ≥ 1024, par exemple 24564). Vide ou `null` : détection par nvidia-smi ; sans carte détectée, repli sur 12282 Mo (12 Go). Une valeur invalide est ignorée avec un avertissement. Lue au premier usage. | `null` |
| `applications_a_fermer` | Liste de `{"nom": "…", "processus": ["…"]}` que `scripts/preparer-machine.ps1` propose de fermer | Chrome, Blender, Discord, Overlay NVIDIA |

Un chemin relatif dans `moteurs` se résout par rapport au dossier de MyMaestro (la racine du projet), pas au dossier courant. Pour `maestro`, le dossier indiqué est la racine du moteur ; MyMaestro y cherche `app/` (et `app/env/Scripts/python.exe`).

### Ordre de priorité

Chaque réglage est lu dans cet ordre : **variable d'environnement**, puis **`data/config.json`**, puis **valeur par défaut**. Pour les moteurs et la marge, une variable vide est ignorée.

| Variable | Effet | Clé de `config.json` équivalente |
|---|---|---|
| `MYMAESTRO_DONNEES` | Dossier des données (et donc de `config.json`) | aucune |
| `MYMAESTRO_PROJETS` | Dossier des projets | aucune |
| `MYMAESTRO_MEDIAS` | Dossier des médias servis | aucune |
| `MYMAESTRO_MAESTRO_APP` | Dossier `app` de Maestro (et non sa racine) | `moteurs.maestro` |
| `MYMAESTRO_DLSS5` | Dossier de DLSS 5 | `moteurs.dlss5` |
| `MYMAESTRO_BONSAI` | Dossier de Bonsai | `moteurs.bonsai` |
| `MYMAESTRO_FFMPEG` | Dossier de ffmpeg (contenant `ffmpeg.exe` et `ffprobe.exe`) | `moteurs.ffmpeg` |
| `MYMAESTRO_MARGE_MEMOIRE_GO` | Marge de mémoire engagée | `marge_memoire_go` |
| `MYMAESTRO_VRAM_MO` | VRAM de la carte forcée, en Mo (entier ≥ 1024) | `vram_mo` |
| `MYMAESTRO_MOTEURS_REELS` | Facultative. Moteurs pilotés pour de vrai, séparés par des virgules ; `aucun` pour simuler tous les moteurs d'IA (mode démo ; ffmpeg reste réel) | aucune |

`MYMAESTRO_MOTEURS_REELS` est facultative. Absente, les moteurs pilotés pour de vrai sont ceux qui sont installés ou externes (`codex` suit `maestro`). `aucun` active le mode démo, et une liste l'emporte sur la détection : un nom omis reste simulé. Hors mode démo, un moteur simulé ne sert pas : un job qui le vise échoue aussitôt avec un message « non installé » (ou « exclu par MYMAESTRO_MOTEURS_REELS » si le moteur est installé mais absent de la liste).

Les réglages par défaut suivent les moteurs détectés : sans Claude, l'écriture et les prompts d'une nouvelle recette passent sur Bonsai ; sans DLSS 5, la passe DLSS 5 est désactivée par défaut.

`MYMAESTRO_PORT` est lu par `config.py`, mais le lanceur démarre le serveur sur le port 7900 : pour un autre port, lancez vous-même `uvicorn` (voir `DEMARRER-MYMAESTRO.bat`).

Pour ffmpeg, l'ordre de recherche est : `moteurs/ffmpeg` (ou le dossier configuré), puis le `PATH`, puis le ffmpeg livré avec DLSS 5.

## Applications à fermer

`scripts/preparer-machine.ps1` détecte les applications gourmandes, Docker Desktop et la VM WSL, et un Bonsai ou un Maestro lancé à la main. Il affiche ce qu'il fermerait, demande confirmation, puis ferme proprement (et de force après 10 s). Un Maestro lancé à la main sur le port 7860 est seulement signalé : il peut être en plein rendu. Pour voir sans rien fermer :

```bat
powershell -ExecutionPolicy Bypass -File scripts\preparer-machine.ps1 -Simulation
```

## Désinstallation

Supprimez le dossier de MyMaestro. Les moteurs, les données et les projets vivent dans `moteurs/`, `data/` et `projets/`, sauf si vous avez déplacé ces dossiers par `config.json` ou par variables d'environnement : dans ce cas, supprimez aussi ceux-là. L'installation écrit aussi dans le profil de l'utilisateur : uv et ses Pythons gérés (`%USERPROFILE%\.local\bin` et `%APPDATA%\uv`), ainsi que la CLI Claude Code si vous l'avez installée. Ces outils relèvent de leurs propres installeurs et se désinstallent séparément.
