import pytest

from mymaestro.contrat.modeles import FormatImage, MoteurVideo
from mymaestro.core import grilles


def test_grille_h3_paysage_960x544():
    g = grilles.grille(MoteurVideo.H3, FormatImage.PAYSAGE)
    assert g.valeurs() == [124, 141, 158, 175, 192, 209, 226, 243]
    assert g.fps == 24
    assert g.duree_min_s == pytest.approx(124 / 24)
    assert g.duree_max_s == pytest.approx(10.125)


def test_h3_portrait_meme_plafond_que_paysage():
    assert grilles.grille(MoteurVideo.H3, FormatImage.PORTRAIT).images_max == 243


def test_plafonds_h3_selon_les_pixels_sur_12_go():
    assert grilles.plafond_h3(864, 480, 12.0) == 345
    assert grilles.plafond_h3(960, 544, 12.0) == 243
    assert grilles.plafond_h3(1280, 704, 12.0) == 124
    assert grilles.plafond_h3(1920, 1088, 12.0) is None
    assert grilles.plafond_h3(960, 544) == 243  # sans VRAM donnée : la carte détectée (12 Go de référence)


def test_plafonds_h3_selon_la_vram():
    assert grilles.plafond_h3(1280, 704, 24.0) == 345
    assert grilles.plafond_h3(1920, 1088, 24.0) == 158
    assert grilles.plafond_h3(1920, 1088, 32.0) == 243
    assert grilles.plafond_h3(864, 480, 8.0) == 243
    assert grilles.plafond_h3(960, 544, 8.0) == 124


def test_definitions_permises_selon_la_vram():
    D = grilles.Definition
    assert grilles.definitions_permises(MoteurVideo.H3, vram_go=12.0) == (D.P480, D.P544)
    assert grilles.definitions_permises(MoteurVideo.H3, vram_go=16.0) == (D.P480, D.P544, D.P720)
    assert grilles.definitions_permises(MoteurVideo.H3, vram_go=24.0) == (D.P480, D.P544, D.P720)
    assert grilles.definitions_permises(MoteurVideo.H3, vram_go=32.0) == (D.P480, D.P544, D.P720, D.P1080)
    assert grilles.definitions_permises(MoteurVideo.H3, vram_go=8.0) == (D.P480,)
    assert grilles.definitions_permises(MoteurVideo.H3) == (D.P480, D.P544)  # carte de référence
    for moteur in (MoteurVideo.LTX23, MoteurVideo.LTX25):
        for vram in (8.0, 12.0, 32.0):
            assert grilles.definitions_permises(moteur, vram_go=vram) == (D.P544, D.P720, D.P1080)


def test_grille_h3_1080p_selon_la_vram():
    D = grilles.Definition
    assert grilles.grille(MoteurVideo.H3, FormatImage.PAYSAGE, D.P1080, vram_go=32.0).images_max == 243
    with pytest.raises(ValueError, match="32 Go"):
        grilles.grille(MoteurVideo.H3, FormatImage.PAYSAGE, D.P1080, vram_go=12.0)
    with pytest.raises(ValueError, match="32 Go"):
        grilles.resolution_rendu(MoteurVideo.H3, FormatImage.PAYSAGE, D.P1080, vram_go=12.0)


def test_refus_de_720p_cite_le_plancher_reel_de_la_table():
    D = grilles.Definition
    with pytest.raises(ValueError, match="16 Go"):
        grilles.resolution_rendu(MoteurVideo.H3, FormatImage.PAYSAGE, D.P720, vram_go=12.0)
    with pytest.raises(ValueError, match="16 Go"):
        grilles.grille(MoteurVideo.H3, FormatImage.PAYSAGE, D.P720, vram_go=12.0)
    with pytest.raises(ValueError, match="12 Go"):
        grilles.resolution_rendu(MoteurVideo.H3, FormatImage.PAYSAGE, D.P544, vram_go=8.0)


