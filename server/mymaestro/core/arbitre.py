"""Arbitre GPU (spec §6.3) : choisit le prochain job et prépare les moteurs.

Pur (aucune entrée/sortie) : il reçoit les jobs éligibles, l'état des connecteurs et le budget
de VRAM, et rend une décision que l'ordonnanceur applique. Une même règle couvre les deux régimes :
- on épuise le bloc de tête (même régime, même phase) avant de passer au suivant ;
- dans ce bloc, on garde le moteur chargé et le même modèle tant que possible.
Avant de charger un autre moteur GPU : on libère ce qui tient la VRAM si la place suffit,
sinon on arrête (Maestro avant Bonsai, Bonsai avant Maestro).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..connectors.base import Connecteur
from ..contrat.modeles import EtatMoteur, Voie
from .file import JobFile


@dataclass(frozen=True)
class Preparation:
    connecteur: str
    action: str  # "arreter", "liberer" ou "demarrer"


@dataclass(frozen=True)
class Decision:
    job: JobFile
    preparations: tuple[Preparation, ...]


def moteur_charge(connecteurs: Mapping[str, Connecteur]) -> str | None:
    for nom, connecteur in connecteurs.items():
        if connecteur.voie is Voie.GPU and connecteur.etat is EtatMoteur.CHARGE:
            return nom
    return None


def ordonner(candidats: list[JobFile], charge: str | None, dernier_modele: str | None) -> JobFile | None:
    if not candidats:
        return None
    tete = min(candidats, key=lambda j: j.ordre)
    bloc = sorted((j for j in candidats if j.regime == tete.regime and j.phase == tete.phase), key=lambda j: j.ordre)
    for garder in (
        lambda j: j.connecteur == charge and j.modele == dernier_modele,
        lambda j: j.connecteur == charge,
    ):
        retenus = [j for j in bloc if garder(j)]
        if retenus:
            return retenus[0]
    return bloc[0]


def preparer(
    job: JobFile, connecteurs: Mapping[str, Connecteur], vram_totale_mo: int, vram_bureau_mo: int
) -> tuple[Preparation, ...]:
    cible = connecteurs[job.connecteur]
    etapes: list[Preparation] = []
    if cible.voie is Voie.GPU:
        autres = [
            (nom, c) for nom, c in connecteurs.items()
            if nom != job.connecteur and c.voie is Voie.GPU and c.etat is not EtatMoteur.ARRETE
        ]
        residuel = sum(c.empreinte.residuelle_mo for _, c in autres)
        a_arreter: set[str] = set()
        for nom, c in sorted(autres, key=lambda nc: nc[1].empreinte.residuelle_mo, reverse=True):
            # Résiduel nul : arrêter ce moteur (et les suivants, triés par résiduel décroissant) ne libère rien.
            if vram_bureau_mo + residuel + cible.empreinte.vram_mo <= vram_totale_mo or c.empreinte.residuelle_mo <= 0:
                break
            a_arreter.add(nom)
            residuel -= c.empreinte.residuelle_mo
        for nom, c in autres:
            if nom in a_arreter:
                etapes.append(Preparation(nom, "arreter"))
            elif c.etat is EtatMoteur.CHARGE:
                etapes.append(Preparation(nom, "liberer"))
    if cible.etat is EtatMoteur.ARRETE:
        etapes.append(Preparation(job.connecteur, "demarrer"))
    return tuple(etapes)


def choisir(
    candidats: list[JobFile],
    connecteurs: Mapping[str, Connecteur],
    dernier_modele: str | None,
    vram_totale_mo: int,
    vram_bureau_mo: int,
) -> Decision | None:
    job = ordonner(candidats, moteur_charge(connecteurs), dernier_modele)
    if job is None:
        return None
    return Decision(job, preparer(job, connecteurs, vram_totale_mo, vram_bureau_mo))
