"""Phase 5 du Director : vidéo et post-production en autonomie (spec §6.1, D7, D20, D23).

- Chaque rendu est une nouvelle PRISE du plan ; chaque étape de post-production (FlashVSR ×2, puis DLSS5, selon
  la recette) une nouvelle SORTIE de cette prise, qui devient la sortie active une fois terminée.
- Ordre : tous les rendus H3, puis les LTX (groupés par modèle), puis tout FlashVSR, puis tout DLSS5 : la
  post-production est en phase « postprod », indexée FlashVSR puis DLSS5, et chaque job attend le précédent de
  sa chaîne (`donnees["apres"]`) ; l'arbitre libère ou arrête Maestro avant DLSS5.
- Échec : la file retente une fois ; au second échec la prise est en échec (clip rouge avec sa cause), ses
  étapes suivantes sont annulées par la file et le reste continue. La phase se termine quand tous les jobs de
  son lancement, entièrement enfilé, sont finaux, échecs compris.
- Les jobs portent des chemins ABSOLUS bornés au dossier du projet (`destination`, `source`, `audio`) et le
  chemin relatif attendu en retour (`fichier`) : c'est le contrat que suivront les connecteurs réels (plan 6).
"""

from __future__ import annotations

import logging
import random
import shutil
import subprocess
import threading
from datetime import datetime
from typing import Any

from ...contrat.modeles import (
    EstimationVideo,
    EtapePostProd,
    EtatPhase,
    FormatImage,
    MoteurVideo,
    Plan,
    Projet,
    Regime,
    RolePlan,
    StatutJob,
    StatutTraitement,
    Voie,
)
from ...core import depot, medias
from ...core.contexte import Contexte
from ...core.file import JobFile
from ...core.grilles import DEFINITION_PAR_DEFAUT, DIMENSIONS, Definition, Grille, dimensions, grille, resolution_rendu, saute_flashvsr
from ...outils import ffmpeg
from . import phases, timeline
from .manifeste import ordre_job
from .reglages import ReglagesDirector

OCTETS_PAR_SECONDE = {"brut": 1_000_000, "flashvsr": 5_000_000, "dlss5": 5_000_000}  # à recaler sur les rendus réels (plan 6)
MARGE_DISQUE = 1.5
RANG_MOTEUR = {MoteurVideo.H3: 0, MoteurVideo.LTX23: 1, MoteurVideo.LTX25: 2}
LIBELLES_MOTEUR = {MoteurVideo.H3: "H3", MoteurVideo.LTX23: "LTX-2.3", MoteurVideo.LTX25: "LTX-2.5"}
LIBELLES_ETAPE = {EtapePostProd.FLASHVSR: "FlashVSR ×2", EtapePostProd.DLSS5: "DLSS5"}
MOTEURS_ETAPE = {EtapePostProd.FLASHVSR: ("maestro", "flashvsr2"), EtapePostProd.DLSS5: ("dlss5", "dlss5")}
RANG_ORDRE_ETAPE = {EtapePostProd.FLASHVSR: 1, EtapePostProd.DLSS5: 2}


def _absolu(ctx: Contexte, projet_id: str, relatif: str) -> str:
    return str(medias.chemin_sur(ctx.dossier_projet(projet_id), relatif))


