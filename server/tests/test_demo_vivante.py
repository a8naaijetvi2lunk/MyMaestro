"""La démo vivante : brief, concepts, chat et prompts amorcés, médias générés sans dépendance."""

import struct
import wave
import zlib

import pytest

from mymaestro.core import amorce, depot
from mymaestro.core.db import Base
from mymaestro.fixtures import demo, medias_demo


@pytest.fixture
def base():
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    yield base
    base.fermer()


def test_ecriture_amorcee_pour_la_demo(base):
    with base.transaction() as cx:
        ecriture = depot.lire_donnees_module(cx, demo.PROJET_DEMO)["ecriture"]
        vertical = depot.lire_donnees_module(cx, demo.PROJET_VERTICAL)["ecriture"]
    assert ecriture["brief"]["ambiance"] == "Nuit urbaine humide, néons magenta et cyan, mélancolie lumineuse"
    assert ecriture["brief"]["genre"] == "Pop électronique, 118 BPM"
    assert ecriture["brief"]["envies"].startswith("Plans chantés face caméra sur le toit")
    assert [c["titre"] for c in ecriture["concepts"]] == ["Toit sous la pluie", "Dernier métro", "Néons jusqu'à l'aube"]
    assert all(c["pitch"].count(".") >= 2 for c in ecriture["concepts"])
    assert ecriture["concept_retenu"] == 0
    assert [m["auteur"] for m in ecriture["chat"]] == ["utilisateur", "opus"]
    assert ecriture["chat"][0]["texte"] == "Plus de reflets dans les flaques sur les coupes"
    assert vertical["brief"]["ambiance"]


def test_casting_et_chanson_de_la_demo(base):
    with base.transaction() as cx:
        projet = depot.lire_projet(cx, demo.PROJET_DEMO)
    assert projet.casting == ["fiche-lina", "fiche-toit", "fiche-neon"]
    assert projet.chanson == "chanson.wav" and projet.duree_chanson_s == demo.DUREE_CHANSON_S


def test_les_huit_plans_ont_leurs_prompts(base):
    with base.transaction() as cx:
        plans = depot.lire_projet(cx, demo.PROJET_DEMO).plans
    assert len(plans) == 8
    for plan in plans:
        assert plan.prompt_image and plan.prompt_video and plan.prompt_son
    assert plans[0].prompt_video.startswith("Slow lateral tracking shot along a rain-soaked street at night")
    assert plans[0].prompt_son == "Rain on asphalt, distant traffic hum"


def _png(chemin):
    octets = chemin.read_bytes()
    assert octets[:8] == b"\x89PNG\r\n\x1a\n"
    largeur, hauteur, profondeur, type_couleur = struct.unpack(">IIBB", octets[16:26])
    assert octets[12:16] == b"IHDR" and (profondeur, type_couleur) == (8, 2)
    assert octets[-12:] == b"\x00\x00\x00\x00IEND\xaeB`\x82"
    return largeur, hauteur


def test_png_degrade_valide(tmp_path):
    chemin = tmp_path / "a.png"
    medias_demo.ecrire_png_degrade(chemin, 96, 54, (10, 10, 60), (200, 20, 160))
    assert _png(chemin) == (96, 54)
    octets = chemin.read_bytes()
    debut = octets.index(b"IDAT")
    taille = struct.unpack(">I", octets[debut - 4 : debut])[0]
    brut = zlib.decompress(octets[debut + 4 : debut + 4 + taille])
    assert len(brut) == 54 * (1 + 96 * 3)
    haut = brut[1:4]
    bas = brut[53 * (1 + 96 * 3) + 1 + 48 * 3 :][:3]
    assert haut != bas


def test_chanson_wav_valide(tmp_path):
    chemin = tmp_path / "chanson.wav"
    medias_demo.ecrire_chanson_wav(chemin, duree_s=2.0)
    with wave.open(str(chemin)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 22050)
        assert w.getnframes() == 2 * 22050
        trames = w.readframes(w.getnframes())
    pic = max(abs(v) for v in struct.unpack(f"<{len(trames) // 2}h", trames))
    assert 0 < pic <= 32768 * 0.5012  # -6 dBFS


def test_amorcage_ecrit_les_medias_sans_ecraser(tmp_path):
    base = Base(":memory:")
    existant = tmp_path / demo.PROJET_DEMO / "images" / "plan-03.png"
    existant.parent.mkdir(parents=True)
    existant.write_bytes(b"deja la")
    assert amorce.amorcer_si_vide(base, tmp_path) is True
    chanson = tmp_path / demo.PROJET_DEMO / "chanson.wav"
    with wave.open(str(chanson)) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(demo.DUREE_CHANSON_S, abs=0.01)
    for plan in demo.plans_demo():
        chemin = tmp_path / demo.PROJET_DEMO / plan.image_depart
        if plan.indice == 3:
            assert chemin.read_bytes() == b"deja la"
        else:
            assert _png(chemin) == (960, 544)
    base.fermer()


def test_amorcage_ecrit_les_images_de_la_bibliotheque(tmp_path):
    base = Base(":memory:")
    medias = tmp_path / "medias"
    amorce.amorcer_si_vide(base, tmp_path / "projets", medias)
    for fiche in demo.fiches_demo():
        for image in fiche.images:
            assert _png(medias / image.chemin) == (640, 480)
    base.fermer()


def test_sans_dossier_projets_rien_n_est_ecrit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    assert list(tmp_path.iterdir()) == []
    base.fermer()
