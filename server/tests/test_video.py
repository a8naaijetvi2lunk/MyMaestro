import threading
import time
from pathlib import Path
import types
import wave

import pytest

from mymaestro import modules
from mymaestro.connectors.simule import registre_simule
from mymaestro.contrat.modeles import EtapePostProd, EtatClip, EtatPhase, MoteurVideo, ProjetEntree, StatutJob, StatutTraitement
from mymaestro.core import amorce, depot, empreintes
from mymaestro.core.contexte import Contexte
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.core.ordonnanceur import Ordonnanceur
from mymaestro.fixtures import demo
from recette_de_test import h3_chante_en_544p
from mymaestro.modules.director_musique import phases, timeline, video
from mymaestro.outils import ffmpeg


def _ffmpeg_disponible() -> bool:
    try:
        ffmpeg.trouver("ffmpeg")
        ffmpeg.trouver("ffprobe")
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")

DUREE_S = 45.0
NOTIFICATIONS: list[tuple[str, str]] = []


def _notifications_recues(nombre=1):
    """La notification part dans un fil démon (hors du verrou de fin) : on l'attend brièvement."""
    limite = time.monotonic() + 2
    while len(NOTIFICATIONS) < nombre and time.monotonic() < limite:
        time.sleep(0.01)
    return NOTIFICATIONS


def _chanson(chemin):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(chemin), "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(8000)
        sortie.writeframes(b"\x00\x00" * int(8000 * DUREE_S))


@pytest.fixture
def pret(tmp_path):
    """Projet mené jusqu'aux images validées, sur connecteurs simulés (recette de démo : H3 chanté, LTX-2.3 en coupe)."""
    NOTIFICATIONS.clear()
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    h3_chante_en_544p(base)
    file = File(base)
    ordonnanceur = Ordonnanceur(file, registre_simule(empreintes.DEFAUTS, repondeur=modules.repondeur_simule(tmp_path)))
    contexte = Contexte(
        base=base, file=file, dossier_projets=tmp_path, publier=ordonnanceur.bus.publier,
        notifier=lambda titre, message: NOTIFICATIONS.append((titre, message)),
    )
    file.rappels.append(lambda job: modules.apres_job(contexte, job))
    with base.transaction() as cx:
        projet = depot.creer_projet(
            cx, ProjetEntree(titre="Essai", recette_id=demo.RECETTE_DEMO, paroles="Un\nDeux\nTrois", casting=["fiche-lina", "fiche-toit"]),
            phases.MODULE, phases.etat_initial(),
        )
    _chanson(tmp_path / projet.id / "chanson.wav")
    phases.televerser_fini(contexte, projet.id, "chanson.wav", DUREE_S)
    phases.lancer_phase(contexte, projet.id, "analyse")
    ordonnanceur.vider()
    phases.proposer_concepts(contexte, projet.id)
    ordonnanceur.vider()
    phases.retenir_concept(contexte, projet.id, 0)
    phases.ecrire_decoupage(contexte, projet.id)
    ordonnanceur.vider()
    for phase in ("ecriture", "prompts", "images"):
        phases.valider_phase(contexte, projet.id, phase)
        ordonnanceur.vider()
    yield contexte, ordonnanceur, projet.id
    base.fermer()


def _projet(contexte, projet_id):
    with contexte.base.transaction() as cx:
        return depot.lire_projet(cx, projet_id)


def test_timeline_creee_a_la_validation_des_images(pret):
    contexte, _, projet_id = pret
    projet = _projet(contexte, projet_id)
    creee = timeline.lire(contexte, projet_id)
    assert sorted(c.plan_id for c in creee.clips if c.piste == "V1") == sorted(p.id for p in projet.plans)
    assert all(c.etat is EtatClip.PREVU for c in creee.clips if c.piste == "V1")
    assert next(c for c in creee.clips if c.piste == "A0").fichier_audio == "chanson.wav"
    assert projet.etat_phases["video"] is EtatPhase.A_FAIRE


