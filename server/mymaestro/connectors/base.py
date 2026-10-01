"""Contrat des connecteurs (spec §4.2) : un connecteur pilote UN moteur.

Simplification assumée pour le cahier n°1 : `executer` est bloquant et rend compte de sa
progression par rappel ; l'ordonnanceur l'appelle depuis le fil de sa voie. Les moteurs réels
(plan 6) suivent le même contrat (Maestro : soumission puis suivi de /status ; DLSS5 : sous-processus).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..contrat.modeles import EtatConnecteur, EtatMoteur, Voie

if TYPE_CHECKING:
    from ..core.file import JobFile


class ErreurMoteur(RuntimeError):
    """Échec d'un job côté moteur : consigné, puis réessayé selon la politique de la file."""


class MoteurInterrompu(ErreurMoteur):
    """Le moteur a été arrêté par MyMaestro (arbitre GPU, fermeture) : le job n'y est pour rien et repart en file
    sans tentative perdue."""


@dataclass(frozen=True)
class Empreinte:
    vram_mo: int  # pic pendant un job
    residuelle_mo: int  # VRAM gardée quand le moteur tourne mais a libéré ses modèles


class Connecteur(ABC):
    nom: str
    voie: Voie
    empreinte: Empreinte
    simule: bool = False

    def __init__(self) -> None:
        self.etat = EtatMoteur.ARRETE

    @abstractmethod
    def demarrer(self) -> None: ...

    @abstractmethod
    def arreter(self) -> None: ...

    @abstractmethod
    def liberer(self) -> None: ...

    @abstractmethod
    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]: ...

    def arreter_sans_attendre(self) -> None:
        """Arrêt à la fermeture de MyMaestro : sans attendre les jobs en vol (ils seront repris sans tentative perdue)."""
        self.arreter()

    def peut_executer(self) -> bool:
        """Faux : la voie parallèle saute pour l'instant les jobs de ce connecteur (ils attendent, sans tentative perdue)."""
        return True

    def attend_le_gpu(self) -> bool:
        """Vrai si ce job cloud ne peut partir que lorsque le GPU est libéré (arrêter Bonsai le débloquerait)."""
        return False

    def etat_public(self) -> EtatConnecteur:
        return EtatConnecteur(
            nom=self.nom,
            voie=self.voie,
            etat=self.etat,
            empreinte_vram_mo=self.empreinte.vram_mo,
            vram_residuelle_mo=self.empreinte.residuelle_mo,
            simule=self.simule,
        )