def octets_estimes(plans: list[Plan], regl: ReglagesDirector, format_image: FormatImage = FormatImage.PAYSAGE) -> int:
    """Estimation par plan, proportionnelle aux pixels : les débits de référence valent pour un rendu en 960×544 (brut),
    sa sortie FlashVSR ×2 et un DLSS5 en 1920×1088. FlashVSR ne compte que pour les plans qui ne le sautent pas."""
    largeur_ref, hauteur_ref = DIMENSIONS[DEFINITION_PAR_DEFAUT]
    total = 0.0
    for plan in plans:
        definition = regl.rendu.definition(plan.moteur_video) if plan.moteur_video else DEFINITION_PAR_DEFAUT
        largeur, hauteur = dimensions(format_image, definition) if plan.moteur_video else (largeur_ref, hauteur_ref)  # sans contrôle : une estimation ne refuse pas
        echelle = largeur * hauteur / (largeur_ref * hauteur_ref)
        par_seconde = OCTETS_PAR_SECONDE["brut"] * echelle
        flashvsr = regl.postprod.flashvsr.actif and not (plan.moteur_video and saute_flashvsr(plan.moteur_video, format_image, definition))
        if flashvsr:
            par_seconde += OCTETS_PAR_SECONDE["flashvsr"] * echelle
        if regl.postprod.dlss5.actif:  # DLSS5 part de la sortie FlashVSR (×2 par côté) ou du brut
            par_seconde += OCTETS_PAR_SECONDE["dlss5"] * echelle * (1 if flashvsr else 0.25)
        total += plan.duree_s * par_seconde
    return int(total * MARGE_DISQUE)


def estimer(ctx: Contexte, projet_id: str) -> EstimationVideo:
    """Place disque nécessaire à la phase 5 (spec §6.1 et §7 : alerte avant la phase)."""
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        regl = phases.reglages(cx, projet)
    plans = [plan for plan in projet.plans if plan.moteur_video]
    dossier = ctx.dossier_projet(projet_id)
    dossier.mkdir(parents=True, exist_ok=True)
    necessaires = octets_estimes(plans, regl, projet.format)
    libres = shutil.disk_usage(dossier).free
    return EstimationVideo(plans=len(plans), octets_necessaires=necessaires, octets_libres=libres, suffisant=libres >= necessaires)


def segment_audio(ctx: Contexte, projet: Projet, plan: Plan) -> str | None:
    """Segment de la chanson couvert par un plan chanté (méthode « rerun » de Maestro, spec §5), en WAV ; déjà
    découpé, il est réutilisé."""
    if plan.role is not RolePlan.CHANTE or not projet.chanson:
        return None
    dossier = ctx.dossier_projet(projet.id)
    cible = medias.chemin_sur(dossier, f"audio/{plan.id}-{round(plan.debut_s * 1000)}-{plan.images}-{plan.fps}.wav")
    if not cible.is_file():
        provisoire = cible.with_name(f"{cible.stem}.{random.getrandbits(32):08x}.partiel.wav")
        try:
            ffmpeg.decouper_audio(medias.chemin_sur(dossier, projet.chanson), plan.debut_s, plan.duree_s, provisoire)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            provisoire.unlink(missing_ok=True)
            raise phases.ErreurPhase(f"Découpe du son du plan {plan.indice + 1} impossible : {exc}") from None
        try:
            provisoire.replace(cible)
        except OSError as exc:
            provisoire.unlink(missing_ok=True)
            if not cible.is_file():
                raise phases.ErreurPhase(f"Découpe du son du plan {plan.indice + 1} impossible : {exc}") from None
    return str(cible)


def enfiler_postprod(
    ctx: Contexte,
    projet_id: str,
    plan: Plan,
    prise_id: str,
    etape: EtapePostProd,
    reglages_etape: dict[str, Any],
    *,
    source: str,
    apres: str | None,
    regime: Regime,
    lancement: str | None,
    ordre: int,
    action_id: str | None = None,
) -> tuple[str, str]:
    """Nouvelle sortie de la prise et son job ; renvoie (job, fichier relatif produit)."""
    with ctx.base.transaction() as cx:
        sortie = depot.creer_sortie(cx, prise_id, etape, reglages_etape)
    fichier = f"prises/{prise_id}/{sortie.ordre}-{etape.value}.mp4"
    connecteur, modele = MOTEURS_ETAPE[etape]
    job = ctx.file.ajouter(
        voie=Voie.GPU, connecteur=connecteur, modele=modele, projet_id=projet_id,
        phase="postprod" if regime is Regime.PHASES else None, ordre=ordre, regime=regime,
        libelle=f"Plan {plan.indice + 1} — {LIBELLES_ETAPE[etape]}",
        donnees={
            "module": phases.MODULE, "tache": f"postprod.{etape.value}", "lancement": lancement, "plan_id": plan.id,
            "prise_id": prise_id, "sortie_id": sortie.id, "indice": plan.indice, "action_id": action_id,
            "apres": [apres] if apres else [], "reglages": reglages_etape, "source": _absolu(ctx, projet_id, source),
            "fichier": fichier, "destination": _absolu(ctx, projet_id, fichier),
        },
    )
    return job, fichier


