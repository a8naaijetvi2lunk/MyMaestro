"""Phases 0 à 4 du Director musique : lancement, suivi des jobs, validation (spec §6.1, D12).

Le module décide ce qui part dans la file et ce que devient chaque résultat ; le socle exécute.
Chaque lancement de phase porte un identifiant : la phase se termine quand tous les jobs de SON
lancement sont finaux, ce qui ignore les jobs d'un lancement précédent (prompts régénérés, image
refaite). L'écriture est pilotée à la main (brief, concepts, chat) et se termine quand le
découpage est appliqué. Arrêt décoché : la validation est sautée et la phase suivante démarre.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import ValidationError

from ...contrat.modeles import (
    CastingModification,
    EtatPhase,
    MoteurImage,
    MoteurVideo,
    Plan,
    PlanModification,
    Projet,
    Regime,
    RolePlan,
    StatutJob,
    Voie,
)
from ...core import depot, grilles, medias
from ...core.contexte import Contexte
from ...core.file import JobFile
from ...core.grilles import grille, resolution_rendu
from ...connectors.registre import MoteurNonInstalle
from ...outils.systeme import MemoireInsuffisante
from . import gabarits
from .analyse_maestro import analyse_depuis_maestro
from .decoupage import normaliser
from .manifeste import MANIFESTE, ordre_job
from .modeles import (
    Analyse,
    Brief,
    EtatDirector,
    LigneParoles,
    MessageChat,
    ReponseChat,
    ReponseConcepts,
    ReponseDecoupage,
    ReponsePrompts,
)
from .moteurs import compatibilite
from .reglages import Fournisseur, ReglagesDirector

MODULE = MANIFESTE.id
PHASES = ("creation", "analyse", "ecriture", "prompts", "images", "video", "postprod", "export")
SUIVANTE = {"analyse": "ecriture", "ecriture": "prompts", "prompts": "images", "images": "video"}
LIBELLES_ETAPE = {"image": "image", "video": "vidéo", "son": "son"}
FINAUX = {StatutJob.TERMINE, StatutJob.ECHEC, StatutJob.ANNULE}


class ErreurPhase(ValueError):
    """Action impossible dans l'état actuel du projet (réponse 409 côté API)."""


def etat_initial() -> dict[str, EtatPhase]:
    return {phase: EtatPhase.EN_COURS if phase == "creation" else EtatPhase.A_FAIRE for phase in PHASES}


def reglages(cx: sqlite3.Connection, projet: Projet) -> ReglagesDirector:
    """Réglages de la recette du projet, complétés par défaut ; une recette invalide retombe sur les défauts."""
    recette = depot.lire_recette(cx, projet.recette_id) if projet.recette_id else None
    valeurs = recette.valeurs if recette else {}
    try:
        regl = ReglagesDirector.model_validate(valeurs)
    except ValidationError:
        regl = ReglagesDirector()
        valeurs = {}
    rendu = valeurs.get("rendu")
    if not isinstance(rendu, dict) or "h3" not in rendu:  # H3 non fourni : défaut de la carte détectée, pas du schéma (544p)
        regl.rendu.h3 = grilles.definition_par_defaut(MoteurVideo.H3, projet.format).value
    return regl


# --- Lecture et petites écritures -------------------------------------------------------------------


def _projet(cx: sqlite3.Connection, projet_id: str) -> Projet:
    projet = depot.lire_projet(cx, projet_id)
    if projet is None or projet.module != MODULE:
        raise KeyError(projet_id)
    return projet


def _casting_pour_llm(cx: sqlite3.Connection, projet: Projet) -> list[dict[str, str]]:
    """Le casting tel que le LLM doit le connaître : un identifiant seul ne lui dit pas qui est à l'image."""
    fiches = {f.id: f for f in depot.lister_fiches(cx)}
    return [{"id": f.id, "nom": f.nom, "type": f.type.value, "description": f.description}
            for f in (fiches.get(fiche_id) for fiche_id in projet.casting) if f is not None]


def _ecriture(cx: sqlite3.Connection, projet_id: str) -> dict[str, Any]:
    return dict(depot.lire_donnees_module(cx, projet_id).get("ecriture") or {})


def _definir(ctx: Contexte, projet_id: str, phase: str, etat: EtatPhase) -> None:
    with ctx.base.transaction() as cx:
        depot.definir_etat_phase(cx, projet_id, phase, etat)
    ctx.publier({"type": "phase", "projet_id": projet_id, "phase": phase, "etat": etat.value})


def _noter_erreur(ctx: Contexte, projet_id: str, cle: str, message: str | None) -> None:
    with ctx.base.transaction() as cx:
        erreurs = dict(depot.lire_donnees_module(cx, projet_id).get("erreurs") or {})
        if message is None:
            erreurs.pop(cle, None)
        else:
            erreurs[cle] = message
        depot.modifier_donnees_module(cx, projet_id, "erreurs", erreurs or None)


def _ouvrir_lancement(ctx: Contexte, projet_id: str, phase: str) -> str:
    """Nouveau lancement : annule les jobs encore en file du précédent, passe la phase en cours."""
    with ctx.base.transaction() as cx:
        lancements = dict(depot.lire_donnees_module(cx, projet_id).get("lancements") or {})
        precedent = lancements.get(phase)
        lancement = depot.nouvel_id("lancement")
        lancements[phase] = lancement
        depot.modifier_donnees_module(cx, projet_id, "lancements", lancements)
        _regler_rejetes(cx, projet_id, phase, None)
    if precedent:
        for job in ctx.file.lister_lancement(precedent):
            if job.statut is StatutJob.EN_FILE:
                ctx.file.annuler(job.id)
    _definir(ctx, projet_id, phase, EtatPhase.EN_COURS)
    _noter_erreur(ctx, projet_id, phase, None)
    return lancement


