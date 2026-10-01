"""Chemins et ports de MyMaestro.

Les dossiers de données peuvent être déplacés par variables d'environnement
(MYMAESTRO_DONNEES, MYMAESTRO_PROJETS) ; par défaut ils vivent à la racine du
projet et sont exclus de Git.

Chaque réglage est lu dans l'ordre : variable d'environnement, puis data/config.json,
puis valeur par défaut. Par défaut, les moteurs sont dans <racine>/moteurs/<moteur>.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

# server/mymaestro/config.py → parents[2] = racine du projet
RACINE = Path(__file__).resolve().parents[2]
DOSSIER_DONNEES = Path(os.environ.get("MYMAESTRO_DONNEES", str(RACINE / "data")))
FICHIER_CONFIG = DOSSIER_DONNEES / "config.json"
DOSSIER_MOTEURS = RACINE / "moteurs"

# Applications gourmandes que scripts/preparer-machine.ps1 propose de fermer (data/config.json → applications_a_fermer).
APPLICATIONS_A_FERMER_DEFAUT: list[dict[str, Any]] = [
    {"nom": "Chrome", "processus": ["chrome"]},
    {"nom": "Blender", "processus": ["blender"]},
    {"nom": "Discord", "processus": ["Discord"]},
    {"nom": "Overlay NVIDIA", "processus": ["NVIDIA Overlay"]},
]


_AVERTISSEMENTS_EMIS: set[str] = set()


def avertir_une_fois(message: str, *args: Any) -> None:
    """Journalise un avertissement, une seule fois par texte (la config est relue à chaque appel)."""
    texte = message % args
    if texte not in _AVERTISSEMENTS_EMIS:
        _AVERTISSEMENTS_EMIS.add(texte)
        logging.getLogger(__name__).warning("%s", texte)


def _flottant(valeur: Any, defaut: float) -> float:
    try:
        return float(valeur)
    except (ValueError, TypeError):
        logging.getLogger(__name__).warning("Valeur non numérique %r ignorée, %s retenu", valeur, defaut)
        return defaut


def _entier(valeur: Any, defaut: int) -> int:
    try:
        return int(valeur)
    except (ValueError, TypeError):
        logging.getLogger(__name__).warning("Valeur non entière %r ignorée, %s retenu", valeur, defaut)
        return defaut


def lire_config(chemin: Path | None = None) -> dict[str, Any]:
    """Contenu de data/config.json ; {} s'il manque, est illisible ou n'est pas un objet JSON."""
    cible = chemin or FICHIER_CONFIG
    try:
        contenu = json.loads(cible.read_text(encoding="utf-8-sig"))  # -sig : accepte un fichier avec ou sans BOM
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as erreur:
        avertir_une_fois("%s ignoré : %s", cible, erreur)
        return {}
    if not isinstance(contenu, dict):
        avertir_une_fois("%s ignoré : le contenu n'est pas un objet JSON", cible)
        return {}
    return contenu


CONFIG = lire_config()  # instantané pris à l'import ; reglage() et chemin_moteur() relisent le fichier à chaque appel


def reglage(env: str | None, cle: str, defaut: Any) -> Any:
    """Variable d'environnement (si posée et non vide), puis clé de data/config.json, puis défaut."""
    if env and os.environ.get(env):
        return os.environ[env]
    valeur = lire_config().get(cle)
    return defaut if valeur is None else valeur


def chemin_moteur(env: str | None, moteur: str) -> Path:
    """Dossier d'un moteur : variable d'environnement, puis config.json → "moteurs"[moteur], puis <racine>/moteurs/<moteur>."""
    if env and os.environ.get(env):
        return Path(os.environ[env])
    moteurs = lire_config().get("moteurs")
    declare = moteurs.get(moteur) if isinstance(moteurs, dict) else None
    if isinstance(declare, str) and declare:
        chemin = Path(declare)
        return chemin if chemin.is_absolute() else RACINE / chemin  # un chemin relatif part de la racine du projet
    return DOSSIER_MOTEURS / moteur


def ecrire_config_par_defaut(chemin: Path | None = None) -> Path:
    """Premier lancement : crée data/config.json s'il n'existe pas. On n'écrase jamais un fichier existant."""
    cible = chemin or FICHIER_CONFIG
    if not cible.exists():
        cible.parent.mkdir(parents=True, exist_ok=True)
        contenu = {
            "moteurs": {},
            "marge_memoire_go": 55,
            "vram_mo": None,
            "applications_a_fermer": APPLICATIONS_A_FERMER_DEFAUT,
        }
        cible.write_text(json.dumps(contenu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cible



DOSSIER_PROJETS = Path(os.environ.get("MYMAESTRO_PROJETS", str(RACINE / "projets")))
DOSSIER_UI = RACINE / "ui" / "dist"
HOTE = "127.0.0.1"
PORT = int(os.environ.get("MYMAESTRO_PORT", "7900"))
CHEMIN_BASE = DOSSIER_DONNEES / "mymaestro.sqlite3"
DOSSIER_MEDIAS = Path(os.environ.get("MYMAESTRO_MEDIAS", str(DOSSIER_DONNEES / "medias")))

# Moteurs pilotés (jamais modifiés depuis MyMaestro) — chemins surchargeables par variables d'environnement.
MAESTRO_APP = Path(os.environ["MYMAESTRO_MAESTRO_APP"]) if os.environ.get("MYMAESTRO_MAESTRO_APP") else chemin_moteur(None, "maestro") / "app"
MAESTRO_PYTHON = MAESTRO_APP / "env" / "Scripts" / "python.exe"
MAESTRO_PORT = 7870
MAESTRO_PORT_MANUEL = 7860
MAESTRO_COMMIT_VALIDE = "949264d561d7b53308886f85e0ff19f972a59f2e"
DLSS5_RACINE = chemin_moteur("MYMAESTRO_DLSS5", "dlss5")
DLSS5_PYTHON = DLSS5_RACINE / "bin" / "python-3.13.15-embed-amd64" / "python.exe"
BONSAI_RACINE = chemin_moteur("MYMAESTRO_BONSAI", "bonsai")
FFMPEG_DOSSIER = chemin_moteur("MYMAESTRO_FFMPEG", "ffmpeg")
BONSAI_PORT = 8088
BONSAI_MODELE = "bonsai2-27b-pq2"
DOSSIER_JOURNAUX = DOSSIER_DONNEES / "journaux"

# Marge de mémoire engagée (RAM + fichier d'échange) exigée avant de démarrer Maestro : H3 en 243 images la monte
# d'environ 50 Go au-dessus du repos (tâche 0, 30/09). Sans elle, Maestro meurt sans trace.
def _marge_memoire_go() -> float:
    return _flottant(reglage("MYMAESTRO_MARGE_MEMOIRE_GO", "marge_memoire_go", 55), 55.0)


MARGE_MEMOIRE_MAESTRO_GO = _marge_memoire_go()  # calée sur H3 à 243 images : à revoir après la mesure de H3 en 480p (345 images) et de LTX en 1080p (recette GPU)


def _moteurs_reels(valeur: str) -> frozenset[str]:
    noms = {nom.strip().lower() for nom in valeur.split(",") if nom.strip()}
    return frozenset() if noms <= {"aucun"} else frozenset(noms - {"aucun"})


# Moteurs pilotés pour de vrai ; les autres restent simulés. « aucun » : tout simulé.
MOTEURS_REELS = _moteurs_reels(os.environ.get("MYMAESTRO_MOTEURS_REELS", "maestro,codex,dlss5,bonsai,claude"))
