"""Étapes d'installation d'un moteur : extraction sûre, commandes, copie de ressource, préchargement des modèles de Maestro
et installeur officiel de Claude. Chaque étape lève ErreurInstallation (ou InstallationAnnulee) avec un message lisible."""

from __future__ import annotations

import fnmatch
import hashlib
import http.client
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from mymaestro import config
from mymaestro.connectors import maestro as connecteur_maestro
from mymaestro.connectors.maestro import ProcessusMaestro
from mymaestro.installation.manifeste import MoteurManifeste, _claude_repond
from mymaestro.installation.telechargement import ErreurInstallation, InstallationAnnulee
from mymaestro.outils.http import get_json, post_json

SONDAGE_ANNULATION_S = 0.5  # fréquence à laquelle une commande lancée vérifie l'annulation
INTERVALLE_SONDAGE_S = 3.0 # préchargement Maestro : fréquence d'interrogation de l'état des téléchargements
MAX_ECHECS_SONDAGE = 20  # ≈ 1 min d'échecs consécutifs de /models/downloads/status : Maestro ne répond plus
ERREURS_RESEAU = (OSError, ValueError, http.client.HTTPException)
COMMANDE_INSTALLEUR_CLAUDE = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://claude.ai/install.ps1 | iex"]


@dataclass
class ContexteEtape:
    moteur: MoteurManifeste
    dossier: Path  # dossier du moteur (dossier_moteur(moteur.id))
    telechargements: Path  # dossier / ".telechargements"
    annule: threading.Event
    progression: Callable[[str, float | None, str], None]  # (étape, fraction 0..1 ou None, message)
    lancer: Callable[[list[str], Path, threading.Event], subprocess.CompletedProcess]  # (argv, cwd, annule) ; doublé dans les tests


def lancer_reel(argv: list[str], cwd: Path, annule: threading.Event) -> subprocess.CompletedProcess:
    """Lanceur par défaut : liste d'arguments (jamais de shell), sorties fusionnées, UTF-8 forcé. `annule` est sondé toutes
    les 0,5 s : posé, le processus et ses enfants sont tués (`taskkill /T /F`) et InstallationAnnulee est levée."""
    options: dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {}
    processus = subprocess.Popen(
        argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env={
            **os.environ, "PYTHONIOENCODING": "utf-8",
            # uv reste sous moteurs/ : même volume que le venv (liens physiques) et espace couvert par le contrôle
            "UV_CACHE_DIR": str(config.DOSSIER_MOTEURS / ".uv-cache"), "UV_PYTHON_INSTALL_DIR": str(config.DOSSIER_MOTEURS / ".uv-python"),
        },
        **options,
    )
    while True:
        try:
            sortie, _ = processus.communicate(timeout=SONDAGE_ANNULATION_S)
            return subprocess.CompletedProcess(argv, processus.returncode, sortie or "", "")
        except subprocess.TimeoutExpired:
            if annule.is_set():
                _tuer_arbre(processus)
                raise InstallationAnnulee("installation annulée") from None


def _tuer_arbre(processus: subprocess.Popen) -> None:
    """Tue le processus et ses enfants (uv lance pip, un build...), puis attend sa fin."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(processus.pid), "/T", "/F"], capture_output=True, timeout=30, check=False)
        else:
            processus.kill()
    except (OSError, subprocess.SubprocessError):
        processus.kill()
    try:
        processus.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        processus.kill()


def _sortie(resultat: subprocess.CompletedProcess) -> str:
    return (resultat.stdout or "") + (resultat.stderr or "")


def _dernieres_lignes(texte: str, nombre: int = 20) -> str:
    return "\n".join(texte.strip().splitlines()[-nombre:])


# --- extraire -----------------------------------------------------------------------------------------


def _nom_sur(nom: str) -> list[str]:
    """Composants d'un nom d'archive ; ErreurInstallation s'il est absolu ou remonte (zip slip)."""
    normalise = nom.replace("\\", "/")
    if normalise.startswith("/") or re.match(r"^[A-Za-z]:", normalise) or ".." in PurePosixPath(normalise).parts:
        raise ErreurInstallation(f"archive refusée : chemin dangereux « {nom} »")
    return [partie for partie in PurePosixPath(normalise).parts if partie not in ("", ".")]


def _sha256(chemin: Path) -> str:
    condensat = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            condensat.update(bloc)
    return condensat.hexdigest()


