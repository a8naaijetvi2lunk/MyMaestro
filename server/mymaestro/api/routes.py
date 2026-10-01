"""Routes de l'API (plan 3 : persistance SQLite, modules, recettes, bibliothèque, actions, file)."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import ValidationError

from .. import __version__, modules
from ..contrat.modeles import (
    EtatFile,
    EtatMoteurs,
    FicheBibliotheque,
    FicheEntree,
    FormatImage,
    ImageFiche,
    InfosMateriel,
    InfosRendu,
    InfosRenduMoteur,
    Job,
    ManifesteModule,
    MoteurVideo,
    Projet,
    Recette,
    RecetteEntree,
    ResumeProjet,
    RoleImageFiche,
    Sante,
)
from ..core import db, depot, grilles, medias
from ..installation.service import adapter_reglages
from ..installation.telechargement import ErreurInstallation
from ..outils import gpu
from .evenements import flux

routeur = APIRouter(prefix="/api")

TYPES_IMAGE = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
TAILLE_MAX_IMAGE = 25 * 1024 * 1024


def _medias(request: Request) -> Path:
    return request.app.state.medias


def _supprimer_media(racine: Path, relatif: str) -> None:
    try:
        medias.chemin_sur(racine, relatif).unlink(missing_ok=True)
    except medias.CheminInterdit:
        pass


def _base(request: Request) -> db.Base:
    return request.app.state.base


@routeur.get("/sante", tags=["système"])
def sante(request: Request) -> Sante:
    with _base(request).transaction() as cx:
        return Sante(statut="ok", version=__version__, schema_db=db.version(cx))


@routeur.get("/materiel", tags=["système"])
def materiel() -> InfosMateriel:
    carte = gpu.detecter_gpu()
    vram_mo, vram_go = gpu.vram_mo(), gpu.vram_go()
    suffisant = vram_mo >= gpu.VRAM_MINIMALE_MO
    avertissement = None
    if carte is None:
        avertissement = "Carte NVIDIA non détectée : planification sur la base d'une carte de 12 Go"
    elif not suffisant:
        vram_affichee = f"{vram_go:.1f}".replace(".", ",")
        avertissement = f"{vram_affichee} Go de VRAM : moins que les {gpu.VRAM_MINIMALE_GO:g} Go recommandés ; H3 limité, rendus plus lents"
    return InfosMateriel(
        gpu=carte.nom if carte else None,
        vram_mo=vram_mo,
        vram_go=vram_go,
        source=carte.source if carte else "repli",
        suffisant=suffisant,
        avertissement=avertissement,
    )


@routeur.get("/projets", tags=["projets"])
def lister_projets(request: Request) -> list[ResumeProjet]:
    with _base(request).transaction() as cx:
        return depot.lister_projets(cx)


@routeur.get("/projets/{projet_id}", tags=["projets"])
def lire_projet(projet_id: str, request: Request) -> Projet:
    with _base(request).transaction() as cx:
        projet = depot.lire_projet(cx, projet_id)
    if projet is None:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return projet


@routeur.get("/modules", tags=["modules"])
def lister_modules() -> list[ManifesteModule]:
    return modules.manifestes()


@routeur.get("/modules/{module_id}/defauts", tags=["modules"])
def defauts_module(module_id: str) -> dict[str, Any]:
    """Réglages par défaut complets d'un module (point de départ d'une nouvelle recette)."""
    try:
        return adapter_reglages(module_id, modules.valider_reglages(module_id, {}))
    except KeyError:
        raise HTTPException(status_code=404, detail="Module introuvable") from None


@routeur.get("/rendu", tags=["modules"])
def infos_rendu(
    format_image: FormatImage = Query(FormatImage.PAYSAGE, alias="format"),
    h3: grilles.Definition | None = Query(None),  # défaut résolu dans le handler : il dépend de la VRAM détectée
    ltx23: grilles.Definition | None = Query(None),
    ltx25: grilles.Definition | None = Query(None),
) -> InfosRendu:
    """Résolution de rendu par moteur, plafond de plan et sortie pour un format (carte « Rendu » de la recette)."""
    choix = {MoteurVideo.H3: h3, MoteurVideo.LTX23: ltx23, MoteurVideo.LTX25: ltx25}
    moteurs = []
    for moteur, definition in choix.items():
        definition = definition or grilles.definition_par_defaut(moteur, format_image)
        try:
            largeur, hauteur = grilles.resolution_rendu(moteur, format_image, definition)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        grille = grilles.grille(moteur, format_image, definition)
        moteurs.append(InfosRenduMoteur(
            moteur=moteur, definition=definition.value, largeur=largeur, hauteur=hauteur,
            images_max=grille.images_max, duree_max_s=grille.duree_max_s,
            saute_flashvsr=grilles.saute_flashvsr(moteur, format_image, definition),
            definitions_permises=[d.value for d in grilles.definitions_permises(moteur, format_image)],
        ))
    largeur_sortie, hauteur_sortie = grilles.RESOLUTIONS_SORTIE[format_image]
    return InfosRendu(
        format=format_image, moteurs=moteurs, fps_maitre=grilles.FPS_MAITRE,
        largeur_sortie=largeur_sortie, hauteur_sortie=hauteur_sortie,
    )


def _definitions_refusees(valeurs: dict[str, Any]) -> None:
    """422 si la recette demande, pour un moteur vidéo, une définition non permise sur la VRAM détectée."""
    rendu = valeurs.get("rendu")
    if not isinstance(rendu, dict):
        return
    format_image = FormatImage(valeurs.get("format", FormatImage.PAYSAGE))
    for moteur, cle in ((MoteurVideo.H3, "h3"), (MoteurVideo.LTX23, "ltx23"), (MoteurVideo.LTX25, "ltx25")):
        if cle in rendu:
            try:
                grilles.resolution_rendu(moteur, format_image, grilles.Definition(rendu[cle]))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None


def _valeurs_validees(entree: RecetteEntree) -> dict[str, Any]:
    try:
        valeurs = modules.valider_reglages(entree.module, entree.valeurs)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Module inconnu : {entree.module}") from None
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False)) from None
    rendu, fournies = valeurs.get("rendu"), entree.valeurs.get("rendu")
    if isinstance(rendu, dict) and not (isinstance(fournies, dict) and "h3" in fournies):  # H3 non précisé : défaut selon la carte
        rendu["h3"] = grilles.definition_par_defaut(MoteurVideo.H3, FormatImage(valeurs.get("format", FormatImage.PAYSAGE))).value
    _definitions_refusees(valeurs)
    return valeurs


@routeur.get("/recettes", tags=["recettes"])
def lister_recettes(request: Request, module: str | None = None) -> list[Recette]:
    with _base(request).transaction() as cx:
        return depot.lister_recettes(cx, module)


@routeur.post("/recettes", status_code=status.HTTP_201_CREATED, tags=["recettes"])
def creer_recette(entree: RecetteEntree, request: Request) -> Recette:
    recette = Recette(id=depot.nouvel_id("recette"), module=entree.module, nom=entree.nom, valeurs=_valeurs_validees(entree))
    with _base(request).transaction() as cx:
        return depot.enregistrer_recette(cx, recette)


@routeur.put("/recettes/{recette_id}", tags=["recettes"])
def modifier_recette(recette_id: str, entree: RecetteEntree, request: Request) -> Recette:
    valeurs = _valeurs_validees(entree)
    with _base(request).transaction() as cx:
        if depot.lire_recette(cx, recette_id) is None:
            raise HTTPException(status_code=404, detail="Recette introuvable")
        return depot.enregistrer_recette(cx, Recette(id=recette_id, module=entree.module, nom=entree.nom, valeurs=valeurs))


@routeur.get("/bibliotheque", tags=["bibliothèque"])
def lister_fiches(request: Request) -> list[FicheBibliotheque]:
    with _base(request).transaction() as cx:
        return depot.lister_fiches(cx)


@routeur.post("/bibliotheque", status_code=status.HTTP_201_CREATED, tags=["bibliothèque"])
def creer_fiche(entree: FicheEntree, request: Request) -> FicheBibliotheque:
    fiche = FicheBibliotheque(id=depot.nouvel_id("fiche"), type=entree.type, nom=entree.nom, description=entree.description)
    with _base(request).transaction() as cx:
        return depot.enregistrer_fiche(cx, fiche)


@routeur.put("/bibliotheque/{fiche_id}", tags=["bibliothèque"])
def modifier_fiche(fiche_id: str, entree: FicheEntree, request: Request) -> FicheBibliotheque:
    with _base(request).transaction() as cx:
        existante = depot.lire_fiche(cx, fiche_id)
        if existante is None:
            raise HTTPException(status_code=404, detail="Fiche introuvable")
        return depot.enregistrer_fiche(
            cx, existante.model_copy(update={"type": entree.type, "nom": entree.nom, "description": entree.description})
        )


@routeur.delete("/bibliotheque/{fiche_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["bibliothèque"])
def supprimer_fiche(fiche_id: str, request: Request) -> Response:
    with _base(request).transaction() as cx:
        if not depot.supprimer_fiche(cx, fiche_id):
            raise HTTPException(status_code=404, detail="Fiche introuvable")
    try:
        shutil.rmtree(medias.chemin_sur(_medias(request), f"bibliotheque/{fiche_id}"), ignore_errors=True)
    except medias.CheminInterdit:
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@routeur.put("/bibliotheque/{fiche_id}/images/{role}", tags=["bibliothèque"])
async def televerser_image_fiche(fiche_id: str, role: RoleImageFiche, request: Request) -> FicheBibliotheque:
    """Image de référence d'une fiche, en corps brut (PNG, JPEG ou WebP) ; remplace celle du même rôle."""
    type_contenu = request.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = TYPES_IMAGE.get(type_contenu)
    if extension is None:
        raise HTTPException(status_code=415, detail="Image PNG, JPEG ou WebP attendue")
    with _base(request).transaction() as cx:
        if depot.lire_fiche(cx, fiche_id) is None:
            raise HTTPException(status_code=404, detail="Fiche introuvable")
    racine = _medias(request)
    relatif = f"bibliotheque/{fiche_id}/{role.value}{extension}"
    try:
        cible = medias.chemin_sur(racine, relatif)
        await medias.ecrire_flux(request.stream(), cible, TAILLE_MAX_IMAGE)
    except medias.TropVolumineux:
        raise HTTPException(status_code=413, detail="Image trop volumineuse") from None
    except medias.FichierVide:
        raise HTTPException(status_code=400, detail="Fichier vide") from None
    except medias.CheminInterdit:
        raise HTTPException(status_code=400, detail="Chemin refusé") from None
    # Fiche relue dans la transaction finale (sans await : lecture et écriture atomiques).
    with _base(request).transaction() as cx:
        fiche = depot.lire_fiche(cx, fiche_id)
        if fiche is None:
            cible.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Fiche introuvable")
        for ancienne in fiche.images:
            if ancienne.role is role and ancienne.chemin != relatif:
                _supprimer_media(racine, ancienne.chemin)
        images = [image for image in fiche.images if image.role is not role]
        images.append(ImageFiche(id=f"img-{fiche_id}-{role.value}", role=role, chemin=relatif))
        return depot.enregistrer_fiche(cx, fiche.model_copy(update={"images": images}))


