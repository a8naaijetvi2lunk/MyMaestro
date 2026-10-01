"""Actions programmées depuis la timeline (spec §6.3, régime « à la carte »).

Elles s'accumulent sans rien lancer ; « Lancer la file » les traduit en jobs, regroupés par type et par moteur, À LA
SUITE de tout ce qui est déjà en file dans ce régime (ordre maximal + 1 : deux lancements ne s'entrelacent pas).
Chaque action vise un plan : refaire (nouvelle prise, éventuellement avec un autre moteur ou « à cette position »
de la chanson), changer de moteur, passe DLSS5 sur la prise active, bruitage guidé par la vidéo du plan.
"""

from __future__ import annotations

import sqlite3
import subprocess
import threading

from pydantic import ValidationError

from ...contrat.modeles import (
    ActionEntree,
    ActionProgrammee,
    EtapePostProd,
    MoteurVideo,
    PlanModification,
    Projet,
    Regime,
    StatutAction,
    StatutJob,
    StatutTraitement,
    TypeAction,
)
from ...core import depot
from ...core.contexte import Contexte
from . import phases, timeline, video
from .moteurs import compatibilite
from .reglages import Dlss5, ReglagesDirector

ORDRE_CARTE = 1_000_000  # après tous les jobs du régime par phases
PAS_ORDRE = 3  # une action enfile au plus trois jobs chaînés (rendu, FlashVSR, DLSS5)
MOTS_MAX_BRUITAGE = 55  # MMAudio : CLIP coupe à 77 jetons
RANG_TYPE = {TypeAction.REFAIRE: 0, TypeAction.CHANGER_MOTEUR: 0, TypeAction.PASSE_DLSS5: 1, TypeAction.BRUITAGE: 2}


# Deux « Lancer la file » simultanés obtenaient la même base d'ordre et relançaient les mêmes actions : le corps de
# `lancer` est sérialisé. Verrou de module, pris AVANT `_verrou_gpu` et `_verrou_fin` (ordre documenté dans
# core/file.py) ; il n'est jamais tenu pendant une méthode de fin de la file.
_VERROU_LANCEMENT_ACTIONS = threading.Lock()


class ActionInvalide(ValueError):
    """Action refusée à la programmation (réponse 422)."""


