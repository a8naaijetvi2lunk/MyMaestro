# Third-party components / Composants tiers

**English.** MyMaestro does not bundle any engine or model. The engines listed below are downloaded from their official sources by the built-in installer (Engines screen) or simply driven, and each one keeps its own license. Only the interface code of cojeev-ui (MIT) is vendored in this repository.

**Français.** MyMaestro n'embarque aucun moteur ni aucun modèle : les moteurs listés ci-dessous sont téléchargés depuis leurs sources officielles par l'installeur intégré (écran Moteurs) ou simplement pilotés, et chacun garde sa licence. Seul le code de l'interface cojeev-ui (MIT) est vendorisé dans ce dépôt.

## Maestro (fork) / WanGP

- Sources : `https://github.com/a8naaijetvi2lunk/Maestro-redit-iv`, fondé sur `https://github.com/Blizaine/Maestro`, lui-même fondé sur `https://github.com/deepbeepmeep/Wan2GP`.
- Licence / License : WanGP Non-Commercial Evaluation License 1.1.
- Usage non commercial seulement : pas de vente, pas de service hébergé, pas d'intégration payante. / Non-commercial use only: no sale, no hosted service, no paid integration.
- Les images, vidéos et sons produits peuvent être utilisés, y compris commercialement, à condition que toute diffusion commerciale indique clairement qu'ils ont été produits avec WanGP, avec un lien vers le dépôt WanGP. / Generated images, videos and sounds may be used, including commercially, provided any commercial distribution clearly states they were produced with WanGP, with a link to the WanGP repository.
- Les modèles téléchargés par Maestro (LTX-Video, Qwen Image, MiniMax H3, FlashVSR, MMAudio, faster-whisper, demucs…) ont chacun leur propre licence, consultable sur leur fiche. / The models downloaded by Maestro (LTX-Video, Qwen Image, MiniMax H3, FlashVSR, MMAudio, faster-whisper, demucs…) each have their own license, available on their model card.

## cojeev-ui

- Source : `https://github.com/luv-jeri/cojeev-ui`
- Licence / License : MIT.
- Code vendorisé dans `ui/src/components/ui`, `ui/src/lib/cojeev*` et `ui/src/scripts` ; notice de copyright conservée (voir `ui/src/lib/cojeev/NOTICES.txt`, qui reprend aussi les notices de ThreeUI Semantic Bloom, MIT, © 2026 Meng To, et de Lucide / Feather, ISC et MIT). / Vendored code in `ui/src/components/ui`, `ui/src/lib/cojeev*` and `ui/src/scripts`; copyright notice retained.
- Polices embarquées (`ui/src/styles/cojeev-fonts.css`) / Embedded fonts :
  - DM Sans : SIL Open Font License 1.1, © 2014 The DM Sans Project Authors (`ui/src/styles/fonts/DMSans-OFL.txt`).
  - Bricolage Grotesque : SIL Open Font License 1.1, © 2022 The Bricolage Grotesque Project Authors (`ui/src/styles/fonts/BricolageGrotesque-OFL.txt`).

## DLSS 5 Visual Enhancer

- Source : `https://github.com/Merserk/dlss5-visual-enhancer`
- Licence / License : MIT, © 2026 Merserk.
- Ses composants NVIDIA (DLSS, NGX), RenoDX et ReShade gardent leurs propres licences, fournies dans sa distribution. / Its NVIDIA components (DLSS, NGX), RenoDX and ReShade keep their own licenses, shipped with its distribution.

## llama.cpp (fork PrismML)

- Source : `https://github.com/PrismML-Eng/llama.cpp`
- Licence / License : MIT.

## Modèle Bonsai / Bonsai model

- Source : `https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf`
- Licence / License : Apache-2.0.

## ffmpeg

- Build Windows téléchargée par l'installeur : BtbN `autobuild-2026-08-31-13-27`, ffmpeg `n9.0.1-11-ge47273f4d9`, licence LGPL. Source : `https://github.com/BtbN/FFmpeg-Builds`. / Windows build downloaded by the installer: BtbN `autobuild-2026-08-31-13-27`, ffmpeg `n9.0.1-11-ge47273f4d9`, LGPL license. Source: `https://github.com/BtbN/FFmpeg-Builds`.

## Modèle de conversation Bonsai / Bonsai chat template

- Fichier embarqué : `server/mymaestro/installation/bonsai2-chat-template.jinja`, dérivé du `chat_template` du modèle `prism-ml/Ternary-Bonsai-2-27B-gguf` (`https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf`).
- Licence / License : Apache-2.0.

## SageAttention

- Installée par l'installeur pour Maestro (roue Windows). Source : `https://github.com/woct0rdho/SageAttention`. / Installed by the installer for Maestro (Windows wheel). Source: `https://github.com/woct0rdho/SageAttention`.
- Licence / License : Apache-2.0 (fichier `LICENSE` du dépôt, vérifié le 2026-10-01).

## Claude Code (Anthropic)

- CLI installée par l'installeur officiel d'Anthropic, utilisée avec l'abonnement de l'utilisateur ; rien n'est redistribué ; soumise aux conditions d'Anthropic. / CLI installed by Anthropic's official installer, used with the user's own subscription; nothing is redistributed; subject to Anthropic's terms.

## Dépendances Python et npm / Python and npm dependencies

- Licences déclarées dans `server/uv.lock` et `ui/package-lock.json`. / Licenses declared in `server/uv.lock` and `ui/package-lock.json`.