@routeur.delete("/bibliotheque/{fiche_id}/images/{role}", status_code=status.HTTP_204_NO_CONTENT, tags=["bibliothèque"])
def supprimer_image_fiche(fiche_id: str, role: RoleImageFiche, request: Request) -> Response:
    with _base(request).transaction() as cx:
        fiche = depot.lire_fiche(cx, fiche_id)
        if fiche is None or all(image.role is not role for image in fiche.images):
            raise HTTPException(status_code=404, detail="Image introuvable")
        for image in fiche.images:
            if image.role is role:
                _supprimer_media(_medias(request), image.chemin)
        depot.enregistrer_fiche(cx, fiche.model_copy(update={"images": [i for i in fiche.images if i.role is not role]}))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@routeur.get("/medias/{chemin:path}", response_class=FileResponse, tags=["médias"])
def lire_media(chemin: str, request: Request) -> FileResponse:
    """Sert un média ; le chemin est résolu et borné au dossier des médias."""
    try:
        cible = medias.chemin_sur(_medias(request), chemin)
    except medias.CheminInterdit:
        raise HTTPException(status_code=404, detail="Média introuvable") from None
    if not cible.is_file():
        raise HTTPException(status_code=404, detail="Média introuvable")
    return FileResponse(cible, headers={"Cache-Control": "no-cache"})