def _rejetes(cx: sqlite3.Connection, projet_id: str, phase: str) -> set[str]:
    """Jobs du lancement courant dont la sortie a été refusée (leur statut reste TERMINE dans la file)."""
    return set((depot.lire_donnees_module(cx, projet_id).get("sorties_rejetees") or {}).get(phase) or [])


def _regler_rejetes(cx: sqlite3.Connection, projet_id: str, phase: str, ids: set[str] | None) -> None:
    tous = dict(depot.lire_donnees_module(cx, projet_id).get("sorties_rejetees") or {})
    if ids:
        tous[phase] = sorted(ids)
    else:
        tous.pop(phase, None)
    depot.modifier_donnees_module(cx, projet_id, "sorties_rejetees", tous or None)


def _lancement_courant(ctx: Contexte, projet_id: str, phase: str) -> str | None:
    with ctx.base.transaction() as cx:
        return (depot.lire_donnees_module(cx, projet_id).get("lancements") or {}).get(phase)


def _enfiler(ctx: Contexte, projet_id: str, phase: str, lancement: str, tache: str, *, connecteur: str, voie: Voie,
             modele: str | None, libelle: str, indice: int = 0, donnees: dict[str, Any] | None = None) -> str:
    return ctx.file.ajouter(
        voie=voie, connecteur=connecteur, modele=modele, projet_id=projet_id, phase=phase,
        ordre=ordre_job(phase, indice), regime=Regime.PHASES, libelle=libelle,
        donnees={"module": MODULE, "tache": tache, "lancement": lancement, **(donnees or {})},
    )


def _voie_llm(fournisseur: Fournisseur) -> tuple[str, Voie]:
    return ("bonsai", Voie.GPU) if fournisseur is Fournisseur.BONSAI else ("claude", Voie.CLOUD)


def _resume_plan(plan: Plan) -> dict[str, Any]:
    return {"id": plan.id, "role": plan.role.value, "debut_s": plan.debut_s, "duree_s": plan.duree_s,
            "paroles": plan.paroles, "description": plan.description, "fiches": plan.fiches}


# --- Création -----------------------------------------------------------------------------------------


def televerser_fini(ctx: Contexte, projet_id: str, chanson: str, duree_s: float) -> None:
    """Chanson enregistrée (chemin relatif au dossier du projet) : la création est terminée."""
    with ctx.base.transaction() as cx:
        _projet(cx, projet_id)
        depot.maj_projet(cx, projet_id, chanson=chanson, duree_chanson_s=duree_s)
    _definir(ctx, projet_id, "creation", EtatPhase.TERMINE)


# --- Lancement et validation des phases ----------------------------------------------------------


def _prevol(ctx: Contexte, connecteur: str) -> None:
    """Refuse de lancer une phase qui démarrerait un moteur réel sans la marge de mémoire nécessaire (409 lisible)."""
    try:
        ctx.prevol(connecteur)
    except MemoireInsuffisante as exc:
        raise ErreurPhase(str(exc)) from None
    except MoteurNonInstalle as exc:
        astuce = " (ou choisis l'autre fournisseur dans la recette)" if connecteur in ("claude", "bonsai") else ""
        raise ErreurPhase(f"{exc}{astuce}") from None


