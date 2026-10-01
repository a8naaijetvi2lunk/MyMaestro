"""Données propres au Director musique (analyse, écriture) et schémas de sortie des modèles de langage.

Chaque sortie de modèle de langage est validée par l'un de ces schémas avant d'être appliquée (D10).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...contrat.modeles import Modele, RolePlan


class Section(Modele):
    nom: str
    debut_s: float = Field(ge=0)
    fin_s: float = Field(gt=0)


class LigneParoles(Modele):
    texte: str
    debut_s: float = Field(ge=0)
    fin_s: float = Field(gt=0)


class Analyse(Modele):
    bpm: float = Field(gt=0)
    temps_forts: list[float] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    voix: list[Section] = Field(default_factory=list)
    lignes: list[LigneParoles] = Field(default_factory=list)
    simule: bool = False


class Brief(Modele):
    ambiance: str = Field("", max_length=2000)
    genre: str = Field("", max_length=500)
    envies: str = Field("", max_length=4000)


class Concept(Modele):
    titre: str = Field(min_length=1)
    pitch: str
    arc: str = ""
    traitement: str = ""


class MessageChat(Modele):
    auteur: Literal["utilisateur", "opus"]
    texte: str


class EtatDirector(Modele):
    analyse: Analyse | None = None
    brief: Brief = Field(default_factory=Brief)
    concepts: list[Concept] = Field(default_factory=list)
    concept_retenu: int | None = None
    chat: list[MessageChat] = Field(default_factory=list)
    en_attente: list[str] = Field(default_factory=list)
    erreurs: dict[str, str] = Field(default_factory=dict)


class MessageEntree(Modele):
    texte: str = Field(min_length=1, max_length=4000)


# --- Schémas de sortie des modèles de langage ------------------------------------------------------


class ReponseConcepts(Modele):
    concepts: list[Concept] = Field(min_length=1, max_length=5)


class ReponseChat(Modele):
    reponse: str = Field(min_length=1)


class PlanPropose(Modele):
    role: RolePlan
    debut_s: float = Field(ge=0)
    fin_s: float = Field(gt=0)
    paroles: str = ""
    description: str = Field(min_length=1)
    fiches: list[str] = Field(default_factory=list)


class ReponseDecoupage(Modele):
    plans: list[PlanPropose] = Field(min_length=1)


class PromptPlan(Modele):
    plan_id: str
    prompt: str = Field(min_length=1)


class ReponsePrompts(Modele):
    prompts: list[PromptPlan]
