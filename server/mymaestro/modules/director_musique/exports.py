"""Export du clip (spec §6.1 phase 7, D25) : projection de la timeline en segments, montage ffmpeg à la taille de
sortie (connecteur « export », hors GPU), puis interpolation 60 fps par DLSS5 si demandée (job suivant).

L'état d'un export se lit dans ses jobs : le module ne garde qu'une liste d'identifiants. La phase « export » passe
en cours AVANT l'enfilage, pour qu'une fin rapide ne soit jamais écrasée.
"""

from __future__ import annotations

from typing import Any

from ...contrat.modeles import EtatPhase, ExportEntree, ExportProjet, Regime, StatutJob, StatutTraitement, Voie
from ...core import depot, medias
from ...core.contexte import Contexte
from ...core.file import JobFile
from ...core.grilles import RESOLUTIONS_SORTIE
from . import phases, timeline
from .manifeste import ordre_job

FPS_INTERPOLATION = 60


def lancer(ctx: Contexte, projet_id: str, entree: ExportEntree) -> ExportProjet:
    # Verrou des prises tenu jusqu'à l'enfilage : un nettoyage ne peut pas supprimer une prise entre la lecture des
    # segments et l'apparition des jobs qui la citent (`donnees["prises"]`).
    with timeline._VERROU_PRISES:
        return _lancer(ctx, projet_id, entree)


def _lancer(ctx: Contexte, projet_id: str, entree: ExportEntree) -> ExportProjet:
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        regl = phases.reglages(cx, projet)
        en_place = depot.lire_timeline(cx, projet_id)
    if en_place is None:
        raise phases.ErreurPhase("Pas encore de timeline à exporter")
    dossier = ctx.dossier_projet(projet_id)
    segments_bruts = timeline.segments(ctx, projet_id) or []
    segments = [
        {
            "debut_s": segment.debut_s, "fin_s": segment.fin_s, "source_debut_s": segment.source_debut_s,
            "fichier": str(medias.chemin_sur(dossier, segment.fichier)) if segment.fichier else None,
        }
        for segment in segments_bruts
    ]
    sons: list[dict[str, Any]] = []
    for clip in en_place.clips:
        if not (clip.piste.startswith("A") and clip.fichier_audio):
            continue
        try:
            chemin = medias.chemin_sur(dossier, clip.fichier_audio)
        except medias.CheminInterdit:
            continue
        if chemin.is_file():
            sons.append({
                "fichier": str(chemin), "position_s": clip.position_s, "entree_s": clip.entree_s, "sortie_s": clip.sortie_s,
                "volume": clip.volume, "fondu_entree_s": clip.fondu_entree_s, "fondu_sortie_s": clip.fondu_sortie_s,
            })
    interpolation = regl.export.interpolation_60fps if entree.interpolation_60fps is None else entree.interpolation_60fps
    if interpolation:
        phases._prevol(ctx, "dlss5")  # l'interpolation 60 fps passe par DLSS5 : refus avant toute écriture
    export_id = depot.nouvel_id("export")
    largeur, hauteur = RESOLUTIONS_SORTIE[projet.format]
    fichier = f"exports/{export_id}.mp4"
    actives = (timeline.prise_active(projet, segment.plan_id) for segment in segments_bruts if segment.plan_id)
    prises = sorted({prise.id for prise in actives if prise is not None})
    commun = {"module": phases.MODULE, "export_id": export_id, "interpolation": interpolation, "prises": prises}
    with ctx.base.transaction() as cx:  # repère posé AVANT l'enfilage : un job rapide peut finir avant l'enregistrement
        depot.modifier_donnees_module(cx, projet_id, "export_courant", export_id)
    phases._definir(ctx, projet_id, "export", EtatPhase.EN_COURS)
    phases._noter_erreur(ctx, projet_id, "export", None)
    jobs = {
        "montage": ctx.file.ajouter(
            voie=Voie.CLOUD, connecteur="export", modele="ffmpeg", projet_id=projet_id, phase="export",
            ordre=ordre_job("export", 0), regime=Regime.PHASES, libelle=f"Export — montage {largeur}×{hauteur}",
            donnees={
                **commun, "tache": "export.montage", "segments": segments, "audio": sons, "largeur": largeur,
                "hauteur": hauteur, "fps": en_place.fps_maitre, "fichier": fichier,
                "destination": str(medias.chemin_sur(dossier, fichier)),
            },
        )
    }
    if interpolation:
        fichier_60 = f"exports/{export_id}-60fps.mp4"
        jobs["interpolation"] = ctx.file.ajouter(
            voie=Voie.GPU, connecteur="dlss5", modele="dlss5", projet_id=projet_id, phase="export",
            ordre=ordre_job("export", 1), regime=Regime.PHASES, libelle="Export — interpolation 60 fps (DLSSG)",
            donnees={
                **commun, "tache": "export.interpolation", "apres": [jobs["montage"]], "fps": FPS_INTERPOLATION,
                "source": str(medias.chemin_sur(dossier, fichier)), "fichier": fichier_60,
                "destination": str(medias.chemin_sur(dossier, fichier_60)),
            },
        )
    enregistre = {
        "id": export_id, "cree_le": depot.horodatage(), "interpolation_60fps": interpolation,
        "duree_s": en_place.duree_chanson_s, "jobs": jobs,
    }
    with ctx.base.transaction() as cx:
        deja = list(depot.lire_donnees_module(cx, projet_id).get("exports") or [])
        depot.modifier_donnees_module(cx, projet_id, "exports", [*deja, enregistre])
    return _public(ctx, enregistre)