def _extraire(etape: dict[str, Any], ctx: ContexteEtape) -> None:
    archive = ctx.telechargements / etape["fichier"]
    vers = (ctx.dossier / etape.get("vers", ".")).resolve()
    motifs = etape.get("membres")
    try:
        zf = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as erreur:
        raise ErreurInstallation(f"archive illisible : {etape['fichier']} ({erreur})") from erreur
    with zf:
        membres = zf.infolist()
        for info in membres:  # tout nom dangereux est refusé AVANT la moindre écriture, même hors des motifs
            _nom_sur(info.filename)
        retenus: list[tuple[zipfile.ZipInfo, list[str]]] = []
        for info in membres:
            if info.is_dir():
                continue
            if motifs and not any(fnmatch.fnmatch(info.filename, motif) for motif in motifs):
                continue
            parties = _nom_sur(info.filename)
            if etape.get("retirer_racine"):
                parties = parties[1:]
            if etape.get("aplatir"):
                parties = parties[-1:]
            if parties:
                retenus.append((info, parties))
        for numero, (info, parties) in enumerate(retenus, start=1):
            if ctx.annule.is_set():
                raise InstallationAnnulee(f"installation annulée pendant l'extraction de {etape['fichier']}")
            cible = vers.joinpath(*parties).resolve()
            if not cible.is_relative_to(vers):
                raise ErreurInstallation(f"archive refusée : chemin dangereux « {info.filename} »")
            cible.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, cible.open("wb") as sortie:
                shutil.copyfileobj(source, sortie, 1024 * 1024)
            ctx.progression("extraire", numero / len(retenus), f"Extraction de {etape['fichier']} ({numero}/{len(retenus)})")
    for fichier in ctx.moteur.fichiers:
        if fichier.nom != etape["fichier"]:
            continue
        for relatif, attendu in fichier.controles_contenu.items():
            chemin = ctx.dossier / relatif
            if not chemin.is_file() or _sha256(chemin).lower() != attendu.lower():
                raise ErreurInstallation(f"contenu inattendu après extraction : {relatif} (archive {fichier.nom})")


# --- commande -----------------------------------------------------------------------------------------


def _ecrire_journal(moteur: str, argv: list[str], sortie: str) -> None:
    try:
        config.DOSSIER_JOURNAUX.mkdir(parents=True, exist_ok=True)
        chemin = config.DOSSIER_JOURNAUX / f"installation-{moteur}-{datetime.now():%Y%m%d-%H%M%S}.log"
        with chemin.open("a", encoding="utf-8") as journal:
            journal.write(f"$ {' '.join(argv)}\n{sortie}\n")
    except OSError:
        pass  # le journal est un confort : son échec ne doit pas faire échouer l'installation


def _commande(etape: dict[str, Any], ctx: ContexteEtape) -> None:
    uv: str | None = None
    argv: list[str] = []
    for element in etape["argv"]:
        if "{uv}" in element:
            uv = uv or shutil.which("uv")
            if not uv:
                raise ErreurInstallation("uv introuvable : relance INSTALLER.bat")
            element = element.replace("{uv}", uv)
        argv.append(element.replace("{dossier}", str(ctx.dossier)))
    if ctx.annule.is_set():
        raise InstallationAnnulee("installation annulée")
    ctx.progression("commande", None, etape.get("libelle") or "Commande d'installation")  # le chemin complet ne va que dans le journal
    resultat = ctx.lancer(argv, ctx.dossier / etape.get("cwd", "."), ctx.annule)
    sortie = _sortie(resultat)
    _ecrire_journal(ctx.moteur.id, argv, sortie)
    if resultat.returncode != 0:
        raise ErreurInstallation(f"commande en échec (code {resultat.returncode}) : {' '.join(argv[:4])}\n{_dernieres_lignes(sortie)}")


# --- copier_ressource ---------------------------------------------------------------------------------


def _copier_ressource(etape: dict[str, Any], ctx: ContexteEtape) -> None:
    source = Path(__file__).with_name(etape["ressource"])
    cible = ctx.dossier / etape["vers"]
    cible.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source, cible)
    except OSError as erreur:
        raise ErreurInstallation(f"copie impossible de {etape['ressource']} : {erreur}") from erreur


# --- precharger_maestro -------------------------------------------------------------------------------


def _fraction_telechargement(url: str) -> float | None:
    try:
        actifs = get_json(f"{url}/api/v1/downloads/active", timeout=10).get("downloads") or []
    except ERREURS_RESEAU:
        return None
    total = sum(int(t.get("total_bytes") or 0) for t in actifs)
    if total <= 0:
        return None
    return min(1.0, sum(int(t.get("downloaded_bytes") or 0) for t in actifs) / total)