def test_phase_video_complete(pret, tmp_path):
    contexte, ordonnanceur, projet_id = pret
    projet = _projet(contexte, projet_id)
    estimation = video.estimer(contexte, projet_id)
    assert estimation.suffisant and estimation.plans == len(projet.plans)
    phases.lancer_phase(contexte, projet_id, "video")
    etats = _projet(contexte, projet_id).etat_phases
    assert etats["video"] is EtatPhase.EN_COURS and etats["postprod"] is EtatPhase.EN_COURS
    jobs = sorted(contexte.file.lister_projet(projet_id), key=lambda j: j.ordre)
    rendus = [j for j in jobs if str(j.donnees.get("tache", "")).startswith(("video.", "postprod."))]
    nombre = len(projet.plans)
    assert [j.donnees["tache"] for j in rendus] == ["video.plan"] * nombre + ["postprod.flashvsr"] * nombre + ["postprod.dlss5"] * nombre
    modeles = [j.modele for j in rendus[:nombre]]
    assert modeles == sorted(modeles, key=lambda m: video.RANG_MOTEUR[MoteurVideo(m)])  # H3 d'abord, puis LTX
    ordonnanceur.vider()
    projet = _projet(contexte, projet_id)
    assert projet.etat_phases["video"] is EtatPhase.TERMINE and projet.etat_phases["postprod"] is EtatPhase.TERMINE
    for plan in projet.plans:
        prise = next(p for p in projet.prises if p.id == plan.prise_active_id)
        assert prise.statut is StatutTraitement.TERMINE
        assert [s.etape for s in prise.sorties] == [EtapePostProd.FLASHVSR, EtapePostProd.DLSS5]
        assert prise.sortie_active_id == prise.sorties[-1].id
        infos = ffmpeg.sonder(tmp_path / projet_id / prise.fichier_brut)
        assert infos["images"] == plan.images and infos["audio"] is (plan.role == "chante")
    assert all(c.etat is EtatClip.DLSS5 for c in timeline.lire(contexte, projet_id).clips if c.piste == "V1")
    assert len(_notifications_recues()) == 1 and f"{len(projet.plans)}/{len(projet.plans)} plans rendus" in NOTIFICATIONS[0][1]
    [rapport] = (tmp_path / projet_id / "rapports").glob("video-*.md")
    lignes = [l for l in rapport.read_text(encoding="utf-8").splitlines() if l.startswith("| ") and l[2].isdigit()]
    assert len(lignes) == len(projet.plans) and all(l.count("| fait |") == 2 for l in lignes)  # rendu et post-production


def test_rendu_rate_deux_fois_clip_rouge_et_file_continue(pret):
    contexte, ordonnanceur, projet_id = pret
    phases.lancer_phase(contexte, projet_id, "video")
    ordonnanceur.connecteurs["maestro"].echecs_restants = 2  # le premier rendu échoue deux fois
    ordonnanceur.vider()
    projet = _projet(contexte, projet_id)
    ratees = [p for p in projet.prises if p.statut is StatutTraitement.ECHEC]
    assert len(ratees) == 1 and "échec simulé" in ratees[0].erreur
    assert all(s.statut is StatutTraitement.ECHEC for s in ratees[0].sorties)
    assert sum(1 for p in projet.prises if p.statut is StatutTraitement.TERMINE) == len(projet.plans) - 1
    assert projet.etat_phases["video"] is EtatPhase.TERMINE
    erreurs = phases.etat_director(contexte, projet_id).erreurs
    assert erreurs["video"].startswith("1 job") and erreurs["postprod"].startswith("2 étape")
    rouge = next(c for c in timeline.lire(contexte, projet_id).clips if c.plan_id == ratees[0].plan_id)
    assert rouge.etat is EtatClip.ECHEC
    assert len(_notifications_recues()) == 1 and "1 en échec" in NOTIFICATIONS[0][1]


