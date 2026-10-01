"""Timeline du Director musique (spec §6.2) : création depuis le découpage, règles d'édition, sources.

- Création : un emplacement par plan, à sa position dans la chanson (piste V1), et la chanson en A0. Un plan
  dont la durée a été recalée sur la grille de son moteur est rogné pour ne pas mordre sur le suivant.
- Règles : aucun chevauchement dans une piste ; la chanson (A0) ne bouge pas ; un plan chanté est ancré
  (position − entrée = début du plan dans la chanson) : on peut le rogner, pas le déplacer, sauf à le
  déverrouiller (lip-sync cassé, « à refaire à cette position ») ; couper = deux clips sur la même prise.
- Sources : un clip vidéo montre la dernière sortie disponible de la prise active de son plan.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading

from ...contrat.modeles import (
    Clip,
    ClipModification,
    EtatClip,
    Nettoyage,
    Plan,
    Prise,
    Projet,
    RolePlan,
    Segment,
    StatutJob,
    StatutTraitement,
    Timeline,
    TypePiste,
)
from ...core import depot, medias
from ...core.contexte import Contexte
from ...core.export import SourceClip, projeter
from ...core.grilles import FPS_MAITRE
from ...outils import ffmpeg
from . import phases
from .phases import ErreurPhase

TOLERANCE_S = 1e-3

# Choix de prise ou de sortie, nettoyage et lancement d'un export s'excluent : sans lui, un nettoyage pouvait
# supprimer la prise qu'un choix ou un export venait de retenir. Verrou de module, pris AVANT `_verrou_gpu` et
# `_verrou_fin` (ordre documenté dans core/file.py) et jamais tenu pendant une méthode de fin de la file.
_VERROU_PRISES = threading.Lock()
PISTES_MAX = 8  # par type de piste


def ordonner_pistes(pistes: list[str]) -> list[str]:
    """Pistes vidéo de la plus haute à la plus basse, puis pistes audio (A0, la chanson, en tête)."""
    return sorted(set(pistes), key=lambda p: (0, -int(p[1:])) if p.startswith("V") else (1, int(p[1:])))


def timeline_initiale(projet: Projet) -> Timeline:
    plans = sorted(projet.plans, key=lambda p: p.debut_s)
    duree = projet.duree_chanson_s or max((p.debut_s + p.duree_s for p in plans), default=1.0)
    clips: list[Clip] = []
    if projet.chanson:
        clips.append(Clip(id=depot.nouvel_id("clip"), piste="A0", fichier_audio=projet.chanson, position_s=0,
                          sortie_s=duree, verrou_chanson=True))
    for plan, suivant in zip(plans, [*plans[1:], None]):
        place = plan.duree_s if suivant is None else min(plan.duree_s, suivant.debut_s - plan.debut_s)
        if place > TOLERANCE_S:
            clips.append(Clip(id=depot.nouvel_id("clip"), piste="V1", plan_id=plan.id, position_s=plan.debut_s,
                              sortie_s=round(place, 6), verrou_chanson=plan.role is RolePlan.CHANTE))
    return Timeline(projet_id=projet.id, fps_maitre=FPS_MAITRE, duree_chanson_s=duree, pistes=["V1", "A0", "A1"], clips=clips)


def assurer(ctx: Contexte, projet_id: str) -> Timeline:
    """Crée la timeline du projet si elle n'existe pas encore ; renvoie la timeline en place."""
    with ctx.base.transaction() as cx:
        existante = depot.lire_timeline(cx, projet_id)
        if existante is not None:
            return existante
        depot.inserer_timeline(cx, timeline_initiale(phases._projet(cx, projet_id)))
        return depot.lire_timeline(cx, projet_id)


