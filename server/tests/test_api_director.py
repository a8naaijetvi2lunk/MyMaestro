import io
import wave

import pytest
from fastapi.testclient import TestClient

from mymaestro import modules
from mymaestro.app import creer_app
from mymaestro.connectors.simule import registre_simule
from mymaestro.core import empreintes
from mymaestro.fixtures import demo
from mymaestro.outils import ffmpeg


def _wav(secondes: float = 2.0) -> bytes:
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(8000)
        sortie.writeframes(b"\x00\x00" * int(8000 * secondes))
    return tampon.getvalue()


def _ffprobe_disponible() -> bool:
    try:
        ffmpeg.trouver("ffprobe")
        return True
    except FileNotFoundError:
        return False


@pytest.fixture
def client(tmp_path):
    projets = tmp_path / "projets"
    app = creer_app(
        ":memory:", dossier_medias=tmp_path / "medias", dossier_projets=projets,
        connecteurs=registre_simule(empreintes.DEFAUTS, repondeur=modules.repondeur_simule(projets)),
    )
    with TestClient(app) as c:
        yield c


def _creer(client, **surcharges):
    corps = {"titre": "Derrière la vitre", "format": "16:9", "recette_id": demo.RECETTE_DEMO, "paroles": "Un\nDeux", "casting": ["fiche-lina"]}
    corps.update(surcharges)
    return client.post("/api/projets", json=corps)


def test_creation_et_refus(client):
    reponse = _creer(client)
    assert reponse.status_code == 201
    projet = reponse.json()
    assert projet["etat_phases"]["creation"] == "en_cours" and projet["casting"] == ["fiche-lina"]
    assert _creer(client, recette_id="inconnue").status_code == 422
    assert _creer(client, casting=["fiche-inconnue"]).status_code == 422
    assert _creer(client, casting=["fiche-lina", "fiche-lina"]).json()["casting"] == ["fiche-lina"]
    assert client.get(f"/api/projets/{projet['id']}/director").json()["concepts"] == []