def lancer_phase(ctx: Contexte, projet_id: str, phase: str) -> None:
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        regl = reglages(cx, projet)
        concept = _concept_retenu(_ecriture(cx, projet_id))
        casting = _casting_pour_llm(cx, projet)
    if phase == "analyse":
        if not projet.chanson or not projet.duree_chanson_s:
            raise ErreurPhase("Chanson manquante : téléverse-la d'abord")
        if projet.plans:
            raise ErreurPhase("Le découpage existe déjà : l'analyse ne se relance plus (crée un nouveau projet pour repartir de zéro)")
        _prevol(ctx, "maestro")
        lancement = _ouvrir_lancement(ctx, projet_id, phase)
        _enfiler(ctx, projet_id, phase, lancement, "analyse", connecteur="maestro", voie=Voie.GPU, modele="analyse_audio",
                 libelle="Analyse de la chanson",
                 donnees={"chanson": str(ctx.dossier_projet(projet_id) / projet.chanson), "paroles": projet.paroles,
                          "duree_s": projet.duree_chanson_s})
    elif phase == "ecriture":
        if projet.etat_phases.get("analyse") is not EtatPhase.TERMINE:
            raise ErreurPhase("L'analyse doit être terminée avant l'écriture")
        _ouvrir_lancement(ctx, projet_id, phase)
    elif phase == "prompts":
        if not projet.plans:
            raise ErreurPhase("Aucun plan : écris d'abord le découpage")
        for connecteur_llm in dict.fromkeys(_voie_llm(getattr(regl.llm, f"prompts_{etape}").fournisseur)[0] for etape in ("image", "video", "son")):
            _prevol(ctx, connecteur_llm)  # Claude ou Bonsai : non installé = refus lisible, avant tout enfilage
        lancement = _ouvrir_lancement(ctx, projet_id, phase)
        _noter_erreur(ctx, projet_id, "bascule", None)  # la note de la génération précédente n'a plus de sens
        plans = [_resume_plan(p) for p in projet.plans]
        for indice, etape in enumerate(("image", "video", "son")):
            choix = getattr(regl.llm, f"prompts_{etape}")
            connecteur, voie = _voie_llm(choix.fournisseur)
            _enfiler(ctx, projet_id, phase, lancement, f"prompts.{etape}", connecteur=connecteur, voie=voie,
                     modele=choix.modele, indice=indice, libelle=f"Prompts {LIBELLES_ETAPE[etape]}",
                     donnees={"etape": etape, "reflexion": choix.reflexion, "plans": plans,
                              "prompt": gabarits.prompts(etape, plans, concept, casting, ReponsePrompts),
                              "schema": ReponsePrompts.model_json_schema()})
    elif phase == "images":
        if projet.etat_phases.get("prompts") is not EtatPhase.TERMINE:
            raise ErreurPhase("Valide d'abord les prompts (moteurs et prompts de chaque plan)")
        if not projet.plans or not all(p.prompt_image for p in projet.plans):
            raise ErreurPhase("Prompts image manquants : valide d'abord les prompts")
        if any((p.moteur_image or regl.moteurs_precoches.image) is MoteurImage.QWEN for p in projet.plans):
            _prevol(ctx, "maestro")
        if any((p.moteur_image or regl.moteurs_precoches.image) is MoteurImage.CODEX for p in projet.plans):
            _prevol(ctx, "codex")  # Codex passe par le même Maestro partagé
        for plan in projet.plans:
            _resolution_image(projet, plan, regl)  # refus avant tout enfilage ou changement d'état
        lancement = _ouvrir_lancement(ctx, projet_id, phase)
        for plan in projet.plans:
            _enfiler_image(ctx, projet, plan, lancement, regl)
    elif phase == "video":
        from .video import lancer_video  # import tardif : le module vidéo s'appuie sur celui-ci

        lancer_video(ctx, projet_id)
    else:
        raise ErreurPhase(f"Phase non lançable ici : {phase}")


def _resolution_image(projet: Projet, plan: Plan, regl: ReglagesDirector) -> tuple[int, int]:
    """Résolution des images d'un plan ; refus lisible si la définition de la recette n'est pas permise sur la carte détectée."""
    moteur_video = plan.moteur_video or (regl.moteurs_precoches.chante if plan.role is RolePlan.CHANTE else regl.moteurs_precoches.coupe)
    try:
        return resolution_rendu(moteur_video, projet.format, regl.rendu.definition(moteur_video))
    except ValueError as exc:  # recette enregistrée sur une autre carte
        raise ErreurPhase(str(exc)) from None


def _enfiler_image(ctx: Contexte, projet: Projet, plan: Plan, lancement: str, regl: ReglagesDirector) -> str:
    moteur = plan.moteur_image or regl.moteurs_precoches.image
    connecteur, voie = ("codex", Voie.CLOUD) if moteur is MoteurImage.CODEX else ("maestro", Voie.GPU)
    with ctx.base.transaction() as cx:
        fiches = {f.id: f for f in depot.lister_fiches(cx)}
    references: list[str] = []
    for fiche_id in plan.fiches:
        for image in fiches[fiche_id].images if fiche_id in fiches else []:
            try:
                references.append(str(medias.chemin_sur(ctx.dossier_medias, image.chemin)))  # Codex exige des chemins absolus
            except medias.CheminInterdit:
                continue
    largeur, hauteur = _resolution_image(projet, plan, regl)
    fichier = f"images/{plan.id}-{depot.nouvel_id('image')}.png"
    return _enfiler(ctx, projet.id, "images", lancement, "images.plan", connecteur=connecteur, voie=voie, modele=moteur.value,
                    indice=plan.indice, libelle=f"Image du plan {plan.indice + 1}",
                    donnees={"plan_id": plan.id, "indice": plan.indice, "prompt": plan.prompt_image, "format": projet.format.value,
                             "references": references, "largeur": largeur, "hauteur": hauteur, "fichier": fichier,
                             "destination": str(medias.chemin_sur(ctx.dossier_projet(projet.id), fichier))})


def valider_phase(ctx: Contexte, projet_id: str, phase: str) -> None:
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
    if projet.etat_phases.get(phase) is not EtatPhase.A_VALIDER:
        raise ErreurPhase(f"La phase « {phase} » n'attend pas de validation")
    if _jobs_en_attente(ctx, projet_id, phase):
        raise ErreurPhase("Des jobs de cette phase sont encore en file ou en cours : attends leur fin avant de valider")
    # Passage à « termine » en une seule transaction : deux validations simultanées ne passent pas toutes les deux.
    with ctx.base.transaction() as cx:
        if _projet(cx, projet_id).etat_phases.get(phase) is not EtatPhase.A_VALIDER:
            raise ErreurPhase(f"La phase « {phase} » vient d'être validée")
        depot.definir_etat_phase(cx, projet_id, phase, EtatPhase.TERMINE)
    ctx.publier({"type": "phase", "projet_id": projet_id, "phase": phase, "etat": EtatPhase.TERMINE.value})
    try:
        _enchainer(ctx, projet_id, phase)
    except ErreurPhase:  # préalables de la suite non remplis : la phase reste à valider
        _definir(ctx, projet_id, phase, EtatPhase.A_VALIDER)
        raise


