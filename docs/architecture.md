# Architecture

MyMaestro est un studio local en trois briques : un **socle** (serveur FastAPI, base SQLite, file de jobs), des **modules** (les workflows, aujourd'hui le seul Director musique) et des **connecteurs** (les moteurs d'IA). L'interface React est servie par le même serveur, sur http://127.0.0.1:7900.

Le socle ne connaît aucun module en dur : il passe par un registre de modules, et chaque module déclare dans un manifeste ses phases, les connecteurs dont il a besoin et le schéma de ses réglages.

## Organisation du code

```
server/mymaestro/
  app.py            application FastAPI (base, file, ordonnanceur, connecteurs)
  config.py         chemins, ports, moteurs (variable d'environnement, puis config.json, puis défaut)
  api/              routes /api/* et flux SSE
  contrat/          modèles pydantic de l'API
  core/             file, arbitre, ordonnanceur, base, dépôt, export, empreintes VRAM
  connectors/       un connecteur par moteur (Maestro, Codex, DLSS 5, Bonsai, Claude, export, simulé)
  installation/     manifeste épinglé des moteurs, détection, téléchargement vérifié, étapes et service d'installation
  modules/          registre des modules ; director_musique/ = le module Director
  outils/           VRAM, HTTP, ffmpeg, synchro audio, mémoire engagée, contrôle des sorties
  fixtures/         données de démonstration
ui/src/             React 19, Vite, composants vendorisés de cojeev-ui
scripts/            installeur (installer.ps1), lanceur de préparation de la machine, export et garde-fou du dépôt public
```

À la racine : `INSTALLER.bat` (uv et dépendances du serveur) et `DEMARRER-MYMAESTRO.bat`. Les moteurs, eux, s'installent depuis l'écran « Moteurs » (`ui/src/pages/PageMoteurs.tsx`).

## Connecteurs