def test_grilles_ltx():
    ltx23 = grilles.grille(MoteurVideo.LTX23)
    assert (ltx23.fps, ltx23.images_min, ltx23.pas, ltx23.images_max) == (25, 17, 8, 793)
    assert ltx23.est_valide(121)
    assert not ltx23.est_valide(120)
    ltx25 = grilles.grille(MoteurVideo.LTX25)
    assert (ltx25.fps, ltx25.images_max) == (24, 761)


def test_plus_proche_reste_sur_la_grille():
    g = grilles.grille(MoteurVideo.H3)
    assert g.plus_proche(6.0) == 141
    assert g.plus_proche(60.0) == 243
    assert g.plus_proche(0.5) == 124


def test_moteurs_compatibles_selon_la_duree():
    assert grilles.moteurs_compatibles(12.0) == [MoteurVideo.LTX23, MoteurVideo.LTX25]
    assert grilles.moteurs_compatibles(3.0) == [MoteurVideo.LTX23, MoteurVideo.LTX25]
    assert grilles.moteurs_compatibles(8.0) == [MoteurVideo.H3, MoteurVideo.LTX23, MoteurVideo.LTX25]


def test_resolution_rendu_par_definition_et_format():
    D = grilles.Definition
    assert grilles.resolution_rendu(MoteurVideo.LTX23, FormatImage.PAYSAGE, D.P1080) == (1920, 1088)
    assert grilles.resolution_rendu(MoteurVideo.LTX23, FormatImage.PORTRAIT, D.P720) == (704, 1280)
    assert grilles.resolution_rendu(MoteurVideo.H3, FormatImage.PAYSAGE) == (960, 544)
    with pytest.raises(ValueError):
        grilles.resolution_rendu(MoteurVideo.H3, FormatImage.PAYSAGE, D.P1080)


def test_grille_h3_selon_la_definition_et_ltx_inchange():
    D = grilles.Definition
    assert grilles.grille(MoteurVideo.H3, FormatImage.PAYSAGE, D.P480).images_max == 345
    assert grilles.grille(MoteurVideo.H3, FormatImage.PAYSAGE, D.P544).images_max == 243
    for moteur in (MoteurVideo.LTX23, MoteurVideo.LTX25):
        assert grilles.grille(moteur, FormatImage.PAYSAGE, D.P1080) == grilles.grille(moteur, FormatImage.PAYSAGE, D.P544)


def test_saute_flashvsr_quand_le_rendu_atteint_la_sortie():
    D = grilles.Definition
    assert grilles.saute_flashvsr(MoteurVideo.LTX23, FormatImage.PAYSAGE, D.P1080)
    assert grilles.saute_flashvsr(MoteurVideo.LTX23, FormatImage.PORTRAIT, D.P1080)
    assert not grilles.saute_flashvsr(MoteurVideo.LTX23, FormatImage.PAYSAGE, D.P720)
    assert not grilles.saute_flashvsr(MoteurVideo.LTX23, FormatImage.PAYSAGE, D.P544)


def test_reglages_rendu_defaut_et_refus_h3_1080p():
    from pydantic import ValidationError

    from mymaestro.modules.director_musique.reglages import ReglagesDirector

    regl = ReglagesDirector()
    assert regl.rendu.h3 == "544p"
    assert regl.rendu.definitions() == {moteur: grilles.Definition.P544 for moteur in MoteurVideo}
    assert ReglagesDirector.model_validate({"rendu": {"h3": "1080p"}}).rendu.h3 == "1080p"  # la lecture ne refuse jamais : le refus se fait à l'enregistrement
    with pytest.raises(ValidationError):
        ReglagesDirector.model_validate({"rendu": {"ltx23": "480p"}})
    assert ReglagesDirector.model_validate({"rendu": {"ltx23": "1080p"}}).rendu.definition(MoteurVideo.LTX23) is grilles.Definition.P1080
