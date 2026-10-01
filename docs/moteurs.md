# Moteurs

MyMaestro ne contient aucun moteur d'IA : il les pilote. Chaque moteur vit dans `moteurs/<moteur>` (ou dans le dossier indiqué par `data/config.json` ou par une variable d'environnement, voir [`installation.md`](installation.md)). Les tailles ci-dessous sont reprises du manifeste d'installation et de ses notes ; le manifeste fait foi pour une version donnée. Chaque moteur s'installe depuis l'écran « Moteurs » (voir [`installation.md`](installation.md)).

| Moteur | Requis | Téléchargement | Espace disque nécessaire | Port ou processus | Ce qu'il débloque |
|---|---|---|---|---|---|
| Maestro | Oui | l'archive, les dépendances Python et les modèles préchargés (Qwen ≈ 31 Go, LTX-2.3 ≈ 44 Go, assets ≈ 5 Go) ; au premier usage, H3 ≈ 34 Go, FlashVSR ≈ 4 Go, MMAudio ≈ 11 Go et Whisper ≈ 0,5 Go | environ 110 Go (plus environ 50 Go au premier usage) | port 7870 (instance dédiée) | analyse audio, images, rendu vidéo, FlashVSR, bruitages |
| ffmpeg | Oui | 0,15 Go | 0,5 Go | sous-processus courts | montage, export, découpe audio, contrôle des sorties |
| DLSS 5 | Non | 0,5 Go | 3 Go | un sous-processus par traitement | passe neuronale par prise, interpolation 60 i/s |
| Bonsai | Non | ≈ 7,9 Go | 9,5 Go | port 8088 | écriture et prompts (image, vidéo, son) en local |
| Claude | Non (Claude ou Bonsai, au moins un, pour écrire un clip) | faible (CLI) | 0,5 Go | un sous-processus par appel | écriture (Opus) et prompts par défaut |

Un moteur absent bloque proprement les phases qui en ont besoin, avec un message adapté à l'état détecté : « n'est pas installé », « version différente, réinstalle-le », « installation incomplète, termine-la », « vient d'être installé : redémarre MyMaestro » ou « est exclu par MYMAESTRO_MOTEURS_REELS ». Un job déjà en file sur un moteur non installé échoue aussitôt avec le même message, sans rien exécuter (« Relancer » le remet en file ; il ne s'exécutera qu'une fois le moteur installé et MyMaestro redémarré). En mode démo (`MYMAESTRO_MOTEURS_REELS=aucun`), rien n'est bloqué : les moteurs d'IA sont simulés.

## Maestro

**Rôle.** C'est le moteur principal, un fork de WanGP piloté par son API HTTP. MyMaestro ne le modifie jamais. Il sert à :
- l'analyse audio de la chanson (sections, temps forts, calage des paroles) ;
- les images de départ (Qwen Image Edit) ;
- le rendu vidéo, plan par plan (MiniMax H3 et LTX) ;
- l'agrandissement FlashVSR ×2 ;
- les bruitages (MMAudio).

Le connecteur « codex » (images gpt-image-2) passe par le même processus Maestro : MyMaestro soumet le modèle `codex_imagegen` à l'API de Maestro, et c'est Maestro qui appelle la CLI `codex`. Cela exige donc Maestro installé, et la CLI `codex` installée et connectée au compte associé sur cette machine ; MyMaestro n'appelle jamais `codex` lui-même.

**Sans lui.** Aucune analyse réelle, aucune image, aucune vidéo : seul le mode simulé reste utilisable.

**Processus.** MyMaestro démarre sa propre instance sur le port 7870, avec `WGP_GGUF_LLAMACPP_CUDA=0` (les noyaux CUDA de llama.cpp produisent des sorties noires sur ce moteur), et note son PID dans `data/maestro-7870.pid` pour pouvoir l'arrêter s'il est resté orphelin. Un Maestro lancé à la main (port 7860) bloque le démarrage : fermez-le d'abord. Journal : `data/journaux/maestro-*.log`.

