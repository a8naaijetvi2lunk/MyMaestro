import pytest

from mymaestro.contrat.modeles import (
    ClipModification,
    EtatClip,
    FormatImage,
    Plan,
    Projet,
    RolePlan,
    TypePiste,
    Voie,
)
from mymaestro.core import amorce, depot
from mymaestro.core.contexte import Contexte
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.fixtures import demo
from mymaestro.modules.director_musique import timeline
from mymaestro.modules.director_musique.phases import ErreurPhase

P = demo.PROJET_DEMO


@pytest.fixture
def monde(tmp_path):
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    yield Contexte(base=base, file=File(base), dossier_projets=tmp_path)
    base.fermer()


def _clip(contexte, clip_id):
    return next(c for c in timeline.lire(contexte, P).clips if c.id == clip_id)


def test_timeline_initiale_absorbe_le_recalage_des_plans():
    projet = Projet(
        id="p", titre="t", module="director_musique", format=FormatImage.PAYSAGE, cree_le="x", chanson="chanson.wav",
        duree_chanson_s=20.0,
        plans=[
            Plan(id="p0", indice=0, role=RolePlan.COUPE, debut_s=0.0, images=126, fps=25),  # 5,04 s : mord de 0,04 s
            Plan(id="p1", indice=1, role=RolePlan.CHANTE, debut_s=5.0, images=243, fps=24),
        ],
    )
    initiale = timeline.timeline_initiale(projet)
    video = [c for c in initiale.clips if c.piste == "V1"]
    assert [(c.plan_id, c.position_s, c.sortie_s, c.verrou_chanson) for c in video] == [
        ("p0", 0.0, 5.0, False), ("p1", 5.0, 10.125, True),
    ]
    chanson = next(c for c in initiale.clips if c.piste == "A0")
    assert (chanson.fichier_audio, chanson.sortie_s, chanson.verrou_chanson) == ("chanson.wav", 20.0, True)
    assert initiale.pistes == ["V1", "A0", "A1"]


def test_assurer_ne_recree_pas(monde):
    avant = {c.id for c in timeline.lire(monde, P).clips}
    assert {c.id for c in timeline.assurer(monde, P).clips} == avant
    assert timeline.lire(monde, demo.PROJET_VERTICAL) is None


def test_la_chanson_ne_bouge_pas_mais_se_regle(monde):
    with pytest.raises(ErreurPhase):
        timeline.modifier_clip(monde, P, "clip-chanson", ClipModification(position_s=1.0))
    reglee = timeline.modifier_clip(monde, P, "clip-chanson", ClipModification(volume=0.7))
    assert next(c for c in reglee.clips if c.id == "clip-chanson").volume == 0.7


def test_plan_chante_ancre_rognable_pas_deplacable(monde):
    clip = _clip(monde, "clip-plan-01")  # plan chanté, ancré à 4,84 s
    with pytest.raises(ErreurPhase, match="déverrouille"):
        timeline.modifier_clip(monde, P, clip.id, ClipModification(position_s=clip.position_s + 0.5))
    # rogner par la gauche : l'entrée et la position bougent ensemble, la synchro suit
    rognee = timeline.modifier_clip(monde, P, clip.id, ClipModification(position_s=clip.position_s + 1.0, entree_s=1.0))
    rogne = next(c for c in rognee.clips if c.id == clip.id)
    assert rogne.position_s == pytest.approx(clip.position_s + 1.0) and rogne.entree_s == 1.0 and rogne.verrou_chanson
    # déverrouillé, il se déplace ; reverrouillé hors de sa place, refus
    timeline.modifier_clip(monde, P, clip.id, ClipModification(verrou_chanson=False))
    timeline.modifier_clip(monde, P, clip.id, ClipModification(position_s=clip.position_s + 0.5))
    with pytest.raises(ErreurPhase, match="à refaire"):
        timeline.modifier_clip(monde, P, clip.id, ClipModification(verrou_chanson=True))


def test_chevauchement_et_bornes_refuses(monde):
    with pytest.raises(ErreurPhase, match="Chevauchement"):
        timeline.modifier_clip(monde, P, "clip-plan-02", ClipModification(position_s=10.0))
    with pytest.raises(ErreurPhase, match="rendu du plan"):
        timeline.modifier_clip(monde, P, "clip-plan-07", ClipModification(sortie_s=20.0))
    with pytest.raises(ErreurPhase, match="audio"):
        timeline.modifier_clip(monde, P, "clip-plan-00", ClipModification(volume=0.5))
    with pytest.raises(ErreurPhase, match="piste"):
        timeline.modifier_clip(monde, P, "clip-plan-00", ClipModification(piste="A1"))
    with pytest.raises(KeyError):
        timeline.modifier_clip(monde, P, "clip-inconnu", ClipModification(volume=0.5))


def test_piste_video_supplementaire_et_deplacement_libre(monde):
    etendue = timeline.ajouter_piste(monde, P, TypePiste.VIDEO)
    assert etendue.pistes == ["V2", "V1", "A0", "A1"]
    deplacee = timeline.modifier_clip(monde, P, "clip-plan-02", ClipModification(piste="V2", position_s=20.0))
    clip = next(c for c in deplacee.clips if c.id == "clip-plan-02")
    assert (clip.piste, clip.position_s) == ("V2", 20.0)
    assert timeline.ajouter_piste(monde, P, TypePiste.AUDIO).pistes == ["V2", "V1", "A0", "A1", "A2"]