Un connecteur enveloppe un moteur derrière un contrat commun : démarrer, arrêter, libérer la VRAM, exécuter un job, et une **empreinte** (VRAM de pointe et VRAM résiduelle). Le registre assemble les connecteurs réels ou simulés : selon `MYMAESTRO_MOTEURS_REELS` si elle est posée (une liste l'emporte ; `aucun` simule tout), sinon selon les moteurs détectés (installés ou externes). Un moteur simulé permet de tout faire tourner sans GPU en mode démo ; hors mode démo, il ne sert pas : l'ordonnanceur fait échouer sans l'exécuter tout job qui le vise (message « non installé »), et le pré-vol des phases refuse de les lancer.

| Connecteur | Voie | Moteur |
|---|---|---|
| `maestro` | GPU | Maestro, instance dédiée sur le port 7870 |
| `codex` | cloud | images gpt-image-2 par la CLI Codex, à travers le processus Maestro |
| `dlss5` | GPU | un sous-processus par traitement |
| `bonsai` | GPU | serveur llama.cpp local, port 8088 |
| `claude` | cloud | CLI `claude` en mode headless |
| `export` | local | montage ffmpeg, toujours réel |

## File de jobs et arbitre GPU

Tout travail passe par une file persistante (table `jobs`). Elle a deux voies :

- **GPU** : un seul job à la fois ;
- **cloud** : plusieurs en parallèle (deux fils par défaut).

Un job a un statut (`en_file`, `en_cours`, `termine`, `echec`, `annule`), un nombre de tentatives (une nouvelle tentative, puis échec) et peut dépendre d'autres jobs : si l'un d'eux échoue, le job est annulé au lieu de tourner sur une entrée manquante. Au démarrage, les jobs restés « en cours » après un arrêt brutal sont remis en file.

Deux régimes d'ordre coexistent : le régime **phases** (la phase d'abord, puis l'indice du plan) et le régime **carte** (actions programmées à la carte, lancées à la suite).

L'**arbitre** est une fonction pure : il reçoit les jobs éligibles, l'état des connecteurs et le budget de VRAM, et rend une décision que l'**ordonnanceur** applique. Deux règles :
- on épuise le bloc de tête (même régime, même phase) avant de passer au suivant, en gardant le moteur et le modèle déjà chargés tant que possible ;
- avant de charger un autre moteur GPU, on le libère ou on l'arrête si la VRAM ne suffit pas (Maestro avant Bonsai, Bonsai avant Maestro). Le calcul part d'une VRAM totale, d'une part réservée au bureau et des empreintes de chaque moteur (`core/empreintes.py`).

Un job interrompu par MyMaestro lui-même (arbitre, fermeture) repart en file sans perdre de tentative. Avant de démarrer Maestro, un pré-vol vérifie la marge de mémoire engagée.

## Installation des moteurs

Le paquet `installation/` porte un **manifeste** épinglé (version, URL, sha256, étapes et fichiers de contrôle de chaque moteur) et la **détection** de leur état : absent, installé, externe (désigné par une variable d'environnement ou un dossier hors de `moteurs/` : jamais modifié), version différente, incomplet, en cours. Le **service d'installation** exécute une installation à la fois dans un fil : téléchargement vérifié, puis les étapes du manifeste (extraction sûre, commandes, copie de ressource, préchargement des modèles de Maestro, installeur officiel de Claude). Les étapes faites sont notées pour qu'un « Réessayer » reprenne à la première étape non faite ; l'annulation arrête aussi la commande en cours et ses sous-processus. L'état et la progression sortent par `GET /api/moteurs` et par les événements SSE `installation` ; les actions par `POST /api/moteurs/{id}/installer`, `/api/moteurs/annuler` et `/api/moteurs/claude/connecter`.

Les **réglages par défaut** suivent les moteurs détectés (sans Claude, l'écriture et les prompts passent sur Bonsai ; sans DLSS 5, sa passe est désactivée).

## Phases du Director

Le module Director musique déroule huit étapes : création (chanson et paroles), puis sept phases à jobs :

| Phase | Connecteurs | Arrêt possible |
|---|---|---|
| Analyse | maestro | oui |
| Écriture | claude | oui |
| Prompts et moteurs | claude, bonsai | oui |
| Images | maestro | oui |
| Vidéo | maestro | non |
| Post-production | maestro, dlss5 | non |
| Export | dlss5 | non |

Chaque phase se lance puis se valide depuis l'interface. Les réglages d'un projet viennent d'une **recette** (une configuration nommée, dont le schéma JSON génère les formulaires), avec notamment la résolution de rendu par moteur vidéo, la chaîne de post-production (FlashVSR, puis DLSS 5) et l'interpolation 60 images par seconde.

## Timeline, aperçu et export

Les plans rendus deviennent des clips sur une **timeline** multipiste. Chaque plan garde plusieurs **prises** ; une prise et sa sortie sont « actives », et c'est la prise active qui est montée. Les gestes de montage (déplacer, couper, supprimer, ajouter une piste) respectent des règles d'édition côté serveur.

L'aperçu et l'export partagent la même projection : sur chaque intervalle, la piste vidéo la plus haute qui a un clip l'emporte, un intervalle sans clip est noir. Dans l'aperçu, la chanson sert d'horloge. L'export rend ensuite un intermédiaire normalisé par segment, les concatène sans réencodage, mixe les pistes audio (la chanson et les sons), puis encode une fois. Si la recette le demande, un second job interpole le résultat en 60 images par seconde avec DLSS 5.

## Modèle de données

| Où | Quoi |
|---|---|
| `data/mymaestro.sqlite3` | Recettes, projets, fiches de la bibliothèque (personnages, décors, styles) et leurs images, plans, prises, sorties, clips, actions programmées, jobs |
| `data/` | Aussi `config.json`, les médias servis, les journaux et le fichier PID de l'instance Maestro |
| `projets/` | Les médias de chaque projet (images, rendus, exports, rapports) |
| `moteurs/` | Les moteurs installés |

La base est migrée par paliers idempotents : `PRAGMA user_version` est écrit juste après chaque palier, donc une migration interrompue se répare au lancement suivant. Au premier lancement, une base vide reçoit les projets de démonstration.

## API et événements

- **Contrat d'abord** : les modèles pydantic définissent l'API, exportée dans `server/openapi.json`, dont le client TypeScript de l'interface (`ui/src/api/schema.d.ts`) est généré.
- **Routes** sous `/api` : santé, projets, modules, recettes, bibliothèque, médias, file (pause, reprise, relance, annulation), et les routes du Director (phases, écriture, plans, prises, timeline, actions, exports). La documentation interactive est servie par FastAPI sur `/docs`.
- **Requêtes d'autres origines** : le serveur n'écoute que sur 127.0.0.1, mais le navigateur y accède ; un middleware refuse (403) toute requête autre que GET, HEAD ou OPTIONS dont l'en-tête `Origin` n'est pas celui de l'application (`127.0.0.1` ou `localhost` sur son port, ou le port 3000 du serveur de développement) ou dont `Sec-Fetch-Site` vaut `cross-site`. Les requêtes sans `Origin` (outils en ligne de commande, tests) passent.
- **SSE** : `GET /api/evenements` diffuse en direct les changements de la file (jobs, progression) et de l'installation des moteurs. Le flux commence par un événement `connecte` et envoie un commentaire régulier pour garder la connexion ouverte.
