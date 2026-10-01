import pytest

from mymaestro.contrat.modeles import FormatImage, MoteurVideo, Plan, RolePlan
from mymaestro.core.grilles import grille
from mymaestro.modules.director_musique.decoupage import normaliser
from mymaestro.modules.director_musique.moteurs import TOLERANCE_RECALAGE_S
from mymaestro.modules.director_musique.modeles import PlanPropose
from mymaestro.modules.director_musique.moteurs import compatibilite, compatibilites
from mymaestro.modules.director_musique.reglages import MoteursPrecoches


def _prop(role, debut, fin):
    return PlanPropose(role=role, debut_s=debut, fin_s=fin, description=f"{role} {debut}")


PROPOSITIONS = [
    _prop(RolePlan.COUPE, 0, 4.8),
    _prop(RolePlan.CHANTE, 4.8, 8.8),  # 4 s : sous le minimum H3, ramené à 124 images
    _prop(RolePlan.COUPE, 8.8, 14),
    _prop(RolePlan.CHANTE, 14, 24),
    _prop(RolePlan.COUPE, 24, 30),
]


def test_pavage_sur_les_grilles_avec_report_de_derive():
    plans = normaliser(PROPOSITIONS, 30.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert [p.images for p in plans] == [121, 124, 97, 243, 153]
    assert [p.moteur_video for p in plans] == [MoteurVideo.LTX23, MoteurVideo.H3, MoteurVideo.LTX23, MoteurVideo.H3, MoteurVideo.LTX23]
    for avant, apres in zip(plans, plans[1:]):
        assert apres.debut_s == pytest.approx(avant.debut_s + avant.duree_s)
    for plan in plans:
        assert grille(plan.moteur_video, FormatImage.PAYSAGE).est_valide(plan.images)
    fin = plans[-1].debut_s + plans[-1].duree_s
    assert abs(fin - 30.0) < 0.25
    assert [p.id for p in plans] == ["p-00", "p-01", "p-02", "p-03", "p-04"]


def test_propositions_desordonnees_et_debordantes():
    propositions = [_prop(RolePlan.COUPE, 20, 40), _prop(RolePlan.CHANTE, 0, 10), _prop(RolePlan.COUPE, 10, 20)]
    plans = normaliser(propositions, 25.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert [p.role for p in plans] == [RolePlan.CHANTE, RolePlan.COUPE, RolePlan.COUPE]
    assert plans[-1].debut_s + plans[-1].duree_s == pytest.approx(25.0, abs=0.25)


def _fin(plans):
    return plans[-1].debut_s + plans[-1].duree_s


def test_proposition_plus_longue_que_la_grille_decoupee_en_tranches():
    propositions = [_prop(RolePlan.COUPE, 0, 15), _prop(RolePlan.CHANTE, 15, 25), _prop(RolePlan.COUPE, 90, 240)]
    plans = normaliser(propositions, 240.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert abs(_fin(plans) - 240.0) < 0.25
    for plan in plans:
        assert grille(plan.moteur_video, FormatImage.PAYSAGE).est_valide(plan.images)


def test_dernier_plan_chante_trop_long_decoupe():
    plans = normaliser([_prop(RolePlan.COUPE, 0, 20), _prop(RolePlan.CHANTE, 20, 28)], 33.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert abs(_fin(plans) - 33.0) < 0.25


def test_propositions_hors_chanson_ne_creent_pas_de_plan_debordant():
    propositions = [_prop(RolePlan.CHANTE, 0, 10), _prop(RolePlan.COUPE, 10, 25), _prop(RolePlan.CHANTE, 25, 30), _prop(RolePlan.COUPE, 30, 35)]
    plans = normaliser(propositions, 25.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert len(plans) == 2
    assert abs(_fin(plans) - 25.0) < 0.25


def test_chante_de_10_s_apres_coupe_arrondie_reste_un_seul_plan_h3():
    propositions = [_prop(RolePlan.COUPE, 0, 5), _prop(RolePlan.CHANTE, 5, 15), _prop(RolePlan.COUPE, 15, 20)]
    plans = normaliser(propositions, 20.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert len(plans) == 3
    assert plans[1].role is RolePlan.CHANTE and plans[1].images == 243


@pytest.mark.parametrize(
    "duree, propositions",
    [
        (25.0, [_prop(RolePlan.CHANTE, 0, 10), _prop(RolePlan.COUPE, 10, 24.7), _prop(RolePlan.CHANTE, 24.7, 25)]),
        (20.0, [_prop(RolePlan.COUPE, 0, 17), _prop(RolePlan.CHANTE, 17, 20)]),
        (25.0, [_prop(RolePlan.CHANTE, 0, 10), _prop(RolePlan.COUPE, 10, 24.6), _prop(RolePlan.CHANTE, 24.6, 24.7), _prop(RolePlan.COUPE, 24.7, 25)]),
    ],
)
def test_aucun_plan_ne_deborde_de_la_chanson(duree, propositions):
    plans = normaliser(propositions, duree, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert _fin(plans) - duree <= TOLERANCE_RECALAGE_S
    for plan in plans:
        assert grille(plan.moteur_video, FormatImage.PAYSAGE).est_valide(plan.images)


def test_dernier_plan_chante_court_garde_ses_paroles():
    """Fin de chanson trop courte pour un plan H3 : le plan de coupe précédent cède la place, le chant reste."""
    propositions = [
        PlanPropose(role=RolePlan.COUPE, debut_s=0, fin_s=17, paroles="", description="intro"),
        PlanPropose(role=RolePlan.CHANTE, debut_s=17, fin_s=20, paroles="dernière phrase chantée", description="final"),
    ]
    plans = normaliser(propositions, 20.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert [p.role for p in plans] == [RolePlan.COUPE, RolePlan.CHANTE]
    assert [p.images for p in plans] == [369, 124]
    assert plans[1].paroles == "dernière phrase chantée"
    assert abs(_fin(plans) - 20.0) <= TOLERANCE_RECALAGE_S


def test_bribe_finale_absorbee_par_le_plan_precedent():
    """Une proposition de 0,3 s en fin de chanson ne crée pas un plan H3 de 5 s : le précédent l'absorbe."""
    propositions = [
        _prop(RolePlan.CHANTE, 0, 10),
        _prop(RolePlan.COUPE, 10, 24.7),
        PlanPropose(role=RolePlan.CHANTE, debut_s=24.7, fin_s=25, paroles="fin", description="bribe", fiches=["fiche-lina"]),
    ]
    plans = normaliser(propositions, 25.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p")
    assert [p.role for p in plans] == [RolePlan.CHANTE, RolePlan.COUPE]
    assert plans[-1].paroles == "fin" and plans[-1].fiches == ["fiche-lina"]
    assert abs(_fin(plans) - 25.0) <= TOLERANCE_RECALAGE_S


def test_fiches_filtrees_sur_le_casting_et_dedoublonnees():
    propositions = [PlanPropose(role=RolePlan.CHANTE, debut_s=0, fin_s=8, description="x", fiches=["fiche-lina", "fiche-lina", "inconnue"])]
    plans = normaliser(propositions, 8.0, FormatImage.PAYSAGE, MoteursPrecoches(chante=MoteurVideo.H3), "p", casting=["fiche-lina"])
    assert plans[0].fiches == ["fiche-lina"]


def _plan(images, fps, role=RolePlan.COUPE):
    return Plan(id="x", indice=0, role=role, debut_s=0, images=images, fps=fps, moteur_video=MoteurVideo.LTX23)


def test_compatibilites_avec_raison_recalage_et_avertissement():
    court = {c.moteur: c for c in compatibilites(_plan(120, 25), FormatImage.PAYSAGE)}  # 4,8 s
    assert not court[MoteurVideo.H3].compatible and court[MoteurVideo.H3].note == "4,8 s < 5,2 s minimum"
    assert court[MoteurVideo.LTX23].compatible and court[MoteurVideo.LTX23].images == 121
    cinq = compatibilite(_plan(120, 24), MoteurVideo.H3, FormatImage.PAYSAGE)  # 5,0 s
    assert cinq.compatible and cinq.images == 124 and cinq.note == "recalé à 5,2 s"
    chante = {c.moteur: c for c in compatibilites(_plan(243, 24, RolePlan.CHANTE), FormatImage.PAYSAGE)}
    assert chante[MoteurVideo.LTX25].compatible and chante[MoteurVideo.LTX25].avertissement == "LTX-2.5 : lip-sync écarté (A/B du 16/08)"
    assert chante[MoteurVideo.H3].avertissement is None and chante[MoteurVideo.H3].note is None
    long = compatibilite(_plan(600, 24), MoteurVideo.H3, FormatImage.PAYSAGE)  # 25 s
    assert not long.compatible and long.note == "25,0 s > 10,1 s maximum"
    ecart = compatibilite(_plan(209, 25), MoteurVideo.H3, FormatImage.PAYSAGE)  # 8,36 s -> 8,71 s
    assert not ecart.compatible and "redécoupe" in ecart.note


def test_compatibilite_h3_selon_la_definition():
    from mymaestro.core.grilles import Definition

    chante = _plan(312, 24, RolePlan.CHANTE)  # 13 s
    en_544 = compatibilite(chante, MoteurVideo.H3, FormatImage.PAYSAGE, Definition.P544)
    assert not en_544.compatible and en_544.note == "13,0 s > 10,1 s maximum"
    assert compatibilite(chante, MoteurVideo.H3, FormatImage.PAYSAGE, Definition.P480).compatible
    par_moteur = {c.moteur: c for c in compatibilites(chante, FormatImage.PAYSAGE, {MoteurVideo.H3: Definition.P480})}
    assert par_moteur[MoteurVideo.H3].compatible


def test_compatibilites_ne_leve_pas_sur_une_definition_h3_non_permise():
    from mymaestro.core.grilles import Definition

    plan = Plan(id="p", indice=0, role=RolePlan.COUPE, debut_s=0, images=243, fps=24, description="x")
    resultat = compatibilites(plan, FormatImage.PAYSAGE, {MoteurVideo.H3: Definition.P1080})
    h3 = next(c for c in resultat if c.moteur is MoteurVideo.H3)
    assert not h3.compatible and "32 Go" in h3.note