@routeur.get("/file", tags=["file"])
def lire_file(request: Request) -> EtatFile:
    return request.app.state.ordonnanceur.etat()


def _ordonnanceur(request: Request):
    return request.app.state.ordonnanceur


@routeur.post("/file/pause", tags=["file"])
def mettre_file_en_pause(request: Request) -> EtatFile:
    """Le job en cours se termine, aucun autre ne démarre avant la reprise."""
    _ordonnanceur(request).mettre_en_pause()
    return _ordonnanceur(request).etat()


@routeur.post("/file/reprendre", tags=["file"])
def reprendre_file(request: Request) -> EtatFile:
    _ordonnanceur(request).lancer()
    return _ordonnanceur(request).etat()


@routeur.post("/file/jobs/{job_id}/relancer", tags=["file"])
def relancer_job(job_id: str, request: Request) -> Job:
    ordonnanceur = _ordonnanceur(request)
    if ordonnanceur.file.lire(job_id) is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    if not ordonnanceur.file.relancer(job_id):
        raise HTTPException(status_code=409, detail="Seul un job en échec ou annulé peut être relancé")
    ordonnanceur.bus.publier({"type": "job", "id": job_id, "statut": "en_file"})
    return ordonnanceur.file.lire(job_id).public()


@routeur.post("/file/jobs/{job_id}/annuler", tags=["file"])
def annuler_job(job_id: str, request: Request) -> Job:
    ordonnanceur = _ordonnanceur(request)
    if ordonnanceur.file.lire(job_id) is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    if not ordonnanceur.file.annuler(job_id):
        raise HTTPException(status_code=409, detail="Seul un job en file peut être annulé")
    ordonnanceur.bus.publier({"type": "job", "id": job_id, "statut": "annule"})
    return ordonnanceur.file.lire(job_id).public()