def enfiler_rendu(
    ctx: Contexte,
    projet: Projet,
    plan: Plan,
    regl: ReglagesDirector,
    *,
    regime: Regime,
    lancements: dict[str, str],
    ordres: tuple[int, int, int],
    activer: bool,
    moteur: MoteurVideo | None = None,
    graine: int | None = None,
    action_id: str | None = None,
) -> tuple[str, list[str]]:
    """Nouvelle prise du plan : rendu, puis FlashVSR et DLSS5 selon la recette, chaînés par la file.

    `activer` : la prise devient active tout de suite (phase 5) ; sinon (prise refaite) elle remplace la
    prise active une fois rendue. Renvoie (identifiant de la prise, jobs enfilés)."""
    moteur = moteur or plan.moteur_video
    if moteur is None or not plan.image_depart:
        raise phases.ErreurPhase(f"Plan {plan.indice + 1} : moteur vidéo ou image de départ manquant")
    audio = segment_audio(ctx, projet, plan)
    graine = random.randrange(2**31) if graine is None else graine
    definition = regl.rendu.definition(moteur)
    largeur, hauteur = resolution_rendu(moteur, projet.format, definition)
    with ctx.base.transaction() as cx:
        prise = depot.creer_prise(
            cx, plan.id, moteur, graine,
            {"images": plan.images, "fps": plan.fps, "format": projet.format.value, "action_id": action_id,
             "definition": definition.value, "largeur": largeur, "hauteur": hauteur},
        )
        if activer:
            depot.maj_plan(cx, plan.id, prise_active_id=prise.id)
    brut = f"prises/{prise.id}/brut.mp4"
    jobs = [
        ctx.file.ajouter(
            voie=Voie.GPU, connecteur="maestro", modele=moteur.value, projet_id=projet.id,
            phase="video" if regime is Regime.PHASES else None, ordre=ordres[0], regime=regime,
            libelle=f"Plan {plan.indice + 1} — rendu {LIBELLES_MOTEUR[moteur]}",
            donnees={
                "module": phases.MODULE, "tache": "video.plan", "lancement": lancements.get("video"), "plan_id": plan.id,
                "prise_id": prise.id, "indice": plan.indice, "action_id": action_id, "activer": activer,
                "moteur": moteur.value, "prompt": plan.prompt_video, "image_depart": _absolu(ctx, projet.id, plan.image_depart),
                "images": plan.images, "fps": plan.fps, "format": projet.format.value, "largeur": largeur, "hauteur": hauteur,
                "definition": definition.value, "audio": audio, "graine": graine, "fichier": brut, "destination": _absolu(ctx, projet.id, brut),
            },
        )
    ]
    etapes: list[tuple[EtapePostProd, dict[str, Any]]] = []
    if regl.postprod.flashvsr.actif and not saute_flashvsr(moteur, projet.format, definition):
        etapes.append((EtapePostProd.FLASHVSR, {"facteur": regl.postprod.flashvsr.facteur}))
    if regl.postprod.dlss5.actif:
        etapes.append((EtapePostProd.DLSS5, regl.postprod.dlss5.model_dump(mode="json", exclude={"actif"})))
    source = brut
    for etape, reglages_etape in etapes:
        job, source = enfiler_postprod(
            ctx, projet.id, plan, prise.id, etape, reglages_etape, source=source, apres=jobs[-1], regime=regime,
            lancement=lancements.get("postprod"), ordre=ordres[RANG_ORDRE_ETAPE[etape]], action_id=action_id,
        )
        jobs.append(job)
    return prise.id, jobs