def test_disque_insuffisant_puis_relance_refusee(pret, monkeypatch):
    contexte, _, projet_id = pret
    monkeypatch.setattr(video.shutil, "disk_usage", lambda chemin: types.SimpleNamespace(free=10))
    with pytest.raises(phases.ErreurPhase, match="Disque insuffisant"):
        phases.lancer_phase(contexte, projet_id, "video")
    assert not [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "video.plan"]
    assert _projet(contexte, projet_id).etat_phases["video"] is EtatPhase.A_FAIRE
    monkeypatch.undo()
    phases.lancer_phase(contexte, projet_id, "video")
    with pytest.raises(phases.ErreurPhase, match="déjà lancée"):
        phases.lancer_phase(contexte, projet_id, "video")


def test_lancements_simultanes_un_seul_lot(pret, monkeypatch):
    contexte, ordonnanceur, projet_id = pret
    barriere = threading.Barrier(2)
    vraie = video.estimer

    def estimer_synchronise(*args, **kwargs):
        try:
            barriere.wait(timeout=1)  # sans verrou, les deux appels se retrouvent ici, contrôle d'état déjà passé
        except threading.BrokenBarrierError:
            pass
        return vraie(*args, **kwargs)

    monkeypatch.setattr(video, "estimer", estimer_synchronise)
    resultats: list[BaseException | None] = []

    def lancer():
        try:
            phases.lancer_phase(contexte, projet_id, "video")
            resultats.append(None)
        except BaseException as exc:  # noqa: BLE001
            resultats.append(exc)

    fils = [threading.Thread(target=lancer) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    erreurs = [r for r in resultats if r is not None]
    assert len(erreurs) == 1 and isinstance(erreurs[0], phases.ErreurPhase) and "déjà lancée" in str(erreurs[0])
    nombre = len(_projet(contexte, projet_id).plans)
    assert sum(1 for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "video.plan") == nombre
    ordonnanceur.vider()
    etats = _projet(contexte, projet_id).etat_phases
    assert etats["video"] is EtatPhase.TERMINE and etats["postprod"] is EtatPhase.TERMINE


def test_segment_audio_distingue_les_cadences(pret):
    contexte, _, projet_id = pret
    projet = _projet(contexte, projet_id)
    chante = next(p for p in projet.plans if p.role == "chante")
    a25 = chante.model_copy(update={"images": 89, "fps": 25})
    a24 = chante.model_copy(update={"images": 89, "fps": 24})
    fichier25, fichier24 = video.segment_audio(contexte, projet, a25), video.segment_audio(contexte, projet, a24)
    assert fichier25 != fichier24
    assert ffmpeg.sonder(Path(fichier25))["duree_s"] == pytest.approx(89 / 25, abs=0.05)
    assert ffmpeg.sonder(Path(fichier24))["duree_s"] == pytest.approx(89 / 24, abs=0.05)


def test_rendu_refait_rate_est_signale_a_l_utilisateur(pret):
    from mymaestro.contrat.modeles import ActionEntree, TypeAction
    from mymaestro.modules.director_musique import actions

    contexte, ordonnanceur, projet_id = pret
    phases.lancer_phase(contexte, projet_id, "video")
    ordonnanceur.vider()
    actions.programmer(contexte, projet_id, ActionEntree(type=TypeAction.REFAIRE, plan_id=_projet(contexte, projet_id).plans[0].id))
    ordonnanceur.connecteurs["maestro"].echecs_restants = 2
    actions.lancer(contexte, projet_id)
    ordonnanceur.vider()
    erreur = phases.etat_director(contexte, projet_id).erreurs["actions"]
    assert "Plan 1" in erreur and "rendu refait a échoué" in erreur and "ancienne prise reste active" in erreur


def test_cause_multiligne_donne_une_seule_ligne_de_tableau():
    trace = "Traceback (most recent call last):\n  File 'x.py', line 1\nValueError: a | b " + "z" * 400
    plan = types.SimpleNamespace(id="pl1", indice=0)
    projet = types.SimpleNamespace(titre="Essai", plans=[plan])
    job = types.SimpleNamespace(
        donnees={"plan_id": "pl1", "prise_id": "pr1"}, statut=StatutJob.ECHEC, erreur=trace, modele="minimax_h3",
        demarre_le=None, termine_le=None,
    )
    _, texte = video.rediger_rapport(projet, [job], [])
    lignes = [l for l in texte.splitlines() if l.startswith("| 1 ")]
    assert len(lignes) == 1 and lignes[0].count("|") == 7
    assert len(lignes[0]) < 400


# --- Plan 6c tâche 2 : rendu à la définition choisie dans la recette -----------------------------------


def _regler_rendu(contexte, **rendu):
    with contexte.base.transaction() as cx:
        recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": {**recette.valeurs, "rendu": rendu}}))


def _jobs_par_tache(contexte, projet_id, tache):
    return [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == tache]


def test_ltx_en_720p_rend_en_1280x704_avec_flashvsr(pret):
    contexte, _, projet_id = pret
    _regler_rendu(contexte, ltx23="720p")
    phases.lancer_phase(contexte, projet_id, "video")
    projet = _projet(contexte, projet_id)
    rendus = _jobs_par_tache(contexte, projet_id, "video.plan")
    ltx = [j for j in rendus if j.modele == MoteurVideo.LTX23.value]
    assert ltx and all((j.donnees["largeur"], j.donnees["hauteur"], j.donnees["definition"]) == (1280, 704, "720p") for j in ltx)
    autres = [j for j in rendus if j.modele != MoteurVideo.LTX23.value]
    assert all((j.donnees["largeur"], j.donnees["hauteur"], j.donnees["definition"]) == (960, 544, "544p") for j in autres)
    assert len(_jobs_par_tache(contexte, projet_id, "postprod.flashvsr")) == len(projet.plans)
    with contexte.base.transaction() as cx:
        reglages_prise = cx.execute("SELECT reglages FROM prises WHERE id = ?", (ltx[0].donnees["prise_id"],)).fetchone()[0]
    assert '"definition": "720p"' in reglages_prise and '"largeur": 1280' in reglages_prise and '"hauteur": 704' in reglages_prise


def test_h3_1080p_enregistre_sur_32_go_refuse_au_lancement_sur_12_go(pret, monkeypatch):
    from mymaestro.outils import gpu

    contexte, _, projet_id = pret
    with monkeypatch.context() as carte:
        carte.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("NVIDIA GeForce RTX 5090", 32768, "nvidia-smi"))
        _regler_rendu(contexte, h3="1080p")
    with pytest.raises(phases.ErreurPhase, match="32 Go"):
        phases.lancer_phase(contexte, projet_id, "video")
    assert not [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "video.plan"]