**Mémoire.** Avant de démarrer Maestro, MyMaestro exige une marge de mémoire engagée (55 Go par défaut). Voir [`depannage.md`](depannage.md).

## ffmpeg

**Rôle.** Montage et export, découpe de l'audio, contrôle des sorties vidéo (nombre d'images, luminance). Il fonctionne hors GPU.

**Sans lui.** Pas de montage ni d'export, donc pas de clip final.

**Recherche.** `moteurs/ffmpeg` (ou le dossier configuré), puis le `PATH`, puis le ffmpeg livré avec DLSS 5.

## DLSS 5 Visual Enhancer

**Rôle.** Deux usages : la passe de rendu neuronal appliquée à chaque prise, et l'interpolation en 60 images par seconde au montage final. Chaque traitement est un sous-processus séparé (le Python embarqué de DLSS 5) : la VRAM est rendue dès qu'il se termine.

**Sans lui.** Pas de passe neuronale et pas d'interpolation 60 i/s. Le reste de la chaîne (rendu, FlashVSR, montage, export en 1080p) fonctionne. Quand DLSS 5 n'est ni installé ni externe (hors mode démo), la passe DLSS 5 est désactivée par défaut dans les nouvelles recettes et dans la recette de démo ; une recette existante qui l'active reste refusée avec un message « non installé » jusqu'à ce que vous la désactiviez.

## Bonsai

**Rôle.** Un modèle de langage local, servi par le llama.cpp de PrismML sur le port 8088, pour l'écriture et les prompts (image, vidéo, son) quand la recette le choisit, ce que font par défaut les nouvelles recettes quand Claude n'est pas disponible. Le modèle reste chargé, et donc sa VRAM tenue, tant que le serveur tourne ; MyMaestro l'arrête quand Maestro en a besoin.

**Sans lui.** L'écriture et les prompts passent par Claude (le fournisseur par défaut). Si Bonsai échoue sur un prompt, le même travail repart sur Claude.

**Processus.** MyMaestro le démarre et l'arrête avec le script `bonsai.ps1` du dossier du moteur. Un Bonsai resté actif après un plantage tient le port 8088 : voir [`depannage.md`](depannage.md).

## Claude

**Rôle.** La CLI `claude`, appelée en mode headless avec votre propre abonnement, pour l'écriture (Opus par défaut) et les prompts. MyMaestro n'en redistribue rien.

**Sans lui.** Les nouvelles recettes (et la recette de démo) confient l'écriture et les prompts à Bonsai. Sans Claude ni Bonsai, l'écriture est bloquée, avec un message qui renvoie à l'écran Moteurs.

**Processus.** Un sous-processus par appel, consigne passée par l'entrée standard, délai de 15 minutes par appel. La CLI doit être installée et connectée (lancez `claude` une fois dans un terminal).

## Carte graphique

**Détection.** Au premier usage, MyMaestro interroge `nvidia-smi` (nom de la carte et VRAM totale) et garde le résultat pour la session. L'écran Moteurs affiche la carte, sa VRAM en Go et la source de l'information. Sans carte NVIDIA détectée, la planification se fait sur la base d'une carte de 12 Go (RTX 4070 Ti, 12282 Mo) et un avertissement s'affiche.

**Surcharge.** Pour forcer la VRAM (détection erronée, plusieurs cartes), renseignez `vram_mo` dans `data/config.json` ou la variable d'environnement `MYMAESTRO_VRAM_MO`, en Mo (1024 ou plus). L'ordonnanceur arbitre alors sur cette VRAM.

**Définitions H3 par palier.** MiniMax H3 limite la durée d'un plan selon la VRAM et la définition. Seules les définitions qui tiennent des plans utiles sont proposées : 12 Go : 480p et 544p ; 16 Go : + 720p ; 32 Go : + 1080p. Une définition non permise est marquée « non disponible sur cette carte » dans la carte « Rendu » de la recette, et refusée par le serveur.

**Minimum recommandé.** 12 Go de VRAM. En dessous, H3 est limité (480p par défaut) et les rendus sont plus lents.