def _fichier(job: JobFile | None) -> str | None:
    if job is None or job.statut is not StatutJob.TERMINE:
        return None
    return str((job.resultat or {}).get("fichier") or "") or None


def _public(ctx: Contexte, enregistre: dict[str, Any]) -> ExportProjet:
    jobs = {cle: ctx.file.lire(job_id) for cle, job_id in enregistre["jobs"].items()}
    presents = [job for job in jobs.values() if job is not None]
    rates = [job for job in presents if job.statut in (StatutJob.ECHEC, StatutJob.ANNULE)]
    if rates or len(presents) < len(jobs):
        statut = StatutTraitement.ECHEC
    elif all(job.statut is StatutJob.TERMINE for job in presents):
        statut = StatutTraitement.TERMINE
    elif any(job.statut is StatutJob.EN_COURS for job in presents):
        statut = StatutTraitement.EN_COURS
    else:
        statut = StatutTraitement.EN_FILE
    if rates:
        erreur: str | None = rates[0].erreur or "export annulé"
    else:
        erreur = None if len(presents) == len(jobs) else "job introuvable"
    return ExportProjet(
        id=enregistre["id"], cree_le=enregistre["cree_le"], statut=statut,
        interpolation_60fps=bool(enregistre["interpolation_60fps"]), duree_s=float(enregistre["duree_s"]),
        fichier=_fichier(jobs.get("montage")), fichier_60fps=_fichier(jobs.get("interpolation")), erreur=erreur,
    )


def lister(ctx: Contexte, projet_id: str) -> list[ExportProjet]:
    with ctx.base.transaction() as cx:
        phases._projet(cx, projet_id)
        enregistres = list(depot.lire_donnees_module(cx, projet_id).get("exports") or [])
    return [_public(ctx, enregistre) for enregistre in reversed(enregistres)]


def apres_job(ctx: Contexte, job: JobFile) -> None:
    """Fin d'un job d'export : la phase « export » suit le dernier export lancé."""
    projet_id = str(job.projet_id)
    with ctx.base.transaction() as cx:
        courant = depot.lire_donnees_module(cx, projet_id).get("export_courant")
    if job.donnees.get("export_id") != courant:
        return  # fin d'un export ancien : elle ne touche pas la phase du dernier export lancé
    dernier = job.donnees.get("tache") == "export.interpolation" or not job.donnees.get("interpolation")
    if job.statut is StatutJob.TERMINE:
        if dernier:
            phases._noter_erreur(ctx, projet_id, "export", None)
            phases._definir(ctx, projet_id, "export", EtatPhase.TERMINE)
        return
    if job.donnees.get("tache") == "export.interpolation" and job.statut is StatutJob.ANNULE:
        # Annulée parce que le montage a échoué : la note du montage (la vraie cause) reste en place.
        prerequis = job.donnees.get("apres") or []
        montage = ctx.file.lire(prerequis[0]) if prerequis else None
        if montage is not None and montage.statut in (StatutJob.ECHEC, StatutJob.ANNULE):
            return
    phases._noter_erreur(ctx, projet_id, "export", job.erreur or "export annulé")
    phases._definir(ctx, projet_id, "export", EtatPhase.ECHEC)