def _jobs_en_attente(ctx: Contexte, projet_id: str, phase: str) -> bool:
    """Jobs non finaux de la phase : ceux du lancement courant, ou toute tâche d'écriture pour l'écriture."""
    if phase == "ecriture":
        return any(
            j.statut not in FINAUX and str(j.donnees.get("tache", "")).startswith("ecriture.")
            for j in ctx.file.lister_projet(projet_id)
        )
    lancement = _lancement_courant(ctx, projet_id, phase)
    return lancement is not None and any(j.statut not in FINAUX for j in ctx.file.lister_lancement(lancement))


def _enchainer(ctx: Contexte, projet_id: str, phase: str, *, depuis_rappel: bool = False) -> None:
    suivante = SUIVANTE.get(phase)
    if suivante in ("ecriture", "prompts", "images"):
        if not depuis_rappel:
            lancer_phase(ctx, projet_id, suivante)
            return
        try:
            lancer_phase(ctx, projet_id, suivante)
        except ErreurPhase as exc:  # dans un rappel, l'exception serait avalée : on la rend visible
            _noter_erreur(ctx, projet_id, suivante, str(exc))
    elif suivante == "video":
        _definir(ctx, projet_id, "video", EtatPhase.A_FAIRE)  # phase autonome, lancée depuis la timeline
        from . import timeline  # import tardif : la timeline s'appuie sur ce module

        timeline.assurer(ctx, projet_id)


def _terminer_phase(ctx: Contexte, projet_id: str, phase: str) -> None:
    with ctx.base.transaction() as cx:
        arret = getattr(reglages(cx, _projet(cx, projet_id)).arrets, phase)
    if arret:
        _definir(ctx, projet_id, phase, EtatPhase.A_VALIDER)
    else:
        _definir(ctx, projet_id, phase, EtatPhase.TERMINE)
        _enchainer(ctx, projet_id, phase, depuis_rappel=True)


# --- Fin des jobs ----------------------------------------------------------------------------------


def apres_job(ctx: Contexte, job: JobFile) -> None:
    """Rappel de fin de job (voir `modules.apres_job`) : applique le résultat, puis fait avancer la phase."""
    if not job.projet_id:
        return
    tache = str(job.donnees.get("tache", ""))
    if tache.startswith(("video.", "postprod.", "bruitage.")):
        from . import video  # import tardif : le module vidéo s'appuie sur celui-ci

        video.apres_job(ctx, job)
        return
    if tache.startswith("export."):
        from . import exports  # import tardif : le module d'export s'appuie sur celui-ci

        exports.apres_job(ctx, job)
        return
    phase = str(job.phase)
    lancee = phase in ("analyse", "prompts", "images")
    if lancee and job.donnees.get("lancement") != _lancement_courant(ctx, job.projet_id, phase):
        return  # job d'un lancement remplacé (encore en cours à la relance) : sa sortie ne doit rien écraser
    if phase == "prompts" and _deja_livree(ctx, job, tache):
        return  # un autre job de la tâche (reprise Claude, Bonsai relancé) a livré : une fin tardive n'écrase rien
    if job.statut is StatutJob.ECHEC and job.connecteur == "bonsai" and tache.startswith("prompts."):
        _basculer_sur_claude(ctx, job)  # enfilé AVANT le constat de fin : la phase attend la reprise
    if job.statut is StatutJob.TERMINE:
        refus: str | None = None
        application = APPLICATIONS.get(tache)
        try:
            if application is not None:
                application(ctx, job)
        except ValidationError as exc:
            refus = f"Sortie invalide ({tache}) : {exc.error_count()} erreur(s)"
        except sqlite3.IntegrityError as exc:  # sortie incohérente avec la base : échec visible, jamais de phase bloquée
            refus = f"Sortie incohérente ({tache}) : {exc}"
        except medias.CheminInterdit:  # image hors du projet : le plan reste sans image, à refaire
            refus = f"Sortie invalide ({tache}) : fichier hors du projet"
        except ErreurPhase as exc:  # ex. découpage livré après un changement de carte : jamais d'erreur muette
            refus = str(exc)
        if job.donnees.get("lancement") == _lancement_courant(ctx, job.projet_id, phase):
            with ctx.base.transaction() as cx:
                rejetes = _rejetes(cx, job.projet_id, phase)
                _regler_rejetes(cx, job.projet_id, phase, (rejetes | {job.id}) if refus else (rejetes - {job.id}))
            if refus and job.connecteur == "bonsai" and tache.startswith("prompts.") and _basculer_sur_claude(ctx, job, refus):
                pass  # sortie refusée = échec de Bonsai : la phase attend la reprise
            elif refus and phase != "images":
                _noter_erreur(ctx, job.projet_id, phase, refus)
                _definir(ctx, job.projet_id, phase, EtatPhase.ECHEC)
        elif refus:  # job d'un ancien lancement : sans effet sur l'état du lancement courant
            return
    elif tache.startswith("ecriture."):
        _noter_erreur(ctx, job.projet_id, "ecriture", job.erreur or "job annulé")
    if job.phase in ("analyse", "prompts", "images"):
        _verifier_fin(ctx, job)


