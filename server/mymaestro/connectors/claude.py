"""Connecteur réel de la CLI `claude` (spec §4.2, D10) : écriture (Opus 5.5) et prompts, en mode headless.

Consigne par stdin (jamais en argument : le shim `.cmd` tronque les arguments multi-lignes), schéma par `--json-schema`,
sortie lue dans `structured_output` (tâche 0). La CLI tourne dans un dossier temporaire HORS du dépôt (sinon elle
chargerait le CLAUDE.md de MyMaestro), sans outils, sans serveurs MCP ni session enregistrée : moins de contexte,
moins de quota, des réponses plus rapides."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..contrat.modeles import EtatMoteur, Voie
from .base import Connecteur, Empreinte, ErreurMoteur, MoteurInterrompu

if TYPE_CHECKING:
    from ..core.file import JobFile


def executable_claude() -> str | None:
    """Chemin de la CLI `claude` : le PATH, puis l'emplacement de l'installeur officiel (juste après l'installation, le
    PATH du processus n'est pas encore à jour)."""
    trouve = shutil.which("claude")
    if trouve:
        return trouve
    installe = Path.home() / ".local" / "bin" / "claude.exe"
    return str(installe) if installe.is_file() else None


def commande_claude() -> list[str]:
    chemin = executable_claude() or "claude"
    if os.name == "nt" and Path(chemin).suffix.lower() in (".cmd", ".bat"):
        return ["cmd", "/c", chemin]
    return [chemin]


def extraire(sortie: dict[str, Any]) -> dict[str, Any] | None:
    """Sortie structurée de la CLI : `structured_output`, sinon `result` décodé ; None si aucune n'est un objet JSON."""
    donnees = sortie.get("structured_output")
    if isinstance(donnees, dict):
        return donnees
    resultat = sortie.get("result")
    if isinstance(resultat, str):
        try:
            valeur = json.loads(resultat)
        except json.JSONDecodeError:
            return None
        return valeur if isinstance(valeur, dict) else None
    return None


class ConnecteurClaude(Connecteur):
    nom = "claude"
    voie = Voie.CLOUD
    empreinte = Empreinte(vram_mo=0, residuelle_mo=0)

    def __init__(self, *, executable: list[str] | None = None, delai_s: float = 900) -> None:
        super().__init__()
        self._executable = executable
        self.delai_s = delai_s
        self._verrou_processus = threading.Lock()
        self._processus: set[subprocess.Popen] = set()  # plusieurs appels peuvent tourner en parallèle (voie cloud)
        self._arret_demande = False

    def demarrer(self) -> None:
        with self._verrou_processus:
            self._arret_demande = False
        self.etat = EtatMoteur.DEMARRE

    @staticmethod
    def _tuer_arbre(processus: subprocess.Popen) -> None:
        if processus.poll() is None:
            subprocess.run(["taskkill", "/PID", str(processus.pid), "/T", "/F"], capture_output=True, check=False)
            try:
                processus.wait(30)
            except subprocess.TimeoutExpired:
                processus.kill()

    def _tuer_tout(self) -> None:
        with self._verrou_processus:
            self._arret_demande = True
            en_cours = list(self._processus)
        for processus in en_cours:
            self._tuer_arbre(processus)

    def arreter(self) -> None:
        self._tuer_tout()
        self.etat = EtatMoteur.ARRETE

    def arreter_sans_attendre(self) -> None:
        self._tuer_tout()
        self.etat = EtatMoteur.ARRETE

    def liberer(self) -> None:
        return None

    def commande(self, modele: str, schema: dict[str, Any], effort: str | None) -> list[str]:
        commande = [
            *(self._executable or commande_claude()),
            "-p", "--output-format", "json", "--model", modele,
            "--json-schema", json.dumps(schema, separators=(",", ":")),
            "--tools", "", "--no-session-persistence", "--strict-mcp-config",
        ]
        if effort:
            commande += ["--effort", effort]
        return commande

    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        d = job.donnees
        consigne, schema = d.get("prompt"), d.get("schema")
        if not isinstance(consigne, str) or not consigne.strip() or not isinstance(schema, dict):
            raise ErreurMoteur("Travail sans consigne ou sans schéma JSON")
        commande = self.commande(str(job.modele or "sonnet"), schema, str(d["effort"]) if d.get("effort") else None)
        progression(0.1)
        with tempfile.TemporaryDirectory(prefix="mymaestro_claude_", ignore_cleanup_errors=True) as dossier:
            try:
                with self._verrou_processus:
                    if self._arret_demande:
                        raise MoteurInterrompu("claude arrêté avant le lancement")
                    processus = subprocess.Popen(
                        commande, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        encoding="utf-8", errors="replace", cwd=dossier, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                    )
                    self._processus.add(processus)
            except OSError as exc:
                raise ErreurMoteur(f"claude ne démarre pas : {exc}") from None
            try:
                stdout, stderr = processus.communicate(input=consigne, timeout=self.delai_s)
            except subprocess.TimeoutExpired:
                self._tuer_arbre(processus)
                try:
                    processus.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    pass  # un descendant détaché garde les tubes ouverts : on n'attend pas sa fin
                with self._verrou_processus:
                    if self._arret_demande:
                        raise MoteurInterrompu("claude arrêté par MyMaestro") from None
                raise ErreurMoteur(f"claude : délai de {self.delai_s:.0f} s dépassé") from None
            finally:
                with self._verrou_processus:
                    self._processus.discard(processus)
                    arrete = self._arret_demande
        if arrete:
            raise MoteurInterrompu("claude arrêté par MyMaestro")
        try:
            sortie = json.loads(stdout)
        except json.JSONDecodeError:
            raise ErreurMoteur(f"claude : sortie illisible (code {processus.returncode}) {stderr[-300:].strip()}") from None
        if not isinstance(sortie, dict):
            raise ErreurMoteur("claude : sortie inattendue")
        if sortie.get("is_error"):
            raise ErreurMoteur(f"claude : {str(sortie.get('result') or 'erreur sans message')[:300]}")
        donnees = extraire(sortie)
        if donnees is None:
            raise ErreurMoteur("claude : aucune sortie structurée")
        progression(1.0)
        return donnees