def enfiler_bruitage(
    ctx: Contexte, projet: Projet, plan: Plan, video: str, *, prompt: str, ordre: int, action_id: str | None,
    prise_id: str | None = None, apres: str | None = None,
) -> str:
    """Bruitage MMAudio guidé par la vidéo du plan (spec D19) ; le son se posera sous le clip du plan."""
    with ctx.base.transaction() as cx:
        en_place = depot.lire_timeline(cx, projet.id)
    clip = next((c for c in en_place.clips if c.plan_id == plan.id), None) if en_place is not None else None
    position, entree, sortie = (clip.position_s, clip.entree_s, clip.sortie_s) if clip else (plan.debut_s, 0.0, plan.duree_s)
    fichier = f"sons/bruitage-{action_id or depot.nouvel_id('son')}.wav"
    return ctx.file.ajouter(
        voie=Voie.GPU, connecteur="maestro", modele="mmaudio", projet_id=projet.id, phase=None, ordre=ordre,
        regime=Regime.CARTE, libelle=f"Plan {plan.indice + 1} — bruitage",
        donnees={
            "module": phases.MODULE, "tache": "bruitage.plan", "plan_id": plan.id, "indice": plan.indice,
            "action_id": action_id, "prise_id": prise_id, "apres": [apres] if apres else [],
            "prompt": prompt, "video": _absolu(ctx, projet.id, video), "duree_s": plan.duree_s,
            "position_s": position, "entree_s": entree, "sortie_s": sortie,
            "fichier": fichier, "destination": _absolu(ctx, projet.id, fichier),
        },
    )


# Un seul lancement de la phase à la fois : le contrôle « déjà lancée » et le passage à EN_COURS (dans
# `_ouvrir_lancement`) sont séparés par les découpes ffmpeg ; sans verrou, un double clic enfilait deux lots.
_VERROU_LANCEMENT = threading.Lock()


def lancer_video(ctx: Contexte, projet_id: str) -> None:
    """Phase 5 : un rendu par plan puis sa post-production, dans l'ordre du §6.1, sans arrêt."""
    with _VERROU_LANCEMENT:
        _lancer_video(ctx, projet_id)


def message_hors_grille(plans, format_, regl) -> str | None:
    """Refus clair si la durée d'un plan dépasse la grille de son moteur à la définition de la recette, sinon None."""
    hors = []
    for plan in plans:
        definition = regl.rendu.definition(plan.moteur_video)
        try:  # recette enregistrée sur une autre carte : la définition peut ne plus être permise
            limite = grille(plan.moteur_video, format_, definition)
        except ValueError as exc:
            return str(exc)
        if not limite.est_valide(plan.images):
            hors.append((plan, definition, limite))
    if not hors:
        return None

    def virgule(secondes: float) -> str:
        return f"{secondes:.1f}".replace(".", ",")

    def detail(plan: Plan, definition: Definition, limite: Grille) -> str:
        if plan.images < limite.images_min:
            borne = f"minimum {virgule(limite.duree_min_s)} s"
        elif plan.images > limite.images_max:
            borne = f"maximum {virgule(limite.duree_max_s)} s"
        else:
            borne = "nombre d'images hors du pas de la grille"
        return f"plan {plan.indice + 1} ({virgule(plan.duree_s)} s, {LIBELLES_MOTEUR[plan.moteur_video]} : {borne} en {definition.value})"

    details = " ; ".join(detail(*entree) for entree in hors[:3])
    h3_trop_long = any(
        plan.moteur_video is MoteurVideo.H3 and definition is Definition.P544 and plan.images > limite.images_max
        for plan, definition, limite in hors
    )
    remede = "passe H3 en 480p dans la recette ou change le moteur du plan" if h3_trop_long else "redécoupe le plan ou change son moteur"
    return f"Durée hors grille du moteur : {details} ; {remede}"