def _deja_livree(ctx: Contexte, job: JobFile, tache: str) -> bool:
    """Un AUTRE job de la même tâche, dans le même lancement, a déjà livré une sortie acceptée. Ses prompts ont pu être
    corrigés à la main, voire validés : la fin tardive de ce job (relance manuelle) ne doit ni les écraser, ni basculer,
    ni changer l'état de la phase."""
    with ctx.base.transaction() as cx:
        rejetes = _rejetes(cx, str(job.projet_id), str(job.phase))
    return any(
        autre.id != job.id and autre.donnees.get("tache") == tache and autre.statut is StatutJob.TERMINE and autre.id not in rejetes
        for autre in ctx.file.lister_lancement(str(job.donnees.get("lancement")))
    )


def _basculer_sur_claude(ctx: Contexte, job: JobFile, motif: str | None = None) -> bool:
    """D10 : Bonsai a échoué deux fois (JSON invalide, moteur en panne) ou rendu une sortie refusée : le même travail
    part sur Claude, signalé. Une seule reprise à la fois par job remplacé. Rend False si Claude n'est pas installé : rien
    n'est enfilé, l'échec reste visible (note « bascule ») et la phase se clôt en échec."""
    projet_id = str(job.projet_id)
    if any(
        autre.donnees.get("remplace") == job.id and autre.statut not in (StatutJob.ECHEC, StatutJob.ANNULE)
        for autre in ctx.file.lister_lancement(job.donnees["lancement"])
    ):
        return True
    try:
        ctx.prevol("claude")
    except MoteurNonInstalle:
        _noter_erreur(ctx, projet_id, "bascule", f"{job.libelle} : Bonsai a échoué et Claude n'est pas installé (installe-le depuis l'écran Moteurs) : pas de reprise")
        return False
    ctx.file.ajouter(
        voie=Voie.CLOUD, connecteur="claude", modele="sonnet", projet_id=projet_id, phase=job.phase, ordre=job.ordre,
        regime=job.regime, libelle=f"{job.libelle} — repris par Claude",
        donnees={**job.donnees, "remplace": job.id, "reflexion": False},
    )
    phrase = f"{job.libelle} : Bonsai a échoué ({job.erreur or motif or 'sans message'}), repris par Claude"
    with ctx.base.transaction() as cx:
        existante = str((depot.lire_donnees_module(cx, projet_id).get("erreurs") or {}).get("bascule") or "")
    if phrase not in existante.split(" ; "):
        _noter_erreur(ctx, projet_id, "bascule", f"{existante} ; {phrase}" if existante else phrase)
    return True


def _verifier_fin(ctx: Contexte, job: JobFile) -> None:
    phase = str(job.phase)
    projet_id = str(job.projet_id)
    lancement = job.donnees.get("lancement")
    if lancement is None or lancement != _lancement_courant(ctx, projet_id, phase):
        return
    jobs = ctx.file.lister_lancement(lancement)
    if any(j.statut not in FINAUX for j in jobs):
        return
    with ctx.base.transaction() as cx:
        rejetes = _rejetes(cx, projet_id, phase)
        projet = _projet(cx, projet_id)
    plans = projet.plans
    # Une fin tardive (job relancé à la main depuis la file) ne rouvre jamais une phase close.
    close = projet.etat_phases.get(phase) in (EtatPhase.TERMINE, EtatPhase.A_FAIRE)
    if phase == "images":  # une image ratée reste à refaire, quel que soit l'arrêt
        derniers = {j.donnees.get("plan_id"): j for j in jobs}  # une image refaite remplace le job précédent du plan
        ratees = {j.donnees.get("plan_id") for j in derniers.values() if j.statut is not StatutJob.TERMINE or j.id in rejetes}
        manquants = [p for p in plans if not p.image_depart or p.id in ratees]
        if manquants:
            _noter_erreur(ctx, projet_id, phase, f"{len(manquants)} image(s) à refaire")
            if not close:
                _definir(ctx, projet_id, phase, EtatPhase.A_VALIDER)
            return
        _noter_erreur(ctx, projet_id, phase, None)
        if not close:
            _terminer_phase(ctx, projet_id, phase)
        return
    if close:
        return
    remplaces = {str(j.donnees["remplace"]) for j in jobs if j.donnees.get("remplace")}
    # une tâche est réussie dès qu'un de ses jobs du lancement (Bonsai relancé ou reprise Claude) est terminé et accepté
    reussies = {j.donnees.get("tache") for j in jobs if j.statut is StatutJob.TERMINE and j.id not in rejetes}
    rates = [j for j in jobs if j.donnees.get("tache") not in reussies and j.id not in remplaces
             and (j.statut is not StatutJob.TERMINE or j.id in rejetes)]
    if rates:
        echoue = next((j for j in rates if j.id not in rejetes), None)
        if echoue is not None:  # sinon la note posée au refus de la sortie reste en place
            _noter_erreur(ctx, projet_id, phase, echoue.erreur or "job annulé")
        _definir(ctx, projet_id, phase, EtatPhase.ECHEC)
        return
    _noter_erreur(ctx, projet_id, phase, None)
    _terminer_phase(ctx, projet_id, phase)


def _appliquer_analyse(ctx: Contexte, job: JobFile) -> None:
    resultat = job.resultat or {}
    if "brut" in resultat:  # moteur réel : l'analyse de Maestro est convertie (calage des paroles compris)
        analyse = analyse_depuis_maestro(dict(resultat["brut"] or {}), str(resultat.get("paroles") or ""))
    else:
        analyse = Analyse.model_validate(resultat)
    with ctx.base.transaction() as cx:
        depot.modifier_donnees_module(cx, str(job.projet_id), "analyse", analyse.model_dump(mode="json"))