def valider(cx: sqlite3.Connection, projet: Projet, entree: ActionEntree) -> ActionEntree:
    """Complète le plan depuis le clip et refuse une action impossible ; renvoie l'action complétée."""
    if entree.clip_id is not None:
        ligne = cx.execute("SELECT plan_id FROM clips WHERE id = ? AND projet_id = ?", (entree.clip_id, projet.id)).fetchone()
        if ligne is None:
            raise ActionInvalide("Ce clip n'appartient pas au projet")
        if entree.plan_id is None:
            entree = entree.model_copy(update={"plan_id": ligne["plan_id"]})
        elif ligne["plan_id"] is not None and ligne["plan_id"] != entree.plan_id:
            raise ActionInvalide("Ce clip appartient à un autre plan")
    plan = next((p for p in projet.plans if p.id == entree.plan_id), None)
    if entree.plan_id is not None and plan is None:
        raise ActionInvalide("Ce plan n'appartient pas au projet")
    if plan is None:
        raise ActionInvalide("Une action vise un plan (ou un clip de plan)")
    reglages = entree.reglages
    graine = reglages.get("graine")
    if graine is not None and (isinstance(graine, bool) or not isinstance(graine, int) or graine < 0):
        raise ActionInvalide("reglages.graine doit être un entier positif")
    moteur = reglages.get("moteur")
    if entree.type is TypeAction.CHANGER_MOTEUR or (entree.type is TypeAction.REFAIRE and moteur is not None):
        if not (isinstance(moteur, str) and moteur in {m.value for m in MoteurVideo}):
            raise ActionInvalide("reglages.moteur doit être l'un des moteurs vidéo")
    if entree.type in (TypeAction.REFAIRE, TypeAction.CHANGER_MOTEUR):
        if not (moteur or plan.moteur_video):
            raise ActionInvalide("Aucun moteur vidéo : cibler un plan avec moteur ou fournir reglages.moteur")
        if not plan.image_depart:
            raise ActionInvalide("Image de départ manquante pour ce plan")
        if moteur and MoteurVideo(moteur) is not plan.moteur_video:
            definition = phases.reglages(cx, projet).rendu.definition(MoteurVideo(moteur))
            verdict = compatibilite(plan, MoteurVideo(moteur), projet.format, definition)
            if not verdict.compatible:
                raise ActionInvalide(f"Moteur incompatible : {verdict.note}")
        elif plan.moteur_video is not None:  # même moteur : la recette a pu changer la définition depuis le découpage
            hors_grille = video.message_hors_grille([plan], projet.format, phases.reglages(cx, projet))
            if hors_grille:
                raise ActionInvalide(hors_grille)
        if reglages.get("a_la_position") and entree.clip_id is None:
            raise ActionInvalide("« À refaire à cette position » vise un clip")
        if reglages.get("a_la_position") and ligne["plan_id"] is None:
            raise ActionInvalide("« À refaire à cette position » vise un clip de plan")
        return entree
    prise = timeline.prise_active(projet, plan.id)
    if prise is None or prise.statut is not StatutTraitement.TERMINE:
        raise ActionInvalide("Aucun rendu terminé pour ce plan")
    if entree.type is TypeAction.PASSE_DLSS5:
        try:
            Dlss5.model_validate({**reglages, "actif": True})
        except ValidationError as exc:
            raise ActionInvalide(f"Réglages DLSS5 invalides : {exc.error_count()} erreur(s)") from None
    if entree.type is TypeAction.BRUITAGE:
        texte = reglages.get("prompt", "")
        if not isinstance(texte, str) or len(texte.split()) > MOTS_MAX_BRUITAGE:
            raise ActionInvalide(f"Invite de bruitage : un texte de {MOTS_MAX_BRUITAGE} mots au plus")
    return entree


def programmer(ctx: Contexte, projet_id: str, entree: ActionEntree) -> ActionProgrammee:
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        return depot.programmer_action(cx, projet_id, valider(cx, projet, entree))


def lister(ctx: Contexte, projet_id: str) -> list[ActionProgrammee]:
    with ctx.base.transaction() as cx:
        phases._projet(cx, projet_id)
        return depot.lister_actions(cx, projet_id, StatutAction.PROGRAMMEE)


def retirer(ctx: Contexte, projet_id: str, action_id: str) -> None:
    with ctx.base.transaction() as cx:
        phases._projet(cx, projet_id)
        if not depot.supprimer_action(cx, projet_id, action_id):
            raise KeyError(action_id)


def lancer(ctx: Contexte, projet_id: str) -> list[str]:
    """« Lancer la file » : toutes les actions programmées partent ; une action devenue impossible est signalée
    (erreur « actions » du Director) et les autres partent quand même."""
    with _VERROU_LANCEMENT_ACTIONS:
        return _lancer(ctx, projet_id)