def _lancer_video(ctx: Contexte, projet_id: str) -> None:
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        regl = phases.reglages(cx, projet)
    if projet.etat_phases.get("images") is not EtatPhase.TERMINE:
        raise phases.ErreurPhase("Valide d'abord les images de départ")
    if projet.etat_phases.get("video", EtatPhase.A_FAIRE) is not EtatPhase.A_FAIRE:
        raise phases.ErreurPhase("La vidéo est déjà lancée : refais un plan depuis la timeline")
    incomplets = [str(p.indice + 1) for p in projet.plans if not p.moteur_video or not p.image_depart]
    if not projet.plans or incomplets:
        raise phases.ErreurPhase(f"Plans sans moteur ou sans image de départ : {', '.join(incomplets) or 'aucun plan'}")
    for moteur in {p.moteur_video for p in projet.plans}:
        try:  # recette enregistrée sur une autre carte : la définition H3 peut ne plus être permise
            resolution_rendu(moteur, projet.format, regl.rendu.definition(moteur))
        except ValueError as exc:
            raise phases.ErreurPhase(str(exc)) from None
    estimation = estimer(ctx, projet_id)
    if not estimation.suffisant:
        raise phases.ErreurPhase(
            f"Disque insuffisant : {estimation.octets_necessaires / 1e9:.1f} Go estimés, {estimation.octets_libres / 1e9:.1f} Go libres"
        )
    hors_grille = message_hors_grille(projet.plans, projet.format, regl)
    if hors_grille:
        raise phases.ErreurPhase(hors_grille)
    phases._prevol(ctx, "maestro")
    if regl.postprod.dlss5.actif:
        phases._prevol(ctx, "dlss5")
    for plan in projet.plans:
        segment_audio(ctx, projet, plan)  # toutes les découpes d'abord : un échec ne laisse aucun job en file
    timeline.assurer(ctx, projet_id)
    lancements = {phase: phases._ouvrir_lancement(ctx, projet_id, phase) for phase in ("video", "postprod")}
    ordonnes = sorted(projet.plans, key=lambda p: (RANG_MOTEUR[p.moteur_video], p.indice))
    total = len(ordonnes)
    for rang, plan in enumerate(ordonnes):
        enfiler_rendu(
            ctx, projet, plan, regl, regime=Regime.PHASES, lancements=lancements, activer=True,
            ordres=(ordre_job("video", rang), ordre_job("postprod", rang), ordre_job("postprod", total + rang)),
        )
    # Lancement entièrement enfilé : sa fin peut désormais être constatée (un job fini avant ne la décide pas).
    with ctx.base.transaction() as cx:
        complets = dict(depot.lire_donnees_module(cx, projet_id).get("lancements_complets") or {})
        complets.update(lancements)
        depot.modifier_donnees_module(cx, projet_id, "lancements_complets", complets)
    for phase in lancements:
        _verifier_fin(ctx, projet_id, phase)


# --- Fins de jobs ------------------------------------------------------------------------------------


def apres_job(ctx: Contexte, job: JobFile) -> None:
    """Fin d'un rendu, d'une étape de post-production ou d'un bruitage (aiguillé par `phases.apres_job`)."""
    tache = str(job.donnees.get("tache", ""))
    try:
        if tache == "video.plan":
            _fin_rendu(ctx, job)
        elif tache.startswith("postprod."):
            _fin_postprod(ctx, job)
        elif tache == "bruitage.plan":
            _fin_bruitage(ctx, job)
    finally:
        if job.phase in ("video", "postprod") and job.projet_id:
            _verifier_fin(ctx, str(job.projet_id), str(job.phase))


def _fichier_produit(ctx: Contexte, job: JobFile) -> str | None:
    """Fichier relatif rendu par le job, s'il reste dans le dossier du projet ; None sinon."""
    fichier = str((job.resultat or {}).get("fichier", ""))
    try:
        medias.chemin_sur(ctx.dossier_projet(str(job.projet_id)), fichier)
    except medias.CheminInterdit:
        return None
    return fichier


def _cause(job: JobFile, defaut: str) -> str:
    return "Sortie invalide : fichier hors du projet" if job.statut is StatutJob.TERMINE else (job.erreur or defaut)


