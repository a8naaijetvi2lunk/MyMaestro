import pytest

from mymaestro import modules
from mymaestro.connectors.simule import registre_simule
from mymaestro.contrat.modeles import (
    ActionEntree,
    ClipModification,
    EtapePostProd,
    MoteurVideo,
    Regime,
    StatutJob,
    StatutTraitement,
    TypeAction,
    Voie,
)
from mymaestro.core import amorce, depot, empreintes
from mymaestro.core.contexte import Contexte
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.core.ordonnanceur import Ordonnanceur
from mymaestro.fixtures import demo
from mymaestro.modules.director_musique import actions, timeline, video
from mymaestro.outils import ffmpeg

P = demo.PROJET_DEMO


def _ffmpeg_disponible() -> bool:
    try:
        ffmpeg.trouver("ffmpeg")
        return True
    except FileNotFoundError:
        return False


@pytest.fixture
def monde(tmp_path):
    base = Base(":memory:")
    amorce.amorcer_si_vide(base, tmp_path)  # la chanson de la démo existe : un plan chanté en découpe son segment
    file = File(base)
    ordonnanceur = Ordonnanceur(file, registre_simule(empreintes.DEFAUTS, repondeur=modules.repondeur_simule(tmp_path)))
    contexte = Contexte(base=base, file=file, dossier_projets=tmp_path, publier=ordonnanceur.bus.publier)
    file.rappels.append(lambda job: modules.apres_job(contexte, job))
    yield contexte, ordonnanceur
    base.fermer()


def _projet(contexte):
    with contexte.base.transaction() as cx:
        return depot.lire_projet(cx, P)


def _entree(type_, **champs):
    return ActionEntree(type=type_, **champs)


def test_une_action_vise_un_plan_rendu(monde):
    contexte, _ = monde
    with pytest.raises(actions.ActionInvalide):
        actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE))
    with pytest.raises(actions.ActionInvalide, match="Aucun rendu"):
        actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-04"))  # rendu en cours
    with pytest.raises(actions.ActionInvalide, match="55 mots"):
        actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-00", reglages={"prompt": "mot " * 56}))
    with pytest.raises(actions.ActionInvalide, match="DLSS5"):
        actions.programmer(contexte, P, _entree(TypeAction.PASSE_DLSS5, plan_id="plan-00", reglages={"intensite": 9}))
    with pytest.raises(actions.ActionInvalide, match="incompatible"):
        actions.programmer(contexte, P, _entree(TypeAction.CHANGER_MOTEUR, plan_id="plan-00", reglages={"moteur": "minimax_h3"}))
    with pytest.raises(actions.ActionInvalide, match="position"):
        actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-01", reglages={"a_la_position": True}))
    with pytest.raises(actions.ActionInvalide, match="clip de plan"):
        actions.programmer(
            contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-01", clip_id="clip-chanson", reglages={"a_la_position": True})
        )
    with pytest.raises(actions.ActionInvalide, match="graine"):
        actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-01", reglages={"graine": "7"}))
    with pytest.raises(KeyError):
        actions.programmer(contexte, "inconnu", _entree(TypeAction.REFAIRE, plan_id="plan-01"))


def test_ordre_a_la_suite_du_regime_a_la_carte(monde):
    contexte, _ = monde
    contexte.file.ajouter(voie=Voie.GPU, connecteur="maestro", regime=Regime.CARTE, ordre=actions.ORDRE_CARTE + 40)
    action = actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-00"))
    [job] = actions.lancer(contexte, P)
    assert contexte.file.lire(job).ordre == actions.ORDRE_CARTE + 41
    assert actions.lister(contexte, P) == []
    with pytest.raises(KeyError):
        actions.retirer(contexte, P, action.id)  # déjà lancée


def test_action_retiree_avant_lancement(monde):
    contexte, _ = monde
    action = actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-00"))
    actions.retirer(contexte, P, action.id)
    assert actions.lister(contexte, P) == [] and actions.lancer(contexte, P) == []


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_refaire_cree_une_prise_qui_remplace_l_active_une_fois_rendue(monde):
    contexte, ordonnanceur = monde
    actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-03", reglages={"graine": 7}))
    jobs = actions.lancer(contexte, P)
    assert [contexte.file.lire(j).donnees["tache"] for j in jobs] == ["video.plan", "postprod.flashvsr", "postprod.dlss5"]
    projet = _projet(contexte)
    nouvelle = max((p for p in projet.prises if p.plan_id == "plan-03"), key=lambda p: p.numero)
    assert nouvelle.numero == 2 and nouvelle.graine == 7
    assert next(p for p in projet.plans if p.id == "plan-03").prise_active_id == "plan-03-p1"  # l'ancienne reste active
    ordonnanceur.vider()
    projet = _projet(contexte)
    plan = next(p for p in projet.plans if p.id == "plan-03")
    active = next(p for p in projet.prises if p.id == plan.prise_active_id)
    assert active.id == nouvelle.id and active.statut is StatutTraitement.TERMINE
    assert active.sortie_active_id == active.sorties[-1].id