def _lancer(ctx: Contexte, projet_id: str) -> list[str]:
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        regl = phases.reglages(cx, projet)
        programmees = depot.lister_actions(cx, projet_id, StatutAction.PROGRAMMEE)
    if any(a.type in (TypeAction.REFAIRE, TypeAction.CHANGER_MOTEUR, TypeAction.BRUITAGE) for a in programmees):
        phases._prevol(ctx, "maestro")  # ces actions enfilent des jobs Maestro ; un refus laisse les actions programmées
    # REFAIRE / CHANGER_MOTEUR rejouent la post-production : DLSS5 actif et absent ne doit pas partir sur le simulé
    rejoue_dlss5 = regl.postprod.dlss5.actif and any(a.type in (TypeAction.REFAIRE, TypeAction.CHANGER_MOTEUR) for a in programmees)
    if rejoue_dlss5 or any(a.type is TypeAction.PASSE_DLSS5 for a in programmees):
        phases._prevol(ctx, "dlss5")
    with ctx.base.transaction() as cx:
        # Relues : une action retirée pendant le pré-vol ne part pas.
        encore = {action.id for action in depot.lister_actions(cx, projet_id, StatutAction.PROGRAMMEE)}
        programmees = [action for action in programmees if action.id in encore]
        depot.marquer_actions(cx, [action.id for action in programmees], StatutAction.LANCEE)
    moteurs = {plan.id: plan.moteur_video.value if plan.moteur_video else "" for plan in projet.plans}
    triees = sorted(
        programmees,
        key=lambda a: (RANG_TYPE[a.type], str(a.reglages.get("moteur") or moteurs.get(a.plan_id or "", ""))),
    )
    base = max(ORDRE_CARTE, ctx.file.ordre_max(Regime.CARTE) + 1)
    jobs: list[str] = []
    refus: list[str] = []
    chaines = _chaines_en_file(ctx, projet_id)  # plan → (nouvelle prise, [(job, tâche, fichier)])
    for rang, action in enumerate(triees):
        try:
            jobs += _lancer_une(ctx, projet_id, action, regl, base + PAS_ORDRE * rang, chaines)
        except (phases.ErreurPhase, ActionInvalide, KeyError, OSError, subprocess.CalledProcessError) as exc:
            refus.append(f"{action.type.value} : {exc}")
    phases._noter_erreur(ctx, projet_id, "actions", " ; ".join(refus) or None)
    return jobs


def _chaines_en_file(ctx: Contexte, projet_id: str) -> dict[str, tuple[str, list[tuple[str, str, str]]]]:
    """Amorce des chaînes avec les prises refaites d'un lot précédent dont le rendu n'est pas fini : les actions de ce
    lot doivent viser cette nouvelle prise (elle remplacera l'active), pas celle qui va être remplacée."""
    jobs = ctx.file.lister_projet(projet_id)
    # Un job en échec ou annulé, et tout ce qui l'attend, ne rendra jamais rien : s'y accrocher perdrait l'action.
    morts = {j.id for j in jobs if j.statut in (StatutJob.ECHEC, StatutJob.ANNULE)}
    for job in jobs:  # ordre de la file = ordre des prérequis
        if morts.intersection(job.apres):
            morts.add(job.id)
    chaines: dict[str, tuple[str, list[tuple[str, str, str]]]] = {}
    for job in jobs:
        if job.donnees.get("tache") != "video.plan" or job.statut in phases.FINAUX:
            continue
        prise_id = str(job.donnees["prise_id"])
        chaines[str(job.donnees["plan_id"])] = (prise_id, [
            (j.id, str(j.donnees["tache"]), str(j.donnees.get("fichier", "")))
            for j in jobs
            if j.id not in morts
            and j.donnees.get("prise_id") == prise_id and str(j.donnees.get("tache", "")).startswith(("video.", "postprod."))
        ])
    return chaines


