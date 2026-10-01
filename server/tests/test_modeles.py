import pytest
from pydantic import ValidationError

from mymaestro.contrat.modeles import (
    Clip,
    EtapePostProd,
    MoteurVideo,
    Plan,
    Prise,
    Projet,
    RolePlan,
    SortiePostProd,
    StatutTraitement,
    Timeline,
)


def _plan(indice: int = 0, **surcharges) -> Plan:
    valeurs = dict(id=f"plan-{indice}", indice=indice, role=RolePlan.CHANTE, debut_s=0, images=243, fps=24)
    valeurs.update(surcharges)
    return Plan(**valeurs)


def _clip(identifiant: str, position: float, duree: float, piste: str = "V1") -> Clip:
    return Clip(id=identifiant, piste=piste, plan_id="plan-0", position_s=position, sortie_s=duree)


def test_duree_du_plan_calculee_et_serialisee():
    plan = _plan()
    assert plan.duree_s == pytest.approx(10.125)
    assert plan.model_dump()["duree_s"] == pytest.approx(10.125)


def test_clip_sortie_avant_entree_refusee():
    with pytest.raises(ValidationError):
        Clip(id="c", piste="V1", plan_id="plan-0", position_s=0, entree_s=2, sortie_s=1)


def test_clip_video_sans_plan_refuse():
    with pytest.raises(ValidationError):
        Clip(id="c", piste="V1", position_s=0, sortie_s=1)


def test_clip_audio_sans_fichier_refuse():
    with pytest.raises(ValidationError):
        Clip(id="c", piste="A1", position_s=0, sortie_s=1)


def test_nom_de_piste_invalide_refuse():
    with pytest.raises(ValidationError):
        Clip(id="c", piste="X1", plan_id="plan-0", position_s=0, sortie_s=1)


def test_timeline_clips_bout_a_bout_acceptes():
    timeline = Timeline(
        projet_id="p", duree_chanson_s=20, pistes=["V1"],
        clips=[_clip("a", 0, 5), _clip("b", 5, 5)],
    )
    assert len(timeline.clips) == 2


def test_timeline_chevauchement_refuse():
    with pytest.raises(ValidationError, match="chevauchement"):
        Timeline(projet_id="p", duree_chanson_s=20, pistes=["V1"], clips=[_clip("a", 0, 5), _clip("b", 4, 5)])


def test_timeline_piste_non_declaree_refusee():
    with pytest.raises(ValidationError, match="non déclarées"):
        Timeline(projet_id="p", duree_chanson_s=20, pistes=["V1"], clips=[_clip("a", 0, 5, piste="V2")])


def test_prise_sortie_active_inconnue_refusee():
    with pytest.raises(ValidationError):
        Prise(id="x", plan_id="plan-0", numero=1, moteur=MoteurVideo.H3, statut=StatutTraitement.TERMINE, sortie_active_id="absente")


def test_prise_sortie_active_connue_acceptee():
    sortie = SortiePostProd(id="s1", etape=EtapePostProd.FLASHVSR, ordre=1, statut=StatutTraitement.TERMINE)
    prise = Prise(
        id="x", plan_id="plan-0", numero=1, moteur=MoteurVideo.H3,
        statut=StatutTraitement.TERMINE, sorties=[sortie], sortie_active_id="s1",
    )
    assert prise.sortie_active_id == "s1"


def test_projet_indices_non_consecutifs_refuses():
    with pytest.raises(ValidationError, match="indices"):
        Projet(id="p", titre="t", module="director_musique", format="16:9", cree_le="2026-09-29", plans=[_plan(0), _plan(2)])


def test_projet_prise_active_d_un_autre_plan_refusee():
    prise = Prise(id="x", plan_id="plan-1", numero=1, moteur=MoteurVideo.H3, statut=StatutTraitement.TERMINE)
    with pytest.raises(ValidationError, match="prise active"):
        Projet(
            id="p", titre="t", module="director_musique", format="16:9", cree_le="2026-09-29",
            plans=[_plan(0, prise_active_id="x"), _plan(1)], prises=[prise],
        )


from mymaestro.contrat.modeles import ActionEntree, EtatFile, RecetteEntree  # noqa: E402


def test_champs_a_defaut_obligatoires_dans_le_schema_de_sortie():
    from mymaestro.app import creer_app

    schemas = creer_app().openapi()["components"]["schemas"]
    assert {"plans", "prises", "etat_phases"} <= set(schemas["Projet"]["required"])
    assert "etat" in schemas["Clip"]["required"]


def test_entrees_valident_leurs_contraintes():
    with pytest.raises(ValidationError):
        RecetteEntree(module="director_musique", nom="")
    with pytest.raises(ValidationError):
        ActionEntree(type="inconnu")
    assert ActionEntree(type="passe_dlss5", plan_id="plan-02").reglages == {}


def test_etat_file_vide_par_defaut():
    etat = EtatFile()
    assert (etat.gpu_occupe_par, etat.en_marche, etat.jobs, etat.connecteurs) == (None, False, [], [])
