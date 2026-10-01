"""Registre des modules (spec §4.3) : le socle ne connaît aucun module en dur, il passe par ici."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..contrat.modeles import ManifesteModule
from ..core.contexte import Contexte
from ..core.file import JobFile
from .director_musique import api as api_director
from .director_musique import phases as phases_director
from .director_musique import simulation as simulation_director
from .director_musique.manifeste import MANIFESTE as MANIFESTE_DIRECTOR
from .director_musique.reglages import ReglagesDirector

REGISTRE: dict[str, tuple[ManifesteModule, type[BaseModel]]] = {
    MANIFESTE_DIRECTOR.id: (MANIFESTE_DIRECTOR, ReglagesDirector),
}


def manifestes() -> list[ManifesteModule]:
    return [manifeste for manifeste, _ in REGISTRE.values()]


def valider_reglages(module_id: str, valeurs: dict[str, Any]) -> dict[str, Any]:
    """Valide des réglages de recette et les renvoie complétés des valeurs par défaut.

    Lève KeyError si le module est inconnu, pydantic.ValidationError si les valeurs sont invalides.
    """
    _, modele = REGISTRE[module_id]
    return modele.model_validate(valeurs).model_dump(mode="json")


# --- Aiguillage des fins de jobs vers leur module (le socle ne connaît aucun module en dur) ---------

APRES_JOB: dict[str, Callable[[Contexte, JobFile], None]] = {MANIFESTE_DIRECTOR.id: phases_director.apres_job}


def apres_job(contexte: Contexte, job: JobFile) -> None:
    """Rappel de fin de job : confié au module qui l'a enfilé (`donnees["module"]`)."""
    traitement = APRES_JOB.get(str(job.donnees.get("module", "")))
    if traitement is not None:
        traitement(contexte, job)


# --- Répondeurs des connecteurs simulés, par module --------------------------------------------------

REPONDEURS_SIMULES: dict[str, Callable[[Path], Callable[[JobFile], dict[str, Any]]]] = {
    MANIFESTE_DIRECTOR.id: simulation_director.fabriquer_repondeur,
}


def repondeur_simule(dossier_projets: Path) -> Callable[[JobFile], dict[str, Any]]:
    """Répondeur unique des connecteurs simulés : aiguille chaque job vers la simulation de son module."""
    fabriques = {module: fabriquer(dossier_projets) for module, fabriquer in REPONDEURS_SIMULES.items()}

    def repondre(job: JobFile) -> dict[str, Any]:
        repondeur = fabriques.get(str(job.donnees.get("module", "")))
        return repondeur(job) if repondeur is not None else {"fichier": f"simule/{job.id}.mp4", "simule": True}

    return repondre


# --- Routes d'API déclarées par les modules (incluses par creer_app) ------------------------------

ROUTEURS = [api_director.routeur]
