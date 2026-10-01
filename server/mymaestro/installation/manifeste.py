"""Manifeste épinglé des moteurs (versions, URL, empreintes) et détection de leur état d'installation."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from mymaestro import config

CHEMIN_MANIFESTE = Path(__file__).with_name("manifeste.json")
FICHIER_VERSION = ".mymaestro-version.json"  # {"id", "version", "installe_le"} — écrit EN DERNIER

VARIABLES_MOTEURS = {
    "maestro": "MYMAESTRO_MAESTRO_APP",
    "dlss5": "MYMAESTRO_DLSS5",
    "bonsai": "MYMAESTRO_BONSAI",
    "ffmpeg": "MYMAESTRO_FFMPEG",
}


@dataclass(frozen=True)
class FichierManifeste:
    nom: str  # chemin relatif au dossier du moteur (dossier de téléchargement : <moteur>/.telechargements/)
    url: str
    taille: int | None
    sha256: str | None
    controles_contenu: dict[str, str]  # chemin extrait relatif au dossier du moteur → sha256 attendu (archives sans empreinte)


@dataclass(frozen=True)
class MoteurManifeste:
    id: str
    libelle: str
    requis: bool
    version: str
    espace_mo: int
    fichiers: tuple[FichierManifeste, ...]
    etapes: tuple[dict[str, Any], ...]
    controle: tuple[str, ...]
    note: str | None = None


class EtatInstallation(StrEnum):
    ABSENT = "absent"
    INSTALLE = "installe"
    EXTERNE = "externe"  # désigné par une variable d'environnement : jamais touché
    VERSION_DIFFERENTE = "version_differente"
    INCOMPLET = "incomplet"
    EN_COURS = "en_cours"  # posé par le service (tâche 4)


def charger_manifeste(chemin: Path | None = None) -> dict[str, MoteurManifeste]:
    """Manifeste épinglé (par défaut installation/manifeste.json), indexé par id, dans l'ordre du fichier."""
    brut = json.loads((chemin or CHEMIN_MANIFESTE).read_text(encoding="utf-8"))
    moteurs: dict[str, MoteurManifeste] = {}
    for entree in brut["moteurs"]:
        fichiers = tuple(
            FichierManifeste(
                nom=f["nom"],
                url=f["url"],
                taille=f.get("taille"),
                sha256=f.get("sha256"),
                controles_contenu=dict(f.get("controles_contenu") or {}),
            )
            for f in entree.get("fichiers", [])
        )
        moteurs[entree["id"]] = MoteurManifeste(
            id=entree["id"],
            libelle=entree["libelle"],
            requis=bool(entree["requis"]),
            version=entree["version"],
            espace_mo=int(entree["espace_mo"]),
            fichiers=fichiers,
            etapes=tuple(entree.get("etapes", [])),
            controle=tuple(entree.get("controle", [])),
            note=entree.get("note"),
        )
    return moteurs


def dossier_moteur(moteur: str) -> Path:
    """config.chemin_moteur(<variable du moteur>, moteur) ; Maestro : le dossier racine du fork (parent de app/)."""
    variable = VARIABLES_MOTEURS.get(moteur)
    if moteur == "maestro":
        if os.environ.get("MYMAESTRO_MAESTRO_APP"):
            return Path(os.environ["MYMAESTRO_MAESTRO_APP"]).parent
        return config.chemin_moteur(None, "maestro")
    return config.chemin_moteur(variable, moteur)


def _sous_moteurs(chemin: Path) -> bool:
    """Vrai si `chemin` est sous config.DOSSIER_MOTEURS, le seul endroit que l'installeur gère (et écrit)."""
    return chemin.resolve().is_relative_to(config.DOSSIER_MOTEURS.resolve())


def _ffmpeg_externe(dossier: Path) -> bool:
    """Vrai si ffmpeg se trouve hors de moteurs/ (PATH, ffmpeg système). Celui que DLSS 5, installé par MyMaestro, embarque
    sous moteurs/ ne compte pas : le ffmpeg épinglé du manifeste doit rester installable."""
    from mymaestro.outils import ffmpeg

    try:
        trouve = Path(ffmpeg.trouver("ffmpeg"))
    except FileNotFoundError:
        return False
    return not _sous_moteurs(trouve)


def _claude_repond() -> bool:
    """Vrai si la CLI `claude` (PATH, puis ~/.local/bin/claude.exe) répond à `--version`."""
    from mymaestro.connectors.claude import executable_claude

    executable = executable_claude()
    if not executable:
        return False
    try:
        resultat = subprocess.run([executable, "--version"], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return resultat.returncode == 0


def _version_installee(dossier: Path) -> str | None:
    try:
        contenu = json.loads((dossier / FICHIER_VERSION).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = contenu.get("version") if isinstance(contenu, dict) else None
    return version if isinstance(version, str) else None


def detecter(manifeste: MoteurManifeste) -> EtatInstallation:
    """ffmpeg, maestro, dlss5, bonsai : EXTERNE si la variable d'environnement du moteur est posée ou si son dossier
    (config.json) est hors de moteurs/ ; INSTALLE si
    FICHIER_VERSION porte la version du manifeste et que tous les fichiers de `controle` existent ; VERSION_DIFFERENTE si
    FICHIER_VERSION porte une autre version ; INCOMPLET si le dossier existe sans FICHIER_VERSION valide ; ABSENT sinon.
    ffmpeg : aussi EXTERNE si `outils.ffmpeg.trouver("ffmpeg")` réussit hors de `moteurs/` (PATH, ffmpeg d'un DLSS5 externe) ; celui de moteurs/dlss5 ne compte pas.
    claude : INSTALLE si `claude --version` répond, ABSENT sinon."""
    if manifeste.id == "claude":
        return EtatInstallation.INSTALLE if _claude_repond() else EtatInstallation.ABSENT
    variable = VARIABLES_MOTEURS.get(manifeste.id)
    if variable and os.environ.get(variable):
        return EtatInstallation.EXTERNE
    dossier = dossier_moteur(manifeste.id)
    if not _sous_moteurs(dossier):  # désigné par config.json hors de moteurs/ : jamais modifié par l'installeur
        return EtatInstallation.EXTERNE
    version = _version_installee(dossier)
    if version == manifeste.version:
        if all((dossier / relatif).exists() for relatif in manifeste.controle):
            return EtatInstallation.INSTALLE
        return EtatInstallation.INCOMPLET
    if manifeste.id == "ffmpeg" and _ffmpeg_externe(dossier):
        return EtatInstallation.EXTERNE
    if version is not None:
        return EtatInstallation.VERSION_DIFFERENTE
    return EtatInstallation.INCOMPLET if dossier.exists() else EtatInstallation.ABSENT