def _appliquer_concepts(ctx: Contexte, job: JobFile) -> None:
    reponse = ReponseConcepts.model_validate(job.resultat)
    with ctx.base.transaction() as cx:
        ecriture = _ecriture(cx, str(job.projet_id))
        ecriture["concepts"] = [c.model_dump(mode="json") for c in reponse.concepts]
        ecriture["concept_retenu"] = None
        depot.modifier_donnees_module(cx, str(job.projet_id), "ecriture", ecriture)


def _appliquer_chat(ctx: Contexte, job: JobFile) -> None:
    reponse = ReponseChat.model_validate(job.resultat)
    with ctx.base.transaction() as cx:
        ecriture = _ecriture(cx, str(job.projet_id))
        ecriture["chat"] = [*ecriture.get("chat", []), MessageChat(auteur="opus", texte=reponse.reponse).model_dump(mode="json")]
        depot.modifier_donnees_module(cx, str(job.projet_id), "ecriture", ecriture)


def _appliquer_decoupage(ctx: Contexte, job: JobFile) -> None:
    reponse = ReponseDecoupage.model_validate(job.resultat)
    projet_id = str(job.projet_id)
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        ouverte = projet.etat_phases.get("ecriture") in (EtatPhase.EN_COURS, EtatPhase.A_VALIDER, EtatPhase.ECHEC)
        if ouverte:
            regl = reglages(cx, projet)
            try:
                plans = normaliser(reponse.plans, float(projet.duree_chanson_s or 0), projet.format, regl.moteurs_precoches,
                                   f"{projet_id}-plan", casting=projet.casting, definitions=regl.rendu.definitions())
            except ValueError as exc:  # recette enregistrée sur une autre carte
                raise ErreurPhase(str(exc)) from None
            depot.remplacer_plans(cx, projet_id, plans)
    if not ouverte:  # écriture déjà validée : les plans et les prompts en place ne sont pas écrasés
        _noter_erreur(ctx, projet_id, "ecriture", "Découpage arrivé après la validation de l'écriture : ignoré")
        return
    _terminer_phase(ctx, projet_id, "ecriture")


def _appliquer_prompts(ctx: Contexte, job: JobFile) -> None:
    reponse = ReponsePrompts.model_validate(job.resultat)
    champ = f"prompt_{job.donnees.get('etape')}"
    with ctx.base.transaction() as cx:
        ids = {p.id for p in _projet(cx, str(job.projet_id)).plans}
        for prompt in reponse.prompts:
            if prompt.plan_id in ids:
                depot.maj_plan(cx, prompt.plan_id, **{champ: prompt.prompt})
        manquants = sorted(ids - {p.plan_id for p in reponse.prompts})
    if manquants:  # traité comme une sortie incohérente : échec visible de la phase
        raise sqlite3.IntegrityError(f"prompts manquants pour : {', '.join(manquants)}")


def _appliquer_image(ctx: Contexte, job: JobFile) -> None:
    fichier = str((job.resultat or {}).get("fichier", ""))
    projet_id = str(job.projet_id)
    medias.chemin_sur(ctx.dossier_projet(projet_id), fichier)  # refuse un chemin qui sortirait du projet
    # Une image refaite remplace le job précédent du plan : une sortie plus ancienne qui finit après coup ne l'écrase pas.
    memes = [j for j in ctx.file.lister_lancement(job.donnees.get("lancement")) if j.donnees.get("plan_id") == job.donnees.get("plan_id")]
    if memes and memes[-1].id != job.id:
        return
    with ctx.base.transaction() as cx:
        if job.donnees.get("plan_id") in {p.id for p in _projet(cx, projet_id).plans}:
            depot.maj_plan(cx, str(job.donnees["plan_id"]), image_depart=fichier)


APPLICATIONS = {
    "analyse": _appliquer_analyse,
    "ecriture.concepts": _appliquer_concepts,
    "ecriture.chat": _appliquer_chat,
    "ecriture.decoupage": _appliquer_decoupage,
    "prompts.image": _appliquer_prompts,
    "prompts.video": _appliquer_prompts,
    "prompts.son": _appliquer_prompts,
    "images.plan": _appliquer_image,
}


# --- Écriture : brief, concepts, chat, découpage --------------------------------------------------


def _concept_retenu(ecriture: dict[str, Any]) -> dict[str, Any] | None:
    indice = ecriture.get("concept_retenu")
    concepts = ecriture.get("concepts") or []
    return concepts[indice] if isinstance(indice, int) and 0 <= indice < len(concepts) else None


def _exiger_ecriture_ouverte(projet: Projet) -> None:
    if projet.etat_phases.get("ecriture") not in (EtatPhase.EN_COURS, EtatPhase.A_VALIDER, EtatPhase.ECHEC):
        raise ErreurPhase("L'écriture n'est pas ouverte : termine d'abord l'analyse")