def _lancer_une(ctx: Contexte, projet_id: str, action: ActionProgrammee, regl: ReglagesDirector, ordre: int, chaines: dict) -> list[str]:
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        valider(cx, projet, ActionEntree(type=action.type, plan_id=action.plan_id, clip_id=action.clip_id, reglages=action.reglages))
    plan = next(p for p in projet.plans if p.id == action.plan_id)
    reglages = action.reglages
    if action.type in (TypeAction.REFAIRE, TypeAction.CHANGER_MOTEUR):
        moteur = MoteurVideo(reglages.get("moteur") or plan.moteur_video)
        if moteur is not plan.moteur_video:
            plan = phases.modifier_plan(ctx, projet_id, plan.id, PlanModification(moteur_video=moteur))
            timeline.ajuster_au_plan(ctx, projet_id, plan)
        if reglages.get("a_la_position") and action.clip_id:
            plan = timeline.ancrer_a_la_position(ctx, projet_id, action.clip_id)
        with ctx.base.transaction() as cx:
            projet = phases._projet(cx, projet_id)
        prise_id, jobs = video.enfiler_rendu(
            ctx, projet, plan, regl, regime=Regime.CARTE, lancements={}, ordres=(ordre, ordre + 1, ordre + 2),
            activer=False, graine=reglages.get("graine"), action_id=action.id,
        )
        # Les actions suivantes sur ce plan (passe DLSS5, bruitage) visent cette nouvelle prise, à la suite de sa chaîne.
        lus = [ctx.file.lire(job) for job in jobs]
        chaines[plan.id] = (prise_id, [(j.id, str(j.donnees["tache"]), str(j.donnees["fichier"])) for j in lus if j is not None])
        return jobs
    nouvelle = chaines.get(plan.id)
    prise = timeline.prise_active(projet, plan.id)
    if prise is None:
        raise ActionInvalide("Aucun rendu terminé pour ce plan")
    if action.type is TypeAction.PASSE_DLSS5:
        prise_id, apres = prise.id, None
        if nouvelle is not None:  # plan refait dans ce lancement : la passe part de la chaîne de la nouvelle prise
            prise_id = nouvelle[0]
            job, _, source = next(e for e in reversed(nouvelle[1]) if e[1] != "postprod.dlss5")
            apres = job
        else:
            source, apres = _source_dlss5(ctx, projet_id, prise)
        if not source:
            raise ActionInvalide("Rendu sans fichier : refais d'abord le plan")
        reglages_dlss5 = Dlss5.model_validate(
            {**regl.postprod.dlss5.model_dump(), **reglages, "actif": True}
        ).model_dump(mode="json", exclude={"actif"})
        job, _ = video.enfiler_postprod(
            ctx, projet_id, plan, prise_id, EtapePostProd.DLSS5, reglages_dlss5, source=source, apres=apres,
            regime=Regime.CARTE, lancement=None, ordre=ordre, action_id=action.id,
        )
        return [job]
    prompt = str(reglages.get("prompt") or plan.prompt_son)
    if nouvelle is not None:  # plan refait dans ce lancement : le son suit la vidéo de la nouvelle prise
        job, _, fichier = nouvelle[1][-1]
        return [video.enfiler_bruitage(
            ctx, projet, plan, fichier, prompt=prompt, ordre=ordre, action_id=action.id, prise_id=nouvelle[0], apres=job
        )]
    fichier = timeline.fichier_actif(projet, plan.id)
    if not fichier:
        raise ActionInvalide("Rendu sans fichier : refais d'abord le plan")
    return [video.enfiler_bruitage(ctx, projet, plan, fichier, prompt=prompt, ordre=ordre, action_id=action.id, prise_id=prise.id)]


def _source_dlss5(ctx: Contexte, projet_id: str, prise) -> tuple[str | None, str | None]:
    """Source de la passe DLSS5 et job à attendre : FlashVSR encore en file ou en cours s'il y en a un, sinon la
    dernière sortie FlashVSR terminée, sinon le brut."""
    en_attente = [
        job for job in ctx.file.lister_projet(projet_id)
        if job.donnees.get("prise_id") == prise.id and job.donnees.get("tache") == "postprod.flashvsr" and job.statut not in phases.FINAUX
    ]
    if en_attente:
        return str(en_attente[-1].donnees["fichier"]), en_attente[-1].id
    flashvsr = next(
        (s for s in reversed(prise.sorties) if s.etape is EtapePostProd.FLASHVSR and s.statut is StatutTraitement.TERMINE and s.fichier),
        None,
    )
    return (flashvsr.fichier if flashvsr is not None else prise.fichier_brut), None
