import dataclasses

import pytest

from mymaestro import modules
from mymaestro.connectors.simule import registre_simule
from mymaestro.connectors.base import ErreurMoteur
from mymaestro.contrat.modeles import CastingModification, EtatPhase, FormatImage, MoteurVideo, PlanModification, ProjetEntree, StatutJob
from mymaestro.core import amorce, depot, empreintes
from mymaestro.core.contexte import Contexte
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.core.ordonnanceur import Ordonnanceur
from mymaestro.fixtures import demo
from recette_de_test import h3_chante_en_544p
from mymaestro.modules.director_musique import phases
from mymaestro.modules.director_musique.modeles import Brief


@pytest.fixture
def monde(tmp_path):
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    h3_chante_en_544p(base)
    file = File(base)
    ordonnanceur = Ordonnanceur(file, registre_simule(empreintes.DEFAUTS, repondeur=modules.repondeur_simule(tmp_path)))
    contexte = Contexte(base=base, file=file, dossier_projets=tmp_path, publier=ordonnanceur.bus.publier, dossier_medias=tmp_path / "medias")
    file.rappels.append(lambda job: modules.apres_job(contexte, job))
    with base.transaction() as cx:
        projet = depot.creer_projet(
            cx, ProjetEntree(titre="Essai", recette_id=demo.RECETTE_DEMO, paroles="Un\nDeux\nTrois", casting=["fiche-lina", "fiche-toit"]),
            phases.MODULE, phases.etat_initial(),
        )
    phases.televerser_fini(contexte, projet.id, "chanson.wav", 45.0)
    yield contexte, ordonnanceur, projet.id
    base.fermer()


def _etats(contexte, projet_id):
    with contexte.base.transaction() as cx:
        return depot.lire_projet(cx, projet_id).etat_phases


def _projet(contexte, projet_id):
    with contexte.base.transaction() as cx:
        return depot.lire_projet(cx, projet_id)


def test_deroule_complet_des_phases_0_a_4(monde, tmp_path):
    contexte, ordonnanceur, projet_id = monde
    assert _etats(contexte, projet_id)["creation"] is EtatPhase.TERMINE
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    # la recette de démo ne s'arrête pas après l'analyse : l'écriture s'ouvre d'elle-même
    assert _etats(contexte, projet_id)["analyse"] is EtatPhase.TERMINE
    assert _etats(contexte, projet_id)["ecriture"] is EtatPhase.EN_COURS
    assert phases.etat_director(contexte, projet_id).analyse.simule

    phases.definir_brief(contexte, projet_id, Brief(ambiance="Nuit, pluie"))
    phases.proposer_concepts(contexte, projet_id)
    assert "ecriture.concepts" in phases.etat_director(contexte, projet_id).en_attente
    ordonnanceur.vider()
    assert len(phases.etat_director(contexte, projet_id).concepts) == 3
    with pytest.raises(phases.ErreurPhase):
        phases.ecrire_decoupage(contexte, projet_id)  # aucun concept retenu
    phases.retenir_concept(contexte, projet_id, 0)
    phases.envoyer_message(contexte, projet_id, "Plus de pluie sur le refrain")
    ordonnanceur.vider()
    assert [m.auteur for m in phases.etat_director(contexte, projet_id).chat] == ["utilisateur", "opus"]
    phases.ecrire_decoupage(contexte, projet_id)
    ordonnanceur.vider()
    projet = _projet(contexte, projet_id)
    assert projet.plans and projet.plans[0].id.startswith(f"{projet_id}-plan-")
    assert _etats(contexte, projet_id)["ecriture"] is EtatPhase.A_VALIDER

    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    projet = _projet(contexte, projet_id)
    assert all(p.prompt_video and p.prompt_image and p.prompt_son for p in projet.plans)
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER

    phases.valider_phase(contexte, projet_id, "prompts")
    ordonnanceur.vider()
    projet = _projet(contexte, projet_id)
    assert all(p.image_depart for p in projet.plans)
    assert all((tmp_path / projet_id / p.image_depart).is_file() for p in projet.plans)
    job_image = next(j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "images.plan")
    assert all(ref.startswith(str((tmp_path / "medias").resolve())) for ref in job_image.donnees["references"])
    assert job_image.donnees["destination"].endswith(job_image.donnees["fichier"].replace("/", "\\")) or job_image.donnees["destination"].endswith(job_image.donnees["fichier"])
    assert (job_image.donnees["largeur"], job_image.donnees["hauteur"]) == (960, 544)
    assert _etats(contexte, projet_id)["images"] is EtatPhase.A_VALIDER

    phases.valider_phase(contexte, projet_id, "images")
    etats = _etats(contexte, projet_id)
    assert etats["images"] is EtatPhase.TERMINE and etats["video"] is EtatPhase.A_FAIRE

    taches = {j.donnees.get("tache"): j for j in contexte.file.lister_projet(projet_id)}
    for tache in ("ecriture.concepts", "ecriture.chat", "ecriture.decoupage", "prompts.image", "prompts.video", "prompts.son"):
        assert "properties" in taches[tache].donnees["schema"], tache