def test_ltx_en_1080p_saute_flashvsr_et_dlss5_part_du_brut(pret):
    contexte, _, projet_id = pret
    _regler_rendu(contexte, ltx23="1080p")
    phases.lancer_phase(contexte, projet_id, "video")
    projet = _projet(contexte, projet_id)
    rendus = _jobs_par_tache(contexte, projet_id, "video.plan")
    ltx = {j.donnees["plan_id"]: j for j in rendus if j.modele == MoteurVideo.LTX23.value}
    assert ltx and all((j.donnees["largeur"], j.donnees["hauteur"]) == (1920, 1088) for j in ltx.values())
    vsr = {j.donnees["plan_id"] for j in _jobs_par_tache(contexte, projet_id, "postprod.flashvsr")}
    assert vsr.isdisjoint(ltx) and len(vsr) == len(projet.plans) - len(ltx)  # projet mixte : FlashVSR pour les autres plans seulement
    dlss5 = {j.donnees["plan_id"]: j for j in _jobs_par_tache(contexte, projet_id, "postprod.dlss5")}
    assert set(dlss5) == {p.id for p in projet.plans}
    for plan_id, rendu in ltx.items():
        assert dlss5[plan_id].donnees["source"] == rendu.donnees["destination"] and dlss5[plan_id].donnees["apres"] == [rendu.id]


