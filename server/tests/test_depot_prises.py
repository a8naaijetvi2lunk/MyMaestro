import pytest

from mymaestro.contrat.modeles import (
    ActionEntree,
    Clip,
    EtapePostProd,
    MoteurVideo,
    Regime,
    StatutTraitement,
    TypeAction,
    Voie,
)
from mymaestro.core import amorce, depot
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.fixtures import demo


@pytest.fixture
def base():
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    yield base
    base.fermer()


def test_prise_et_sorties_numerotees(base):
    with base.transaction() as cx:
        prise = depot.creer_prise(cx, "plan-01", MoteurVideo.LTX23, 42, {"images": 121})
        assert prise.numero == 3  # plan-01 a déjà deux prises de démonstration
        flashvsr = depot.creer_sortie(cx, prise.id, EtapePostProd.FLASHVSR, {"facteur": 2})
        dlss5 = depot.creer_sortie(cx, prise.id, EtapePostProd.DLSS5, {"style": "Cinematic"})
        assert (flashvsr.ordre, dlss5.ordre) == (1, 2)
        depot.maj_prise(cx, prise.id, statut=StatutTraitement.TERMINE, fichier_brut=f"prises/{prise.id}/brut.mp4")
        depot.maj_sortie(cx, dlss5.id, statut=StatutTraitement.ECHEC, erreur="CUDA out of memory")
        depot.maj_sortie(cx, flashvsr.id, statut=StatutTraitement.TERMINE, fichier=f"prises/{prise.id}/1-flashvsr.mp4")
        depot.maj_prise(cx, prise.id, sortie_active_id=flashvsr.id)
        depot.maj_plan(cx, "plan-01", prise_active_id=prise.id)
        relu = depot.lire_projet(cx, demo.PROJET_DEMO)
        assert depot.existe(cx, "prises", prise.id) and not depot.existe(cx, "sorties", "inconnue")
    active = next(p for p in relu.prises if p.id == prise.id)
    assert active.statut is StatutTraitement.TERMINE and active.graine == 42
    assert active.sortie_active_id == flashvsr.id
    assert [s.erreur for s in active.sorties] == [None, "CUDA out of memory"]
    assert next(p for p in relu.plans if p.id == "plan-01").prise_active_id == prise.id


def test_champs_non_modifiables_refuses(base):
    with base.transaction() as cx:
        with pytest.raises(ValueError):
            depot.maj_prise(cx, "plan-00-p1", plan_id="autre")
        with pytest.raises(ValueError):
            depot.maj_sortie(cx, "plan-00-p1-s1", etape="dlss5")
        with pytest.raises(ValueError):
            depot.maj_clip(cx, "clip-plan-00", plan_id="autre")
        with pytest.raises(ValueError):
            depot.existe(cx, "projets; DROP TABLE plans", "x")


def test_clips_pistes_et_suppression(base):
    with base.transaction() as cx:
        depot.definir_pistes(cx, demo.PROJET_DEMO, ["V1", "A0", "A1", "A2"])
        depot.inserer_clip(cx, demo.PROJET_DEMO, Clip(id="clip-son", piste="A2", fichier_audio="sons/x.wav", position_s=3, sortie_s=2))
        depot.maj_clip(cx, "clip-son", position_s=5.0, verrou_chanson=False, volume=0.5)
        timeline = depot.lire_timeline(cx, demo.PROJET_DEMO)
        son = next(c for c in timeline.clips if c.id == "clip-son")
        assert (son.position_s, son.volume, son.verrou_chanson) == (5.0, 0.5, False)
        assert timeline.pistes == ["V1", "A0", "A1", "A2"]
        assert depot.supprimer_clip(cx, "clip-son") and not depot.supprimer_clip(cx, "clip-son")
        with pytest.raises(KeyError):
            depot.definir_pistes(cx, demo.PROJET_VERTICAL, ["V1"])  # pas de timeline


def test_suppression_de_prise_emporte_ses_sorties(base):
    with base.transaction() as cx:
        assert depot.supprimer_prise(cx, "plan-01-p1")
        assert cx.execute("SELECT COUNT(*) FROM sorties WHERE prise_id = 'plan-01-p1'").fetchone()[0] == 0
        assert [p.id for p in depot.lire_projet(cx, demo.PROJET_DEMO).prises if p.plan_id == "plan-01"] == ["plan-01-p2"]


def test_action_retiree_seulement_si_programmee(base):
    with base.transaction() as cx:
        action = depot.programmer_action(cx, demo.PROJET_DEMO, ActionEntree(type=TypeAction.BRUITAGE, plan_id="plan-00"))
        assert not depot.supprimer_action(cx, demo.PROJET_VERTICAL, action.id)
        assert depot.supprimer_action(cx, demo.PROJET_DEMO, action.id)
        assert not depot.supprimer_action(cx, demo.PROJET_DEMO, action.id)


def test_ordre_max_par_regime(base):
    file = File(base)
    assert file.ordre_max(Regime.CARTE) == 0
    file.ajouter(voie=Voie.GPU, connecteur="maestro", regime=Regime.CARTE, ordre=1_000_004)
    assert file.ordre_max(Regime.CARTE) == 1_000_004 and file.ordre_max(Regime.PHASES) == 0


def test_images_de_depart_de_la_demo(base):
    with base.transaction() as cx:
        assert all(p.image_depart == f"images/{p.id}.png" for p in depot.lire_projet(cx, demo.PROJET_DEMO).plans)


def test_maj_clip_entree_et_sortie_ensemble(base):
    with base.transaction() as cx:
        depot.maj_clip(cx, "clip-plan-00", entree_s=0.0, sortie_s=2.0)
        depot.maj_clip(cx, "clip-plan-00", entree_s=3.0, sortie_s=4.5)
        clip = next(c for c in depot.lire_timeline(cx, demo.PROJET_DEMO).clips if c.id == "clip-plan-00")
    assert (clip.entree_s, clip.sortie_s) == (3.0, 4.5)