def test_changer_de_moteur_recale_le_plan_et_rogne_ses_clips(monde):
    contexte, _ = monde
    actions.programmer(contexte, P, _entree(TypeAction.CHANGER_MOTEUR, plan_id="plan-03", reglages={"moteur": MoteurVideo.LTX23.value}))
    actions.lancer(contexte, P)
    plan = next(p for p in _projet(contexte).plans if p.id == "plan-03")
    assert plan.moteur_video is MoteurVideo.LTX23 and plan.fps == 25 and plan.images == 233
    clip = next(c for c in timeline.lire(contexte, P).clips if c.plan_id == "plan-03")
    assert clip.sortie_s == pytest.approx(plan.duree_s)


def test_passe_dlss5_ajoute_une_sortie_active(monde, tmp_path):
    contexte, ordonnanceur = monde
    source = tmp_path / P / "prises" / "plan-02-p1" / "1-flashvsr.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"flashvsr")
    actions.programmer(contexte, P, _entree(TypeAction.PASSE_DLSS5, plan_id="plan-02", reglages={"intensite": 0.8}))
    [job] = actions.lancer(contexte, P)
    donnees = contexte.file.lire(job).donnees
    assert donnees["source"] == str(source.resolve())
    assert (donnees["reglages"]["intensite"], donnees["reglages"]["style"]) == (0.8, "Cinematic")
    ordonnanceur.vider()
    prise = next(p for p in _projet(contexte).prises if p.id == "plan-02-p1")
    assert [s.etape for s in prise.sorties] == [EtapePostProd.FLASHVSR, EtapePostProd.DLSS5]
    assert prise.sortie_active_id == prise.sorties[-1].id and prise.sorties[-1].reglages["intensite"] == 0.8
    assert (tmp_path / P / prise.sorties[-1].fichier).read_bytes() == b"flashvsr"


def test_bruitage_pose_un_son_sous_le_plan(monde, tmp_path):
    contexte, ordonnanceur = monde
    actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-02", reglages={"prompt": "flaque, gouttes"}))
    [job] = actions.lancer(contexte, P)
    assert contexte.file.lire(job).donnees["prompt"] == "flaque, gouttes"
    ordonnanceur.vider()
    posee = timeline.lire(contexte, P)
    son = next(c for c in posee.clips if (c.fichier_audio or "").startswith("sons/bruitage-"))
    clip = next(c for c in posee.clips if c.plan_id == "plan-02")
    assert (son.piste, son.position_s, son.sortie_s) == ("A1", clip.position_s, clip.sortie_s)
    assert (tmp_path / P / son.fichier_audio).is_file()