def test_estimation_proportionnelle_aux_pixels_et_sans_flashvsr_en_1080p(pret):
    contexte, _, projet_id = pret
    plans = [p for p in _projet(contexte, projet_id).plans if p.moteur_video is MoteurVideo.LTX23]
    duree = sum(p.duree_s for p in plans)
    debits = video.OCTETS_PAR_SECONDE
    with contexte.base.transaction() as cx:
        regl = phases.reglages(cx, _projet(contexte, projet_id))
    assert regl.postprod.flashvsr.actif and regl.postprod.dlss5.actif
    attendu_544p = duree * (debits["brut"] + debits["flashvsr"] + debits["dlss5"]) * video.MARGE_DISQUE
    assert video.octets_estimes(plans, regl) == pytest.approx(attendu_544p, abs=2)
    _regler_rendu(contexte, ltx23="1080p")
    with contexte.base.transaction() as cx:
        regl = phases.reglages(cx, _projet(contexte, projet_id))
    # 1920×1088 = 4 × 960×544 : brut quatre fois plus lourd, pas de FlashVSR, DLSS5 sur une image de sortie
    attendu_1080p = duree * (4 * debits["brut"] + debits["dlss5"]) * video.MARGE_DISQUE
    assert video.octets_estimes(plans, regl) == pytest.approx(attendu_1080p, abs=2)


def test_message_hors_grille_d_un_plan_ltx_garde_son_libelle_et_son_remede(pret):
    contexte, _, projet_id = pret
    plan = next(p for p in _projet(contexte, projet_id).plans if p.moteur_video is MoteurVideo.LTX23)
    with contexte.base.transaction() as cx:
        depot.maj_plan(cx, plan.id, images=9)  # 0,36 s : sous le minimum de LTX-2.3 (17 images à 25 fps)
        projet = phases._projet(cx, projet_id)
        regl = phases.reglages(cx, projet)
    relu = next(p for p in projet.plans if p.id == plan.id)
    message = video.message_hors_grille([relu], projet.format, regl)
    assert f"plan {plan.indice + 1} (0,4 s, LTX-2.3 : minimum 0,7 s en 544p)" in message
    assert message.endswith("redécoupe le plan ou change son moteur") and "480p" not in message


def test_plan_h3_hors_grille_en_544p_refuse_le_lancement(pret):
    contexte, _, projet_id = pret
    plan = next(p for p in _projet(contexte, projet_id).plans if p.moteur_video is MoteurVideo.H3)
    with contexte.base.transaction() as cx:
        depot.maj_plan(cx, plan.id, images=277)  # 11,5 s, sur la grille H3 (124 + 17k) mais au-delà des 10,1 s de 544p
    with pytest.raises(phases.ErreurPhase, match=rf"plan {plan.indice + 1}.*10,1 s en 544p.*passe H3 en 480p dans la recette"):
        phases.lancer_phase(contexte, projet_id, "video")
    assert not _jobs_par_tache(contexte, projet_id, "video.plan")
    _regler_rendu(contexte, h3="480p")
    phases.lancer_phase(contexte, projet_id, "video")  # 11,5 s tiennent en 480p (14,4 s max)
    assert _jobs_par_tache(contexte, projet_id, "video.plan")


def test_plan_ltx_en_1080p_va_jusqu_au_bout_sans_flashvsr(pret):
    contexte, ordonnanceur, projet_id = pret
    _regler_rendu(contexte, ltx23="1080p")
    phases.lancer_phase(contexte, projet_id, "video")
    ordonnanceur.vider()
    projet = _projet(contexte, projet_id)
    assert projet.etat_phases["video"] is EtatPhase.TERMINE and projet.etat_phases["postprod"] is EtatPhase.TERMINE
    for plan in projet.plans:
        prise = next(p for p in projet.prises if p.id == plan.prise_active_id)
        attendu = [EtapePostProd.DLSS5] if plan.moteur_video is MoteurVideo.LTX23 else [EtapePostProd.FLASHVSR, EtapePostProd.DLSS5]
        assert prise.statut is StatutTraitement.TERMINE and [s.etape for s in prise.sorties] == attendu
        assert prise.sortie_active_id == prise.sorties[-1].id
