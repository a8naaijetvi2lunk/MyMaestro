"""Connecteur réel DLSS 5 Visual Enhancer (spec §4.2, D6, D25) : un sous-processus par traitement, lancé avec le
Python embarqué de DLSS5 sur `runners/dlss5_runner.py` (une ligne JSON par événement sur stdout). Rendu neuronal
pour la passe DLSS5 d'une prise, interpolation pour les 60 fps de l'export ; DLSS5 remuxe l'audio d'origine.
Aucun processus résident : la VRAM est rendue à la fin de chaque traitement."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import config
from ..contrat.modeles import EtatMoteur, Voie
from ..outils import controle, ffmpeg
from .base import Connecteur, Empreinte, ErreurMoteur, MoteurInterrompu

if TYPE_CHECKING:
    from ..core.file import JobFile

RUNNER = Path(__file__).resolve().parents[2] / "runners" / "dlss5_runner.py"
ENCODAGE = {"codec": "H.264 (NVIDIA NVENC)", "container": "MP4", "quality": "Max"}  # validé par la tâche 0


def options_neurales(reglages: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "nr_style": str(reglages.get("style", "Cinematic")),
        "nr_intensity": float(reglages.get("intensite", 1.0)),
        "local_tone_strength": float(reglages.get("ton_local", 1.0)),
        "local_structure_strength": float(reglages.get("structure", 1.0)),
        "upscaling_factor": float(reglages.get("facteur", 1.0)),
        **ENCODAGE,
    }


def options_interpolation(fps: int) -> dict[str, Any]:
    return {"target_fps": str(int(fps)), "engine": "Auto", **ENCODAGE}


class ConnecteurDlss5(Connecteur):
    nom = "dlss5"
    voie = Voie.GPU

    def __init__(
        self,
        empreinte: Empreinte,
        *,
        commande: Callable[[Path], list[str]] | None = None,
        repertoire: Path | None = None,
        delai_s: float = 7200,
    ) -> None:
        super().__init__()
        self.empreinte = empreinte
        self._commande = commande or (lambda demande: [str(config.DLSS5_PYTHON), str(RUNNER), str(demande)])
        self._repertoire = repertoire or config.DLSS5_RACINE
        self.delai_s = delai_s
        self._verrou_processus = threading.Lock()
        self._processus: subprocess.Popen | None = None
        self._arret_demande = False
        self._delai_depasse = False

    def demarrer(self) -> None:
        with self._verrou_processus:
            self._arret_demande = False
        self.etat = EtatMoteur.DEMARRE

    def _tuer_processus(self) -> None:
        """Tue l'arbre du traitement en cours (sinon il continue sur le GPU après la fermeture)."""
        with self._verrou_processus:
            self._arret_demande = True
            processus = self._processus
        if processus is not None:
            self._tuer_arbre(processus)

    @staticmethod
    def _tuer_arbre(processus: subprocess.Popen) -> None:
        if processus.poll() is None:
            subprocess.run(["taskkill", "/PID", str(processus.pid), "/T", "/F"], capture_output=True, check=False)
            try:
                processus.wait(30)
            except subprocess.TimeoutExpired:
                processus.kill()

    def _delai_depasse_tuer(self, processus: subprocess.Popen) -> None:
        """Délai écoulé : indicateur distinct de l'arrêt demandé (une erreur, pas une remise en file)."""
        with self._verrou_processus:
            self._delai_depasse = True
        self._tuer_arbre(processus)

    def arreter(self) -> None:
        self._tuer_processus()
        self.etat = EtatMoteur.ARRETE

    def arreter_sans_attendre(self) -> None:
        self._tuer_processus()
        self.etat = EtatMoteur.ARRETE

    def liberer(self) -> None:
        if self.etat is EtatMoteur.CHARGE:
            self.etat = EtatMoteur.DEMARRE

    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        d = job.donnees
        tache = str(d.get("tache", ""))
        if tache == "postprod.dlss5":
            operation, options = "neural_rendering", options_neurales(d.get("reglages") or {})
        elif tache == "export.interpolation":
            operation, options = "interpolation", options_interpolation(int(d.get("fps") or 60))
        else:
            raise ErreurMoteur(f"Tâche inconnue pour DLSS5 : {tache}")
        source = Path(str(d.get("source", "")))
        if not source.is_file():
            raise ErreurMoteur(f"Source introuvable : {source.name}")
        destination = Path(str(d["destination"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._verrou_processus:
            if self._arret_demande:  # seul demarrer() remet l'arrêt à zéro
                raise MoteurInterrompu("DLSS5 arrêté avant le lancement")
            self._delai_depasse = False
        self.etat = EtatMoteur.CHARGE
        travail = Path(tempfile.mkdtemp(prefix="dlss5-", dir=destination.parent))
        try:
            produit = self._lancer(operation, source, options, travail, progression)
            provisoire = destination.with_name(f"{destination.stem}.partiel{destination.suffix}")
            shutil.copyfile(produit, provisoire)
            provisoire.replace(destination)
        finally:
            shutil.rmtree(travail, ignore_errors=True)
        self._controler(operation, source, destination)
        progression(1.0)
        return {"fichier": str(d["fichier"])}

    def _lancer(self, operation: str, source: Path, options: dict[str, Any], travail: Path, progression: Callable[[float], None]) -> Path:
        demande = travail / "demande.json"
        demande.write_text(
            json.dumps({"operation": operation, "entree": str(source), "sortie_dossier": str(travail / "sortie"), "options": options}, ensure_ascii=False),
            encoding="utf-8",
        )
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        final: dict[str, Any] | None = None
        with (travail / "stderr.log").open("w", encoding="utf-8") as erreurs:
            try:
                with self._verrou_processus:
                    if self._arret_demande:
                        raise MoteurInterrompu("DLSS5 arrêté avant le lancement")
                    processus = subprocess.Popen(
                        self._commande(demande), cwd=self._repertoire, env=env, stdout=subprocess.PIPE, stderr=erreurs,
                        text=True, encoding="utf-8", errors="replace",
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                    )
                    self._processus = processus
            except OSError as exc:
                raise ErreurMoteur(f"DLSS5 ne démarre pas : {exc}") from None
            minuterie = threading.Timer(self.delai_s, self._delai_depasse_tuer, args=(processus,))
            minuterie.daemon = True
            minuterie.start()
            try:
                assert processus.stdout is not None
                for ligne in processus.stdout:
                    if not ligne.startswith("{"):
                        continue
                    try:
                        evenement = json.loads(ligne)
                    except json.JSONDecodeError:
                        continue
                    if evenement.get("type") == "progression":
                        progression(max(0.0, min(1.0, float(evenement.get("valeur", 0)))))
                    elif evenement.get("type") in ("resultat", "erreur"):
                        final = evenement
                processus.wait()
            finally:
                minuterie.cancel()
                if processus.poll() is None:  # chemin d'exception (rappel qui lève, valeur illisible) : jamais de runner orphelin
                    self._tuer_arbre(processus)
                with self._verrou_processus:
                    self._processus = None
                    arrete = self._arret_demande
                    trop_long = self._delai_depasse
        if trop_long:
            raise ErreurMoteur(f"DLSS5 trop long (plus de {self.delai_s / 60:.0f} min) : arrêté")
        if arrete:
            raise MoteurInterrompu("DLSS5 arrêté par MyMaestro")
        if final is None or final.get("type") == "erreur":
            cause = (final or {}).get("message") or (travail / "stderr.log").read_text(encoding="utf-8", errors="replace")[-300:]
            raise ErreurMoteur(f"DLSS5 : {cause or 'échec sans message'}")
        produit = Path(str((final.get("resultat") or {}).get("output_path", "")))
        if not produit.is_file():
            raise ErreurMoteur("DLSS5 : fichier de sortie introuvable")
        return produit

    def _controler(self, operation: str, source: Path, destination: Path) -> None:
        infos_source = ffmpeg.sonder(source)
        if operation == "neural_rendering":
            verdict = controle.controler_video(destination, infos_source.get("images"))
            if not verdict.valide:
                raise ErreurMoteur(str(verdict.motif))
            return
        duree = ffmpeg.sonder(destination).get("duree_s", 0.0)
        if abs(float(duree) - float(infos_source.get("duree_s", 0.0))) > 0.2:
            raise ErreurMoteur(f"Interpolation : durée {duree:.2f} s au lieu de {infos_source.get('duree_s', 0.0):.2f} s")
