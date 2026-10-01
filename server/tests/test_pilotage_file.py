import time

import pytest
from fastapi.testclient import TestClient

from mymaestro.app import creer_app
from mymaestro.connectors.simule import registre_simule
from mymaestro.contrat.modeles import StatutJob, Voie
from mymaestro.core import empreintes
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.core.ordonnanceur import Ordonnanceur


@pytest.fixture
def client():
    with TestClient(creer_app(":memory:", connecteurs=registre_simule(empreintes.DEFAUTS))) as c:
        yield c


def _echouer_deux_fois(file, job_id):
    for _ in range(2):
        file.demarrer(job_id)
        file.echouer(job_id, "panne")


def test_relance_d_un_job_en_echec():
    base = Base(":memory:")
    file = File(base)
    job = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    _echouer_deux_fois(file, job)
    assert file.relancer(job) is True
    lu = file.lire(job)
    assert (lu.statut, lu.tentatives, lu.erreur) == (StatutJob.EN_FILE, 0, None)
    assert file.relancer(job) is False
    base.fermer()


def test_la_pause_retient_les_jobs():
    base = Base(":memory:")
    ordonnanceur = Ordonnanceur(File(base), registre_simule(empreintes.DEFAUTS), pause_s=0.01)
    ordonnanceur.lancer()
    ordonnanceur.mettre_en_pause()
    assert ordonnanceur.fils_actifs and not ordonnanceur.en_marche
    job = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx")
    time.sleep(0.2)
    assert ordonnanceur.file.lire(job).statut is StatutJob.EN_FILE
    ordonnanceur.lancer()
    assert ordonnanceur.en_marche
    limite = time.monotonic() + 5
    while time.monotonic() < limite and ordonnanceur.file.lire(job).statut is not StatutJob.TERMINE:
        time.sleep(0.02)
    ordonnanceur.arreter()
    assert ordonnanceur.file.lire(job).statut is StatutJob.TERMINE
    base.fermer()


def test_routes_de_pause_et_de_reprise(client):
    assert client.post("/api/file/reprendre").json()["en_marche"] is True
    etat = client.post("/api/file/pause").json()
    assert etat["en_marche"] is False
    assert etat["vram_totale_mo"] == 12282
    assert all(c["simule"] for c in etat["connecteurs"] if c["nom"] != "export")  # l'export ffmpeg local est réel


def test_relance_et_annulation_par_l_api(client):
    file = client.app.state.file
    job = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    _echouer_deux_fois(file, job)
    assert client.post(f"/api/file/jobs/{job}/relancer").json()["statut"] == "en_file"
    assert client.post(f"/api/file/jobs/{job}/relancer").status_code == 409
    assert client.post(f"/api/file/jobs/{job}/annuler").json()["statut"] == "annule"
    assert client.post(f"/api/file/jobs/{job}/annuler").status_code == 409
    assert client.post("/api/file/jobs/inconnu/relancer").status_code == 404