def _fin_rendu(ctx: Contexte, job: JobFile) -> None:
    prise_id = str(job.donnees.get("prise_id"))
    fichier = _fichier_produit(ctx, job) if job.statut is StatutJob.TERMINE else None
    cause = _cause(job, "rendu annulé")
    with ctx.base.transaction() as cx:
        if not depot.existe(cx, "prises", prise_id):
            return  # prise nettoyée, ou plans remplacés entre-temps
        if fichier is not None:
            depot.maj_prise(cx, prise_id, statut=StatutTraitement.TERMINE, fichier_brut=fichier, erreur=None)
            if not job.donnees.get("activer"):  # prise refaite : elle remplace la prise active une fois rendue
                depot.maj_plan(cx, str(job.donnees.get("plan_id")), prise_active_id=prise_id)
            return
        depot.maj_prise(cx, prise_id, statut=StatutTraitement.ECHEC, erreur=cause)
    if not job.donnees.get("activer"):  # hors transaction : le rendu refait a échoué, l'ancienne prise reste active
        indice = int(job.donnees.get("indice", 0))
        phases._noter_erreur(
            ctx, str(job.projet_id), "actions",
            f"Plan {indice + 1} : le rendu refait a échoué ({cause}) ; l'ancienne prise reste active",
        )


def _fin_postprod(ctx: Contexte, job: JobFile) -> None:
    sortie_id = str(job.donnees.get("sortie_id"))
    fichier = _fichier_produit(ctx, job) if job.statut is StatutJob.TERMINE else None
    with ctx.base.transaction() as cx:
        if not depot.existe(cx, "sorties", sortie_id):
            return
        if fichier is None:
            depot.maj_sortie(cx, sortie_id, statut=StatutTraitement.ECHEC, erreur=_cause(job, "étape annulée"))
            return
        depot.maj_sortie(cx, sortie_id, statut=StatutTraitement.TERMINE, fichier=fichier, erreur=None)
        depot.maj_prise(cx, str(job.donnees.get("prise_id")), sortie_active_id=sortie_id)


def _fin_bruitage(ctx: Contexte, job: JobFile) -> None:
    projet_id = str(job.projet_id)
    fichier = _fichier_produit(ctx, job) if job.statut is StatutJob.TERMINE else None
    if fichier is None:
        phases._noter_erreur(ctx, projet_id, "bruitage", _cause(job, "bruitage annulé"))
        return
    donnees = job.donnees
    try:
        with ctx.base.transaction() as cx:
            timeline.placer_son(
                cx, projet_id, fichier, float(donnees["position_s"]), float(donnees["entree_s"]), float(donnees["sortie_s"])
            )
    except phases.ErreurPhase as exc:
        phases._noter_erreur(ctx, projet_id, "bruitage", str(exc))
        return
    phases._noter_erreur(ctx, projet_id, "bruitage", None)


def _verifier_fin(ctx: Contexte, projet_id: str, phase: str) -> None:
    """La phase se termine quand tous les jobs de son lancement, entièrement enfilé, sont finaux."""
    with ctx.base.transaction() as cx:
        donnees = depot.lire_donnees_module(cx, projet_id)
        etat = phases._projet(cx, projet_id).etat_phases.get(phase)
    lancement = (donnees.get("lancements") or {}).get(phase)
    complet = (donnees.get("lancements_complets") or {}).get(phase)
    if lancement is None or complet != lancement or etat is not EtatPhase.EN_COURS:
        return
    jobs = ctx.file.lister_lancement(lancement)
    if any(job.statut not in phases.FINAUX for job in jobs):
        return
    rates = sum(1 for job in jobs if job.statut is not StatutJob.TERMINE)
    if not rates:
        message = None
    elif phase == "postprod":
        message = f"{rates} étape(s) de post-production en échec ou annulées : le plan garde sa dernière sortie disponible"
    else:
        message = f"{rates} job(s) en échec ou annulés : voir les clips rouges de la timeline"
    phases._noter_erreur(ctx, projet_id, phase, message)
    phases._definir(ctx, projet_id, phase, EtatPhase.TERMINE)
    _rapport_si_fini(ctx, projet_id)