def lire(ctx: Contexte, projet_id: str) -> Timeline | None:
    """Timeline et état de chaque clip ; un rendu en cours porte sa progression (lue dans la file)."""
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        timeline = depot.lire_timeline(cx, projet_id)
    if timeline is None:
        return None
    en_cours = {
        str(job.donnees.get("prise_id")): job.progression
        for job in ctx.file.lister_projet(projet_id)
        if job.statut is StatutJob.EN_COURS and job.donnees.get("tache") == "video.plan"
    }
    actives = {plan.id: plan.prise_active_id for plan in projet.plans}
    clips: list[Clip] = []
    for clip in timeline.clips:
        prise_id = actives.get(clip.plan_id) if clip.plan_id else None
        if prise_id is not None and prise_id in en_cours and clip.etat in (EtatClip.EN_FILE, EtatClip.EN_RENDU):
            clip = clip.model_copy(update={"etat": EtatClip.EN_RENDU, "progression": en_cours[prise_id]})
        clips.append(clip)
    return timeline.model_copy(update={"clips": clips})


# --- Règles d'édition ------------------------------------------------------------------------------


def _lire(cx: sqlite3.Connection, projet_id: str) -> tuple[Projet, Timeline]:
    projet = phases._projet(cx, projet_id)
    timeline = depot.lire_timeline(cx, projet_id)
    if timeline is None:
        raise ErreurPhase("Pas encore de timeline : valide d'abord les images de départ")
    return projet, timeline


