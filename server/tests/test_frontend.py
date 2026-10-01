from fastapi.testclient import TestClient

from mymaestro import config
from mymaestro.app import creer_app

HTML = {"accept": "text/html,application/xhtml+xml"}


def test_interface_servie_avec_repli_spa(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root"></div><title>MyMaestro</title>', encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(config, "DOSSIER_UI", dist)
    with TestClient(creer_app(":memory:", servir_ui=True)) as client:
        assert client.get("/", headers=HTML).status_code == 200
        assert "MyMaestro" in client.get("/projets/demo-nuit-blanche", headers=HTML).text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/sante").json()["statut"] == "ok"


def test_sans_interface_par_defaut():
    with TestClient(creer_app(":memory:")) as client:
        assert client.get("/", headers=HTML).status_code == 404
