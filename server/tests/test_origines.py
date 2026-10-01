"""Requêtes d'autres origines : une page web quelconque ne doit pas pouvoir piloter MyMaestro (POST, PUT, DELETE...)
depuis le navigateur de l'utilisateur. Les requêtes sans en-tête `Origin` (tests, curl) passent."""

import pytest
from fastapi.testclient import TestClient

from mymaestro import config
from mymaestro.app import creer_app

REFUS = {"detail": "Requête d'une autre origine refusée"}


@pytest.fixture
def client():
    with TestClient(creer_app(":memory:")) as c:
        yield c


def test_post_d_une_autre_origine_refuse(client):
    reponse = client.post("/api/moteurs/annuler", headers={"Origin": "https://exemple.com"})
    assert reponse.status_code == 403 and reponse.json() == REFUS


@pytest.mark.parametrize("methode", ["PUT", "PATCH", "DELETE"])
def test_autres_methodes_d_une_autre_origine_refusees(client, methode):
    reponse = client.request(methode, "/api/moteurs/annuler", headers={"Origin": "https://exemple.com"})
    assert reponse.status_code == 403 and reponse.json() == REFUS


@pytest.mark.parametrize(
    "origine",
    [
        f"http://127.0.0.1:{config.PORT}",
        f"http://localhost:{config.PORT}",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
)
def test_origines_de_l_application_et_de_vite_acceptees(client, origine):
    assert client.post("/api/moteurs/annuler", headers={"Origin": origine}).status_code == 204


def test_origine_avec_un_autre_port_ou_hote_refusee(client):
    for origine in ("http://127.0.0.1:9999", "http://localhost.evil.com", "https://127.0.0.1:3000", "null"):
        assert client.post("/api/moteurs/annuler", headers={"Origin": origine}).status_code == 403, origine


def test_sans_origine_traite(client):
    assert client.post("/api/moteurs/annuler").status_code == 204


def test_get_d_une_autre_origine_traite(client):
    for methode in ("GET", "HEAD", "OPTIONS"):
        reponse = client.request(methode, "/api/moteurs", headers={"Origin": "https://exemple.com"})
        assert reponse.status_code != 403, methode


def test_sec_fetch_site_cross_site_refuse(client):
    reponse = client.post("/api/moteurs/annuler", headers={"Sec-Fetch-Site": "cross-site"})
    assert reponse.status_code == 403 and reponse.json() == REFUS
    assert client.post("/api/moteurs/annuler", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 204
    assert client.get("/api/moteurs", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