@pytest.mark.skipif(not _ffprobe_disponible(), reason="ffprobe introuvable")
def test_chanson_televersee(client, tmp_path):
    projet_id = _creer(client).json()["id"]
    url = f"/api/projets/{projet_id}/chanson"
    reponse = client.put(url, content=_wav(2.0), headers={"Content-Type": "audio/wav"})
    assert reponse.status_code == 200
    projet = reponse.json()
    assert projet["chanson"] == "chanson.wav" and projet["duree_chanson_s"] == pytest.approx(2.0, abs=0.05)
    assert projet["etat_phases"]["creation"] == "termine"
    assert (tmp_path / "projets" / projet_id / "chanson.wav").is_file()
    assert client.put(url, content=b"texte", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.put(url, content=b"pas un son", headers={"Content-Type": "audio/mpeg"}).status_code == 422
    # Un renvoi illisible de même type ne détruit pas la chanson en place.
    assert client.put(url, content=b"pas un son", headers={"Content-Type": "audio/wav"}).status_code == 422
    assert (tmp_path / "projets" / projet_id / "chanson.wav").is_file()
    assert client.get(f"/api/projets/{projet_id}").json()["chanson"] == "chanson.wav"


def test_parcours_par_l_api(client):
    projet_id = _creer(client).json()["id"]
    contexte = client.app.state.contexte
    from mymaestro.modules.director_musique import phases

    phases.televerser_fini(contexte, projet_id, "chanson.wav", 40.0)  # sans ffprobe : chanson déclarée directement
    ordonnanceur = client.app.state.ordonnanceur
    assert client.post(f"/api/projets/{projet_id}/phases/prompts/lancer").status_code == 409
    client.post(f"/api/projets/{projet_id}/phases/analyse/lancer")
    ordonnanceur.vider()
    client.put(f"/api/projets/{projet_id}/ecriture/brief", json={"ambiance": "Nuit", "genre": "Pop", "envies": ""})
    client.post(f"/api/projets/{projet_id}/ecriture/concepts")
    ordonnanceur.vider()
    assert len(client.get(f"/api/projets/{projet_id}/director").json()["concepts"]) == 3
    assert client.post(f"/api/projets/{projet_id}/ecriture/concepts/9/retenir").status_code == 409
    client.post(f"/api/projets/{projet_id}/ecriture/concepts/0/retenir")
    etat = client.post(f"/api/projets/{projet_id}/ecriture/chat", json={"texte": "Plus de pluie"}).json()
    assert etat["chat"][0]["auteur"] == "utilisateur" and "ecriture.chat" in etat["en_attente"]
    ordonnanceur.vider()
    client.post(f"/api/projets/{projet_id}/ecriture/decoupage")
    ordonnanceur.vider()
    projet = client.get(f"/api/projets/{projet_id}").json()
    assert projet["etat_phases"]["ecriture"] == "a_valider" and projet["plans"]
    compat = client.get(f"/api/projets/{projet_id}/compatibilites").json()
    assert set(compat) == {p["id"] for p in projet["plans"]}
    client.post(f"/api/projets/{projet_id}/phases/ecriture/valider")
    ordonnanceur.vider()
    plan = projet["plans"][0]
    modifie = client.patch(f"/api/projets/{projet_id}/plans/{plan['id']}", json={"prompt_video": "Already moving, rain"})
    assert modifie.json()["prompt_video"] == "Already moving, rain"
    assert client.patch(f"/api/projets/{projet_id}/plans/inconnu", json={}).status_code == 404
    client.post(f"/api/projets/{projet_id}/phases/prompts/valider")
    ordonnanceur.vider()
    projet = client.get(f"/api/projets/{projet_id}").json()
    image = projet["plans"][0]["image_depart"]
    assert client.get(f"/api/projets/{projet_id}/medias/{image}").content.startswith(b"\x89PNG")
    assert client.get(f"/api/projets/{projet_id}/medias/..%2F..%2Fsecret").status_code == 404
    client.post(f"/api/projets/{projet_id}/plans/{plan['id']}/image/refaire")
    ordonnanceur.vider()
    assert client.get(f"/api/projets/{projet_id}").json()["plans"][0]["image_depart"] != image
    assert client.post(f"/api/projets/{projet_id}/phases/images/valider").json()["etat_phases"]["video"] == "a_faire"
    assert "codex" in {c["nom"] for c in client.get("/api/file").json()["connecteurs"]}


def test_chanson_verrouillee_une_fois_l_analyse_lancee(client):
    from mymaestro.modules.director_musique import phases

    projet_id = _creer(client).json()["id"]
    phases.televerser_fini(client.app.state.contexte, projet_id, "chanson.wav", 40.0)
    client.post(f"/api/projets/{projet_id}/phases/analyse/lancer")
    reponse = client.put(f"/api/projets/{projet_id}/chanson", content=b"RIFF", headers={"Content-Type": "audio/wav"})
    assert reponse.status_code == 409 and "verrouillée" in reponse.json()["detail"]


def test_casting_modifiable_par_l_api(client):
    projet_id = _creer(client, casting=[]).json()["id"]
    assert client.put(f"/api/projets/{projet_id}/casting", json={"casting": ["fiche-lina"]}).json()["casting"] == ["fiche-lina"]
    assert client.get(f"/api/projets/{projet_id}").json()["casting"] == ["fiche-lina"]
    refus = client.put(f"/api/projets/{projet_id}/casting", json={"casting": ["fiche-absente"]})
    assert refus.status_code == 409 and "fiche-absente" in refus.json()["detail"]
    assert client.put("/api/projets/inconnu/casting", json={"casting": []}).status_code == 404
    assert client.patch(f"/api/projets/{projet_id}/plans/inconnu", json={"fiches": []}).status_code == 404
