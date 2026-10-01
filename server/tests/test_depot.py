import pytest

from mymaestro.contrat.modeles import ActionEntree, Recette, StatutAction, TypeAction
from mymaestro.core import amorce, depot, etats
from mymaestro.core.db import Base
from mymaestro.fixtures import demo


@pytest.fixture
def base():
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    yield base
    base.fermer()


def test_amorcage_idempotent(base):
    assert amorce.amorcer_si_vide(base) is False
    with base.transaction() as cx:
        assert cx.execute("SELECT COUNT(*) FROM projets").fetchone()[0] == 2


def test_projet_relu_identique(base):
    with base.transaction() as cx:
        relu = depot.lire_projet(cx, demo.PROJET_DEMO)
        assert depot.lire_projet(cx, "inconnu") is None
    assert relu == demo.projets_demo()[demo.PROJET_DEMO]


def test_liste_des_projets(base):
    with base.transaction() as cx:
        resumes = depot.lister_projets(cx)
    assert {r.id: r.nb_plans for r in resumes} == {demo.PROJET_DEMO: 8, demo.PROJET_VERTICAL: 0}


def test_etats_des_clips_deduits_des_prises(base):
    attendu = {plan.id: etat for plan, etat in zip(demo.plans_demo(), demo._ETATS)}
    assert etats.etats_des_plans(demo.projets_demo()[demo.PROJET_DEMO]) == attendu
    with base.transaction() as cx:
        timeline = depot.lire_timeline(cx, demo.PROJET_DEMO)
        assert depot.lire_timeline(cx, demo.PROJET_VERTICAL) is None
    assert {c.plan_id: c.etat for c in timeline.clips if c.piste == "V1"} == attendu
    assert {c.id for c in timeline.clips} == {c.id for c in demo.timeline_demo().clips}


def test_recette_enregistree_puis_modifiee(base):
    recette = Recette(id="r-test", module="director_musique", nom="Essai", valeurs={"format": "9:16"})
    with base.transaction() as cx:
        depot.enregistrer_recette(cx, recette)
        depot.enregistrer_recette(cx, recette.model_copy(update={"nom": "Essai 2"}))
        assert depot.lire_recette(cx, "r-test").nom == "Essai 2"
        assert [r.id for r in depot.lister_recettes(cx, "director_musique")] == [demo.RECETTE_DEMO, "r-test"]


def test_fiche_supprimee_retire_ses_liens(base):
    with base.transaction() as cx:
        assert depot.supprimer_fiche(cx, "fiche-neon") is True
        assert depot.supprimer_fiche(cx, "fiche-neon") is False
        assert "fiche-neon" not in {f.id for f in depot.lister_fiches(cx)}
        projet = depot.lire_projet(cx, demo.PROJET_DEMO)
    assert all("fiche-neon" not in plan.fiches for plan in projet.plans)


def test_fiche_enregistree_avec_ses_images(base):
    source = demo.fiches_demo()[0]
    fiche = source.model_copy(
        update={"id": "fiche-copie", "nom": "Lina bis", "images": [i.model_copy(update={"id": f"{i.id}-bis"}) for i in source.images]}
    )
    with base.transaction() as cx:
        depot.enregistrer_fiche(cx, fiche)
        relue = depot.lire_fiche(cx, "fiche-copie")
    assert relue.nom == "Lina bis"
    assert [i.role for i in relue.images] == [i.role for i in source.images]


def test_actions_programmees_puis_marquees(base):
    with base.transaction() as cx:
        action = depot.programmer_action(
            cx, demo.PROJET_DEMO, ActionEntree(type=TypeAction.PASSE_DLSS5, plan_id="plan-02", reglages={"intensite": 0.8})
        )
        assert [a.id for a in depot.lister_actions(cx, demo.PROJET_DEMO, StatutAction.PROGRAMMEE)] == [action.id]
        depot.marquer_actions(cx, [action.id], StatutAction.LANCEE)
        assert depot.lister_actions(cx, demo.PROJET_DEMO, StatutAction.PROGRAMMEE) == []
        assert depot.lister_actions(cx, demo.PROJET_DEMO)[0].statut is StatutAction.LANCEE