def _clip(timeline: Timeline, clip_id: str) -> Clip:
    clip = next((c for c in timeline.clips if c.id == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    return clip


def _plan(projet: Projet, plan_id: str | None) -> Plan:
    plan = next((p for p in projet.plans if p.id == plan_id), None)
    if plan is None:
        raise KeyError(plan_id)
    return plan


def _ancre(clip: Clip, plan: Plan) -> bool:
    return abs(clip.position_s - clip.entree_s - plan.debut_s) <= TOLERANCE_S


def _place_libre(timeline: Timeline, clip: Clip) -> bool:
    return not any(
        autre.id != clip.id and autre.piste == clip.piste
        and autre.position_s < clip.fin_s - 1e-6 and clip.position_s < autre.fin_s - 1e-6
        for autre in timeline.clips
    )


def _duree_fichier(ctx: Contexte, projet_id: str, fichier: str) -> float | None:
    """Durée du fichier son ; None si la sonde échoue (on ne bloque pas le montage pour ça)."""
    try:
        return float(ffmpeg.sonder(medias.chemin_sur(ctx.dossier_projet(projet_id), fichier))["duree_s"])
    except Exception:  # noqa: BLE001 — sonde indisponible ou fichier illisible : pas de garde-fou
        return None


def modifier_clip(ctx: Contexte, projet_id: str, clip_id: str, modification: ClipModification) -> Timeline:
    with ctx.base.transaction() as cx:
        projet, timeline = _lire(cx, projet_id)
        clip = _clip(timeline, clip_id)
        champs = modification.model_dump(exclude_none=True)
        if clip.piste == "A0" and set(champs) - {"volume"}:
            raise ErreurPhase("La chanson est la piste maîtresse : seul son volume se règle")
        if clip.piste.startswith("V") and set(champs) & {"volume", "fondu_entree_s", "fondu_sortie_s"}:
            raise ErreurPhase("Volume et fondus : clips audio seulement")
        nouveau = clip.model_copy(update=champs)
        if nouveau.piste not in timeline.pistes:
            raise ErreurPhase(f"Piste inconnue : {nouveau.piste}")
        if nouveau.piste[0] != clip.piste[0] or (nouveau.piste == "A0") != (clip.piste == "A0"):
            raise ErreurPhase("Un clip reste sur une piste de son type (vidéo, son, chanson)")
        if nouveau.sortie_s <= nouveau.entree_s + TOLERANCE_S:
            raise ErreurPhase("Le clip doit garder une durée")
        if nouveau.position_s >= timeline.duree_chanson_s:
            raise ErreurPhase("Le clip doit commencer avant la fin de la chanson")
        plan = _plan(projet, nouveau.plan_id) if nouveau.plan_id else None
        if plan is not None and nouveau.sortie_s > plan.duree_s + TOLERANCE_S:
            raise ErreurPhase(f"Le rendu du plan dure {plan.duree_s:.2f} s : le clip ne peut pas aller au-delà")
        if clip.piste != "A0" and clip.piste.startswith("A") and clip.fichier_audio and "sortie_s" in champs:
            duree = _duree_fichier(ctx, projet_id, clip.fichier_audio)
            if duree is not None and nouveau.sortie_s > duree + TOLERANCE_S:
                raise ErreurPhase(f"Le son dure {duree:.2f} s : le clip ne peut pas aller au-delà")
        if plan is not None and nouveau.verrou_chanson and not _ancre(nouveau, plan):
            if clip.verrou_chanson:
                raise ErreurPhase("Plan ancré à la chanson : déverrouille-le pour le déplacer (le lip-sync sera cassé)")
            raise ErreurPhase("Ce clip n'est plus à sa place dans la chanson : programme « à refaire à cette position »")
        if not _place_libre(timeline, nouveau):
            raise ErreurPhase(f"Chevauchement sur la piste {nouveau.piste}")
        depot.maj_clip(cx, clip_id, **champs)
        return depot.lire_timeline(cx, projet_id)


def couper(ctx: Contexte, projet_id: str, clip_id: str, temps_s: float) -> Timeline:
    """Coupe non destructive : deux clips sur la même prise, aux entrées et sorties complémentaires."""
    with ctx.base.transaction() as cx:
        _, timeline = _lire(cx, projet_id)
        clip = _clip(timeline, clip_id)
        if clip.piste == "A0":
            raise ErreurPhase("La chanson ne se coupe pas")
        marge = 1 / timeline.fps_maitre
        if not clip.position_s + marge <= temps_s <= clip.fin_s - marge:
            raise ErreurPhase("Coupe hors du clip (au moins une image de chaque côté)")
        point = clip.entree_s + (temps_s - clip.position_s)
        second = clip.model_copy(update={"id": depot.nouvel_id("clip"), "position_s": temps_s, "entree_s": point, "fondu_entree_s": 0.0})
        depot.maj_clip(cx, clip_id, sortie_s=point, fondu_sortie_s=0.0)
        depot.inserer_clip(cx, projet_id, second)
        return depot.lire_timeline(cx, projet_id)


def supprimer_clip(ctx: Contexte, projet_id: str, clip_id: str) -> Timeline:
    with ctx.base.transaction() as cx:
        _, timeline = _lire(cx, projet_id)
        clip = _clip(timeline, clip_id)
        if clip.piste == "A0":
            raise ErreurPhase("La chanson ne se supprime pas")
        if clip.plan_id and sum(1 for c in timeline.clips if c.plan_id == clip.plan_id) == 1:
            raise ErreurPhase("Dernier clip de ce plan : rogne-le plutôt que de le retirer")
        depot.supprimer_clip(cx, clip_id)
        return depot.lire_timeline(cx, projet_id)


def ajouter_piste(ctx: Contexte, projet_id: str, type_: TypePiste) -> Timeline:
    with ctx.base.transaction() as cx:
        _, timeline = _lire(cx, projet_id)
        prefixe = "V" if type_ is TypePiste.VIDEO else "A"
        numeros = [int(p[1:]) for p in timeline.pistes if p.startswith(prefixe) and p != "A0"]
        if len(numeros) >= PISTES_MAX:
            raise ErreurPhase(f"{PISTES_MAX} pistes de ce type au plus")
        nouvelle = f"{prefixe}{max(numeros, default=0) + 1}"
        depot.definir_pistes(cx, projet_id, ordonner_pistes([*timeline.pistes, nouvelle]))
        return depot.lire_timeline(cx, projet_id)


def placer_son(cx: sqlite3.Connection, projet_id: str, fichier: str, position_s: float, entree_s: float, sortie_s: float) -> Clip:
    """Pose un son sur la première piste audio libre à cet endroit (une nouvelle piste si toutes sont prises).
    S'appelle dans une transaction ouverte."""
    timeline = depot.lire_timeline(cx, projet_id)
    if timeline is None:
        raise ErreurPhase("Pas encore de timeline : valide d'abord les images de départ")
    clip = Clip(id=depot.nouvel_id("clip"), piste="A1", fichier_audio=fichier, position_s=position_s, entree_s=entree_s, sortie_s=sortie_s)
    audio = [p for p in ordonner_pistes(timeline.pistes) if p.startswith("A") and p != "A0"]
    for piste in audio:
        candidat = clip.model_copy(update={"piste": piste})
        if _place_libre(timeline, candidat):
            depot.inserer_clip(cx, projet_id, candidat)
            return candidat
    if len(audio) >= PISTES_MAX:
        raise ErreurPhase("Plus de place : toutes les pistes audio sont occupées à cet endroit")
    nouvelle = f"A{max((int(p[1:]) for p in audio), default=0) + 1}"
    depot.definir_pistes(cx, projet_id, ordonner_pistes([*timeline.pistes, nouvelle]))
    candidat = clip.model_copy(update={"piste": nouvelle})
    depot.inserer_clip(cx, projet_id, candidat)
    return candidat


def importer_son(ctx: Contexte, projet_id: str, fichier: str, position_s: float, duree_s: float) -> Timeline:
    with ctx.base.transaction() as cx:
        _lire(cx, projet_id)
        placer_son(cx, projet_id, fichier, position_s, 0.0, duree_s)
        return depot.lire_timeline(cx, projet_id)


def ajuster_au_plan(ctx: Contexte, projet_id: str, plan: Plan) -> None:
    """Après un changement de moteur (durée recalée), les clips du plan ne dépassent plus son rendu."""
    with ctx.base.transaction() as cx:
        timeline = depot.lire_timeline(cx, projet_id)
        for clip in timeline.clips if timeline is not None else []:
            if clip.plan_id != plan.id or clip.sortie_s <= plan.duree_s + TOLERANCE_S:
                continue
            if clip.entree_s < plan.duree_s - TOLERANCE_S:
                depot.maj_clip(cx, clip.id, sortie_s=round(plan.duree_s, 6))
            else:
                depot.maj_clip(
                    cx, clip.id, entree_s=0.0, sortie_s=round(min(clip.duree_s, plan.duree_s), 6),
                    verrou_chanson=clip.verrou_chanson and abs(clip.position_s - plan.debut_s) <= TOLERANCE_S,
                )


def ancrer_a_la_position(ctx: Contexte, projet_id: str, clip_id: str) -> Plan:
    """« À refaire à cette position » : le plan prendra son son à l'endroit où son clip a été posé."""
    with ctx.base.transaction() as cx:
        projet, timeline = _lire(cx, projet_id)
        clip = _clip(timeline, clip_id)
        if not clip.plan_id:
            raise ErreurPhase("« À refaire à cette position » vise un clip de plan")
        plan = _plan(projet, clip.plan_id)
        debut = round(max(0.0, clip.position_s - clip.entree_s), 6)
        depot.maj_plan(cx, plan.id, debut_s=debut)
        for autre in timeline.clips:
            if autre.plan_id == plan.id:
                ancre = plan.role is RolePlan.CHANTE and abs(autre.position_s - autre.entree_s - debut) <= TOLERANCE_S
                depot.maj_clip(cx, autre.id, verrou_chanson=ancre)
        return _plan(phases._projet(cx, projet_id), plan.id)


# --- Prises, sorties et nettoyage ------------------------------------------------------------------


def choisir_prise(ctx: Contexte, projet_id: str, plan_id: str, prise_id: str) -> Projet:
    with _VERROU_PRISES, ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        _plan(projet, plan_id)
        prise = next((p for p in projet.prises if p.id == prise_id and p.plan_id == plan_id), None)
        if prise is None:
            raise KeyError(prise_id)
        if prise.statut is not StatutTraitement.TERMINE:
            raise ErreurPhase("Seule une prise rendue peut partir au montage")
        depot.maj_plan(cx, plan_id, prise_active_id=prise_id)
        return phases._projet(cx, projet_id)


def choisir_sortie(ctx: Contexte, projet_id: str, prise_id: str, sortie_id: str | None) -> Projet:
    """Sortie de post-production qui part au montage ; None : le rendu brut."""
    with _VERROU_PRISES, ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        prise = next((p for p in projet.prises if p.id == prise_id), None)
        if prise is None:
            raise KeyError(prise_id)
        if sortie_id is not None:
            sortie = next((s for s in prise.sorties if s.id == sortie_id), None)
            if sortie is None:
                raise KeyError(sortie_id)
            if sortie.statut is not StatutTraitement.TERMINE:
                raise ErreurPhase("Seule une sortie terminée peut partir au montage")
        depot.maj_prise(cx, prise_id, sortie_active_id=sortie_id)
        return phases._projet(cx, projet_id)


def nettoyer(ctx: Contexte, projet_id: str) -> Nettoyage:
    """Supprime les prises non retenues (ni actives, ni en cours de traitement) et leurs fichiers.

    Les fichiers partent d'abord : une prise dont le dossier résiste (fichier tenu ouvert) garde sa ligne,
    le prochain nettoyage la retrouvera.
    """
    with _VERROU_PRISES:  # du calcul des cibles à la fin de la seconde transaction
        occupees: set[str] = set()
        for job in ctx.file.lister_projet(projet_id):
            if job.statut in phases.FINAUX:
                continue
            occupees.add(str(job.donnees.get("prise_id")))
            occupees.update(str(prise) for prise in job.donnees.get("prises") or [])  # prises citées par un export en cours

        def cibles(projet: Projet) -> list[Prise]:
            actives = {plan.prise_active_id for plan in projet.plans}
            return [
                prise for prise in projet.prises
                if prise.id not in actives and prise.id not in occupees
                and prise.statut in (StatutTraitement.TERMINE, StatutTraitement.ECHEC)
            ]

        with ctx.base.transaction() as cx:
            a_nettoyer = cibles(phases._projet(cx, projet_id))
        octets = 0
        racine = ctx.dossier_projet(projet_id)
        for prise in a_nettoyer:
            try:
                dossier = medias.chemin_sur(racine, f"prises/{prise.id}")
            except medias.CheminInterdit:
                continue
            if not dossier.is_dir():
                continue
            try:
                taille = sum(fichier.stat().st_size for fichier in dossier.rglob("*") if fichier.is_file())
                shutil.rmtree(dossier)
            except OSError:
                continue  # dossier résistant : ni compté ni supprimé de la base
            octets += taille
        supprimees = 0
        with ctx.base.transaction() as cx:
            for prise in cibles(phases._projet(cx, projet_id)):
                try:
                    dossier = medias.chemin_sur(racine, f"prises/{prise.id}")
                except medias.CheminInterdit:
                    continue
                if not dossier.exists() and depot.supprimer_prise(cx, prise.id):
                    supprimees += 1
        return Nettoyage(prises_supprimees=supprimees, octets_liberes=octets)


# --- Sources de la projection ------------------------------------------------------------------------


def prise_active(projet: Projet, plan_id: str) -> Prise | None:
    plan = next((p for p in projet.plans if p.id == plan_id), None)
    if plan is None:
        return None
    return next((p for p in projet.prises if p.id == plan.prise_active_id), None)


def fichier_actif(projet: Projet, plan_id: str) -> str | None:
    """Dernière sortie disponible de la prise active (la sortie active, sinon le brut) ; None sans rendu."""
    prise = prise_active(projet, plan_id)
    if prise is None or prise.statut is not StatutTraitement.TERMINE:
        return None
    sortie = next(
        (s for s in prise.sorties if s.id == prise.sortie_active_id and s.statut is StatutTraitement.TERMINE and s.fichier),
        None,
    )
    return sortie.fichier if sortie is not None else prise.fichier_brut


def _existe(ctx: Contexte, projet_id: str, relatif: str) -> bool:
    try:
        return medias.chemin_sur(ctx.dossier_projet(projet_id), relatif).is_file()
    except medias.CheminInterdit:
        return False


def segments(ctx: Contexte, projet_id: str) -> list[Segment] | None:
    """Projection de la timeline, telle que l'aperçu la montre et que l'export la rend."""
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        timeline = depot.lire_timeline(cx, projet_id)
    if timeline is None:
        return None
    sources: dict[str, SourceClip] = {}
    for clip in timeline.clips:
        if clip.plan_id:
            fichier = fichier_actif(projet, clip.plan_id)
            sources[clip.id] = SourceClip(fichier if fichier and _existe(ctx, projet_id, fichier) else None)
    return projeter(timeline, sources)