def test_relance_ignore_l_ancien_lancement(monde):
    contexte, ordonnanceur, projet_id = monde
    phases.lancer_phase(contexte, projet_id, "analyse")
    premier = contexte.file.lister_projet(projet_id)[0].id
    phases.lancer_phase(contexte, projet_id, "analyse")
    assert contexte.file.lire(premier).statut is StatutJob.ANNULE
    assert _etats(contexte, projet_id)["analyse"] is EtatPhase.EN_COURS
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["analyse"] is EtatPhase.TERMINE


def test_echec_d_analyse(monde):
    contexte, ordonnanceur, projet_id = monde
    ordonnanceur.connecteurs["maestro"].echecs_restants = 2
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["analyse"] is EtatPhase.ECHEC


def test_prealables_et_validation(monde):
    contexte, _, projet_id = monde
    with pytest.raises(phases.ErreurPhase):
        phases.lancer_phase(contexte, projet_id, "prompts")
    with pytest.raises(phases.ErreurPhase):
        phases.valider_phase(contexte, projet_id, "analyse")
    with pytest.raises(phases.ErreurPhase):
        phases.lancer_phase(contexte, projet_id, "video")


def test_modification_de_plan_et_image_refaite(monde):
    contexte, ordonnanceur, projet_id = monde
    for etape in ("analyse",):
        phases.lancer_phase(contexte, projet_id, etape)
    ordonnanceur.vider()
    phases.proposer_concepts(contexte, projet_id)
    ordonnanceur.vider()
    phases.retenir_concept(contexte, projet_id, 1)
    phases.ecrire_decoupage(contexte, projet_id)
    ordonnanceur.vider()
    projet = _projet(contexte, projet_id)
    chante = next(p for p in projet.plans if p.role == "chante")
    plan = phases.modifier_plan(contexte, projet_id, chante.id, PlanModification(moteur_video=MoteurVideo.LTX23, prompt_video="Nouveau"))
    assert plan.moteur_video is MoteurVideo.LTX23 and plan.fps == 25 and plan.prompt_video == "Nouveau"
    assert plan.debut_s == chante.debut_s
    # chanson de 45 s, paroles sur 15-30 s : le découpage simulé ouvre sur un plan de coupe de 15 s, hors grille H3
    long = next(p for p in projet.plans if p.role == "coupe" and p.duree_s > 11)
    with pytest.raises(phases.ErreurPhase):
        phases.modifier_plan(contexte, projet_id, long.id, PlanModification(moteur_video=MoteurVideo.H3))
    with pytest.raises(KeyError):
        phases.modifier_plan(contexte, projet_id, "plan-inconnu", PlanModification(prompt_image="x"))


# --- Correctifs de vérification (tour 1) -----------------------------------------------------------


def _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id):
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    phases.proposer_concepts(contexte, projet_id)
    ordonnanceur.vider()
    phases.retenir_concept(contexte, projet_id, 0)
    phases.ecrire_decoupage(contexte, projet_id)
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["ecriture"] is EtatPhase.A_VALIDER


def _regler_arrets(monkeypatch, **arrets):
    origine = phases.reglages

    def patche(cx, projet):
        regl = origine(cx, projet)
        for nom, valeur in arrets.items():
            setattr(regl.arrets, nom, valeur)
        return regl

    monkeypatch.setattr(phases, "reglages", patche)


def _sortie_vide_pour(ordonnanceur, tache):
    for connecteur in ordonnanceur.connecteurs.values():
        base = connecteur.repondeur
        connecteur.repondeur = lambda job, base=base: {} if job.donnees.get("tache") == tache else base(job)


def test_image_ratee_reste_a_valider_meme_sans_arret(monde, monkeypatch):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    _regler_arrets(monkeypatch, images=False)
    ordonnanceur.connecteurs["maestro"].echecs_restants = 2
    phases.valider_phase(contexte, projet_id, "prompts")
    ordonnanceur.vider()
    etats = _etats(contexte, projet_id)
    assert etats["images"] is EtatPhase.A_VALIDER and etats["video"] is EtatPhase.A_FAIRE
    manquant = next(p for p in _projet(contexte, projet_id).plans if not p.image_depart)
    phases.refaire_image(contexte, projet_id, manquant.id)
    ordonnanceur.vider()
    assert all(p.image_depart for p in _projet(contexte, projet_id).plans)
    assert "images" not in phases.etat_director(contexte, projet_id).erreurs
    assert _etats(contexte, projet_id)["images"] is EtatPhase.TERMINE and _etats(contexte, projet_id)["video"] is EtatPhase.A_FAIRE