def test_a_refaire_a_cette_position_reancre_le_plan(monde):
    contexte, _ = monde
    timeline.modifier_clip(contexte, P, "clip-plan-01", ClipModification(verrou_chanson=False, sortie_s=9.0))
    timeline.modifier_clip(contexte, P, "clip-plan-01", ClipModification(position_s=5.5))
    actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, clip_id="clip-plan-01", reglages={"a_la_position": True}))
    actions.lancer(contexte, P)
    plan = next(p for p in _projet(contexte).plans if p.id == "plan-01")
    assert plan.debut_s == 5.5
    assert next(c for c in timeline.lire(contexte, P).clips if c.id == "clip-plan-01").verrou_chanson is True


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_bruitage_et_dlss5_apres_un_refaire_visent_la_nouvelle_prise(monde):
    contexte, ordonnanceur = monde
    actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-02"))
    actions.programmer(contexte, P, _entree(TypeAction.PASSE_DLSS5, plan_id="plan-02", reglages={"intensite": 0.5}))
    actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-02"))
    jobs = [contexte.file.lire(j) for j in actions.lancer(contexte, P)]
    par_tache = {j.donnees["tache"]: j for j in jobs}
    prise = par_tache["video.plan"].donnees["prise_id"]
    bruitage, passe = par_tache["bruitage.plan"], [j for j in jobs if j.donnees["tache"] == "postprod.dlss5"][-1]
    assert prise != "plan-02-p1" and bruitage.donnees["prise_id"] == prise
    assert prise in bruitage.donnees["video"] and bruitage.donnees["apres"] == [jobs[2].id]
    assert passe.donnees["prise_id"] == prise and passe.donnees["source"].endswith("-flashvsr.mp4")
    assert passe.donnees["apres"] == [par_tache["postprod.flashvsr"].id] and passe.donnees["reglages"]["intensite"] == 0.5
    ordonnanceur.vider()
    assert not any(j.statut.value in ("en_file", "en_cours") for j in contexte.file.lister_projet(P))


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_actions_d_un_second_lot_visent_la_prise_refaite_encore_en_file(monde):
    contexte, ordonnanceur = monde
    actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-02"))
    jobs1 = [contexte.file.lire(j) for j in actions.lancer(contexte, P)]
    prise = next(j for j in jobs1 if j.donnees["tache"] == "video.plan").donnees["prise_id"]
    fvsr = next(j for j in jobs1 if j.donnees["tache"] == "postprod.flashvsr")
    actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-02"))
    actions.programmer(contexte, P, _entree(TypeAction.PASSE_DLSS5, plan_id="plan-02", reglages={"intensite": 0.5}))
    jobs2 = [contexte.file.lire(j) for j in actions.lancer(contexte, P)]
    bruitage = next(j for j in jobs2 if j.donnees["tache"] == "bruitage.plan")
    passe = next(j for j in jobs2 if j.donnees["tache"] == "postprod.dlss5")
    assert bruitage.donnees["prise_id"] == prise and bruitage.donnees["apres"] == [jobs1[-1].id]
    assert passe.donnees["prise_id"] == prise and passe.donnees["apres"] == [fvsr.id]
    ordonnanceur.vider()
    projet = _projet(contexte)
    active = next(p for p in projet.prises if p.id == next(p for p in projet.plans if p.id == "plan-02").prise_active_id)
    assert active.id == prise
    assert next(s for s in active.sorties if s.id == active.sortie_active_id).reglages["intensite"] == 0.5


def test_dlss5_attend_le_flashvsr_encore_en_file(monde):
    contexte, _ = monde
    projet = _projet(contexte)
    plan = next(p for p in projet.plans if p.id == "plan-03")
    job_fvsr, fichier = video.enfiler_postprod(
        contexte, P, plan, "plan-03-p1", EtapePostProd.FLASHVSR, {"facteur": 2}, source="prises/plan-03-p1/brut.mp4",
        apres=None, regime=Regime.PHASES, lancement=None, ordre=1,
    )
    actions.programmer(contexte, P, _entree(TypeAction.PASSE_DLSS5, plan_id="plan-03"))
    [job] = actions.lancer(contexte, P)
    donnees = contexte.file.lire(job).donnees
    assert donnees["apres"] == [job_fvsr] and donnees["source"].replace("\\", "/").endswith(fichier)


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_second_lot_ne_s_accroche_pas_a_un_job_annule(monde):
    """Un DLSS5 de la prise refaite annulé à la main : le bruitage et la passe du lot suivant s'accrochent à la
    dernière étape encore vivante (le FlashVSR), jamais au job annulé, sinon la file les annulerait à leur tour."""
    contexte, ordonnanceur = monde
    actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-02"))
    jobs1 = [contexte.file.lire(j) for j in actions.lancer(contexte, P)]
    fvsr = next(j for j in jobs1 if j.donnees["tache"] == "postprod.flashvsr")
    dlss5 = next(j for j in jobs1 if j.donnees["tache"] == "postprod.dlss5")
    assert contexte.file.annuler(dlss5.id)
    actions.programmer(contexte, P, _entree(TypeAction.BRUITAGE, plan_id="plan-02"))
    actions.programmer(contexte, P, _entree(TypeAction.PASSE_DLSS5, plan_id="plan-02"))
    jobs2 = [contexte.file.lire(j) for j in actions.lancer(contexte, P)]
    bruitage = next(j for j in jobs2 if j.donnees["tache"] == "bruitage.plan")
    passe = next(j for j in jobs2 if j.donnees["tache"] == "postprod.dlss5")
    assert bruitage.donnees["apres"] == [fvsr.id] and passe.donnees["apres"] == [fvsr.id]
    ordonnanceur.vider()
    assert contexte.file.lire(bruitage.id).statut is StatutJob.TERMINE
    assert contexte.file.lire(passe.id).statut is StatutJob.TERMINE


