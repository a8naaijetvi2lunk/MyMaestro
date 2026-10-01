import subprocess

import pytest
from fastapi.testclient import TestClient

from mymaestro import config
from mymaestro.app import creer_app
from mymaestro.outils import gpu
from mymaestro.outils.gpu import Gpu, lire_sortie_nvidia_smi
from mymaestro.outils.gpu import detecter_gpu as detecter_origine  # la fixture autouse remplace gpu.detecter_gpu
from mymaestro.outils.gpu import detecter_sans_cache


def test_lecture_de_la_sortie_nvidia_smi():
    carte = lire_sortie_nvidia_smi("NVIDIA GeForce RTX 4070 Ti, 12282\n")
    assert carte is not None
    assert carte.nom == "NVIDIA GeForce RTX 4070 Ti"
    assert carte.vram_mo == 12282
    assert carte.vram_go == 12.0


def test_deux_cartes_rendent_la_premiere():
    carte = lire_sortie_nvidia_smi("NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 3060, 12288\n")
    assert carte is not None
    assert carte.nom == "NVIDIA GeForce RTX 4090"
    assert carte.vram_mo == 24564


@pytest.mark.parametrize("texte", ["", "\n", "pas de carte", "NVIDIA, abc"])
def test_sortie_illisible(texte):
    assert lire_sortie_nvidia_smi(texte) is None


def test_vram_go_arrondie_au_dixieme():
    assert Gpu("RTX 4090", 24564, "nvidia-smi").vram_go == 24.0


def test_vram_forcee_par_la_config(monkeypatch):
    monkeypatch.setenv("MYMAESTRO_VRAM_MO", "8192")
    carte = detecter_sans_cache()
    assert carte is not None
    assert carte.source == "config"
    assert carte.vram_mo == 8192


@pytest.mark.parametrize("valeur", ["16 Go", "0", "16", "auto"])
def test_vram_forcee_invalide_retombe_sur_nvidia_smi(monkeypatch, caplog, valeur):
    monkeypatch.setenv("MYMAESTRO_VRAM_MO", valeur)
    config._AVERTISSEMENTS_EMIS.clear()

    def faux_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="NVIDIA GeForce RTX 4090, 24564\n", stderr="")

    monkeypatch.setattr(subprocess, "run", faux_run)
    with caplog.at_level("WARNING"):
        carte = detecter_sans_cache()
    assert carte is not None
    assert carte.source == "nvidia-smi"
    assert carte.vram_mo == 24564
    assert "ignoré" in caplog.text


def test_nvidia_smi_introuvable(monkeypatch):
    monkeypatch.delenv("MYMAESTRO_VRAM_MO", raising=False)

    def absent(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "run", absent)
    assert detecter_sans_cache() is None


def test_detection_ratee_n_est_pas_mise_en_cache(monkeypatch):
    monkeypatch.delenv("MYMAESTRO_VRAM_MO", raising=False)
    sorties = iter([None, subprocess.CompletedProcess([], 0, stdout="NVIDIA GeForce RTX 4090, 24564\n", stderr="")])

    def faux_run(*args, **kwargs):
        sortie = next(sorties)
        if sortie is None:
            raise FileNotFoundError("nvidia-smi")
        return sortie

    monkeypatch.setattr(subprocess, "run", faux_run)
    gpu.vider_cache()
    try:
        assert detecter_origine() is None
        carte = detecter_origine()
        assert carte is not None and carte.vram_mo == 24564
        assert detecter_origine() is carte  # un résultat non nul, lui, est mémorisé (pas de troisième appel à nvidia-smi)
    finally:
        gpu.vider_cache()


def test_repli_sans_detection(monkeypatch):
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: None)
    assert gpu.vram_mo() == gpu.VRAM_REPLI_MO
    assert gpu.vram_go() == 12.0


@pytest.fixture
def client():
    with TestClient(creer_app(":memory:")) as c:
        yield c


def test_route_materiel_carte_de_reference(client):
    corps = client.get("/api/materiel").json()
    assert corps["gpu"] == "NVIDIA GeForce RTX 4070 Ti"
    assert corps["vram_go"] == 12.0
    assert corps["source"] == "nvidia-smi"
    assert corps["suffisant"] is True
    assert corps["avertissement"] is None


def test_route_materiel_carte_de_8_go(client, monkeypatch):
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: Gpu("NVIDIA GeForce RTX 3070", 8192, "nvidia-smi"))
    corps = client.get("/api/materiel").json()
    assert corps["suffisant"] is False
    assert corps["vram_go"] == 8.0
    assert "8,0 Go" in corps["avertissement"]
    assert "moins que les 12 Go recommandés" in corps["avertissement"]


def test_route_materiel_sans_detection(client, monkeypatch):
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: None)
    corps = client.get("/api/materiel").json()
    assert corps["gpu"] is None
    assert corps["source"] == "repli"
    assert corps["suffisant"] is True
    assert "non détectée" in corps["avertissement"]


def test_route_materiel_carte_de_12_go_a_11_9(client, monkeypatch):
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: Gpu("NVIDIA GeForce RTX 5070", 12227, "nvidia-smi"))
    corps = client.get("/api/materiel").json()
    assert corps["vram_go"] == 11.9
    assert corps["suffisant"] is True
    assert corps["avertissement"] is None


def test_route_materiel_carte_de_11_go_insuffisante(client, monkeypatch):
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: Gpu("NVIDIA GeForce RTX 2080 Ti", 11264, "nvidia-smi"))
    corps = client.get("/api/materiel").json()
    assert corps["suffisant"] is False
    assert "moins que les 12 Go recommandés" in corps["avertissement"]


def test_ordonnanceur_carte_de_reference(client):
    assert client.app.state.ordonnanceur.vram_totale_mo == 12282


def test_ordonnanceur_carte_de_24_go(monkeypatch):
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: Gpu("NVIDIA GeForce RTX 4090", 24564, "nvidia-smi"))
    with TestClient(creer_app(":memory:")) as c:
        assert c.app.state.ordonnanceur.vram_totale_mo == 24564