@pytest.mark.parametrize("arret", [True, False])
@pytest.mark.parametrize("rang", ["premier", "dernier"])
def test_image_hors_projet_reste_a_refaire(monde, monkeypatch, arret, rang):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    _regler_arrets(monkeypatch, images=arret)
    plans = _projet(contexte, projet_id).plans
    fautif = plans[0 if rang == "premier" else -1].id
    for connecteur in ordonnanceur.connecteurs.values():
        base = connecteur.repondeur
        connecteur.repondeur = lambda job, base=base: {"fichier": "../dehors.png"} if job.donnees.get("plan_id") == fautif else base(job)
    phases.valider_phase(contexte, projet_id, "prompts")
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["images"] is EtatPhase.A_VALIDER
    assert next(p for p in _projet(contexte, projet_id).plans if p.id == fautif).image_depart is None
    assert phases.etat_director(contexte, projet_id).erreurs["images"] == "1 image(s) à refaire"


def test_relance_manuelle_du_job_retablit_la_phase(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    ordonnanceur.connecteurs["claude"].echecs_restants = 3
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.ECHEC
    en_echec = next(j for j in contexte.file.lister_projet(projet_id) if j.statut is StatutJob.ECHEC)
    contexte.file.relancer(en_echec.id)
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER
    assert "prompts" not in phases.etat_director(contexte, projet_id).erreurs


def test_sortie_invalide_d_un_ancien_lancement_ignoree(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ancien = next(j for j in contexte.file.lister_projet(projet_id) if j.phase == "prompts" and j.statut is StatutJob.EN_FILE)
    phases.lancer_phase(contexte, projet_id, "prompts")  # annule les jobs en file de l'ancien lancement
    contexte.file.terminer(ancien.id, {})
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER


@pytest.mark.parametrize("arret", [True, False])
def test_sortie_invalide_de_prompts_finit_en_echec(monde, monkeypatch, arret):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    _regler_arrets(monkeypatch, prompts=arret)
    _sortie_vide_pour(ordonnanceur, "prompts.image")
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    etats = _etats(contexte, projet_id)
    assert etats["prompts"] is EtatPhase.ECHEC and etats["images"] is EtatPhase.A_FAIRE


def _images_avec_une_ratee(contexte, ordonnanceur, projet_id):
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    ordonnanceur.connecteurs["maestro"].echecs_restants = 2
    phases.valider_phase(contexte, projet_id, "prompts")
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["images"] is EtatPhase.A_VALIDER
    return next(j for j in contexte.file.lister_projet(projet_id) if j.phase == "images" and j.statut is StatutJob.ECHEC)


def test_validation_refusee_tant_qu_un_job_de_la_phase_tourne(monde):
    contexte, ordonnanceur, projet_id = monde
    ratee = _images_avec_une_ratee(contexte, ordonnanceur, projet_id)
    contexte.file.relancer(ratee.id)
    with pytest.raises(phases.ErreurPhase):
        phases.valider_phase(contexte, projet_id, "images")
    ordonnanceur.vider()
    phases.valider_phase(contexte, projet_id, "images")
    assert _etats(contexte, projet_id)["images"] is EtatPhase.TERMINE


def test_fin_tardive_ne_rouvre_pas_une_phase_validee(monde):
    contexte, ordonnanceur, projet_id = monde
    ratee = _images_avec_une_ratee(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "images")  # validée malgré l'image manquante
    contexte.file.relancer(ratee.id)
    ordonnanceur.vider()
    etats = _etats(contexte, projet_id)
    assert etats["images"] is EtatPhase.TERMINE and etats["video"] is EtatPhase.A_FAIRE
    assert all(p.image_depart for p in _projet(contexte, projet_id).plans)


def test_decoupage_tardif_ignore_apres_validation(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.ecrire_decoupage(contexte, projet_id)
    with pytest.raises(phases.ErreurPhase):
        phases.valider_phase(contexte, projet_id, "ecriture")  # un découpage est encore en file
    avant = [p.id for p in _projet(contexte, projet_id).plans]
    with contexte.base.transaction() as cx:  # simule une validation passée juste avant l'arrivée du découpage
        depot.definir_etat_phase(cx, projet_id, "ecriture", EtatPhase.TERMINE)
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["ecriture"] is EtatPhase.TERMINE
    assert [p.id for p in _projet(contexte, projet_id).plans] == avant
    assert "ignoré" in phases.etat_director(contexte, projet_id).erreurs["ecriture"]


def test_validation_refusee_laisse_la_phase_a_valider(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    plan = _projet(contexte, projet_id).plans[0]
    phases.modifier_plan(contexte, projet_id, plan.id, PlanModification(prompt_image=""))
    with pytest.raises(phases.ErreurPhase):
        phases.valider_phase(contexte, projet_id, "prompts")
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER


def test_nouvel_essai_d_ecriture_rouvre_la_phase(monde):
    contexte, ordonnanceur, projet_id = monde
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    _sortie_vide_pour(ordonnanceur, "ecriture.concepts")
    phases.proposer_concepts(contexte, projet_id)
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["ecriture"] is EtatPhase.ECHEC
    for connecteur in ordonnanceur.connecteurs.values():
        connecteur.repondeur = modules.repondeur_simule(contexte.dossier_projets)
    phases.proposer_concepts(contexte, projet_id)
    assert _etats(contexte, projet_id)["ecriture"] is EtatPhase.EN_COURS
    ordonnanceur.vider()
    assert len(phases.etat_director(contexte, projet_id).concepts) == 3


def test_sortie_d_un_lancement_remplace_ignoree(monde):
    contexte, ordonnanceur, projet_id = monde
    phases.lancer_phase(contexte, projet_id, "analyse")
    ancien = contexte.file.lister_projet(projet_id)[0]
    contexte.file.demarrer(ancien.id)  # en cours au moment de la relance : il n'est pas annulé
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    assert phases.etat_director(contexte, projet_id).analyse.bpm == 120
    contexte.file.terminer(ancien.id, {"bpm": 99.0, "simule": True})
    assert phases.etat_director(contexte, projet_id).analyse.bpm == 120
    assert _etats(contexte, projet_id)["analyse"] is EtatPhase.TERMINE


def test_refaire_image_annule_le_job_en_file_du_meme_plan(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    phases.valider_phase(contexte, projet_id, "prompts")
    plan = _projet(contexte, projet_id).plans[0]
    lancement = phases._lancement_courant(contexte, projet_id, "images")
    avant = [j for j in contexte.file.lister_lancement(lancement) if j.donnees.get("plan_id") == plan.id]
    assert avant and avant[-1].statut is StatutJob.EN_FILE
    phases.refaire_image(contexte, projet_id, plan.id)
    apres = [j for j in contexte.file.lister_lancement(lancement) if j.donnees.get("plan_id") == plan.id]
    assert avant[-1].id in {j.id for j in apres if j.statut is StatutJob.ANNULE}
    assert apres[-1].statut is StatutJob.EN_FILE


def test_images_exigent_des_prompts_valides(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER
    with pytest.raises(phases.ErreurPhase):
        phases.lancer_phase(contexte, projet_id, "images")


def _jusqu_aux_images_en_file(contexte, ordonnanceur, projet_id):
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    phases.valider_phase(contexte, projet_id, "prompts")  # images enfilées, pas encore traitées
    return [j for j in contexte.file.lister_projet(projet_id) if j.phase == "images"]


def test_refaire_le_dernier_job_en_file_ne_conclut_pas_la_phase(monde, monkeypatch):
    contexte, ordonnanceur, projet_id = monde
    jobs = _jusqu_aux_images_en_file(contexte, ordonnanceur, projet_id)
    for job in jobs[:-1]:  # tous les autres plans finis : seul le dernier reste en file
        contexte.file.demarrer(job.id)
        contexte.file.terminer(job.id, {"fichier": f"images/{job.donnees['plan_id']}.png"})
    transitions = []
    origine = phases._definir
    monkeypatch.setattr(phases, "_definir", lambda ctx, p, ph, e: (transitions.append((ph, e)), origine(ctx, p, ph, e))[1])
    phases.refaire_image(contexte, projet_id, jobs[-1].donnees["plan_id"])
    assert ("images", EtatPhase.A_VALIDER) not in transitions
    assert _etats(contexte, projet_id)["images"] is EtatPhase.EN_COURS
    assert "images" not in phases.etat_director(contexte, projet_id).erreurs


def test_sortie_d_image_plus_ancienne_ignoree(monde):
    contexte, ordonnanceur, projet_id = monde
    jobs = _jusqu_aux_images_en_file(contexte, ordonnanceur, projet_id)
    ancien = jobs[0]
    contexte.file.demarrer(ancien.id)  # en cours : refaire ne l'annule pas
    phases.refaire_image(contexte, projet_id, ancien.donnees["plan_id"])
    nouveau = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("plan_id") == ancien.donnees["plan_id"]][-1]
    contexte.file.demarrer(nouveau.id)
    contexte.file.terminer(nouveau.id, {"fichier": "images/nouvelle.png"})
    contexte.file.terminer(ancien.id, {"fichier": "images/ancienne.png"})
    plan = next(p for p in _projet(contexte, projet_id).plans if p.id == ancien.donnees["plan_id"])
    assert plan.image_depart == "images/nouvelle.png"


def test_analyse_non_relancable_une_fois_le_decoupage_ecrit(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    with pytest.raises(phases.ErreurPhase):
        phases.lancer_phase(contexte, projet_id, "analyse")


def _refuser_memoire(*noms):
    """Pré-vol doublure : refuse les connecteurs nommés (tous si aucun), note les appels."""
    from mymaestro.outils.systeme import MemoireInsuffisante

    appels: list[str] = []

    def prevol(connecteur: str) -> None:
        appels.append(connecteur)
        if not noms or connecteur in noms:
            raise MemoireInsuffisante("Mémoire engagée insuffisante : quitte Docker Desktop")

    return prevol, appels


def _tous_les_plans_en(contexte, projet_id, moteur):
    with contexte.base.transaction() as cx:
        for plan in depot.lire_projet(cx, projet_id).plans:
            depot.maj_plan(cx, plan.id, moteur_image=moteur)


def test_phase_images_toute_codex_exige_la_marge_memoire(monde):
    from mymaestro.contrat.modeles import MoteurImage

    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    _tous_les_plans_en(contexte, projet_id, MoteurImage.CODEX)
    contexte.prevol, appels = _refuser_memoire("codex")
    with pytest.raises(phases.ErreurPhase, match="Docker"):
        phases.valider_phase(contexte, projet_id, "prompts")
    assert appels == ["codex"]
    assert [j for j in contexte.file.lister_projet(projet_id) if j.phase == "images"] == []
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER


def test_refaire_image_refuse_sans_marge_et_laisse_l_etat_intact(monde):
    contexte, ordonnanceur, projet_id = monde
    jobs = _jusqu_aux_images_en_file(contexte, ordonnanceur, projet_id)
    plan_id = jobs[0].donnees["plan_id"]
    avant = [(j.id, j.statut) for j in contexte.file.lister_projet(projet_id)]
    etats = dict(_etats(contexte, projet_id))
    contexte.prevol, appels = _refuser_memoire()
    with pytest.raises(phases.ErreurPhase, match="Docker"):
        phases.refaire_image(contexte, projet_id, plan_id)
    assert len(appels) == 1 and appels[0] in ("maestro", "codex")
    assert [(j.id, j.statut) for j in contexte.file.lister_projet(projet_id)] == avant
    assert _etats(contexte, projet_id) == etats


def _enregistrer_h3_1080p_sur_32_go(contexte, monkeypatch):
    from mymaestro.outils import gpu

    with monkeypatch.context() as carte:
        carte.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("NVIDIA GeForce RTX 5090", 32768, "nvidia-smi"))
        with contexte.base.transaction() as cx:
            recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
            depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": {"h3": "1080p"}}}))


def test_validation_des_prompts_refuse_h3_1080p_sans_job_d_image(monde, monkeypatch):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    _enregistrer_h3_1080p_sur_32_go(contexte, monkeypatch)
    etats = dict(_etats(contexte, projet_id))
    with pytest.raises(phases.ErreurPhase, match="32 Go"):
        phases.valider_phase(contexte, projet_id, "prompts")
    assert not [j for j in contexte.file.lister_projet(projet_id) if j.phase == "images"]
    assert _etats(contexte, projet_id)["images"] == etats["images"]
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER


def test_refaire_image_refuse_h3_1080p_et_laisse_l_etat_intact(monde, monkeypatch):
    contexte, ordonnanceur, projet_id = monde
    jobs = _jusqu_aux_images_en_file(contexte, ordonnanceur, projet_id)
    ordonnanceur.vider()  # images terminées : la phase attend sa validation
    assert _etats(contexte, projet_id)["images"] is EtatPhase.A_VALIDER
    chante = next(p for p in _projet(contexte, projet_id).plans if p.moteur_video is MoteurVideo.H3)
    _enregistrer_h3_1080p_sur_32_go(contexte, monkeypatch)
    avant = [(j.id, j.statut) for j in contexte.file.lister_projet(projet_id)]
    etats = dict(_etats(contexte, projet_id))
    with pytest.raises(phases.ErreurPhase, match="32 Go"):
        phases.refaire_image(contexte, projet_id, chante.id)
    assert [(j.id, j.statut) for j in contexte.file.lister_projet(projet_id)] == avant
    assert _etats(contexte, projet_id) == etats


def test_h3_non_fourni_prend_le_defaut_de_la_carte_a_la_lecture(monde, monkeypatch):
    from mymaestro.outils import gpu

    contexte, ordonnanceur, projet_id = monde
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("Carte de 8 Go", 8192, "nvidia-smi"))
    with contexte.base.transaction() as cx:
        projet = depot.lire_projet(cx, projet_id)
        assert phases.reglages(cx, projet).rendu.h3 == "480p"  # recette de test : section rendu vide
        sans_recette = projet.model_copy(update={"recette_id": None})
        assert phases.reglages(cx, sans_recette).rendu.h3 == "480p"
        recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": {"h3": "544p"}}}))
        assert phases.reglages(cx, projet).rendu.h3 == "544p"  # valeur explicite : jamais remplacée
    # Un projet dont la recette ne dit rien de H3 lance ses images sans refus sur 8 Go.
    with contexte.base.transaction() as cx:
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": {}}}))
    jobs = _jusqu_aux_images_en_file(contexte, ordonnanceur, projet_id)
    h3 = [j for j in jobs if (j.donnees["largeur"], j.donnees["hauteur"]) == (864, 480)]
    assert jobs and h3


def test_decoupage_refuse_apres_changement_de_carte_met_l_ecriture_en_echec(monde, monkeypatch):
    from mymaestro.outils import gpu

    contexte, ordonnanceur, projet_id = monde
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    phases.proposer_concepts(contexte, projet_id)
    ordonnanceur.vider()
    phases.retenir_concept(contexte, projet_id, 0)
    _enregistrer_h3_1080p_sur_32_go(contexte, monkeypatch)
    with monkeypatch.context() as carte:
        carte.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("NVIDIA GeForce RTX 5090", 32768, "nvidia-smi"))
        phases.ecrire_decoupage(contexte, projet_id)  # enfilé sur 32 Go
    ordonnanceur.vider()  # livré sur 12 Go : la définition n'est plus permise
    assert _etats(contexte, projet_id)["ecriture"] is EtatPhase.ECHEC
    assert "32 Go" in phases.etat_director(contexte, projet_id).erreurs["ecriture"]


def test_bonsai_rate_deux_fois_bascule_sur_claude(monde):
    contexte, ordonnanceur, projet_id = monde
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    phases.proposer_concepts(contexte, projet_id)
    ordonnanceur.vider()
    phases.retenir_concept(contexte, projet_id, 0)
    phases.ecrire_decoupage(contexte, projet_id)
    ordonnanceur.vider()
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.connecteurs["bonsai"].echecs_restants = 2
    ordonnanceur.vider()
    jobs = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.video"]
    assert [(j.connecteur, j.statut) for j in jobs] == [("bonsai", StatutJob.ECHEC), ("claude", StatutJob.TERMINE)]
    assert jobs[1].donnees["remplace"] == jobs[0].id
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER
    assert all(p.prompt_video for p in _projet(contexte, projet_id).plans)
    assert "repris par Claude" in phases.etat_director(contexte, projet_id).erreurs["bascule"]


def test_relance_du_job_bonsai_apres_reprise_claude_ratee_retablit_la_phase(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    ordonnanceur.connecteurs["bonsai"].echecs_restants = 2
    claude = ordonnanceur.connecteurs["claude"]
    base = claude.repondeur

    def repondeur(job):
        if job.donnees.get("remplace"):  # la reprise Claude échoue (quota épuisé)
            raise ErreurMoteur("quota Claude épuisé")
        return base(job) if base is not None else {}

    claude.repondeur = repondeur
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.ECHEC
    jobs = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.video"]
    assert [(j.connecteur, j.statut) for j in jobs] == [("bonsai", StatutJob.ECHEC), ("claude", StatutJob.ECHEC)]
    contexte.file.relancer(jobs[0].id)
    ordonnanceur.vider()
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER
    assert "prompts" not in phases.etat_director(contexte, projet_id).erreurs


def test_fin_tardive_d_un_job_remplace_n_ecrase_pas_les_prompts_corriges(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    ordonnanceur.connecteurs["bonsai"].echecs_restants = 2
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()  # Bonsai rate deux fois, la reprise Claude réussit
    bonsai = next(j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.video" and j.connecteur == "bonsai")
    plan = _projet(contexte, projet_id).plans[0]
    phases.modifier_plan(contexte, projet_id, plan.id, PlanModification(prompt_video="CORRIGÉ À LA MAIN"))
    contexte.file.relancer(bonsai.id)  # relance tardive du job remplacé, pendant la relecture (A_VALIDER)
    ordonnanceur.vider()
    assert _projet(contexte, projet_id).plans[0].prompt_video == "CORRIGÉ À LA MAIN"
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER
    phases.valider_phase(contexte, projet_id, "prompts")
    ordonnanceur.connecteurs["bonsai"].echecs_restants = 2
    contexte.file.relancer(bonsai.id)  # et après validation : ni écrasement, ni bascule, ni phase rouverte
    ordonnanceur.vider()
    assert _projet(contexte, projet_id).plans[0].prompt_video == "CORRIGÉ À LA MAIN"
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.TERMINE
    reprises = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("remplace") == bonsai.id]
    assert len(reprises) == 1


def _bonsai_rend_une_sortie_refusee(ordonnanceur):
    bonsai = ordonnanceur.connecteurs["bonsai"]
    base = bonsai.repondeur
    bonsai.repondeur = lambda job, base=base: {"prompts": []} if job.donnees.get("tache") == "prompts.video" else base(job)


def test_sortie_refusee_de_bonsai_bascule_sur_claude(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    _bonsai_rend_une_sortie_refusee(ordonnanceur)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    jobs = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.video"]
    assert [(j.connecteur, j.statut) for j in jobs] == [("bonsai", StatutJob.TERMINE), ("claude", StatutJob.TERMINE)]
    assert jobs[1].donnees["remplace"] == jobs[0].id
    assert _etats(contexte, projet_id)["prompts"] is EtatPhase.A_VALIDER
    assert all(p.prompt_video for p in _projet(contexte, projet_id).plans)
    erreurs = phases.etat_director(contexte, projet_id).erreurs
    assert "prompts" not in erreurs and "prompts manquants" in erreurs["bascule"]


def test_une_seule_reprise_pendant_qu_une_autre_est_en_file(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    ordonnanceur.connecteurs["bonsai"].echecs_restants = 2
    claude = ordonnanceur.connecteurs["claude"]
    base = claude.repondeur

    def repondeur(job):
        if job.donnees.get("remplace"):
            raise ErreurMoteur("quota Claude épuisé")
        return base(job) if base is not None else {}

    claude.repondeur = repondeur
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    jobs = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.video"]
    bonsai, reprise = jobs[0], jobs[1]
    assert bonsai.connecteur == "bonsai" and reprise.statut is StatutJob.ECHEC
    contexte.file.relancer(reprise.id)  # la reprise est de nouveau en file
    phases.apres_job(contexte, next(j for j in contexte.file.lister_projet(projet_id) if j.id == bonsai.id))
    reprises = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("remplace") == bonsai.id]
    assert len(reprises) == 1


def test_note_de_bascule_cumulee_puis_effacee(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    ordonnanceur.connecteurs["bonsai"].echecs_restants = 2
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    bonsai = next(j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.video" and j.connecteur == "bonsai")
    autre = dataclasses.replace(bonsai, id="job-autre", libelle="Prompts son")
    phases._basculer_sur_claude(contexte, autre)
    note = phases.etat_director(contexte, projet_id).erreurs["bascule"]
    assert "Prompts vidéo" in note and "Prompts son" in note and ";" in note
    phases._basculer_sur_claude(contexte, autre, "motif")  # même phrase, jamais répétée deux fois
    assert phases.etat_director(contexte, projet_id).erreurs["bascule"].count("Prompts son") == 1
    phases.lancer_phase(contexte, projet_id, "prompts")
    assert "bascule" not in phases.etat_director(contexte, projet_id).erreurs


def test_bornes_du_decoupage_suivent_la_definition_h3(monde):
    contexte, ordonnanceur, projet_id = monde
    with contexte.base.transaction() as cx:
        recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": {"h3": "480p"}}}))
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    phases.proposer_concepts(contexte, projet_id)
    ordonnanceur.vider()
    phases.retenir_concept(contexte, projet_id, 0)
    phases.ecrire_decoupage(contexte, projet_id)
    job = next(j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "ecriture.decoupage")
    assert "14.4 s (minimax_h3, 480p)" in job.donnees["prompt"]


def test_image_de_depart_a_la_definition_du_moteur_video_du_plan(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    with contexte.base.transaction() as cx:
        recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": {"ltx23": "1080p", "h3": "480p"}}}))
    phases.valider_phase(contexte, projet_id, "prompts")
    projet = _projet(contexte, projet_id)
    attendu = {MoteurVideo.LTX23: (1920, 1088), MoteurVideo.H3: (864, 480), MoteurVideo.LTX25: (960, 544)}
    jobs = {j.donnees["plan_id"]: j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "images.plan"}
    assert {p.moteur_video for p in projet.plans} >= {MoteurVideo.LTX23, MoteurVideo.H3}
    for plan in projet.plans:
        assert (jobs[plan.id].donnees["largeur"], jobs[plan.id].donnees["hauteur"]) == attendu[plan.moteur_video]


# --- Casting modifiable après la création (premier vrai test, 2026-10-01) ------------------------------


def _fiches_des_plans(contexte, projet_id):
    return {p.id: p.fiches for p in _projet(contexte, projet_id).plans}


def test_casting_modifiable_apres_creation(monde):
    contexte, _, projet_id = monde
    projet = phases.modifier_casting(contexte, projet_id, CastingModification(casting=["fiche-neon", "fiche-lina", "fiche-neon"]))
    assert projet.casting == ["fiche-neon", "fiche-lina"]
    assert _projet(contexte, projet_id).casting == ["fiche-neon", "fiche-lina"]
    with pytest.raises(phases.ErreurPhase, match="fiche-absente"):
        phases.modifier_casting(contexte, projet_id, CastingModification(casting=["fiche-lina", "fiche-absente"]))
    assert _projet(contexte, projet_id).casting == ["fiche-neon", "fiche-lina"]
    with pytest.raises(KeyError):
        phases.modifier_casting(contexte, "projet-inconnu", CastingModification(casting=[]))


def test_fiche_retiree_du_casting_quitte_les_plans(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    assert any("fiche-toit" in fiches for fiches in _fiches_des_plans(contexte, projet_id).values())
    phases.modifier_casting(contexte, projet_id, CastingModification(casting=["fiche-lina"]))
    assert not any("fiche-toit" in fiches for fiches in _fiches_des_plans(contexte, projet_id).values())
    assert any("fiche-lina" in fiches for fiches in _fiches_des_plans(contexte, projet_id).values())


def test_fiche_ajoutee_au_casting_et_a_tous_les_plans_sert_de_reference(monde, tmp_path):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    plan = _projet(contexte, projet_id).plans[0]
    phases.modifier_plan(contexte, projet_id, plan.id, PlanModification(fiches=[]))  # retirée à la main d'un plan…
    phases.modifier_casting(contexte, projet_id, CastingModification(casting=["fiche-lina", "fiche-toit", "fiche-neon"], ajouter_aux_plans=True))
    fiches = _fiches_des_plans(contexte, projet_id)
    assert all("fiche-neon" in f for f in fiches.values())  # seule la fiche nouvelle entre dans tous les plans
    assert fiches[plan.id] == ["fiche-neon"]  # …et pas remise par l'ajout d'une autre
    phases.valider_phase(contexte, projet_id, "ecriture")
    ordonnanceur.vider()
    phases.valider_phase(contexte, projet_id, "prompts")
    job = next(j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "images.plan" and j.donnees["plan_id"] == plan.id)
    assert job.donnees["references"] == [str((tmp_path / "medias" / "bibliotheque/fiche-neon/reference.png").resolve())]


def test_fiches_d_un_plan_modifiables_dans_le_casting_seulement(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    plan = _projet(contexte, projet_id).plans[0]
    relu = phases.modifier_plan(contexte, projet_id, plan.id, PlanModification(fiches=["fiche-toit", "fiche-lina", "fiche-toit"]))
    assert relu.fiches == ["fiche-toit", "fiche-lina"]
    with pytest.raises(phases.ErreurPhase, match="casting"):
        phases.modifier_plan(contexte, projet_id, plan.id, PlanModification(fiches=["fiche-neon"]))
    assert _fiches_des_plans(contexte, projet_id)[plan.id] == ["fiche-toit", "fiche-lina"]
    autre = _projet(contexte, projet_id).plans[1]
    assert phases.modifier_plan(contexte, projet_id, autre.id, PlanModification(prompt_image="x")).fiches == autre.fiches  # None = inchangé


def test_le_llm_connait_le_casting_par_son_nom(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    decoupage = next(j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "ecriture.decoupage")
    assert "Lina" in decoupage.donnees["prompt"] and "personnage" in decoupage.donnees["prompt"]
    phases.valider_phase(contexte, projet_id, "ecriture")
    prompts_image = next(j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.image")
    assert "Lina" in prompts_image.donnees["prompt"]


def test_casting_vide_retire_toutes_les_fiches_des_plans(monde):
    contexte, ordonnanceur, projet_id = monde
    _jusqu_a_l_ecriture_validable(contexte, ordonnanceur, projet_id)
    assert any(_fiches_des_plans(contexte, projet_id).values())
    phases.modifier_casting(contexte, projet_id, CastingModification(casting=[]))
    assert not any(_fiches_des_plans(contexte, projet_id).values())