def _installation(request: Request):
    return request.app.state.installation


@routeur.get("/moteurs", tags=["moteurs"])
def lister_moteurs(request: Request) -> EtatMoteurs:
    return _installation(request).etat()


@routeur.post("/moteurs/annuler", status_code=status.HTTP_204_NO_CONTENT, tags=["moteurs"])
def annuler_installation(request: Request) -> Response:
    _installation(request).annuler()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@routeur.post("/moteurs/claude/connecter", status_code=status.HTTP_204_NO_CONTENT, tags=["moteurs"])
def connecter_claude(request: Request) -> Response:
    try:
        _installation(request).connecter_claude()
    except ErreurInstallation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@routeur.post("/moteurs/{moteur_id}/installer", status_code=status.HTTP_202_ACCEPTED, tags=["moteurs"])
def installer_moteur(moteur_id: str, request: Request) -> Response:
    """Démarre l'installation (progression par les événements `installation`). 409 : déjà en cours, moteur externe ou
    installé, espace disque insuffisant."""
    try:
        _installation(request).installer(moteur_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Moteur inconnu") from None
    except ErreurInstallation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return Response(status_code=status.HTTP_202_ACCEPTED)


@routeur.get("/evenements",response_class=EventSourceResponse, tags=["file"])
async def evenements(request: Request) -> AsyncIterable[ServerSentEvent]:
    async for evenement in flux(request.app.state.ordonnanceur.bus, request.app.state.delai_sse_s):
        yield evenement
