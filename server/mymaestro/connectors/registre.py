"""Assemblage des moteurs pilotés : réels selon `config.MOTEURS_REELS`, simulés pour le reste (spec §4.2)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from .. import config
from ..contrat.modeles import EtatMoteur
from ..outils import systeme
from .base import Connecteur, Empreinte
from .bonsai import ConnecteurBonsai
from .claude import ConnecteurClaude
from .dlss5 import ConnecteurDlss5
from .maestro import ConnecteurCodex, ConnecteurMaestro, ProcessusMaestro
from .simule import registre_simule

if TYPE_CHECKING:
    from ..core.file import JobFile


MOTEURS_INSTALLABLES = ("maestro", "codex", "dlss5", "bonsai", "claude")  # les moteurs que l'écran « Moteurs » sait installer


class MoteurNonInstalle(RuntimeError):
    """Une phase demande un moteur simulé alors qu'on n'est pas en mode démo : il faut l'installer (409 lisible)."""


def registre(
    empreintes: Mapping[str, Empreinte],
    repondeur: Callable[[JobFile], dict[str, Any]] | None,
    *,
    reels: frozenset[str] | None = None,
    duree_simulee_s: float = 1.0,
    processus: ProcessusMaestro | None = None,
) -> dict[str, Connecteur]:
    """`reels` omis : `MYMAESTRO_MOTEURS_REELS` si elle est posée, sinon les moteurs INSTALLE ou EXTERNE. Le calcul se fait
    ici, à l'appel (jamais dans config.py : import circulaire avec `installation`)."""
    if reels is None:
        if "MYMAESTRO_MOTEURS_REELS" in os.environ:
            reels = config.MOTEURS_REELS
        else:
            from ..installation import service

            reels = service.moteurs_reels()
    connecteurs: dict[str, Connecteur] = dict(registre_simule(empreintes, duree_s=duree_simulee_s, repondeur=repondeur))
    if reels & {"maestro", "codex"}:
        partage = processus or ProcessusMaestro()
        if "maestro" in reels:
            connecteurs["maestro"] = ConnecteurMaestro(partage, empreintes["maestro"])
        if "codex" in reels:
            # Démarrer Maestro prend le GPU : Codex attend que Bonsai l'ait rendu (spec §6.3).
            connecteurs["codex"] = ConnecteurCodex(partage, gpu_libre=lambda: connecteurs["bonsai"].etat is EtatMoteur.ARRETE)
    if "dlss5" in reels:
        connecteurs["dlss5"] = ConnecteurDlss5(empreintes["dlss5"])
    if "bonsai" in reels:
        connecteurs["bonsai"] = ConnecteurBonsai(empreintes["bonsai"])
    if "claude" in reels:
        connecteurs["claude"] = ConnecteurClaude()
    return connecteurs


def _libelle(nom: str) -> str:
    from ..installation.manifeste import charger_manifeste

    cle = "maestro" if nom == "codex" else nom  # Codex passe par le Maestro partagé
    moteur = charger_manifeste().get(cle)
    return moteur.libelle if moteur is not None else nom


def message_non_installe(nom: str) -> str:
    """Pourquoi le moteur `nom` (connecteur simulé hors mode démo) ne sert pas : adapté à l'état détecté."""
    from ..installation.manifeste import EtatInstallation, charger_manifeste, detecter
    from ..installation.service import ETATS_UTILISABLES

    libelle = _libelle(nom)
    entree = charger_manifeste().get("maestro" if nom == "codex" else nom)
    etat = detecter(entree) if entree is not None else EtatInstallation.ABSENT
    if etat in ETATS_UTILISABLES:
        valeur = os.environ.get("MYMAESTRO_MOTEURS_REELS")
        if valeur is not None and nom not in config._moteurs_reels(valeur):
            return f"{libelle} est exclu par MYMAESTRO_MOTEURS_REELS"
        return f"{libelle} vient d'être installé : redémarre MyMaestro pour l'utiliser"
    if etat is EtatInstallation.VERSION_DIFFERENTE:
        return f"{libelle} : version différente, réinstalle-le depuis l'écran Moteurs"
    if etat is EtatInstallation.INCOMPLET:
        return f"{libelle} : installation incomplète, termine-la depuis l'écran Moteurs"
    return f"{libelle} n'est pas installé : installe-le depuis l'écran Moteurs"


def prevol_pour(moteurs: Mapping[str, Connecteur], *, demo: bool | None = None) -> Callable[[str], None]:
    """Contrôle à faire avant une phase : le moteur demandé doit être installé (sinon `MoteurNonInstalle`, hors mode démo),
    puis, avant de démarrer le Maestro partagé (connecteurs `maestro` et `codex`), la marge de mémoire engagée. Si le
    processus tourne déjà, la marge a été contrôlée à son démarrage. `demo` : None = lu à chaque appel (variable
    `MYMAESTRO_MOTEURS_REELS=aucun`) ; True quand l'appelant a fourni lui-même les connecteurs (tests)."""

    def verifier(nom: str) -> None:
        from ..installation.service import mode_demo

        moteur = moteurs.get(nom)
        if moteur is not None and moteur.simule and nom in MOTEURS_INSTALLABLES and not (mode_demo() if demo is None else demo):
            raise MoteurNonInstalle(message_non_installe(nom))
        if nom not in ("maestro", "codex") or moteur is None or moteur.simule or getattr(moteur, "processus", None) is None or moteur.processus.lance():
            return
        systeme.exiger_marge(config.MARGE_MEMOIRE_MAESTRO_GO)

    return verifier