def _enfiler_ecriture(ctx: Contexte, projet: Projet, tache: str, libelle: str, donnees: dict[str, Any]) -> None:
    with ctx.base.transaction() as cx:
        regl = reglages(cx, projet)
    connecteur, voie = _voie_llm(regl.llm.ecriture.fournisseur)
    _prevol(ctx, connecteur)  # Claude (ou Bonsai si la recette le choisit) doit être installé : refus avant tout enfilage
    lancement = _lancement_courant(ctx, projet.id, "ecriture") or _ouvrir_lancement(ctx, projet.id, "ecriture")
    _enfiler(ctx, projet.id, "ecriture", lancement, tache, connecteur=connecteur, voie=voie,
             modele=regl.llm.ecriture.modele, libelle=libelle, donnees={"effort": regl.llm.ecriture.effort.value, **donnees})
    _noter_erreur(ctx, projet.id, "ecriture", None)
    if projet.etat_phases.get("ecriture") is EtatPhase.ECHEC:  # un nouvel essai rouvre l'écriture
        _definir(ctx, projet.id, "ecriture", EtatPhase.EN_COURS)


def definir_brief(ctx: Contexte, projet_id: str, brief: Brief) -> None:
    with ctx.base.transaction() as cx:
        _projet(cx, projet_id)
        ecriture = _ecriture(cx, projet_id)
        ecriture["brief"] = brief.model_dump(mode="json")
        depot.modifier_donnees_module(cx, projet_id, "ecriture", ecriture)


def proposer_concepts(ctx: Contexte, projet_id: str) -> None:
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        donnees = depot.lire_donnees_module(cx, projet_id)
        nombre = reglages(cx, projet).llm.ecriture.nombre_concepts
    _exiger_ecriture_ouverte(projet)
    brief = (donnees.get("ecriture") or {}).get("brief") or {}
    _enfiler_ecriture(ctx, projet, "ecriture.concepts", "Écriture · concepts",
                      {"brief": brief, "nombre": nombre, "prompt": gabarits.concepts(brief, donnees.get("analyse"), nombre, ReponseConcepts),
                       "schema": ReponseConcepts.model_json_schema()})


def retenir_concept(ctx: Contexte, projet_id: str, indice: int) -> None:
    with ctx.base.transaction() as cx:
        _projet(cx, projet_id)
        ecriture = _ecriture(cx, projet_id)
        if not 0 <= indice < len(ecriture.get("concepts") or []):
            raise ErreurPhase("Ce concept n'existe pas")
        ecriture["concept_retenu"] = indice
        depot.modifier_donnees_module(cx, projet_id, "ecriture", ecriture)


def envoyer_message(ctx: Contexte, projet_id: str, texte: str) -> None:
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        _exiger_ecriture_ouverte(projet)
        ecriture = _ecriture(cx, projet_id)
        historique = list(ecriture.get("chat") or [])
        ecriture["chat"] = [*historique, MessageChat(auteur="utilisateur", texte=texte).model_dump(mode="json")]
        depot.modifier_donnees_module(cx, projet_id, "ecriture", ecriture)
    _enfiler_ecriture(ctx, projet, "ecriture.chat", "Écriture · réponse d'Opus",
                      {"message": texte, "prompt": gabarits.chat(historique, _concept_retenu(ecriture), texte, ReponseChat),
                       "schema": ReponseChat.model_json_schema()})


def ecrire_decoupage(ctx: Contexte, projet_id: str) -> None:
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        donnees = depot.lire_donnees_module(cx, projet_id)
        regl = reglages(cx, projet)
        casting = _casting_pour_llm(cx, projet)
    _exiger_ecriture_ouverte(projet)
    ecriture = dict(donnees.get("ecriture") or {})
    concept = _concept_retenu(ecriture)
    if concept is None:
        raise ErreurPhase("Retiens d'abord un concept")
    analyse = donnees.get("analyse")
    if analyse is None:
        raise ErreurPhase("Analyse manquante")
    bornes = {}
    for role, moteur in (("chante", regl.moteurs_precoches.chante), ("coupe", regl.moteurs_precoches.coupe)):
        definition = regl.rendu.definition(moteur)
        try:
            g = grille(moteur, projet.format, definition)
        except ValueError as exc:  # recette enregistrée sur une autre carte
            raise ErreurPhase(str(exc)) from None
        bornes[role] = f"{g.duree_min_s:.1f} à {g.duree_max_s:.1f} s ({moteur.value}, {definition.value})"
    _enfiler_ecriture(ctx, projet, "ecriture.decoupage", "Écriture · découpage",
                      {"analyse": analyse, "concept": concept, "casting": casting, "duree_s": projet.duree_chanson_s,
                       "prompt": gabarits.decoupage(projet, analyse, concept, ecriture.get("chat") or [], bornes, casting, ReponseDecoupage),
                       "schema": ReponseDecoupage.model_json_schema()})


def modifier_lignes(ctx: Contexte, projet_id: str, lignes: list[LigneParoles]) -> None:
    """Relecture du calage des paroles (arrêt après l'analyse)."""
    with ctx.base.transaction() as cx:
        _projet(cx, projet_id)
        brut = depot.lire_donnees_module(cx, projet_id).get("analyse")
        if brut is None:
            raise ErreurPhase("Aucune analyse à corriger")
        analyse = Analyse.model_validate(brut).model_copy(update={"lignes": lignes})
        depot.modifier_donnees_module(cx, projet_id, "analyse", analyse.model_dump(mode="json"))


# --- Prompts, moteurs et images ------------------------------------------------------------------------


