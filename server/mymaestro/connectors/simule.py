"""Connecteur simulé : même contrat qu'un vrai moteur, sans GPU (tests, démonstration jusqu'au plan 6)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from ..contrat.modeles import EtatMoteur, Voie
from .base import Connecteur, Empreinte, ErreurMoteur

if TYPE_CHECKING:
    from ..core.file import JobFile

VOIES = {"maestro": Voie.GPU, "dlss5": Voie.GPU, "bonsai": Voie.GPU, "claude": Voie.CLOUD, "codex": Voie.CLOUD}


class ConnecteurSimule(Connecteur):
    simule = True

    def __init__(
        self,
        nom: str,
        voie: Voie,
        empreinte: Empreinte,
        *,
        echecs: int = 0,
        duree_s: float = 0.0,
        journal: list[str] | None = None,
        repondeur: Callable[[JobFile], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.nom = nom
        self.voie = voie
        self.empreinte = empreinte
        self.echecs_restants = echecs
        self.duree_s = duree_s
        self.journal: list[str] = journal if journal is not None else []
        self.repondeur = repondeur

    def demarrer(self) -> None:
        self.journal.append(f"{self.nom}:demarrer")
        self.etat = EtatMoteur.DEMARRE

    def arreter(self) -> None:
        self.journal.append(f"{self.nom}:arreter")
        self.etat = EtatMoteur.ARRETE

    def liberer(self) -> None:
        self.journal.append(f"{self.nom}:liberer")
        if self.etat is EtatMoteur.CHARGE:
            self.etat = EtatMoteur.DEMARRE

    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        self.journal.append(f"{self.nom}:executer:{job.id}")
        self.etat = EtatMoteur.CHARGE
        progression(0.5)
        if self.duree_s:
            time.sleep(self.duree_s)
        if self.echecs_restants > 0:
            self.echecs_restants -= 1
            raise ErreurMoteur(f"échec simulé sur {job.id}")
        progression(1.0)
        return self.repondeur(job) if self.repondeur is not None else {"fichier": f"simule/{job.id}.mp4"}


def registre_simule(
    empreintes: Mapping[str, Empreinte],
    duree_s: float = 0.0,
    journal: list[str] | None = None,
    repondeur: Callable[[JobFile], dict[str, Any]] | None = None,
) -> dict[str, ConnecteurSimule]:
    """Les moteurs du cahier n°1, simulés, partageant un même journal d'actions et un même répondeur."""
    commun = [] if journal is None else journal
    return {
        nom: ConnecteurSimule(nom, voie, empreintes[nom], duree_s=duree_s, journal=commun, repondeur=repondeur)
        for nom, voie in VOIES.items()
    }
