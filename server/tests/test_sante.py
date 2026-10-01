from fastapi.testclient import TestClient

from mymaestro import __version__
from mymaestro.app import creer_app
from mymaestro.core import db


def test_sante_repond_ok_avec_la_version_du_schema():
    with TestClient(creer_app(":memory:")) as client:
        reponse = client.get("/api/sante")
    assert reponse.status_code == 200
    assert reponse.json() == {"statut": "ok", "version": __version__, "schema_db": len(db.PALIERS)}
