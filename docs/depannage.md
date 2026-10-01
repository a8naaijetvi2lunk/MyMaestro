# Dépannage

## Mémoire engagée et fichier d'échange

**Symptôme.** Maestro meurt sans laisser de trace, ou MyMaestro refuse de le démarrer avec « Mémoire engagée insuffisante ».

**Cause.** La mémoire engagée de Windows (RAM plus fichier d'échange) atteint sa limite. Charger un gros modèle vidéo la fait monter d'environ 50 Go au-dessus du repos. La VM WSL de Docker Desktop en tient à elle seule une quinzaine de Go.

**Marge de pré-vol.** Avant de démarrer Maestro, MyMaestro compare la mémoire engagée encore disponible à une marge (55 Go par défaut) et refuse de lancer le moteur en dessous. La marge se règle par `marge_memoire_go` dans `data/config.json` ou par la variable `MYMAESTRO_MARGE_MEMOIRE_GO` (voir [`installation.md`](installation.md)). La baisser ne crée pas de mémoire : c'est un réglage à n'utiliser que si vous avez mesuré vos besoins.

**Remèdes.**
1. Quittez Docker Desktop, puis lancez `wsl --shutdown` (environ 16 Go rendus).
2. Fermez les navigateurs et les applications gourmandes (le script ci-dessous le fait pour vous).
3. Agrandissez le fichier d'échange : Paramètres système avancés, Performances, Mémoire virtuelle, taille personnalisée (par exemple 64 Go), puis redémarrez. Sans redémarrage, la taille fixe ne s'applique pas.
4. Pour plafonner durablement WSL, créez `%USERPROFILE%\.wslconfig` avec une section `[wsl2]` et une ligne `memory=6GB`.

## Script de préparation

`DEMARRER-MYMAESTRO.bat` lance `scripts/preparer-machine.ps1` avant le serveur. Il détecte les applications listées dans `applications_a_fermer` (`data/config.json`), Docker Desktop et la VM WSL, et un Bonsai lancé à la main (port 8088). Il affiche ce qu'il va fermer et la mémoire engagée disponible, demande confirmation, ferme proprement, puis de force au bout de 10 s.

Pour voir sans rien fermer :

```bat
powershell -ExecutionPolicy Bypass -File scripts\preparer-machine.ps1 -Simulation
```

Pour fermer sans confirmation, ajoutez `-Oui`.

## Processus orphelins après un plantage

| Ce qui reste | Symptôme | Que faire |
|---|---|---|
| Maestro sur le port **7870** (instance de MyMaestro) | Le port est pris au démarrage suivant | MyMaestro l'arrête seul grâce à `data/maestro-7870.pid`. À défaut : `netstat -ano \| findstr :7870`, puis `taskkill /PID <pid> /T /F` |
| Maestro lancé à la main sur le port **7860** | MyMaestro refuse de démarrer son Maestro | Fermez-le. Il n'est pas fermé automatiquement, car il peut être en plein rendu |
| Bonsai sur le port **8088** | « Bonsai n'a pas démarré » | `netstat -ano \| findstr :8088`, puis `taskkill /PID <pid> /T /F`, ou `bonsai.ps1 -Action Stop` depuis le dossier du moteur |

## Journaux

| Journal | Emplacement |
|---|---|
| Maestro | `data/journaux/maestro-*.log` (un fichier par lancement de MyMaestro, ouvert en ajout : les redémarrages de Maestro dans la même session s'écrivent à la suite) |
| Serveur MyMaestro | la console de `DEMARRER-MYMAESTRO.bat` |
| Rapport de fin de phase vidéo | `rapports/video-*.md`, dans le dossier du projet |

Un clip en échec passe en rouge avec sa cause : « Relancer » depuis l'écran File GPU, après avoir consulté le journal de Maestro.

## Ctrl+C et reprise de la file

Ctrl+C dans la console arrête MyMaestro proprement : les jobs en cours repartent en file sans perdre de tentative, et les moteurs démarrés par MyMaestro sont arrêtés pour ne pas garder la VRAM. Au lancement suivant, la file reprend. Après un arrêt brutal (coupure de courant, fermeture de la console sans Ctrl+C), les jobs restés « en cours » sont remis en file, ou passent en échec s'ils avaient déjà épuisé leurs tentatives (deux par défaut).

La file peut aussi être mise en pause et reprise depuis l'écran File GPU.

## Espace disque

Chaque sortie vidéo existe en double : la copie dans le dossier du projet et l'original laissé par Maestro dans son dossier de sorties (`moteurs/maestro/app/outputs/mymaestro`), avec ses fichiers `.meta.json` et les agrandissements FlashVSR. L'estimation de disque de MyMaestro ne compte que le projet. Après avoir vérifié votre export, videz ce dossier de Maestro à la main.

## Sans GPU

Pour vérifier que l'application elle-même fonctionne, lancez-la avec tous les moteurs d'IA simulés (ffmpeg reste nécessaire, dans `moteurs/ffmpeg` ou sur le PATH) : `set MYMAESTRO_MOTEURS_REELS=aucun`, puis `DEMARRER-MYMAESTRO.bat`.
