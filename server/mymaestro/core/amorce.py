"""Amorçage : au premier lancement, la base reçoit la démonstration du plan 1,
pour que l'interface ait toujours des données réalistes à montrer."""

from __future__ import annotations

from pathlib import Path

from ..fixtures import demo, medias_demo
from ..installation.service import adapter_reglages
from . import depot
from .db import Base


def amorcer_si_vide(base: Base, dossier_projets: Path | None = None, dossier_medias: Path | None = None) -> bool:
    """Charge fiches, recette, projets et timeline de démonstration si aucun projet n'existe. Renvoie True si amorcé.

    Quand `dossier_projets` (et `dossier_medias` pour les fiches) est fourni, les médias de la démo sont générés
    aux chemins que référencent les données, seulement s'ils sont absents : jamais d'image cassée ni de chanson illisible.
    """
    with base.transaction() as cx:
        if cx.execute("SELECT COUNT(*) FROM projets").fetchone()[0]:
            return False
        fiches = demo.fiches_demo()
        for fiche in fiches:
            depot.enregistrer_fiche(cx, fiche)
        for recette in demo.recettes_demo():  # sur Bonsai sans Claude, DLSS5 inactif sans DLSS5 (ni installés ni externes)
            recette = recette.model_copy(update={"valeurs": adapter_reglages(recette.module, recette.valeurs)})
            depot.enregistrer_recette(cx, recette)
        projets = demo.projets_demo()
        for projet in projets.values():
            depot.inserer_projet(cx, projet, demo.donnees_module_demo(projet.id))
        depot.inserer_timeline(cx, demo.timeline_demo())
    if dossier_projets is not None:
        _medias_des_projets(Path(dossier_projets), projets)
    if dossier_medias is not None:
        _medias_des_fiches(Path(dossier_medias), fiches)
    return True


def _medias_des_projets(dossier: Path, projets: dict) -> None:
    for projet in projets.values():
        if projet.chanson:
            chanson = dossier / projet.id / projet.chanson
            if not chanson.exists():
                medias_demo.ecrire_chanson_wav(chanson, projet.duree_chanson_s or demo.DUREE_CHANSON_S)
        for plan in projet.plans:
            if plan.image_depart is None:
                continue
            image = dossier / projet.id / plan.image_depart
            if image.exists():
                continue
            haut, bas = demo.PALETTES_PLANS[plan.indice % len(demo.PALETTES_PLANS)]
            largeur, hauteur = (544, 960) if projet.format.value == "9:16" else (960, 544)
            medias_demo.ecrire_png_degrade(image, largeur, hauteur, haut, bas)


def _medias_des_fiches(dossier: Path, fiches: list) -> None:
    for fiche in fiches:
        for image in fiche.images:
            chemin = dossier / image.chemin
            palette = demo.PALETTES_FICHES.get(image.id)
            if palette is not None and not chemin.exists():
                medias_demo.ecrire_png_degrade(chemin, 640, 480, *palette)