def _precharger_maestro(etape: dict[str, Any], ctx: ContexteEtape) -> None:
    """Démarre Maestro sans la marge de mémoire engagée (on ne génère rien), mais avec l'arrêt de notre orphelin et les
    contrôles du port : un préchargement interrompu ne doit pas piéger les essais suivants. Télécharge les modèles, puis
    arrête Maestro."""
    if ctx.annule.is_set():
        raise InstallationAnnulee("installation annulée avant le préchargement de Maestro")
    maestro = ProcessusMaestro(prealables=lambda: connecteur_maestro._prealables_maestro(marge_memoire=False))
    fini = threading.Event()

    def _veiller() -> None:  # l'annulation interrompt aussitôt un démarrage en cours (arreter() incrémente la génération)
        while not fini.wait(0.2):
            if ctx.annule.is_set():
                maestro.arreter(attente_s=0)
                return

    threading.Thread(target=_veiller, daemon=True).start()
    try:
        ctx.progression("precharger_maestro", None, "Démarrage de Maestro")
        try:
            maestro.demarrer()
        except Exception as erreur:  # noqa: BLE001
            if ctx.annule.is_set():
                raise InstallationAnnulee("installation annulée pendant le démarrage de Maestro") from erreur
            raise ErreurInstallation(f"Maestro ne démarre pas : {erreur}") from erreur
        demandes: list[str] = []
        for modele in etape["modeles"]:
            if ctx.annule.is_set():
                raise InstallationAnnulee("installation annulée pendant le préchargement des modèles")
            try:
                post_json(f"{maestro.url}/api/v1/models/{modele}/download", {}, timeout=60)
                demandes.append(modele)
            except urllib.error.HTTPError as erreur:
                if erreur.code != 404:
                    raise ErreurInstallation(f"téléchargement de {modele} refusé par Maestro (HTTP {erreur.code})") from erreur
                ctx.progression("precharger_maestro", None, f"Avertissement : {modele} absent de cette version de Maestro")
            except ERREURS_RESEAU as erreur:
                raise ErreurInstallation(f"Maestro injoignable pendant le téléchargement de {modele} : {erreur}") from erreur
        echecs_consecutifs = 0
        while demandes:
            if ctx.annule.is_set():
                raise InstallationAnnulee("installation annulée pendant le préchargement des modèles")
            if not maestro.lance():
                raise ErreurInstallation(f"Maestro s'est arrêté pendant le préchargement des modèles (journal : {maestro.journal})")
            try:
                statuts = get_json(f"{maestro.url}/api/v1/models/downloads/status", timeout=10).get("downloads") or {}
                echecs_consecutifs = 0
            except ERREURS_RESEAU:
                statuts = {}
                echecs_consecutifs += 1
                if echecs_consecutifs >= MAX_ECHECS_SONDAGE:
                    raise ErreurInstallation(f"Maestro ne répond plus (journal : {maestro.journal})") from None
            for modele in demandes:
                suivi = statuts.get(modele) or {}
                if suivi.get("status") == "failed":
                    raise ErreurInstallation(f"téléchargement de {modele} en échec : {suivi.get('error') or 'erreur inconnue'}")
            if all((statuts.get(modele) or {}).get("status") == "completed" for modele in demandes):
                break
            ctx.progression("precharger_maestro", _fraction_telechargement(maestro.url), "Téléchargement des modèles par Maestro")
            ctx.annule.wait(INTERVALLE_SONDAGE_S)
    finally:
        fini.set()
        maestro.arreter(attente_s=0)


# --- installeur_claude --------------------------------------------------------------------------------


def _installeur_claude(etape: dict[str, Any], ctx: ContexteEtape) -> None:
    if _claude_repond():
        return
    ctx.progression("installeur_claude", None, "Installation de la CLI Claude (installeur officiel d'Anthropic)")
    resultat = ctx.lancer(COMMANDE_INSTALLEUR_CLAUDE, ctx.dossier, ctx.annule)
    sortie = _sortie(resultat)
    _ecrire_journal(ctx.moteur.id, COMMANDE_INSTALLEUR_CLAUDE, sortie)
    if resultat.returncode != 0 or not _claude_repond():
        raise ErreurInstallation(f"installation de Claude en échec (code {resultat.returncode}) : {_dernieres_lignes(sortie)}")


# --- aiguillage ---------------------------------------------------------------------------------------

ETAPES: dict[str, Callable[[dict[str, Any], ContexteEtape], None]] = {
    "extraire": _extraire,
    "commande": _commande,
    "copier_ressource": _copier_ressource,
    "precharger_maestro": _precharger_maestro,
    "installeur_claude": _installeur_claude,
}


def executer_etape(etape: dict[str, Any], ctx: ContexteEtape) -> None:
    """Aiguille selon etape["type"] : extraire, commande, copier_ressource, precharger_maestro, installeur_claude."""
    fonction = ETAPES.get(str(etape.get("type")))
    if fonction is None:
        raise ErreurInstallation(f"type d'étape inconnue : {etape.get('type')}")
    fonction(etape, ctx)
