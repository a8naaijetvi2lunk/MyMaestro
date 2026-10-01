"""Connecteur d'export : le montage ffmpeg en local (spec §4.1 `core/export`).

Aucun GPU : il tourne sur la voie parallèle de la file (nommée « cloud », qui veut dire ici « hors GPU »).
L'interpolation 60 fps, elle, passe par le connecteur DLSS5 (job suivant, voie GPU).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..contrat.modeles import EtatMoteur, Voie
from ..core.export import rendre
from .base import Connecteur, Empreinte, ErreurMoteur

if TYPE_CHECKING:
    from ..core.file import JobFile


class ConnecteurExport(Connecteur):
    nom = "export"
    voie = Voie.CLOUD
    empreinte = Empreinte(vram_mo=0, residuelle_mo=0)

    def demarrer(self) -> None:
        self.etat = EtatMoteur.DEMARRE

    def arreter(self) -> None:
        self.etat = EtatMoteur.ARRETE

    def liberer(self) -> None:
        return None

    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        if job.donnees.get("tache") != "export.montage":
            raise ErreurMoteur(f"tâche inconnue pour l'export : {job.donnees.get('tache')}")
        rendre(job.donnees, progression)
        return {"fichier": str(job.donnees["fichier"])}
