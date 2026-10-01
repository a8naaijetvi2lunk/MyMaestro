# Changelog

## v0.1.1 — 2026-10-01

### English

Fixes from the first real run.

- **Prompt model follows its provider**: a recipe step set to Claude while still carrying the Bonsai model name made the Claude CLI reject the video prompts, which blocked the images. The model now follows the provider (Claude → Sonnet, Bonsai → its own model), and existing recipes are corrected when read.
- **Cast editable after project creation**: a Cast card on the Writing and Prompts screens, with an option to add new library entries to every shot. Each shot now has "In frame" toggles. The images of the selected entries are the references for that shot's image (Qwen or Codex).
- **The LLM knows the cast by name**: the shot breakdown and the prompts receive each entry's name, type and description instead of bare identifiers.

### Français

Correctifs issus du premier vrai test.

- **Le modèle des prompts suit son fournisseur** : une étape réglée sur Claude, mais qui portait encore le modèle de Bonsai, faisait refuser les prompts vidéo par la CLI Claude, ce qui bloquait les images. Le modèle suit désormais le fournisseur (Claude → Sonnet, Bonsai → son modèle), et les recettes existantes sont corrigées à la lecture.
- **Casting modifiable après la création du projet** : une carte Casting sur les écrans Écriture et Prompts propose d'ajouter les nouvelles fiches à tous les plans. Chaque plan a ses boutons « À l'image ». Les images des fiches choisies servent de références à l'image du plan (Qwen ou Codex).
- **Le LLM connaît le casting par son nom** : le découpage et les prompts reçoivent le nom, le type et la description de chaque fiche, et plus seulement des identifiants.

## v0.1.0 — 2026-10-01

### English

First public release.

- **Full music-video Director**: song, analysis, writing, prompts, images, video and post-production, in one guided flow.
- **Timeline and export**: editing with takes, preview against the song, 1080p export with an optional 60 fps interpolation.
- **Five engines driven**: Maestro (WanGP fork), ffmpeg, DLSS 5 Visual Enhancer, Bonsai and the Claude Code CLI, queued on a single GPU.
- **Installer and Moteurs screen**: each engine is downloaded at a pinned version, checked against its fingerprint and installed with live progress.
- **Detected VRAM**: the graphics card is detected and the render settings (H3 in particular) adapt to it.
- **Demo mode**: demo projects and simulated engines (`MYMAESTRO_MOTEURS_REELS=aucun`), to try the interface without a GPU.

### Français

Première version publique.

- **Director complet pour clip musical** : chanson, analyse, écriture, prompts, images, vidéo et post-production, dans un parcours guidé.
- **Timeline et export** : montage avec prises, aperçu calé sur la chanson, export en 1080p avec interpolation 60 images par seconde facultative.
- **Cinq moteurs pilotés** : Maestro (fork de WanGP), ffmpeg, DLSS 5 Visual Enhancer, Bonsai et la CLI Claude Code, mis en file sur un seul GPU.
- **Installeur et écran Moteurs** : chaque moteur est téléchargé à une version épinglée, son empreinte est vérifiée, puis il est installé avec la progression en direct.
- **VRAM détectée** : la carte graphique est détectée et les réglages de rendu (H3 en particulier) s'y adaptent.
- **Mode démo** : projets de démonstration et moteurs simulés (`MYMAESTRO_MOTEURS_REELS=aucun`), pour essayer l'interface sans GPU.
