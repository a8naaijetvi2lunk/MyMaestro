import json

import pytest
from fastapi.testclient import TestClient

from mymaestro import __version__
from mymaestro.app import creer_app
from mymaestro.contrat.modeles import FormatImage, MoteurVideo
from mymaestro.core import db
from mymaestro.core.grilles import grille
from mymaestro.exporter_openapi import exporter
from mymaestro.fixtures import demo


@pytest.fixture
def client():
    with TestClient(creer_app(":memory:")) as c:
        yield c


def test_sante(client):
    assert client.get("/api/sante").json() == {"statut": "ok", "version": __version__, "schema_db": len(db.PALIERS)}


def test_liste_des_projets(client):
    projets = client.get("/api/projets").json()
    assert {p["id"] for p in projets} == {demo.PROJET_DEMO, demo.PROJET_VERTICAL}
    assert next(p for p in projets if p["id"] == demo.PROJET_DEMO)["nb_plans"] == 8


def test_projet_demo_conforme_aux_grilles(client):
    projet = client.get(f"/api/projets/{demo.PROJET_DEMO}").json()
    assert len(projet["plans"]) == 8
    for plan in projet["plans"]:
        g = grille(MoteurVideo(plan["moteur_video"]), FormatImage(projet["format"]))
        assert g.est_valide(plan["images"]), plan["id"]
        assert plan["fps"] == g.fps
        assert plan["duree_s"] == pytest.approx(plan["images"] / plan["fps"])
    fin = projet["plans"][-1]["debut_s"] + projet["plans"][-1]["duree_s"]
    assert fin <= demo.DUREE_CHANSON_S


def test_projet_inconnu_404(client):
    reponse = client.get("/api/projets/inconnu")
    assert reponse.status_code == 404
    assert reponse.json()["detail"] == "Projet introuvable"


def test_timeline_plans_chantes_verrouilles(client):
    projet = client.get(f"/api/projets/{demo.PROJET_DEMO}").json()
    roles = {p["id"]: p["role"] for p in projet["plans"]}
    timeline = client.get(f"/api/projets/{demo.PROJET_DEMO}/timeline").json()
    clips_video = [c for c in timeline["clips"] if c["piste"] == "V1"]
    assert len(clips_video) == 8
    for clip in clips_video:
        assert clip["verrou_chanson"] is (roles[clip["plan_id"]] == "chante")
    chanson = next(c for c in timeline["clips"] if c["piste"] == "A0")
    assert chanson["verrou_chanson"] is True
    assert chanson["sortie_s"] == demo.DUREE_CHANSON_S


def test_timeline_projet_sans_timeline_404(client):
    assert client.get(f"/api/projets/{demo.PROJET_VERTICAL}/timeline").status_code == 404


def test_recettes_et_bibliotheque(client):
    recettes = client.get("/api/recettes").json()
    assert recettes[0]["valeurs"]["moteurs_precoches"]["chante"] == MoteurVideo.LTX23.value  # démo : LTX-2.3 en 720p partout
    assert recettes[0]["valeurs"]["rendu"]["ltx23"] == "720p"
    fiches = client.get("/api/bibliotheque").json()
    assert {f["type"] for f in fiches} == {"personnage", "decor", "style"}


def test_export_openapi(tmp_path):
    chemin = exporter(tmp_path / "openapi.json")
    schema = json.loads(chemin.read_text(encoding="utf-8"))
    assert "/api/projets/{projet_id}/timeline" in schema["paths"]
    assert "duree_s" in schema["components"]["schemas"]["Plan"]["properties"]