def modifier_plan(ctx: Contexte, projet_id: str, plan_id: str, modification: PlanModification) -> Plan:
    """Prompts et moteurs d'un plan. Un moteur vidéo incompatible avec la durée est refusé ; sinon le
    nombre d'images est recalé sur sa grille, sans décaler les plans suivants (la timeline absorbe)."""
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        plan = next((p for p in projet.plans if p.id == plan_id), None)
        if plan is None:
            raise KeyError(plan_id)
        champs: dict[str, Any] = {
            cle: valeur
            for cle, valeur in modification.model_dump(exclude_none=True).items()
            if cle in ("moteur_image", "prompt_image", "prompt_video", "prompt_son")
        }
        if modification.moteur_video is not None and modification.moteur_video is not plan.moteur_video:
            definition = reglages(cx, projet).rendu.definition(modification.moteur_video)
            verdict = compatibilite(plan, modification.moteur_video, projet.format, definition)
            if not verdict.compatible:
                raise ErreurPhase(f"Moteur incompatible : {verdict.note}")
            champs.update(moteur_video=modification.moteur_video, images=verdict.images,
                          fps=grille(modification.moteur_video, projet.format, definition).fps)
        if modification.fiches is not None:
            fiches = list(dict.fromkeys(modification.fiches))
            hors_casting = [f for f in fiches if f not in projet.casting]
            if hors_casting:
                raise ErreurPhase(f"Fiches hors du casting du projet : {', '.join(hors_casting)} (ajoute-les d'abord au casting)")
            depot.remplacer_fiches_plan(cx, plan_id, fiches)
        if champs:
            depot.maj_plan(cx, plan_id, **champs)
        plan_relu = next(p for p in _projet(cx, projet_id).plans if p.id == plan_id)
        a_timeline = depot.lire_timeline(cx, projet_id) is not None
    if "moteur_video" in champs and a_timeline:
        from . import timeline  # import tardif : le module de la timeline s'appuie sur celui-ci

        timeline.ajuster_au_plan(ctx, projet_id, plan_relu)
    return plan_relu


def modifier_casting(ctx: Contexte, projet_id: str, modification: CastingModification) -> Projet:
    """Casting après la création. Une fiche retirée quitte les plans ; sur demande, les fiches nouvelles
    entrent dans tous les plans existants (à retirer ensuite, plan par plan, là où elles ne sont pas à l'image)."""
    casting = list(dict.fromkeys(modification.casting))
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        connues = {f.id for f in depot.lister_fiches(cx)}
        inconnues = [f for f in casting if f not in connues]
        if inconnues:
            raise ErreurPhase(f"Fiches introuvables : {', '.join(inconnues)}")
        nouvelles = [f for f in casting if f not in projet.casting]
        depot.remplacer_casting(cx, projet_id, casting)
        if modification.ajouter_aux_plans and nouvelles:
            for plan in projet.plans:
                depot.remplacer_fiches_plan(cx, plan.id, list(dict.fromkeys([*(f for f in plan.fiches if f in casting), *nouvelles])))
        return _projet(cx, projet_id)


def refaire_image(ctx: Contexte, projet_id: str, plan_id: str) -> None:
    with ctx.base.transaction() as cx:
        projet = _projet(cx, projet_id)
        regl = reglages(cx, projet)
    plan = next((p for p in projet.plans if p.id == plan_id), None)
    if plan is None:
        raise KeyError(plan_id)
    if projet.etat_phases.get("images") not in (EtatPhase.EN_COURS, EtatPhase.A_VALIDER, EtatPhase.ECHEC):
        raise ErreurPhase("Les images ne sont pas en cours de validation")
    lancement = _lancement_courant(ctx, projet_id, "images")
    if lancement is None:
        raise ErreurPhase("Aucun lancement d'images")
    moteur = plan.moteur_image or regl.moteurs_precoches.image
    _resolution_image(projet, plan, regl)  # refus avant toute modification d'état
    _prevol(ctx, "maestro" if moteur is MoteurImage.QWEN else "codex")  # avant toute modification d'état
    anciens = [
        j.id for j in ctx.file.lister_lancement(lancement)
        if j.statut is StatutJob.EN_FILE and j.donnees.get("plan_id") == plan_id
    ]
    _definir(ctx, projet_id, "images", EtatPhase.EN_COURS)
    _noter_erreur(ctx, projet_id, "images", None)
    _enfiler_image(ctx, projet, plan, lancement, regl)
    # Annulés APRÈS l'enfilage : le rappel d'annulation voit le nouveau job non final et ne conclut pas la phase.
    for ancien in anciens:
        ctx.file.annuler(ancien)


# --- État exposé à l'interface ----------------------------------------------------------------------


def etat_director(ctx: Contexte, projet_id: str) -> EtatDirector:
    with ctx.base.transaction() as cx:
        _projet(cx, projet_id)
        donnees = depot.lire_donnees_module(cx, projet_id)
    ecriture = donnees.get("ecriture") or {}
    en_attente = sorted({
        str(job.donnees.get("tache")) for job in ctx.file.lister_projet(projet_id)
        if job.statut in (StatutJob.EN_FILE, StatutJob.EN_COURS)
    })
    return EtatDirector(
        analyse=donnees.get("analyse"), brief=ecriture.get("brief") or {}, concepts=ecriture.get("concepts") or [],
        concept_retenu=ecriture.get("concept_retenu"), chat=ecriture.get("chat") or [], en_attente=en_attente,
        erreurs=donnees.get("erreurs") or {},
    )