def test_couper_puis_supprimer(monde):
    clip = _clip(monde, "clip-plan-01")
    coupee = timeline.couper(monde, P, clip.id, clip.position_s + 4.0)
    morceaux = sorted((c for c in coupee.clips if c.plan_id == "plan-01"), key=lambda c: c.position_s)
    assert len(morceaux) == 2 and all(m.verrou_chanson for m in morceaux)
    assert morceaux[0].sortie_s == pytest.approx(4.0) and morceaux[1].entree_s == pytest.approx(4.0)
    assert morceaux[1].position_s == pytest.approx(clip.position_s + 4.0)
    assert morceaux[1].fin_s == pytest.approx(clip.fin_s)
    with pytest.raises(ErreurPhase):
        timeline.couper(monde, P, clip.id, clip.position_s + 0.01)
    with pytest.raises(ErreurPhase):
        timeline.couper(monde, P, "clip-chanson", 10.0)
    timeline.supprimer_clip(monde, P, morceaux[1].id)
    with pytest.raises(ErreurPhase, match="Dernier clip"):
        timeline.supprimer_clip(monde, P, morceaux[0].id)
    with pytest.raises(ErreurPhase):
        timeline.supprimer_clip(monde, P, "clip-chanson")
    sans_son = timeline.supprimer_clip(monde, P, "clip-bruitage-metro")
    assert all(c.id != "clip-bruitage-metro" for c in sans_son.clips)


def test_son_place_sur_la_premiere_piste_libre(monde):
    with monde.base.transaction() as cx:
        premier = timeline.placer_son(cx, P, "sons/a.wav", 31.0, 0.0, 2.0)  # le métro occupe A1 de 30,5 à 32,3 s
        second = timeline.placer_son(cx, P, "sons/b.wav", 0.0, 0.0, 2.0)
    assert (premier.piste, second.piste) == ("A2", "A1")
    assert "A2" in timeline.lire(monde, P).pistes


def test_prise_et_sortie_actives(monde):
    projet = timeline.choisir_prise(monde, P, "plan-01", "plan-01-p1")
    assert next(p for p in projet.plans if p.id == "plan-01").prise_active_id == "plan-01-p1"
    with pytest.raises(ErreurPhase):
        timeline.choisir_prise(monde, P, "plan-06", "plan-06-p1")  # prise en échec
    with pytest.raises(KeyError):
        timeline.choisir_prise(monde, P, "plan-01", "plan-02-p1")  # prise d'un autre plan
    projet = timeline.choisir_sortie(monde, P, "plan-01-p2", "plan-01-p2-s1")
    assert next(p for p in projet.prises if p.id == "plan-01-p2").sortie_active_id == "plan-01-p2-s1"
    projet = timeline.choisir_sortie(monde, P, "plan-01-p2", None)
    assert next(p for p in projet.prises if p.id == "plan-01-p2").sortie_active_id is None
    with pytest.raises(KeyError):
        timeline.choisir_sortie(monde, P, "plan-01-p2", "sortie-inconnue")


def test_nettoyer_les_prises_non_retenues(monde, tmp_path):
    dossier = tmp_path / P / "prises" / "plan-01-p1"
    dossier.mkdir(parents=True)
    (dossier / "brut.mp4").write_bytes(b"0123456789")
    bilan = timeline.nettoyer(monde, P)
    assert (bilan.prises_supprimees, bilan.octets_liberes) == (1, 10)
    assert not dossier.exists()
    with monde.base.transaction() as cx:
        assert [p.id for p in depot.lire_projet(cx, P).prises if p.plan_id == "plan-01"] == ["plan-01-p2"]


def test_nettoyer_garde_la_ligne_d_une_prise_dont_le_dossier_resiste(monde, tmp_path, monkeypatch):
    dossier = tmp_path / P / "prises" / "plan-01-p1"
    dossier.mkdir(parents=True)
    (dossier / "brut.mp4").write_bytes(b"0123456789")

    def refuse(chemin, *args, **kwargs):
        raise PermissionError("fichier ouvert")

    monkeypatch.setattr(timeline.shutil, "rmtree", refuse)
    bilan = timeline.nettoyer(monde, P)
    assert (bilan.prises_supprimees, bilan.octets_liberes) == (0, 0)
    assert (dossier / "brut.mp4").exists()
    with monde.base.transaction() as cx:
        assert "plan-01-p1" in [p.id for p in depot.lire_projet(cx, P).prises]
    monkeypatch.undo()
    assert timeline.nettoyer(monde, P).prises_supprimees == 1  # le prochain nettoyage réessaie
    assert not dossier.exists()


def test_segments_suivent_la_derniere_sortie_disponible(monde, tmp_path):
    fichier = tmp_path / P / "prises" / "plan-00-p1" / "2-dlss5.mp4"
    fichier.parent.mkdir(parents=True)
    fichier.write_bytes(b"x")
    segments = timeline.segments(monde, P)
    assert segments[0].clip_id == "clip-plan-00" and segments[0].fichier == "prises/plan-00-p1/2-dlss5.mp4"
    assert segments[1].clip_id == "clip-plan-01" and segments[1].fichier is None  # fichier absent du disque
    assert segments[-1].clip_id is None and segments[-1].fin_s == demo.DUREE_CHANSON_S


def test_etat_en_rendu_et_progression(monde):
    job = monde.file.ajouter(voie=Voie.GPU, connecteur="maestro", projet_id=P, donnees={"tache": "video.plan", "prise_id": "plan-05-p1"})
    monde.file.demarrer(job)
    monde.file.progresser(job, 0.42)
    clip = _clip(monde, "clip-plan-05")
    assert (clip.etat, clip.progression) == (EtatClip.EN_RENDU, 0.42)
