"""Routes d'API du module Director musique (incluses par l'application via `modules.ROUTEURS`)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse

from ...contrat.modeles import (
    ActionEntree,
    ActionProgrammee,
    ChoixPrise,
    ChoixSortie,
    ClipModification,
    CompatibiliteMoteur,
    Coupe,
    EstimationVideo,
    EtatPhase,
    ExportEntree,
    ExportProjet,
    Lancement,
    Nettoyage,
    NouvellePiste,
    Plan,
    PlanModification,
    Projet,
    ProjetEntree,
    Segment,
    Timeline,
)
from ...core import depot, medias
from ...core.contexte import Contexte
from ...outils import ffmpeg
from . import actions, exports, phases, timeline, video
from .modeles import Brief, EtatDirector, LigneParoles, MessageEntree
from .moteurs import compatibilites

routeur = APIRouter(prefix="/api", tags=["director"])

TYPES_AUDIO = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
    "audio/flac": ".flac", "audio/x-flac": ".flac", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/ogg": ".ogg",
}
TAILLE_MAX_CHANSON = 200 * 1024 * 1024


def _ctx(request: Request) -> Contexte:
    return request.app.state.contexte


def _lire_projet(ctx: Contexte, projet_id: str) -> Projet:
    with ctx.base.transaction() as cx:
        projet = depot.lire_projet(cx, projet_id)
    if projet is None or projet.module != phases.MODULE:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return projet


def _executer(action, *args: Any) -> Any:
    try:
        return action(*args)
    except KeyError:
        raise HTTPException(status_code=404, detail="Projet, plan, clip ou prise introuvable") from None
    except phases.ErreurPhase as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@routeur.post("/projets", status_code=status.HTTP_201_CREATED)
def creer_projet(entree: ProjetEntree, request: Request) -> Projet:
    ctx = _ctx(request)
    entree = entree.model_copy(update={"casting": list(dict.fromkeys(entree.casting))})
    with ctx.base.transaction() as cx:
        if entree.recette_id and depot.lire_recette(cx, entree.recette_id) is None:
            raise HTTPException(status_code=422, detail="Recette introuvable")
        connues = {f.id for f in depot.lister_fiches(cx)}
        inconnues = [fiche for fiche in entree.casting if fiche not in connues]
        if inconnues:
            raise HTTPException(status_code=422, detail=f"Fiches introuvables : {', '.join(inconnues)}")
        return depot.creer_projet(cx, entree, phases.MODULE, phases.etat_initial())


@routeur.put("/projets/{projet_id}/chanson")
async def televerser_chanson(projet_id: str, request: Request) -> Projet:
    """Chanson en corps brut ; sa durée est lue par ffprobe, un fichier illisible est refusé et supprimé."""
    ctx = _ctx(request)
    projet = _lire_projet(ctx, projet_id)
    if projet.etat_phases.get("analyse") not in (EtatPhase.A_FAIRE, EtatPhase.ECHEC):
        # L'analyse, l'écriture et les plans dépendent de la chanson : on ne la remplace pas en cours de route.
        raise HTTPException(status_code=409, detail="Chanson verrouillée une fois l'analyse lancée : crée un nouveau projet pour une autre chanson")
    type_contenu = request.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = TYPES_AUDIO.get(type_contenu)
    if extension is None:
        raise HTTPException(status_code=415, detail="Fichier audio attendu (mp3, wav, flac, m4a, ogg)")
    relatif = f"chanson{extension}"
    dossier = ctx.dossier_projet(projet_id)
    cible = medias.chemin_sur(dossier, relatif)
    # Envoi écrit sous un nom temporaire (hors « chanson.* ») : la chanson en place n'est remplacée qu'une fois sondée.
    temp = medias.chemin_sur(dossier, f"envoi-{uuid.uuid4().hex}{extension}")
    try:
        await medias.ecrire_flux(request.stream(), temp, TAILLE_MAX_CHANSON)
    except medias.TropVolumineux:
        raise HTTPException(status_code=413, detail="Chanson trop volumineuse (200 Mo au plus)") from None
    except medias.FichierVide:
        raise HTTPException(status_code=400, detail="Fichier vide") from None
    try:
        duree = float(ffmpeg.sonder(temp)["duree_s"])
    except Exception:  # noqa: BLE001 — ffprobe refuse le fichier : on le dit sans détail technique
        duree = 0.0
    if duree <= 0:
        temp.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Fichier audio illisible")
    temp.replace(cible)
    for autre in dossier.glob("chanson.*"):
        if autre != cible:
            autre.unlink(missing_ok=True)
    phases.televerser_fini(ctx, projet_id, relatif, duree)
    return _lire_projet(ctx, projet_id)


@routeur.get("/projets/{projet_id}/director")
def lire_etat_director(projet_id: str, request: Request) -> EtatDirector:
    return _executer(phases.etat_director, _ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/phases/{phase}/lancer")
def lancer_phase(projet_id: str, phase: str, request: Request) -> Projet:
    _executer(phases.lancer_phase, _ctx(request), projet_id, phase)
    return _lire_projet(_ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/phases/{phase}/valider")
def valider_phase(projet_id: str, phase: str, request: Request) -> Projet:
    _executer(phases.valider_phase, _ctx(request), projet_id, phase)
    return _lire_projet(_ctx(request), projet_id)


@routeur.put("/projets/{projet_id}/ecriture/brief")
def definir_brief(projet_id: str, brief: Brief, request: Request) -> EtatDirector:
    _executer(phases.definir_brief, _ctx(request), projet_id, brief)
    return phases.etat_director(_ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/ecriture/concepts")
def proposer_concepts(projet_id: str, request: Request) -> EtatDirector:
    _executer(phases.proposer_concepts, _ctx(request), projet_id)
    return phases.etat_director(_ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/ecriture/concepts/{indice}/retenir")
def retenir_concept(projet_id: str, indice: int, request: Request) -> EtatDirector:
    _executer(phases.retenir_concept, _ctx(request), projet_id, indice)
    return phases.etat_director(_ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/ecriture/chat")
def envoyer_message(projet_id: str, message: MessageEntree, request: Request) -> EtatDirector:
    _executer(phases.envoyer_message, _ctx(request), projet_id, message.texte)
    return phases.etat_director(_ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/ecriture/decoupage")
def ecrire_decoupage(projet_id: str, request: Request) -> EtatDirector:
    _executer(phases.ecrire_decoupage, _ctx(request), projet_id)
    return phases.etat_director(_ctx(request), projet_id)


@routeur.put("/projets/{projet_id}/analyse/lignes")
def modifier_lignes(projet_id: str, lignes: list[LigneParoles], request: Request) -> EtatDirector:
    _executer(phases.modifier_lignes, _ctx(request), projet_id, lignes)
    return phases.etat_director(_ctx(request), projet_id)


@routeur.get("/projets/{projet_id}/compatibilites")
def lire_compatibilites(projet_id: str, request: Request) -> dict[str, list[CompatibiliteMoteur]]:
    ctx = _ctx(request)
    projet = _lire_projet(ctx, projet_id)
    with ctx.base.transaction() as cx:
        definitions = phases.reglages(cx, projet).rendu.definitions()
    return {plan.id: compatibilites(plan, projet.format, definitions) for plan in projet.plans}


@routeur.patch("/projets/{projet_id}/plans/{plan_id}")
def modifier_plan(projet_id: str, plan_id: str, modification: PlanModification, request: Request) -> Plan:
    return _executer(phases.modifier_plan, _ctx(request), projet_id, plan_id, modification)


@routeur.post("/projets/{projet_id}/plans/{plan_id}/image/refaire")
def refaire_image(projet_id: str, plan_id: str, request: Request) -> Projet:
    _executer(phases.refaire_image, _ctx(request), projet_id, plan_id)
    return _lire_projet(_ctx(request), projet_id)


@routeur.get("/projets/{projet_id}/medias/{chemin:path}", response_class=FileResponse)
def lire_media_projet(projet_id: str, chemin: str, request: Request, telecharger: bool = False) -> FileResponse:
    ctx = _ctx(request)
    _lire_projet(ctx, projet_id)
    try:
        cible = medias.chemin_sur(ctx.dossier_projet(projet_id), chemin)
    except medias.CheminInterdit:
        raise HTTPException(status_code=404, detail="Média introuvable") from None
    if not cible.is_file():
        raise HTTPException(status_code=404, detail="Média introuvable")
    return FileResponse(cible, headers={"Cache-Control": "no-cache"}, filename=cible.name if telecharger else None)


# --- Actions programmées (régime « à la carte ») ------------------------------------------------------


@routeur.get("/projets/{projet_id}/actions", tags=["file"])
def lister_actions(projet_id: str, request: Request) -> list[ActionProgrammee]:
    return _executer(actions.lister, _ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/actions", status_code=status.HTTP_201_CREATED, tags=["file"])
def programmer_action(projet_id: str, entree: ActionEntree, request: Request) -> ActionProgrammee:
    try:
        return _executer(actions.programmer, _ctx(request), projet_id, entree)
    except actions.ActionInvalide as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@routeur.post("/projets/{projet_id}/actions/lancer", tags=["file"])
def lancer_actions(projet_id: str, request: Request) -> Lancement:
    return Lancement(jobs=_executer(actions.lancer, _ctx(request), projet_id))


@routeur.delete("/projets/{projet_id}/actions/{action_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["file"])
def retirer_action(projet_id: str, action_id: str, request: Request) -> Response:
    _executer(actions.retirer, _ctx(request), projet_id, action_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Timeline, prises, sons, estimation de la phase 5 et export ----------------------------------------


@routeur.get("/projets/{projet_id}/timeline", tags=["projets"])
def lire_timeline(projet_id: str, request: Request) -> Timeline:
    ctx = _ctx(request)
    _lire_projet(ctx, projet_id)
    resultat = timeline.lire(ctx, projet_id)
    if resultat is None:
        raise HTTPException(status_code=404, detail="Timeline introuvable")
    return resultat


@routeur.get("/projets/{projet_id}/timeline/segments", tags=["projets"])
def lire_segments(projet_id: str, request: Request) -> list[Segment]:
    ctx = _ctx(request)
    _lire_projet(ctx, projet_id)
    resultat = timeline.segments(ctx, projet_id)
    if resultat is None:
        raise HTTPException(status_code=404, detail="Timeline introuvable")
    return resultat


@routeur.patch("/projets/{projet_id}/timeline/clips/{clip_id}", tags=["projets"])
def modifier_clip(projet_id: str, clip_id: str, modification: ClipModification, request: Request) -> Timeline:
    return _executer(timeline.modifier_clip, _ctx(request), projet_id, clip_id, modification)


@routeur.post("/projets/{projet_id}/timeline/clips/{clip_id}/couper", tags=["projets"])
def couper_clip(projet_id: str, clip_id: str, coupe: Coupe, request: Request) -> Timeline:
    return _executer(timeline.couper, _ctx(request), projet_id, clip_id, coupe.temps_s)


@routeur.delete("/projets/{projet_id}/timeline/clips/{clip_id}", tags=["projets"])
def supprimer_clip(projet_id: str, clip_id: str, request: Request) -> Timeline:
    return _executer(timeline.supprimer_clip, _ctx(request), projet_id, clip_id)


@routeur.post("/projets/{projet_id}/timeline/pistes", tags=["projets"])
def ajouter_piste(projet_id: str, piste: NouvellePiste, request: Request) -> Timeline:
    return _executer(timeline.ajouter_piste, _ctx(request), projet_id, piste.type)


@routeur.put("/projets/{projet_id}/plans/{plan_id}/prise-active")
def choisir_prise(projet_id: str, plan_id: str, choix: ChoixPrise, request: Request) -> Projet:
    return _executer(timeline.choisir_prise, _ctx(request), projet_id, plan_id, choix.prise_id)


@routeur.put("/projets/{projet_id}/prises/{prise_id}/sortie-active")
def choisir_sortie(projet_id: str, prise_id: str, choix: ChoixSortie, request: Request) -> Projet:
    return _executer(timeline.choisir_sortie, _ctx(request), projet_id, prise_id, choix.sortie_id)


@routeur.post("/projets/{projet_id}/prises/nettoyer")
def nettoyer_prises(projet_id: str, request: Request) -> Nettoyage:
    return _executer(timeline.nettoyer, _ctx(request), projet_id)


@routeur.put("/projets/{projet_id}/sons", tags=["projets"])
async def importer_son(projet_id: str, request: Request, position_s: float = Query(0.0, ge=0, allow_inf_nan=False)) -> Timeline:
    """Son importé en corps brut, posé sur la première piste audio libre à `position_s`."""
    ctx = _ctx(request)
    _lire_projet(ctx, projet_id)
    type_contenu = request.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = TYPES_AUDIO.get(type_contenu)
    if extension is None:
        raise HTTPException(status_code=415, detail="Fichier audio attendu (mp3, wav, flac, m4a, ogg)")
    relatif = f"sons/import-{uuid.uuid4().hex[:12]}{extension}"
    cible = medias.chemin_sur(ctx.dossier_projet(projet_id), relatif)
    try:
        await medias.ecrire_flux(request.stream(), cible, TAILLE_MAX_CHANSON)
    except medias.TropVolumineux:
        raise HTTPException(status_code=413, detail="Son trop volumineux (200 Mo au plus)") from None
    except medias.FichierVide:
        raise HTTPException(status_code=400, detail="Fichier vide") from None
    try:
        infos = ffmpeg.sonder(cible)
        duree = float(infos["duree_s"]) if infos.get("audio") else 0.0
    except Exception:  # noqa: BLE001 — ffprobe refuse le fichier : on le dit sans détail technique
        duree = 0.0
    if duree <= 0:
        cible.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Fichier audio illisible")
    try:
        return _executer(timeline.importer_son, ctx, projet_id, relatif, position_s, duree)
    except HTTPException:
        cible.unlink(missing_ok=True)
        raise


@routeur.get("/projets/{projet_id}/video/estimation")
def estimer_video(projet_id: str, request: Request) -> EstimationVideo:
    return _executer(video.estimer, _ctx(request), projet_id)


@routeur.get("/projets/{projet_id}/exports")
def lister_exports(projet_id: str, request: Request) -> list[ExportProjet]:
    return _executer(exports.lister, _ctx(request), projet_id)


@routeur.post("/projets/{projet_id}/exports", status_code=status.HTTP_201_CREATED)
def lancer_export(projet_id: str, entree: ExportEntree, request: Request) -> ExportProjet:
    return _executer(exports.lancer, _ctx(request), projet_id, entree)
