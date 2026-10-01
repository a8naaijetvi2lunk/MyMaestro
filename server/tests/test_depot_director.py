import pytest

from mymaestro.contrat.modeles import EtatPhase, FormatImage, Plan, ProjetEntree, RolePlan
from mymaestro.core import amorce, db, depot
from mymaestro.core.db import Base
from mymaestro.fixtures import demo


@pytest.fixture
def base():
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    yield base
    base.fermer()


def test_palier_3():
    connexion = db.ouvrir(":memory:")
    assert "prompt_son" in db.colonnes(connexion, "plans")
    assert "duree_chanson_s" in db.colonnes(connexion, "projets")
    assert db.version(connexion) == len(db.PALIERS) == 3


def test_creation_d_un_projet(base):
    entree = ProjetEntree(titre="Derrière la vitre", format=FormatImage.PORTRAIT, recette_id=demo.RECETTE_DEMO,
                          paroles="Ligne 1\nLigne 2", casting=["fiche-lina", "fiche-toit"])
    with base.transaction() as cx:
        projet = depot.creer_projet(cx, entree, "director_musique", {"creation": EtatPhase.EN_COURS, "analyse": EtatPhase.A_FAIRE})
        relu = depot.lire_projet(cx, projet.id)
    assert relu == projet
    assert (relu.titre, relu.format, relu.casting, relu.paroles) == ("Derrière la vitre", FormatImage.PORTRAIT, ["fiche-lina", "fiche-toit"], "Ligne 1\nLigne 2")
    assert relu.etat_phases == {"creation": EtatPhase.EN_COURS, "analyse": EtatPhase.A_FAIRE}


def test_donnees_module_modifiees_sans_perdre_la_timeline(base):
    with base.transaction() as cx:
        depot.modifier_donnees_module(cx, demo.PROJET_DEMO, "analyse", {"bpm": 120})
        depot.modifier_donnees_module(cx, demo.PROJET_DEMO, "ecriture", {"brief": {}})
        donnees = depot.lire_donnees_module(cx, demo.PROJET_DEMO)
        assert depot.lire_timeline(cx, demo.PROJET_DEMO) is not None
        depot.modifier_donnees_module(cx, demo.PROJET_DEMO, "ecriture", None)
        assert "ecriture" not in depot.lire_donnees_module(cx, demo.PROJET_DEMO)
    assert donnees["analyse"] == {"bpm": 120} and "timeline" in donnees


def test_etat_de_phase_et_champs_du_projet(base):
    with base.transaction() as cx:
        etats = depot.definir_etat_phase(cx, demo.PROJET_VERTICAL, "analyse", EtatPhase.A_VALIDER)
        depot.maj_projet(cx, demo.PROJET_VERTICAL, chanson="chanson.wav", duree_chanson_s=61.5)
        projet = depot.lire_projet(cx, demo.PROJET_VERTICAL)
        with pytest.raises(ValueError):
            depot.maj_projet(cx, demo.PROJET_VERTICAL, titre="interdit")
    assert etats["analyse"] is EtatPhase.A_VALIDER
    assert (projet.chanson, projet.duree_chanson_s) == ("chanson.wav", 61.5)


def test_plans_remplaces_et_modifies(base):
    plans = [
        Plan(id="demo-reel-vertical-plan-00", indice=0, role=RolePlan.COUPE, debut_s=0, images=121, fps=25, fiches=["fiche-neon"]),
        Plan(id="demo-reel-vertical-plan-01", indice=1, role=RolePlan.CHANTE, debut_s=4.84, images=243, fps=24),
    ]
    with base.transaction() as cx:
        depot.remplacer_plans(cx, demo.PROJET_VERTICAL, plans)
        depot.maj_plan(cx, "demo-reel-vertical-plan-01", prompt_video="Already singing", image_depart="images/p1.png")
        with pytest.raises(ValueError):
            depot.maj_plan(cx, "demo-reel-vertical-plan-01", indice=3)
        relu = depot.lire_projet(cx, demo.PROJET_VERTICAL)
        depot.remplacer_plans(cx, demo.PROJET_VERTICAL, plans[:1])
        assert len(depot.lire_projet(cx, demo.PROJET_VERTICAL).plans) == 1
    assert [p.fiches for p in relu.plans] == [["fiche-neon"], []]
    assert (relu.plans[1].prompt_video, relu.plans[1].image_depart, relu.plans[1].prompt_son) == ("Already singing", "images/p1.png", "")