# --- Rapport de fin de phase vidéo (D23) ----------------------------------------------------------


def _duree_s(job: JobFile) -> float:
    try:
        return max(0.0, (datetime.fromisoformat(str(job.termine_le)) - datetime.fromisoformat(str(job.demarre_le))).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _heures(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def rediger_rapport(projet: Projet, jobs_video: list[JobFile], jobs_postprod: list[JobFile]) -> tuple[str, str]:
    """(résumé d'une ligne pour la notification, rapport Markdown) d'un lancement de la phase vidéo."""
    indices = {plan.id: plan.indice for plan in projet.plans}
    lignes = [
        f"# Rapport de la phase vidéo — {projet.titre}",
        "",
        "| Plan | Moteur | Rendu | Durée | Post-production | Cause |",
        "|---|---|---|---|---|---|",
    ]
    rendus = rates = 0
    total = 0.0
    for job in sorted(jobs_video, key=lambda j: indices.get(str(j.donnees.get("plan_id")), 0)):
        suite = [j for j in jobs_postprod if j.donnees.get("prise_id") == job.donnees.get("prise_id")]
        fait = job.statut is StatutJob.TERMINE
        rendus += fait
        rates += not fait
        duree = _duree_s(job) + sum(_duree_s(j) for j in suite)
        total += duree
        post = "fait" if suite and all(j.statut is StatutJob.TERMINE for j in suite) else ("—" if not suite else "échec")
        cause = job.erreur if not fait else next((j.erreur for j in suite if j.statut is not StatutJob.TERMINE and j.erreur), None)
        cause_courte = " ".join((cause or "—").split())[:200].replace("|", "/")  # une seule ligne de tableau, même pour une trace
        moteur = LIBELLES_MOTEUR.get(MoteurVideo(job.modele), str(job.modele)) if job.modele in {m.value for m in MoteurVideo} else str(job.modele)
        lignes.append(
            f"| {indices.get(str(job.donnees.get('plan_id')), 0) + 1} | {moteur} | {'fait' if fait else 'échec'} | {_heures(duree)} "
            f"| {post} | {cause_courte} |"
        )
    resume = f"« {projet.titre} » : {rendus}/{rendus + rates} plans rendus{f', {rates} en échec' if rates else ''} en {_heures(total)}"
    return resume, "\n".join([*lignes, "", resume, ""])


def _rapport_si_fini(ctx: Contexte, projet_id: str) -> None:
    """Une fois par lancement : quand vidéo ET post-production sont terminées, rapport écrit et notification."""
    with ctx.base.transaction() as cx:
        projet = phases._projet(cx, projet_id)
        donnees = depot.lire_donnees_module(cx, projet_id)
        lancements = donnees.get("lancements") or {}
        lancement = lancements.get("video")
        if (
            lancement is None
            or donnees.get("rapport_video") == lancement
            or projet.etat_phases.get("video") is not EtatPhase.TERMINE
            or projet.etat_phases.get("postprod") is not EtatPhase.TERMINE
        ):
            return
        depot.modifier_donnees_module(cx, projet_id, "rapport_video", lancement)  # pris dans la même transaction : une seule fois
    jobs_video = ctx.file.lister_lancement(lancement)
    jobs_postprod = ctx.file.lister_lancement(lancements["postprod"]) if lancements.get("postprod") else []
    resume, texte = rediger_rapport(projet, jobs_video, jobs_postprod)
    try:
        fichier = medias.chemin_sur(ctx.dossier_projet(projet_id), f"rapports/video-{datetime.now():%Y%m%d-%H%M%S}.md")
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(texte, encoding="utf-8")
    except OSError:
        logging.getLogger("mymaestro").exception("rapport de la phase vidéo non écrit")
        resume += " (rapport non écrit)"
    # Dans un fil démon : PowerShell (1 à 30 s) ne doit pas garder le verrou de fin de la file.
    threading.Thread(target=ctx.notifier, args=("MyMaestro — vidéo terminée", resume), daemon=True).start()