def test_lancer_la_file_refuse_sans_marge_memoire_et_garde_les_actions(monde):
    from mymaestro.contrat.modeles import StatutAction
    from mymaestro.outils.systeme import MemoireInsuffisante

    contexte, _ = monde
    appels: list[str] = []

    def refuser(connecteur: str) -> None:
        appels.append(connecteur)
        raise MemoireInsuffisante("Mémoire engagée insuffisante : quitte Docker Desktop")

    contexte.prevol = refuser
    actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-03"))
    avant = len(contexte.file.lister_projet(P))
    with pytest.raises(actions.phases.ErreurPhase, match="Docker"):
        actions.lancer(contexte, P)
    assert appels == ["maestro"]
    assert [a.statut for a in actions.lister(contexte, P)] == [StatutAction.PROGRAMMEE]
    assert len(contexte.file.lister_projet(P)) == avant


def test_action_retiree_pendant_le_pre_vol_ne_part_pas(monde):
    contexte, _ = monde
    action = actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-03"))
    retraits: list[str] = []

    def prevol(connecteur):  # retrait pendant le pré-vol (une seule fois : il y a un pré-vol Maestro puis un pré-vol DLSS5)
        if not retraits:
            retraits.append(connecteur)
            actions.retirer(contexte, P, action.id)

    contexte.prevol = prevol
    avant = len(contexte.file.lister_projet(P))
    assert actions.lancer(contexte, P) == []
    assert len(contexte.file.lister_projet(P)) == avant


def test_refaire_un_plan_ltx_en_1080p_n_enfile_pas_flashvsr(monde):
    contexte, _ = monde
    with contexte.base.transaction() as cx:
        recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": {"ltx23": "1080p"}}}))
    actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-00", reglages={"graine": 3}))
    jobs = [contexte.file.lire(j) for j in actions.lancer(contexte, P)]
    assert [j.donnees["tache"] for j in jobs] == ["video.plan", "postprod.dlss5"]
    assert (jobs[0].donnees["largeur"], jobs[0].donnees["hauteur"]) == (1920, 1088)
    assert jobs[1].donnees["source"] == jobs[0].donnees["destination"]


def test_refaire_un_plan_hors_grille_de_la_recette_est_refuse(monde):
    contexte, _ = monde
    with contexte.base.transaction() as cx:
        projet = depot.lire_projet(cx, P)
        plan = next(p for p in projet.plans if p.id == "plan-01")
        assert plan.moteur_video is MoteurVideo.H3
        depot.maj_plan(cx, plan.id, images=277)
        recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": {"h3": "544p"}}}))
    with pytest.raises(actions.ActionInvalide, match="hors grille"):
        actions.programmer(contexte, P, _entree(TypeAction.REFAIRE, plan_id="plan-01"))


@pytest.mark.parametrize("type_", [TypeAction.REFAIRE, TypeAction.CHANGER_MOTEUR])
def test_lancer_refaire_avec_dlss5_actif_sans_dlss5_installe_refuse(monde, monkeypatch, type_):
    """Hors mode démo, DLSS5 actif dans la recette mais absent : la file refuse, aucun job, l'action reste programmée."""
    from mymaestro.connectors.registre import prevol_pour
    from mymaestro.connectors.simule import ConnecteurSimule
    from mymaestro.contrat.modeles import StatutAction
    from mymaestro.modules.director_musique import phases

    contexte, _ = monde
    reglages = {"moteur": MoteurVideo.LTX23.value} if type_ is TypeAction.CHANGER_MOTEUR else {"graine": 7}
    actions.programmer(contexte, P, _entree(type_, plan_id="plan-03", reglages=reglages))
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    moteurs = registre_simule(empreintes.DEFAUTS)
    maestro = ConnecteurSimule("maestro", Voie.GPU, empreintes.DEFAUTS["maestro"])
    maestro.simule = False  # seul DLSS5 manque
    moteurs["maestro"] = maestro
    contexte.prevol = prevol_pour(moteurs)
    avant = len(contexte.file.lister_projet(P))
    with pytest.raises(phases.ErreurPhase, match="DLSS 5 Visual Enhancer n'est pas installé"):
        actions.lancer(contexte, P)
    assert len(contexte.file.lister_projet(P)) == avant
    assert len(actions.lister(contexte, P)) == 1
