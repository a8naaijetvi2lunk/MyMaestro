"""Manifeste du module Director musique (spec §4.3) : phases, connecteurs requis, schéma de recette."""

from __future__ import annotations

from ...contrat.modeles import ManifesteModule, PhaseModule
from .reglages import ReglagesDirector

MANIFESTE = ManifesteModule(
    id="director_musique",
    nom="Director musique",
    description="Clip musical : chanson → écriture → prompts → images → vidéo → post-production → timeline.",
    phases=[
        PhaseModule(id="analyse", nom="Analyse", arret_possible=True, connecteurs=["maestro"]),
        PhaseModule(id="ecriture", nom="Écriture", arret_possible=True, connecteurs=["claude"]),
        PhaseModule(id="prompts", nom="Prompts et moteurs", arret_possible=True, connecteurs=["claude", "bonsai"]),
        PhaseModule(id="images", nom="Images", arret_possible=True, connecteurs=["maestro"]),
        PhaseModule(id="video", nom="Vidéo", arret_possible=False, connecteurs=["maestro"]),
        PhaseModule(id="postprod", nom="Post-production", arret_possible=False, connecteurs=["maestro", "dlss5"]),
        PhaseModule(id="export", nom="Export", arret_possible=False, connecteurs=["dlss5"]),
    ],
    schema_reglages=ReglagesDirector.model_json_schema(),
)

ORDRE_PHASES: list[str] = [phase.id for phase in MANIFESTE.phases]


def ordre_job(phase: str, indice: int) -> int:
    """Rang global d'un job du régime par phases : la phase d'abord, puis l'indice du plan."""
    return ORDRE_PHASES.index(phase) * 10_000 + indice
